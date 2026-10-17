import unittest
from collections import Counter

from wow_data import (
    ALLIANCE,
    CLASS_ARMOR,
    FACTION_RACES,
    HEALER,
    HORDE,
    MELEE,
    RACE_CLASSES,
    RACE_FILE_NAMES,
    RANGED,
    SPEC_IDS,
    SPEC_ROLES,
    TANK,
    WOW_CLASSES,
    WOW_RACES,
    WOW_SPECS,
    character_role,
    find_class,
    find_race,
    find_spec,
    role_label,
    role_of,
    specs_for_class,
)


class GameDataTests(unittest.TestCase):
    def test_every_race_has_factions_and_classes(self):
        self.assertEqual(set(RACE_CLASSES), set(WOW_RACES))
        self.assertEqual(set(FACTION_RACES[ALLIANCE]) | set(FACTION_RACES[HORDE]), set(WOW_RACES))
        both = set(FACTION_RACES[ALLIANCE]) & set(FACTION_RACES[HORDE])
        self.assertEqual(both, {"Pandaren", "Dracthyr", "Earthen", "Haranir"})
        for race, classes in RACE_CLASSES.items():
            with self.subTest(race=race):
                self.assertTrue(set(classes) <= set(WOW_CLASSES))
                self.assertTrue({"Hunter", "Mage", "Priest", "Rogue", "Warlock", "Warrior"} <= set(classes))

    def test_race_class_combinations(self):
        self.assertEqual(sum(len(classes) for classes in RACE_CLASSES.values()), 240)
        self.assertEqual(
            RACE_CLASSES["Dracthyr"], ("Evoker", "Hunter", "Mage", "Priest", "Rogue", "Warlock", "Warrior")
        )
        self.assertEqual([race for race, classes in RACE_CLASSES.items() if "Evoker" in classes], ["Dracthyr"])
        demon_hunters = sorted(race for race, classes in RACE_CLASSES.items() if "Demon Hunter" in classes)
        self.assertEqual(demon_hunters, ["Blood Elf", "Night Elf", "Void Elf"])
        self.assertIn("Druid", RACE_CLASSES["Haranir"])
        self.assertNotIn("Death Knight", RACE_CLASSES["Earthen"])
        for race in ("Night Elf", "Troll", "Undead"):  # Paladin csak a 12.2-es patchtől lesz
            with self.subTest(race=race):
                self.assertNotIn("Paladin", RACE_CLASSES[race])

    def test_roles_and_armor_types(self):
        self.assertEqual(set(SPEC_ROLES), {(c, spec) for c, specs in WOW_SPECS.items() for spec in specs})
        roles = Counter(SPEC_ROLES.values())
        self.assertEqual((roles[TANK], roles[HEALER], roles[MELEE], roles[RANGED]), (6, 7, 13, 14))
        self.assertEqual(SPEC_ROLES[("Demon Hunter", "Devourer")], RANGED)
        self.assertEqual(SPEC_ROLES[("Demon Hunter", "Havoc")], MELEE)
        self.assertEqual(SPEC_ROLES[("Hunter", "Survival")], MELEE)
        self.assertEqual(SPEC_ROLES[("Evoker", "Augmentation")], RANGED)
        self.assertEqual(SPEC_ROLES[("Priest", "Discipline")], HEALER)
        self.assertEqual(set(CLASS_ARMOR), set(WOW_CLASSES))
        self.assertEqual(Counter(CLASS_ARMOR.values()), {"cloth": 3, "leather": 4, "mail": 3, "plate": 3})
        self.assertEqual(character_role("Mage", None), RANGED)  # minden Mage spec ranged DPS
        self.assertEqual(character_role("Rogue", None), MELEE)
        self.assertIsNone(character_role("Hunter", None))  # a Survival melee, a többi ranged
        self.assertIsNone(character_role("Paladin", None))  # spec nélkül nem tudható
        self.assertEqual(character_role("Paladin", "Holy"), HEALER)

    def test_role_of_typed_class_and_spec(self):
        self.assertEqual(role_of("Shaman", "Enhancement"), MELEE)
        self.assertEqual(role_of(" demon hunter ", "devourer"), RANGED)
        self.assertEqual(role_of("Mage", ""), RANGED)  # spec nélkül is egyértelmű
        self.assertIsNone(role_of("Hunter", ""))  # Beast Mastery és Marksmanship ranged, a Survival melee
        self.assertIsNone(role_of("Necromancer", "Bone"))
        labels = [role_label(role) for role in (TANK, HEALER, MELEE, RANGED)]
        self.assertEqual(labels, ["Tank", "Healer", "Melee DPS", "Ranged DPS"])

    def test_names_are_matched_loosely(self):
        self.assertEqual(find_class(" death knight "), "Death Knight")
        self.assertEqual(find_class("DeathKnight"), "Death Knight")
        self.assertIsNone(find_class("DK"))
        self.assertEqual(find_spec("Hunter", "beast mastery"), "Beast Mastery")
        self.assertIsNone(find_spec("Mage", "Holy"))
        self.assertEqual(find_race("Mag’har orc"), "Mag'har Orc")
        self.assertIsNone(find_race("Ogre"))
        self.assertEqual(specs_for_class("mage"), ("Arcane", "Fire", "Frost"))

    def test_game_ids_of_specs_and_races(self):
        # Minden specnek egy azonosítója van (forrás: warcraft.wiki.gg, „SpecializationID”).
        all_specs = sorted((char_class, spec) for char_class, specs in WOW_SPECS.items() for spec in specs)
        self.assertEqual(sorted(SPEC_IDS.values()), all_specs)
        self.assertEqual(
            (SPEC_IDS[250], SPEC_IDS[268], SPEC_IDS[270], SPEC_IDS[1480], SPEC_IDS[1473], SPEC_IDS[73]),
            (
                ("Death Knight", "Blood"),
                ("Monk", "Brewmaster"),
                ("Monk", "Mistweaver"),
                ("Demon Hunter", "Devourer"),
                ("Evoker", "Augmentation"),
                ("Warrior", "Protection"),
            ),
        )
        # A játék nyelvtől független fajnevei közül a többit a find_race is felismeri.
        self.assertEqual(set(RACE_FILE_NAMES.values()) - set(WOW_RACES), set())
        for race_file in ("NightElf", "BloodElf", "HighmountainTauren", "MagharOrc", "ZandalariTroll", "KulTiran"):
            with self.subTest(race_file=race_file):
                self.assertIsNotNone(find_race(race_file))
        self.assertEqual(find_class("DEATHKNIGHT"), "Death Knight")  # a játék kasztazonosítója


if __name__ == "__main__":
    unittest.main()
