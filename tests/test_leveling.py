import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from leveling import (
    PARALLEL,
    SEQUENTIAL,
    Character,
    LevelingData,
    Settings,
    SpecScores,
    Status,
    _number_article,
    build_plan,
    day_progress,
    deadlines,
    format_deviation,
    format_level,
    format_raiderio_score,
    format_spec_score,
    goal_day_phrase,
    leveling_windows,
    load_data,
    lookahead_day,
    parse_date,
    parse_level,
    parse_raiderio_score,
    planned_level,
    save_data,
    sort_plans,
)

START = date(2026, 10, 1)
D = Decimal


def make_settings(first_days=9, last_days=29, start_level="1", target_level="90", mode=PARALLEL):
    return Settings(
        start_date=START,
        first_target_date=START + timedelta(days=first_days),
        last_target_date=START + timedelta(days=last_days),
        start_level=D(start_level),
        target_level=D(target_level),
        mode=mode,
    )


class ParseTests(unittest.TestCase):
    def test_accepts_iso_and_hungarian_date_formats(self):
        for text in ("2026-10-15", "2026.10.15", "2026. 10. 15.", "2026/10/15", " 2026-10-15 "):
            with self.subTest(text=text):
                self.assertEqual(parse_date(text), date(2026, 10, 15))

    def test_rejects_invalid_dates(self):
        for text in ("", "   ", "15/10/2026", "2026-13-01", "2026-02-30", "holnap", "2026-10"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_date(text)

    def test_levels_have_two_decimal_precision(self):
        cases = {"83,45": "83.45", "83.45": "83.45", " 83 ": "83.00", "7,5": "7.50", "1": "1.00", "999,99": "999.99"}
        for text, expected in cases.items():
            with self.subTest(text=text):
                value = parse_level(text)
                self.assertEqual(value, D(expected))
                self.assertEqual(value.as_tuple().exponent, -2)

    def test_rejects_invalid_levels(self):
        for text in ("", "abc", "83,456", "83,", "8 3", "-5", "0,99", "1000"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_level(text)

    def test_format_level_uses_decimal_comma(self):
        self.assertEqual(format_level(D("83.4")), "83,40")
        self.assertEqual(format_level(D("90")), "90,00")

    def test_raiderio_score_has_one_decimal(self):
        cases = {"2543,7": "2543.7", "2543.7": "2543.7", " 2543 ": "2543.0", "2,543.7": "2543.7", "2.543,7": "2543.7"}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_raiderio_score(text), D(expected))
        self.assertIsNone(parse_raiderio_score("  "))
        self.assertEqual(format_raiderio_score(D("2543")), "2543,0")
        self.assertEqual((format_spec_score(D("3891")), format_spec_score(D("3712.5"))), ("3891", "3712,5"))
        for text in ("2543,75", "abc", "-5", "100000", "2,5,4"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_raiderio_score(text)

    def test_format_deviation_is_signed(self):
        self.assertEqual(format_deviation(D("2.87")), "+2,87")
        self.assertEqual(format_deviation(D("-2.13")), "−2,13")
        self.assertEqual(format_deviation(D("0")), "0,00")
        self.assertEqual(format_deviation(D("-0.00")), "0,00")


class SettingsTests(unittest.TestCase):
    def test_valid_settings_have_no_errors(self):
        self.assertEqual(make_settings().errors(), [])
        self.assertEqual(make_settings(first_days=0, last_days=0).errors(), [])
        self.assertEqual(make_settings(start_level="80.5", target_level="80.51").errors(), [])

    def test_dates_must_be_in_order(self):
        self.assertEqual(len(make_settings(first_days=-1, last_days=5).errors()), 1)
        self.assertEqual(len(make_settings(first_days=10, last_days=5).errors()), 1)

    def test_target_level_must_be_above_start_level(self):
        self.assertEqual(len(make_settings(start_level="80", target_level="80").errors()), 1)
        self.assertEqual(len(make_settings(start_level="85", target_level="80").errors()), 1)


class DeadlineTests(unittest.TestCase):
    def test_single_character_uses_first_date(self):
        settings = make_settings()
        self.assertEqual(deadlines(settings, 1), [settings.first_target_date])

    def test_deadlines_are_spread_evenly_between_first_and_last(self):
        settings = make_settings(first_days=10, last_days=20)
        result = deadlines(settings, 3)
        self.assertEqual([(d - START).days for d in result], [10, 15, 20])

    def test_deadlines_are_rounded_to_whole_days(self):
        settings = make_settings(first_days=0, last_days=10)
        result = deadlines(settings, 4)
        self.assertEqual([(d - START).days for d in result], [0, 3, 7, 10])

    def test_no_characters(self):
        self.assertEqual(deadlines(make_settings(), 0), [])


class WindowTests(unittest.TestCase):
    def test_parallel_mode_starts_everyone_on_start_date(self):
        windows = leveling_windows(make_settings(first_days=10, last_days=20, mode=PARALLEL), 3)
        self.assertEqual([start for start, _ in windows], [START] * 3)

    def test_sequential_mode_starts_after_previous_deadline(self):
        settings = make_settings(first_days=10, last_days=20, mode=SEQUENTIAL)
        windows = leveling_windows(settings, 3)
        self.assertEqual(
            [((start - START).days, (end - START).days) for start, end in windows],
            [(0, 10), (11, 15), (16, 20)],
        )

    def test_sequential_mode_with_same_deadlines_never_starts_after_deadline(self):
        settings = make_settings(first_days=5, last_days=5, mode=SEQUENTIAL)
        for start, end in leveling_windows(settings, 3):
            self.assertLessEqual(start, end)


class PlannedLevelTests(unittest.TestCase):
    def level(self, day, days=10, from_level="1", to_level="90"):
        deadline = START + timedelta(days=days - 1)
        return planned_level(START, deadline, D(from_level), D(to_level), START + timedelta(days=day))

    def test_levels_grow_evenly_until_the_deadline(self):
        self.assertEqual(self.level(-1), D("1.00"))
        self.assertEqual(self.level(0), D("9.90"))  # 10 nap alatt 89 szint: 8,90 naponta
        self.assertEqual(self.level(1), D("18.80"))
        self.assertEqual(self.level(9), D("90.00"))
        self.assertEqual(self.level(12), D("90.00"))

    def test_works_between_any_start_and_target_level(self):
        self.assertEqual(self.level(0, days=7, from_level="80", to_level="90.5"), D("81.50"))
        self.assertEqual(self.level(2, days=7, from_level="80", to_level="90.5"), D("84.50"))

    def test_rounds_down_to_two_decimals(self):
        self.assertEqual(self.level(0, days=3, from_level="1", to_level="2"), D("1.33"))
        self.assertEqual(self.level(1, days=3, from_level="1", to_level="2"), D("1.66"))
        self.assertEqual(self.level(2, days=3, from_level="1", to_level="2"), D("2.00"))

    def test_target_is_monotonic(self):
        levels = [self.level(day, days=41, from_level="12.5", to_level="80") for day in range(-2, 45)]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual((levels[0], levels[-1]), (D("12.50"), D("80.00")))

    def test_one_day_window(self):
        self.assertEqual(planned_level(START, START, D(1), D(90), START), D(90))


class PlanTests(unittest.TestCase):
    def plan_for(self, level, today, settings=None):
        settings = settings or make_settings(first_days=9, last_days=29)
        return build_plan(settings, [Character("Thrall", level=D(level))], today)[0]

    def test_done_when_target_level_reached(self):
        plan = self.plan_for("90", START + timedelta(days=3))
        self.assertIs(plan.status, Status.DONE)
        self.assertIsNone(plan.goal)
        self.assertIsNone(plan.pace)
        self.assertEqual(plan.deviation, D("53.40"))  # a terv szerint ma estére 36,60 lenne

    def test_level_above_target_counts_as_done(self):
        plan = self.plan_for("95.5", START, make_settings(target_level="80"))
        self.assertIs(plan.status, Status.DONE)

    def test_not_started_before_start_date(self):
        plan = self.plan_for("1", START - timedelta(days=2))
        self.assertIs(plan.status, Status.NOT_STARTED)
        self.assertIsNone(plan.goal)
        self.assertEqual(plan.pace, D("8.90"))  # 89 szint 10 nap alatt
        self.assertEqual(plan.days_left, 10)  # a kezdés előtti napok nem számítanak

    def test_level_outside_range_before_start_date(self):
        settings = make_settings(start_level="80", target_level="90")
        above = self.plan_for("82.5", START - timedelta(days=2), settings)
        self.assertIs(above.status, Status.AHEAD)
        self.assertEqual(above.status_text, "Előrébb jár (+2,50 szint)")
        self.assertEqual(above.deviation, D("2.50"))
        below = self.plan_for("75.25", START - timedelta(days=2), settings)
        self.assertIs(below.status, Status.BEHIND)
        self.assertEqual(below.status_text, "Kezdőszint alatt (−4,75 szint)")
        self.assertEqual(below.deviation, D("-4.75"))
        self.assertEqual(below.pace, D("1.48"))  # 14,75 szint 10 nap alatt, felfelé kerekítve

    def test_statuses_relative_to_daily_goal(self):
        today = START + timedelta(days=1)  # tegnapi cél: 9,90, mai cél: 18,80
        cases = {
            "20": Status.AHEAD,
            "18.81": Status.AHEAD,
            "18.8": Status.GOAL_MET,
            "18.79": Status.ON_TRACK,
            "9.9": Status.ON_TRACK,
            "9.89": Status.BEHIND,
        }
        for level, expected in cases.items():
            with self.subTest(level=level):
                plan = self.plan_for(level, today)
                self.assertIs(plan.status, expected)
                self.assertEqual(plan.goal, D("18.80"))
                self.assertEqual(plan.deviation, D(level) - D("18.80"))
                self.assertEqual(plan.levels_due, max(D(0), D("18.80") - D(level)))

    def test_status_text_uses_two_decimals(self):
        plan = self.plan_for("12.34", START + timedelta(days=1))
        self.assertEqual(plan.status_text, "Ütemben – ma még 6,46 szint")

    def test_first_day_at_start_level_is_on_track(self):
        plan = self.plan_for("1", START)
        self.assertIs(plan.status, Status.ON_TRACK)
        self.assertEqual(plan.goal, D("9.90"))

    def test_below_start_level_during_leveling_is_behind(self):
        settings = make_settings(start_level="80", target_level="90")
        plan = self.plan_for("75", START, settings)
        self.assertIs(plan.status, Status.BEHIND)
        self.assertEqual(plan.goal, D("81.00"))
        self.assertEqual(plan.status_text, "Lemaradásban – ma még 6,00 szint")

    def test_overdue_after_deadline(self):
        plan = self.plan_for("70.25", START + timedelta(days=10))
        self.assertIs(plan.status, Status.OVERDUE)
        self.assertEqual(plan.days_left, 0)
        self.assertEqual(plan.deviation, D("-19.75"))
        self.assertEqual(plan.levels_due, D("19.75"))
        self.assertEqual(plan.status_text, "Lejárt a céldátum – még 19,75 szint")

    def test_pace_counts_today_and_rounds_up(self):
        plan = self.plan_for("50", START + timedelta(days=5))  # 40 szint, 5 nap van hátra
        self.assertEqual((plan.days_left, plan.pace), (5, D("8.00")))
        plan = self.plan_for("80", START + timedelta(days=7))  # 10 szint 3 nap alatt
        self.assertEqual((plan.days_left, plan.pace), (3, D("3.34")))

    def test_plan_follows_list_order(self):
        settings = make_settings(first_days=10, last_days=20, mode=SEQUENTIAL)
        characters = [Character("A"), Character("B"), Character("C")]
        plans = build_plan(settings, characters, START)
        self.assertEqual([plan.position for plan in plans], [1, 2, 3])
        self.assertEqual([plan.character.name for plan in plans], ["A", "B", "C"])
        self.assertEqual([(plan.deadline - START).days for plan in plans], [10, 15, 20])
        self.assertEqual([plan.status for plan in plans], [Status.ON_TRACK, Status.NOT_STARTED, Status.NOT_STARTED])


class LookAheadTests(unittest.TestCase):
    """Egy karakter, 10 nap alatt 1,00 → 90,00: a napi célok 9,90; 18,80; 27,70; 36,60 …"""

    def day(self, *levels, today=START, settings=None):
        settings = settings or make_settings(first_days=9, last_days=29)
        return lookahead_day(settings, [Character(f"K{i}", level=D(level)) for i, level in enumerate(levels)], today)

    def test_moves_on_while_every_goal_is_met(self):
        self.assertEqual(self.day("9.89"), START)  # a mai cél sincs meg
        self.assertEqual(self.day("9.9"), START + timedelta(days=1))  # a mai megvan → a holnapi
        self.assertEqual(self.day("27.7"), START + timedelta(days=3))  # a 3. napé is megvan

    def test_every_character_has_to_meet_the_goal(self):
        # A második karakter (30 napos terv) mai célja 3,96, ezt nem érte el.
        self.assertEqual(self.day("9.9", "1"), START)
        self.assertEqual(self.day("9.9", "3.96"), START + timedelta(days=1))

    def test_stays_on_today_when_nothing_to_look_ahead_to(self):
        self.assertEqual(self.day("90"), START)  # mindenki elérte a célszintet
        self.assertEqual(self.day("70", today=START + timedelta(days=12)), START + timedelta(days=12))  # a terv véget ért
        self.assertEqual(lookahead_day(make_settings(), [], START), START)

    def test_before_the_start_date(self):
        self.assertEqual(self.day("1", today=START - timedelta(days=2)), START)

    def test_goal_day_phrase(self):
        cases = {0: "a mai", 1: "a holnapi", 2: "a holnaputáni", 17: "az október 18-i", 33: "a november 3-i"}
        for offset, phrase in cases.items():
            with self.subTest(offset=offset):
                self.assertEqual(goal_day_phrase(START + timedelta(days=offset), START), phrase)

    def test_plan_for_a_later_goal_day(self):
        tomorrow = START + timedelta(days=1)
        plan = build_plan(make_settings(), [Character("A", level=D("9.9"))], START, goal_day=tomorrow)[0]
        self.assertEqual((plan.goal, plan.deviation, plan.status), (D("18.80"), D("-8.90"), Status.ON_TRACK))
        self.assertEqual(plan.status_text, "Ütemben – a holnapi célig még 8,90 szint")
        self.assertEqual((plan.days_left, plan.pace), (10, D("8.01")))  # a valódi mai naptól számolva
        plan = build_plan(make_settings(), [Character("A", level=D("18.8"))], START, goal_day=tomorrow)[0]
        self.assertEqual((plan.status, plan.status_text), (Status.GOAL_MET, "A holnapi cél teljesítve"))


class SortTests(unittest.TestCase):
    def plans(self, *levels, today=START + timedelta(days=1)):
        characters = [Character(name, level=D(level)) for name, level in zip("ABCDE", levels)]
        return build_plan(make_settings(first_days=9, last_days=29), characters, today)

    @staticmethod
    def names(plans):
        return [plan.character.name for plan in plans]

    def test_sort_by_deviation(self):
        plans = self.plans("10", "20", "3")  # mai célok: 18,80 / 9,90 / 6,93
        self.assertEqual([plan.deviation for plan in plans], [D("-8.80"), D("10.10"), D("-3.93")])
        self.assertEqual(self.names(sort_plans(plans, "deviation")), ["A", "C", "B"])
        self.assertEqual(self.names(sort_plans(plans, "deviation", descending=True)), ["B", "C", "A"])
        self.assertEqual(self.names(sort_plans(plans)), ["A", "B", "C"])  # alapból az eredeti sorrend

    def test_sort_by_status_puts_most_urgent_first(self):
        plans = self.plans("10", "20", "3")
        self.assertEqual([plan.status for plan in plans], [Status.ON_TRACK, Status.AHEAD, Status.BEHIND])
        self.assertEqual(self.names(sort_plans(plans, "status")), ["C", "A", "B"])

    def test_missing_values_stay_last(self):
        plans = self.plans("10", "90", "3")  # B kész, nincs mai célja
        self.assertEqual(self.names(sort_plans(plans, "goal")), ["C", "A", "B"])
        self.assertEqual(self.names(sort_plans(plans, "goal", descending=True)), ["A", "C", "B"])

    def test_equal_values_keep_list_order(self):
        plans = self.plans("5", "5", "1")
        self.assertEqual(self.names(sort_plans(plans, "level")), ["C", "A", "B"])
        self.assertEqual(self.names(sort_plans(plans, "level", descending=True)), ["A", "B", "C"])

    def test_sort_by_spec_and_by_class_then_spec(self):
        characters = [
            Character("A", "Mage", "Frost"),
            Character("B", "Death Knight", "Unholy"),
            Character("C"),
            Character("D", "Mage", "Arcane"),
            Character("E", "Death Knight", "Blood"),
        ]
        plans = build_plan(make_settings(), characters, START)
        self.assertEqual(self.names(sort_plans(plans, "spec")), ["D", "E", "A", "B", "C"])
        self.assertEqual(self.names(sort_plans(plans, "class")), ["E", "B", "D", "A", "C"])

    def test_sort_by_race_and_realm(self):
        characters = [
            Character("A", race="Orc", realm="Ragnaros"),
            Character("B", race="Human"),
            Character("C", race="Dwarf", realm="Draenor"),
        ]
        plans = build_plan(make_settings(), characters, START)
        self.assertEqual(self.names(sort_plans(plans, "race")), ["C", "B", "A"])
        self.assertEqual(self.names(sort_plans(plans, "realm")), ["C", "A", "B"])

    def test_sort_by_raiderio_score(self):
        characters = [
            Character("A", raiderio_score=D("2543.7")),
            Character("B"),
            Character("C", raiderio_score=D("3012.4")),
        ]
        plans = build_plan(make_settings(), characters, START)
        self.assertEqual(self.names(sort_plans(plans, "raiderio")), ["A", "C", "B"])
        self.assertEqual(self.names(sort_plans(plans, "raiderio", descending=True)), ["C", "A", "B"])

    def test_names_follow_hungarian_alphabet(self):
        names = ["Zoli", "Ödön", "Oszkár", "Ábel", "abel"]
        plans = build_plan(make_settings(), [Character(name) for name in names], START)
        self.assertEqual(self.names(sort_plans(plans, "name")), ["abel", "Ábel", "Oszkár", "Ödön", "Zoli"])


class DayProgressTests(unittest.TestCase):
    """Egy karakter, 10 nap alatt 1,00 → 90,00: naponta 8,90 szint."""

    def progress(self, *levels, day=5, settings=None):
        settings = settings or make_settings(first_days=9, last_days=29)
        characters = [Character(f"K{index}", level=D(level)) for index, level in enumerate(levels)]
        return day_progress(settings, characters, START + timedelta(days=day - 1))

    def test_reached_day_compared_with_today(self):
        cases = {
            "30": (3, "Ma a szintezés 5. napja van (összesen 10 nap). A karakter a 3. nap szintjén áll – "
                   "2 nappal a mai cél mögött."),
            "50": (5, "Ma a szintezés 5. napja van (összesen 10 nap). A karakter az 5. nap szintjén áll – "
                   "pont a mai célnál."),
            "70": (7, "Ma a szintezés 5. napja van (összesen 10 nap). A karakter a 7. nap szintjén áll – "
                   "2 nappal a terv előtt."),
            "1": (0, "Ma a szintezés 5. napja van (összesen 10 nap). A karakter még az 1. nap szintjét sem "
                  "érte el – 5 nappal a mai cél mögött."),
        }
        for level, (reached, text) in cases.items():
            with self.subTest(level=level):
                progress = self.progress(level)
                self.assertEqual((progress.today, progress.total_days, progress.reached_day), (5, 10, reached))
                self.assertEqual(progress.days_ahead, reached - 5)
                self.assertEqual(progress.describe(), text)

    def test_finished(self):
        progress = self.progress("90")
        self.assertTrue(progress.finished)
        self.assertEqual(progress.describe(), "A szintezés kész: minden karakter elérte a célszintet.")

    def test_before_start_and_after_end(self):
        self.assertEqual(self.progress("1", day=-2).describe(), "A szintezés 3 nap múlva kezdődik.")
        self.assertEqual(
            self.progress("20", day=0).describe(), "A szintezés holnap kezdődik. A karakter a 2. nap szintjén áll."
        )
        self.assertEqual(
            self.progress("70", day=13).describe(),
            "A tervezett 10 nap letelt. A karakter a 7. nap szintjén áll – 3 nappal a mai cél mögött.",
        )

    def test_all_characters_count_together(self):
        # Céldátumok: 10., 20. és 30. nap; a 10. napon a tervezett összes szintlépés 163,16,
        # a 11. napon 170,58. A karakterek összesen 89 + 49 + 29 = 167 szintet léptek.
        progress = self.progress("90", "50", "30", day=10)
        self.assertEqual((progress.total_days, progress.reached_day, progress.days_ahead), (30, 10, 0))
        self.assertEqual(
            progress.describe(),
            "Ma a szintezés 10. napja van (összesen 30 nap). A karakterek együtt a 10. nap szintjén állnak – "
            "pont a mai célnál.",
        )

    def test_levels_below_start_level_count_as_deficit(self):
        settings = make_settings(start_level="80", target_level="90")
        progress = self.progress("75", "80", day=1, settings=settings)
        self.assertEqual(progress.reached_day, 0)
        self.assertEqual(
            progress.describe(),
            "Ma a szintezés 1. napja van (összesen 30 nap). A karakterek együtt még az 1. nap szintjét sem "
            "érték el – 1 nappal a mai cél mögött.",
        )

    def test_sequential_plan(self):
        settings = make_settings(first_days=9, last_days=19, mode=SEQUENTIAL)
        progress = self.progress("90", "1", day=15, settings=settings)  # a második karakter a 11. napon kezd
        self.assertEqual((progress.reached_day, progress.days_ahead), (10, -5))

    def test_no_characters(self):
        self.assertIsNone(day_progress(make_settings(), [], START))

    def test_article_before_numbers(self):
        expected = {1: "az", 2: "a", 5: "az", 10: "a", 15: "a", 50: "az", 51: "az", 100: "a", 1000: "az", 1500: "az"}
        self.assertEqual({number: _number_article(number) for number in expected}, expected)


class SpecScoresTests(unittest.TestCase):
    def test_lookup_by_class_and_spec(self):
        scores = SpecScores({SpecScores.spec_key("Death Knight", "Unholy"): D("3891")})
        self.assertEqual(scores.score_for(Character("A", "death knight", " unholy ")), D("3891"))
        self.assertIsNone(scores.score_for(Character("B", "Death Knight", "Blood")))
        self.assertIsNone(scores.score_for(Character("C", "Death Knight")))

    def test_staleness_follows_murlok_refresh_interval(self):
        fetched = datetime(2026, 10, 15, 12, 0)
        scores = SpecScores({}, fetched)
        self.assertFalse(scores.is_stale(fetched + timedelta(hours=7, minutes=59)))
        self.assertTrue(scores.is_stale(fetched + timedelta(hours=8)))
        self.assertTrue(SpecScores().is_stale())

    def test_plan_rows_get_the_spec_score_and_sort_by_it(self):
        scores = SpecScores({"mage/frost": D("3500"), "paladin/holy": D("4050")}, datetime(2026, 10, 15, 12, 0))
        characters = [Character("A", "Mage", "Frost"), Character("B", "Mage"), Character("C", "Paladin", "Holy")]
        plans = build_plan(make_settings(), characters, START, scores)
        self.assertEqual([plan.spec_score for plan in plans], [D("3500"), None, D("4050")])
        self.assertEqual([p.character.name for p in sort_plans(plans, "murlok", descending=True)], ["C", "A", "B"])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "adatok.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_round_trip(self):
        data = LevelingData(
            make_settings(mode=SEQUENTIAL, start_level="80", target_level="90.5"),
            [
                Character(
                    "Thrall", "Shaman", "Enhancement", D("83.45"), race="Orc", realm="Draenor", raiderio_score=D("2543.7")
                ),
                Character("Jaina", "Mage", level=D("1.00")),
            ],
        )
        save_data(self.path, data)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["characters"][0]["level"], 83.45)  # olvasható szám a fájlban
        self.assertEqual(raw["characters"][0]["raiderio_score"], 2543.7)
        self.assertIsNone(raw["characters"][1]["raiderio_score"])
        loaded = load_data(self.path)
        self.assertEqual(loaded.settings, data.settings)
        self.assertEqual(
            [(c.name, c.realm, c.race, c.char_class, c.spec, c.level, c.raiderio_score) for c in loaded.characters],
            [
                ("Thrall", "Draenor", "Orc", "Shaman", "Enhancement", D("83.45"), D("2543.7")),
                ("Jaina", "", "", "Mage", "", D("1.00"), None),
            ],
        )
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [self.path])  # nem marad ideiglenes fájl

    def test_spec_scores_are_saved(self):
        scores = SpecScores({"mage/frost": D("3500.5")}, datetime(2026, 10, 15, 20, 13, 5))
        save_data(self.path, LevelingData(make_settings(), [], scores))
        loaded = load_data(self.path).spec_scores
        self.assertEqual((loaded.scores, loaded.fetched_at), (scores.scores, scores.fetched_at))

    def test_look_ahead_switch_is_saved(self):
        save_data(self.path, LevelingData(make_settings(), look_ahead=False))
        self.assertFalse(load_data(self.path).look_ahead)
        save_data(self.path, LevelingData(make_settings()))
        self.assertTrue(load_data(self.path).look_ahead)  # alapból bekapcsolva

    def test_broken_spec_score_cache_does_not_lose_data(self):
        content = {
            "settings": {"start_date": "2026-10-01", "first_target_date": "2026-10-10", "last_target_date": "2026-11-01"},
            "characters": [{"name": "Arthas"}],
            "spec_scores": {"fetched_at": "nem dátum", "scores": {}},
        }
        self.path.write_text(json.dumps(content), encoding="utf-8")
        loaded = load_data(self.path)
        self.assertEqual([c.name for c in loaded.characters], ["Arthas"])
        self.assertIsNone(loaded.spec_scores.fetched_at)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_data(self.path)

    def test_corrupt_files_raise_value_error(self):
        settings = '{"start_date": "2026-10-01", "first_target_date": "2026-10-10", "last_target_date": "2026-11-01"}'
        contents = (
            "{nem json",
            "[]",
            '{"settings": {}}',
            '{"settings": {"start_date": 5}}',
            '{"settings": %s, "characters": [{"name": "A", "level": "sok"}]}' % settings,
            '{"settings": %s, "characters": [{"name": "A", "level": NaN}]}' % settings,
        )
        for content in contents:
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_data(self.path)

    def test_optional_fields_get_defaults(self):
        content = {
            "settings": {
                "start_date": "2026-10-01",
                "first_target_date": "2026-10-10",
                "last_target_date": "2026-11-01",
                "start_level": 80,
            },
            "characters": [{"name": "Arthas"}],
        }
        self.path.write_text(json.dumps(content), encoding="utf-8")
        loaded = load_data(self.path)
        self.assertEqual(loaded.settings.mode, PARALLEL)
        self.assertEqual((loaded.settings.start_level, loaded.settings.target_level), (D("80.00"), D("90.00")))
        arthas = loaded.characters[0]
        self.assertEqual(
            (arthas.realm, arthas.race, arthas.char_class, arthas.spec, arthas.level, arthas.raiderio_score),
            ("", "", "", "", D("80.00"), None),
        )

    def test_reads_files_of_the_first_version(self):
        content = {
            "version": 1,
            "settings": {
                "start_date": "2026-10-01",
                "first_max_date": "2026-10-10",
                "last_max_date": "2026-11-01",
                "max_level": 80,
                "mode": "sequential",
            },
            "characters": [{"name": "Thrall", "class": "Shaman", "level": 23}],
        }
        self.path.write_text(json.dumps(content), encoding="utf-8")
        loaded = load_data(self.path)
        self.assertEqual(
            loaded.settings,
            Settings(date(2026, 10, 1), date(2026, 10, 10), date(2026, 11, 1), D("1.00"), D("80.00"), SEQUENTIAL),
        )
        self.assertEqual((loaded.characters[0].spec, loaded.characters[0].level), ("", D("23.00")))


if __name__ == "__main__":
    unittest.main()
