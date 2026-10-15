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
    RANGED,
    SPEC_ROLES,
    TANK,
    WOW_CLASSES,
    WOW_RACES,
    WOW_SPECS,
    character_role,
    find_class,
    find_race,
    find_spec,
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

    def test_names_are_matched_loosely(self):
        self.assertEqual(find_class(" death knight "), "Death Knight")
        self.assertEqual(find_class("DeathKnight"), "Death Knight")
        self.assertIsNone(find_class("DK"))
        self.assertEqual(find_spec("Hunter", "beast mastery"), "Beast Mastery")
        self.assertIsNone(find_spec("Mage", "Holy"))
        self.assertEqual(find_race("Mag’har orc"), "Mag'har Orc")
        self.assertIsNone(find_race("Ogre"))
        self.assertEqual(specs_for_class("mage"), ("Arcane", "Fire", "Frost"))


if __name__ == "__main__":
    unittest.main()
