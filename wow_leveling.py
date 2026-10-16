#!/usr/bin/env python3
"""WoW szintezés tervező – grafikus felület.

World of Warcraft karakterek szintezésének megtervezését és követését segítő
program. Indítás:

    python wow_leveling.py [adatfájl]

A beállításokat és a karaktereket a program automatikusan menti, alapértelmezés
szerint a program mappájában lévő ``szintezes_adatok.json`` fájlba.
"""

from __future__ import annotations

import argparse
import calendar
import queue
import sys
import threading
import tkinter as tk
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from leveling import (
    HU_MONTHS,
    ITEM_LEVEL_MAX,
    LEVEL_MAX,
    LEVEL_MIN,
    PARALLEL,
    SEQUENTIAL,
    Character,
    CharacterPlan,
    LevelingData,
    Settings,
    SpecScores,
    Status,
    build_plan,
    day_progress,
    estimate_target_dates,
    format_date,
    format_deviation,
    format_item_level,
    format_level,
    format_raiderio_score,
    format_compact,
    goal_day_phrase,
    load_data,
    lookahead_day,
    murlok_order,
    parse_date,
    plan_item_levels,
    parse_item_level,
    reached_target_item_level,
    parse_level,
    parse_raiderio_score,
    save_data,
    sort_plans,
)
import murlok
from recommend import recommend_combo
from wow_data import ALL_SPECS, ALLIANCE, FACTIONS, WOW_CLASSES, WOW_RACES, specs_for_class

APP_TITLE = "WoW szintezés tervező"
DATA_FILE_NAME = "szintezes_adatok.json"

INTRO_TEXT = (
    "Add meg, mikor kezdődik a szintezés, mikorra érje el az első, illetve az utolsó karakter a "
    "célszintet, és hogy a terv melyik szintről melyikre vezet. A köztes karakterek céldátumait a "
    "program egyenletesen osztja el, és kiszámolja a napi célokat. A szinteket két tizedesjegy "
    "pontossággal adhatod meg (pl. 83,45)."
)


HU_WEEKDAYS = ("hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap")
HU_WEEKDAY_ABBREVIATIONS = ("H", "K", "Sze", "Cs", "P", "Szo", "V")

OK_COLOR = "#1b7f3a"
ERROR_COLOR = "#c62828"
HINT_COLOR = "#5f6368"
SELECTED_DAY_COLOR = "#1f5fae"
HOVER_DAY_COLOR = "#cfe0f5"
OTHER_MONTH_COLOR = "#9aa0a6"

SORT_ARROWS = {False: " ▲", True: " ▼"}  # növekvő / csökkenő rendezés jele a fejlécben
PLAN_ORDER = ("position", False)  # a lista eredeti (# szerinti) sorrendje
GEAR_ORDER = ("item_level_deviation", False)  # a Gear ablak alapból az itemlevel-eltérés szerint rendez

BEHIND_COLOR = "#b35c00"

# Az „Ütemben” állapot az alapértelmezett betűszínnel jelenik meg.
STATUS_COLORS = {
    Status.DONE: OK_COLOR,
    Status.GOAL_MET: OK_COLOR,
    Status.AHEAD: "#1f5fae",
    Status.BEHIND: BEHIND_COLOR,
    Status.OVERDUE: ERROR_COLOR,
    Status.NOT_STARTED: "#80868b",
}


def default_data_path() -> Path:
    """Az adatfájl alapértelmezett helye: a program mappája."""
    if getattr(sys, "frozen", False):  # pl. PyInstallerrel készült .exe esetén
        folder = Path(sys.executable).resolve().parent
    else:
        folder = Path(__file__).resolve().parent
    return folder / DATA_FILE_NAME


def long_date(value: date) -> str:
    return f"{value.year}. {HU_MONTHS[value.month - 1]} {value.day}., {HU_WEEKDAYS[value.weekday()]}"


def format_number(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def article(word: str) -> str:
    """A szóhoz illő határozott névelő: „a Thrall”, de „az Arthas”."""
    return "az" if word[:1].lower() in tuple("aáeéiíoóöőuúüű") else "a"


def link_spec_to_class(class_var: tk.StringVar, spec_var: tk.StringVar, spec_box: ttk.Combobox) -> None:
    """A spec-választó listája mindig a kiválasztott kaszt specjeit kínálja.

    Kasztváltáskor a már kiválasztott spec törlődik, ha az biztosan nem az új
    kaszthoz tartozik (a saját, kézzel beírt szöveg megmarad).
    """
    known = {spec.casefold() for spec in ALL_SPECS}

    def update(*_args) -> None:
        specs = specs_for_class(class_var.get())
        spec_box.configure(values=specs)
        spec = spec_var.get().strip().casefold()
        if spec in known and spec not in {item.casefold() for item in specs}:
            spec_var.set("")

    spec_box.configure(values=specs_for_class(class_var.get()))
    class_var.trace_add("write", update)


def style_font(style: ttk.Style, element: str, default: str) -> tkfont.Font:
    """Egy ttk-stíluselem betűtípusa, a szövegek szélességének méréséhez."""
    name = style.lookup(element, "font") or default
    try:
        return tkfont.nametofont(name)
    except tk.TclError:
        return tkfont.Font(font=name)


def goal_heading(goal_day: date, today: date) -> str:
    """A cél oszlop fejléce: „Mai cél”, „Holnapi cél”, vagy pl. „Cél (10-18)”."""
    offset = (goal_day - today).days
    return "Mai cél" if offset == 0 else "Holnapi cél" if offset == 1 else f"Cél ({goal_day:%m-%d})"


def look_ahead_text(goal_day: date, today: date) -> str:
    """Magyarázat, ha a lista egy későbbi nap céljait mutatja (különben üres)."""
    offset = (goal_day - today).days
    if offset <= 0:
        return ""
    if offset == 1:
        done = "A mai célt"
    elif offset == 2:
        done = "A mai és a holnapi célt is"
    else:
        done = f"A mai és a következő {offset - 1} nap célját is"
    return f"{done} minden karakter teljesítette, ezért {goal_day_phrase(goal_day, today)} célok látszanak."


def describe_character(character: Character) -> str:
    """A karakter rövid leírása, pl. „Arthas-Draenor (Undead Death Knight, Unholy)”."""
    name = f"{character.name}-{character.realm}" if character.realm else character.name
    kind = " ".join(part for part in (character.race, character.char_class) if part)
    details = ", ".join(part for part in (kind, character.spec) if part)
    return f"{name} ({details})" if details else name


def place_over(window: tk.Toplevel, parent: tk.Misc) -> None:
    """Az ablakot a szülőablak fölé, vízszintesen középre helyezi."""
    window.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 3
    window.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def show_modal(window: tk.Toplevel) -> None:
    """Megjeleníti az ablakot; amíg nyitva van, a többi ablak nem kattintható."""
    window.deiconify()
    try:
        window.wait_visibility()
        window.grab_set()
    except tk.TclError:
        pass
    window.focus_set()


class DateField(ttk.Frame):
    """Dátummező, mellette naptárt nyitó gombbal."""

    def __init__(self, master: tk.Misc, variable: tk.StringVar) -> None:
        super().__init__(master)
        self.variable = variable
        self.entry = ttk.Entry(self, textvariable=variable, width=12)
        self.entry.pack(side="left")
        ttk.Button(
            self, text="▼", width=2, style="Compact.TButton", takefocus=False, command=self.open_calendar
        ).pack(side="left", padx=(3, 0), fill="y")

    def open_calendar(self) -> None:
        try:
            current = parse_date(self.variable.get())
        except ValueError:
            current = date.today()
        CalendarPopup(self, current, self._picked)

    def _picked(self, value: date) -> None:
        self.variable.set(format_date(value))
        self.entry.focus_set()
        self.entry.icursor("end")


@dataclass(frozen=True)
class NumberField:
    """Két tizedesjegyű szám a karakteren (szint vagy itemlevel), a beolvasásához és kiírásához."""

    attribute: str  # a Character mezője
    label: str  # a listaablak alján, a kijelölt karakternél
    unit: str  # a léptetőgomb felirata: „+1 <unit>”
    error_title: str
    parse: Callable[[str], Decimal | None]  # hibás szövegnél ValueError
    format: Callable[[Decimal], str]
    minimum: Decimal
    maximum: Decimal


LEVEL_FIELD = NumberField(
    "level", "Jelenlegi szint:", "szint", "Hibás szint", parse_level, format_level, LEVEL_MIN, LEVEL_MAX
)
# Az itemlevel üresen is hagyható (None: nincs megadva).
ITEM_LEVEL_FIELD = NumberField(
    "item_level",
    "Itemlevel:",
    "itemlevel",
    "Hibás itemlevel",
    parse_item_level,
    format_item_level,
    Decimal(0),
    ITEM_LEVEL_MAX,
)


class NumberSpinbox(ttk.Spinbox):
    """Szám két tizedesjegy pontossággal (pl. 83,45), alapból szint.

    A nyilak, a fel/le billentyűk és az egérgörgő egy egésszel léptetnek.
    """

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.StringVar,
        on_step=None,
        empty_value=None,
        field: NumberField = LEVEL_FIELD,
    ) -> None:
        super().__init__(master, textvariable=variable, width=8)
        self._variable = variable
        self._on_step = on_step  # léptetés után hívódik meg
        self._empty_value = empty_value  # üres mezőnél innen indul a léptetés
        self._field = field
        # A Tk saját léptetése nem ismeri a tizedesvesszőt, ezért itt kezeljük.
        self.bind("<<Increment>>", lambda _event: self._step(1))
        self.bind("<<Decrement>>", lambda _event: self._step(-1))

    def _step(self, delta: int) -> str:
        text = self._variable.get()
        try:
            if not text.strip() and self._empty_value is not None:
                value = self._empty_value()
            else:
                value = self._field.parse(text)
        except ValueError:
            value = None
        if value is None:  # hibás vagy üres mező
            self.bell()
            return "break"
        field = self._field
        self._variable.set(field.format(min(max(value + delta, field.minimum), field.maximum)))
        if self._on_step is not None:
            self._on_step()
        return "break"


