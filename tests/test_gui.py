"""A grafikus felület tesztjei. Grafikus kijelző kell hozzájuk (Linuxon pl. xvfb-run);
ha nincs, vagy hiányzik a tkinter, a tesztek kimaradnak."""

import tempfile
import time
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = ttk = None

from leveling import SEQUENTIAL, SpecScores, format_date, load_data

D = Decimal


@unittest.skipIf(tk is None, "a tkinter nincs telepítve")
class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"nincs elérhető grafikus kijelző ({exc})")
        import wow_leveling

        self.gui = wow_leveling
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "adatok.json"
        self.app = wow_leveling.App(self.root, self.path)

    def tearDown(self):
        self.root.destroy()
        self.temp_dir.cleanup()

    def add(self, *names, level="", char_class="", spec="", race="", realm="", score="", item_level=""):
        for name in names:
            self.app.name_var.set(name)
            self.app.raiderio_var.set(score)
            self.app.item_level_var.set(item_level)
            self.app.realm_var.set(realm)
            self.app.race_var.set(race)
            self.app.class_var.set(char_class)
            self.app.spec_var.set(spec)
            self.app.new_level_var.set(level)
            self.app.add_character()

    def rows(self, window=None):
        """A lista (vagy a megadott listaablak) sorai a nézet sorrendjében, oszlopazonosító szerint."""
        window = window or self.app.list_window
        tree = window.tree
        columns = [column[0] for column in window.COLUMNS]
        return [
            {key: str(value) for key, value in zip(columns, tree.item(iid, "values"))} for iid in tree.get_children()
        ]

    def names(self, window=None):
        return [row["name"] for row in self.rows(window)]

    def find_button(self, widget, text):
        """A widget alatt az adott feliratú gomb (vagy None)."""
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button) and child.cget("text") == text:
                return child
            found = self.find_button(child, text)
            if found is not None:
                return found
        return None

    def select(self, character):
        window = self.app.list_window
        window.tree.selection_set(character.uid)
        window._sync_selection()

    def test_added_characters_are_saved_and_listed_in_a_new_window(self):
        self.add("Thrall", "Jaina")
        self.assertEqual([c.name for c in load_data(self.path).characters], ["Thrall", "Jaina"])
        self.assertIsNone(self.app.list_window)

        self.app.open_list()
        window = self.app.list_window
        self.assertIsInstance(window, tk.Toplevel)
        self.assertEqual(self.names(), ["Thrall", "Jaina"])

        self.app.open_list()  # a már nyitott ablakot csak előtérbe hozza
        self.assertIs(self.app.list_window, window)

        self.add("Arthas")  # a nyitott lista azonnal frissül, és kijelöli az új karaktert
        self.assertEqual(self.names(), ["Thrall", "Jaina", "Arthas"])
        self.assertEqual(window.selected_var.get(), "Arthas")

        window.close()
        self.assertIsNone(self.app.list_window)

    def test_gear_button_opens_a_separate_copy_of_the_list(self):
        self.add("Thrall", "Jaina")
        self.find_button(self.root, "Gear").invoke()
        gear = self.app.gear_window
        self.assertIsInstance(gear, self.gui.GearWindow)
        self.assertEqual(gear.title(), f"Gear – {self.gui.APP_TITLE}")
        self.assertIsNone(self.app.list_window)  # a karakterlista külön ablak
        self.assertEqual(self.names(gear), ["Thrall", "Jaina"])
        self.app.open_gear()  # a már nyitott ablakot csak előtérbe hozza
        self.assertIs(self.app.gear_window, gear)

        self.app.open_list()
        window = self.app.list_window
        list_rows = self.rows(window)  # a karakterlista oszlopai a Gear ablakban is ugyanazt mutatják
        self.assertEqual([{key: row[key] for key in list_rows[0]} for row in self.rows(gear)], list_rows)
        self.assertEqual((self.app.gear_sort, self.app.list_sort), (self.gui.GEAR_ORDER, self.gui.PLAN_ORDER))
        gear.sort_by("name")  # saját rendezése van
        self.assertEqual((self.names(gear), self.names(window)), (["Jaina", "Thrall"], ["Thrall", "Jaina"]))
        self.assertEqual((self.app.gear_sort, self.app.list_sort), (("name", False), self.gui.PLAN_ORDER))

        self.add("Arthas")  # minden változás mindkét ablakban azonnal látszik
        self.assertEqual(self.names(gear), ["Arthas", "Jaina", "Thrall"])
        self.assertEqual(self.names(window), ["Thrall", "Jaina", "Arthas"])
        gear.close()
        self.assertIsNone(self.app.gear_window)
        self.assertIs(self.app.list_window, window)
        self.app.open_gear()
        self.assertEqual(self.names(self.app.gear_window), ["Arthas", "Jaina", "Thrall"])  # a rendezés megmarad

    def test_gear_window_plans_item_levels(self):
        self.app.target_item_level_var.set("330")
        self.app.data.spec_scores = SpecScores(
            {"paladin/holy": D("4050"), "mage/frost": D("3575"), "warrior/arms": D("3500")}
        )
        self.add("Jaina", char_class="Mage", spec="Frost", item_level="321")
        self.add("Uther", char_class="Paladin", spec="Holy", item_level="325")
        self.add("Varian", char_class="Warrior", spec="Arms", item_level="310")
        self.add("Anduin")  # nincs itemlevel
        self.app.open_gear()
        gear = self.app.gear_window
        columns = [column[0] for column in gear.COLUMNS]
        start = columns.index("item_level")  # az „Itemlevel” után következnek
        self.assertEqual(
            columns[start : start + 4], ["item_level", "planned_item_level", "item_level_deviation", "raiderio"]
        )
        # Murlok.io-sorrend: Uther, Jaina, Varian, Anduin; X = 5, így a tervezett itemlevel 325, 320, 315, 310.
        # Az eltérés szerint rendezve az 1. sor negatív, a 2. sorban 0 áll.
        self.assertEqual(
            [(row["name"], row["planned_item_level"], row["item_level_deviation"]) for row in self.rows(gear)],
            [
                ("Varian", "315,00", "−5,00"),
                ("Uther", "325,00", "0,00"),
                ("Jaina", "320,00", "+1,00"),
                ("Anduin", "310,00", "–"),
            ],
        )
        self.assertEqual(gear.tree.heading("item_level_deviation", "text"), "Itemlevel-eltérés ▲")
        self.assertEqual(
            gear.gear_info_var.get(),
            "Célitemlevel: 330,00   ·   X = 5,00 (ennyivel csökken a tervezett itemlevel karakterenként)",
        )

        self.app.target_item_level_var.set("")  # célitemlevel nélkül nincs terv
        self.assertEqual({row["planned_item_level"] for row in self.rows(gear)}, {"–"})
        self.assertEqual(
            gear.gear_info_var.get(), "Tervezett itemlevel: nincs megadva célitemlevel (a főablakban adhatod meg)."
        )
        self.app.open_list()  # a karakterlistában nincsenek ilyen oszlopok
        self.assertNotIn("planned_item_level", [column[0] for column in self.app.list_window.COLUMNS])

    def test_new_character_level_defaults_to_start_level(self):
        self.app.start_level_var.set("80")
        self.add("Thrall")
        self.add("Jaina", level="72,35")  # a kezdőszint alatt is lehet
        self.add("Arthas", level="95.5")  # a célszint felett is lehet
        self.assertEqual([c.level for c in self.app.data.characters], [D("80.00"), D("72.35"), D("95.50")])
        self.assertEqual(self.app.new_level_var.get(), "")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            self.add("Sylvanas", level="45,678")
        warning.assert_called_once()
        self.assertEqual(len(self.app.data.characters), 3)

    def test_spec_is_saved_and_shown_in_the_list(self):
        self.add("Thrall", char_class="Shaman", spec="Enhancement")
        self.add("Jaina", char_class="Mage")
        self.assertEqual((self.app.class_var.get(), self.app.spec_var.get()), ("", ""))
        saved = load_data(self.path).characters
        self.assertEqual([(c.char_class, c.spec) for c in saved], [("Shaman", "Enhancement"), ("Mage", "")])

        self.app.open_list()
        window = self.app.list_window
        self.assertEqual([(row["class"], row["spec"]) for row in self.rows()], [("Shaman", "Enhancement"), ("Mage", "–")])
        self.select(self.app.data.characters[0])
        self.assertEqual(window.selected_var.get(), "Thrall (Shaman, Enhancement)")
        window.sort_by("spec")
        window.sort_by("spec")  # csökkenő sorrendben is a spec nélküli karakter marad a végén
        self.assertEqual(self.names(), ["Thrall", "Jaina"])

    def test_realm_and_race_are_saved_and_shown(self):
        self.add("Thrall", realm="Draenor", race="Orc", char_class="Shaman", spec="Enhancement")
        self.add("Jaina", realm="Ragnaros", race="Human")
        self.add("Arthas")
        self.assertEqual((self.app.realm_var.get(), self.app.race_var.get()), ("", ""))
        saved = load_data(self.path).characters
        self.assertEqual([(c.realm, c.race) for c in saved], [("Draenor", "Orc"), ("Ragnaros", "Human"), ("", "")])
        # a realm mező a már használt realmeket ajánlja
        self.assertEqual(self.root.tk.splitlist(self.app.realm_box.cget("values")), ("Draenor", "Ragnaros"))

        self.app.open_list()
        window = self.app.list_window
        self.assertEqual(
            [(row["realm"], row["race"]) for row in self.rows()], [("Draenor", "Orc"), ("Ragnaros", "Human"), ("–", "–")]
        )
        self.select(self.app.data.characters[0])
        self.assertEqual(window.selected_var.get(), "Thrall-Draenor (Orc Shaman, Enhancement)")
        self.select(self.app.data.characters[1])
        self.assertEqual(window.selected_var.get(), "Jaina-Ragnaros (Human)")
        window.sort_by("race")
        self.assertEqual(self.names(), ["Jaina", "Thrall", "Arthas"])

    def test_item_level_is_saved_shown_and_sortable(self):
        self.add("Thrall", item_level="327")
        self.add("Jaina")
        self.add("Arthas", item_level="329.55")  # két tizedesjegyig
        self.assertEqual(self.app.item_level_var.get(), "")
        saved = load_data(self.path).characters
        self.assertEqual([c.item_level for c in saved], [D("327"), None, D("329.55")])
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            self.add("Sylvanas", item_level="sok")
            self.add("Sylvanas", item_level="326,555")
        self.assertEqual(warning.call_count, 2)
        self.assertEqual(len(self.app.data.characters), 3)

        self.app.open_list()
        self.assertEqual([row["item_level"] for row in self.rows()], ["327,00", "–", "329,55"])
        self.app.list_window.sort_by("item_level")
        self.app.list_window.sort_by("item_level")  # csökkenő: a legnagyobb itemlevel elöl
        self.assertEqual(self.names(), ["Arthas", "Thrall", "Jaina"])

    def test_raiderio_score_is_saved_shown_and_sortable(self):
        self.add("Thrall", score="2543,7")
        self.add("Jaina")
        self.add("Arthas", score="3,012.4")  # a weboldalról másolt, ezres elválasztós alak is jó
        self.assertEqual(self.app.raiderio_var.get(), "")
        saved = load_data(self.path).characters
        self.assertEqual([c.raiderio_score for c in saved], [D("2543.7"), None, D("3012.4")])
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            self.add("Sylvanas", score="2543,75")
        warning.assert_called_once()
        self.assertEqual(len(self.app.data.characters), 3)

        self.app.open_list()
        window = self.app.list_window
        self.assertEqual([row["raiderio"] for row in self.rows()], ["2543,7", "–", "3012,4"])
        window.sort_by("raiderio")
        window.sort_by("raiderio")  # csökkenő: a legjobb pontszám elöl, a pontszám nélküli a végén
        self.assertEqual(self.names(), ["Arthas", "Thrall", "Jaina"])

    def fetch_app(self, fetch):
        """Egy második főablak, amely a megadott függvénnyel „kéri le” a spec-pontszámokat."""
        return self.gui.App(tk.Toplevel(self.root), Path(self.temp_dir.name) / "lekeres.json", fetch_scores=fetch)

    def wait_for_fetch(self, app):
        for _ in range(200):
            self.root.update()
            if app.can_fetch_scores():
                return
            time.sleep(0.01)
        self.fail("a háttérben futó lekérés nem fejeződött be")

    def test_spec_scores_column_is_filled_in_the_background(self):
        calls = []

        def fetch():
            calls.append(1)
            return {"death knight/unholy": D("3891"), "paladin/holy": D("4050")}

        app = self.fetch_app(fetch)
        for name, char_class, spec in (("Arthas", "Death Knight", "Unholy"), ("Uther", "paladin", "holy"), ("Jaina", "Mage", "")):
            app.name_var.set(name)
            app.class_var.set(char_class)
            app.spec_var.set(spec)
            app.add_character()
        app.open_list()  # még nincs tárolt adat, ezért a lista megnyitásakor elindul a lekérés
        self.assertIn("folyamatban", app.score_status_var.get())
        self.assertIn("disabled", app.list_window.score_button.state())
        self.wait_for_fetch(app)
        self.assertEqual(len(calls), 1)
        tree = app.list_window.tree
        self.assertEqual([tree.set(iid, "murlok") for iid in tree.get_children()], ["3891", "4050", "–"])
        self.assertTrue(app.score_status_var.get().startswith("Murlok.io-pontszámok: "))
        self.assertEqual(load_data(app.data_path).spec_scores.scores["paladin/holy"], D("4050"))

        app.list_window.close()
        app.open_list()  # friss adatnál nincs újabb lekérés
        self.assertEqual(len(calls), 1)
        app.list_window.sort_by("murlok")
        app.list_window.sort_by("murlok")
        self.assertEqual(app.list_window.tree.get_children()[0], app.data.characters[1].uid)  # Uther: 4050

    def test_failed_spec_score_fetch_is_reported(self):
        def fetch():
            raise self.gui.murlok.MurlokError("a Murlok.io nem érhető el (teszt).")

        app = self.fetch_app(fetch)
        app.open_list()
        self.wait_for_fetch(app)
        self.assertEqual(
            app.score_status_var.get(), "Murlok.io: a Murlok.io nem érhető el (teszt)."
        )
        self.assertNotIn("disabled", app.list_window.score_button.state())  # újra lehet próbálni

    def test_look_ahead_shows_next_goals_when_todays_are_met(self):
        today = date.today()
        self.app.start_var.set(format_date(today))
        self.app.first_var.set(format_date(today + timedelta(days=9)))
        self.add("Thrall", level="9,9")  # 10 napos terv: a mai cél 9,90, a holnapi 18,80
        self.app.open_list()
        window = self.app.list_window
        tree = window.tree

        def view():
            row = self.rows()[0]
            return tree.heading("goal", "text"), row["goal"], row["deviation"], row["status"]

        self.assertTrue(window.look_ahead_var.get())  # alapból bekapcsolva
        self.assertEqual(view(), ("Holnapi cél", "18,80", "−8,90", "Ütemben – a holnapi célig még 8,90 szint"))
        self.assertEqual(
            window.look_ahead_info_var.get(), "A mai célt minden karakter teljesítette, ezért a holnapi célok látszanak."
        )
        self.assertIn("teendő a holnapi célig: 8,90 szint", window.summary_var.get())

        window.look_ahead_var.set(False)  # kikapcsolás a jelölőnégyzettel
        window._toggle_look_ahead()
        self.assertEqual(view(), ("Mai cél", "9,90", "0,00", "Mai cél teljesítve"))
        self.assertEqual(window.look_ahead_info_var.get(), "")
        self.assertFalse(load_data(self.path).look_ahead)

        window.look_ahead_var.set(True)
        window._toggle_look_ahead()
        self.select(self.app.data.characters[0])
        window.level_var.set("27,7")  # a mai, a holnapi és a holnaputáni cél is megvan
        window.apply_level()
        goal_day = today + timedelta(days=3)
        self.assertEqual(view()[:2], (f"Cél ({goal_day:%m-%d})", "36,60"))
        self.assertEqual(
            window.look_ahead_info_var.get(),
            "A mai és a következő 2 nap célját is minden karakter teljesítette, ezért "
            f"{self.gui.goal_day_phrase(goal_day, today)} célok látszanak.",
        )

    def test_column_widths_follow_the_content(self):
        self.add("Thrall", realm="Draenor")
        self.app.open_list()
        window = self.app.list_window
        self.root.update()
        cell, padding = window._cell_font, self.app.px(20)

        def width(key):
            return int(window.tree.column(key, "width"))

        realm_before = width("realm")
        self.assertGreaterEqual(realm_before, cell.measure("Draenor") + padding)
        heading_width = window._heading_font.measure("Szinteltérés" + self.gui.SORT_ARROWS[False])
        self.assertGreaterEqual(width("deviation"), heading_width)  # a fejléc sem lóg ki

        # A kézzel kisebbre vett ablakot a frissítés nem méretezi vissza, ha a tartalom nem nőtt.
        window.geometry(f"1000x{window.winfo_height()}")
        self.root.update()
        window.refresh()
        self.root.update()
        self.assertEqual(window.winfo_width(), 1000)

        long_name = "Sylvanas Windrunner Banshee Queen"
        self.add(long_name, realm="Twisting Nether")  # hosszabb tartalom: szélesebb oszlop és ablak
        self.root.update()
        self.assertGreaterEqual(width("realm"), cell.measure("Twisting Nether") + padding)
        self.assertGreaterEqual(width("name"), cell.measure(long_name) + padding)
        self.assertGreater(window.winfo_width(), 1000)

        # Rövidebb tartalomhoz keskenyebb oszlop tartozik.
        self.select(self.app.data.characters[1])
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.delete_selected()
        self.assertEqual(width("realm"), realm_before)

    def test_murlok_order_button_reorders_all_characters(self):
        self.add("Jaina", char_class="Mage", spec="Frost", level="60")
        self.add("Illidan")  # nincs class/spec
        self.add("Uther", char_class="Paladin", spec="Holy", level="30")
        self.add("Khadgar", char_class="Mage", spec="Frost", level="70")
        self.app.open_list()
        window = self.app.list_window
        self.assertNotIn("disabled", window.murlok_order_button.state())  # kijelölés nélkül is használható

        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            window.order_by_murlok()  # még nincsenek pontszámok
        self.assertIn("Még nincsenek Murlok.io-pontszámok", info.call_args.args[1])

        self.app.data.spec_scores = SpecScores({"paladin/holy": D("4050"), "mage/frost": D("3575")})
        window.sort_by("name")
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=False) as ask:
            window.order_by_murlok()
        self.assertIn("1 karakternek nincs Murlok.io-pontszáma", ask.call_args.args[1])
        self.assertEqual([c.name for c in self.app.data.characters], ["Jaina", "Illidan", "Uther", "Khadgar"])

        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.order_by_murlok()
        expected = ["Uther", "Khadgar", "Jaina", "Illidan"]
        self.assertEqual([c.name for c in self.app.data.characters], expected)
        self.assertEqual([c.name for c in load_data(self.path).characters], expected)
        self.assertEqual(self.app.list_sort, self.gui.PLAN_ORDER)  # az új sorrend látszik
        self.assertEqual(self.names(), expected)

        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            window.order_by_murlok()
        self.assertIn("már most is a Murlok.io szerinti", info.call_args.args[1])

    def test_list_shows_which_day_level_we_are_at(self):
        today = date.today()
        self.app.start_var.set(format_date(today - timedelta(days=4)))
        self.app.first_var.set(format_date(today + timedelta(days=5)))
        self.app.last_var.set(format_date(today + timedelta(days=5)))
        self.add("Thrall", level="30")  # 10 napos terv, naponta 8,90 szint: a 3. nap szintjén áll
        self.app.open_list()
        window = self.app.list_window
        self.assertEqual(
            window.day_var.get(),
            "Ma a szintezés 5. napja van (összesen 10 nap). A karakter a 3. nap szintjén áll – 2 nappal a mai cél mögött.",
        )
        self.assertEqual(str(window.day_label.cget("style")), "Late.TLabel")

        self.select(self.app.data.characters[0])
        window.level_var.set("70")
        window.apply_level()
        self.assertTrue(window.day_var.get().endswith("A karakter a 7. nap szintjén áll – 2 nappal a terv előtt."))
        self.assertEqual(str(window.day_label.cget("style")), "Good.TLabel")

    def test_spec_choices_follow_the_class(self):
        def choices():
            return tuple(self.root.tk.splitlist(self.app.spec_box.cget("values")))

        self.assertEqual(choices(), self.gui.ALL_SPECS)  # kaszt nélkül minden spec választható
        self.app.class_var.set("mage")
        self.assertEqual(choices(), ("Arcane", "Fire", "Frost"))
        self.app.spec_var.set("Frost")
        self.app.class_var.set("Death Knight")  # a Frost a Death Knightnál is létezik
        self.assertEqual(self.app.spec_var.get(), "Frost")
        self.app.class_var.set("Paladin")  # a Frost nem Paladin spec, ezért törlődik
        self.assertEqual(self.app.spec_var.get(), "")
        self.app.class_var.set("Hunter")
        self.assertIn("Beast Mastery", choices())
        self.app.spec_var.set("Saját spec")  # a kézzel beírt szöveg megmarad
        self.app.class_var.set("Warrior")
        self.assertEqual(self.app.spec_var.get(), "Saját spec")

    def test_empty_name_is_rejected(self):
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            self.add("   ")
        warning.assert_called_once()
        self.assertEqual(self.app.data.characters, [])

    def test_duplicate_name_needs_confirmation(self):
        self.add("Thrall")
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=False):
            self.add("thrall")
        self.assertEqual(len(self.app.data.characters), 1)
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.add("thrall")
        self.assertEqual(len(self.app.data.characters), 2)

    def test_valid_settings_are_applied_and_saved(self):
        self.app.start_var.set("2026-10-01")
        self.app.first_var.set("2026.10.10.")
        self.app.last_var.set("2026-11-01")
        self.app.start_level_var.set("10")
        self.app.target_level_var.set("80,5")
        self.app.mode_var.set(SEQUENTIAL)
        saved = load_data(self.path).settings
        self.assertEqual(
            (saved.start_date, saved.first_target_date, saved.last_target_date),
            (date(2026, 10, 1), date(2026, 10, 10), date(2026, 11, 1)),
        )
        self.assertEqual((saved.start_level, saved.target_level, saved.mode), (D("10.00"), D("80.50"), SEQUENTIAL))
        self.assertTrue(self.app.settings_message.get().startswith("✔"))

    def test_target_dates_are_estimated_from_current_levels(self):
        today = date.today()
        start = today - timedelta(days=10)
        old_first, old_last = start + timedelta(days=20), start + timedelta(days=40)
        self.app.start_var.set(format_date(start))
        self.app.first_var.set(format_date(old_first))
        self.app.last_var.set(format_date(old_last))
        self.app.mode_var.set(SEQUENTIAL)
        self.assertEqual(str(self.app.estimate_button.grid_info()["row"]), "1")  # a céldátumok mellett
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.estimate_target_dates()
        self.assertIn("Még nincs karakter a listán", info.call_args.args[1])

        # A szintek a tegnapi nap végén voltak meg: Thrall 10 nap alatt 44,50 szintet lépett (napi 4,45).
        self.add("Thrall", level="45,5")
        self.add("Jaina", "Arthas")
        first, last = today + timedelta(days=9), today + timedelta(days=49)  # 44,50 és összesen 222,50 szint
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=False) as ask:
            self.app.estimate_target_dates()
        question, detail = ask.call_args.args[1], ask.call_args.kwargs["detail"]
        self.assertIn(f"Első karakter célszinten: {format_date(old_first)} → {format_date(first)}", question)
        self.assertIn(f"Utolsó karakter célszinten: {format_date(old_last)} → {format_date(last)}", question)
        self.assertIn("szintezés eddigi 10 napjának tempójából", detail)
        self.assertIn("Thrall eddig napi 4,45 szintet lépett", detail)
        self.assertEqual(self.app.first_var.get(), format_date(old_first))  # nemet mondtunk

        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.app.estimate_target_dates()
        self.assertEqual((self.app.first_var.get(), self.app.last_var.get()), (format_date(first), format_date(last)))
        saved = load_data(self.path).settings
        self.assertEqual((saved.first_target_date, saved.last_target_date), (first, last))
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.estimate_target_dates()
        self.assertIn("A céldátumok már most is ezek", info.call_args.args[1])

        # A hibás céldátumot a számolás kijavítja, a hibás kezdőnap viszont akadály.
        self.app.last_var.set("hibás")
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True) as ask:
            self.app.estimate_target_dates()
        self.assertIn(f"Első karakter célszinten: {format_date(first)} (nem változik)", ask.call_args.args[1])
        self.assertEqual(self.app.last_var.get(), format_date(last))
        self.assertTrue(self.app.settings_message.get().startswith("✔"))
        self.app.start_var.set("hibás")
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.estimate_target_dates()
        self.assertIn("Előbb javítsd ki a beállításokat", info.call_args.args[1])

    def test_target_item_level_is_optional_and_saved(self):
        self.assertEqual(self.app.target_item_level_var.get(), "")  # alapból nincs megadva
        self.assertIsNone(self.app.data.settings.target_item_level)
        self.app.target_item_level_var.set("330,5")
        self.assertEqual(load_data(self.path).settings.target_item_level, D("330.50"))
        self.assertTrue(self.app.settings_message.get().startswith("✔"))

        self.app.target_item_level_var.set("330,555")
        message = self.app.settings_message.get()
        self.assertIn("Célitemlevel: „330,555”: az itemlevel legfeljebb két tizedesjegyű lehet.", message)
        self.assertEqual(self.app.data.settings.target_item_level, D("330.50"))  # a hibás érték nem kerül be
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.estimate_target_dates()  # amíg hibás, a céldátumok sem állíthatók be
        self.assertIn("Előbb javítsd ki a beállításokat", info.call_args.args[1])

        self.app.target_item_level_var.set("")
        self.assertIsNone(load_data(self.path).settings.target_item_level)
        self.app.target_item_level_var.set("331")
        app = self.gui.App(tk.Toplevel(self.root), self.path)  # újraindítás után is megvan
        self.assertEqual(app.target_item_level_var.get(), "331,00")

    def test_invalid_settings_are_reported_and_not_applied(self):
        before = self.app.data.settings
        self.app.first_var.set("2026-02-30")
        self.assertIn("nem létező dátum", self.app.settings_message.get())
        self.assertIs(self.app.data.settings, before)
        self.app.first_var.set(format_date(before.start_date - timedelta(days=1)))
        self.assertIn("nem lehet korábbi", self.app.settings_message.get())
        self.assertIs(self.app.data.settings, before)
        self.app.first_var.set(format_date(before.first_target_date))
        self.app.target_level_var.set("83,456")
        self.assertIn("Célszint: „83,456”: a szint legfeljebb két tizedesjegyű lehet.", self.app.settings_message.get())
        self.app.target_level_var.set("1")
        self.assertIn("nagyobbnak kell lennie", self.app.settings_message.get())
        self.assertIs(self.app.data.settings, before)

    def test_level_fields_step_by_whole_levels(self):
        variable = tk.StringVar(value="83,45")
        field = self.gui.LevelSpinbox(self.root, variable, empty_value=lambda: D("80"))
        field.event_generate("<<Increment>>")
        self.assertEqual(variable.get(), "84,45")
        field.event_generate("<<Decrement>>")
        field.event_generate("<<Decrement>>")
        self.assertEqual(variable.get(), "82,45")
        variable.set("")
        field.event_generate("<<Increment>>")
        self.assertEqual(variable.get(), "81,00")
        variable.set("999,5")
        field.event_generate("<<Increment>>")
        self.assertEqual(variable.get(), "999,99")
        variable.set("hibás")
        field.event_generate("<<Increment>>")
        self.assertEqual(variable.get(), "hibás")

    def test_list_shows_daily_goal_and_status(self):
        today = date.today()
        self.app.start_var.set(format_date(today))
        self.app.first_var.set(format_date(today + timedelta(days=9)))
        self.app.last_var.set(format_date(today + timedelta(days=19)))
        self.add("Thrall")
        self.add("Jaina", level="90")
        self.app.open_list()
        tree = self.app.list_window.tree

        thrall, jaina = self.rows()
        self.assertEqual(
            thrall,
            {
                "position": "1",
                "name": "Thrall",
                "realm": "–",
                "race": "–",
                "class": "–",
                "spec": "–",
                "item_level": "–",
                "raiderio": "–",
                "murlok": "–",
                "level": "1,00",
                "start": format_date(today),
                "deadline": format_date(today + timedelta(days=9)),
                "goal": "9,90",
                "deviation": "−8,90",
                "days": "10",
                "pace": "8,90",
                "status": "Ütemben – ma még 8,90 szint",
            },
        )
        self.assertEqual((jaina["deviation"], jaina["status"]), ("+84,55", "Kész – elérte a célszintet"))
        self.assertEqual([tree.item(iid, "tags")[0] for iid in tree.get_children()], ["on_track", "done"])
        self.assertIn("mai teendő összesen: 8,90 szint", self.app.list_window.summary_var.get())

        self.assertNotIn("start", tree["displaycolumns"])  # párhuzamosan mindenki ugyanakkor kezd
        self.app.mode_var.set(SEQUENTIAL)
        self.assertIn("start", tree["displaycolumns"])
        # A szint a spec és az itemlevel között látszik.
        shown = list(tree["displaycolumns"])
        self.assertEqual(shown[shown.index("spec") : shown.index("spec") + 3], ["spec", "level", "item_level"])

    def test_list_can_be_sorted_by_deviation(self):
        today = date.today()
        self.app.start_var.set(format_date(today))
        self.app.first_var.set(format_date(today + timedelta(days=9)))
        self.app.last_var.set(format_date(today + timedelta(days=29)))
        self.add("Thrall", level="5")  # céldátum: 9 nap múlva, mai cél 9,90 → −4,90
        self.add("Jaina", level="50")  # 16 nap múlva, mai cél 6,23 → +43,77
        self.add("Arthas", level="2")  # 22 nap múlva, mai cél 4,86 → −2,86
        self.add("Sylvanas", level="1")  # 29 nap múlva, mai cél 3,96 → −2,96
        self.app.open_list()
        window = self.app.list_window
        tree = window.tree

        self.assertTrue(str(tree.heading("deviation", "command")))  # a fejléc kattintható
        self.assertEqual(tree.heading("position", "text"), "# ▲")
        window.sort_by("deviation")
        self.assertEqual(self.names(), ["Thrall", "Sylvanas", "Arthas", "Jaina"])
        self.assertEqual([row["deviation"] for row in self.rows()], ["−4,90", "−2,96", "−2,86", "+43,77"])
        self.assertEqual((tree.heading("deviation", "text"), tree.heading("position", "text")), ("Szinteltérés ▲", "#"))
        window.sort_by("deviation")
        self.assertEqual(self.names(), ["Jaina", "Arthas", "Sylvanas", "Thrall"])
        self.assertEqual(tree.heading("deviation", "text"), "Szinteltérés ▼")

        # Rendezett nézetben nem lehet átrendezni, a karakterek sorrendje (és a céldátumok) nem változik.
        jaina = self.app.data.characters[1]
        self.select(jaina)
        self.assertIn("disabled", window._order_widgets[0].state())
        self.assertTrue(window.order_hint_var.get())
        window.move_selected(-1)
        self.assertEqual([c.name for c in self.app.data.characters], ["Thrall", "Jaina", "Arthas", "Sylvanas"])

        # Szintmódosítás után újrarendeződik, a kijelölés megmarad.
        window.level_var.set("1")
        window.apply_level()  # Jaina: 1 − 6,23 = −5,23, a nézet végére kerül
        self.assertEqual(self.names(), ["Arthas", "Sylvanas", "Thrall", "Jaina"])
        self.assertEqual(tree.selection(), (jaina.uid,))

        # Törléskor a nézetben szomszédos sor lesz kijelölve (az utolsó sor helyett az előző).
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.delete_selected()
        self.assertEqual(window.selected_var.get(), "Thrall")

        # A rendezés az ablak újranyitása után is megmarad.
        window.close()
        self.app.open_list()
        window = self.app.list_window
        self.assertEqual(self.names(), ["Sylvanas", "Arthas", "Thrall"])  # 3 karakterrel: −2,96 / −3,45 / −4,90

        # A # oszlop visszaállítja az eredeti sorrendet, és újra lehet átrendezni.
        window.sort_by("position")
        self.assertEqual(self.names(), ["Thrall", "Arthas", "Sylvanas"])
        self.assertEqual(window.tree.heading("position", "text"), "# ▲")
        self.select(self.app.data.characters[1])
        self.assertNotIn("disabled", window._order_widgets[0].state())
        self.assertEqual(window.order_hint_var.get(), "")

    def test_level_changes_reordering_and_deletion(self):
        self.add("Thrall", "Jaina", "Arthas")
        self.app.open_list()
        window = self.app.list_window
        thrall = self.app.data.characters[0]
        self.select(thrall)

        window.change_level(1)
        self.assertEqual(thrall.level, D("2.00"))
        window.level_var.set("35,5")
        window.apply_level()
        self.assertEqual(thrall.level, D("35.50"))
        self.assertEqual(window.level_var.get(), "35,50")
        self.assertEqual(load_data(self.path).characters[0].level, D("35.50"))
        window.level_spin.event_generate("<<Increment>>")  # a nyíl azonnal menti is
        self.assertEqual(load_data(self.path).characters[0].level, D("36.50"))
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            window.level_var.set("35,555")
            window.apply_level()
        warning.assert_called_once()
        self.assertEqual(thrall.level, D("36.50"))
        window.level_var.set("95")  # a célszint felett is lehet
        window.apply_level()
        self.assertEqual(thrall.level, D("95.00"))

        window.move_selected(1)
        self.assertEqual([c.name for c in self.app.data.characters], ["Jaina", "Thrall", "Arthas"])
        self.assertEqual(self.names(), ["Jaina", "Thrall", "Arthas"])
        self.assertEqual(window.tree.selection(), (thrall.uid,))

        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.delete_selected()
        self.assertEqual([c.name for c in self.app.data.characters], ["Jaina", "Arthas"])
        self.assertEqual([c.name for c in load_data(self.path).characters], ["Jaina", "Arthas"])
        self.assertEqual(window.selected_var.get(), "Arthas")

    def test_character_dialog_validates_input(self):
        self.add("Thrall", item_level="326,5")
        dialog = self.gui.CharacterDialog(self.root, self.app.data.characters[0], ["Draenor"])
        self.assertEqual((dialog.level_var.get(), dialog.item_level_var.get()), ("1,00", "326,50"))
        dialog.name_var.set("  Go'el ")
        dialog.realm_var.set("Draenor ")
        dialog.race_var.set("Orc")
        dialog.class_var.set("Shaman")
        dialog.spec_var.set(" Enhancement ")
        dialog.level_var.set("42,555")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertIsNone(dialog.result)
        dialog.level_var.set("142,5")
        dialog.item_level_var.set("326,555")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertIsNone(dialog.result)
        dialog.item_level_var.set("326,55")
        dialog.raiderio_var.set("2543,75")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertIsNone(dialog.result)
        dialog.raiderio_var.set("2543,7")
        dialog.accept()
        self.assertEqual(
            dialog.result,
            {
                "name": "Go'el",
                "realm": "Draenor",
                "race": "Orc",
                "char_class": "Shaman",
                "spec": "Enhancement",
                "item_level": D("326.55"),
                "raiderio_score": D("2543.7"),
                "level": D("142.50"),
            },
        )

    def test_combo_recommendation_fills_the_new_character_form(self):
        self.add("Garrosh", char_class="Warrior", spec="Protection", race="Orc")
        self.app.data.spec_scores = SpecScores({"druid/restoration": D("3720"), "monk/mistweaver": D("3590")})
        with mock.patch.object(self.app, "_ask_faction", return_value=None), mock.patch.object(
            self.gui.messagebox, "askyesno"
        ) as ask:
            self.app.show_combo_recommendation()  # a frakciókérdést bezárták
        ask.assert_not_called()

        # Tank (plate, Warrior, Orc) már van: healer, melee vagy ranged DPS, nem plate, más kaszt és faj kell;
        # ezek közül a Restoration Druidnak a legmagasabb a Murlok.io-pontszáma.
        with mock.patch.object(self.app, "_ask_faction", return_value="Horde"), mock.patch.object(
            self.gui.messagebox, "askyesno", return_value=False
        ) as ask:
            self.app.show_combo_recommendation()
        self.assertEqual(
            ask.call_args.args[1],
            "Ajánlott Horde karakter:\nTauren Restoration Druid\n\nKitöltsem vele az új karakter mezőit?",
        )
        self.assertIn("• szerep – healer: még egy sincs", ask.call_args.kwargs["detail"])
        self.assertEqual(self.app._last_faction, "Horde")  # legközelebb ez az alapértelmezett
        self.assertEqual((self.app.race_var.get(), self.app.class_var.get(), self.app.spec_var.get()), ("", "", ""))

        self.app.name_var.set("Hamuul")
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.app.show_combo_recommendation("Horde")
        filled = (self.app.race_var.get(), self.app.class_var.get(), self.app.spec_var.get())
        self.assertEqual(filled, ("Tauren", "Druid", "Restoration"))
        self.assertEqual(self.app.name_var.get(), "Hamuul")  # a beírt név megmarad
        self.assertIn("Kitöltve: Tauren Restoration Druid", self.app.feedback_var.get())
        self.app.add_character()
        hamuul = self.app.data.characters[-1]
        self.assertEqual(
            (hamuul.name, hamuul.race, hamuul.char_class, hamuul.spec), ("Hamuul", "Tauren", "Druid", "Restoration")
        )

    def test_faction_dialog(self):
        def pick():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, self.gui.FactionDialog))
            self.assertEqual(list(dialog.buttons), ["Alliance", "Horde"])
            dialog.choose("Alliance")

        self.root.after(50, pick)
        self.assertEqual(self.app._ask_faction(), "Alliance")
        dialog = self.gui.FactionDialog(self.root, "Horde")
        dialog.destroy()  # Mégse vagy Escape
        self.assertIsNone(dialog.result)

    def test_calendar_popup_picks_a_date(self):
        picked = []
        popup = self.gui.CalendarPopup(self.root, date(2026, 12, 15), picked.append)
        popup._shift_month(1)
        self.assertEqual(popup._month, date(2027, 1, 1))
        popup._pick(date(2027, 1, 4))
        self.assertEqual(picked, [date(2027, 1, 4)])
        self.assertFalse(popup.winfo_exists())

    def test_corrupt_data_file_is_backed_up(self):
        path = Path(self.temp_dir.name) / "hibas.json"
        path.write_text("{nem json", encoding="utf-8")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            app = self.gui.App(tk.Toplevel(self.root), path)
        warning.assert_called_once()
        self.assertEqual(app.data.characters, [])
        backups = list(Path(self.temp_dir.name).glob("hibas.hibas-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{nem json")


if __name__ == "__main__":
    unittest.main()
