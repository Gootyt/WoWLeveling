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
import sys
import tkinter as tk
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from leveling import (
    MAX_LEVEL_LIMIT,
    PARALLEL,
    SEQUENTIAL,
    START_LEVEL,
    Character,
    CharacterPlan,
    LevelingData,
    Settings,
    Status,
    build_plan,
    format_date,
    load_data,
    parse_date,
    parse_level,
    parse_max_level,
    save_data,
)

APP_TITLE = "WoW szintezés tervező"
DATA_FILE_NAME = "szintezes_adatok.json"

INTRO_TEXT = (
    "Minden karakter 1-es szintről indul. Add meg, mikor kezdődik a szintezés, mikorra érje el "
    "az első, illetve az utolsó karakter a maximum szintet, és mekkora legyen a maximum szint. "
    "A köztes karakterek céldátumait a program egyenletesen osztja el, és kiszámolja a napi célokat."
)

WOW_CLASSES = (
    "Death Knight",
    "Demon Hunter",
    "Druid",
    "Evoker",
    "Hunter",
    "Mage",
    "Monk",
    "Paladin",
    "Priest",
    "Rogue",
    "Shaman",
    "Warlock",
    "Warrior",
)

HU_MONTHS = (
    "január",
    "február",
    "március",
    "április",
    "május",
    "június",
    "július",
    "augusztus",
    "szeptember",
    "október",
    "november",
    "december",
)
HU_WEEKDAYS = ("hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap")
HU_WEEKDAY_ABBREVIATIONS = ("H", "K", "Sze", "Cs", "P", "Szo", "V")

OK_COLOR = "#1b7f3a"
ERROR_COLOR = "#c62828"
HINT_COLOR = "#5f6368"
SELECTED_DAY_COLOR = "#1f5fae"
HOVER_DAY_COLOR = "#cfe0f5"
OTHER_MONTH_COLOR = "#9aa0a6"

# Az „Ütemben” állapot az alapértelmezett betűszínnel jelenik meg.
STATUS_COLORS = {
    Status.DONE: OK_COLOR,
    Status.GOAL_MET: OK_COLOR,
    Status.AHEAD: "#1f5fae",
    Status.BEHIND: "#b35c00",
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
    """Egy karakter nevének, kasztjának és szintjének szerkesztése."""

    def __init__(self, parent: tk.Misc, character: Character, max_level: int) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title("Karakter szerkesztése")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result: tuple[str, str, int] | None = None
        self._max_level = max_level
        self.name_var = tk.StringVar(value=character.name)
        self.class_var = tk.StringVar(value=character.char_class)
        self.level_var = tk.StringVar(value=str(min(character.level, max_level)))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Név:").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=3)
        name_entry = ttk.Entry(body, textvariable=self.name_var, width=26)
        name_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Kaszt:").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=3)
        ttk.Combobox(body, textvariable=self.class_var, values=WOW_CLASSES, width=24).grid(
            row=1, column=1, sticky="ew", pady=3
        )
        ttk.Label(body, text="Jelenlegi szint:").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=3)
        ttk.Spinbox(body, from_=START_LEVEL, to=max_level, width=6, textvariable=self.level_var).grid(
            row=2, column=1, sticky="w", pady=3
        )
        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
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
            level = parse_level(self.level_var.get(), self._max_level)
        except ValueError as exc:
            messagebox.showwarning("Hibás szint", str(exc), parent=self)
            return
        self.result = (name, self.class_var.get().strip(), level)
        self.destroy()


