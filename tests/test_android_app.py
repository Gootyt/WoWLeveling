"""A telefonos alkalmazás Kivy-felületének (android/app/main.py) tesztjei, a játék és a telefon
nélkül: a képernyők, a szerkesztés, a vissza gomb és a szinkronizálás a Firebase-utánzattal. Csak
akkor futnak, ha a Kivy telepítve van, és van grafikus kijelző (Linuxon pl. xvfb-run)."""

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

import cloud_sync
import storage
from leveling import Character, LevelingData, Settings, load_data, save_data

try:
    import fake_firebase
except ImportError:  # python -m unittest tests.test_android_app
    from tests import fake_firebase

APP_DIR = Path(__file__).resolve().parent.parent / "android" / "app"
sys.path.append(str(APP_DIR))  # a mobile_plan (a gyökérben lévő közös modulok maradnak elöl)
import mobile_plan  # noqa: E402

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_LOG_MODE", "PYTHON")  # a Kivy ne vegye át a sys.stderr-t (ott a teszt eredménye)
try:
    import kivy  # noqa: F401
except ImportError:
    kivy = None

D = Decimal


def load_app_module():
    spec = importlib.util.spec_from_file_location("android_main", APP_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def buttons(widget, text):
    """A widget alatti, adott feliratú gombok."""
    from kivy.uix.button import Button

    return [child for child in widget.walk() if isinstance(child, Button) and child.text == text]


@unittest.skipIf(kivy is None or not os.environ.get("DISPLAY"), "a Kivy nincs telepítve, vagy nincs kijelző")
class AndroidAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("KIVY_HOME", tempfile.mkdtemp())
        cls.main = load_app_module()
        from kivy.base import EventLoop

        EventLoop.ensure_window()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = Path(folder.name) / storage.DB_NAME
        today = date.today()
        settings = Settings(today - timedelta(days=5), today + timedelta(days=5), today + timedelta(days=15), D(80), D(90))
        characters = [
            Character("Thrall", "Shaman", "Enhancement", D("83.45"), realm="Draenor", uid="thrall1"),
            Character("Jaina", "Mage", "Frost", D("81.00"), uid="jaina22"),
        ]
        save_data(self.database, LevelingData(settings, characters, look_ahead=False))
        self.fake = fake_firebase.FakeFirebase()
        self.addCleanup(self.fake.close)

    def start(self):
        from kivy.app import App
        from kivy.lang import global_idmap

        # A KV-szabályok „app”-ja az első alkalmazást jegyzi meg (és csak annak leállásakor felejti el):
        # ez a teszt alkalmazása legyen, különben a gombjai egy korábbi tesztét hívnák.
        object.__setattr__(global_idmap["app"], "_obj", None)
        with mock.patch.multiple(cloud_sync, AUTH_URL=f"{self.fake.url}/v1/accounts", TOKEN_URL=f"{self.fake.url}/v1/token"):
            app = self.main.WowApp(database=self.database)
            app.build()
        App._running_app = app  # mint az app.run()-ban (a kártyák ebből érik el)
        self.addCleanup(app.sync.close)
        return app

    def pump(self, condition, what, timeout=5.0):
        from kivy.clock import Clock

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            Clock.tick()
            if condition():
                return
            time.sleep(0.02)
        self.fail(f"nem történt meg: {what}")

    def titles(self, app):
        return [card.title for card in app.list_screen.ids.cards.children[::-1]]

    def test_list_and_editing(self):
        app = self.start()
        cards = app.list_screen.ids.cards.children[::-1]  # alapból az állapot szerint (itt ugyanaz a sorrend)
        self.assertEqual([card.title for card in cards], ["1. Thrall (Draenor)", "2. Jaina"])
        self.assertIn("2 karakter", app.list_screen.ids.summary.text)
        # Koppintás egy kártyára: a szerkesztő; a vissza gomb a listára visz.
        cards[1].dispatch("on_release")
        self.assertEqual((app.manager.current, app.form_screen.ids.title.text), ("form", "Jaina"))
        app.fields["level"].text = "sok"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        self.assertTrue(app.message.text.startswith("Szint: "), app.message.text)
        self.assertEqual(app.manager.current, "form")  # a hibás szint nem került be
        app.fields["level"].text = "82,4"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        self.assertEqual((app.manager.current, load_data(self.database).characters[1].level), ("list", D("82.40")))
        # Új karakter (a lista végére), átrendezés a szerkesztőben és törlés (megerősítéssel).
        buttons(app.list_screen, "+ Új karakter")[0].dispatch("on_release")
        self.assertNotIn("position", app.fields)
        app.fields["name"].text = "Uther"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        uther = app.data.characters[-1]
        self.assertEqual((uther.name, uther.level), ("Uther", D(80)))
        app.edit_character(uther.uid)
        self.assertEqual(app.fields["position"].text, "3")
        app.fields["position"].text = "4"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        self.assertEqual(app.message.text, "Hely a tervben: A hely 1 és 3 között lehet.")
        app.fields["position"].text = "2"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        self.assertEqual(app.manager.current, "list")
        self.assertEqual([c.name for c in load_data(self.database).characters], ["Thrall", "Uther", "Jaina"])
        app.edit_character("thrall1")
        buttons(app.form_screen, "Törlés")[0].dispatch("on_release")
        buttons(app.popup.content, "Törlés")[0].dispatch("on_release")
        self.assertEqual([c.name for c in load_data(self.database).characters], ["Uther", "Jaina"])
        # Ha a hely mezőjéhez nem nyúlt, a közben (a másik eszközön) módosított sorrend marad.
        app.edit_character("jaina22")
        self.assertEqual(app.fields["position"].text, "2")
        app.data.characters.reverse()  # a szinkronizálásból: Jaina lett az első
        app.fields["level"].text = "82,5"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        self.assertEqual([(c.name, c.level) for c in app.data.characters], [("Jaina", D("82.50")), ("Uther", D(80))])
        app.edit_character("jaina22")
        self.assertTrue(app._on_key(None, 27))  # az Android vissza gombja
        self.assertEqual(app.manager.current, "list")
        self.assertFalse(app._on_key(None, 27))  # a listán: kilép (az Android dönt)

    def test_sorting(self):
        app = self.start()
        ids = app.list_screen.ids
        self.assertEqual((ids.sort.text, ids.reverse.state), ("Állapot", "normal"))  # elöl a legsürgősebb
        self.assertEqual(ids.sort.values, list(mobile_plan.SORTS.values()))
        ids.sort.text = "Név"
        self.assertEqual(self.titles(app), ["2. Jaina", "1. Thrall (Draenor)"])
        ids.reverse.state = "down"
        self.assertEqual(self.titles(app), ["1. Thrall (Draenor)", "2. Jaina"])
        self.assertEqual(mobile_plan.load_sort(self.database), ("name", True))
        # Átrendezni bármelyik rendezésben lehet; a cím a terv szerinti új helyet mutatja.
        app.edit_character("jaina22")
        app.fields["position"].text = "1"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        self.assertEqual(self.titles(app), ["2. Thrall (Draenor)", "1. Jaina"])
        self.assertEqual(mobile_plan.load_sort(self.database), ("name", True))  # a rendezés marad
        # A választás a következő indításkor is megmarad: a telefon saját beállítása, nem a tervé (nem szinkronizálódik).
        ids.sort.text = "Itemlevel"
        ids.reverse.state = "normal"
        again = self.start().list_screen.ids
        self.assertEqual((again.sort.text, again.reverse.state), ("Itemlevel", "normal"))
        view = json.loads(storage.read_document(self.database, storage.PHONE_VIEW))
        self.assertEqual(view, {"sort": "item_level", "descending": False})

    def test_order_screen(self):
        app = self.start()
        app.list_screen.ids.sort.text = "Név"  # a lista rendezésétől független
        buttons(app.list_screen, "Sorrend")[0].dispatch("on_release")
        self.assertEqual(app.manager.current, "order")
        ids = app.order_screen.ids

        def rows():
            return ids.rows.children[::-1]

        self.assertEqual([row.title for row in rows()], ["1. Thrall (Draenor)", "2. Jaina"])
        self.assertIn("céldátum: ", rows()[1].subtitle)
        self.assertTrue(ids.up.disabled and ids.down.disabled)  # még nincs kijelölve senki
        rows()[1].dispatch("on_release")  # Jaina kijelölése
        self.assertEqual([row.chosen for row in rows()], [False, True])
        self.assertFalse(ids.up.disabled)
        self.assertTrue(ids.down.disabled)  # az utolsót nem lehet lejjebb vinni
        jaina_deadline = rows()[1].subtitle.rsplit(" ", 1)[1]
        ids.up.dispatch("on_release")
        self.assertEqual([c.name for c in load_data(self.database).characters], ["Jaina", "Thrall"])  # azonnal mentve
        self.assertEqual([row.title for row in rows()], ["1. Jaina", "2. Thrall (Draenor)"])
        self.assertEqual([row.chosen for row in rows()], [True, False])  # a kijelölés vele megy
        self.assertTrue(rows()[1].subtitle.endswith(jaina_deadline))  # Thrall kapta az ő céldátumát
        self.assertTrue(ids.up.disabled)
        self.assertFalse(ids.down.disabled)
        ids.up.dispatch("on_release")  # az elsőt már nem viszi feljebb
        self.assertEqual([c.name for c in app.data.characters], ["Jaina", "Thrall"])
        # Ha közben a gépről jön változás (itt: egy új karakter), a képernyő frissül, a kijelölés marad.
        app.data.characters.append(Character("Uther", uid="uther9"))
        app._remote_changed()
        self.assertEqual([row.title for row in rows()], ["1. Jaina", "2. Thrall (Draenor)", "3. Uther"])
        rows()[2].dispatch("on_release")
        ids.up.dispatch("on_release")
        self.assertEqual([c.name for c in app.data.characters], ["Jaina", "Uther", "Thrall"])
        # A vissza gomb a listára visz, amely a rendezését megtartja, a címekben az új helyekkel.
        self.assertTrue(app._on_key(None, 27))
        self.assertEqual(app.manager.current, "list")
        self.assertEqual(self.titles(app), ["1. Jaina", "3. Thrall (Draenor)", "2. Uther"])

    def test_plan_settings(self):
        app = self.start()
        app.open_plan()
        app.fields["target_level"].text = "70"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        self.assertEqual(app.manager.current, "form")  # a célszint nem lehet a kezdőszint alatt
        app.fields["target_level"].text = "91"
        buttons(app.form_screen, "Egymás után")[0].state = "down"
        buttons(app.form_screen, "Párhuzamosan")[0].state = "normal"
        buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        saved = load_data(self.database)
        self.assertEqual((saved.settings.target_level, saved.settings.mode), (D(91), "sequential"))

    def test_sync_with_the_desktop(self):
        # A gépi program (itt egy SyncEngine) már feltöltötte a tervét, egy másik karakterrel.
        client = self.fake.client()
        client.sign_up("gamer@example.com", "titok123")
        pc = cloud_sync.SyncEngine(client, device="PC")
        pc_data = LevelingData(Settings.default(), [Character("Anduin", "Priest", "Holy", D("85.00"), uid="anduin5")])
        pc.sync(cloud_sync.shared_part(pc_data))
        app = self.start()
        app.sync_now()  # bejelentkezés nélkül a fiók képernyője nyílik meg
        self.assertEqual(app.form_screen.ids.title.text, "Szinkronizálás (Firebase)")
        self.assertIn("Web API-kulcsát", app.account_status.text)
        app.fields["api_key"].text = fake_firebase.API_KEY
        app.fields["database_url"].text = "https://wow-default-rtdb.europe-west1.firebasedatabase.app"
        app.fields["email"].text = "gamer@example.com"
        app.fields["password"].text = "titok123"
        with mock.patch.object(cloud_sync, "normalize_database_url", lambda text: f"{self.fake.url}/db"):
            buttons(app.form_screen, "Bejelentkezés")[0].dispatch("on_release")
        self.assertEqual(app.fields["password"].text, "")  # a jelszót nem tartja meg
        # A telefonon is van terv: megkérdezi, melyik maradjon.
        self.pump(lambda: getattr(app, "popup", None) is not None and app.popup.title == "Melyik terv maradjon?", "a kérdés")
        buttons(app.popup.content, "A felhőbeli maradjon")[0].dispatch("on_release")
        self.pump(lambda: [c.name for c in app.data.characters] == ["Anduin"], "a felhőbeli terv átvétele")
        app.show_list()
        self.assertEqual(app.list_screen.ids.cards.children[0].title, "1. Anduin")
        self.assertIn("Szinkronizálva:", app.status_text)
        # A telefonon átírt szint kicsit később felmegy; a gépi program megkapja.
        app.edit_character("anduin5")
        app.fields["level"].text = "86"
        with mock.patch.object(cloud_sync, "PUSH_DELAY_MS", 0):
            buttons(app.form_screen, "Mentés")[0].dispatch("on_release")
        uid = client.account.uid
        self.pump(lambda: json.loads(self.fake.plan(uid)["data"])["characters"][0]["level"] == 86.0, "a feltöltés")
        incoming = pc.sync(cloud_sync.shared_part(pc_data))
        self.assertEqual(incoming["characters"][0]["level"], 86.0)
        self.assertEqual(self.fake.plan(uid)["device"], "Telefon")


if __name__ == "__main__":
    unittest.main()
