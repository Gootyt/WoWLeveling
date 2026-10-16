import unittest
from decimal import Decimal
from fractions import Fraction

from leveling import Character, SpecScores
from recommend import combo_shares, ranked_combos, recommend_combo
from wow_data import ALLIANCE, HEALER, HORDE, MELEE, RANGED, TANK

D = Decimal
F = Fraction


def names(combos):
    return [combo.name for combo in combos]


class RecommendTests(unittest.TestCase):
    def test_role_and_armor_shares_of_all_combos(self):
        # A Horde 419 class/spec/faj combójából 51 tank (12%), 65 healer, 149 melee és 154 ranged DPS.
        roles, armors = combo_shares(HORDE)
        self.assertEqual(roles, {TANK: F(51, 419), HEALER: F(65, 419), MELEE: F(149, 419), RANGED: F(154, 419)})
        self.assertEqual(
            armors, {"plate": F(93, 419), "mail": F(81, 419), "cloth": F(135, 419), "leather": F(110, 419)}
        )
        roles, armors = combo_shares(ALLIANCE)
        self.assertEqual((roles[TANK], sum(roles.values()), sum(armors.values())), (F(53, 412), 1, 1))

    def test_empty_list_follows_the_largest_shares(self):
        # A legtöbb combó ranged DPS és cloth; ezek közül a legjobb pontszámú spec jön.
        scores = SpecScores({"paladin/holy": D("4050"), "mage/frost": D("3575")})
        self.assertEqual(recommend_combo([], scores, ALLIANCE).best.name, "Human Frost Mage")
        self.assertEqual(recommend_combo([], scores, HORDE).best.name, "Orc Frost Mage")

    def test_only_available_races_are_offered(self):
        def first_races(faction):
            races = {}
            for combo in ranked_combos([], SpecScores(), faction):
                races.setdefault((combo.char_class, combo.spec), combo.race)
            return races

        horde, alliance = first_races(HORDE), first_races(ALLIANCE)
        self.assertEqual(horde[("Paladin", "Holy")], "Tauren")  # Orc és Undead (még) nem lehet Paladin
        self.assertEqual(alliance[("Paladin", "Holy")], "Human")
        self.assertEqual(horde[("Evoker", "Preservation")], "Dracthyr")
        self.assertEqual(horde[("Demon Hunter", "Vengeance")], "Blood Elf")
        self.assertEqual(alliance[("Demon Hunter", "Vengeance")], "Night Elf")

    def test_roles_follow_their_share_of_all_combos(self):
        roster = [
            Character("A", "Warrior", "Protection"),
            Character("B", "Paladin", "Protection"),
            Character("C", "Priest", "Holy"),
            Character("D", "Shaman", "Restoration"),
            Character("E", "Rogue", "Outlaw"),
            Character("F", "Warrior", "Arms"),
            Character("G", "Death Knight", "Frost"),
            Character("H", "Mage", "Fire"),
            Character("I", "Warlock", "Affliction"),
            Character("J", "Hunter", "Beast Mastery"),
        ]
        # 2 tank, 2 healer, 3 melee és 3 ranged: a DPS a combók 72%-a, így nem a tank vagy a healer
        # hiányzik, hanem a ranged. Egy újjal 11 karakter lenne, ebből a ranged aránya 154/419 · 11 ≈ 4,04.
        best = recommend_combo(roster, SpecScores(), HORDE).best
        self.assertEqual(best.role, RANGED)
        self.assertEqual(best.balance[0], 3 - F(154 * 11, 419))
        # Még egy ranged után már a melee marad el jobban.
        roster.append(Character("K", "Mage", "Frost"))
        self.assertEqual(recommend_combo(roster, SpecScores(), HORDE).best.role, MELEE)

    def test_armor_follows_its_share_of_all_combos(self):
        # Egy cloth ranged után melee jön; a nem cloth páncélok közül a leather (26%) marad el
        # leginkább az arányától, így a magasabb pontszámú, de plate Arms Warrior helyett Rogue.
        scores = SpecScores({"warrior/arms": D("9999"), "rogue/outlaw": D("3600")})
        recommendation = recommend_combo([Character("A", "Mage", "Fire")], scores, HORDE)
        self.assertEqual(recommendation.best.name, "Orc Outlaw Rogue")
        self.assertEqual((recommendation.best.role, recommendation.best.armor), (MELEE, "leather"))

    def test_class_spec_and_race_counts(self):
        roster = [
            Character("A", "Warrior", "Arms", race="Human"),
            Character("B", "Warrior", "Fury", race="Dwarf"),
            Character("C", "Priest", "Shadow", race="Human"),
        ]
        ranked = ranked_combos(roster, SpecScores(), ALLIANCE)
        by_name = {combo.name: combo for combo in ranked}
        self.assertEqual(by_name["Human Protection Warrior"].counts, (0, 2, 2, 0, 2))
        self.assertEqual(by_name["Dwarf Arms Warrior"].counts, (2, 2, 2, 1, 1))  # melee DPS: 2
        self.assertEqual(by_name["Night Elf Holy Priest"].counts, (0, 1, 1, 0, 0))
        self.assertEqual([combo.balance for combo in ranked], sorted(combo.balance for combo in ranked))

    def test_least_used_race_is_chosen(self):
        roster = [
            Character("A", "Warrior", "Arms", race="Human"),
            Character("B", "Warrior", "Fury", race="Dwarf"),
            Character("C", "Rogue", "Outlaw", race="Night Elf"),
        ]
        scores = SpecScores({"mage/frost": D("4000")})  # ranged cloth jön, a fajok közül a még nem használt
        self.assertEqual(recommend_combo(roster, scores, ALLIANCE).best.name, "Gnome Frost Mage")

    def test_role_without_spec(self):
        roster = [Character("A", "Mage"), Character("B", "Hunter")]  # Mage: ranged; Hunter: nem tudható
        by_name = {combo.name: combo for combo in ranked_combos(roster, SpecScores(), ALLIANCE)}
        self.assertEqual(by_name["Human Fire Mage"].counts[:3], (1, 1, 1))  # ranged, cloth, Mage
        self.assertEqual(by_name["Human Survival Hunter"].counts[:3], (0, 1, 1))  # melee, mail, Hunter

    def test_unknown_names_are_ignored_and_names_matched_loosely(self):
        roster = [
            Character("A", "death knight", "blood", race="Mag’har orc"),
            Character("B", "Necromancer", race="Ogre"),  # ismeretlen kaszt és faj: nem számít
        ]
        by_name = {combo.name: combo for combo in ranked_combos(roster, SpecScores(), HORDE)}
        self.assertEqual(by_name["Mag'har Orc Blood Death Knight"].counts, (1, 1, 1, 1, 1))
        self.assertEqual(by_name["Orc Arms Warrior"].counts, (0, 1, 0, 0, 0))

    def test_description(self):
        roster = [
            Character("A", "Warrior", "Protection", race="Orc"),
            Character("B", "Paladin", "Protection", race="Tauren"),
            Character("C", "Shaman", "Restoration", race="Orc"),
            Character("D", "Shaman", "Enhancement", race="Orc"),
            Character("E", "Mage", "Frost", race="Undead"),
            Character("F", "Death Knight", "Unholy", race="Undead"),
        ]
        scores = SpecScores(
            {"druid/balance": D("3605"), "demon hunter/devourer": D("3790"), "warlock/destruction": D("3650")}
        )
        recommendation = recommend_combo(roster, scores, HORDE)
        self.assertEqual(recommendation.best.name, "Blood Elf Devourer Demon Hunter")
        self.assertEqual(
            recommendation.describe(),
            "A meglévő 6 karakter alapján ez hiányzik leginkább (sorban a szerep, a páncéltípus, a kaszt, "
            "a spec és a faj szerint). A szerepet és a páncéltípust ahhoz méri, hogy az összes Horde combó "
            "hány százaléka ilyen:\n"
            "• szerep – ranged DPS: 1 karakter (17%); az összes combó 37%-a\n"
            "• páncéltípus – leather: még egy sincs (0%); az összes combó 26%-a\n"
            "• kaszt – Demon Hunter: még egy sincs\n"
            "• spec – Devourer Demon Hunter: még egy sincs\n"
            "• faj – Blood Elf: még egy sincs\n"
            "Ugyanennyire hiányzik még 1 másik class/spec is; közülük ennek a legmagasabb a Murlok.io-pontszáma "
            "(3790).\n"
            "\nUtána következnének: Troll Balance Druid, Troll Destruction Warlock, Troll Shadow Priest.",
        )

    def test_without_scores_the_alphabet_decides(self):
        recommendation = recommend_combo([], SpecScores(), HORDE)
        self.assertEqual(recommendation.best.name, "Orc Arcane Mage")
        description = recommendation.describe()
        self.assertTrue(description.startswith("Még nincs karakter a listán"))
        self.assertIn("• szerep – ranged DPS: még egy sincs; az összes combó 37%-a", description)
        self.assertIn("Murlok.io-pontszámok még nincsenek", description)

    def test_unknown_faction(self):
        with self.assertRaises(ValueError):
            recommend_combo([], SpecScores(), "Scourge")


if __name__ == "__main__":
    unittest.main()
