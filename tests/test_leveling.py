import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from leveling import (
    PARALLEL,
    SEQUENTIAL,
    Character,
    LevelingData,
    Settings,
    Status,
    build_plan,
    deadlines,
    format_deviation,
    format_level,
    leveling_windows,
    load_data,
    parse_date,
    parse_level,
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
        self.assertIsNone(plan.goal_today)
        self.assertIsNone(plan.pace)
        self.assertEqual(plan.deviation, D("53.40"))  # a terv szerint ma estére 36,60 lenne

    def test_level_above_target_counts_as_done(self):
        plan = self.plan_for("95.5", START, make_settings(target_level="80"))
        self.assertIs(plan.status, Status.DONE)

    def test_not_started_before_start_date(self):
        plan = self.plan_for("1", START - timedelta(days=2))
        self.assertIs(plan.status, Status.NOT_STARTED)
        self.assertIsNone(plan.goal_today)
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
                self.assertEqual(plan.goal_today, D("18.80"))
                self.assertEqual(plan.deviation, D(level) - D("18.80"))
                self.assertEqual(plan.levels_due_today, max(D(0), D("18.80") - D(level)))

    def test_status_text_uses_two_decimals(self):
        plan = self.plan_for("12.34", START + timedelta(days=1))
        self.assertEqual(plan.status_text, "Ütemben – ma még 6,46 szint")

    def test_first_day_at_start_level_is_on_track(self):
        plan = self.plan_for("1", START)
        self.assertIs(plan.status, Status.ON_TRACK)
        self.assertEqual(plan.goal_today, D("9.90"))

    def test_below_start_level_during_leveling_is_behind(self):
        settings = make_settings(start_level="80", target_level="90")
        plan = self.plan_for("75", START, settings)
        self.assertIs(plan.status, Status.BEHIND)
        self.assertEqual(plan.goal_today, D("81.00"))
        self.assertEqual(plan.status_text, "Lemaradásban – ma még 6,00 szint")

    def test_overdue_after_deadline(self):
        plan = self.plan_for("70.25", START + timedelta(days=10))
        self.assertIs(plan.status, Status.OVERDUE)
        self.assertEqual(plan.days_left, 0)
        self.assertEqual(plan.deviation, D("-19.75"))
        self.assertEqual(plan.levels_due_today, D("19.75"))
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

    def test_names_follow_hungarian_alphabet(self):
        names = ["Zoli", "Ödön", "Oszkár", "Ábel", "abel"]
        plans = build_plan(make_settings(), [Character(name) for name in names], START)
        self.assertEqual(self.names(sort_plans(plans, "name")), ["abel", "Ábel", "Oszkár", "Ödön", "Zoli"])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "adatok.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_round_trip(self):
        data = LevelingData(
            make_settings(mode=SEQUENTIAL, start_level="80", target_level="90.5"),
            [Character("Thrall", "Shaman", D("83.45")), Character("Jaina", "Mage", D("1.00"))],
        )
        save_data(self.path, data)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["characters"][0]["level"], 83.45)  # olvasható szám a fájlban
        loaded = load_data(self.path)
        self.assertEqual(loaded.settings, data.settings)
        self.assertEqual(
            [(c.name, c.char_class, c.level) for c in loaded.characters],
            [("Thrall", "Shaman", D("83.45")), ("Jaina", "Mage", D("1.00"))],
        )
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [self.path])  # nem marad ideiglenes fájl

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
        self.assertEqual((loaded.characters[0].char_class, loaded.characters[0].level), ("", D("80.00")))

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
        self.assertEqual(loaded.characters[0].level, D("23.00"))


if __name__ == "__main__":
    unittest.main()
