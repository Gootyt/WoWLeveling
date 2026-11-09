"""A telefonos alkalmazás felülettől független részének (android/app/mobile_plan.py) tesztjei."""

import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import storage
from leveling import SEQUENTIAL, SORT_KEYS, Character, LevelingData, Settings, SpecScores, build_plan

# A gyökérben lévő közös modulok maradjanak elöl (az android/app-ba bemásoltak régebbiek lehetnek).
sys.path.append(str(Path(__file__).resolve().parent.parent / "android" / "app"))
import mobile_plan  # noqa: E402

D = Decimal
TODAY = date(2026, 10, 27)


def sample() -> LevelingData:
    settings = Settings(TODAY - timedelta(days=5), TODAY + timedelta(days=5), TODAY + timedelta(days=15), D(80), D(90))
    settings.target_item_level = D(320)
    characters = [
        Character("Thrall", "Shaman", "Enhancement", D("83.45"), race="Orc", realm="Draenor", item_level=D("301.56"),
                  raiderio_score=D("1234.0"), uid="thrall1"),
        Character("Jaina", "Mage", "Frost", D("90.00"), item_level=D(305), raiderio_score=D(1500), uid="jaina22"),
        Character("Arthas", level=D("81.00"), uid="arthas3"),
    ]
    scores = SpecScores({"mage/frost": D(3600), "shaman/enhancement": D(3500)})
    return LevelingData(settings, characters, scores, look_ahead=False)


class CardTests(unittest.TestCase):
    def test_cards_show_what_the_program_does(self):
        data = sample()
        cards = mobile_plan.cards(data, TODAY)
        plans = build_plan(data.settings, data.characters, TODAY, data.spec_scores)
        self.assertEqual([card.uid for card in cards], ["thrall1", "jaina22", "arthas3"])
        thrall = cards[0]
        self.assertEqual((thrall.title, thrall.subtitle), ("1. Thrall (Draenor)", "Enhancement Shaman · Orc"))
        self.assertEqual(thrall.status, plans[0].status_text)
        self.assertEqual(thrall.level, f"Szint 83,45 · cél {plans[0].goal:.2f} · −{plans[0].goal - D('83.45'):.2f}".replace(".", ","))
        self.assertEqual(thrall.tone, mobile_plan.TONES[plans[0].status])
        self.assertTrue(thrall.gear.startswith("Itemlevel 301,56 · terv "))
        self.assertTrue(thrall.mplus.startswith("M+ 1234,0 · terv "))
        jaina = cards[1]
        self.assertEqual((jaina.title, jaina.subtitle, jaina.status), ("2. Jaina", "Frost Mage", "Kész – elérte a célszintet"))
        arthas = cards[2]  # se itemlevel, se pontszám, se spec: nincs mit mutatni
        self.assertEqual((arthas.subtitle, arthas.mplus), ("", ""))
        self.assertTrue(arthas.gear.startswith("Itemlevel – · terv "))

    def test_summary(self):
        data = sample()
        self.assertRegex(mobile_plan.summary(data, TODAY), r"^3 karakter · célszinten: 1 · mai teendő: \d+,\d\d szint$")
        data.look_ahead = True
        for character in data.characters:
            character.level = D(90) if character.uid == "jaina22" else D(89)  # a mai célokat mindenki teljesítette
        self.assertIn("célig:", mobile_plan.summary(data, TODAY))
        self.assertTrue(mobile_plan.summary(LevelingData(Settings.default()), TODAY).startswith("Még nincs karakter"))


