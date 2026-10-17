import io
import json
import unittest
import urllib.error
from decimal import Decimal
from unittest import mock

import raiderio
from leveling import Character

D = Decimal

SLOTS = (
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist",
    "legs", "feet", "finger1", "finger2", "trinket1", "trinket2", "mainhand",
)  # fmt: skip


def gear(reported, mainhand=331, offhand=None, others=333, **extra_slots):
    """A Raider.io válaszának „gear” része: a felsorolt helyeken `others` itemlevelű tárgyak."""
    items = {slot: {"item_level": others, "name": slot} for slot in SLOTS}
    items["mainhand"]["item_level"] = mainhand
    items["shirt"] = {"item_level": 1}  # az ing nem számít
    if offhand is not None:
        items["offhand"] = {"item_level": offhand}
    for slot, level in extra_slots.items():
        items[slot] = {"item_level": level}
    return {"item_level_equipped": reported, "item_level_total": 0, "source": "s3", "items": items}


def profile_data(gear_part=None, score=4186.2, **fields):
    data = {
        "name": "Ayijeqt",
        "race": "Dwarf",
        "class": "Paladin",
        "active_spec_name": "Holy",
        "active_spec_role": "HEALING",
        "region": "eu",
        "realm": "Twisting Nether",
        **fields,
    }
    if gear_part is not None:
        data["gear"] = gear_part
    if score is not None:
        data["mythic_plus_scores_by_season"] = [
            {"season": "season-mn-2", "scores": {"all": score, "dps": 1232.8, "healer": score, "tank": 0}}
        ]
    return data


class ParseProfileTests(unittest.TestCase):
    def test_item_level_is_computed_from_the_items(self):
        # A Raider.io lefelé kerekítve 333-at ad; a 16 hely átlaga (14 × 333 + 331 + 339) / 16 = 333,25.
        profile = raiderio.parse_profile(profile_data(gear(333, mainhand=331, offhand=339)))
        self.assertEqual(profile, raiderio.Profile(D("333.25"), D("4186.2"), "Dwarf", "Paladin", "Holy"))

    def test_two_handed_weapon_counts_twice(self):
        # Nincs mellékkéz: a fegyver kétszer számít (14 × 333 + 2 × 334) / 16 = 333,125 → 333,13.
        self.assertEqual(raiderio.parse_profile(profile_data(gear(333, mainhand=334))).item_level, D("333.13"))

    def test_precise_item_level_is_used_as_given(self):
        self.assertEqual(raiderio.parse_profile(profile_data(gear(332.625, others=1))).item_level, D("332.63"))

    def test_reported_item_level_wins_when_the_items_disagree(self):
        # Pl. egykezes fegyver mellékkéz nélkül: a tárgyakból számolt átlag nem illik a 330-hoz.
        self.assertEqual(raiderio.parse_profile(profile_data(gear(330, mainhand=340))).item_level, D("330.00"))
        missing = gear(331)
        del missing["items"]["back"]  # hiányzó tárgy
        self.assertEqual(raiderio.parse_profile(profile_data(missing)).item_level, D("331.00"))

    def test_race_class_and_spec_get_the_programs_names(self):
        profile = raiderio.parse_profile(
            profile_data(race="Mag’har orc", **{"class": "death knight", "active_spec_name": "UNHOLY"})
        )
        self.assertEqual((profile.race, profile.char_class, profile.spec), ("Mag'har Orc", "Death Knight", "Unholy"))
        # Amit a program nem ismer, az úgy marad, ahogy a Raider.io-n van.
        profile = raiderio.parse_profile(profile_data(race="Ogre", **{"class": "Tinker", "active_spec_name": "Gadget"}))
        self.assertEqual((profile.race, profile.char_class, profile.spec), ("Ogre", "Tinker", "Gadget"))

    def test_missing_data(self):
        self.assertEqual(raiderio.parse_profile({}), raiderio.Profile(item_level=None, score=None))
        empty = raiderio.parse_profile(profile_data(race=" ", **{"class": None, "active_spec_name": 5}))
        self.assertEqual((empty.race, empty.char_class, empty.spec), (None, None, None))
        self.assertIsNone(raiderio.parse_profile(profile_data(gear(0))).item_level)  # nincs adat a felszerelésről
        self.assertIsNone(raiderio.parse_profile(profile_data({"item_level_equipped": "sok"})).item_level)
        self.assertIsNone(raiderio.parse_profile({"mythic_plus_scores_by_season": []}).score)
        self.assertEqual(raiderio.parse_profile(profile_data(score=0)).score, D("0.0"))  # még nincs futása