class CharacterListWindow(tk.Toplevel):
    """A karakterek listája és ütemterve külön ablakban."""

    # azonosító, fejléc, alapszélesség (képpont), igazítás, nyúlhat-e
    COLUMNS = (
        ("position", "#", 36, "center", False),
        ("name", "Név", 130, "w", True),
        ("class", "Kaszt", 105, "w", True),
        ("level", "Szint", 50, "center", False),
        ("start", "Kezdés", 92, "center", False),
        ("deadline", "Céldátum", 92, "center", False),
        ("goal", "Mai cél", 62, "center", False),
        ("days", "Hátralévő napok", 100, "center", False),
        ("pace", "Tempó (szint/nap)", 110, "center", False),
        ("status", "Állapot", 290, "w", True),
    )

    def __init__(self, app: App) -> None:
        super().__init__(app.root)
        self.app = app
        self.title(f"Karakterek listája – {APP_TITLE}")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.header_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.selected_var = tk.StringVar()
        self.level_var = tk.StringVar()
        self._build()
        self.bind("<Escape>", lambda _event: self.close())
        self.refresh()
        self.minsize(app.px(640), app.px(360))

    def _build(self) -> None:
        px = self.app.px
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, textvariable=self.header_var, style="Strong.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text="A sorrend számít: az első karakternek kell elsőként, az utolsónak utoljára elérnie "
            "a maximum szintet. A „Mai cél” az a szint, amelyet a mai nap végéig el kell érni.",
            style="Hint.TLabel",
            wraplength=px(860),
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table, columns=[column[0] for column in self.COLUMNS], show="headings", selectmode="browse", height=12
        )
        heading_font = tkfont.nametofont("TkHeadingFont")
        for key, heading, width, anchor, stretch in self.COLUMNS:
            self.tree.heading(key, text=heading, anchor=anchor)
            width = max(px(width), heading_font.measure(heading) + px(16))
            self.tree.column(key, width=width, minwidth=px(30), anchor=anchor, stretch=stretch)
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
            self.tree.bind(key, lambda _event, delta=delta: self.change_level(delta))

        selected = ttk.LabelFrame(body, text="Kijelölt karakter", padding=8)
        selected.pack(fill="x", pady=(10, 0))
        level_row = ttk.Frame(selected)
        level_row.pack(fill="x")
        ttk.Label(level_row, textvariable=self.selected_var, style="Strong.TLabel", width=30).pack(side="left")
        ttk.Label(level_row, text="Jelenlegi szint:").pack(side="left", padx=(12, 4))
        self.level_spin = ttk.Spinbox(
            level_row,
            from_=START_LEVEL,
            to=MAX_LEVEL_LIMIT,
            width=5,
            textvariable=self.level_var,
            command=self.apply_level,
        )
        self.level_spin.pack(side="left")
        self.level_spin.bind("<Return>", lambda _event: self.apply_level())
        set_button = ttk.Button(level_row, text="Beállítás", command=self.apply_level)
        set_button.pack(side="left", padx=(6, 0))
        plus_button = ttk.Button(level_row, text="+1 szint", command=lambda: self.change_level(1))
        plus_button.pack(side="left", padx=(6, 0))

        action_row = ttk.Frame(selected)
        action_row.pack(fill="x", pady=(8, 0))
        up_button = ttk.Button(action_row, text="▲ Feljebb", command=lambda: self.move_selected(-1))
        down_button = ttk.Button(action_row, text="▼ Lejjebb", command=lambda: self.move_selected(1))
        edit_button = ttk.Button(action_row, text="Szerkesztés…", command=self.edit_selected)
        delete_button = ttk.Button(action_row, text="Törlés", command=self.delete_selected)
        for button in (up_button, down_button, edit_button, delete_button):
            button.pack(side="left", padx=(0, 6))
        self._selection_widgets = (
            self.level_spin,
            set_button,
            plus_button,
            up_button,
            down_button,
            edit_button,
            delete_button,
        )

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Bezárás", command=self.close).pack(side="right")
        ttk.Label(footer, textvariable=self.summary_var, wraplength=px(720), justify="left").pack(
            side="left", anchor="w"
        )

    def refresh(self, select: Character | None = None) -> None:
        """A táblázat újraszámolása és újrarajzolása."""
        settings = self.app.data.settings
        today = date.today()
        plans = build_plan(settings, self.app.data.characters, today)
        keep = select.uid if select is not None else next(iter(self.tree.selection()), None)

        self.tree.delete(*self.tree.get_children())
        for plan in plans:
            self.tree.insert(
                "", "end", iid=plan.character.uid, values=self._row_values(plan), tags=(plan.status.value,)
            )
        shown = [column[0] for column in self.COLUMNS]
        if settings.mode == PARALLEL:  # párhuzamos ütemezésnél mindenki ugyanakkor kezd
            shown.remove("start")
        self.tree.configure(displaycolumns=shown)
        if keep is not None and self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.focus(keep)
            self.tree.see(keep)
        self.level_spin.configure(to=settings.max_level)
        self._sync_selection()

        mode = "párhuzamos" if settings.mode == PARALLEL else "egymás utáni"
        self.header_var.set(
            f"Ma: {long_date(today)}   ·   Maximum szint: {settings.max_level}   ·   Ütemezés: {mode}"
        )
        self.summary_var.set(self._summary(plans))

    @staticmethod
    def _row_values(plan: CharacterPlan) -> tuple:
        character = plan.character
        if plan.status is Status.DONE:
            days = "–"
        elif plan.status is Status.OVERDUE:
            days = "lejárt"
        else:
            days = str(plan.days_left)
        return (
            plan.position,
            character.name,
            character.char_class or "–",
            character.level,
            format_date(plan.start),
            format_date(plan.deadline),
            "–" if plan.goal_today is None else plan.goal_today,
            days,
            "–" if plan.pace is None else format_number(plan.pace),
            plan.status_text,
        )

    @staticmethod
    def _summary(plans: list[CharacterPlan]) -> str:
        if not plans:
            return "Még nincs karakter a listán. Új karaktert a főablakban adhatsz hozzá."
        counts = Counter(plan.status for plan in plans)
        parts = [f"Összesen {len(plans)} karakter", f"max. szinten: {counts[Status.DONE]}"]
        behind = counts[Status.BEHIND] + counts[Status.OVERDUE]
        if behind:
            parts.append(f"lemaradásban: {behind}")
        due = sum(plan.levels_due_today for plan in plans)
        parts.append(f"mai teendő összesen: {due} szint" if due else "mára nincs több teendő")
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
        if character is None:
            self.selected_var.set("– nincs kijelölve –")
            self.level_var.set("")
        else:
            suffix = f" ({character.char_class})" if character.char_class else ""
            self.selected_var.set(character.name + suffix)
            self.level_var.set(str(character.level))

    def _on_double_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_region(event.x, event.y) == "cell":
            self.tree.selection_set(row)
            self._sync_selection()
            self.edit_selected()

    def apply_level(self) -> None:
        character = self._selected_character()
        if character is None:
            return
        try:
            level = parse_level(self.level_var.get(), self.app.data.settings.max_level)
        except ValueError as exc:
            messagebox.showwarning("Hibás szint", str(exc), parent=self)
            self.level_var.set(str(character.level))
            return
        self._set_level(character, level)

    def change_level(self, delta: int) -> None:
        character = self._selected_character()
        if character is not None:
            max_level = self.app.data.settings.max_level
            self._set_level(character, min(max(character.level + delta, START_LEVEL), max_level))

    def _set_level(self, character: Character, level: int) -> None:
        if level == character.level:
            self.level_var.set(str(level))
            return
        character.level = level
        self.app.data_changed(select=character)

    def move_selected(self, offset: int) -> None:
        character = self._selected_character()
        if character is None:
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
        dialog = CharacterDialog(self, character, self.app.data.settings.max_level)
        self.wait_window(dialog)
        if dialog.result is not None:
            character.name, character.char_class, character.level = dialog.result
            self.app.data_changed(select=character)

    def delete_selected(self) -> None:
        character = self._selected_character()
        if character is None:
            return
        question = f"Biztosan törlöd {article(character.name)} „{character.name}” nevű karaktert a listáról?"
        if not messagebox.askyesno("Karakter törlése", question, parent=self):
            return
        characters = self.app.data.characters
        index = characters.index(character)
        characters.pop(index)
        neighbour = characters[min(index, len(characters) - 1)] if characters else None
        self.app.data_changed(select=neighbour)

    def close(self) -> None:
        self.app.list_window = None
        self.destroy()