class SortTests(unittest.TestCase):
    def order(self, data, sort, descending=False):
        return [card.uid for card in mobile_plan.cards(data, TODAY, sort, descending)]

    def test_sorted_cards(self):
        data = sample()
        self.assertTrue(set(mobile_plan.SORTS) <= set(SORT_KEYS))
        self.assertEqual(self.order(data, "position"), ["thrall1", "jaina22", "arthas3"])
        self.assertEqual(self.order(data, "name"), ["arthas3", "jaina22", "thrall1"])
        self.assertEqual(self.order(data, "name", True), ["thrall1", "jaina22", "arthas3"])
        # Arthasnak nincs itemlevele: mindkét irányban a végére kerül.
        self.assertEqual(self.order(data, "item_level"), ["thrall1", "jaina22", "arthas3"])
        self.assertEqual(self.order(data, "item_level", True), ["jaina22", "thrall1", "arthas3"])
        self.assertEqual(self.order(data, "status")[-1], "jaina22")  # aki már kész, a végén
        plans = build_plan(data.settings, data.characters, TODAY, data.spec_scores)
        most_behind = min(plans, key=lambda plan: plan.deviation).character.uid
        self.assertEqual(self.order(data, "deviation")[0], most_behind)
        # A cím a terv szerinti helyet mutatja, akárhogy is rendezett a lista.
        self.assertEqual(mobile_plan.cards(data, TODAY, "name")[0].title, "3. Arthas")
        self.assertEqual(mobile_plan.DEFAULT_SORT, ("status", False))

    def test_moving_only_in_plan_order(self):
        self.assertEqual(mobile_plan.move_hint("position", False), "")
        self.assertIn("„Terv szerinti sorrend”", mobile_plan.move_hint("status", False))
        self.assertIn("„Fordítva”", mobile_plan.move_hint("position", True))

    def test_saved_sort(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / storage.DB_NAME
            self.assertEqual(mobile_plan.load_sort(database), mobile_plan.DEFAULT_SORT)  # még nincs adatbázis
            mobile_plan.save_sort(database, "item_level", True)
            self.assertEqual(mobile_plan.load_sort(database), ("item_level", True))
            storage.write_document(database, storage.PHONE_VIEW, '{"sort": "level"}')
            self.assertEqual(mobile_plan.load_sort(database), ("level", False))
            for body in ("nem json", "[]", '{"sort": "nincs ilyen"}', '{"sort": ["level"]}', '{"sort": "level", "descending": 1}'):
                with self.subTest(body=body):
                    storage.write_document(database, storage.PHONE_VIEW, body)
                    self.assertEqual(mobile_plan.load_sort(database), mobile_plan.DEFAULT_SORT)
            self.assertIsNone(storage.read_document(database, storage.LEVELING))  # a tervhez nem nyúlt


class EditTests(unittest.TestCase):
    def test_add_edit_delete_and_move(self):
        data = sample()
        uther = mobile_plan.save_character(data, None, {"name": " Uther ", "class": "Paladin", "spec": "Holy", "level": ""})
        self.assertEqual((data.characters[-1], uther.level, uther.spec), (uther, D(80), "Holy"))  # üres szint: a kezdőszint
        form = mobile_plan.character_form(data.characters[0])
        self.assertEqual(form["level"], "83,45")
        form.update(level="84,5", item_level="303,25", score="", **{"class": "Mage"})  # a régi spec nem illik az új kaszthoz
        thrall = mobile_plan.save_character(data, "thrall1", form)
        self.assertEqual((thrall.level, thrall.item_level, thrall.raiderio_score, thrall.spec), (D("84.50"), D("303.25"), None, ""))
        for form, message in (
            ({"name": ""}, "nevét"),
            ({"name": "X", "level": "sok"}, "Szint: "),
            ({"name": "X", "item_level": "x"}, "Itemlevel: "),
            ({"name": "X", "score": "-5"}, "Mythic\\+ pontszám: "),
        ):
            with self.subTest(form=form), self.assertRaisesRegex(ValueError, message):
                mobile_plan.save_character(data, None, form)
        self.assertEqual(len(data.characters), 4)  # a hibás nem került fel
        with self.assertRaisesRegex(ValueError, "közben törlődött"):
            mobile_plan.save_character(data, "nincs-ilyen", {"name": "X"})
        self.assertTrue(mobile_plan.move_character(data, uther.uid, -1))
        self.assertEqual([c.name for c in data.characters], ["Thrall", "Jaina", "Uther", "Arthas"])
        self.assertFalse(mobile_plan.move_character(data, "thrall1", -1))  # már az első
        mobile_plan.delete_character(data, "jaina22")
        self.assertEqual([c.name for c in data.characters], ["Thrall", "Uther", "Arthas"])
        self.assertEqual(mobile_plan.spec_choices("Mage"), ("", "Arcane", "Fire", "Frost"))
        self.assertEqual(mobile_plan.spec_choices(""), ("",))
        self.assertEqual(mobile_plan.character_form(None)["name"], "")

    def test_settings(self):
        data = sample()
        form = mobile_plan.settings_form(data)
        self.assertEqual((form["target_item_level"], form["region"], form["look_ahead"]), ("320,00", "EU", False))
        form.update(target_level="91", mode=SEQUENTIAL, region="US", look_ahead=True, target_item_level="")
        mobile_plan.save_settings(data, form)
        settings = data.settings
        self.assertEqual((settings.target_level, settings.mode, settings.region, settings.target_item_level), (D(91), SEQUENTIAL, "us", None))
        self.assertTrue(data.look_ahead)
        for change, message in (
            ({"start_date": "tegnap"}, "Szintezés kezdete: "),
            ({"target_level": "70"}, "nagyobbnak kell lennie"),
            ({"first_target_date": "2020-01-01"}, "nem lehet korábbi"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                mobile_plan.save_settings(data, dict(mobile_plan.settings_form(data), **change))
        self.assertEqual(data.settings, settings)  # a hibás nem változtatott rajta


if __name__ == "__main__":
    unittest.main()
