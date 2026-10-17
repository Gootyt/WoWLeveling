"""A gear ajánló ablaka – a „WoW Gearing Ajánló” HTML-oldal a programban: melyik tartalom ad
még fejlesztést a megadott (vagy egy karakter) itemleveléhez. Az adatok és a logika a
gearing.py-ban vannak; a Mythic+ és a raid sorok belépési ilvl-je a statisztikákból frissül
(a statisztikai ablakok „Átvitel a gear ajánlóba” gombjával vagy itt, CSV-ből).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import gearing
from leveling import format_item_level

MANUAL = "– kézi megadás –"
OPTIONS_KEY = "gear"  # az adatfájlban (stats_options) ezen a kulcson vannak a szűrők
ILVL_ERROR = (
    f"Adj meg egy {gearing.MIN_ILVL:.2f} és {gearing.MAX_ILVL:.2f}".replace(".", ",") + " közötti item levelt."
)
HINT = (
    "Add meg az itemlevelt (vagy válassz karaktert), és a táblázat megmutatja, melyik tartalom ad még "
    "fejlesztést: dropból, csak a Great Vaultból, túl alacsony hozzá az itemlevel, vagy már kinőtted. A "
    "Mythic+ és a raid sorok belépési ilvl-je a statisztikákból frissíthető (a kulcsszintek játékosainak, "
    "illetve a bossok kill-jeinek medián itemlevele): a statisztikai ablakok „Átvitel a gear ajánlóba” "
    "gombjával, vagy itt a statisztikák CSV-jéből."
)
# Az állapotok színei (háttér, szöveg) a táblázatban és a jelmagyarázatban
STATUS_COLORS = {
    "recommended": ("#d6f5df", "#1b7f3a"),
    "vault": ("#fff3c4", "#7a5f00"),
    "undergeared": ("#fbdada", "#b3261e"),
    "outgrown": ("#f1f3f4", "#80868b"),
}
COLUMNS = (
    ("name", "Tartalom típusa", 34, "w"),
    ("entry", "Belépési ilvl", 11, "center"),
    ("drop", "Drop ilvl", 9, "center"),
    ("vault", "Great Vault", 10, "center"),
    ("status", "Ajánlás", 16, "w"),
    ("note", "Megjegyzés", 22, "w"),
)


def parse_ilvl(text: str) -> float | None:
    """A mezőbe írt itemlevel (tizedesvessző vagy -pont); üresen None. Hibás vagy a
    tartományon kívüli értéknél ValueError."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    value = float(text)  # ValueError, ha nem szám
    if not gearing.MIN_ILVL <= value <= gearing.MAX_ILVL:
        raise ValueError(text)
    return value


