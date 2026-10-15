import unittest
from decimal import Decimal

from leveling import Character, SpecScores
from recommend import ranked_combos, recommend_combo
from wow_data import ALLIANCE, HORDE

D = Decimal


def names(combos):
    return [combo.name for combo in combos]


class RecommendTests(unittest.TestCase):
    def test_empty_list_gets_the_best_scored_spec_with_an_available_race(self):
        scores = SpecScores({"paladin/holy": D("4050"), "mage/frost": D("3575")})
        self.assertEqual(recommend_combo([], scores, ALLIANCE).best.name, "Human Holy Paladin")
        # Orc és Undead (még) nem lehet Paladin, Tauren igen.
        self.assertEqual(recommend_combo([], scores, HORDE).best.name, "Tauren Holy Paladin")
        # Evoker csak Dracthyr lehet, Demon Hunter frakciónként más fajú.
        evoker = SpecScores({"evoker/preservation": D("4100")})
        self.assertEqual(recommend_combo([], evoker, HORDE).best.name, "Dracthyr Preservation Evoker")
        vengeance = SpecScores({"demon hunter/vengeance": D("3950")})
        self.assertEqual(recommend_combo([], vengeance, ALLIANCE).best.name, "Night Elf Vengeance Demon Hunter")
        self.assertEqual(recommend_combo([], vengeance, HORDE).best.name, "Blood Elf Vengeance Demon Hunter")

    def test_rarest_role_comes_first(self):
        roster = [
            Character("A", "Warrior", "Protection"),
            Character("B", "Paladin", "Protection"),
            Character("C", "Shaman", "Restoration"),
            Character("D", "Mage"),  # spec nélkül is DPS
            Character("E", "Rogue", "Outlaw"),
        ]
        best = recommend_combo(roster, SpecScores({"warrior/arms": D("9999")}), HORDE).best
        self.assertEqual(best.role, "healer")  # tank: 2, healer: 1, DPS: 2
        self.assertEqual(best.counts[0], 1)

    def test_armor_type_beats_a_better_score(self):
        # Egy Shadow Priest után a cloth már foglalt: a legjobb pontszámú Holy Priest helyett
        # a még hiányzó páncéltípusok közül a legjobb pontszámú jön.
        scores = SpecScores({"priest/holy": D("5000"), "monk/brewmaster": D("4000"), "paladin/holy": D("3500")})
        recommendation = recommend_combo([Character("A", "Priest", "Shadow", race="Undead")], scores, HORDE)
        self.assertEqual(recommendation.best.name, "Orc Brewmaster Monk")
        self.assertEqual(recommendation.best.counts, (0, 0, 0, 0, 0))
        self.assertEqual(names(recommendation.alternatives)[0], "Tauren Holy Paladin")

    def test_class_spec_and_race_counts(self):
        roster = [
            Character("A", "Warrior", "Arms", race="Human"),
            Character("B", "Warrior", "Fury", race="Dwarf"),
            Character("C", "Priest", "Shadow", race="Human"),
        ]
        ranked = ranked_combos(roster, SpecScores(), ALLIANCE)
        by_name = {combo.name: combo for combo in ranked}
        self.assertEqual(by_name["Human Protection Warrior"].counts, (0, 2, 2, 0, 2))
        self.assertEqual(by_name["Dwarf Arms Warrior"].counts, (3, 2, 2, 1, 1))
        self.assertEqual(by_name["Night Elf Holy Priest"].counts, (0, 1, 1, 0, 0))
        # A rangsor a számok szerint növekvő.
        self.assertEqual([combo.counts for combo in ranked], sorted(combo.counts for combo in ranked))

    def test_least_used_race_is_chosen(self):
        roster = [
            Character("A", "Warrior", "Arms", race="Human"),
            Character("B", "Warrior", "Fury", race="Dwarf"),
            Character("C", "Rogue", "Outlaw", race="Night Elf"),
        ]
        scores = SpecScores({"priest/holy": D("4000")})
        self.assertEqual(recommend_combo(roster, scores, ALLIANCE).best.name, "Gnome Holy Priest")

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
        scores = SpecScores({"druid/restoration": D("3720"), "monk/mistweaver": D("3590"), "priest/holy": D("3800")})
        recommendation = recommend_combo(roster, scores, HORDE)
        self.assertEqual(recommendation.best.name, "Troll Restoration Druid")
        self.assertEqual(
            recommendation.describe(),
            "A meglévő 6 karakter között ebből van a legkevesebb (sorban a szerep, a páncéltípus, a kaszt, "
            "a spec és a faj szerint):\n"
            "• szerep – healer: 1 karakter\n"
            "• páncéltípus – leather: még egy sincs\n"
            "• kaszt – Druid: még egy sincs\n"
            "• spec – Restoration Druid: még egy sincs\n"
            "• faj – Troll: még egy sincs\n"
            "Ugyanennyire hiányzik még 1 másik class/spec is; közülük ennek a legmagasabb a Murlok.io-pontszáma "
            "(3720).\n"
            "\nUtána következnének: Troll Mistweaver Monk, Troll Holy Priest, Troll Discipline Priest.",
        )

    def test_without_scores_the_alphabet_decides(self):
        recommendation = recommend_combo([], SpecScores(), HORDE)
        self.assertEqual(recommendation.best.name, "Orc Blood Death Knight")
        self.assertIn("Murlok.io-pontszámok még nincsenek", recommendation.describe())
        self.assertTrue(recommendation.describe().startswith("Még nincs karakter a listán"))

    def test_unknown_faction(self):
        with self.assertRaises(ValueError):
            recommend_combo([], SpecScores(), "Scourge")


if __name__ == "__main__":
    unittest.main()
