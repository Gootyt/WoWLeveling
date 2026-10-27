"""A szinkronizálás (cloud_sync.py) tesztjei: az összefésülés, a Firebase-kliens, és két eszköz
(a gép és a telefon) szinkronizálása egy Firebase-utánzaton (fake_firebase.py) át – hálózat nélkül."""

import copy
import heapq
import json
import socket
import tempfile
import time
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

import cloud_sync
import storage
from cloud_sync import AuthError, ChoiceNeeded, SyncController, SyncEngine, SyncError, apply_shared, merge, shared_part
from leveling import Character, LevelingData, Settings, SpecScores

try:
    import fake_firebase
except ImportError:  # python -m unittest tests.test_cloud_sync
    from tests import fake_firebase

D = Decimal


def sample() -> LevelingData:
    settings = Settings(date(2026, 10, 1), date(2026, 10, 15), date(2026, 11, 30), D(80), D(90))
    characters = [
        Character("Thrall", "Shaman", "Enhancement", D("83.45"), realm="Draenor", uid="thrall1"),
        Character("Jaina", "Mage", "Frost", D("81.00"), realm="Draenor", uid="jaina22"),
    ]
    return LevelingData(settings, characters, SpecScores({"mage/frost": D(3600)}, datetime(2026, 10, 20, 10)))


def character(shared: dict, uid: str) -> dict:
    return next(item for item in shared["characters"] if item["id"] == uid)


def new_character(name: str, uid: str) -> dict:
    return Character(name, "Paladin", "Holy", D("80.00"), uid=uid).to_dict()