class App:
    """A főablak: beállítások, új karakter felvétele, a lista megnyitása."""

    def __init__(self, root: tk.Tk, data_path: Path) -> None:
        self.root = root
        self.data_path = Path(data_path)
        self.list_window: CharacterListWindow | None = None
        self._scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self._today = date.today()
        self._save_error_shown = False
        self._feedback_job: str | None = None

        root.title(APP_TITLE)
        self._setup_styles()
        self.data = self._load_data()

        settings = self.data.settings
        self.start_var = tk.StringVar(value=format_date(settings.start_date))
        self.first_var = tk.StringVar(value=format_date(settings.first_max_date))
        self.last_var = tk.StringVar(value=format_date(settings.last_max_date))
        self.max_level_var = tk.StringVar(value=str(settings.max_level))
        self.mode_var = tk.StringVar(value=settings.mode)
        self.settings_message = tk.StringVar()
        self.name_var = tk.StringVar()
        self.class_var = tk.StringVar()
        self.feedback_var = tk.StringVar()
        self.summary_var = tk.StringVar()

        self._build()
        for variable in (self.start_var, self.first_var, self.last_var, self.max_level_var, self.mode_var):
            variable.trace_add("write", self._on_settings_edited)
        self._show_settings_problems(settings.errors())
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
        body.columnconfigure(0, weight=1)
        wrap = self.px(470)

        ttk.Label(body, text="World of Warcraft – szintezés tervező", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(body, text=INTRO_TEXT, style="Hint.TLabel", wraplength=wrap, justify="left").grid(
            row=1, column=0, sticky="w", pady=(4, 12)
        )

        field_labels = []

        def field_label(frame: ttk.Frame, text: str, row: int, sticky: str = "w") -> None:
            label = ttk.Label(frame, text=text)
            label.grid(row=row, column=0, sticky=sticky, padx=(0, 12), pady=3)
            field_labels.append(label)

        settings = ttk.LabelFrame(body, text="Beállítások", padding=10)
        settings.grid(row=2, column=0, sticky="ew")
        date_rows = (
            ("Szintezés kezdete:", self.start_var),
            ("Első karakter max. szinten:", self.first_var),
            ("Utolsó karakter max. szinten:", self.last_var),
        )
        for row, (text, variable) in enumerate(date_rows):
            field_label(settings, text, row)
            DateField(settings, variable).grid(row=row, column=1, sticky="w", pady=3)
        field_label(settings, "Maximum szint:", 3)
        ttk.Spinbox(
            settings, from_=START_LEVEL + 1, to=MAX_LEVEL_LIMIT, width=6, textvariable=self.max_level_var
        ).grid(row=3, column=1, sticky="w", pady=3)
        field_label(settings, "Ütemezés:", 4, sticky="nw")
        modes = ttk.Frame(settings)
        modes.grid(row=4, column=1, sticky="w", pady=3)
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
            settings, textvariable=self.settings_message, wraplength=wrap, justify="left"
        )
        self.settings_message_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        new = ttk.LabelFrame(body, text="Új karakter hozzáadása", padding=10)
        new.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        field_label(new, "Név:", 0)
        self.name_entry = ttk.Entry(new, textvariable=self.name_var, width=26)
        self.name_entry.grid(row=0, column=1, sticky="w", pady=3)
        field_label(new, "Kaszt (nem kötelező):", 1)
        class_box = ttk.Combobox(new, textvariable=self.class_var, values=WOW_CLASSES, width=24)
        class_box.grid(row=1, column=1, sticky="w", pady=3)
        for widget in (self.name_entry, class_box):
            widget.bind("<Return>", self.add_character)
        ttk.Button(new, text="Hozzáadás", command=self.add_character).grid(
            row=2, column=1, sticky="w", pady=(6, 0)
        )
        ttk.Label(new, textvariable=self.feedback_var, style="Ok.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        # A két keret beviteli mezői egy vonalba kerüljenek.
        label_width = max(label.winfo_reqwidth() for label in field_labels) + self.px(12)
        for frame in (settings, new):
            frame.columnconfigure(0, minsize=label_width)

        footer = ttk.Frame(body)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(footer, textvariable=self.summary_var, justify="left").pack(side="left", anchor="w")
        ttk.Button(footer, text="Karakterlista megnyitása…", command=self.open_list).pack(
            side="right", anchor="n"
        )

    def _on_settings_edited(self, *_args) -> None:
        """Minden módosítás után ellenőrzi a beállításokat; ha helyesek, el is menti őket."""
        values = {}
        problems = []
        date_fields = (
            ("start_date", "Szintezés kezdete", self.start_var),
            ("first_max_date", "Első karakter céldátuma", self.first_var),
            ("last_max_date", "Utolsó karakter céldátuma", self.last_var),
        )
        for key, label, variable in date_fields:
            try:
                values[key] = parse_date(variable.get())
            except ValueError as exc:
                problems.append(f"{label}: {exc}")
        try:
            values["max_level"] = parse_max_level(self.max_level_var.get())
        except ValueError as exc:
            problems.append(str(exc))
        if problems:
            self._show_settings_problems(problems)
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

    def add_character(self, *_args) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Hiányzó név", "Add meg az új karakter nevét!", parent=self.root)
            self.name_entry.focus_set()
            return
        if any(character.name.casefold() == name.casefold() for character in self.data.characters):
            question = f"Már van „{name}” nevű karakter a listán.\nMégis hozzáadod?"
            if not messagebox.askyesno("Létező név", question, parent=self.root):
                return
        character = Character(name=name, char_class=self.class_var.get().strip())
        self.data.characters.append(character)
        self.data_changed(select=character)
        self.name_var.set("")
        self.class_var.set("")
        self.name_entry.focus_set()
        self._show_feedback(f"✔ {name} felkerült a lista {len(self.data.characters)}. helyére (1. szintről indul).")

    def _show_feedback(self, text: str) -> None:
        self.feedback_var.set(text)
        if self._feedback_job is not None:
            self.root.after_cancel(self._feedback_job)
        self._feedback_job = self.root.after(6000, lambda: self.feedback_var.set(""))

    def open_list(self) -> None:
        if self.list_window is not None and self.list_window.winfo_exists():
            self.list_window.deiconify()
            self.list_window.lift()
            self.list_window.focus_set()
            return
        self.list_window = CharacterListWindow(self)

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

    def refresh(self, select: Character | None = None) -> None:
        characters = self.data.characters
        settings = self.data.settings
        if characters:
            done = sum(1 for character in characters if character.level >= settings.max_level)
            lines = [f"Karakterek száma: {len(characters)} (ebből max. szinten: {done})"]
            span = (settings.last_max_date - settings.first_max_date).days
            if len(characters) > 1 and span > 0:
                every = span / (len(characters) - 1)
                every_text = str(int(every)) if every.is_integer() else f"kb. {format_number(every)}"
                lines.append(f"A karakterek {every_text} naponként érik el a maximum szintet.")
            self.summary_var.set("\n".join(lines))
        else:
            self.summary_var.set("Még nincs karakter a listán.")
        if self.list_window is not None:
            self.list_window.refresh(select=select)

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
    App(root, args.data_file)
    root.mainloop()


if __name__ == "__main__":
    main()
