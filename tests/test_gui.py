"""A grafikus felület tesztjei. Grafikus kijelző kell hozzájuk (Linuxon pl. xvfb-run);
ha nincs, vagy hiányzik a tkinter, a tesztek kimaradnak."""

import gc
import os
import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = ttk = None

import wow_addon
from leveling import (
    SEQUENTIAL,
    Character,
    LevelingData,
    Settings,
    SpecScores,
    format_date,
    load_data,
    save_data,
)

D = Decimal

# A WoWLeveling addon mentése, ahogy a játék kiírja (lásd tests/test_wow_addon.py), a programmal
# érkező változattól.
ADDON_VERSION = wow_addon.addon_version(wow_addon.ADDON_SOURCE)
ADDON_SAVE = """
WoWLevelingDB = {
\t["addonVersion"] = "%s",
\t["characters"] = {
\t\t["Thrall-Draenor"] = {
\t\t\t["name"] = "Thrall",
\t\t\t["realm"] = "Draenor",
\t\t\t["raceFile"] = "Orc",
\t\t\t["classFile"] = "SHAMAN",
\t\t\t["specID"] = 263,
\t\t\t["level"] = 85,
\t\t\t["xp"] = 2999,
\t\t\t["xpMax"] = 10000,
\t\t\t["itemLevel"] = 301.5625,
\t\t\t["mythicPlusScore"] = 1234.5,
\t\t\t["updated"] = 1760700000,
\t\t},
\t\t["Jaina-Draenor"] = {
\t\t\t["name"] = "Jaina",
\t\t\t["realm"] = "Draenor",
\t\t\t["classFile"] = "MAGE",
\t\t\t["specID"] = 64,
\t\t\t["level"] = 90,
\t\t\t["updated"] = 1760700100,
\t\t},
\t\t["Arthas-Draenor"] = {
\t\t\t["name"] = "Arthas",
\t\t\t["realm"] = "Draenor",
\t\t\t["classFile"] = "DEATHKNIGHT",
\t\t\t["level"] = 80,
\t\t\t["updated"] = 1760700200,
\t\t},
\t},
\t["version"] = 1,
}
""" % ADDON_VERSION


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
        # A gépen telepített játék mentéseit a tesztek ne olvassák be.
        patcher = mock.patch.object(wow_addon, "default_wow_folders", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = wow_leveling.App(self.root, self.path)

    def tearDown(self):
        # A még várakozó időzített hívások (pl. a mentések figyelése) ne egy későbbi teszt alatt fussanak
        # le, amikor már nincs meg az ablakuk. (A parancsaikat az ablakaik lebontása törli.)
        for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.tk.call("after", "cancel", job)
        self.root.destroy()
        # A lebontott ablakok Tk-objektumai itt, a fő szálon szűnjenek meg: ha a szemétgyűjtés egy
        # későbbi teszt háttérszálában takarítaná el őket, a tkinter mindegyiknél kb. egy másodpercig
        # várna a fő szálra (mainloop nélkül), és a háttérben futó lekérdezés kifutna az időből.
        gc.collect()
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

    def double_click(self, window, character):
        """Dupla kattintás a karakter során; visszaadja, hány szerkesztőablak nyílt meg."""
        window.update()
        tree = window.tree
        x, y, _width, height = tree.bbox(character.uid, "name")
        opened = []

        def close_dialogs():
            dialogs = [child for child in window.winfo_children() if isinstance(child, self.gui.CharacterDialog)]
            opened.append(len(dialogs))
            for dialog in dialogs:
                dialog.destroy()

        job = self.root.after(200, close_dialogs)  # a megnyílt (modális) ablak közben fut le
        for _ in range(2):
            tree.event_generate("<ButtonPress-1>", x=x + 5, y=y + height // 2)
            tree.event_generate("<ButtonRelease-1>", x=x + 5, y=y + height // 2)
        if not opened:
            self.root.after_cancel(job)
        return sum(opened)

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
        self.select_in(self.app.list_window, character)

    @staticmethod
    def select_in(window, character):
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

    def test_main_window_buttons(self):
        self.assertIsNotNone(self.find_button(self.root, "Karakterlista"))
        self.assertIsNone(self.find_button(self.root, "Karakterlista megnyitása…"))
        buttons = self.find_button(self.root, "Gear").master.winfo_children()
        self.assertEqual([button.cget("text") for button in buttons], ["Karakterlista", "Gear", "Mythic+"])
        self.find_button(self.root, "Karakterlista").invoke()
        self.assertIsNotNone(self.app.list_window)
        buttons = self.find_button(self.root, "Importálás most").master.winfo_children()
        self.assertEqual(
            [button.cget("text") for button in buttons],
            ["Tallózás…", "Importálás most", "Szinkronizálás", "Addon telepítése…"],
        )

    def test_double_click_opens_the_editor_in_both_windows(self):
        self.add("Thrall", "Jaina")
        jaina = self.app.data.characters[1]
        for open_window in (self.app.open_list, self.app.open_gear, self.app.open_mythic):
            open_window()
        for window in (self.app.list_window, self.app.gear_window, self.app.mythic_window):
            with self.subTest(window=window.TITLE):
                self.assertEqual(self.double_click(window, jaina), 1)
                self.assertEqual(window.tree.selection(), (jaina.uid,))

    def test_mythic_plus_button_opens_a_copy_of_the_gear_window(self):
        self.app.target_item_level_var.set("330")
        self.add("Thrall", item_level="320")
        self.add("Jaina", item_level="325")
        self.add("Arthas", item_level="331")  # elérte a célitemlevelt
        self.find_button(self.root, "Mythic+").invoke()
        mythic = self.app.mythic_window
        self.assertIsInstance(mythic, self.gui.MythicPlusWindow)
        self.assertIsInstance(mythic, self.gui.GearWindow)  # a Gear ablak másolata
        self.assertEqual(mythic.title(), f"Mythic+ – {self.gui.APP_TITLE}")
        self.assertIsNone(self.app.gear_window)  # külön ablak
        self.app.open_mythic()  # a már nyitott ablakot csak előtérbe hozza
        self.assertIs(self.app.mythic_window, mythic)

        self.app.open_gear()
        gear = self.app.gear_window
        # A Gear ablak oszlopai a tervezett itemlevel és az eltérés nélkül, ugyanabban a sorrendben, ugyanazzal
        # a tartalommal; helyettük a Raider.io-terv oszlopai vannak benne.
        gear_columns = [column[0] for column in gear.COLUMNS]
        mythic_columns = [column[0] for column in mythic.COLUMNS]
        common = [key for key in gear_columns if key in mythic_columns]
        self.assertEqual(set(gear_columns) - set(common), {"planned_item_level", "item_level_deviation"})
        self.assertEqual([key for key in mythic_columns if key in gear_columns], common)
        self.assertEqual(
            [{key: row[key] for key in common} for row in self.rows(mythic)],
            [{key: row[key] for key in common} for row in self.rows(gear)],
        )
        self.assertEqual(self.names(mythic), ["Thrall", "Jaina"])  # Arthas lekerült
        self.assertEqual(self.app.mythic_sort, self.gui.MYTHIC_ORDER)  # alapból a Raider.io-különbözet szerint
        self.assertEqual(mythic.tree.heading("raiderio_deviation", "text"), "Raider.io-különbözet ▲")
        info = mythic.info_var.get()  # a táblázat fölött a Raider.io-terv, nem az itemlevelé
        self.assertTrue(info.startswith("Tervezett Raider.io: "))
        self.assertTrue(info.endswith("Célitemlevelen (nem látszik a listán): 1 karakter"))
        mythic.sort_by("name")  # saját rendezése van
        self.assertEqual((self.names(mythic), self.names(gear)), (["Jaina", "Thrall"], ["Thrall", "Jaina"]))
        self.assertEqual((self.app.mythic_sort, self.app.gear_sort), (("name", False), self.gui.GEAR_ORDER))

        # Alul a Raider.io pontszám állítható; a változás minden ablakban látszik.
        jaina = self.app.data.characters[1]
        self.assertEqual(mythic.EDITED_FIELD.label, "Raider.io pontszám:")
        self.select_in(mythic, jaina)
        self.assertEqual(mythic.value_var.get(), "")  # még nincs megadva
        mythic.change_value(1)  # nincs mit léptetni
        self.assertIsNone(jaina.raiderio_score)
        mythic.value_var.set("2543,7")
        mythic.apply_value()
        self.assertEqual(load_data(self.path).characters[1].raiderio_score, D("2543.7"))
        self.assertEqual(jaina.item_level, D("325.00"))  # az itemlevel nem változott
        self.assertEqual({row["name"]: row["raiderio"] for row in self.rows(gear)}["Jaina"], "2543,7")
        mythic.change_value(1)  # „+1 pont”
        self.assertEqual(jaina.raiderio_score, D("2544.7"))
        self.assertEqual(mythic.value_var.get(), "2544,7")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            mythic.value_var.set("2544,75")
            mythic.apply_value()
        self.assertEqual(warning.call_args.args[0], "Hibás Raider.io pontszám")
        self.assertEqual(jaina.raiderio_score, D("2544.7"))
        mythic.value_var.set("")  # törölhető is
        mythic.apply_value()
        self.assertIsNone(load_data(self.path).characters[1].raiderio_score)

        self.select_in(gear, jaina)  # a Gear ablakban továbbra is az itemlevel állítható
        gear.value_var.set("330")
        gear.apply_value()
        self.assertEqual((self.names(mythic), self.names(gear)), (["Thrall"], ["Thrall"]))
        mythic.close()
        self.assertIsNone(self.app.mythic_window)
        self.assertIs(self.app.gear_window, gear)

    def test_mythic_plus_window_plans_raiderio_scores(self):
        self.app.data.spec_scores = SpecScores(
            {"paladin/holy": D("4000"), "mage/frost": D("3600"), "warrior/arms": D("3500")}
        )
        self.add("Jaina", char_class="Mage", spec="Frost", score="3000")
        self.add("Uther", char_class="Paladin", spec="Holy", score="3500")
        self.add("Varian", char_class="Warrior", spec="Arms", score="2800")
        self.add("Anduin")  # nincs kasztja, így Murlok.io-pontszáma sem
        self.app.open_mythic()
        mythic = self.app.mythic_window
        columns = [column[0] for column in mythic.COLUMNS]
        start = columns.index("raiderio")  # a Raider.io után következnek
        self.assertEqual(columns[start : start + 4], ["raiderio", "planned_raiderio", "raiderio_deviation", "murlok"])
        self.assertEqual(
            (mythic.tree.heading("planned_raiderio", "text"), mythic.tree.heading("raiderio_deviation", "text")),
            ("Tervezett Raider.io", "Raider.io-különbözet ▲"),  # alapból eszerint rendez
        )
        # Murlok.io-sorrend: Uther, Jaina, Varian; Jaina a 2.: 3600 · (1 − 2x) = 3000, x = 8,33%.
        rows = {row["name"]: (row["planned_raiderio"], row["raiderio_deviation"]) for row in self.rows(mythic)}
        self.assertEqual(
            rows,
            {
                "Uther": ("3666,7", "−166,7"),
                "Jaina": ("3000,0", "0,0"),
                "Varian": ("2625,0", "+175,0"),
                "Anduin": ("–", "–"),
            },
        )
        self.assertEqual(
            mythic.info_var.get(),
            "Tervezett Raider.io: x = kb. 8,33% (ennyivel kisebb a Murlok.io-pontszámhoz mért arány "
            "karakterenként; a 2. karakternél 0 a különbözet)",
        )
        # Alapból a Raider.io-különbözet szerint növekvő sorrendben; újabb kattintásra megfordul.
        self.assertEqual(self.names(mythic), ["Uther", "Jaina", "Varian", "Anduin"])
        mythic.sort_by("raiderio_deviation")
        self.assertEqual(self.names(mythic), ["Varian", "Jaina", "Uther", "Anduin"])
        mythic.sort_by("raiderio_deviation")

        # A Raider.io pontszám módosítása után újraszámol (Jaina továbbra is 0-n áll).
        uther = self.app.data.characters[1]
        self.select_in(mythic, uther)
        mythic.value_var.set("3700")
        mythic.apply_value()
        rows = {row["name"]: row["raiderio_deviation"] for row in self.rows(mythic)}
        self.assertEqual((rows["Uther"], rows["Jaina"]), ("+33,3", "0,0"))

        self.app.data.spec_scores = SpecScores()  # pontszámok nélkül nincs terv
        self.app.data_changed()
        self.assertIn("még nincsenek Murlok.io-pontszámok", mythic.info_var.get())
        self.app.open_gear()  # a Gear ablakban nincsenek ilyen oszlopok
        self.assertNotIn("planned_raiderio", [column[0] for column in self.app.gear_window.COLUMNS])

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
        # A közös oszlopok a Gear ablakban is ugyanazt mutatják; a szinttel kapcsolatosak ott nincsenek.
        gear_rows, list_rows = self.rows(gear), self.rows(window)
        common = [key for key in gear_rows[0] if key in list_rows[0]]
        self.assertEqual(
            [{key: row[key] for key in common} for row in gear_rows],
            [{key: row[key] for key in common} for row in list_rows],
        )
        hidden = {"level", "start", "deadline", "goal", "deviation", "days", "pace", "status"}
        self.assertFalse(hidden & set(gear_rows[0]))
        self.assertEqual(gear_rows[0]["item_level"], "–")
        self.assertEqual([gear.tree.item(iid, "tags") for iid in gear.tree.get_children()], ["", ""])  # nincs szín
        # A Murlok.io-állapot szövege már a megnyitáskor megvan, így a keskenyebb ablakban sem lóg ki.
        self.assertEqual(self.app.score_status_var.get(), "Murlok.io-pontszámok: még nincsenek lekérve")
        gear.update_idletasks()
        self.assertGreaterEqual(gear.winfo_width(), gear.winfo_reqwidth())
        self.app.mode_var.set(SEQUENTIAL)  # a „Kezdés” oszlop egymás utáni ütemezésnél sem jelenik meg
        self.assertNotIn("start", gear.tree["displaycolumns"])
        self.assertIn("start", window.tree["displaycolumns"])
        self.assertEqual((self.app.gear_sort, self.app.list_sort), (self.gui.GEAR_ORDER, self.gui.LIST_ORDER))
        gear.sort_by("name")  # saját rendezése van
        self.assertEqual((self.names(gear), self.names(window)), (["Jaina", "Thrall"], ["Thrall", "Jaina"]))
        self.assertEqual((self.app.gear_sort, self.app.list_sort), (("name", False), self.gui.LIST_ORDER))

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
            gear.info_var.get(),
            "Célitemlevel: 330,00   ·   X = 5,00 (ennyivel csökken a tervezett itemlevel karakterenként)",
        )

        # Az ablak alján az itemlevel módosítható; aki eléri a célitemlevelt, lekerül a listáról.
        self.assertEqual(gear.EDITED_FIELD.label, "Itemlevel:")
        uther = self.app.data.characters[1]
        self.select_in(gear, uther)
        self.assertEqual(gear.value_var.get(), "325,00")
        gear.change_value(1)  # „+1 itemlevel”
        self.assertEqual(load_data(self.path).characters[1].item_level, D("326.00"))
        gear.value_var.set("330")
        gear.apply_value()
        self.assertEqual(uther.item_level, D("330.00"))
        self.assertEqual(self.names(gear), ["Varian", "Jaina", "Anduin"])
        # A maradék sorrend: Jaina (1.), Varian (2.), Anduin; (330 − 321)/1 = 9, (330 − 310)/2 = 10 → X = 9.
        self.assertEqual(
            [(row["planned_item_level"], row["item_level_deviation"]) for row in self.rows(gear)],
            [("312,00", "−2,00"), ("321,00", "0,00"), ("303,00", "–")],
        )
        self.assertIn("Célitemlevelen (nem látszik a listán): 1 karakter", gear.info_var.get())
        self.assertIn("X = 9,00", gear.info_var.get())
        anduin = self.app.data.characters[3]
        self.select_in(gear, anduin)
        self.assertEqual(gear.value_var.get(), "")  # még nincs itemlevele
        gear.change_value(1)  # nincs mit léptetni
        self.assertIsNone(anduin.item_level)
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            gear.value_var.set("sok")
            gear.apply_value()
        self.assertEqual(warning.call_args.args[0], "Hibás itemlevel")
        gear.value_var.set("305,5")
        gear.apply_value()
        self.assertEqual(load_data(self.path).characters[3].item_level, D("305.50"))
        self.assertEqual(anduin.level, D("1.00"))  # a szint nem változott

        self.app.target_item_level_var.set("300")  # mindenki elérte
        self.assertEqual(self.rows(gear), [])
        self.assertEqual(
            gear.summary_var.get(), "Minden karakter elérte a célitemlevelt, ezért egyik sem látszik a listán."
        )
        self.assertIn("minden karakter elérte a célitemlevelt", gear.info_var.get())

        self.app.target_item_level_var.set("")  # célitemlevel nélkül nincs terv
        self.assertEqual({row["planned_item_level"] for row in self.rows(gear)}, {"–"})
        self.assertEqual(len(self.rows(gear)), 4)  # célitemlevel nélkül senki sem kerül le
        self.assertEqual(
            gear.info_var.get(), "Tervezett itemlevel: nincs megadva célitemlevel (a főablakban adhatod meg)."
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

    def test_role_column_follows_the_spec(self):
        self.add("Thrall", char_class="Shaman", spec="Enhancement")
        self.add("Jaina", char_class="Mage")  # spec nélkül is egyértelmű: minden Mage spec ranged
        self.add("Rexxar", char_class="Hunter")  # spec nélkül nem tudható (a Survival melee)
        self.add("Uther", char_class="Paladin", spec="Holy")
        self.add("Malfurion", char_class="druid", spec="guardian")
        self.add("Kel'Thuzad", char_class="Necromancer", spec="Bone")  # ismeretlen kaszt
        self.app.open_list()
        window = self.app.list_window
        columns = [column[0] for column in window.COLUMNS]
        self.assertEqual(columns[columns.index("spec") + 1], "role")
        self.assertEqual(window.tree.heading("role", "text"), "Role")
        self.assertEqual(
            {row["name"]: row["role"] for row in self.rows()},
            {
                "Thrall": "Melee DPS",
                "Jaina": "Ranged DPS",
                "Rexxar": "–",
                "Uther": "Healer",
                "Malfurion": "Tank",
                "Kel'Thuzad": "–",
            },
        )
        window.sort_by("role")  # tank, healer, melee, ranged, végül az ismeretlenek
        self.assertEqual(self.names(), ["Malfurion", "Uther", "Thrall", "Jaina", "Rexxar", "Kel'Thuzad"])
        thrall = self.app.data.characters[0]
        thrall.spec = "Elemental"  # a role a spec változásával együtt változik
        self.app.data_changed(select=thrall)
        self.assertEqual({row["name"]: row["role"] for row in self.rows()}["Thrall"], "Ranged DPS")

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

    def raiderio_app(self, fetch, characters=(), fetched_at=None):
        """Egy második főablak a megadott karakterekkel, amely a `fetch` függvénnyel „kéri le” a
        Raider.io-adatokat (fetched_at: a legutóbbi lekérés ideje)."""
        path = Path(self.temp_dir.name) / "raiderio.json"
        data = LevelingData(Settings.default(), list(characters))
        data.raiderio_fetched_at = fetched_at
        save_data(path, data)
        return self.gui.App(tk.Toplevel(self.root), path, fetch_profile=fetch)

    def wait_for_raiderio(self, app):
        for _ in range(300):
            self.root.update()
            if app.can_fetch_raiderio():
                return
            time.sleep(0.01)
        self.fail("a Raider.io-lekérés nem fejeződött be")

    @staticmethod
    def add_to(app, name, realm=""):
        app.name_var.set(name)
        app.realm_var.set(realm)
        app.add_character()

    def test_raiderio_button_fetches_item_levels_and_scores(self):
        self.app.open_list()  # lekérő függvény nélkül a gomb nem használható
        self.assertIn("disabled", self.app.list_window.raiderio_button.state())

        Profile = self.gui.raiderio.Profile
        profiles = {
            "Thrall": Profile(D("331.25"), D("2543.7"), "Orc", "Shaman", "Enhancement"),  # eddig üres: beíródik
            "Jaina": Profile(D("320.00"), D("2600.0")),  # az itemlevel kisebb (kérdés), a pontszám nagyobb
            "Arthas": Profile(D("333.00"), None),  # csak egész itemlevel: a pontosabb 333,56 marad
        }
        calls = []

        def fetch(region, realm, name):
            calls.append((region, realm, name))
            if name == "Valaki":
                raise self.gui.raiderio.CharacterNotFound("nem található a Raider.io-n")
            return profiles[name]

        characters = [
            Character("Thrall", realm="Draenor"),
            Character("Jaina", realm="Ragnaros", item_level=D("325.50"), raiderio_score=D("2500.0")),
            Character("Arthas", realm="Draenor", item_level=D("333.56")),
            Character("Valaki", realm="Draenor"),
            Character("Illidan"),  # realm nélkül nem lehet lekérni
        ]
        app = self.raiderio_app(fetch, characters, fetched_at=datetime.now())
        thrall, jaina, arthas = app.data.characters[:3]
        app.open_list()  # friss az adat, ezért most nem indul magától lekérés
        window = app.list_window
        self.assertEqual(calls, [])
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=False) as ask:
            window.raiderio_button.invoke()
            self.assertIn("lekérés folyamatban", app.raiderio_status_var.get())
            self.assertIn("disabled", window.raiderio_button.state())
            self.wait_for_raiderio(app)
        self.assertEqual([call[2] for call in calls], ["Thrall", "Jaina", "Arthas", "Valaki"])
        self.assertEqual(calls[1], ("eu", "Ragnaros", "Jaina"))
        self.assertEqual(
            (thrall.item_level, thrall.raiderio_score, thrall.race, thrall.char_class, thrall.spec),
            (D("331.25"), D("2543.7"), "Orc", "Shaman", "Enhancement"),
        )
        self.assertEqual((jaina.item_level, jaina.raiderio_score), (D("325.50"), D("2600.0")))  # nemet mondtunk
        self.assertEqual(arthas.item_level, D("333.56"))
        question, detail = ask.call_args.args[1], ask.call_args.kwargs["detail"]
        self.assertIn("• Jaina: itemlevel 325,50 → 320,00", question)
        self.assertNotIn("Thrall", question)
        self.assertIn("2 karakter adata frissült", detail)
        self.assertIn("• Valaki (Draenor): nem található a Raider.io-n", detail)
        self.assertIn("Realm nélkül kimaradt: Illidan", detail)
        self.assertRegex(
            app.raiderio_status_var.get(),
            r"^Raider\.io-adatok: \d{4}-\d\d-\d\d \d\d:\d\d – 2 karakter adata frissült, 1 karakter nem található, "
            r"1 kisebb értéket nem írtam át$",
        )
        self.assertEqual(window.tree.set(thrall.uid, "item_level"), "331,25")  # a táblázat is frissült
        saved = load_data(app.data_path)
        self.assertEqual((saved.characters[0].raiderio_score, saved.characters[0].spec), (D("2543.7"), "Enhancement"))

        # Újra: a régió a beállításokból jön, és igen válaszra a csökkenés is átíródik.
        app.region_var.set("US")
        calls.clear()
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.raiderio_button.invoke()
            self.wait_for_raiderio(app)
        self.assertEqual({call[0] for call in calls}, {"us"})
        self.assertEqual(jaina.item_level, D("320.00"))
        self.assertIn("– 1 karakter adata frissült, 1 karakter nem található", app.raiderio_status_var.get())

    def test_raiderio_data_is_fetched_automatically(self):
        Profile = self.gui.raiderio.Profile
        profiles = {
            "Thrall": Profile(D("331.25"), D("2543.7"), "Orc", "Shaman", "Enhancement"),
            "Jaina": Profile(D("320.00"), D("2600.0"), "Human", "Mage", "Frost"),
            "Valira": Profile(D("328.00"), D("1500.0"), "Night Elf", "Rogue", "Outlaw"),
        }
        calls = []

        def fetch(region, realm, name):
            calls.append(name)
            if name not in profiles:
                raise self.gui.raiderio.CharacterNotFound("nem található a Raider.io-n")
            return profiles[name]

        app = self.raiderio_app(fetch, [Character("Jaina", "Mage", realm="Ragnaros", item_level=D("325.50"))])

        # Új karakter hozzáadásakor az övé magától lekérődik, és kitölti az üres mezőit.
        self.add_to(app, "Thrall", "Draenor")
        self.wait_for_raiderio(app)
        thrall = app.data.characters[1]
        self.assertEqual(calls, ["Thrall"])
        self.assertEqual(
            (thrall.race, thrall.char_class, thrall.spec, thrall.item_level, thrall.raiderio_score),
            ("Orc", "Shaman", "Enhancement", D("331.25"), D("2543.7")),
        )
        self.assertEqual(
            app.feedback_var.get(),
            "✔ Thrall adatai a Raider.io-ról: faj Orc, kaszt Shaman, spec Enhancement, itemlevel 331,25, "
            "Raider.io 2543,7.",
        )
        self.assertIsNone(app.data.raiderio_fetched_at)  # csak egy karakteré jött meg
        self.add_to(app, "Valaki", "Draenor")  # elírt név
        self.wait_for_raiderio(app)
        self.assertEqual(
            app.feedback_var.get(),
            "⚠ Valaki (Draenor, EU): nem található a Raider.io-n – ellenőrizd a nevét, a realmjét és a régiót.",
        )
        self.assertEqual(str(app.feedback_label.cget("style")), "Error.TLabel")
        self.add_to(app, "Illidan")  # realm nélkül nincs mit lekérni
        self.assertEqual(calls, ["Thrall", "Valaki"])

        # Ablak megnyitásakor mindenkiét lekéri, kérdés és üzenetablak nélkül: a kisebb értéket nem írja át.
        calls.clear()
        with mock.patch.object(self.gui.messagebox, "askyesno") as ask, mock.patch.object(
            self.gui.messagebox, "showinfo"
        ) as info:
            app.open_mythic()
            self.assertIn("lekérés folyamatban", app.raiderio_status_var.get())
            self.wait_for_raiderio(app)
        ask.assert_not_called()
        info.assert_not_called()
        self.assertEqual(calls, ["Jaina", "Thrall", "Valaki"])
        jaina = app.data.characters[0]
        self.assertEqual(
            (jaina.item_level, jaina.raiderio_score, jaina.race, jaina.char_class, jaina.spec),
            (D("325.50"), D("2600.0"), "Human", "Mage", "Frost"),
        )
        self.assertTrue(
            app.raiderio_status_var.get().endswith(
                "– 1 karakter adata frissült, 1 karakter nem található, 1 kisebb értéket nem írtam át"
            )
        )
        self.assertIsNotNone(app.data.raiderio_fetched_at)

        # Fél órán belül egy másik ablak megnyitásakor nincs újabb lekérés.
        app.open_gear()
        self.assertTrue(app.can_fetch_raiderio())
        self.assertEqual(len(calls), 3)

        # Ha a szerkesztésnél javítjuk a nevet, az övé újra lekérődik.
        window = app.mythic_window
        valaki = app.data.characters[2]
        self.select_in(window, valaki)

        def fix_name():
            dialog = next(child for child in window.winfo_children() if isinstance(child, self.gui.CharacterDialog))
            dialog.name_var.set("Valira")
            dialog.accept()

        self.root.after(100, fix_name)
        window.edit_selected()
        self.wait_for_raiderio(app)
        self.assertEqual(calls[-1], "Valira")
        self.assertEqual((valaki.name, valaki.char_class, valaki.item_level), ("Valira", "Rogue", D("328.00")))

    def test_new_character_waits_for_the_running_raiderio_fetch(self):
        release = threading.Event()
        calls = []

        def fetch(region, realm, name):
            calls.append(name)
            if name == "Jaina":
                release.wait(5)
            return self.gui.raiderio.Profile(D("330.00"), D("2000.0"))

        app = self.raiderio_app(fetch, [Character("Jaina", realm="Ragnaros")])
        app.open_list()  # magától elindul a lekérés (Jainánál várakozik)
        self.add_to(app, "Thrall", "Draenor")  # közben új karakter: utána kerül sorra
        self.assertFalse(app.can_fetch_raiderio())
        release.set()
        self.wait_for_raiderio(app)
        self.assertEqual(calls, ["Jaina", "Thrall"])
        self.assertEqual([c.item_level for c in app.data.characters], [D("330.00"), D("330.00")])
        self.assertTrue(app.feedback_var.get().startswith("✔ Thrall adatai a Raider.io-ról: itemlevel 330,00"))

    def test_raiderio_fetch_problems_are_reported(self):
        calls = []

        def fetch(region, realm, name):
            calls.append(name)
            raise self.gui.raiderio.RaiderioError("a Raider.io nem érhető el (teszt).")

        app = self.raiderio_app(fetch, [Character("Thrall")])
        app.open_gear()  # magától indulna a lekérés, de egyik karakternek sincs realmje
        window = app.gear_window
        self.assertTrue(app.can_fetch_raiderio())
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            window.raiderio_button.invoke()
        self.assertIn("add meg a karakterek realmjét", info.call_args.args[1])
        self.assertEqual(calls, [])

        self.add_to(app, "Jaina", "Draenor")  # az új karakteré magától lekérődne
        self.wait_for_raiderio(app)
        self.assertEqual(
            app.feedback_var.get(),
            "⚠ Jaina: a Raider.io-adatok lekérése nem sikerült – a Raider.io nem érhető el (teszt).",
        )
        self.add_to(app, "Arthas", "Draenor")
        self.wait_for_raiderio(app)
        calls.clear()
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            window.raiderio_button.invoke()
            self.wait_for_raiderio(app)
        self.assertEqual(calls, ["Jaina"])  # az első hiba után nem próbálkozik tovább
        self.assertEqual(info.call_args.args[1], "Nem sikerült lekérni az adatokat: a Raider.io nem érhető el (teszt).")
        self.assertEqual(app.raiderio_status_var.get(), "Raider.io: a Raider.io nem érhető el (teszt).")
        self.assertIsNone(app.data.raiderio_fetched_at)
        self.assertNotIn("disabled", window.raiderio_button.state())  # újra lehet próbálni

    def wait_until_finished(self, window):
        for _ in range(500):
            self.root.update()
            if not window.running:
                return
            time.sleep(0.01)
        self.fail("a statisztikai lekérdezés nem fejeződött be")

    def test_stats_windows_open_from_the_main_window(self):
        stats = self.gui.stats_windows
        for text, attribute, window_class in (
            ("M+ ilvl statisztika", "mplus_stats_window", stats.MythicStatsWindow),
            ("Raid ilvl statisztika", "raid_stats_window", stats.RaidStatsWindow),
        ):
            button = self.find_button(self.root, text)
            button.invoke()
            window = getattr(self.app, attribute)
            self.assertIsInstance(window, window_class)
            self.assertEqual(window.title(), f"{window_class.TITLE} – {self.gui.APP_TITLE}")
            button.invoke()  # a már nyitott ablakot csak előtérbe hozza
            self.assertIs(getattr(self.app, attribute), window)
            window.close()
            self.assertIsNone(getattr(self.app, attribute))

        # Ha a statisztikai modulok nem tölthetők be (pl. hiányzik az sqlite3), a program többi része működik.
        with mock.patch.object(self.gui, "stats_windows", None), mock.patch.object(
            self.gui, "STATS_IMPORT_ERROR", "No module named '_sqlite3'", create=True
        ), mock.patch.object(self.gui.messagebox, "showerror") as error:
            self.app.open_raid_stats()
        self.assertIn("No module named '_sqlite3'", error.call_args.args[1])
        self.assertIsNone(self.app.raid_stats_window)

    def test_mplus_stats_run_in_the_background(self):
        stats = self.gui.stats_windows
        mplus = stats.mplus
        seen = {}

        def fake_run(args, seeds, make_view, info):
            seen.update(args=args, seeds=seeds)
            info("season=season-mn-2  guild(s)=Solutions@Ragnaros\n")
            state, guild_queue = mplus.new_state(), mplus.GuildQueue()
            view = make_view(state, guild_queue, "Raider.IO ilvl")
            view.start()
            for level, item_levels in ((2, [300.0, 310.0]), (4, [315.0])):
                state["runs"][level] += 1
                for value in item_levels:
                    mplus.add_ilvl(state, level, value)
                view.changed()
            state["c"]["guilds_done"] = 1
            state["c"]["cached_runs"] = 1
            view.event("guild Solutions@ragnaros@eu: 40 member(s), 38 to check")
            view.stop("finished")
            return None, state, guild_queue, "250-350"

        self.app.open_mplus_stats()
        window = self.app.mplus_stats_window
        self.assertEqual(window.region_var.get(), "eu")  # a főablakban beállított régió
        self.assertFalse(window.follow_var.get())  # a ranglistánál alapból nem követi a guildeket
        window.source_var.set("guild")
        window._source_changed()
        self.assertTrue(window.follow_var.get())  # guildeknél igen (mint a parancssorban)
        window.guilds_var.set("Solutions@Ragnaros")
        window.levels_var.set("2-4")
        window.per_level_var.set("5")
        self.assertFalse(window.cached_runs_var.get())  # alapból csak a most elért futások számítanak
        window.cached_runs_var.set(True)
        with mock.patch.object(mplus, "run", fake_run):
            window.start_button.invoke()
            self.assertTrue(window.running)
            self.assertIn("disabled", window.start_button.state())
            self.wait_until_finished(window)
        args = seen["args"]
        self.assertEqual((args.guild, args.levels, args.per_level, args.follow_guilds), (["Solutions@Ragnaros"], "2,3,4", 5, True))
        self.assertTrue(args.use_cached_runs)
        self.assertEqual(seen["seeds"], [("eu", "Ragnaros", "Solutions")])
        self.assertEqual(Path(args.cache), self.path.parent.resolve() / stats.MPLUS_CACHE_NAME)
        self.assertEqual(
            window.table.rows(),
            [("2", "1", "2", "305,0", "305,0", "302,5", "300,0", "310,0"), ("4", "1", "1", "315,0", "315,0", "315,0", "315,0", "315,0")],
        )
        self.assertEqual(window.status_var.get(), "Kész.")
        self.assertIn("beolvasott guildek: 1", window.progress_var.get())
        self.assertIn("ebből korábban letöltött (a gyorsítótárból): 1", window.progress_var.get())
        log = window.log.content()
        self.assertIn("season=season-mn-2", log)
        self.assertIn("guild Solutions@ragnaros@eu: 40 member(s)", log)
        self.assertIn("(P25 = 25th percentile", log)  # az összefoglaló is a naplóba kerül
        self.assertEqual(load_data(self.path).stats_options["mplus"]["guilds"], "Solutions@Ragnaros")
        self.assertTrue(load_data(self.path).stats_options["mplus"]["cached_runs"])

        csv_path = self.path.parent / "mplus.csv"
        with mock.patch.object(stats.filedialog, "asksaveasfilename", return_value=str(csv_path)):
            window.csv_button.invoke()
        self.assertEqual(
            csv_path.read_text(encoding="utf-8").splitlines()[:2],
            ["mythic_level,runs,players,avg_item_level,median_item_level,p25_item_level,min_item_level,max_item_level",
             "2,1,2,305.0,305.0,302.5,300.0,310.0"],
        )

        # Újranyitva a mezők az előző értékeket mutatják.
        window.close()
        self.app.open_mplus_stats()
        window = self.app.mplus_stats_window
        self.assertEqual((window.source_var.get(), window.levels_var.get()), ("guild", "2-4"))

    def test_mplus_stats_stop_and_input_checks(self):
        stats = self.gui.stats_windows
        mplus = stats.mplus
        self.app.open_mplus_stats()
        window = self.app.mplus_stats_window
        window.source_var.set("guild")
        window._source_changed()
        for guilds, levels, message in (("", "", "legalább egy guildet"), ("Solutions@Ragnaros", "x", "2-10 vagy 18,19,20")):
            window.guilds_var.set(guilds)
            window.levels_var.set(levels)
            with mock.patch.object(stats.messagebox, "showwarning") as warning:
                window.start()
            self.assertIn(message, warning.call_args.args[1])
            self.assertFalse(window.running)
        window.levels_var.set("")

        def endless_run(args, seeds, make_view, info):
            state, guild_queue = mplus.new_state(), mplus.GuildQueue()
            view = make_view(state, guild_queue, "Raider.IO ilvl")
            view.start()
            state["runs"][7] += 1
            mplus.add_ilvl(state, 7, 290.0)
            view.changed()
            while not mplus.STOP.wait(0.01):  # a guildek bejárása sokáig tart
                pass
            reason = "stopped - summarizing what was collected so far"
            view.stop(f"finished - {reason}")
            return reason, state, guild_queue, None

        with mock.patch.object(mplus, "run", endless_run):
            window.start()
            for _ in range(20):
                self.root.update()
                time.sleep(0.01)
            self.assertTrue(window.running)
            window.stop_button.invoke()
            self.wait_until_finished(window)
        self.assertEqual(window.status_var.get(), "Leállítva – a táblázat az addig összegyűjtött adatokat mutatja.")
        self.assertEqual(window.table.rows(), [("7", "1", "1", "290,0", "290,0", "290,0", "290,0", "290,0")])
        self.assertNotIn("disabled", window.csv_button.state())

    def test_raid_stats_window(self):
        stats = self.gui.stats_windows
        wcl = stats.wcl
        self.app.open_raid_stats()
        window = self.app.raid_stats_window
        window.client_id_var.set("")
        window.client_secret_var.set("")
        with mock.patch.object(stats.messagebox, "showwarning") as warning:
            window.start()
        self.assertIn("Add meg a Warcraft Logs API-kulcsot", warning.call_args.args[1])

        def stats_row(name, kills, values, players=None):
            counts = (kills,) if players is None else (kills, players)
            summary = None if not values else {"mean": sum(values) / len(values), "median": values[0],
                                               "p25": values[0], "min": min(values), "max": max(values)}
            return name, counts, summary

        raid_tables = {3: [stats_row("Első Boss", 0, []), stats_row("Összes boss", 0, [])],
                       4: [stats_row("Első Boss", 2, [330.0, 332.0]), stats_row("Összes boss", 2, [330.0, 332.0])],
                       5: [stats_row("Első Boss", 1, [340.0]), stats_row("Összes boss", 1, [340.0])]}
        player_tables = {d: [stats_row(name, counts[0], [v + 1 for v in ([summary["min"]] if summary else [])], 20)
                             for name, counts, summary in rows] for d, rows in raid_tables.items()}
        seen = {}

        def fake_run(args, cache):
            seen["args"] = args
            wcl.out("Zóna: Teszt Raid (id 50), 1 boss: Első Boss")
            return {"zone": {"name": "Teszt Raid"}, "kills": 3, "per_difficulty": {4: 2, 5: 1},
                    "sections": [("raid átlag / kill", raid_tables), ("játékos egyéni", player_tables)]}

        window.client_id_var.set("azonosito")
        window.client_secret_var.set("titok")
        window.zone_var.set("1500")
        window.region_var.set("eu")
        window.players_var.set("3")
        with mock.patch.object(wcl, "run", fake_run), mock.patch.object(wcl, "Cache") as cache:
            window.start()
            self.wait_until_finished(window)
        args = seen["args"]
        self.assertEqual((args.client_id, args.zone_id, args.zone, args.region, args.players), ("azonosito", 1500, None, "eu", 3))
        self.assertEqual(Path(cache.call_args.args[0]), self.path.parent.resolve() / stats.WCL_CACHE_NAME)
        cache.return_value.close.assert_called_once()
        self.assertEqual(window.status_var.get(), "Kész.")
        self.assertIsNone(wcl.OUTPUT)
        self.assertIn("Zóna: Teszt Raid", window.log.content())
        self.assertEqual(window.info_var.get(), "Teszt Raid · kill-ek (a duplikált logok nélkül): 3 · Normal: 0, Heroic: 2, Mythic: 1")
        heroic = window.tables[4]
        self.assertEqual(heroic.rows()[0], ("Első Boss", "2", "", "331,0", "330,0", "330,0", "330,0", "332,0"))
        self.assertEqual(heroic.tree.item(heroic.tree.get_children()[-1], "tags"), ("total",))
        self.assertEqual(window.tables[3].rows()[0], ("Első Boss", "0", "", "–", "–", "–", "–", "–"))
        self.assertNotIn("players", heroic.tree["displaycolumns"])
        window.metric_var.set("players")  # a játékosok egyéni itemlevele
        window._show_result()
        self.assertIn("players", heroic.tree["displaycolumns"])
        self.assertEqual(heroic.rows()[0][:4], ("Első Boss", "2", "20", "331,0"))
        keys = stats.load_api_keys(self.path.parent)
        self.assertEqual((keys["wcl_client_id"], keys["wcl_client_secret"]), ("azonosito", "titok"))

        csv_path = self.path.parent / "raid.csv"
        with mock.patch.object(stats.filedialog, "asksaveasfilename", return_value=str(csv_path)):
            window.save_csv()
        self.assertIn("Heroic;raid átlag / kill;Első Boss;2;;331,0", csv_path.read_text(encoding="utf-8-sig"))

        # Megjegyzés nélkül a kulcs a következő indításkor kikerül a fájlból.
        window.remember_var.set(False)
        with mock.patch.object(wcl, "run", fake_run), mock.patch.object(wcl, "Cache"):
            window.start()
            self.wait_until_finished(window)
        self.assertEqual(stats.load_api_keys(self.path.parent), {})

    def test_gear_advisor_window(self):
        advisor = self.gui.gear_advisor
        self.add("Thrall", item_level="305,25")
        self.add("Arthas")  # itemlevel nélkül nem választható
        self.find_button(self.root, "Gear ajánló").invoke()
        window = self.app.gear_advisor_window
        self.assertIsInstance(window, advisor.GearAdvisorWindow)
        self.assertEqual(list(window.character_box["values"]), [advisor.MANUAL, "Thrall (305,25)"])
        self.assertEqual(window.summary_var.get(), "70 sor látható.")  # itemlevel nélkül minden sor
        window.character_box.current(1)
        window._character_chosen()
        self.assertEqual(window.ilvl_var.get(), "305,25")
        self.assertEqual(
            window.rows()[0], ("Mythic+ 8", "303", "308", "315", "Irány farmolni!", "dropból még +2,75 ilvl")
        )
        self.assertEqual(window.tree.item(window.tree.get_children()[0], "tags"), ("recommended",))
        self.assertEqual(window.summary_var.get(), "58 sor látható, ebből 2 ajánlott.")

        # Kézzel átírva már nem a karakteré; hibás értéknél figyelmeztet, véglegesítéskor két tizedesre formáz.
        window.ilvl_var.set("abc")
        window.render()
        self.assertEqual(window.character_var.get(), advisor.MANUAL)
        self.assertEqual(window.error_var.get(), "Adj meg egy 1,00 és 500,00 közötti item levelt.")
        window.ilvl_var.set("320.5")
        window._format_ilvl()
        self.assertEqual((window.ilvl_var.get(), window.error_var.get()), ("320,50", ""))

        window.set_all_groups(False)
        self.assertIn("Nincs bepipálva egyetlen tartalomtípus sem", window.summary_var.get())
        window.group_vars["delve"].set(True)
        window.render()
        self.assertEqual(window.rows()[0][0], "Bountiful Delve Tier 11")  # csak a legjobb elérhető tier
        window.show_all_var.set(True)
        window.render()
        self.assertEqual(len(window.rows()), 11)

        # A Gear ablakból a kijelölt karakterrel nyílik; az itemlevele változását is követi.
        thrall = self.app.data.characters[0]
        self.app.open_gear()
        self.select_in(self.app.gear_window, thrall)
        self.find_button(self.app.gear_window, "Gear ajánló…").invoke()
        self.assertIs(self.app.gear_advisor_window, window)
        self.assertEqual(window.ilvl_var.get(), "305,25")
        thrall.item_level = D("310.00")
        self.app.data_changed()
        self.assertEqual((window.ilvl_var.get(), window.character_var.get()), ("310,00", "Thrall (310,00)"))

        window.close()
        self.assertIsNone(self.app.gear_advisor_window)
        self.assertEqual(load_data(self.path).stats_options["gear"], {"groups": ["delve"], "show_all": True})
        self.app.open_gear_advisor()  # a szűrők megmaradnak
        window = self.app.gear_advisor_window
        self.assertEqual([gid for gid, var in window.group_vars.items() if var.get()], ["delve"])

    def test_gear_advisor_data_transfer(self):
        advisor = self.gui.gear_advisor
        folder = self.path.parent
        live = folder / "live.csv"
        live.write_text(
            "mythic_level,runs,players,avg_item_level,median_item_level,p25_item_level,min_item_level,max_item_level\n"
            "4,3571,17222,290.8,291.4,284.0,250.0,344.0\n",
            encoding="utf-8",
        )
        self.app.open_gear_advisor()
        window = self.app.gear_advisor_window
        with mock.patch.object(advisor.filedialog, "askopenfilenames", return_value=(str(live),)), mock.patch.object(
            self.gui.messagebox, "askyesno", return_value=True
        ) as ask:
            window.import_csv()
        self.assertIn("• Mythic+ 4: 291,5 → 291,4", ask.call_args.args[1])
        self.assertEqual(load_data(self.path).gear_entry_min, {"Mythic+ 4": 291.4})
        self.assertEqual(self.app.data.gear_updated_at, {})  # a CSV régi is lehet: nem számít frissítésnek
        self.assertEqual(window.source_var.get(), "Belépési ilvl-ek: 1 sor a statisztikákból frissítve, a többi az alapérték.")
        with mock.patch.object(advisor.filedialog, "askopenfilenames", return_value=(str(live),)), mock.patch.object(
            self.gui.messagebox, "showinfo"
        ) as info:
            window.import_csv()  # ugyanaz újra: már naprakész
        self.assertIn("már megegyeznek", info.call_args.args[1])

        # A Mythic+ statisztika eredményéből (a mediánokból)
        self.app.open_mplus_stats()
        mythic = self.app.mplus_stats_window
        self.assertIn("disabled", mythic.transfer_button.state())  # eredmény nélkül nem használható
        mythic._show_rows([(10, 5, 25, 309.5, 309.0, 303.0, 250.0, 348.0)])
        mythic._set_buttons()
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            mythic.transfer_button.invoke()
        self.assertEqual(self.app.data.gear_entry_min["Mythic+ 10"], 309.0)
        self.assertEqual(mythic.status_var.get(), "Átvive a gear ajánlóba: 1 belépési ilvl.")
        self.assertEqual(list(load_data(self.path).gear_updated_at), ["mplus"])  # ehhez igazodik az automatikus

        # A raid statisztika eredményéből (a „raid átlag / kill” mediánjai, az „Összes boss” nélkül)
        self.app.open_raid_stats()
        raid = self.app.raid_stats_window
        stats_row = {"mean": 318.0, "median": 320.04, "p25": 317.0, "min": 250.0, "max": 325.0}
        raid.result = {
            "zone": {"name": "Teszt"},
            "kills": 1,
            "per_difficulty": {4: 1},
            "sections": [("raid átlag / kill", {4: [("Sszorak", (1,), stats_row), ("Összes boss", (1,), stats_row)]})],
        }
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=False):
            raid.transfer()  # nemet mondunk: nem változik
        self.assertNotIn("Raid - Sszorak Heroic", self.app.data.gear_entry_min)
        self.assertNotIn("raid", self.app.data.gear_updated_at)
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True) as ask:
            raid.transfer()
        self.assertIn("• Raid - Sszorak Heroic: 319,8 → 320", ask.call_args.args[1])
        self.assertEqual(self.app.data.gear_entry_min["Raid - Sszorak Heroic"], 320.0)
        self.assertIn("3 sor a statisztikákból frissítve", window.source_var.get())  # a nyitott ajánló is frissül

        # A HTML-oldal a mostani adatokkal; minden más marad.
        out = folder / "ajanlo.html"
        with mock.patch.object(advisor.filedialog, "asksaveasfilename", return_value=str(out)), mock.patch.object(
            advisor.messagebox, "showinfo"
        ):
            window.export_html()
        html = out.read_text(encoding="utf-8")
        template = self.gui.gearing.HTML_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('{ name: "Mythic+ 10", entryMin: 309,    dropMax: 311, vaultMax: 318 },', html)
        self.assertIn('{ name: "Raid - Sszorak Heroic",                 entryMin: 320, dropMax: 311', html)
        changed = [(a, b) for a, b in zip(template.splitlines(), html.splitlines()) if a != b]
        self.assertEqual(len(changed), 3)

        with mock.patch.object(advisor.messagebox, "askyesno", return_value=True):
            window.reset_entry_mins()
        self.assertEqual(load_data(self.path).gear_entry_min, {})
        self.assertIn("az alapértékek", window.source_var.get())

    def fake_mplus_run(self, levels=((10, (309.0, 309.0)),)):
        """A raiderio_ilvl_stats.run helyett: a megadott kulcsszintek itemlevelei, hálózat nélkül."""
        mplus = self.gui.stats_windows.mplus

        def run(args, seeds, make_view, info):
            state, guild_queue = mplus.new_state(), mplus.GuildQueue()
            view = make_view(state, guild_queue, "Raider.IO ilvl")
            view.start()
            for level, item_levels in levels:
                state["runs"][level] += 1
                for value in item_levels:
                    mplus.add_ilvl(state, level, value)
            view.stop("finished")
            return None, state, guild_queue, "250-350"

        return run

    @staticmethod
    def fake_raid_run(args, cache):
        """A wcl_raid_ilvl_stats.run helyett: egy Heroic boss kill-jei, hálózat nélkül."""
        stats_row = {"mean": 318.0, "median": 320.04, "p25": 317.0, "min": 250.0, "max": 325.0}
        tables = {4: [("Sszorak", (1,), stats_row), ("Összes boss", (1,), stats_row)]}
        sections = [("raid átlag / kill", tables)]
        return {"zone": {"name": "Teszt"}, "kills": 1, "per_difficulty": {4: 1}, "sections": sections}

    def start_auto_app(self, path, mplus_run=None, raid_run=None, while_running=None):
        """Új főablak bekapcsolt automatikus frissítéssel; a statisztikák a megadott (vagy hamis)
        futásokkal, megvárja a végüket (közben meghívja a while_running-et). Nem nyílhat kérdés."""
        stats = self.gui.stats_windows
        with mock.patch.object(stats.mplus, "run", mplus_run or self.fake_mplus_run()), mock.patch.object(
            stats.wcl, "run", raid_run or self.fake_raid_run
        ), mock.patch.object(stats.wcl, "Cache"), mock.patch.object(self.gui.messagebox, "askyesno") as ask:
            app = self.gui.App(tk.Toplevel(self.root), path, auto_stats=True)
            if while_running is not None:
                while_running(app)
            for window in (app.mplus_stats_window, app.raid_stats_window):
                if window is not None:
                    self.wait_until_finished(window)
        ask.assert_not_called()
        return app

    def test_gear_entry_levels_are_updated_automatically(self):
        stats = self.gui.stats_windows
        path = Path(self.temp_dir.name) / "auto.json"
        stats.save_api_keys(path.parent, {"wcl_client_id": "azonosito", "wcl_client_secret": "titok"})
        self.assertEqual(  # a tesztek főablakában ki van kapcsolva
            self.app.gear_status_var.get(),
            "Gear ajánló – automatikus frissítés a statisztikákból 7 naponta. "
            "M+: még nem volt; raid: még nem volt.",
        )
        release = threading.Event()

        def slow_run(args, seeds, make_view, info):
            release.wait(5)
            return self.fake_mplus_run()(args, seeds, make_view, info)

        def while_running(app):  # indításkor a rejtett ablakban fut, az állapotsor jelzi
            self.assertEqual(app.mplus_stats_window.state(), "withdrawn")
            self.assertIn("M+: fut a háttérben…", app.gear_status_var.get())
            release.set()

        app = self.start_auto_app(path, mplus_run=slow_run, while_running=while_running)
        self.assertTrue(release.is_set())
        self.assertEqual(app.data.gear_entry_min, {"Mythic+ 10": 309.0, "Raid - Sszorak Heroic": 320.0})
        saved = load_data(path)
        self.assertEqual(saved.gear_entry_min, app.data.gear_entry_min)
        self.assertEqual(set(saved.gear_updated_at), {"mplus", "raid"})
        self.assertRegex(
            app.gear_status_var.get(),
            r"^Gear ajánló – automatikus frissítés a statisztikákból 7 naponta\. M\+: frissítve "
            r"\d{4}-\d\d-\d\d \d\d:\d\d \(1 belépési ilvl változott\); "
            r"raid: frissítve .* \(1 belépési ilvl változott\)\.$",
        )
        self.assertEqual(app.gear_status_label.cget("style"), "Hint.TLabel")
        self.assertEqual(stats.load_api_keys(path.parent)["wcl_client_id"], "azonosito")  # a kulcsokhoz nem nyúlt

        # Az ablak gombjával megnyitva az automatikus frissítés eredménye látszik.
        mythic = app.mplus_stats_window
        self.assertEqual(mythic.state(), "withdrawn")
        self.assertEqual(mythic.status_var.get(), "Kész. Átvive a gear ajánlóba: 1 belépési ilvl.")
        app.open_mplus_stats()
        self.assertIs(app.mplus_stats_window, mythic)
        self.assertNotEqual(mythic.state(), "withdrawn")
        self.assertEqual(mythic.table.rows()[0][:5], ("10", "1", "2", "309,0", "309,0"))

        # Újraindítva a hét napnál frissebb adatokhoz nem indul lekérdezés.
        never = mock.Mock(side_effect=AssertionError("nem kellene lefutnia"))
        again = self.start_auto_app(path, mplus_run=never, raid_run=never)
        self.assertIsNone(again.mplus_stats_window)
        self.assertIsNone(again.raid_stats_window)
        self.assertIn("M+: legutóbb ", again.gear_status_var.get())

    def test_gear_auto_update_problems_and_retry(self):
        stats = self.gui.stats_windows
        path = Path(self.temp_dir.name) / "auto.json"

        def failing_run(args, seeds, make_view, info):
            raise stats.mplus.StatsError("a Raider.io nem érhető el")

        app = self.start_auto_app(path, mplus_run=failing_run)
        raid = app.raid_stats_window  # API-kulcs nélkül el sem indul, az ablaka rejtve marad
        self.assertEqual((raid.state(), raid.running), ("withdrawn", False))
        self.assertEqual(
            app.gear_status_var.get(),
            "Gear ajánló – automatikus frissítés a statisztikákból 7 naponta. "
            "M+: nem sikerült: a Raider.io nem érhető el; "
            "raid: nincs Warcraft Logs API-kulcs (a Raid ilvl statisztika ablakában adható meg).",
        )
        self.assertEqual(app.gear_status_label.cget("style"), "Error.TLabel")  # az M+ hibája miatt
        self.assertEqual((app.data.gear_entry_min, app.data.gear_updated_at), ({}, {}))

        # A percenkénti ellenőrzés ebben a futásban nem próbálkozik újra, a „Frissítés most” igen.
        never = mock.Mock(side_effect=AssertionError("nem kellene lefutnia"))
        with mock.patch.object(stats.mplus, "run", never):
            app._watch_date()
        self.assertFalse(app.mplus_stats_window.running)
        stats.save_api_keys(path.parent, {"wcl_client_id": "azonosito", "wcl_client_secret": "titok"})
        app.data.stats_options["raid"] = {"refresh": True}  # a raid ablakban bejelölt „Minden újra letöltése”
        with mock.patch.object(stats.mplus, "run", self.fake_mplus_run()), mock.patch.object(
            stats.wcl, "run", self.fake_raid_run
        ), mock.patch.object(stats.wcl, "Cache") as cache:
            app.update_gear_stats(force=True)
            for window in (app.mplus_stats_window, app.raid_stats_window):
                self.wait_until_finished(window)
        self.assertEqual(set(app.data.gear_updated_at), {"mplus", "raid"})
        self.assertIs(cache.call_args.kwargs["refresh"], False)  # magától nem tölt le mindent újra
        self.assertTrue(app.raid_stats_window.refresh_var.get())  # de a beállítás megmarad
        self.assertEqual(app.gear_status_label.cget("style"), "Hint.TLabel")

        # Kikapcsolva indításkor sem fut.
        app.data.gear_auto = False
        app.data.gear_updated_at.clear()
        app.save()
        again = self.start_auto_app(path, mplus_run=never, raid_run=never)
        self.assertIsNone(again.mplus_stats_window)
        self.assertIsNone(again.raid_stats_window)
        self.assertTrue(again.gear_status_var.get().startswith("Gear ajánló – az automatikus frissítés"))

    def test_automatic_run_can_be_watched_and_stopped(self):
        stats = self.gui.stats_windows
        mplus = stats.mplus
        path = Path(self.temp_dir.name) / "auto.json"

        def endless_run(args, seeds, make_view, info):
            state, guild_queue = mplus.new_state(), mplus.GuildQueue()
            view = make_view(state, guild_queue, "Raider.IO ilvl")
            view.start()
            state["runs"][7] += 1
            mplus.add_ilvl(state, 7, 290.0)
            view.changed()
            while not mplus.STOP.wait(0.01):
                pass
            reason = "stopped - summarizing what was collected so far"
            view.stop(f"finished - {reason}")
            return reason, state, guild_queue, None

        with mock.patch.object(mplus, "run", endless_run):
            app = self.gui.App(tk.Toplevel(self.root), path, auto_stats=True)
            window = app.mplus_stats_window
            for _ in range(20):
                self.root.update()
                time.sleep(0.01)
            self.assertTrue(window.running and window.automatic)
            app.open_mplus_stats()  # a gombbal megnyitva látszik a futó frissítés
            self.assertEqual(window.state(), "normal")
            self.assertEqual(window.status_var.get(), "Automatikus frissítés folyamatban (a gear ajánlóhoz)…")
            self.assertIn("disabled", window.start_button.state())
            window.close()  # bezárva a háttérben fut tovább
            self.assertEqual(window.state(), "withdrawn")
            self.assertTrue(window.running)
            self.assertIs(app.mplus_stats_window, window)
            app.open_mplus_stats()
            window.stop_button.invoke()
            self.wait_until_finished(window)
        self.assertIn("M+: leállítva; raid: nincs Warcraft Logs API-kulcs", app.gear_status_var.get())
        self.assertEqual(app.gear_status_label.cget("style"), "Hint.TLabel")  # egyik sem hiba
        self.assertEqual(app.data.gear_entry_min, {})  # a leállított frissítés eredménye nem kerül át magától
        self.assertEqual(window.state(), "normal")  # a látható ablak nyitva marad
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.transfer_button.invoke()  # kézzel átvihető
        self.assertIn("Mythic+ 7", app.data.gear_entry_min)
        self.assertIn("M+: legutóbb ", app.gear_status_var.get())
        window.close()
        self.assertIsNone(app.mplus_stats_window)

    def test_gear_advisor_auto_update_settings(self):
        self.app.open_gear_advisor()
        window = self.app.gear_advisor_window
        self.assertEqual(str(window.auto_status_label.cget("textvariable")), str(self.app.gear_status_var))
        checkbox = next(
            child
            for child in window.auto_status_label.master.winfo_children()[0].winfo_children()
            if isinstance(child, ttk.Checkbutton)
        )
        with mock.patch.object(self.app, "update_gear_stats", wraps=self.app.update_gear_stats) as update:
            checkbox.invoke()  # kikapcsolás
            self.assertFalse(self.app.data.gear_auto)
            self.assertIn("ki van kapcsolva", self.app.gear_status_var.get())
            checkbox.invoke()
            window.days_var.set("3")
            window._days_changed()
            self.assertEqual(update.call_count, 3)  # minden változás után megnézi, esedékes-e a frissítés
        saved = load_data(self.path)
        self.assertEqual((saved.gear_auto, saved.gear_auto_days), (True, 3))
        self.assertIn("a statisztikákból 3 naponta", self.app.gear_status_var.get())
        for wrong in ("0", "abc", "366"):
            window.days_var.set(wrong)
            window._days_changed()
            self.assertEqual(window.days_var.get(), "3")
        with mock.patch.object(self.app, "update_gear_stats") as update:
            self.find_button(window, "Frissítés most").invoke()
        update.assert_called_once_with(force=True)
        with mock.patch.object(self.app, "update_gear_stats") as update:
            self.app._watch_date()  # percenként megnézi, esedékes-e
        update.assert_called_once_with()

    def addon_folder(self, text=ADDON_SAVE):
        """Egy World of Warcraft mappa, benne az addon mentésével."""
        root = Path(self.temp_dir.name) / "World of Warcraft"
        saved = root / "_retail_" / "WTF" / "Account" / "111#1" / "SavedVariables"
        saved.mkdir(parents=True, exist_ok=True)
        (saved / "WoWLeveling.lua").write_text(text, encoding="utf-8")
        return root

    def test_addon_data_is_imported_at_startup(self):
        data = LevelingData(Settings.default(), [Character("Thrall", level=D("84.00")), Character("Garrosh")])
        data.addon_path = str(self.addon_folder())
        path = Path(self.temp_dir.name) / "addon.json"
        save_data(path, data)
        with mock.patch.object(self.gui.messagebox, "showinfo") as info, mock.patch.object(
            self.gui.messagebox, "showwarning"
        ) as warning, mock.patch.object(self.gui, "NewCharactersDialog") as dialog:
            app = self.gui.App(tk.Toplevel(self.root), path)
        for silent in (info, warning, dialog):  # indításkor nem kérdez, és nem nyit ablakot
            silent.assert_not_called()
        thrall = app.data.characters[0]
        self.assertEqual(
            (thrall.realm, thrall.race, thrall.char_class, thrall.spec, thrall.level, thrall.item_level),
            ("Draenor", "Orc", "Shaman", "Enhancement", D("85.29"), D("301.56")),
        )
        self.assertEqual(thrall.raiderio_score, D("1234.5"))
        self.assertEqual([c.name for c in app.data.characters], ["Thrall", "Garrosh"])  # az újak nem kerülnek fel
        saved_at = datetime.fromtimestamp(1760700200)
        self.assertEqual(
            app.addon_status_var.get(),
            f"Az addon legutóbbi mentése: {saved_at:%Y-%m-%d %H:%M}. 1 karakter adata frissült. Nincs a listán: "
            "Jaina, Arthas – a felvételükhöz kattints az „Importálás most” gombra.",
        )
        self.assertEqual(app.addon_status_label.cget("style"), "Ok.TLabel")
        self.assertEqual(load_data(path).characters[0].level, D("85.29"))  # mentette
        self.assertEqual(load_data(path).addon_imported, {"draenor/thrall": 1760700000})

        # Újraindításkor ugyanaz a mentés már nem írja felül a programban közben átírt adatokat.
        thrall.level = D("85.50")
        app.save()
        app = self.gui.App(tk.Toplevel(self.root), path)
        self.assertEqual(app.data.characters[0].level, D("85.50"))
        self.assertIn(". Nem változott semmi. Nincs a listán: Jaina, Arthas", app.addon_status_var.get())
        self.assertEqual(app.addon_status_label.cget("style"), "Hint.TLabel")

    def test_addon_import_button_adds_the_chosen_new_characters(self):
        self.add("Thrall", realm="Draenor")
        folder = self.addon_folder()
        self.app.addon_path_var.set(str(folder))
        with mock.patch.object(self.app, "_choose_new_characters", return_value=None) as choose:
            self.find_button(self.root, "Importálás most").invoke()  # az új karakterekről: Mégse
        offered, intro = choose.call_args.args
        self.assertEqual([snapshot.name for snapshot in offered], ["Jaina", "Arthas"])  # a magasabb szintű elöl
        self.assertEqual(intro, "Az addon mentése szerint 1 karakter adata frissült.")
        self.assertEqual([c.name for c in self.app.data.characters], ["Thrall"])
        self.assertEqual(self.app.data.characters[0].level, D("85.29"))
        self.assertIn("Nincs a listán: Jaina, Arthas", self.app.addon_status_var.get())
        self.assertEqual(load_data(self.path).addon_path, str(folder))  # a megadott mappát megjegyzi

        with mock.patch.object(self.app, "_choose_new_characters", side_effect=lambda found, _intro: found[:1]):
            self.app.import_addon()  # Jaina kell, Arthas nem
        jaina = self.app.data.characters[-1]
        self.assertEqual(
            [(c.name, c.realm, c.char_class, c.spec, c.level) for c in self.app.data.characters],
            [("Thrall", "Draenor", "Shaman", "Enhancement", D("85.29")), ("Jaina", "Draenor", "Mage", "Frost", D("90.00"))],
        )
        self.assertEqual(self.app.addon_status_var.get().split(". ", 1)[1], "1 új karakter felkerült a listára.")
        saved = load_data(self.path)
        self.assertEqual((saved.addon_skipped, len(saved.characters)), (["draenor/arthas"], 2))
        self.app.open_list()
        self.assertIn(jaina.uid, self.app.list_window.tree.get_children())

        # Ha nincs új karakter, az eredmény egy üzenetben jelenik meg.
        with mock.patch.object(self.app, "_choose_new_characters") as choose, mock.patch.object(
            self.gui.messagebox, "showinfo"
        ) as info:
            self.app.import_addon()
        choose.assert_not_called()
        self.assertEqual(
            info.call_args.args[1], "Az addon mentése szerint a listán lévő karakterek adatai nem változtak."
        )
        self.assertEqual(info.call_args.kwargs["detail"], "Ezeket korábban nem kérted a listára: Arthas.")

        # Az újabb mentés adatai felülírják a program adatait; a változások felsorolva.
        newer = ADDON_SAVE.replace("1760700000", "1760800000").replace('["level"] = 85', '["level"] = 86')
        self.addon_folder(newer)
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.import_addon()
        self.assertEqual(info.call_args.args[1], "Az addon mentése szerint 1 karakter adata frissült.")
        self.assertTrue(info.call_args.kwargs["detail"].startswith("Thrall: szint 85,29 → 86,29\n\n"))

    def test_addon_problems_are_reported(self):
        self.assertEqual(self.app.addon_status_var.get(), self.gui.ADDON_HINT)  # nincs megadva mappa
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.import_addon()
        self.assertEqual(info.call_args.args[1], self.gui.ADDON_HINT)

        self.app.addon_path_var.set(str(Path(self.temp_dir.name) / "nincs"))
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            self.app.import_addon(automatic=True)  # indításkor nem nyit ablakot
        warning.assert_not_called()
        self.assertIn("Nem létezik ez a mappa vagy fájl", self.app.addon_status_var.get())
        self.assertEqual(self.app.addon_status_label.cget("style"), "Error.TLabel")
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            self.app.import_addon()
        self.assertIn("Nem létezik ez a mappa vagy fájl", warning.call_args.args[1])

        broken = Path(self.temp_dir.name) / "WoWLeveling.lua"
        broken.write_text("WoWLevelingDB = {", encoding="utf-8")
        self.app.addon_path_var.set(str(broken))
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            self.app.import_addon()
        self.assertIn("nem az addon mentése, vagy sérült", warning.call_args.args[1])
        with mock.patch.object(self.gui.wow_addon, "load_addon_data", side_effect=RuntimeError("hopp")):
            self.app.import_addon(automatic=True)  # a váratlan hiba sem akasztja meg a programot
        self.assertIn("Váratlan hiba", self.app.addon_status_var.get())

        # Az addon által jelzett hiba az eredmény mellett látszik.
        self.addon_folder(ADDON_SAVE.replace('\t["version"] = 1,', '\t["lastError"] = "hopp",\n\t["version"] = 1,'))
        self.app.addon_path_var.set(str(Path(self.temp_dir.name) / "World of Warcraft"))
        self.app.import_addon(automatic=True)
        self.assertTrue(self.app.addon_status_var.get().endswith("Gond: az addon hibát jelzett: hopp"))
        self.assertEqual(self.app.addon_status_label.cget("style"), "Error.TLabel")

    def test_new_addon_saves_are_imported_while_running(self):
        self.add("Thrall", realm="Draenor")
        thrall = self.app.data.characters[0]
        folder = Path(self.temp_dir.name) / "World of Warcraft"
        (folder / "_retail_" / "WTF").mkdir(parents=True)
        self.app.addon_path_var.set(str(folder))
        self.app.import_addon(automatic=True)
        self.assertIn("Még nincs mentett adat", self.app.addon_status_var.get())

        def loads():
            return mock.patch.object(self.gui.wow_addon, "load_addon_data", wraps=wow_addon.load_addon_data)

        # Az első mentés: amint a játék kiírta (és a fájl két nézés között már nem változott), beolvassa.
        with loads() as load:
            self.app._check_addon_saves()  # még mindig nincs mentés
            saved = next(self.addon_folder().glob("_retail_/WTF/Account/*/SavedVariables/WoWLeveling.lua"))
            self.app._check_addon_saves()  # a játék még írhatja
            load.assert_not_called()
            self.app._check_addon_saves()
            load.assert_called_once_with(str(folder))
        self.assertEqual(thrall.level, D("85.29"))
        self.assertEqual(load_data(self.path).characters[0].level, D("85.29"))  # mentette is
        written = saved.stat().st_mtime_ns

        def game_writes(level, seconds):
            """A játék új mentést ír ki (a módosítás idejét kézzel lépteti, hogy biztosan más legyen)."""
            stamp = str(1760700000 + seconds)
            saved.write_text(ADDON_SAVE.replace('["level"] = 85', f'["level"] = {level}').replace("1760700000", stamp))
            os.utime(saved, ns=(written + seconds * 10**9,) * 2)

        # Egy újabb mentés (pl. karakterváltáskor vagy /reload után): amíg változik, vár.
        with loads() as load:
            self.app._check_addon_saves()  # nem változott semmi
            game_writes(86, 10)
            self.app._check_addon_saves()
            game_writes(87, 20)
            self.app._check_addon_saves()
            load.assert_not_called()
            self.app._check_addon_saves()
            self.app._check_addon_saves()  # egyszer olvassa be
            load.assert_called_once()
        self.assertEqual(thrall.level, D("87.29"))
        self.assertIn(". 1 karakter adata frissült. ", self.app.addon_status_var.get())
        self.assertEqual(self.app.addon_status_label.cget("style"), "Ok.TLabel")

        # Amíg a gombbal indított importálás kérdez, nem kezd újabb beolvasásba; utána beolvassa.
        def dialog(_found, _intro):
            game_writes(88, 30)
            for _ in range(3):
                self.app._check_addon_saves()
            return None  # Mégse

        with loads() as load, mock.patch.object(self.app, "_choose_new_characters", side_effect=dialog):
            self.app.import_addon()
            load.assert_called_once()
            self.assertEqual(thrall.level, D("87.29"))
            self.app._check_addon_saves()
            self.app._check_addon_saves()
            self.assertEqual(load.call_count, 2)
        self.assertEqual(thrall.level, D("88.29"))

        # Amíg a WoW mappáját írják át, nem figyel (és a félig beírt útvonalat sem jegyzi meg).
        self.app.addon_path_var.set(str(folder)[:-3])
        game_writes(89, 40)
        with loads() as load:
            for _ in range(3):
                self.app._check_addon_saves()
        load.assert_not_called()
        self.assertEqual(self.app.data.addon_path, str(folder))

        # Két másodpercenként néz rá.
        with mock.patch.object(self.app, "_check_addon_saves") as check, mock.patch.object(self.root, "after") as after:
            self.app._watch_addon()
        check.assert_called_once_with()
        after.assert_called_once_with(self.gui.ADDON_WATCH_MS, self.app._watch_addon)

    def test_old_addon_version_is_pointed_out(self):
        # A régi addon nem írja be a változatát: a program szól, hogy az új mikor töltődik be a játékban.
        old = ADDON_SAVE.replace(f'\t["addonVersion"] = "{ADDON_VERSION}",\n', "")
        self.app.addon_path_var.set(str(self.addon_folder(old)))
        self.app.import_addon(automatic=True)
        self.assertIn(
            f"A legutóbbi mentést még az addon régebbi változata írta: az új ({ADDON_VERSION}) a játék következő "
            "indításakor vagy /reload után töltődik be.",
            self.app.addon_status_var.get(),
        )
        self.addon_folder()  # már az új változat mentése
        self.app.import_addon(automatic=True)
        self.assertNotIn("régebbi változata", self.app.addon_status_var.get())

    def test_wow_folder_can_be_browsed_and_the_addon_installed(self):
        folder = self.addon_folder()
        with mock.patch.object(self.gui.filedialog, "askdirectory", return_value=str(folder)) as ask, mock.patch.object(
            self.app, "_choose_new_characters", return_value=None
        ):
            self.find_button(self.root, "Tallózás…").invoke()
        self.assertIsNone(ask.call_args.kwargs["initialdir"])
        self.assertEqual(self.app.data.addon_path, str(folder))
        self.assertIn("Nincs a listán: Jaina, Thrall, Arthas", self.app.addon_status_var.get())  # be is olvasta
        with mock.patch.object(self.gui.filedialog, "askdirectory", return_value="") as ask:
            self.app.browse_addon_path()  # Mégse
        self.assertEqual(ask.call_args.kwargs["initialdir"], str(folder))
        self.assertEqual(self.app.data.addon_path, str(folder))

        target = folder / "_retail_" / "Interface" / "AddOns" / "WoWLeveling"
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True) as ask, mock.patch.object(
            self.gui.messagebox, "showinfo"
        ) as info:
            self.find_button(self.root, "Addon telepítése…").invoke()
        self.assertEqual(ask.call_args.args[1], f"Telepítsem (frissítsem) az addont ide?\n{target}")
        self.assertEqual(info.call_args.args[1], self.gui.ADDON_INSTALLED)
        self.assertEqual(
            sorted(path.name for path in target.iterdir()),
            ["Gear.lua", "Plan.lua", "PlanData.lua", "WoWLeveling.lua", "WoWLeveling.toc"],
        )
        plan = wow_addon.parse_lua((target / "PlanData.lua").read_text(encoding="utf-8"))  # a terv is odakerült
        self.assertEqual(plan[wow_addon.PLAN_VARIABLE]["version"], 1)
        self.assertIn("Szinkronizálva az addonba:", self.app.addon_status_var.get())

        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True), mock.patch.object(
            self.gui.wow_addon, "install_addon", side_effect=PermissionError("nincs jogosultság")
        ), mock.patch.object(self.gui.messagebox, "showerror") as error:
            self.app.install_addon()
        self.assertIn("nincs jogosultság", error.call_args.args[1])

        # A szokásos helyen talált játékba is telepíthető, és a mappát megjegyzi.
        self.app.addon_path_var.set("")
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.install_addon()
        self.assertIn("Nem találom a játék mappáját", info.call_args.args[1])
        with mock.patch.object(wow_addon, "default_wow_folders", return_value=[folder]), mock.patch.object(
            self.gui.messagebox, "askyesno", return_value=True
        ), mock.patch.object(self.gui.messagebox, "showinfo"):
            self.app.install_addon()
        self.assertEqual(self.app.addon_path_var.get(), str(folder))
        self.assertEqual(self.app.data.addon_path, str(folder))

    def test_plan_is_synced_to_the_addon(self):
        def plan_names():
            text = (target / wow_addon.PLAN_FILE).read_text(encoding="utf-8")
            characters = wow_addon.parse_lua(text)[wow_addon.PLAN_VARIABLE]["characters"]
            return [characters[index]["name"] for index in sorted(characters)]

        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.find_button(self.root, "Szinkronizálás").invoke()  # nincs megadva a WoW mappája
        self.assertIn("Add meg a World of Warcraft mappáját", info.call_args.args[1])
        folder = self.addon_folder()
        self.app.addon_path_var.set(str(folder))
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            self.app.sync_addon_plan()  # nincs telepítve az addon
        self.assertIn("Az addon nincs telepítve ebben a WoW mappában", info.call_args.args[1])

        target = wow_addon.install_addon(folder / "_retail_")
        self.add("Thrall", realm="Draenor", level="83,5")
        self.app.sync_addon_plan()
        self.assertEqual(plan_names(), ["Thrall"])
        status = self.app.addon_status_var.get()
        self.assertRegex(
            status, r"Szinkronizálva az addonba: \d{4}-\d\d-\d\d \d\d:\d\d – a játékban /reload után látszik\.$"
        )

        # Minden mentés után magától, egy másodperccel később (a gyors mentések után egyszer).
        self.add("Jaina")
        self.assertIsNotNone(self.app._sync_job)
        for _ in range(300):
            self.root.update()
            if self.app._sync_job is None:
                break
            time.sleep(0.01)
        self.assertEqual(plan_names(), ["Thrall", "Jaina"])
        with mock.patch.object(wow_addon, "write_plan") as write:
            self.app.save()  # nem változott a terv: nem írja újra
            self.app.sync_addon_plan(automatic=True)
        write.assert_not_called()

        # A gear ajánló adatai is átmennek; a statisztikákból frissített belépési ilvl változása is.
        def gear_entry(name):
            text = (target / wow_addon.PLAN_FILE).read_text(encoding="utf-8")
            groups = wow_addon.parse_lua(text)[wow_addon.PLAN_VARIABLE]["gear"]["groups"]
            return next(row["entry"] for group in groups.values() for row in group["rows"].values() if row["name"] == name)

        self.assertEqual(gear_entry("Mythic+ 10"), 31160)
        self.app.data.gear_entry_min["Mythic+ 10"] = 309.5
        self.app.sync_addon_plan(automatic=True)
        self.assertEqual(gear_entry("Mythic+ 10"), 30950)

        # Ha nem írható, az állapotsor jelzi (a gombnál üzenet is).
        self.app.data.characters[0].level = D("84.00")
        with mock.patch.object(wow_addon, "write_plan", side_effect=PermissionError("nincs jogosultság")):
            self.app.sync_addon_plan(automatic=True)
            self.assertIn("A terv átadása az addonnak nem sikerült: nincs jogosultság", self.app.addon_status_var.get())
            self.assertEqual(self.app.addon_status_label.cget("style"), "Error.TLabel")
            with mock.patch.object(self.gui.messagebox, "showerror") as error:
                self.app.sync_addon_plan()
        self.assertIn("nincs jogosultság", error.call_args.args[1])
        self.app.sync_addon_plan(automatic=True)
        self.assertNotEqual(self.app.addon_status_label.cget("style"), "Error.TLabel")
        self.assertEqual(self.app._sync_job, None)

    def test_plan_is_synced_at_startup(self):
        folder = self.addon_folder()
        target = wow_addon.install_addon(folder / "_retail_")
        data = LevelingData(Settings.default(), [Character("Thrall")])
        data.addon_path = str(folder)
        path = Path(self.temp_dir.name) / "indulas.json"
        save_data(path, data)
        before = (target / wow_addon.PLAN_FILE).read_text(encoding="utf-8")
        self.assertEqual(wow_addon.parse_lua(before), {})  # még a telepítéskori üres terv
        app = self.gui.App(tk.Toplevel(self.root), path)
        plan = wow_addon.parse_lua((target / wow_addon.PLAN_FILE).read_text(encoding="utf-8"))
        self.assertEqual(plan[wow_addon.PLAN_VARIABLE]["characters"][1]["name"], "Thrall")
        self.assertIn("Szinkronizálva az addonba:", app.addon_status_var.get())

    def test_addon_is_found_in_the_usual_place_at_startup(self):
        folder = self.addon_folder()
        with mock.patch.object(wow_addon, "default_wow_folders", return_value=[Path(self.temp_dir.name), folder]):
            app = self.gui.App(tk.Toplevel(self.root), Path(self.temp_dir.name) / "uj.json")
        self.assertEqual(app.data.addon_path, str(folder))
        self.assertIn("Nincs a listán: Jaina, Thrall, Arthas", app.addon_status_var.get())

    def test_new_characters_dialog(self):
        snapshots = [
            wow_addon.Snapshot("Jaina", "Draenor", "eu", "", "Mage", "Frost", D("90.00"), None, None, 1),
            wow_addon.Snapshot("Arthas", "Draenor", "eu", "Human", "Death Knight", "", D("80.50"), D("280"), None, 2),
        ]

        def checkbuttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Checkbutton):
                    yield child
                yield from checkbuttons(child)

        def pick():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, self.gui.NewCharactersDialog))
            self.assertEqual(
                [check.cget("text") for check in checkbuttons(dialog)],
                [
                    "Jaina (Draenor) – szint: 90,00, Mage, Frost",
                    "Arthas (Draenor) – szint: 80,50, Human Death Knight, itemlevel 280,00",
                ],
            )
            dialog.chosen_vars[0].set(False)
            dialog.accept()

        self.root.after(50, pick)
        self.assertEqual(self.app._choose_new_characters(snapshots, "1 karakter adata frissült."), snapshots[1:])
        dialog = self.gui.NewCharactersDialog(self.root, snapshots)
        dialog.destroy()  # Mégse vagy Escape
        self.assertIsNone(dialog.result)

    def test_region_setting_is_saved(self):
        self.assertEqual(self.app.region_var.get(), "EU")
        self.app.region_var.set("KR")
        self.assertEqual(load_data(self.path).settings.region, "kr")

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
        window.value_var.set("27,7")  # a mai, a holnapi és a holnaputáni cél is megvan
        window.apply_value()
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
        # A nézet rendezése nem változik (itt a név szerinti); az új sorrend a # oszlopban látszik.
        self.assertEqual(self.app.list_sort, ("name", False))
        self.assertEqual(self.names(), ["Illidan", "Jaina", "Khadgar", "Uther"])
        positions = {row["name"]: row["position"] for row in self.rows()}
        self.assertEqual(positions, {"Uther": "1", "Khadgar": "2", "Jaina": "3", "Illidan": "4"})

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
        window.value_var.set("70")
        window.apply_value()
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
        field = self.gui.NumberSpinbox(self.root, variable, empty_value=lambda: D("80"))
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
                "role": "–",
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
        # A spec mellett jobbra a role, utána a szint, majd az itemlevel látszik.
        shown = list(tree["displaycolumns"])
        self.assertEqual(shown[shown.index("spec") : shown.index("spec") + 4], ["spec", "role", "level", "item_level"])

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

        # Alapból az állapot szerint rendez (lásd lent); a fejlécre kattintva a szinteltérés szerint.
        self.assertEqual(self.app.list_sort, self.gui.LIST_ORDER)
        self.assertEqual((tree.heading("status", "text"), tree.heading("position", "text")), ("Állapot ▲", "#"))
        self.assertTrue(str(tree.heading("deviation", "command")))  # a fejléc kattintható
        window.sort_by("deviation")
        self.assertEqual(self.names(), ["Thrall", "Sylvanas", "Arthas", "Jaina"])
        self.assertEqual([row["deviation"] for row in self.rows()], ["−4,90", "−2,96", "−2,86", "+43,77"])
        self.assertEqual((tree.heading("deviation", "text"), tree.heading("status", "text")), ("Szinteltérés ▲", "Állapot"))
        window.sort_by("deviation")  # újabb kattintásra megfordul
        self.assertEqual(self.names(), ["Jaina", "Arthas", "Sylvanas", "Thrall"])
        self.assertEqual(tree.heading("deviation", "text"), "Szinteltérés ▼")
        self.app.open_list()  # a már nyitott ablakot csak előtérbe hozza, a rendezése marad
        self.assertEqual(tree.heading("deviation", "text"), "Szinteltérés ▼")

        # Rendezett nézetben nem lehet átrendezni, a karakterek sorrendje (és a céldátumok) nem változik.
        jaina = self.app.data.characters[1]
        self.select(jaina)
        self.assertIn("disabled", window._order_widgets[0].state())
        self.assertTrue(window.order_hint_var.get())
        window.move_selected(-1)
        self.assertEqual([c.name for c in self.app.data.characters], ["Thrall", "Jaina", "Arthas", "Sylvanas"])

        # Szintmódosítás után újrarendeződik, a kijelölés megmarad.
        window.value_var.set("1")
        window.apply_value()  # Jaina: 1 − 6,23 = −5,23, a nézet végére kerül
        self.assertEqual(self.names(), ["Arthas", "Sylvanas", "Thrall", "Jaina"])
        self.assertEqual(tree.selection(), (jaina.uid,))

        # Törléskor a nézetben szomszédos sor lesz kijelölve (az utolsó sor helyett az előző).
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            window.delete_selected()
        self.assertEqual(window.selected_var.get(), "Thrall")

        # Újranyitáskor ismét az állapot szerinti sorrend látszik (mindenki ütemben: a szinteltérés dönt).
        window.close()
        self.app.open_list()
        window = self.app.list_window
        self.assertEqual(self.names(), ["Thrall", "Arthas", "Sylvanas"])  # 3 karakterrel: −4,90 / −3,45 / −2,96
        self.assertEqual(window.tree.heading("status", "text"), "Állapot ▲")
        self.assertEqual(window.tree.heading("deviation", "text"), "Szinteltérés")

        # A # oszlop visszaállítja az eredeti sorrendet, és újra lehet átrendezni.
        window.sort_by("position")
        self.assertEqual(self.names(), ["Thrall", "Arthas", "Sylvanas"])
        self.assertEqual(window.tree.heading("position", "text"), "# ▲")
        self.select(self.app.data.characters[1])
        self.assertNotIn("disabled", window._order_widgets[0].state())
        self.assertEqual(window.order_hint_var.get(), "")

    def test_list_opens_sorted_by_status_with_finished_characters_last(self):
        today = date.today()
        self.app.start_var.set(format_date(today - timedelta(days=10)))
        self.app.first_var.set(format_date(today - timedelta(days=1)))
        self.app.last_var.set(format_date(today + timedelta(days=10)))
        self.add("Thrall", level="90")  # célszinten: kész (a céldátuma már lejárt, a szinteltérése 0,00)
        self.add("Jaina", level="80")  # előrébb jár: +9,08
        self.add("Arthas", level="30")  # lemaradásban: −28,58
        self.add("Sylvanas", level="60")  # előrébb jár: +12,39
        self.app.open_list()
        window = self.app.list_window

        # Elöl a legsürgősebb, azonos állapotban a szinteltérés dönt; a célszintet elért karakter a végén.
        self.assertEqual(self.app.list_sort, ("status", False))
        self.assertEqual(self.names(), ["Arthas", "Jaina", "Sylvanas", "Thrall"])
        self.assertEqual(self.rows()[-1]["status"], "Kész – elérte a célszintet")
        self.assertEqual(window.tree.heading("status", "text"), "Állapot ▲")
        window.sort_by("deviation")  # a szinteltérés szerint a kész karakter (0,00) középre kerülne
        self.assertEqual(self.names(), ["Arthas", "Thrall", "Jaina", "Sylvanas"])

    def test_level_changes_reordering_and_deletion(self):
        self.add("Thrall", "Jaina", "Arthas")
        self.app.open_list()
        window = self.app.list_window
        thrall = self.app.data.characters[0]
        self.select(thrall)

        window.change_value(1)
        self.assertEqual(thrall.level, D("2.00"))
        window.value_var.set("35,5")
        window.apply_value()
        self.assertEqual(thrall.level, D("35.50"))
        self.assertEqual(window.value_var.get(), "35,50")
        self.assertEqual(load_data(self.path).characters[0].level, D("35.50"))
        window.value_spin.event_generate("<<Increment>>")  # a nyíl azonnal menti is
        self.assertEqual(load_data(self.path).characters[0].level, D("36.50"))
        with mock.patch.object(self.gui.messagebox, "showwarning") as warning:
            window.value_var.set("35,555")
            window.apply_value()
        warning.assert_called_once()
        self.assertEqual(thrall.level, D("36.50"))
        window.value_var.set("95")  # a célszint felett is lehet
        window.apply_value()
        self.assertEqual(thrall.level, D("95.00"))

        window.sort_by("position")  # átrendezni a # szerinti nézetben lehet
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
        self.app.data.spec_scores = SpecScores({"mage/fire": D("3700"), "warlock/destruction": D("3650")})
        with mock.patch.object(self.app, "_ask_faction", return_value=None), mock.patch.object(
            self.gui.messagebox, "askyesno"
        ) as ask:
            self.app.show_combo_recommendation()  # a frakciókérdést bezárták
        ask.assert_not_called()

        # Egy tank (plate, Warrior, Orc) után a combók közti arányukhoz képest a ranged DPS és a cloth
        # hiányzik leginkább; ezek közül a Fire Mage-nek a legmagasabb a Murlok.io-pontszáma.
        with mock.patch.object(self.app, "_ask_faction", return_value="Horde"), mock.patch.object(
            self.gui.messagebox, "askyesno", return_value=False
        ) as ask:
            self.app.show_combo_recommendation()
        self.assertEqual(
            ask.call_args.args[1],
            "Ajánlott Horde karakter:\nUndead Fire Mage\n\nKitöltsem vele az új karakter mezőit?",
        )
        detail = ask.call_args.kwargs["detail"]
        self.assertIn("• szerep – ranged DPS: még egy sincs (0%); az összes combó 37%-a", detail)
        self.assertIn("• páncéltípus – cloth: még egy sincs (0%); az összes combó 32%-a", detail)
        self.assertEqual(self.app._last_faction, "Horde")  # legközelebb ez az alapértelmezett
        self.assertEqual((self.app.race_var.get(), self.app.class_var.get(), self.app.spec_var.get()), ("", "", ""))

        self.app.name_var.set("Sylvanas")
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.app.show_combo_recommendation("Horde")
        filled = (self.app.race_var.get(), self.app.class_var.get(), self.app.spec_var.get())
        self.assertEqual(filled, ("Undead", "Mage", "Fire"))
        self.assertEqual(self.app.name_var.get(), "Sylvanas")  # a beírt név megmarad
        self.assertIn("Kitöltve: Undead Fire Mage", self.app.feedback_var.get())
        self.app.add_character()
        added = self.app.data.characters[-1]
        self.assertEqual((added.name, added.race, added.char_class, added.spec), ("Sylvanas", "Undead", "Mage", "Fire"))

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