def ids(shared: dict) -> list:
    return [item["id"] for item in shared["characters"]]


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.base = shared_part(sample())
        self.local, self.remote = copy.deepcopy(self.base), copy.deepcopy(self.base)

    def test_changes_on_one_side_come_through(self):
        character(self.local, "thrall1")["level"] = 84.1
        self.remote["settings"]["target_level"] = 91.0
        character(self.remote, "jaina22")["item_level"] = 300.5
        merged = merge(self.base, self.local, self.remote)
        self.assertEqual(character(merged, "thrall1")["level"], 84.1)
        self.assertEqual(merged["settings"]["target_level"], 91.0)
        self.assertEqual(character(merged, "jaina22")["item_level"], 300.5)
        self.assertEqual(merge(self.base, self.base, self.remote), self.remote)  # itt nem változott semmi
        self.assertEqual(merge(self.base, self.local, self.base), self.local)

    def test_same_field_on_both_sides_keeps_the_local(self):
        character(self.local, "thrall1")["level"] = 84.1
        character(self.remote, "thrall1")["level"] = 85.0
        character(self.remote, "thrall1")["spec"] = "Elemental"  # más mező: átjön
        merged = merge(self.base, self.local, self.remote)
        self.assertEqual((character(merged, "thrall1")["level"], character(merged, "thrall1")["spec"]), (84.1, "Elemental"))

    def test_added_and_deleted_characters(self):
        self.local["characters"].append(new_character("Uther", "uther33"))
        self.remote["characters"].append(new_character("Arthas", "arthas4"))
        merged = merge(self.base, self.local, self.remote)
        self.assertEqual(ids(merged), ["thrall1", "jaina22", "arthas4", "uther33"])
        # A törlés átjön, ha a másik eszközön nem írták át közben...
        remote = copy.deepcopy(self.base)
        del remote["characters"][1]
        self.assertEqual(ids(merge(self.base, self.base, remote)), ["thrall1"])
        self.assertEqual(ids(merge(self.base, remote, self.base)), ["thrall1"])
        # ...különben a karakter megmarad, az átírt adataival.
        local = copy.deepcopy(self.base)
        character(local, "jaina22")["level"] = 82.0
        merged = merge(self.base, local, remote)
        self.assertEqual((ids(merged), character(merged, "jaina22")["level"]), (["thrall1", "jaina22"], 82.0))
        merged = merge(self.base, remote, local)
        self.assertEqual((ids(merged), character(merged, "jaina22")["level"]), (["thrall1", "jaina22"], 82.0))

    def test_order(self):
        self.remote["characters"].reverse()  # csak a távolin rendezték át
        self.assertEqual(ids(merge(self.base, self.local, self.remote)), ["jaina22", "thrall1"])
        self.assertEqual(ids(merge(self.base, self.remote, self.base)), ["jaina22", "thrall1"])
        # Mindkettőn átrendezték: a helyi marad; az új karakter a helyén (az előzője után) marad.
        local = copy.deepcopy(self.base)
        local["characters"].insert(1, new_character("Uther", "uther33"))
        local["characters"].append(local["characters"].pop(0))  # Thrall a végére
        merged = merge(self.base, local, self.remote)
        self.assertEqual(ids(merged), ["uther33", "jaina22", "thrall1"])
        merged = merge(self.base, self.remote, local)  # Uther a másikon Jaina elé került
        self.assertEqual(ids(merged), ["uther33", "jaina22", "thrall1"])

    def test_scores_and_fetch_times(self):
        newer = {"fetched_at": "2026-10-21T08:00:00", "scores": {"mage/frost": 3650.0}}
        older = {"fetched_at": "2026-10-20T12:00:00", "scores": {"mage/frost": 3610.0}}
        self.local["spec_scores"], self.remote["spec_scores"] = older, newer
        self.assertEqual(merge(self.base, self.local, self.remote)["spec_scores"], newer)  # mindkettő lekérte
        self.assertEqual(merge(self.base, self.remote, self.local)["spec_scores"], newer)
        self.local["raiderio_fetched_at"], self.remote["raiderio_fetched_at"] = "2026-10-21T09:00:00", None
        self.assertEqual(merge(self.base, self.local, self.remote)["raiderio_fetched_at"], "2026-10-21T09:00:00")
        self.remote["gear_entry_min"] = {"Mythic+ 4": 291.4}
        self.assertEqual(merge(self.base, self.local, self.remote)["gear_entry_min"], {"Mythic+ 4": 291.4})

    def test_device_data_stays_and_values_are_checked(self):
        data = sample()
        data.addon_path, data.stats_options = r"C:\Games\World of Warcraft", {"mplus": {"region": "eu"}}
        shared = copy.deepcopy(shared_part(data))
        character(shared, "thrall1")["level"] = 86.5
        shared["settings"]["region"] = "us"
        updated = apply_shared(data, shared)
        self.assertEqual((updated.addon_path, updated.stats_options), (data.addon_path, data.stats_options))
        self.assertEqual((updated.characters[0].level, updated.settings.region), (D("86.50"), "us"))
        self.assertEqual([c.uid for c in updated.characters], ["thrall1", "jaina22"])  # az azonosító megmarad
        self.assertEqual(shared_part(updated), shared)
        character(shared, "thrall1")["level"] = "sok"
        with self.assertRaisesRegex(SyncError, "Hibás adat jött a felhőből"):
            apply_shared(data, shared)


class FirebaseTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = fake_firebase.FakeFirebase()
        self.addCleanup(self.fake.close)

    def signed_in_client(self, email="gamer@example.com", password="titok123"):
        client = self.fake.client()
        if email in self.fake.users:
            client.sign_in(email, password)
        else:
            client.sign_up(email, password)
        return client