class CalendarPopup(tk.Toplevel):
    """Egyszerű naptár a dátum kiválasztásához (külső csomag nélkül)."""

    def __init__(self, anchor: tk.Widget, selected: date, on_pick) -> None:
        super().__init__(anchor)
        self.withdraw()
        self.title("Dátum választása")
        self.resizable(False, False)
        self.transient(anchor.winfo_toplevel())
        self._on_pick = on_pick
        self._selected = selected
        self._month = selected.replace(day=1)
        style = ttk.Style(self)
        self._background = style.lookup("TFrame", "background") or self.cget("background")
        self._foreground = style.lookup("TLabel", "foreground") or "black"

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        navigation = ttk.Frame(body)
        navigation.pack(fill="x")
        ttk.Button(navigation, text="◀", width=3, command=lambda: self._shift_month(-1)).pack(side="left")
        ttk.Button(navigation, text="▶", width=3, command=lambda: self._shift_month(1)).pack(side="right")
        self._month_label = ttk.Label(navigation, anchor="center", style="Strong.TLabel")
        self._month_label.pack(side="left", fill="x", expand=True)
        self._days_frame = ttk.Frame(body)
        self._days_frame.pack(pady=6)
        ttk.Button(body, text="Ma", command=lambda: self._pick(date.today())).pack()

        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Prior>", lambda _event: self._shift_month(-1))  # Page Up
        self.bind("<Next>", lambda _event: self._shift_month(1))  # Page Down
        self._render()

        self.update_idletasks()
        self.geometry(f"+{anchor.winfo_rootx()}+{anchor.winfo_rooty() + anchor.winfo_height() + 2}")
        show_modal(self)

    def _shift_month(self, delta: int) -> None:
        index = self._month.year * 12 + self._month.month - 1 + delta
        self._month = date(index // 12, index % 12 + 1, 1)
        self._render()

    def _pick(self, value: date) -> None:
        self.destroy()
        self._on_pick(value)

    def _render(self) -> None:
        for child in self._days_frame.winfo_children():
            child.destroy()
        self._month_label.configure(text=f"{self._month.year}. {HU_MONTHS[self._month.month - 1]}")
        for column, name in enumerate(HU_WEEKDAY_ABBREVIATIONS):
            ttk.Label(self._days_frame, text=name, width=4, anchor="center", style="Hint.TLabel").grid(
                row=0, column=column
            )
        today = date.today()
        weeks = calendar.Calendar(calendar.MONDAY).monthdatescalendar(self._month.year, self._month.month)
        for row, week in enumerate(weeks, start=1):
            for column, day in enumerate(week):
                self._day_cell(day, today).grid(row=row, column=column, padx=1, pady=1)

    def _day_cell(self, day: date, today: date) -> tk.Label:
        selected = day == self._selected
        if selected:
            background, foreground = SELECTED_DAY_COLOR, "white"
        elif day.month != self._month.month:
            background, foreground = self._background, OTHER_MONTH_COLOR
        else:
            background, foreground = self._background, self._foreground
        cell = tk.Label(
            self._days_frame,
            text=str(day.day),
            width=3,
            pady=2,
            cursor="hand2",
            background=background,
            foreground=foreground,
            relief="solid" if day == today else "flat",
            borderwidth=1,
        )
        cell.bind("<Button-1>", lambda _event: self._pick(day))
        if not selected:
            cell.bind("<Enter>", lambda _event: cell.configure(background=HOVER_DAY_COLOR))
            cell.bind("<Leave>", lambda _event: cell.configure(background=background))
        return cell


class CharacterDialog(tk.Toplevel):
    """Egy karakter adatainak szerkesztése."""

    def __init__(self, parent: tk.Misc, character: Character, realms: list[str] | None = None) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title("Karakter szerkesztése")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result: dict | None = None  # mentéskor a karakter új adatai
        self.name_var = tk.StringVar(value=character.name)
        self.realm_var = tk.StringVar(value=character.realm)
        self.race_var = tk.StringVar(value=character.race)
        self.class_var = tk.StringVar(value=character.char_class)
        self.spec_var = tk.StringVar(value=character.spec)
        score = character.raiderio_score
        self.raiderio_var = tk.StringVar(value="" if score is None else format_raiderio_score(score))
        item_level = character.item_level
        self.item_level_var = tk.StringVar(value="" if item_level is None else format_item_level(item_level))
        self.level_var = tk.StringVar(value=format_level(character.level))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        item_level_entry = ttk.Entry(body, textvariable=self.item_level_var, width=10)
        score_entry = ttk.Entry(body, textvariable=self.raiderio_var, width=10)
        level_box = NumberSpinbox(body, self.level_var)
        rows = (
            ("Név:", ttk.Entry(body, textvariable=self.name_var, width=26)),
            ("Realm:", ttk.Combobox(body, textvariable=self.realm_var, values=realms or [], width=24)),
            ("Faj:", ttk.Combobox(body, textvariable=self.race_var, values=WOW_RACES, width=24)),
            ("Kaszt:", ttk.Combobox(body, textvariable=self.class_var, values=WOW_CLASSES, width=24)),
            ("Spec:", ttk.Combobox(body, textvariable=self.spec_var, width=24)),
            ("Itemlevel:", item_level_entry),
            ("Raider.io pontszám:", score_entry),
            ("Jelenlegi szint:", level_box),
        )
        short_fields = (item_level_entry, score_entry, level_box)
        for row, (text, widget) in enumerate(rows):
            ttk.Label(body, text=text).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            widget.grid(row=row, column=1, sticky="w" if widget in short_fields else "ew", pady=3)
        name_entry, spec_box = rows[0][1], rows[4][1]
        link_spec_to_class(self.class_var, self.spec_var, spec_box)
        buttons = ttk.Frame(body)
        buttons.grid(row=len(rows), column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Mentés", command=self.accept).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Mégse", command=self.destroy).pack(side="left")

        self.bind("<Return>", lambda _event: self.accept())
        self.bind("<Escape>", lambda _event: self.destroy())
        place_over(self, parent)
        show_modal(self)
        name_entry.focus_set()
        name_entry.select_range(0, "end")

    def accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Hiányzó név", "A karakter neve nem lehet üres.", parent=self)
            return
        try:
            level = parse_level(self.level_var.get())
        except ValueError as exc:
            messagebox.showwarning("Hibás szint", str(exc), parent=self)
            return
        try:
            item_level = parse_item_level(self.item_level_var.get())
        except ValueError as exc:
            messagebox.showwarning("Hibás itemlevel", str(exc), parent=self)
            return
        try:
            score = parse_raiderio_score(self.raiderio_var.get())
        except ValueError as exc:
            messagebox.showwarning("Hibás Raider.io pontszám", str(exc), parent=self)
            return
        self.result = {
            "name": name,
            "realm": self.realm_var.get().strip(),
            "race": self.race_var.get().strip(),
            "char_class": self.class_var.get().strip(),
            "spec": self.spec_var.get().strip(),
            "item_level": item_level,
            "raiderio_score": score,
            "level": level,
        }
        self.destroy()


class FactionDialog(tk.Toplevel):
    """Rákérdez, hogy Alliance vagy Horde karaktert ajánljon-e a program."""

    def __init__(self, parent: tk.Misc, default: str | None = None) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title("Combó ajánlása")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result: str | None = None  # a választott frakció (None: mégse)

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Ally vagy Horda?", style="Strong.TLabel").pack(anchor="w")
        ttk.Label(body, text="Melyik frakcióba ajánljak új karaktert?", style="Hint.TLabel").pack(
            anchor="w", pady=(2, 10)
        )
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.buttons = {}
        for faction in FACTIONS:
            button = ttk.Button(row, text=faction, command=lambda faction=faction: self.choose(faction))
            button.pack(side="left", padx=(0, 6))
            self.buttons[faction] = button
        ttk.Button(row, text="Mégse", command=self.destroy).pack(side="left", padx=(12, 0))

        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._invoke_focused())
        place_over(self, parent)
        show_modal(self)
        self.buttons.get(default, self.buttons[ALLIANCE]).focus_set()  # Enterrel a legutóbbi választás

    def _invoke_focused(self) -> None:
        widget = self.focus_get()
        if isinstance(widget, ttk.Button):
            widget.invoke()

    def choose(self, faction: str) -> None:
        self.result = faction
        self.destroy()