class FetchProfileTests(unittest.TestCase):
    def test_url(self):
        self.assertEqual(
            raiderio.profile_url("eu", "Twilight's Hammer", "Héléna"),
            "https://raider.io/api/v1/characters/profile?region=eu&realm=Twilight%27s%20Hammer"
            "&name=H%C3%A9l%C3%A9na&fields=gear,mythic_plus_scores_by_season:current",
        )

    def test_successful_fetch(self):
        body = json.dumps(profile_data(gear(333, mainhand=331, offhand=339))).encode()
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = body
        with mock.patch.object(raiderio.urllib.request, "urlopen", return_value=response) as urlopen:
            profile = raiderio.fetch_profile("eu", "Twisting Nether", "Ayijeqt")
        self.assertEqual(profile, raiderio.Profile(D("333.25"), D("4186.2"), "Dwarf", "Paladin", "Holy"))
        request = urlopen.call_args.args[0]
        self.assertIn("realm=Twisting%20Nether&name=Ayijeqt", request.full_url)
        self.assertTrue(request.get_header("User-agent"))

    def fetch_error(self, error):
        with mock.patch.object(raiderio.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(raiderio.RaiderioError) as caught:
                raiderio.fetch_profile("eu", "Draenor", "Valaki")
        return caught.exception

    @staticmethod
    def http_error(code, message=None):
        body = b"" if message is None else json.dumps({"statusCode": code, "message": message}).encode()
        return urllib.error.HTTPError("https://raider.io/api", code, "hiba", {}, io.BytesIO(body))

    def test_unknown_character_and_realm(self):
        error = self.fetch_error(self.http_error(400, "Could not find requested character"))
        self.assertIsInstance(error, raiderio.CharacterNotFound)
        self.assertEqual(str(error), "nem található a Raider.io-n")
        error = self.fetch_error(self.http_error(400, "Failed to find realm Nincs Ilyen in region eu"))
        self.assertIsInstance(error, raiderio.CharacterNotFound)
        self.assertEqual(str(error), "ismeretlen realm a Raider.io-n")

    def test_other_errors_stop_the_fetch(self):
        cases = (
            (self.http_error(400, "Invalid request query input"), "hibával válaszolt (400: Invalid request query"),
            (self.http_error(429), "túl sok kérést kapott"),
            (self.http_error(503), "hibával válaszolt (503)"),
            (urllib.error.URLError("timed out"), "nem érhető el (timed out)"),
        )
        for error, text in cases:
            with self.subTest(text=text):
                caught = self.fetch_error(error)
                self.assertNotIsInstance(caught, raiderio.CharacterNotFound)
                self.assertIn(text, str(caught))

    def test_unreadable_response(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>"
        with mock.patch.object(raiderio.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(raiderio.RaiderioError, "nem értelmezhető"):
                raiderio.fetch_profile("eu", "Draenor", "Thrall")


class ProfileChangesTests(unittest.TestCase):
    def changes(self, character, item_level=None, score=None):
        rises, drops = raiderio.profile_changes(character, raiderio.Profile(item_level, score))
        return [change.describe() for change in rises], [change.describe() for change in drops]

    def test_new_and_higher_values_are_rises(self):
        thrall = Character("Thrall", item_level=D("320.50"), raiderio_score=None)
        self.assertEqual(
            self.changes(thrall, D("326.13"), D("2543.7")),
            (["Thrall: itemlevel 320,50 → 326,13", "Thrall: Raider.io – → 2543,7"], []),
        )

    def test_lower_values_are_drops(self):
        jaina = Character("Jaina", item_level=D("335.20"), raiderio_score=D("2600.0"))
        self.assertEqual(
            self.changes(jaina, D("333.25"), D("2543.7")),
            ([], ["Jaina: itemlevel 335,20 → 333,25", "Jaina: Raider.io 2600,0 → 2543,7"]),
        )

    def test_unchanged_and_missing_values(self):
        arthas = Character("Arthas", item_level=D("333.25"), raiderio_score=D("2543.7"))
        self.assertEqual(self.changes(arthas, D("333.25"), D("2543.7")), ([], []))
        self.assertEqual(self.changes(arthas, None, None), ([], []))

    def test_whole_item_level_keeps_the_more_precise_value(self):
        # A Raider.io csak egészet tud: a beírt 333,56 ugyanennyi egész, így marad.
        arthas = Character("Arthas", item_level=D("333.56"))
        self.assertEqual(self.changes(arthas, D("333.00")), ([], []))
        self.assertEqual(self.changes(arthas, D("334.00")), (["Arthas: itemlevel 333,56 → 334,00"], []))
        self.assertEqual(self.changes(arthas, D("332.00")), ([], ["Arthas: itemlevel 333,56 → 332,00"]))

    def test_empty_race_class_and_spec_are_filled_in(self):
        profile = raiderio.Profile(None, None, "Orc", "Shaman", "Enhancement")
        rises, drops = raiderio.profile_changes(Character("Thrall"), profile)
        self.assertEqual([change.summary() for change in rises], ["faj Orc", "kaszt Shaman", "spec Enhancement"])
        self.assertEqual(rises[2].describe(), "Thrall: spec – → Enhancement")
        self.assertEqual(drops, [])
        # A már megadott adat marad; a spec csak ugyanannál a kasztnál kerül be.
        filled = Character("Thrall", "shaman", "Elemental", race="Troll")
        self.assertEqual(raiderio.profile_changes(filled, profile), ([], []))
        rises, _drops = raiderio.profile_changes(Character("Thrall", "shaman", race="Orc"), profile)
        self.assertEqual([change.summary() for change in rises], ["spec Enhancement"])
        rises, _drops = raiderio.profile_changes(Character("Thrall", "Mage"), profile)
        self.assertEqual([change.summary() for change in rises], ["faj Orc"])

    def test_apply(self):
        thrall = Character("Thrall")
        rises, _drops = raiderio.profile_changes(thrall, raiderio.Profile(D("326.13"), D("0.0")))
        for change in rises:
            change.apply()
        self.assertEqual((thrall.item_level, thrall.raiderio_score), (D("326.13"), D("0.0")))


if __name__ == "__main__":
    unittest.main()
