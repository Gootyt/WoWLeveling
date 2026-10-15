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

    def add(self, *names, level="", char_class="", spec="", race="", realm=""):
        for name in names:
            self.app.name_var.set(name)
            self.app.realm_var.set(realm)
            self.app.race_var.set(race)
            self.app.class_var.set(char_class)
            self.app.spec_var.set(spec)
            self.app.new_level_var.set(level)
            self.app.add_character()

    def rows(self):
        """A lista sorai a nézet sorrendjében, oszlopazonosító szerint."""
        tree = self.app.list_window.tree
        columns = [column[0] for column in self.gui.CharacterListWindow.COLUMNS]
        return [
            {key: str(value) for key, value in zip(columns, tree.item(iid, "values"))} for iid in tree.get_children()
        ]

    def names(self):
        return [row["name"] for row in self.rows()]

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
        self.add("Thrall")
        dialog = self.gui.CharacterDialog(self.root, self.app.data.characters[0], ["Draenor"])
        self.assertEqual(dialog.level_var.get(), "1,00")
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
        dialog.accept()
        self.assertEqual(
            dialog.result,
            {
                "name": "Go'el",
                "realm": "Draenor",
                "race": "Orc",
                "char_class": "Shaman",
                "spec": "Enhancement",
                "level": D("142.50"),
            },
        )

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