class CharacterListWindow(tk.Toplevel):
    """A karakterek listája és ütemterve külön ablakban."""

    TITLE = "Karakterek listája"
    # Az App ezekben az attribútumaiban tartja nyilván az ablakot és a nézet rendezését
    # (a rendezés az ablak bezárása után is megmarad).
    WINDOW_ATTRIBUTE = "list_window"
    SORT_ATTRIBUTE = "list_sort"
    EDITED_FIELD = LEVEL_FIELD  # ezt lehet módosítani az ablak alján a kijelölt karakternél
    HINT_TEXT = (
        "A sorrend számít: az első karakternek kell elsőként, az utolsónak utoljára elérnie a célszintet. "
        "A „Mai cél” az a szint, amelyet a mai nap végéig el kell érni (előretekintéskor a következő "
        "napé), a „Szinteltérés” pedig azt mutatja, hány szinttel jár a karakter a terv előtt (+) vagy "
        "mögött (−). A „Murlok.io” oszlop a karakter specjének pontszáma a Murlok.io Mythic+ rangsorában. "
        "A fejlécekre kattintva rendezheted a nézetet; a # oszlop az eredeti sorrend."
    )

    # azonosító, fejléc, igazítás, nyúlhat-e; a szélesség a tartalomhoz igazodik
    COLUMNS = (
        ("position", "#", "center", False),
        ("name", "Név", "w", False),
        ("realm", "Realm", "w", False),
        ("race", "Faj", "w", False),
        ("class", "Kaszt", "w", False),
        ("spec", "Spec", "w", False),
        ("level", "Szint", "center", False),
        ("item_level", "Itemlevel", "center", False),
        ("raiderio", "Raider.io", "center", False),
        ("murlok", "Murlok.io", "center", False),
        ("start", "Kezdés", "center", False),
        ("deadline", "Céldátum", "center", False),
        ("goal", "Mai cél", "center", False),
        ("deviation", "Szinteltérés", "center", False),
        ("days", "Hátra (nap)", "center", False),
        ("pace", "Napi tempó", "center", False),
        ("status", "Állapot", "w", True),
    )

    def __init__(self, app: App) -> None:
        super().__init__(app.root)
        self.app = app
        self.title(f"{self.TITLE} – {APP_TITLE}")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.header_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.selected_var = tk.StringVar()
        self.value_var = tk.StringVar()  # a kijelölt karakter módosítható száma (lásd EDITED_FIELD)
        self.order_hint_var = tk.StringVar()
        self.day_var = tk.StringVar()
        self.look_ahead_var = tk.BooleanVar(value=app.data.look_ahead)
        self.look_ahead_info_var = tk.StringVar()
        self._sized = False  # megkapta-e már az ablak a kezdeti méretét
        self._content_width = 0  # a tartalom legutóbb mért szélessége
        self._build()
        self.update_score_controls()
        self.bind("<Escape>", lambda _event: self.close())
        self.refresh()
        self.minsize(app.px(640), app.px(360))
        # Kezdetben akkora, amekkorát a tartalom kíván (legfeljebb a képernyő szélessége);
        # utána csak akkor nő, ha a tartalom szélesebb lesz, így nem ugrál.
        self.update_idletasks()
        width = min(self.winfo_reqwidth(), self.winfo_screenwidth() - app.px(40))
        self.geometry(f"{width}x{self.winfo_reqheight()}")
        self._sized = True

    def _build(self) -> None:
        px = self.app.px
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        header = ttk.Frame(body)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.header_var, style="Strong.TLabel").pack(side="left", anchor="w")
        self.score_button = ttk.Button(
            header, text="Frissítés a Murlok.io-ról", command=lambda: self.app.refresh_spec_scores(force=True)
        )
        self.score_button.pack(side="right")
        ttk.Label(header, textvariable=self.app.score_status_var, style="Hint.TLabel").pack(
            side="right", padx=(0, 8)
        )
        ttk.Label(
            body,
            text=self.HINT_TEXT,
            style="Hint.TLabel",
            wraplength=px(860),
            justify="left",
        ).pack(anchor="w", pady=(2, 6))

        options = ttk.Frame(body)
        options.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(
            options,
            text="Teljesített nap után a következő nap céljait mutassa",
            variable=self.look_ahead_var,
            command=self._toggle_look_ahead,
        ).pack(side="left")
        ttk.Label(options, textvariable=self.look_ahead_info_var, style="Good.TLabel").pack(side="left", padx=(12, 0))

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.table_frame = table
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table, columns=[column[0] for column in self.COLUMNS], show="headings", selectmode="browse", height=12
        )
        style = ttk.Style(self)
        self._cell_font = style_font(style, "Treeview", "TkDefaultFont")
        self._heading_font = style_font(style, "Treeview.Heading", "TkHeadingFont")
        for key, heading, anchor, stretch in self.COLUMNS:
            self.tree.heading(key, text=heading, anchor=anchor, command=lambda key=key: self.sort_by(key))
            minwidth = px(200) if stretch else px(30)
            self.tree.column(key, minwidth=minwidth, anchor=anchor, stretch=stretch)
        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(status.value, foreground=color)
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_selection())
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Delete>", lambda _event: self.delete_selected())
        for key, delta in (("<plus>", 1), ("<KP_Add>", 1), ("<minus>", -1), ("<KP_Subtract>", -1)):
            self.tree.bind(key, lambda _event, delta=delta: self.change_value(delta))

        selected = ttk.LabelFrame(body, text="Kijelölt karakter", padding=8)
        selected.pack(fill="x", pady=(10, 0))
        value_row = ttk.Frame(selected)
        value_row.pack(fill="x")
        field = self.EDITED_FIELD
        ttk.Label(value_row, textvariable=self.selected_var, style="Strong.TLabel", width=-30).pack(side="left")
        ttk.Label(value_row, text=field.label).pack(side="left", padx=(12, 4))
        self.value_spin = NumberSpinbox(value_row, self.value_var, on_step=self.apply_value, field=field)
        self.value_spin.pack(side="left")
        self.value_spin.bind("<Return>", lambda _event: self.apply_value())
        set_button = ttk.Button(value_row, text="Beállítás", command=self.apply_value)
        set_button.pack(side="left", padx=(6, 0))
        plus_button = ttk.Button(value_row, text=f"+1 {field.unit}", command=lambda: self.change_value(1))
        plus_button.pack(side="left", padx=(6, 0))

        action_row = ttk.Frame(selected)
        action_row.pack(fill="x", pady=(8, 0))
        up_button = ttk.Button(action_row, text="▲ Feljebb", command=lambda: self.move_selected(-1))
        down_button = ttk.Button(action_row, text="▼ Lejjebb", command=lambda: self.move_selected(1))
        self.murlok_order_button = ttk.Button(
            action_row, text="Murlok.io szerinti sorrend", command=self.order_by_murlok
        )
        edit_button = ttk.Button(action_row, text="Szerkesztés…", command=self.edit_selected)
        delete_button = ttk.Button(action_row, text="Törlés", command=self.delete_selected)
        for button in (up_button, down_button, self.murlok_order_button, edit_button, delete_button):
            button.pack(side="left", padx=(0, 6))
        ttk.Label(action_row, textvariable=self.order_hint_var, style="Hint.TLabel").pack(side="left", padx=(6, 0))
        self._selection_widgets = (self.value_spin, set_button, plus_button, edit_button, delete_button)
        self._order_widgets = (up_button, down_button)  # csak az eredeti sorrendben használhatók

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Bezárás", command=self.close).pack(side="right", anchor="n")
        texts = ttk.Frame(footer)
        texts.pack(side="left", fill="x", expand=True)
        summary = ttk.Label(texts, textvariable=self.summary_var, justify="left")
        summary.pack(anchor="w")
        self.day_label = ttk.Label(texts, textvariable=self.day_var, justify="left")
        self.day_label.pack(anchor="w", pady=(4, 0))
        # A sorok az ablak tényleges szélességénél törjenek.
        texts.bind(
            "<Configure>",
            lambda event: [label.configure(wraplength=max(event.width, px(300))) for label in (summary, self.day_label)],
        )

    def refresh(self, select: Character | None = None) -> None:
        """A táblázat újraszámolása és újrarajzolása."""
        data = self.app.data
        settings = data.settings
        today = date.today()
        # Előretekintéskor az első olyan nap céljai, amelyet még nem teljesített minden karakter.
        goal_day = lookahead_day(settings, data.characters, today) if data.look_ahead else today
        sort_key, descending = self.view_sort
        plans = build_plan(settings, data.characters, today, data.spec_scores, goal_day)
        plans = sort_plans(self._shown_plans(plans), sort_key, descending)
        keep = select.uid if select is not None else next(iter(self.tree.selection()), None)

        self.tree.delete(*self.tree.get_children())
        rows = []
        for plan in plans:
            values = self._row_values(plan)
            rows.append(values)
            self.tree.insert("", "end", iid=plan.character.uid, values=values, tags=self._row_tags(plan))
        headings = {"goal": goal_heading(goal_day, today)}
        for key, heading, *_ in self.COLUMNS:
            text = headings.get(key, heading)
            self.tree.heading(key, text=text + (SORT_ARROWS[descending] if key == sort_key else ""))
        shown = [column[0] for column in self.COLUMNS]
        if settings.mode == PARALLEL and "start" in shown:  # párhuzamos ütemezésnél mindenki ugyanakkor kezd
            shown.remove("start")
        self.tree.configure(displaycolumns=shown)
        self._fit_columns(rows, headings, shown)
        if keep is not None and self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.focus(keep)
            self.tree.see(keep)
        self._sync_selection()

        mode = "párhuzamos" if settings.mode == PARALLEL else "egymás utáni"
        self.header_var.set(
            f"Ma: {long_date(today)}   ·   Kezdőszint: {format_level(settings.start_level)}   ·   "
            f"Célszint: {format_level(settings.target_level)}   ·   Ütemezés: {mode}"
        )
        self.look_ahead_var.set(data.look_ahead)
        self.look_ahead_info_var.set(look_ahead_text(goal_day, today))
        self.summary_var.set(self._summary(plans, goal_day, today))
        progress = day_progress(settings, self.app.data.characters, today)
        self.day_var.set(progress.describe() if progress is not None else "")
        behind = progress is not None and not progress.finished and progress.today >= 1 and progress.days_ahead < 0
        self.day_label.configure(style="Late.TLabel" if behind else "Good.TLabel")

    def _fit_columns(self, rows: list[tuple], headings: dict[str, str], shown: list[str]) -> None:
        """Minden oszlop olyan széles, amennyit a fejléce és a leghosszabb cellája kíván."""
        arrow = self._heading_font.measure(SORT_ARROWS[False])  # a rendezés jele se lógjon ki
        padding = self.app.px(20)
        total = 0
        for index, (key, heading, *_) in enumerate(self.COLUMNS):
            title = self._heading_font.measure(headings.get(key, heading)) + arrow
            cells = max((self._cell_font.measure(str(row[index])) for row in rows), default=0)
            width = max(title, cells) + padding
            self.tree.column(key, width=width)
            if key in shown:
                total += width
        self._grow_to_fit(total)

    def _grow_to_fit(self, columns_width: int) -> None:
        """Ha a táblázat szélesebb lett, mint amennyi hely jut neki, az ablak is nő
        (legfeljebb a képernyő szélességéig).

        Csak a tartalom növekedésekor nő, így a kézzel kisebbre vett ablakot nem írja
        felül. (Látható táblázatnál a Tk nem jelzi az oszlopok miatti új méretigényt,
        ezért a szükséges szélességet az oszlopok összegéből számoljuk.)
        """
        grown = columns_width > self._content_width
        self._content_width = columns_width
        if not (self._sized and grown):
            return
        missing = columns_width + self.app.px(4) - self.tree.winfo_width()
        if missing > 0:
            limit = self.winfo_screenwidth() - self.app.px(40)
            self.geometry(f"{min(self.winfo_width() + missing, limit)}x{self.winfo_height()}")

    def _shown_plans(self, plans: list[CharacterPlan]) -> list[CharacterPlan]:
        """A listában megjelenő sorok (itt mind)."""
        return plans

    def _row_tags(self, plan: CharacterPlan) -> tuple[str, ...]:
        """A sor címkéi: a színe a szintezési állapotot jelzi."""
        return (plan.status.value,)

    @classmethod
    def _row_values(cls, plan: CharacterPlan) -> tuple:
        """Egy sor cellái a COLUMNS sorrendjében."""
        character = plan.character
        if plan.status is Status.DONE:
            days = "–"
        elif plan.status is Status.OVERDUE:
            days = "lejárt"
        else:
            days = str(plan.days_left)
        cells = {
            "position": plan.position,
            "name": character.name,
            "realm": character.realm or "–",
            "race": character.race or "–",
            "class": character.char_class or "–",
            "spec": character.spec or "–",
            "level": format_level(character.level),
            "item_level": "–" if character.item_level is None else format_item_level(character.item_level),
            "planned_item_level": (
                "–" if plan.planned_item_level is None else format_item_level(plan.planned_item_level)
            ),
            "item_level_deviation": (
                "–" if plan.item_level_deviation is None else format_deviation(plan.item_level_deviation)
            ),
            "raiderio": "–" if character.raiderio_score is None else format_raiderio_score(character.raiderio_score),
            "murlok": "–" if plan.spec_score is None else format_compact(plan.spec_score),
            "start": format_date(plan.start),
            "deadline": format_date(plan.deadline),
            "goal": "–" if plan.goal is None else format_level(plan.goal),
            "deviation": format_deviation(plan.deviation),
            "days": days,
            "pace": "–" if plan.pace is None else format_level(plan.pace),
            "status": plan.status_text,
        }
        return tuple(cells[key] for key, *_ in cls.COLUMNS)

    @staticmethod
    def _summary(plans: list[CharacterPlan], goal_day: date, today: date) -> str:
        if not plans:
            return "Még nincs karakter a listán. Új karaktert a főablakban adhatsz hozzá."
        counts = Counter(plan.status for plan in plans)
        parts = [f"Összesen {len(plans)} karakter", f"célszinten: {counts[Status.DONE]}"]
        behind = counts[Status.BEHIND] + counts[Status.OVERDUE]
        if behind:
            parts.append(f"lemaradásban: {behind}")
        due = sum(plan.levels_due for plan in plans)
        if goal_day != today:
            parts.append(f"teendő {goal_day_phrase(goal_day, today)} célig: {format_level(due)} szint")
        else:
            parts.append(f"mai teendő összesen: {format_level(due)} szint" if due else "mára nincs több teendő")
        return "   ·   ".join(parts)

    def _selected_character(self) -> Character | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return next((c for c in self.app.data.characters if c.uid == selection[0]), None)

    def _sync_selection(self) -> None:
        """A „Kijelölt karakter” rész frissítése a kijelölés alapján."""
        character = self._selected_character()
        for widget in self._selection_widgets:
            widget.state(["!disabled" if character else "disabled"])
        in_plan_order = self.view_sort == PLAN_ORDER
        for widget in self._order_widgets:
            widget.state(["!disabled" if character and in_plan_order else "disabled"])
        self.order_hint_var.set("" if in_plan_order else "Az átrendezéshez rendezd a listát a # oszlop szerint.")
        if character is None:
            self.selected_var.set("– nincs kijelölve –")
            self.value_var.set("")
        else:
            self.selected_var.set(describe_character(character))
            self._show_value(character)

    def sort_by(self, key: str) -> None:
        """Rendezés oszlop szerint; ugyanarra az oszlopra kattintva megfordul az irány."""
        current, descending = self.view_sort
        self.view_sort = (key, not descending if key == current else False)
        self.refresh()

    def _on_double_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_region(event.x, event.y) == "cell":
            self.tree.selection_set(row)
            self._sync_selection()
            self.edit_selected()

    def _show_value(self, character: Character) -> None:
        value = getattr(character, self.EDITED_FIELD.attribute)
        self.value_var.set("" if value is None else self.EDITED_FIELD.format(value))

    def apply_value(self) -> None:
        """A kijelölt karakter beírt szintjének (a Gear ablakban itemlevelének) beállítása."""
        character = self._selected_character()
        if character is None:
            return
        field = self.EDITED_FIELD
        try:
            value = field.parse(self.value_var.get())
        except ValueError as exc:
            messagebox.showwarning(field.error_title, str(exc), parent=self)
            self._show_value(character)
            return
        self._set_value(character, value)

    def change_value(self, delta: int) -> None:
        """Léptetés egy egésszel; a szint a kezdő- és célszinten kívül is lehet."""
        character = self._selected_character()
        if character is None:
            return
        field = self.EDITED_FIELD
        value = getattr(character, field.attribute)
        if value is None:  # pl. még nincs megadva itemlevel
            self.bell()
            return
        self._set_value(character, min(max(value + delta, field.minimum), field.maximum))

    def _set_value(self, character: Character, value: Decimal | None) -> None:
        if value == getattr(character, self.EDITED_FIELD.attribute):
            self._show_value(character)
            return
        setattr(character, self.EDITED_FIELD.attribute, value)
        self.app.data_changed(select=character)

    def order_by_murlok(self) -> None:
        """Az összes karakter szintezési sorrendje a Murlok.io-pontszámok alapján (lásd murlok_order)."""
        title = "Murlok.io szerinti sorrend"
        data = self.app.data
        if not data.spec_scores.scores:
            message = (
                "Még nincsenek Murlok.io-pontszámok. Kérd le őket a „Frissítés a Murlok.io-ról” "
                "gombbal, majd próbáld újra."
            )
            messagebox.showinfo(title, message, parent=self)
            return
        new_order = murlok_order(data.characters, data.spec_scores)
        if new_order == data.characters:
            messagebox.showinfo(title, "A karakterek sorrendje már most is a Murlok.io szerinti.", parent=self)
            return
        question = (
            "Átrendezed az összes karaktert a Murlok.io-pontszámok alapján?\n\n"
            "Körönként minden class/specből egy karakter kerül sorra (mindig a legmagasabb szintű), "
            "a körön belül a magasabb pontszámú spec van elöl. A céldátumok az új sorrendhez igazodnak."
        )
        unranked = sum(1 for character in data.characters if data.spec_scores.score_for(character) is None)
        if unranked:
            single = unranked == 1
            question += (
                f"\n\n{unranked} karakternek nincs Murlok.io-pontszáma (nincs megadva vagy ismeretlen a "
                f"class/spec), {'ő' if single else 'ők'} a lista végére {'kerül' if single else 'kerülnek'}."
            )
        if not messagebox.askyesno(title, question, parent=self):
            return
        data.characters[:] = new_order
        self.view_sort = PLAN_ORDER  # hogy az új sorrend látszódjon
        self.app.data_changed(select=self._selected_character())

    def move_selected(self, offset: int) -> None:
        character = self._selected_character()
        if character is None or self.view_sort != PLAN_ORDER:
            return
        characters = self.app.data.characters
        index = characters.index(character)
        target = index + offset
        if 0 <= target < len(characters):
            characters[index], characters[target] = characters[target], characters[index]
            self.app.data_changed(select=character)

    def edit_selected(self) -> None:
        character = self._selected_character()
        if character is None:
            return
        dialog = CharacterDialog(self, character, self.app.known_realms())
        self.wait_window(dialog)
        if dialog.result is not None:
            for field_name, value in dialog.result.items():
                setattr(character, field_name, value)
            self.app.data_changed(select=character)

    def delete_selected(self) -> None:
        character = self._selected_character()
        if character is None:
            return
        question = f"Biztosan törlöd {article(character.name)} „{character.name}” nevű karaktert a listáról?"
        if not messagebox.askyesno("Karakter törlése", question, parent=self):
            return
        # A törölt sor helyére a nézetben következő (vagy utolsóként az előző) sor kerül kijelölésre.
        rows = self.tree.get_children()
        index = rows.index(character.uid)
        remaining = [uid for uid in rows if uid != character.uid]
        neighbour_uid = remaining[min(index, len(remaining) - 1)] if remaining else None
        self.app.data.characters.remove(character)
        neighbour = next((c for c in self.app.data.characters if c.uid == neighbour_uid), None)
        self.app.data_changed(select=neighbour)

    def _toggle_look_ahead(self) -> None:
        self.app.data.look_ahead = self.look_ahead_var.get()
        self.app.data_changed()

    def update_score_controls(self) -> None:
        """A Murlok.io frissítés gomb csak akkor használható, ha éppen nem fut lekérés."""
        self.score_button.state(["!disabled" if self.app.can_fetch_scores() else "disabled"])

    @property
    def view_sort(self) -> tuple[str, bool]:
        """A nézet rendezése: (oszlop, csökkenő-e)."""
        return getattr(self.app, self.SORT_ATTRIBUTE)

    @view_sort.setter
    def view_sort(self, value: tuple[str, bool]) -> None:
        setattr(self.app, self.SORT_ATTRIBUTE, value)

    def close(self) -> None:
        setattr(self.app, self.WINDOW_ATTRIBUTE, None)
        self.destroy()


