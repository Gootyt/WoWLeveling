"""A grafikus felület tesztjei. Grafikus kijelző kell hozzájuk (Linuxon pl. xvfb-run);
ha nincs, vagy hiányzik a tkinter, a tesztek kimaradnak."""

import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
except ImportError:
    tk = None

from leveling import SEQUENTIAL, format_date, load_data

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

    def add(self, *names, level=""):
        for name in names:
            self.app.name_var.set(name)
            self.app.new_level_var.set(level)
            self.app.add_character()

    def rows(self):
        tree = self.app.list_window.tree
        return [tuple(str(value) for value in tree.item(iid, "values")) for iid in tree.get_children()]

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
        self.assertEqual([row[1] for row in self.rows()], ["Thrall", "Jaina"])

        self.app.open_list()  # a már nyitott ablakot csak előtérbe hozza
        self.assertIs(self.app.list_window, window)

        self.add("Arthas")  # a nyitott lista azonnal frissül, és kijelöli az új karaktert
        self.assertEqual([row[1] for row in self.rows()], ["Thrall", "Jaina", "Arthas"])
        self.assertEqual(window.selected_var.get(), "Arthas")

        window.close()
        self.assertIsNone(self.app.list_window)

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
            thrall[3:10],
            ("1,00", format_date(today), format_date(today + timedelta(days=9)), "9,90", "10", "8,90", "Ütemben – ma még 8,90 szint"),
        )
        self.assertEqual(jaina[9], "Kész – elérte a célszintet")
        self.assertEqual([tree.item(iid, "tags")[0] for iid in tree.get_children()], ["on_track", "done"])
        self.assertIn("mai teendő összesen: 8,90 szint", self.app.list_window.summary_var.get())

        self.assertNotIn("start", tree["displaycolumns"])  # párhuzamosan mindenki ugyanakkor kezd
        self.app.mode_var.set(SEQUENTIAL)
        self.assertIn("start", tree["displaycolumns"])

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
        self.assertEqual([row[1] for row in self.rows()], ["Jaina", "Thrall", "Arthas"])
        self.assertEqual(window.tree.selection(), (thrall.uid,))

        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.delete_selected()
        self.assertEqual([c.name for c in self.app.data.characters], ["Jaina", "Arthas"])
        self.assertEqual([c.name for c in load_data(self.path).characters], ["Jaina", "Arthas"])
        self.assertEqual(window.selected_var.get(), "Arthas")

    def test_character_dialog_validates_input(self):
        self.add("Thrall")
        dialog = self.gui.CharacterDialog(self.root, self.app.data.characters[0])
        self.assertEqual(dialog.level_var.get(), "1,00")
        dialog.name_var.set("  Go'el ")
        dialog.class_var.set("Shaman")
        dialog.level_var.set("42,555")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertIsNone(dialog.result)
        dialog.level_var.set("142,5")
        dialog.accept()
        self.assertEqual(dialog.result, ("Go'el", "Shaman", D("142.50")))

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