class ClientTests(FirebaseTestCase):
    def test_accounts(self):
        client = self.fake.client()
        client.sign_up("gamer@example.com", "titok123")
        self.assertTrue(client.account.signed_in)
        uid = client.account.uid
        self.assertEqual((client.account.email, self.fake.users["gamer@example.com"]["uid"]), ("gamer@example.com", uid))
        for action, email, password, message in (
            ("sign_up", "gamer@example.com", "titok123", "már van fiók"),
            ("sign_up", "uj@example.com", "123", "Túl rövid a jelszó"),
            ("sign_up", "nem-email", "titok123", "Hibás az e-mail-cím"),
            ("sign_in", "gamer@example.com", "rossz", "Hibás az e-mail-cím vagy a jelszó"),
        ):
            with self.subTest(action=action, email=email), self.assertRaisesRegex(AuthError, message):
                getattr(self.fake.client(), action)(email, password)
        other = self.fake.client(self.fake.account(api_key="AIzaRosszKulcs-0123456789"))
        with self.assertRaisesRegex(AuthError, "Hibás a Web API-kulcs"):
            other.sign_in("gamer@example.com", "titok123")
        client.sign_out()
        self.assertFalse(client.account.signed_in)
        with self.assertRaisesRegex(AuthError, "Nincs bejelentkezve"):
            client.read_plan()

    def test_tokens_are_renewed(self):
        client = self.signed_in_client()
        self.assertEqual(client.read_plan(), (None, fake_firebase.etag_of(None)))
        self.fake.expire_tokens()  # a szerver szerint lejárt, a kliens még nem tudja
        self.assertEqual(client.read_rev(), None)
        self.assertEqual(self.fake.log[-3:], [("GET", f"/db/users/{client.account.uid}/plan/rev.json"), ("POST", "/v1/token"),
                                               ("GET", f"/db/users/{client.account.uid}/plan/rev.json")])
        client._expires = 0  # a kliens is tudja: előbb újat kér
        client.read_rev()
        self.assertEqual(self.fake.log[-2][1], "/v1/token")
        # A hosszú lejáratú token is érvénytelen lett (pl. jelszócsere): újra be kell jelentkezni.
        self.fake.refresh_tokens.clear()
        client._expires = 0
        with self.assertRaisesRegex(AuthError, "jelentkezz be újra"):
            client.read_rev()

    def test_database_problems(self):
        client = self.signed_in_client()
        other = self.signed_in_client("masik@example.com")
        client.account.uid = other.account.uid  # más fiókjának helye: a szabályok tiltják
        with self.assertRaisesRegex(SyncError, "szabályait"):
            client.read_plan()
        wrong = self.fake.client(self.fake.account(database_url=f"{self.fake.url}/nincs"))
        wrong.sign_in("gamer@example.com", "titok123")
        with self.assertRaisesRegex(SyncError, "Nincs ilyen adatbázis"):
            wrong.read_rev()
        self.fake.unavailable = True
        with self.assertRaisesRegex(SyncError, "503"):
            other.read_rev()
        with socket.socket() as probe:  # egy szabad port, amelyen nem figyel senki
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        offline = self.fake.client(self.fake.account(database_url=f"http://127.0.0.1:{port}/db"))
        offline.account.uid, offline.account.refresh_token = "abc", "rt"
        offline.auth_url = offline.token_url = f"http://127.0.0.1:{port}/v1/token"
        with self.assertRaisesRegex(SyncError, "Nincs kapcsolat a Firebase-szel"):
            offline.read_rev()

    def test_account_data(self):
        account = cloud_sync.Account.from_dict({"api_key": "k", "database_url": 5, "uid": "u", "refresh_token": "r"})
        self.assertEqual((account.database_url, account.configured, account.signed_in), ("", False, False))
        self.assertEqual(cloud_sync.Account.from_dict(account.to_dict()), account)
        self.assertEqual(
            cloud_sync.normalize_database_url(" https://wow-default-rtdb.europe-west1.firebasedatabase.app/ "),
            "https://wow-default-rtdb.europe-west1.firebasedatabase.app",
        )
        for text in ("http://valami.hu", "wow-default-rtdb", "https://", "https://a.b/c"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                cloud_sync.normalize_database_url(text)
        self.assertEqual(cloud_sync.normalize_api_key(" AIzaSyA-0123456789abcdefgh "), "AIzaSyA-0123456789abcdefgh")
        with self.assertRaises(ValueError):
            cloud_sync.normalize_api_key("rövid kulcs")


class EngineTests(FirebaseTestCase):
    def setUp(self):
        super().setUp()
        self.pc = SyncEngine(self.signed_in_client(), device="PC")
        self.phone = SyncEngine(self.signed_in_client(), device="Telefon")
        self.uid = self.pc.client.account.uid

    def test_two_devices(self):
        pc_data = sample()
        self.assertIsNone(self.pc.sync(shared_part(pc_data)))  # az első feltöltés
        node = self.fake.plan(self.uid)
        self.assertEqual((node["rev"], node["device"]), (1, "PC"))
        self.assertIsInstance(node["updated"], int)  # az adatbázis órája szerint
        self.assertEqual(self.fake.shared(self.uid), shared_part(pc_data))
        # A telefonon még nincs semmi: átveszi a felhőbelit.
        phone_data = LevelingData(Settings.default())
        incoming = self.phone.sync(shared_part(phone_data))
        phone_data = apply_shared(phone_data, incoming)
        self.assertEqual(shared_part(phone_data), shared_part(pc_data))
        # A telefonon átírják Jaina szintjét; a gép a következő ellenőrzéskor átveszi.
        phone_data.characters[1].level = D("82.40")
        self.assertIsNone(self.phone.sync(shared_part(phone_data)))
        self.assertEqual(self.fake.plan(self.uid)["rev"], 2)
        self.assertTrue(self.pc.changed_remotely())
        pc_data = apply_shared(pc_data, self.pc.sync(shared_part(pc_data)))
        self.assertEqual(pc_data.characters[1].level, D("82.40"))
        self.assertFalse(self.pc.changed_remotely())
        # Mindkettőn változtatnak, mielőtt szinkronizálnának: mindkét változtatás megmarad.
        pc_data.characters[0].level = D("84.00")
        phone_data.settings.target_item_level = D(330)
        self.assertIsNone(self.pc.sync(shared_part(pc_data)))
        phone_data = apply_shared(phone_data, self.phone.sync(shared_part(phone_data)))
        pc_data = apply_shared(pc_data, self.pc.sync(shared_part(pc_data)))
        for data in (pc_data, phone_data):
            self.assertEqual((data.characters[0].level, data.settings.target_item_level), (D("84.00"), D(330)))
        self.assertEqual(shared_part(pc_data), shared_part(phone_data))
        self.assertEqual((self.fake.plan(self.uid)["rev"], self.phone.remote.device), (4, "Telefon"))

    def test_nothing_changed_costs_one_small_request(self):
        data = shared_part(sample())
        self.pc.sync(data)
        before = len(self.fake.log)
        self.assertIsNone(self.pc.sync(data))
        self.assertEqual(self.fake.log[before:], [("GET", f"/db/users/{self.uid}/plan/rev.json")])

    def test_write_in_between_is_merged(self):
        data = sample()
        self.pc.sync(shared_part(data))
        self.phone.sync(shared_part(LevelingData(Settings.default())))
        mine = shared_part(data)
        character(mine, "thrall1")["level"] = 84.0
        theirs = shared_part(data)
        character(theirs, "jaina22")["level"] = 82.0

        def phone_writes_first():  # a gép olvasása és írása között a telefon ír
            self.fake.before_put = None
            node = self.fake.plan(self.uid)
            self.fake.set(f"users/{self.uid}/plan", cloud_sync.make_node(node["rev"] + 1, theirs, "Telefon") | {"updated": 1})

        self.fake.before_put = phone_writes_first
        merged = self.pc.sync(mine)
        self.assertEqual((character(merged, "thrall1")["level"], character(merged, "jaina22")["level"]), (84.0, 82.0))
        self.assertEqual(self.fake.shared(self.uid), merged)
        self.assertEqual(self.fake.plan(self.uid)["rev"], 3)

    def test_first_sync_with_a_plan_on_both_sides(self):
        self.pc.sync(shared_part(sample()))
        phone_plan = LevelingData(Settings.default(), [Character("Anduin", "Priest", uid="anduin5")])
        with self.assertRaises(ChoiceNeeded) as caught:
            self.phone.sync(shared_part(phone_plan))
        self.assertIn("2 karakterrel, utoljára a(z) „PC” eszközről", str(caught.exception))
        self.assertEqual(len(caught.exception.remote["characters"]), 2)
        incoming = self.phone.sync(shared_part(phone_plan), first="remote")
        self.assertEqual(ids(incoming), ["thrall1", "jaina22"])
        # A másik választás: a telefoné kerül fel (a gép a következő szinkronizáláskor átveszi).
        self.phone.base = None
        self.assertIsNone(self.phone.sync(shared_part(phone_plan), first="local"))
        self.assertEqual(ids(self.fake.shared(self.uid)), ["anduin5"])
        self.assertEqual(ids(self.pc.sync(shared_part(sample()))), ["anduin5"])

    def test_broken_or_newer_remote_data_is_left_alone(self):
        self.pc.sync(shared_part(sample()))
        node = self.fake.plan(self.uid)
        for data, message in (
            ("{nem json", "nem olvashatók"),
            (json.dumps({"version": 99, "settings": {}, "characters": []}), "újabb változata"),
            (json.dumps({"settings": {}, "characters": [{"name": "X"}]}), "karakterlista"),
        ):
            self.fake.set(f"users/{self.uid}/plan", dict(node, data=data, rev=node["rev"] + 1))
            with self.subTest(data=data), self.assertRaisesRegex(SyncError, message):
                self.pc.sync(shared_part(sample()))
        self.assertEqual(self.fake.plan(self.uid)["data"], data)  # nem írta felül

    def test_base_survives_a_restart(self):
        self.pc.sync(shared_part(sample()))
        saved = json.loads(json.dumps(self.pc.base.to_dict()))
        restored = cloud_sync.Base.from_dict(saved)
        self.assertEqual((restored.rev, restored.data), (self.pc.base.rev, self.pc.base.data))
        self.assertIsNone(cloud_sync.Base.from_dict({"rev": 1, "data": {"settings": 5}}))  # sérült: mintha nem lett volna



class FakeApp:
    """Egy alkalmazás a vezérlő körül (mint a gépi vagy a telefonos), egy virtuális órával: a
    call_later-rel kért függvények akkor futnak, amikor a teszt előre tekeri az órát (pump)."""

    def __init__(self, folder: Path, name: str, data: LevelingData, fake: fake_firebase.FakeFirebase):
        self.database = folder / f"{name}.sqlite"
        self.data = data
        self.now, self.queue, self.counter = 0, [], 0
        self.changes, self.statuses, self.questions = 0, [], []
        self.answer = None  # erre válaszol a kérdésre (None: a teszt maga válaszol)
        with mock.patch.multiple(cloud_sync, AUTH_URL=f"{fake.url}/v1/accounts", TOKEN_URL=f"{fake.url}/v1/token"):
            self.sync = SyncController(
                self.database, name, lambda: self.data, self.changed, self.status, self.ask, self.call_later
            )

    def changed(self):
        self.changes += 1
        storage.write_document(self.database, storage.LEVELING, json.dumps(self.data.to_dict()))

    def status(self, text, problem):
        self.statuses.append((text, problem))

    def ask(self, question, answer):
        self.questions.append(question)
        if self.answer is not None:
            answer(self.answer)
        else:
            self.pending_answer = answer

    def call_later(self, ms, function):
        self.counter += 1
        heapq.heappush(self.queue, (self.now + ms, self.counter, function))

    def pump(self, seconds: float = 0.0, until=None, timeout: float = 5.0):
        """Az óra előretekerése (seconds másodperccel), közben a háttérszál eredményeinek feldolgozása;
        until: addig, amíg ez igaz nem lesz (és a háttérszál nem végzett)."""
        target = self.now + int(seconds * 1000)
        deadline = time.monotonic() + timeout
        while True:
            while self.queue and self.queue[0][0] <= self.now:
                _due, _counter, function = heapq.heappop(self.queue)
                function()
            done = self.now >= target and not self.sync.busy and (until is None or until())
            if done:
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"lejárt az idő; állapot: {self.sync.status}")
            if self.now < target:
                self.now += cloud_sync.CHECK_MS
            else:
                time.sleep(0.01)
                self.now += cloud_sync.CHECK_MS

    def close(self):
        self.sync.close()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_firebase.FakeFirebase()
        self.addCleanup(self.fake.close)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def app(self, name, data):
        app = FakeApp(self.folder, name, data, self.fake)
        self.addCleanup(app.close)
        return app

    def sign_in(self, app, create=False, email="gamer@example.com", password="titok123"):
        app.sync.sign_in(fake_firebase.API_KEY, "https://x.firebasedatabase.app", email, password, create)

    def test_two_apps(self):
        pc = self.app("PC", sample())
        self.assertEqual(pc.statuses[-1], (cloud_sync.NOT_CONFIGURED, False))
        for args, message in (
            (("rövid", "https://x.firebasedatabase.app", "a@b.hu", "titok123"), "Web API-kulcs"),
            ((fake_firebase.API_KEY, "nincs", "a@b.hu", "titok123"), "https://"),
            ((fake_firebase.API_KEY, "https://x.firebasedatabase.app", " ", "titok123"), "e-mail-címet"),
        ):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, message):
                pc.sync.sign_in(*args)
        with mock.patch.object(cloud_sync, "normalize_database_url", lambda text: f"{self.fake.url}/db"):
            self.sign_in(pc, create=True)
        pc.pump(until=lambda: pc.sync.last_sync is not None)  # bejelentkezett, és fel is töltötte
        uid = pc.sync.account.uid
        self.assertEqual(self.fake.shared(uid), shared_part(pc.data))
        self.assertRegex(pc.statuses[-1][0], r"^Szinkronizálva: \d\d:\d\d · gamer@example.com · a felhőbe utoljára: PC, ")

        # A telefon üres tervvel jelentkezik be: átveszi a felhőbelit.
        phone = self.app("Telefon", LevelingData(Settings.default()))
        with mock.patch.object(cloud_sync, "normalize_database_url", lambda text: f"{self.fake.url}/db"):
            self.sign_in(phone)
        phone.pump(until=lambda: phone.changes == 1)
        self.assertEqual(shared_part(phone.data), shared_part(pc.data))
        self.assertEqual(phone.questions, [])

        # A telefonon átírják Jaina szintjét: kicsit később feltölti, a gép a következő ellenőrzéskor átveszi.
        jaina = pc.data.characters[1]
        phone.data.characters[1].level = D("82.40")
        phone.sync.local_changed()
        phone.sync.local_changed()  # a gyors egymás utáni változások egyben mennek
        phone.pump(seconds=cloud_sync.PUSH_DELAY_MS / 1000)
        self.assertEqual(character(self.fake.shared(uid), "jaina22")["level"], 82.4)
        self.assertEqual(self.fake.plan(uid)["rev"], 2)
        pc.pump(seconds=cloud_sync.POLL_SECONDS, until=lambda: pc.changes == 1)
        self.assertEqual(pc.data.characters[1].level, D("82.40"))
        self.assertIs(pc.data.characters[1], jaina)  # ugyanaz az objektum: a nyitott ablakok is jók
        # Újraindítás után a fiók és az utolsó közös állapot megvan: nem kérdez, és nincs mit letölteni.
        pc.close()
        again = self.app("PC", pc.data)
        again.pump(until=lambda: again.sync.last_sync is not None)
        self.assertEqual((again.changes, again.questions, again.sync.account.uid), (0, [], uid))

    def test_local_changes_during_a_sync_are_kept(self):
        pc, phone = self.app("PC", sample()), self.app("Telefon", LevelingData(Settings.default()))
        with mock.patch.object(cloud_sync, "normalize_database_url", lambda text: f"{self.fake.url}/db"):
            self.sign_in(pc, create=True)
            pc.pump(until=lambda: pc.sync.last_sync is not None)
            self.sign_in(phone)
        phone.pump(until=lambda: phone.changes == 1)
        phone.data.characters[0].level = D("85.00")  # a telefon feltölt egy változást...
        phone.sync.sync_now()
        phone.pump()
        pc.sync.sync_now()  # ...a gép épp lekéri, amikor helyben is átírnak egy szintet
        pc.data.characters[1].level = D("83.00")
        pc.pump(until=lambda: pc.changes == 1)
        self.assertEqual([c.level for c in pc.data.characters], [D("85.00"), D("83.00")])
        pc.sync.local_changed()
        pc.pump(seconds=cloud_sync.PUSH_DELAY_MS / 1000)
        uid = pc.sync.account.uid
        self.assertEqual([c["level"] for c in self.fake.shared(uid)["characters"]], [85.0, 83.0])

    def test_first_sign_in_with_a_plan_on_both_sides(self):
        pc = self.app("PC", sample())
        with mock.patch.object(cloud_sync, "normalize_database_url", lambda text: f"{self.fake.url}/db"):
            self.sign_in(pc, create=True)
            pc.pump(until=lambda: pc.sync.last_sync is not None)
            phone = self.app("Telefon", LevelingData(Settings.default(), [Character("Anduin", uid="anduin5")]))
            phone.answer = "remote"
            self.sign_in(phone)
        phone.pump(until=lambda: phone.changes == 1)
        self.assertIn("A felhőben már van egy terv (2 karakterrel, utoljára a(z) „PC” eszközről).", phone.questions[0])
        self.assertEqual([c.name for c in phone.data.characters], ["Thrall", "Jaina"])
        (backup,) = self.folder.glob("Telefon.elozo-terv-*.json")  # az itteni terv nem veszett el
        self.assertEqual([c["name"] for c in json.loads(backup.read_text(encoding="utf-8"))["characters"]], ["Anduin"])

    def test_login_problems(self):
        pc = self.app("PC", sample())
        with mock.patch.object(cloud_sync, "normalize_database_url", lambda text: f"{self.fake.url}/db"):
            self.sign_in(pc, create=True)
            pc.pump(until=lambda: pc.sync.last_sync is not None)
            uid = pc.sync.account.uid
            self.sign_in(pc, password="rossz")  # egy elrontott újabb bejelentkezés: a régi marad
            pc.pump()
        self.assertEqual(pc.statuses[-1], ("⚠ Hibás az e-mail-cím vagy a jelszó.", True))
        self.assertEqual((pc.sync.account.uid, pc.sync.account.signed_in), (uid, True))
        # A hosszú lejáratú token érvénytelen lett: szól, és magától nem próbálkozik tovább.
        self.fake.refresh_tokens.clear()
        self.fake.expire_tokens()
        pc.sync._client._expires = 0
        pc.data.characters[0].level = D("86.00")
        pc.sync.sync_now()
        pc.pump()
        self.assertEqual(pc.statuses[-1], ("⚠ Lejárt a bejelentkezés: jelentkezz be újra.", True))
        before = len(self.fake.log)
        pc.sync.local_changed()
        pc.pump(seconds=cloud_sync.POLL_SECONDS)
        self.assertEqual(len(self.fake.log), before)  # nem próbálkozott
        # Újra bejelentkezve (ugyanaz a fiók): nem kérdez, a változás felmegy.
        with mock.patch.object(cloud_sync, "normalize_database_url", lambda text: f"{self.fake.url}/db"):
            self.sign_in(pc)
        pc.pump(until=lambda: character(self.fake.shared(uid), "thrall1")["level"] == 86.0)
        # Kijelentkezés: a helyi adatok maradnak, a szinkronizálás leáll.
        pc.sync.sign_out()
        self.assertEqual(pc.statuses[-1][0], "Nincs bejelentkezve: a „Beállítás…” gombbal jelentkezhetsz be.")
        self.assertIsNone(storage.read_document(pc.database, storage.CLOUD_BASE))
        self.assertEqual(json.loads(storage.read_document(pc.database, storage.CLOUD))["refresh_token"], "")
        self.assertEqual(len(pc.data.characters), 2)


if __name__ == "__main__":
    unittest.main()