GEAR_COLUMNS = (
    ("planned_item_level", "Tervezett itemlevel", "center", False),
    ("item_level_deviation", "Itemlevel-eltérés", "center", False),
)
# A szintezéssel kapcsolatos oszlopok a Gear ablakban nem látszanak.
GEAR_HIDDEN_COLUMNS = ("level", "start", "deadline", "goal", "deviation", "days", "pace", "status")


def item_level_step_text(step: Decimal) -> str:
    """X kiírása két tizedesjeggyel (pl. „2,35”, „kb. 3,42”, „−2,50”)."""
    rounded = step.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format_deviation(rounded).lstrip("+")
    return text if rounded == step else f"kb. {text}"


class GearWindow(CharacterListWindow):
    """A karakterlista másolata a felszerelés (gear) követéséhez, saját ablakban és saját
    rendezéssel; a tervezett itemlevelt és az attól való eltérést is mutatja."""

    TITLE = "Gear"
    WINDOW_ATTRIBUTE = "gear_window"
    SORT_ATTRIBUTE = "gear_sort"
    EDITED_FIELD = ITEM_LEVEL_FIELD
    # A karakterlista oszlopai a szinttel kapcsolatosak nélkül; az „Itemlevel” után a
    # tervezett itemlevel és az eltérés.
    COLUMNS = tuple(
        column
        for base in CharacterListWindow.COLUMNS
        if base[0] not in GEAR_HIDDEN_COLUMNS
        for column in ((base, *GEAR_COLUMNS) if base[0] == "item_level" else (base,))
    )
    HINT_TEXT = (
        "A „Tervezett itemlevel” a Murlok.io szerinti sorrend (mint a „Murlok.io szerinti sorrend” gombnál) "
        "első karakterénél a célitemlevel − X, minden következőnél újabb X-szel kevesebb. Az "
        "„Itemlevel-eltérés” a valós és a tervezett itemlevel különbsége (+: a terv felett, −: alatta); a "
        "táblázat alapból eszerint van rendezve. X-et a program úgy állítja be, hogy a 2. sorban 0 legyen az "
        "eltérés, így az 1. sorban negatív. Aki elérte a célitemlevelt, lekerül a listáról, és a többiekkel "
        "számol tovább. A fejlécekre kattintva más oszlop szerint is rendezheted."
    )

    def _build(self) -> None:
        super()._build()
        self.gear_info_var = tk.StringVar()
        self.gear_info_label = ttk.Label(self.table_frame.master, textvariable=self.gear_info_var)
        self.gear_info_label.pack(anchor="w", pady=(0, 6), before=self.table_frame)

    def _row_tags(self, plan: CharacterPlan) -> tuple[str, ...]:
        return ()  # az „Állapot” oszlop nélkül a szintezési állapot színe sem kell

    def _shown_plans(self, plans: list[CharacterPlan]) -> list[CharacterPlan]:
        """A célitemlevelt már elért karakterek lekerülnek a listáról."""
        target = self.app.data.settings.target_item_level
        return [plan for plan in plans if not reached_target_item_level(plan.character, target)]

    def _summary(self, plans: list[CharacterPlan], goal_day: date, today: date) -> str:
        if not plans and self.app.data.characters:
            return "Minden karakter elérte a célitemlevelt, ezért egyik sem látszik a listán."
        return super()._summary(plans, goal_day, today)

    def refresh(self, select: Character | None = None) -> None:
        super().refresh(select)
        data = self.app.data
        target = data.settings.target_item_level
        item_levels = plan_item_levels(data.characters, data.spec_scores, target)
        reached = len(item_levels.reached)
        reached_text = f"   ·   Célitemlevelen (nem látszik a listán): {reached} karakter" if reached else ""
        if item_levels.step is None:
            self.gear_info_var.set(f"Tervezett itemlevel: {item_levels.problem}{reached_text}")
            self.gear_info_label.configure(style="Late.TLabel")
        else:
            self.gear_info_var.set(
                f"Célitemlevel: {format_item_level(target)}   ·   X = {item_level_step_text(item_levels.step)} "
                f"(ennyivel csökken a tervezett itemlevel karakterenként){reached_text}"
            )
            self.gear_info_label.configure(style="Strong.TLabel")


