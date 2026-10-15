import json
import tempfile
import unittest
from datetime import date, timedelta
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
    leveling_windows,
    load_data,
    parse_date,
    parse_level,
    parse_max_level,
    save_data,
    target_level,
)

START = date(2026, 10, 1)


def make_settings(first_days=9, last_days=29, max_level=90, mode=PARALLEL):
    return Settings(
        start_date=START,
        first_max_date=START + timedelta(days=first_days),
        last_max_date=START + timedelta(days=last_days),
        max_level=max_level,
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

    def test_max_level_must_be_an_integer_above_one(self):
        self.assertEqual(parse_max_level(" 80 "), 80)
        for text in ("1", "0", "-5", "abc", "", "1000"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_max_level(text)

    def test_level_must_be_between_one_and_max(self):
        self.assertEqual(parse_level("1", 80), 1)
        self.assertEqual(parse_level("80", 80), 80)
        for text in ("0", "81", "x"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_level(text, 80)


class SettingsTests(unittest.TestCase):
    def test_valid_settings_have_no_errors(self):
        self.assertEqual(make_settings().errors(), [])
        self.assertEqual(make_settings(first_days=0, last_days=0).errors(), [])

    def test_dates_must_be_in_order(self):
        self.assertEqual(len(make_settings(first_days=-1, last_days=5).errors()), 1)
        self.assertEqual(len(make_settings(first_days=10, last_days=5).errors()), 1)

    def test_max_level_range(self):
        self.assertEqual(len(make_settings(max_level=1).errors()), 1)


class DeadlineTests(unittest.TestCase):
    def test_single_character_uses_first_date(self):
        settings = make_settings()
        self.assertEqual(deadlines(settings, 1), [settings.first_max_date])

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


class TargetLevelTests(unittest.TestCase):
    def test_levels_grow_evenly_until_the_deadline(self):
        deadline = START + timedelta(days=9)  # 10 nap, 89 szint
        self.assertEqual(target_level(START, deadline, 90, START - timedelta(days=1)), 1)
        self.assertEqual(target_level(START, deadline, 90, START), 9)
        self.assertEqual(target_level(START, deadline, 90, START + timedelta(days=1)), 18)
        self.assertEqual(target_level(START, deadline, 90, deadline), 90)
        self.assertEqual(target_level(START, deadline, 90, deadline + timedelta(days=3)), 90)

    def test_target_is_monotonic(self):
        deadline = START + timedelta(days=40)
        levels = [target_level(START, deadline, 80, START + timedelta(days=i)) for i in range(-2, 45)]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual(levels[0], 1)
        self.assertEqual(levels[-1], 80)

    def test_one_day_window(self):
        self.assertEqual(target_level(START, START, 90, START), 90)


class PlanTests(unittest.TestCase):
    def plan_for(self, level, today, settings=None):
        settings = settings or make_settings(first_days=9, last_days=29)
        return build_plan(settings, [Character("Thrall", level=level)], today)[0]

    def test_done_when_max_level_reached(self):
        plan = self.plan_for(90, START + timedelta(days=3))
        self.assertIs(plan.status, Status.DONE)
        self.assertIsNone(plan.goal_today)
        self.assertIsNone(plan.pace)

    def test_level_above_a_lowered_max_counts_as_done(self):
        plan = self.plan_for(85, START, make_settings(max_level=80))
        self.assertIs(plan.status, Status.DONE)

    def test_not_started_before_start_date(self):
        plan = self.plan_for(1, START - timedelta(days=2))
        self.assertIs(plan.status, Status.NOT_STARTED)
        self.assertIsNone(plan.goal_today)
        self.assertAlmostEqual(plan.pace, 8.9)  # 89 szint 10 nap alatt
        self.assertEqual(plan.days_left, 10)  # a kezdés előtti napok nem számítanak

    def test_statuses_relative_to_daily_goal(self):
        today = START + timedelta(days=1)  # tegnapi cél: 9, mai cél: 18
        cases = {
            20: Status.AHEAD,
            18: Status.GOAL_MET,
            9: Status.ON_TRACK,
            12: Status.ON_TRACK,
            8: Status.BEHIND,
        }
        for level, expected in cases.items():
            with self.subTest(level=level):
                plan = self.plan_for(level, today)
                self.assertIs(plan.status, expected)
                self.assertEqual(plan.goal_today, 18)
                self.assertEqual(plan.levels_due_today, max(0, 18 - level))

    def test_first_day_with_level_one_is_on_track(self):
        plan = self.plan_for(1, START)
        self.assertIs(plan.status, Status.ON_TRACK)
        self.assertEqual(plan.goal_today, 9)

    def test_overdue_after_deadline(self):
        plan = self.plan_for(70, START + timedelta(days=10))
        self.assertIs(plan.status, Status.OVERDUE)
        self.assertEqual(plan.days_left, 0)
        self.assertEqual(plan.levels_due_today, 20)

    def test_pace_counts_today_as_available(self):
        plan = self.plan_for(50, START + timedelta(days=5))  # 40 szint, 5 nap van hátra
        self.assertEqual(plan.days_left, 5)
        self.assertAlmostEqual(plan.pace, 8.0)

    def test_plan_follows_list_order(self):
        settings = make_settings(first_days=10, last_days=20, mode=SEQUENTIAL)
        characters = [Character("A"), Character("B"), Character("C")]
        plans = build_plan(settings, characters, START)
        self.assertEqual([plan.position for plan in plans], [1, 2, 3])
        self.assertEqual([plan.character.name for plan in plans], ["A", "B", "C"])
        self.assertEqual([(plan.deadline - START).days for plan in plans], [10, 15, 20])
        self.assertEqual([plan.status for plan in plans], [Status.ON_TRACK, Status.NOT_STARTED, Status.NOT_STARTED])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "adatok.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_round_trip(self):
        data = LevelingData(
            make_settings(mode=SEQUENTIAL, max_level=80),
            [Character("Thrall", "Shaman", 23), Character("Jaina", "Mage")],
        )
        save_data(self.path, data)
        loaded = load_data(self.path)
        self.assertEqual(loaded.settings, data.settings)
        self.assertEqual(
            [(c.name, c.char_class, c.level) for c in loaded.characters],
            [("Thrall", "Shaman", 23), ("Jaina", "Mage", 1)],
        )
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [self.path])  # nem marad ideiglenes fájl

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_data(self.path)

    def test_corrupt_files_raise_value_error(self):
        for content in ("{nem json", "[]", '{"settings": {}}', '{"settings": {"start_date": 5}}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_data(self.path)

    def test_optional_fields_get_defaults(self):
        content = {
            "settings": {"start_date": "2026-10-01", "first_max_date": "2026-10-10", "last_max_date": "2026-11-01"},
            "characters": [{"name": "Arthas"}],
        }
        self.path.write_text(json.dumps(content), encoding="utf-8")
        loaded = load_data(self.path)
        self.assertEqual(loaded.settings.mode, PARALLEL)
        self.assertEqual(loaded.settings.max_level, 90)
        self.assertEqual((loaded.characters[0].char_class, loaded.characters[0].level), ("", 1))


if __name__ == "__main__":
    unittest.main()