class GearAdvisorWindow(tk.Toplevel):
    """A gear ajánló: itemlevel (vagy karakter), tartalomtípus-szűrők, jelmagyarázat és a
    tartalmak táblázata az ajánlással, a HTML-oldal sorrendjében és színeivel."""

    def __init__(self, app, character=None) -> None:
        super().__init__(app.root)
        self.app = app
        self.title(f"Gear ajánló – {app.root.title()}")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.ilvl_var = tk.StringVar()
        self.character_var = tk.StringVar(value=MANUAL)
        self.error_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.source_var = tk.StringVar()
        options = app.data.stats_options.get(OPTIONS_KEY)
        options = options if isinstance(options, dict) else {}
        active = options.get("groups")
        self.group_vars = {
            group.id: tk.BooleanVar(value=not isinstance(active, list) or group.id in active)
            for group in gearing.GROUPS
        }
        self.show_all_var = tk.BooleanVar(value=options.get("show_all") is True)
        self._characters = []  # a karakterválasztó karakterei (a MANUAL utáni sorrendben)
        self._selected_uid: str | None = None
        self._render_job: str | None = None
        self._building = False
        self._build()
        self.refresh_characters()
        if character is not None:
            self.select_character(character)
        self.ilvl_var.trace_add("write", self._ilvl_typed)
        self.render()
        self.update_idletasks()
        px = app.px
        self.minsize(px(760), px(480))
        width = min(self.winfo_reqwidth(), self.winfo_screenwidth() - px(40))
        height = min(self.winfo_reqheight(), self.winfo_screenheight() - px(80))
        self.geometry(f"{width}x{height}")

    def _build(self) -> None:
        px = self.app.px
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        footer = ttk.Frame(body)  # elsőként a helyére, így kis ablakban is látszik
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        for text, command in (
            ("Importálás CSV-ből…", self.import_csv),
            ("Alapértékek visszaállítása", self.reset_entry_mins),
            ("HTML mentése…", self.export_html),
        ):
            ttk.Button(footer, text=text, command=command).pack(side="left", padx=(0, 6))
        ttk.Button(footer, text="Bezárás", command=self.close).pack(side="right")

        ttk.Label(body, text=HINT, style="Hint.TLabel", wraplength=px(900), justify="left").pack(anchor="w")
        top = ttk.Frame(body)
        top.pack(fill="x", pady=(10, 0))
        ttk.Label(top, text="Karakter:").pack(side="left")
        self.character_box = ttk.Combobox(top, textvariable=self.character_var, state="readonly", width=32)
        self.character_box.pack(side="left", padx=(6, 16))
        self.character_box.bind("<<ComboboxSelected>>", lambda _event: self._character_chosen())
        ttk.Label(top, text="Jelenlegi item level:", style="Strong.TLabel").pack(side="left")
        self.ilvl_entry = ttk.Entry(top, textvariable=self.ilvl_var, width=10)
        self.ilvl_entry.pack(side="left", padx=(6, 6))
        self.ilvl_entry.bind("<Return>", lambda _event: self._format_ilvl())
        self.ilvl_entry.bind("<FocusOut>", lambda _event: self._format_ilvl())
        ttk.Button(top, text="↺ Nullázás", command=self.clear_ilvl).pack(side="left")
        ttk.Label(body, textvariable=self.error_var, style="Error.TLabel").pack(anchor="w", pady=(2, 0))

        filters = ttk.Frame(body)
        filters.pack(fill="x", pady=(4, 0))
        ttk.Label(filters, text="Tartalom:").pack(side="left", padx=(0, 6))
        for group in gearing.GROUPS:
            ttk.Checkbutton(
                filters,
                text=f"{group.label} ({len(group.rows)})",
                variable=self.group_vars[group.id],
                command=self.render,
            ).pack(side="left", padx=(0, 10))
        for text, checked in (("Mindet mutat", True), ("Pipák törlése", False)):
            ttk.Button(filters, text=text, command=lambda checked=checked: self.set_all_groups(checked)).pack(
                side="left", padx=(6 if checked else 0, 4)
            )
        ttk.Checkbutton(
            body, text="Minden Delve/Prey tier mutatása", variable=self.show_all_var, command=self.render
        ).pack(anchor="w", pady=(6, 0))

        legend = ttk.Frame(body)
        legend.pack(fill="x", pady=(8, 6))
        statuses = sorted(gearing.STATUSES.items(), key=lambda item: item[1].priority)
        for key, status in statuses:
            background, foreground = STATUS_COLORS[key]
            tk.Label(
                legend,
                text=f"{status.priority}. {status.legend}",
                background=background,
                foreground=foreground,
                padx=8,
                pady=3,
                relief="solid",
                borderwidth=1,
            ).pack(side="left", padx=(0, 8))

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", height=14)
        font = tkfont.nametofont("TkDefaultFont")
        for key, heading, chars, anchor in COLUMNS:
            width = max(font.measure(heading), font.measure("0") * chars) + font.measure("0") * 2
            self.tree.heading(key, text=heading, anchor=anchor)
            self.tree.column(key, width=width, minwidth=width, anchor=anchor, stretch=key in ("name", "note"))
        for key, (background, foreground) in STATUS_COLORS.items():
            self.tree.tag_configure(key, background=background, foreground=foreground)
        bar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        ttk.Label(body, textvariable=self.summary_var).pack(anchor="w", pady=(6, 0))
        ttk.Label(body, textvariable=self.source_var, style="Hint.TLabel").pack(anchor="w")

    # -- itemlevel és karakter
    def refresh_characters(self) -> None:
        """A karakterválasztó a megadott itemlevelű karakterekkel; a kiválasztott karakter
        itemlevelének változását is követi."""
        self._characters = [c for c in self.app.data.characters if c.item_level is not None]
        self.character_box.configure(
            values=[MANUAL] + [f"{c.name} ({format_item_level(c.item_level)})" for c in self._characters]
        )
        selected = next((c for c in self._characters if c.uid == self._selected_uid), None)
        if selected is None:
            self._selected_uid = None
            self.character_var.set(MANUAL)
        else:
            self.select_character(selected)

    def select_character(self, character) -> None:
        if character is None or character.item_level is None:
            return
        self._selected_uid = character.uid
        self.character_var.set(f"{character.name} ({format_item_level(character.item_level)})")
        self._set_ilvl(format_item_level(character.item_level))

    def _character_chosen(self) -> None:
        index = self.character_box.current()
        if index <= 0:
            self._selected_uid = None
            return
        self.select_character(self._characters[index - 1])

    def _set_ilvl(self, text: str) -> None:
        self._building = True  # ez nem kézi megadás
        try:
            self.ilvl_var.set(text)
        finally:
            self._building = False
        self.render()

    def _ilvl_typed(self, *_args) -> None:
        if self._building:
            return
        if self._selected_uid is not None:  # kézzel átírva: már nem a karakteré
            self._selected_uid = None
            self.character_var.set(MANUAL)
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(150, self.render)

    def _format_ilvl(self) -> None:
        """Véglegesítéskor (Enter, fókuszvesztés) két tizedesre formázza a mezőt."""
        try:
            value = parse_ilvl(self.ilvl_var.get())
        except ValueError:
            return
        if value is not None:
            self._set_ilvl(f"{value:.2f}".replace(".", ","))

    def clear_ilvl(self) -> None:
        self._selected_uid = None
        self.character_var.set(MANUAL)
        self._set_ilvl("")
        self.ilvl_entry.focus_set()

    def set_all_groups(self, checked: bool) -> None:
        for variable in self.group_vars.values():
            variable.set(checked)
        self.render()

    # -- táblázat
    def items(self) -> list[gearing.Evaluation]:
        """A megjelenítendő sorok a mezők szerint (a hibás itemlevel üresnek számít)."""
        try:
            ilvl = parse_ilvl(self.ilvl_var.get())
        except ValueError:
            ilvl = None
        active = {group_id for group_id, variable in self.group_vars.items() if variable.get()}
        return gearing.build_items(ilvl, active, self.show_all_var.get(), self.app.gear_groups())

    def render(self) -> None:
        self._render_job = None
        try:
            ilvl = parse_ilvl(self.ilvl_var.get())
            self.error_var.set("")
        except ValueError:
            ilvl = None
            self.error_var.set(ILVL_ERROR)
        items = self.items()
        self.tree.delete(*self.tree.get_children())
        if not items:
            nothing_checked = not any(variable.get() for variable in self.group_vars.values())
            self.summary_var.set(
                "Nincs bepipálva egyetlen tartalomtípus sem. Válassz legalább egyet a szűrők közül."
                if nothing_checked
                else "Erre a szűrésre nincs találat."
            )
        else:
            for item in items:
                row = item.row
                values = (
                    row.name,
                    gearing.format_ilvl(max(row.entry_min, gearing.MIN_ILVL)),  # 0 (nincs korlát) → 1
                    gearing.format_ilvl(row.drop_max),
                    "Nincs" if row.vault_max is None else gearing.format_ilvl(row.vault_max),
                    gearing.STATUSES[item.status].label if item.status else "-",
                    item.note,
                )
                self.tree.insert("", "end", values=values, tags=(item.status,) if item.status else ())
            recommended = sum(1 for item in items if item.status == "recommended")
            self.summary_var.set(
                f"{len(items)} sor látható."
                if ilvl is None
                else f"{len(items)} sor látható, ebből {recommended} ajánlott."
            )
        updated = len(self.app.data.gear_entry_min)
        self.source_var.set(
            f"Belépési ilvl-ek: {updated} sor a statisztikákból frissítve, a többi az alapérték."
            if updated
            else "Belépési ilvl-ek: az alapértékek (még nem volt átvitel a statisztikákból)."
        )

    def rows(self) -> list[tuple[str, ...]]:
        return [tuple(str(v) for v in self.tree.item(iid, "values")) for iid in self.tree.get_children()]

    # -- adatok
    def import_csv(self) -> None:
        """Belépési ilvl-ek a statisztikák CSV-jéből (live.csv, stat.csv), mint az update.py-nál."""
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Statisztika CSV-jének megnyitása (live.csv, stat.csv)",
            filetypes=[("CSV fájl", "*.csv"), ("Minden fájl", "*.*")],
        )
        if not paths:
            return
        targets, prefixes = {}, []
        for path in paths:
            try:
                file_targets, prefix = gearing.read_stats_csv(path)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                messagebox.showerror("Importálás CSV-ből", f"Nem sikerült beolvasni:\n{exc}", parent=self)
                return
            targets.update(file_targets)
            prefixes.append(prefix)
        names = ", ".join(Path(path).name for path in paths)
        self.app.transfer_gear_targets(targets, prefixes, names, parent=self)

    def reset_entry_mins(self) -> None:
        if not self.app.data.gear_entry_min:
            messagebox.showinfo("Alapértékek", "A belépési ilvl-ek már most is az alapértékek.", parent=self)
            return
        question = (
            f"Visszaállítod a statisztikákból frissített {len(self.app.data.gear_entry_min)} belépési ilvl-t "
            "az alapértékre?"
        )
        if messagebox.askyesno("Alapértékek visszaállítása", question, parent=self):
            self.app.data.gear_entry_min.clear()
            self.app.save()
            self.render()

    def export_html(self) -> None:
        """A „WoW Gearing Ajánló” HTML-oldal mentése a program mostani adataival."""
        title = "HTML mentése"
        try:
            template = gearing.HTML_TEMPLATE.read_text(encoding="utf-8")
            html, missing = gearing.update_html(template, self.app.gear_groups())
        except (OSError, ValueError) as exc:
            messagebox.showerror(title, f"Nem található a HTML-sablon:\n{exc}", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title=title,
            defaultextension=".html",
            initialfile=gearing.HTML_TEMPLATE.name,
            initialdir=str(Path(self.app.data_path).resolve().parent),
            filetypes=[("HTML-oldal", "*.html"), ("Minden fájl", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as handle:  # a sorvégek maradnak
                handle.write(html)
        except OSError as exc:
            messagebox.showerror(title, f"Nem sikerült menteni:\n{exc}", parent=self)
            return
        message = f"Elmentve: {path}"
        if missing:
            message += "\n\nEzek a sorok nincsenek meg a HTML-oldalon: " + ", ".join(missing)
        messagebox.showinfo(title, message, parent=self)

    def close(self) -> None:
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        options = {
            "groups": [group_id for group_id, variable in self.group_vars.items() if variable.get()],
            "show_all": self.show_all_var.get(),
        }
        if self.app.data.stats_options.get(OPTIONS_KEY) != options:
            self.app.data.stats_options[OPTIONS_KEY] = options
            self.app.save()
        self.app.gear_advisor_window = None
        self.destroy()