class App:
    """A főablak: beállítások, új karakter felvétele, a karakterlista és a Gear ablak megnyitása."""

    def __init__(self, root: tk.Tk, data_path: Path, fetch_scores=None) -> None:
        self.root = root
        self.data_path = Path(data_path)
        # A Murlok.io-pontszámokat lekérő függvény (None: nincs lekérés, pl. a tesztekben).
        self._fetch_scores = fetch_scores
        self._score_fetch_running = False
        self._score_error: str | None = None
        self.score_status_var = tk.StringVar()
        self.list_window: CharacterListWindow | None = None
        self.gear_window: GearWindow | None = None
        self.list_sort = PLAN_ORDER  # a lista nézetének rendezése (oszlop, csökkenő-e)
        self.gear_sort = GEAR_ORDER  # a Gear ablak rendezése
        self._scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self._today = date.today()
        self._save_error_shown = False
        self._feedback_job: str | None = None
        self._last_faction: str | None = None  # a combóajánlásnál legutóbb választott frakció

        root.title(APP_TITLE)
        self._setup_styles()
        self.data = self._load_data()

        settings = self.data.settings
        self.start_var = tk.StringVar(value=format_date(settings.start_date))
        self.first_var = tk.StringVar(value=format_date(settings.first_target_date))
        self.last_var = tk.StringVar(value=format_date(settings.last_target_date))
        self.start_level_var = tk.StringVar(value=format_level(settings.start_level))
        self.target_level_var = tk.StringVar(value=format_level(settings.target_level))
        target_item_level = settings.target_item_level
        self.target_item_level_var = tk.StringVar(
            value="" if target_item_level is None else format_item_level(target_item_level)
        )
        self.mode_var = tk.StringVar(value=settings.mode)
        self.settings_message = tk.StringVar()
        self.name_var = tk.StringVar()
        self.realm_var = tk.StringVar()
        self.race_var = tk.StringVar()
        self.class_var = tk.StringVar()
        self.spec_var = tk.StringVar()
        self.item_level_var = tk.StringVar()
        self.raiderio_var = tk.StringVar()
        self.new_level_var = tk.StringVar()
        self.feedback_var = tk.StringVar()
        self.summary_var = tk.StringVar()

        self._build()
        settings_vars = (
            self.start_var,
            self.first_var,
            self.last_var,
            self.start_level_var,
            self.target_level_var,
            self.target_item_level_var,
            self.mode_var,
        )
        for variable in settings_vars:
            variable.trace_add("write", self._on_settings_edited)
        self._show_settings_problems(settings.errors())
        self._update_score_status()  # a listaablakok már a szöveggel együtt méretezik magukat
        self.refresh()
        self.name_entry.focus_set()
        root.after(60_000, self._watch_date)

    def px(self, value: int) -> int:
        """Képpontméret a kijelző felbontásához (DPI) igazítva."""
        return round(value * self._scale)

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        if style.theme_use() == "default" and "clam" in style.theme_names():
            style.theme_use("clam")  # Linuxon szebb, mint az alapértelmezett téma
        base = tkfont.nametofont("TkDefaultFont")
        strong = base.copy()
        strong.configure(weight="bold")
        title = base.copy()
        title.configure(weight="bold", size=round((base.cget("size") or 10) * 1.4))
        self._fonts = (strong, title)  # hivatkozás kell, különben a betűtípus törlődik
        style.configure("Title.TLabel", font=title)
        style.configure("Strong.TLabel", font=strong)
        style.configure("Hint.TLabel", foreground=HINT_COLOR)
        style.configure("Ok.TLabel", foreground=OK_COLOR)
        style.configure("Error.TLabel", foreground=ERROR_COLOR)
        style.configure("Compact.TButton", padding=(2, 0))
        style.configure("Estimate.TButton", justify="center")
        style.configure("Good.TLabel", font=strong, foreground=OK_COLOR)
        style.configure("Late.TLabel", font=strong, foreground=BEHIND_COLOR)
        style.configure("Treeview", rowheight=round(base.metrics("linespace") * 1.5))

        # Egyes Tk-verziókban (8.6.9) e nélkül nem látszanak a sorok színei.
        def without_default(option: str) -> list:
            return [
                entry
                for entry in style.map("Treeview", query_opt=option)
                if entry[:2] != ("!disabled", "!selected")
            ]

        style.map("Treeview", foreground=without_default("foreground"), background=without_default("background"))

    def _load_data(self) -> LevelingData:
        try:
            return load_data(self.data_path)
        except FileNotFoundError:
            return LevelingData(Settings.default())
        except (OSError, ValueError) as exc:
            message = f"Az adatfájl nem olvasható be:\n{self.data_path}\n\n{exc}"
            backup = self.data_path.with_name(
                f"{self.data_path.stem}.hibas-{datetime.now():%Y%m%d-%H%M%S}{self.data_path.suffix}"
            )
            try:
                self.data_path.replace(backup)
            except OSError:
                pass
            else:
                message += f"\n\nA hibás fájlt átneveztem, így megmaradt: {backup.name}"
            messagebox.showwarning(APP_TITLE, message + "\n\nA program alapbeállításokkal indul.")
            return LevelingData(Settings.default())

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure((0, 1), weight=1)

        ttk.Label(body, text="World of Warcraft – szintezés tervező", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(body, text=INTRO_TEXT, style="Hint.TLabel", wraplength=self.px(940), justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 12)
        )

        def field_label(frame: ttk.Frame, text: str, row: int, sticky: str = "w") -> None:
            ttk.Label(frame, text=text).grid(row=row, column=0, sticky=sticky, padx=(0, 12), pady=3)

        settings = ttk.LabelFrame(body, text="Beállítások", padding=10)
        settings.grid(row=2, column=0, sticky="nsew")
        date_rows = (
            ("Szintezés kezdete:", self.start_var),
            ("Első karakter célszinten:", self.first_var),
            ("Utolsó karakter célszinten:", self.last_var),
        )
        for row, (text, variable) in enumerate(date_rows):
            field_label(settings, text, row)
            DateField(settings, variable).grid(row=row, column=1, sticky="w", pady=3)
        self.estimate_button = ttk.Button(
            settings,
            text="Kiszámolás a\nmostani szintekből",
            style="Estimate.TButton",
            command=self.estimate_target_dates,
        )
        self.estimate_button.grid(row=1, column=2, rowspan=2, sticky="nsw", padx=(10, 0), pady=3)
        for row, (text, variable) in enumerate(
            (("Kezdőszint:", self.start_level_var), ("Célszint:", self.target_level_var)), start=3
        ):
            field_label(settings, text, row)
            NumberSpinbox(settings, variable).grid(row=row, column=1, sticky="w", pady=3)
        field_label(settings, "Célitemlevel:", 5)
        item_level_cell = ttk.Frame(settings)
        item_level_cell.grid(row=5, column=1, columnspan=2, sticky="w", pady=3)
        ttk.Entry(item_level_cell, textvariable=self.target_item_level_var, width=10).pack(side="left")
        ttk.Label(item_level_cell, text="nem kötelező (pl. 326,55)", style="Hint.TLabel").pack(
            side="left", padx=(8, 0)
        )
        field_label(settings, "Ütemezés:", 6, sticky="nw")
        modes = ttk.Frame(settings)
        modes.grid(row=6, column=1, columnspan=2, sticky="w", pady=3)
        ttk.Radiobutton(
            modes,
            text="Párhuzamosan – mindegyik a kezdő naptól szintez",
            value=PARALLEL,
            variable=self.mode_var,
        ).pack(anchor="w")
        ttk.Radiobutton(
            modes,
            text="Egymás után – mindegyik az előző céldátuma után kezd",
            value=SEQUENTIAL,
            variable=self.mode_var,
        ).pack(anchor="w")
        self.settings_message_label = ttk.Label(
            settings, textvariable=self.settings_message, wraplength=self.px(520), justify="left"
        )
        self.settings_message_label.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))

        new = ttk.LabelFrame(body, text="Új karakter hozzáadása", padding=10)
        new.grid(row=2, column=1, sticky="nsew", padx=(12, 0))
        ttk.Label(new, text="Csak a név kötelező.", style="Hint.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 3)
        )
        self.name_entry = ttk.Entry(new, textvariable=self.name_var, width=26)
        self.realm_box = ttk.Combobox(new, textvariable=self.realm_var, width=24)
        race_box = ttk.Combobox(new, textvariable=self.race_var, values=WOW_RACES, width=24)
        class_box = ttk.Combobox(new, textvariable=self.class_var, values=WOW_CLASSES, width=24)
        self.spec_box = ttk.Combobox(new, textvariable=self.spec_var, width=24)
        link_spec_to_class(self.class_var, self.spec_var, self.spec_box)
        level_cell = ttk.Frame(new)
        level_box = NumberSpinbox(
            level_cell, self.new_level_var, empty_value=lambda: self.data.settings.start_level
        )
        level_box.pack(side="left")
        ttk.Label(level_cell, text="üresen hagyva: a kezdőszint", style="Hint.TLabel").pack(
            side="left", padx=(8, 0)
        )
        item_level_entry = ttk.Entry(new, textvariable=self.item_level_var, width=10)
        raiderio_entry = ttk.Entry(new, textvariable=self.raiderio_var, width=10)
        fields = (
            ("Név:", self.name_entry),
            ("Realm:", self.realm_box),
            ("Faj:", race_box),
            ("Kaszt:", class_box),
            ("Spec:", self.spec_box),
            ("Itemlevel:", item_level_entry),
            ("Raider.io pontszám:", raiderio_entry),
            ("Jelenlegi szint:", level_cell),
        )
        for row, (text, widget) in enumerate(fields, start=1):
            field_label(new, text, row)
            widget.grid(row=row, column=1, sticky="w", pady=3)
        inputs = (
            self.name_entry,
            self.realm_box,
            race_box,
            class_box,
            self.spec_box,
            item_level_entry,
            raiderio_entry,
            level_box,
        )
        for widget in inputs:
            widget.bind("<Return>", self.add_character)
        buttons = ttk.Frame(new)
        buttons.grid(row=len(fields) + 1, column=1, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text="Hozzáadás", command=self.add_character).pack(side="left")
        ttk.Button(buttons, text="Combó ajánlása…", command=self.show_combo_recommendation).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(new, textvariable=self.feedback_var, style="Ok.TLabel", wraplength=self.px(400)).grid(
            row=len(fields) + 2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        footer = ttk.Frame(body)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(footer, textvariable=self.summary_var, justify="left").pack(side="left", anchor="w")
        ttk.Button(footer, text="Gear", command=self.open_gear).pack(side="right", anchor="n")
        ttk.Button(footer, text="Karakterlista", command=self.open_list).pack(
            side="right", anchor="n", padx=(0, 6)
        )

    def _read_settings_fields(self) -> tuple[dict, dict[str, str]]:
        """A beállítások mezőiből beolvasott értékek és a hibák, a Settings mezőnevei szerint."""
        values = {}
        problems = {}
        fields = (
            ("start_date", "Szintezés kezdete", self.start_var, parse_date),
            ("first_target_date", "Első karakter céldátuma", self.first_var, parse_date),
            ("last_target_date", "Utolsó karakter céldátuma", self.last_var, parse_date),
            ("start_level", "Kezdőszint", self.start_level_var, parse_level),
            ("target_level", "Célszint", self.target_level_var, parse_level),
            ("target_item_level", "Célitemlevel", self.target_item_level_var, parse_item_level),
        )
        for key, label, variable, parse in fields:
            try:
                values[key] = parse(variable.get())
            except ValueError as exc:
                problems[key] = f"{label}: {exc}"
        return values, problems

    def _on_settings_edited(self, *_args) -> None:
        """Minden módosítás után ellenőrzi a beállításokat; ha helyesek, el is menti őket."""
        values, problems = self._read_settings_fields()
        if problems:
            self._show_settings_problems(list(problems.values()))
            return
        settings = Settings(mode=self.mode_var.get(), **values)
        problems = settings.errors()
        self._show_settings_problems(problems)
        if not problems and settings != self.data.settings:
            self.data.settings = settings
            self.data_changed()

    def _show_settings_problems(self, problems: list[str]) -> None:
        if problems:
            self.settings_message.set("\n".join(f"⚠ {problem}" for problem in problems))
            self.settings_message_label.configure(style="Error.TLabel")
        else:
            self.settings_message.set("✔ A beállítások rendben vannak, a változások automatikusan mentődnek.")
            self.settings_message_label.configure(style="Ok.TLabel")

    def estimate_target_dates(self) -> None:
        """Az első és az utolsó céldátum kiszámolása a karakterek mostani szintjéből.

        A mostani szinteket a tegnapi nap végéig elértnek tekinti (lásd
        leveling.estimate_target_dates); az új dátumok beállítása előtt rákérdez.
        """
        title = "Céldátumok kiszámolása"
        values, problems = self._read_settings_fields()
        # A két céldátum mezőjét a számolás úgyis felülírja, így azok hibája nem akadály.
        blocking = [text for key, text in problems.items() if key not in ("first_target_date", "last_target_date")]
        if blocking:
            message = "Előbb javítsd ki a beállításokat:\n\n" + "\n".join(blocking)
            messagebox.showinfo(title, message, parent=self.root)
            return
        current = self.data.settings
        settings = Settings(
            start_date=values["start_date"],
            first_target_date=values.get("first_target_date", current.first_target_date),
            last_target_date=values.get("last_target_date", current.last_target_date),
            start_level=values["start_level"],
            target_level=values["target_level"],
            mode=self.mode_var.get(),
        )
        try:
            estimate = estimate_target_dates(settings, self.data.characters, date.today())
        except ValueError as exc:
            messagebox.showinfo(title, str(exc), parent=self.root)
            return
        new_first = format_date(estimate.first_target_date)
        new_last = format_date(estimate.last_target_date)
        old = (values.get("first_target_date"), values.get("last_target_date"))
        if old == (estimate.first_target_date, estimate.last_target_date):
            message = f"A céldátumok már most is ezek: {new_first} és {new_last}."
            messagebox.showinfo(title, message, parent=self.root)
            return

        def change(old_date: date | None, variable: tk.StringVar, new: str) -> str:
            if old_date is not None and format_date(old_date) == new:
                return f"{new} (nem változik)"
            return f"{variable.get().strip() or '–'} → {new}"

        question = (
            f"Első karakter célszinten: {change(old[0], self.first_var, new_first)}\n"
            f"Utolsó karakter célszinten: {change(old[1], self.last_var, new_last)}\n\n"
            "Beállítod az új céldátumokat?"
        )
        # A magyarázat kisebb betűvel jelenik meg (Windowson a kérdés alatt, ugyanabban a szövegben).
        detail = (
            f"A számolás a mostani szinteket tegnap estig elértnek tekinti: a szintezés eddigi {estimate.days} "
            "napjának tempójából indul ki, a mai nap még hátravan.\n\n"
            f"Első céldátum: {estimate.first_reason}\n\n"
            f"Utolsó céldátum: {estimate.last_reason}"
        )
        if messagebox.askyesno(title, question, detail=detail, parent=self.root):
            self.first_var.set(new_first)  # a mezők figyelése ellenőriz, ment és frissít
            self.last_var.set(new_last)

    def add_character(self, *_args) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Hiányzó név", "Add meg az új karakter nevét!", parent=self.root)
            self.name_entry.focus_set()
            return
        level_text = self.new_level_var.get()
        try:
            level = parse_level(level_text) if level_text.strip() else self.data.settings.start_level
        except ValueError as exc:
            messagebox.showwarning("Hibás szint", str(exc), parent=self.root)
            return
        try:
            item_level = parse_item_level(self.item_level_var.get())
        except ValueError as exc:
            messagebox.showwarning("Hibás itemlevel", str(exc), parent=self.root)
            return
        try:
            score = parse_raiderio_score(self.raiderio_var.get())
        except ValueError as exc:
            messagebox.showwarning("Hibás Raider.io pontszám", str(exc), parent=self.root)
            return
        if any(character.name.casefold() == name.casefold() for character in self.data.characters):
            question = f"Már van „{name}” nevű karakter a listán.\nMégis hozzáadod?"
            if not messagebox.askyesno("Létező név", question, parent=self.root):
                return
        character = Character(
            name=name,
            realm=self.realm_var.get().strip(),
            race=self.race_var.get().strip(),
            char_class=self.class_var.get().strip(),
            spec=self.spec_var.get().strip(),
            level=level,
            item_level=item_level,
            raiderio_score=score,
        )
        self.data.characters.append(character)
        self.data_changed(select=character)
        for variable in (
            self.name_var,
            self.realm_var,
            self.race_var,
            self.class_var,
            self.spec_var,
            self.item_level_var,
            self.raiderio_var,
        ):
            variable.set("")
        self.new_level_var.set("")
        self.name_entry.focus_set()
        position = len(self.data.characters)
        self._show_feedback(f"✔ {name} felkerült a lista {position}. helyére (szint: {format_level(level)}).")

    def _ask_faction(self) -> str | None:
        """Ally vagy Horda? (None, ha a kérdést bezárták.)"""
        dialog = FactionDialog(self.root, self._last_faction)
        self.root.wait_window(dialog)
        return dialog.result

    def show_combo_recommendation(self, faction: str | None = None) -> None:
        """Új karakter ajánlása: a választott frakcióban az a class/spec/faj combó, amelyből a
        legkevesebb van (lásd recommend.recommend_combo). Kérésre kitölti vele az új karakter mezőit."""
        faction = faction or self._ask_faction()
        if faction is None:
            return
        self._last_faction = faction
        recommendation = recommend_combo(self.data.characters, self.data.spec_scores, faction)
        combo = recommendation.best
        question = f"Ajánlott {faction} karakter:\n{combo.name}\n\nKitöltsem vele az új karakter mezőit?"
        if not messagebox.askyesno("Combó ajánlása", question, detail=recommendation.describe(), parent=self.root):
            return
        self.class_var.set(combo.char_class)  # előbb a kaszt, mert a kasztváltás törölheti a specet
        self.spec_var.set(combo.spec)
        self.race_var.set(combo.race)
        self.name_entry.focus_set()
        self._show_feedback(f"✔ Kitöltve: {combo.name}. Írd be a nevét, majd kattints a „Hozzáadás” gombra.")

    def _show_feedback(self, text: str) -> None:
        self.feedback_var.set(text)
        if self._feedback_job is not None:
            self.root.after_cancel(self._feedback_job)
        self._feedback_job = self.root.after(6000, lambda: self.feedback_var.set(""))

    def open_list(self) -> None:
        self._open_window(CharacterListWindow)

    def open_gear(self) -> None:
        self._open_window(GearWindow)

    def _open_window(self, window_class: type[CharacterListWindow]) -> None:
        """Megnyitja a listaablakot; ha már nyitva van, csak előtérbe hozza."""
        window = getattr(self, window_class.WINDOW_ATTRIBUTE)
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            return
        setattr(self, window_class.WINDOW_ATTRIBUTE, window_class(self))
        self._update_score_status()
        self.refresh_spec_scores()  # ha a tárolt adat már régebbi 8 óránál

    def open_windows(self) -> list[CharacterListWindow]:
        """A nyitott listaablakok (karakterlista, Gear)."""
        return [window for window in (self.list_window, self.gear_window) if window is not None]

    def can_fetch_scores(self) -> bool:
        return self._fetch_scores is not None and not self._score_fetch_running

    def refresh_spec_scores(self, force: bool = False) -> None:
        """A specenkénti pontszámok lekérése a Murlok.io-ról a háttérben; közben a program használható."""
        if not self.can_fetch_scores() or not (force or self.data.spec_scores.is_stale()):
            return
        fetch = self._fetch_scores
        results: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                results.put((True, fetch()))
            except murlok.MurlokError as exc:
                results.put((False, str(exc)))
            except Exception as exc:  # váratlan hiba se akassza meg a programot
                results.put((False, f"váratlan hiba: {exc!r}"))

        self._score_fetch_running = True
        self._score_error = None
        self._update_score_status()
        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._check_score_fetch, results)

    def _check_score_fetch(self, results: queue.Queue) -> None:
        try:
            succeeded, value = results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._check_score_fetch, results)
            return
        self._score_fetch_running = False
        if succeeded:
            self.data.spec_scores = SpecScores(scores=value, fetched_at=datetime.now())
            self.data_changed()
        else:
            self._score_error = value
        self._update_score_status()

    def _update_score_status(self) -> None:
        fetched_at = self.data.spec_scores.fetched_at
        last = f"{fetched_at:%Y-%m-%d %H:%M}" if fetched_at else None
        if self._score_fetch_running:
            text = "Murlok.io: lekérés folyamatban…"
        elif self._score_error:
            text = f"Murlok.io: {self._score_error}" + (f" Utolsó sikeres lekérés: {last}." if last else "")
        elif last:
            text = f"Murlok.io-pontszámok: {last}"
        else:
            text = "Murlok.io-pontszámok: még nincsenek lekérve"
        self.score_status_var.set(text)
        for window in self.open_windows():
            window.update_score_controls()

    def data_changed(self, select: Character | None = None) -> None:
        """Módosítás után: mentés, majd minden ablak frissítése."""
        self.save()
        self.refresh(select=select)

    def save(self) -> None:
        try:
            save_data(self.data_path, self.data)
        except OSError as exc:
            if not self._save_error_shown:  # ne jelenjen meg minden billentyűleütésnél
                self._save_error_shown = True
                messagebox.showerror(
                    "Mentési hiba",
                    f"Nem sikerült menteni az adatokat ide:\n{self.data_path}\n\n{exc}",
                    parent=self.root,
                )
        else:
            self._save_error_shown = False

    def known_realms(self) -> list[str]:
        """A karaktereknél már megadott realmek, a realm mezők javaslataihoz."""
        return sorted({character.realm for character in self.data.characters if character.realm}, key=str.casefold)

    def refresh(self, select: Character | None = None) -> None:
        self.realm_box.configure(values=self.known_realms())
        characters = self.data.characters
        settings = self.data.settings
        if characters:
            done = sum(1 for character in characters if character.level >= settings.target_level)
            lines = [f"Karakterek száma: {len(characters)} (ebből célszinten: {done})"]
            span = (settings.last_target_date - settings.first_target_date).days
            if len(characters) > 1 and span > 0:
                every = span / (len(characters) - 1)
                every_text = str(int(every)) if every.is_integer() else f"kb. {format_number(every)}"
                lines.append(f"A karakterek {every_text} naponként érik el a célszintet.")
            self.summary_var.set("\n".join(lines))
        else:
            self.summary_var.set("Még nincs karakter a listán.")
        for window in self.open_windows():
            window.refresh(select=select)

    def _watch_date(self) -> None:
        """Éjfél után frissíti a napi célokat, ha a program végig nyitva marad."""
        if date.today() != self._today:
            self._today = date.today()
            self.refresh()
        self.root.after(60_000, self._watch_date)


def _enable_windows_dpi_awareness() -> None:
    """Windows alatt éles (nem elmosódott) megjelenítés nagy felbontású kijelzőn."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="World of Warcraft karakterek szintezésének tervezése.")
    parser.add_argument(
        "data_file",
        nargs="?",
        type=Path,
        default=default_data_path(),
        help=f"az adatfájl útvonala (alapértelmezés: {DATA_FILE_NAME} a program mappájában)",
    )
    args = parser.parse_args(argv)
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    App(root, args.data_file, fetch_scores=murlok.fetch_spec_scores)
    root.mainloop()


if __name__ == "__main__":
    main()
