"""A beépített statisztikai programok ablakai.

* M+ ilvl statisztika: milyen itemlevelű játékosok viszik időben a Mythic+ kulcsokat,
  kulcsszintenként (raiderio_ilvl_stats.py, a Raider.io adataiból).
* Raid ilvl statisztika: milyen itemlevellel ölik meg az aktuális raid bossait Normal,
  Heroic és Mythic nehézségen (wcl_raid_ilvl_stats.py, a Warcraft Logs adataiból).

A lekérdezés a háttérben fut, közben a program használható; a „Leállítás” gomb az eddig
összegyűjtött adatokkal zárja le (mint parancssorban a Ctrl+C). A beállítások, az API-kulcsok
(ha kéred) és a letöltött adatok gyorsítótára is a program adatbázisába kerülnek (lásd
storage.py), így egy újabb lekérdezés csak az újakat kéri le.

A gear ajánló automatikus frissítéséhez (App.update_gear_stats) a program egy rejtett ablakban
indítja el a lekérdezést (start_automatic) az elmentett beállításokkal; az ablak gombjával
megnyitva ugyanez látszik, és a végén az eredmény magától a gear ajánlóba kerül.
"""

from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import gearing
import raiderio_ilvl_stats as mplus
import storage
import wcl_raid_ilvl_stats as wcl

LOG_LINES = 2000  # ennyi sor marad meg a naplóban
POLL_MS = 100  # ilyen gyakran nézi az ablak a háttérszál üzeneteit

MPLUS_REGIONS = ("eu", "us", "kr", "tw", "cn", "world")
WCL_REGIONS = ("mind", "eu", "us", "kr", "tw", "cn")

# A háttérszálak modulonként: egy lekérdezés futhat egyszerre (a modulok globális állapota miatt).
_workers: dict[str, threading.Thread] = {}
BUSY = "Még fut (vagy most áll le) egy lekérdezés."  # a start_automatic válasza, ha most nem indítható
NO_KEY = "nincs Warcraft Logs API-kulcs (a Raid ilvl statisztika ablakában adható meg)"  # és ha kulcs kellene
AUTO_HINT = (
    "A gear ajánló belépési ilvl-jeihez a program ezt a lekérdezést az itt beállított értékekkel "
    "magától is lefuttatja, és az eredményt átviszi (lásd a gear ajánló ablakát)."
)


class MissingApiKey(ValueError):
    """A lekérdezéshez API-kulcs kellene (a raid statisztikához a Warcraft Logs kulcsa)."""


def load_api_keys(database: Path) -> dict[str, str]:
    """Az adatbázisba mentett API-kulcsok (ha nincsenek, vagy hibásak: üres)."""
    try:
        text = storage.read_document(database, storage.API_KEYS)
        data = json.loads(text) if text else {}
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, str) and value}


def save_api_keys(database: Path, changes: dict[str, str]) -> None:
    """A megadott kulcsok mentése az adatbázisba (üres érték: törlés), a többi kulcs marad; ha
    egy sem marad, a bejegyzés törlődik. A mentés nem kötelező, ezért a hibája nem állítja meg a
    programot."""
    keys = load_api_keys(database)
    for key, value in changes.items():
        if value:
            keys[key] = value
        else:
            keys.pop(key, None)
    try:
        if keys:
            storage.write_document(database, storage.API_KEYS, json.dumps(keys, ensure_ascii=False, indent=2))
        elif Path(database).exists():
            storage.delete_document(database, storage.API_KEYS)
    except OSError:
        pass


def format_stat(value) -> str:
    """Statisztikai érték egy tizedesjeggyel, tizedesvesszővel (pl. 329,4); hiányzó: –."""
    return "–" if value is None else f"{value:.1f}".replace(".", ",")


def parse_levels_text(text: str) -> str | None:
    """A kulcsszintek mezője („2-10, 15”) a raiderio_ilvl_stats --levels alakjában
    („2,3,…,10,15”); üresen None (minden szint). Hibás alaknál ValueError."""
    levels = set()
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        low, dash, high = part.partition("-")
        first = int(low)
        last = int(high) if dash else first
        if not 1 <= first <= last <= 99:
            raise ValueError(part)
        levels.update(range(first, last + 1))
    return ",".join(str(level) for level in sorted(levels)) or None


def parse_number(text: str, label: str, kind=int, minimum=0, maximum=None, empty=None):
    """Szám egy beviteli mezőből (tizedesvessző is jó); üresen az `empty` érték, ha az nem
    None. Hibánál ValueError a megjelenítendő magyar üzenettel."""
    text = text.strip().replace(",", ".")
    if not text and empty is not None:
        return empty
    try:
        value = kind(text)
        if not math.isfinite(value):
            raise ValueError(text)
    except ValueError:
        what = "egész számot" if kind is int else "számot"
        raise ValueError(f"{label}: {what} adj meg.") from None
    if maximum is not None and not minimum <= value <= maximum:
        raise ValueError(f"{label}: {minimum:g} és {maximum:g} közötti szám lehet.")
    if value < minimum:
        raise ValueError(f"{label}: legalább {minimum:g} lehet.")
    return value


def parse_guilds(text: str, region: str) -> list[str]:
    """A guildek mezője (vesszővel vagy pontosvesszővel elválasztva, Név@realm vagy
    Név@realm@régió) a raiderio_ilvl_stats --guild értékeiként. Hibánál ValueError."""
    guilds = []
    for spec in text.replace(";", ",").split(","):
        spec = spec.strip()
        if not spec:
            continue
        parts = [part.strip() for part in spec.split("@")]
        if len(parts) not in (2, 3) or not all(parts) or (len(parts) == 3 and parts[2].lower() not in MPLUS_REGIONS):
            raise ValueError(f"„{spec}”: a guildet Név@realm vagy Név@realm@régió alakban add meg (pl. Solutions@Ragnaros).")
        guilds.append("@".join(parts))
    if not guilds:
        raise ValueError("Add meg legalább egy guildet Név@realm alakban (pl. Solutions@Ragnaros).")
    if region == "world":
        raise ValueError("Guildek bejárásához válassz konkrét régiót (a „world” csak a ranglistához jó).")
    return guilds


class LogPane(ttk.Frame):
    """Görgethető, csak olvasható napló; ha a végén áll, az új sorokat is mutatja."""

    def __init__(self, parent: tk.Misc, height: int = 8) -> None:
        super().__init__(parent)
        self.text = tk.Text(self, height=height, wrap="word", state="disabled", relief="flat", borderwidth=1)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        self.text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

    def add(self, line: str) -> None:
        at_end = self.text.yview()[1] >= 0.999
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > LOG_LINES:
            self.text.delete("1.0", f"{lines - LOG_LINES}.0")
        self.text.configure(state="disabled")
        if at_end:
            self.text.see("end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def content(self) -> str:
        return self.text.get("1.0", "end-1c")


class StatsTable(ttk.Frame):
    """Statisztikai táblázat. columns: (azonosító, fejléc, szélesség karakterben); a széles
    ablakban az első oszlop nyúlik (stretch_all: mindegyik)."""

    def __init__(self, parent: tk.Misc, columns, height: int = 8, total_font=None, stretch_all=False) -> None:
        super().__init__(parent)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings", height=height)
        font = tkfont.nametofont("TkDefaultFont")
        for index, (key, heading, chars) in enumerate(columns):
            width = max(font.measure(heading), font.measure("0") * chars) + font.measure("0") * 3
            anchor = "w" if index == 0 and not stretch_all else "center"
            self.tree.heading(key, text=heading, anchor=anchor)
            self.tree.column(key, width=width, minwidth=width, anchor=anchor, stretch=stretch_all or index == 0)
        if total_font is not None:
            self.tree.tag_configure("total", font=total_font)  # az „Összes boss” sor
        bar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

    def show(self, rows, totals: int = 0) -> None:
        """A sorok megjelenítése (szövegek); az utolsó `totals` sor kiemelve."""
        self.tree.delete(*self.tree.get_children())
        for index, values in enumerate(rows):
            tags = ("total",) if index >= len(rows) - totals else ()
            self.tree.insert("", "end", values=values, tags=tags)

    def rows(self) -> list[tuple[str, ...]]:
        return [tuple(str(v) for v in self.tree.item(iid, "values")) for iid in self.tree.get_children()]


class StatsWindow(tk.Toplevel):
    """A két statisztikai ablak közös része: a háttérszál és az üzenetei, a gombok, a napló
    és a beállítások mentése. Az alosztályok adják a mezőket és a lekérdezést."""

    TITLE = ""
    WINDOW_ATTRIBUTE = ""  # az App attribútuma, amely az ablakot tartja
    OPTIONS_KEY = ""  # az adatfájlban (stats_options) ezen a kulcson vannak a beállítások
    HINT = ""
    CSV_NAME = ""
    module = None  # a statisztikai program modulja (STOP)

    def __init__(self, app, hidden: bool = False) -> None:
        super().__init__(app.root)
        if hidden:  # az automatikus frissítés ablaka: csak az ablak gombjával megnyitva látszik
            self.withdraw()
        self.app = app
        self.automatic = False  # a gear ajánló automatikus frissítése fut-e benne (lásd start_automatic)
        self.title(f"{self.TITLE} – {app.root.title()}")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.database = Path(app.data_path).resolve()  # a gyorsítótár és a kulcsok is ide kerülnek
        self.folder = self.database.parent  # a CSV-fájlok alapértelmezett helye
        self.keys = load_api_keys(self.database)
        self.status_var = tk.StringVar(value="Állítsd be a lekérdezést, majd kattints az „Indítás” gombra.")
        self._messages: queue.Queue = queue.Queue()
        self._running = False
        self._poll_job: str | None = None
        self._option_vars: dict[str, tk.Variable] = {}
        px = app.px
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        # Az alsó sor elsőként kerül a helyére, így kis ablakban is látszik (a napló zsugorodik).
        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(footer, text="Bezárás", command=self.close).pack(side="right")
        ttk.Label(
            body, text=f"{self.HINT} {AUTO_HINT}", style="Hint.TLabel", wraplength=px(900), justify="left"
        ).pack(anchor="w", pady=(0, 8))
        self._build_options(body)
        self._load_keys()
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 4))
        self.start_button = ttk.Button(buttons, text="Indítás", command=self.start)
        self.stop_button = ttk.Button(buttons, text="Leállítás", command=self.stop, state="disabled")
        self.csv_button = ttk.Button(buttons, text="CSV mentése…", command=self.save_csv, state="disabled")
        self.transfer_button = ttk.Button(
            buttons, text="Átvitel a gear ajánlóba", command=self.transfer, state="disabled"
        )
        for button in (self.start_button, self.stop_button, self.csv_button, self.transfer_button):
            button.pack(side="left", padx=(0, 6))
        self.status_label = ttk.Label(buttons, textvariable=self.status_var, wraplength=px(620), justify="left")
        self.status_label.pack(side="left", padx=(6, 0))
        self._build_results(body)
        ttk.Label(body, text="Napló").pack(anchor="w", pady=(8, 2))
        self.log = LogPane(body, height=4)
        self.log.pack(fill="both", expand=True)
        self._load_options()
        self.update_idletasks()
        self.minsize(px(720), px(480))
        width = min(self.winfo_reqwidth(), self.winfo_screenwidth() - px(40))
        height = min(self.winfo_reqheight(), self.winfo_screenheight() - px(80))
        self.geometry(f"{width}x{height}")

    # -- az alosztályok részei
    def _build_options(self, parent: tk.Misc) -> None:
        raise NotImplementedError

    def _build_results(self, parent: tk.Misc) -> None:
        raise NotImplementedError

    def _load_keys(self) -> None:
        """A mentett (vagy környezeti változóban megadott) API-kulcsok a mezőkbe."""

    def _prepare(self, automatic: bool = False):
        """A mezőkből a lekérdezés (a háttérszálnak); hibás mezőnél ValueError. automatic: a gear
        ajánló automatikus frissítéséhez – ilyenkor a kulcsokat nem menti (és nem is törli) a
        „Megjegyzés” jelölőnégyzet szerint, és a gyorsítótárat sem tölti le újra."""
        raise NotImplementedError

    def _work(self, job) -> None:
        """A háttérszálban fut; az eredményt és a naplót a self._post-tal küldi."""
        raise NotImplementedError

    def _handle(self, message: tuple) -> None:
        """Egy háttérszálból jött üzenet feldolgozása (a „log” és a „finished” üzenetet
        a közös rész kezeli)."""

    def _write_csv(self, path: str) -> None:
        raise NotImplementedError

    # -- mezők és beállítások
    def option(self, name: str, default, kind=tk.StringVar) -> tk.Variable:
        """A beállításként mentett mező változója (az alapértékkel)."""
        variable = kind(value=default)
        self._option_vars[name] = variable
        return variable

    def _load_options(self) -> None:
        saved = self.app.data.stats_options.get(self.OPTIONS_KEY)
        if not isinstance(saved, dict):
            return
        for name, variable in self._option_vars.items():
            value = saved.get(name)
            if isinstance(variable, tk.BooleanVar) and isinstance(value, bool):
                variable.set(value)
            elif not isinstance(variable, tk.BooleanVar) and isinstance(value, str):
                variable.set(value)

    def _save_options(self) -> None:
        options = {name: variable.get() for name, variable in self._option_vars.items()}
        if self.app.data.stats_options.get(self.OPTIONS_KEY) != options:
            self.app.data.stats_options[self.OPTIONS_KEY] = options
            self.app.save()

    def field(self, parent: tk.Misc, row: int, label: str, widget: tk.Widget, hint: str = "", column: int = 0):
        """Felirat, mező és (ha van) halvány magyarázat egy rácssorban."""
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 8), pady=2)
        # magyarázat nélkül a mező a magyarázatok oszlopát is elfoglalhatja (nem szélesíti a mezők oszlopát)
        widget.grid(row=row, column=column + 1, columnspan=1 if hint else 2, sticky="w", pady=2)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel", wraplength=self.app.px(440), justify="left").grid(
                row=row, column=column + 2, sticky="w", padx=(8, 12), pady=2
            )

    # -- futtatás
    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._busy():
            messagebox.showinfo(
                self.TITLE, "Az előző lekérdezés még leáll – próbáld újra pár másodperc múlva.", parent=self
            )
            return
        try:
            job = self._prepare()
        except ValueError as exc:
            messagebox.showwarning(self.TITLE, str(exc), parent=self)
            return
        self._save_options()
        self._launch(job, "Lekérdezés folyamatban…")

    def start_automatic(self) -> str | None:
        """Indítás a gear ajánló automatikus frissítéséhez (lásd App.update_gear_stats): a mezők
        (az elmentett beállítások) szerint, üzenetablakok és a kulcsok mentése nélkül; a végén az
        App.gear_stats_finished viszi át az eredményt. None, ha elindult, különben az oka (BUSY:
        egy korábbi lekérdezés még fut vagy most áll le; NO_KEY: nincs megadva API-kulcs)."""
        if self._busy():
            return BUSY
        if self.state() == "withdrawn":  # a rejtett ablak a legutóbb elmentett beállításokkal fusson
            self.keys = load_api_keys(self.database)
            self._load_keys()
            self._load_options()
        try:
            job = self._prepare(automatic=True)
        except MissingApiKey:
            return NO_KEY
        except ValueError as exc:
            return str(exc)
        self.automatic = True
        self._launch(job, "Automatikus frissítés folyamatban (a gear ajánlóhoz)…")
        return None

    def _busy(self) -> bool:
        """Fut-e még (vagy áll-e még le) lekérdezés ezzel a statisztikai programmal."""
        previous = _workers.get(self.OPTIONS_KEY)
        return previous is not None and previous.is_alive()

    def _launch(self, job, status: str) -> None:
        self.module.STOP.clear()
        self._messages = queue.Queue()
        self._running = True
        self.log.clear()
        self._set_buttons()
        self.status_var.set(status)
        self.status_label.configure(style="TLabel")
        thread = threading.Thread(target=self._run_work, args=(job,), daemon=True)
        _workers[self.OPTIONS_KEY] = thread
        thread.start()
        self._poll_job = self.after(POLL_MS, self._poll)

    def _run_work(self, job) -> None:
        try:
            self._work(job)
        except Exception as exc:  # váratlan hiba se akassza meg a programot
            self._post(("finished", f"Váratlan hiba: {exc!r}", True))

    def _post(self, message: tuple) -> None:
        self._messages.put(message)

    def stop(self) -> None:
        if self._running:
            self.module.STOP.set()
            self.status_var.set("Leállítás… (az éppen futó kérés még befejeződik)")
            self.stop_button.state(["disabled"])

    def _poll(self) -> None:
        self._poll_job = None
        try:
            while True:
                message = self._messages.get_nowait()
                kind = message[0]
                if kind == "log":
                    self.log.add(message[1])
                elif kind == "finished":
                    self._finish(message[1], message[2])
                else:
                    self._handle(message)
        except queue.Empty:
            pass
        if self._running:
            self._poll_job = self.after(POLL_MS, self._poll)

    def _finish(self, text: str, problem: bool) -> None:
        self._running = False
        self.status_var.set(text)
        self.status_label.configure(style="Error.TLabel" if problem else "Ok.TLabel")
        self._set_buttons()
        if self.automatic:
            self.automatic = False
            outcome = "failed" if problem else "stopped" if self.module.STOP.is_set() else "done"
            self.app.gear_stats_finished(self, outcome, text)

    def _set_buttons(self) -> None:
        self.start_button.state(["disabled" if self._running else "!disabled"])
        self.stop_button.state(["!disabled" if self._running else "disabled"])
        ready = not self._running and self.has_results()
        for button in (self.csv_button, self.transfer_button):
            button.state(["!disabled" if ready else "disabled"])

    def has_results(self) -> bool:
        raise NotImplementedError

    def gear_targets(self) -> tuple[dict, str]:
        """Az eredményből a gear ajánló sorainak új belépési ilvl-je és a sorok névkezdete."""
        raise NotImplementedError

    def transfer(self) -> None:
        """Az eredmény (medián itemlevelek) átvitele a gear ajánló belépési ilvl-jeibe."""
        targets, prefix = self.gear_targets()
        changed = self.app.transfer_gear_targets(targets, [prefix], self.TITLE, parent=self)
        if changed is not None:  # átvitte, vagy már egyezett: ehhez igazodik az automatikus frissítés
            self.app.gear_stats_transferred(self.OPTIONS_KEY)
        if changed:
            self.status_var.set(f"Átvive a gear ajánlóba: {changed} belépési ilvl.")
            self.status_label.configure(style="Ok.TLabel")

    def save_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="CSV mentése",
            defaultextension=".csv",
            initialfile=self.CSV_NAME,
            initialdir=str(self.folder),
            filetypes=[("CSV fájl", "*.csv"), ("Minden fájl", "*.*")],
        )
        if not path:
            return
        try:
            self._write_csv(path)
        except OSError as exc:
            messagebox.showerror(self.TITLE, f"Nem sikerült menteni (nyitva van Excelben?):\n{exc}", parent=self)
            return
        self.status_var.set(f"CSV elmentve: {path}")
        self.status_label.configure(style="Ok.TLabel")

    def close(self) -> None:
        if self._running and self.automatic:
            self.withdraw()  # az automatikus frissítés a háttérben fut tovább
            return
        if self._running:
            self.module.STOP.set()  # a háttérszál a következő kérésnél leáll
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        self._save_options()
        setattr(self.app, self.WINDOW_ATTRIBUTE, None)
        self.destroy()


# Miért szakadt meg a lekérdezés (a TooManyErrors.kind, lásd mplus.failure_kind).
MPLUS_ABORT_CAUSES = {
    "rate_limit": "a Raider.io túl sok kérést jelzett (lekérési korlát): várj néhány percet, vagy adj meg API-kulcsot",
    "unavailable": "a Raider.io nem válaszol (kimaradás, vagy nincs internetkapcsolat)",
    "refused": "a Raider.io elutasította a kéréseket",
}
KEY_REFUSED = (
    " A Raider.io nem fogadta el az API-kulcsot, ezért kulcs nélkül kérdezett le: javítsd vagy töröld a"
    " „Raider.io API-kulcs” mezőben."
)


def mplus_abort_text(abort: dict) -> str:
    """Az ablak állapotsora, ha a lekérdezés sok egymás utáni hiba miatt megszakadt."""
    cause = MPLUS_ABORT_CAUSES.get(abort.get("kind"))
    text = f"Megszakadt: {mplus.MAX_ERROR_STREAK} karakter lekérése egymás után nem sikerült"
    text += f" – {cause}." if cause else "."
    if abort.get("last"):
        text += f" Az utolsó hiba: {abort['last']}."
    return text + " A táblázat az addig összegyűjtött adatokat mutatja."


class _MythicView(mplus.LiveView):
    """A raiderio_ilvl_stats élő nézete az ablakhoz: a háttérszálban a konzol helyett
    üzenetet küld (a táblázat sorait, az állapotot, a naplósorokat), az ablak a saját
    szálán rajzolja ki őket. Ugyanúgy legfeljebb fél másodpercenként frissít."""

    def __init__(self, state, guild_queue, title, post) -> None:
        super().__init__(state, guild_queue, title, in_place=False, csv_path=None, min_interval=0.5)
        self.active = True  # a naplósorok (log) az ablakba kerülnek, nem a konzolra
        self.post = post

    def start(self) -> None:
        self.draw()

    def stop(self, final_status=None) -> None:
        self.status = ""  # a végeredményt az ablak állapotsora mondja meg
        self.draw()
        self.active = False

    def event(self, text) -> None:
        self.post(("log", time.strftime("%H:%M:%S ") + " ".join(str(text).split())))

    def progress(self) -> str:
        c = self.state["c"]
        text = f"Felhasznált futások: {sum(self.state['runs'].values())}"
        dropped = c["skipped_untimed"] + c["skipped_timer_unknown"]
        if dropped:
            text += f" (nem időben teljesített, kihagyva: {dropped})"
        if c["skipped_ilvl_range"]:
            text += f" · tartományon kívüli itemlevel, kihagyva: {c['skipped_ilvl_range']} játékos"
        if c["private_profiles"]:
            text += f" · privát profil, kihagyva: {c['private_profiles']} karakter"
        if c["guilds_done"] or len(self.queue):
            text += (
                f" · beolvasott guildek: {c['guilds_done']}, várakozik: {len(self.queue)}"
                f" · ellenőrzött karakterek: {c['chars_checked']}"
            )
        if c["cached_runs"]:
            text += f" · ebből korábban letöltött (a gyorsítótárból): {c['cached_runs']}"
        return text

    def api_line(self) -> str:
        c = self.state["c"]
        text = (
            f"API-kérések: {mplus.HTTP_CALLS} · a gyorsítótárból: {c['run_hits']} futás, "
            f"{c['profile_hits']} profil, {c['guild_hits']} guildlista"
        )
        if c["page_hits"] or c["page_calls"]:
            text += f", {c['page_hits']} ranglista-oldal"
        errors = c["lookup_errors"] + c["details_errors"] + c["guild_errors"]
        return text + (f" · hibák: {errors}" if errors else "")

    def draw(self) -> None:
        self.last_draw = time.monotonic()
        self.stats_dirty = self.screen_dirty = False
        self.post(("live", mplus.summary_rows(self.state), self.progress(), self.api_line(), self.status, self.elapsed()))


class MythicStatsWindow(StatsWindow):
    """Mythic+ csapatok itemlevele kulcsszintenként, a Raider.io adataiból."""

    TITLE = "M+ ilvl statisztika"
    WINDOW_ATTRIBUTE = "mplus_stats_window"
    OPTIONS_KEY = "mplus"
    CSV_NAME = "mplus_ilvl_statisztika.csv"
    module = mplus
    HINT = (
        "A Raider.io nyilvános adataiból számolja ki, milyen itemlevelű játékosok viszik időben a "
        "Mythic+ kulcsokat, kulcsszintenként: átlag, medián, 25. percentilis (P25: a játékosok negyedének "
        "ennél kisebb az itemlevele), minimum és maximum. A ranglista csak a legjobb pontszámú (magas) "
        "futásokat éri el; a guildek tagjainak legutóbbi futásai minden kulcsszintet. A táblázat menet "
        "közben frissül; a „Leállítás” az eddigi adatokkal zárja le. A letöltött adatok a gyorsítótárban "
        "maradnak, így egy újabb lekérdezés csak az újakat kéri le. Alapból csak a most elért futásokból "
        "számol; kérésre a korábbi lekérdezésekkel letöltött futásokat is beszámolja, ha megfelelnek a "
        "szűrőknek."
    )
    COLUMNS = (
        ("level", "Kulcsszint", 8),
        ("runs", "Futás", 6),
        ("players", "Játékos", 7),
        ("avg", "Átlag", 7),
        ("median", "Medián", 7),
        ("p25", "P25", 7),
        ("min", "Min", 6),
        ("max", "Max", 6),
    )

    def __init__(self, app, hidden: bool = False) -> None:
        self.result_rows: list[tuple] = []  # a legutóbbi eredmény (a CSV-hez)
        super().__init__(app, hidden)

    def _build_options(self, parent: tk.Misc) -> None:
        region = self.app.data.settings.region
        self.source_var = self.option("source", "leaderboard")
        self.region_var = self.option("region", region if region in MPLUS_REGIONS else "eu")
        self.guilds_var = self.option("guilds", "")
        # A guildek követése forrásonként: a ranglistánál alapból ki (különben a gyors lekérdezés
        # végtelen bejárássá válna), guildeknél be – mint a parancssorban. A jelölőnégyzet mindig
        # az éppen választott forrásét mutatja.
        self.follow_by_source = {
            "leaderboard": self.option("follow_leaderboard", False, tk.BooleanVar),
            "guild": self.option("follow_guild", True, tk.BooleanVar),
        }
        self.follow_var = tk.BooleanVar(value=self.follow_by_source[self.source_var.get()].get())
        self.max_guilds_var = self.option("max_guilds", "0")
        self.levels_var = self.option("levels", "")
        self.per_level_var = self.option("per_level", "0")
        self.min_ilvl_var = self.option("min_ilvl", "250")
        self.max_ilvl_var = self.option("max_ilvl", "350")
        self.since_days_var = self.option("since_days", "")
        self.cache_hours_var = self.option("cache_hours", "24")
        self.timed_only_var = self.option("timed_only", True, tk.BooleanVar)
        self.cached_runs_var = self.option("cached_runs", False, tk.BooleanVar)
        self.pages_var = self.option("pages", "5")
        self.each_dungeon_var = self.option("each_dungeon", False, tk.BooleanVar)
        self.affixes_var = self.option("affixes", "all")
        self.api_key_var = tk.StringVar()
        self.remember_key_var = tk.BooleanVar(value=True)

        box = ttk.LabelFrame(parent, text="Lekérdezés", padding=8)
        box.pack(fill="x")
        source = ttk.Frame(box)
        source.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Label(source, text="Forrás:").pack(side="left", padx=(0, 8))
        for value, text in (
            ("leaderboard", "Ranglista (a legjobb futások)"),
            ("guild", "Guildek tagjainak futásai (minden kulcsszint)"),
        ):
            ttk.Radiobutton(
                source, text=text, value=value, variable=self.source_var, command=self._source_changed
            ).pack(side="left", padx=(0, 12))
        ttk.Label(source, text="Régió:").pack(side="left", padx=(12, 4))
        ttk.Combobox(source, textvariable=self.region_var, values=MPLUS_REGIONS, state="readonly", width=7).pack(
            side="left"
        )
        self.field(
            box,
            1,
            "Guildek:",
            ttk.Entry(box, textvariable=self.guilds_var, width=48),
            "Név@realm, több guild vesszővel (más régió: Név@realm@us)",
        )
        follow = ttk.Frame(box)
        follow.grid(row=2, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(
            follow,
            text="A csapattagok guildjeit is bejárja (sokáig futhat)",
            variable=self.follow_var,
            command=lambda: self.follow_by_source[self.source_var.get()].set(self.follow_var.get()),
        ).pack(side="left")
        ttk.Label(follow, text="legfeljebb").pack(side="left", padx=(12, 4))
        ttk.Entry(follow, textvariable=self.max_guilds_var, width=6).pack(side="left")
        ttk.Label(follow, text="guild (0: nincs korlát)", style="Hint.TLabel").pack(side="left", padx=(4, 0))

        levels = ttk.Frame(box)
        ttk.Entry(levels, textvariable=self.levels_var, width=16).pack(side="left")
        ttk.Label(levels, text="pl. 2-10 vagy 18,19,20; üresen: mind", style="Hint.TLabel").pack(side="left", padx=(6, 16))
        ttk.Label(levels, text="legfeljebb").pack(side="left", padx=(0, 4))
        ttk.Entry(levels, textvariable=self.per_level_var, width=6).pack(side="left")
        ttk.Label(levels, text="futás szintenként (0: nincs korlát)", style="Hint.TLabel").pack(side="left", padx=(4, 0))
        self.field(box, 3, "Kulcsszintek:", levels)

        ilvl = ttk.Frame(box)
        ttk.Entry(ilvl, textvariable=self.min_ilvl_var, width=7).pack(side="left")
        ttk.Label(ilvl, text="–").pack(side="left", padx=4)
        ttk.Entry(ilvl, textvariable=self.max_ilvl_var, width=7).pack(side="left")
        ttk.Label(ilvl, text="a többit kihagyja (0: nincs korlát)", style="Hint.TLabel").pack(side="left", padx=(6, 0))
        self.field(box, 4, "Itemlevel:", ilvl)

        # Milyen régi adatokból számoljon: a futások kora, és meddig jók a letöltött adatok.
        age = ttk.Frame(box)
        ttk.Label(age, text="csak az utolsó").pack(side="left", padx=(0, 4))
        ttk.Entry(age, textvariable=self.since_days_var, width=6).pack(side="left")
        ttk.Label(age, text="nap futásai").pack(side="left", padx=(4, 0))
        self.field(box, 5, "Futások kora:", age, "üresen: az egész szezon; a futás befejezésének ideje számít")
        cache = ttk.Frame(box)
        ttk.Entry(cache, textvariable=self.cache_hours_var, width=6).pack(side="left")
        ttk.Label(cache, text="óráig használja újra").pack(side="left", padx=(4, 0))
        self.field(
            box,
            6,
            "Letöltött adatok:",
            cache,
            "profilok, guildlisták, ranglista-oldalak: a régebbieket újra letölti (0: mindig); a futásokat "
            "sosem tölti le újra",
        )
        flags = ttk.Frame(box)
        flags.grid(row=7, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(flags, text="Csak az időben teljesített futások", variable=self.timed_only_var).pack(side="left")
        ttk.Checkbutton(
            flags,
            text="A korábban letöltött futásokat is beszámolja (a gyorsítótárból, a szűrőkön belül)",
            variable=self.cached_runs_var,
        ).pack(side="left", padx=(16, 0))

        pages = ttk.Frame(box)
        ttk.Entry(pages, textvariable=self.pages_var, width=6).pack(side="left")
        ttk.Label(pages, text="oldal").pack(side="left", padx=(4, 0))
        ttk.Checkbutton(pages, text="Minden dungeon külön", variable=self.each_dungeon_var).pack(
            side="left", padx=(16, 0)
        )
        ttk.Label(pages, text="Affix:").pack(side="left", padx=(16, 4))
        ttk.Entry(pages, textvariable=self.affixes_var, width=20).pack(side="left")
        self.field(box, 8, "Ranglista:", pages)
        key = ttk.Frame(box)
        ttk.Entry(key, textvariable=self.api_key_var, width=34, show="•").pack(side="left")
        ttk.Checkbutton(key, text="Megjegyzés ezen a gépen", variable=self.remember_key_var).pack(
            side="left", padx=(12, 0)
        )
        self.field(box, 9, "Raider.io API-kulcs:", key, "nem kötelező (nagyobb lekérési keret)")

    def _load_keys(self) -> None:
        self.api_key_var.set(self.keys.get("raiderio_api_key") or os.environ.get("RAIDERIO_API_KEY", ""))

    def _source_changed(self) -> None:
        self.follow_var.set(self.follow_by_source[self.source_var.get()].get())

    def _load_options(self) -> None:
        super()._load_options()
        self._source_changed()

    def _build_results(self, parent: tk.Misc) -> None:
        self.progress_var = tk.StringVar()  # a futások, guildek stb. száma
        self.api_var = tk.StringVar()  # az API-kérések és a most futó lépés
        for variable, style in ((self.progress_var, "Strong.TLabel"), (self.api_var, "Hint.TLabel")):
            ttk.Label(parent, textvariable=variable, style=style, wraplength=self.app.px(900), justify="left").pack(
                anchor="w"
            )
        self.table = StatsTable(parent, self.COLUMNS, height=8, stretch_all=True)
        self.table.pack(fill="both", expand=True, pady=(6, 0))

    def has_results(self) -> bool:
        return bool(self.result_rows)

    def _prepare(self, automatic: bool = False):
        region = self.region_var.get()
        guild_mode = self.source_var.get() == "guild"
        args = mplus.build_parser().parse_args([])
        args.region = region
        args.guild = parse_guilds(self.guilds_var.get(), region) if guild_mode else []
        args.follow_guilds = self.follow_var.get()
        args.max_guilds = parse_number(self.max_guilds_var.get(), "Guildek száma", empty=0)
        try:
            args.levels = parse_levels_text(self.levels_var.get())
        except ValueError:
            raise ValueError("A kulcsszinteket pl. 2-10 vagy 18,19,20 alakban add meg.") from None
        args.per_level = parse_number(self.per_level_var.get(), "Futás szintenként", empty=0)
        args.min_ilvl = parse_number(self.min_ilvl_var.get(), "Legkisebb itemlevel", float, empty=0.0)
        args.max_ilvl = parse_number(self.max_ilvl_var.get(), "Legnagyobb itemlevel", float, empty=0.0)
        if args.min_ilvl and args.max_ilvl and args.min_ilvl > args.max_ilvl:
            raise ValueError("Az itemlevel-tartomány alja nem lehet nagyobb a tetejénél.")
        days = parse_number(self.since_days_var.get(), "Futások kora", minimum=1, empty=-1)
        args.since_days = None if days == -1 else days
        args.cache_hours = parse_number(self.cache_hours_var.get(), "Letöltött adatok", float, empty=24.0)
        args.include_untimed = not self.timed_only_var.get()
        args.use_cached_runs = self.cached_runs_var.get()
        args.max_pages = parse_number(self.pages_var.get(), "Ranglista-oldalak", minimum=1, maximum=1000)
        args.each_dungeon = self.each_dungeon_var.get()
        args.affixes = self.affixes_var.get().strip() or "all"
        args.api_key = self.api_key_var.get().strip() or None
        args.cache = str(self.database)
        args.no_live = True
        seeds = mplus.prepare_args(args)
        if not automatic:
            save_api_keys(self.database, {"raiderio_api_key": args.api_key if self.remember_key_var.get() else ""})
        return args, seeds

    def _work(self, job) -> None:
        args, seeds = job
        post = self._post

        def make_view(state, guild_queue, title):
            return _MythicView(state, guild_queue, title, post)

        try:
            reason, state, guild_queue, ilvl_range = mplus.run(
                args, seeds, make_view, info=lambda line: post(("log", line.rstrip()))
            )
        except mplus.Stopped:
            post(("finished", "Leállítva, mielőtt adat érkezett volna.", False))
            return
        except (mplus.StatsError, ValueError) as exc:
            post(("finished", f"Nem sikerült: {exc}", True))
            return
        for line in mplus.summary_lines(state, guild_queue, ilvl_range):
            post(("log", line))
        post(("result", mplus.summary_rows(state)))
        key_note = KEY_REFUSED if mplus.KEY_REJECTED else ""
        if reason and reason.startswith("stopped"):
            post(("finished", "Leállítva – a táblázat az addig összegyűjtött adatokat mutatja." + key_note, False))
        elif reason and reason.startswith("aborted"):
            post(("finished", mplus_abort_text(state.get("abort") or {}) + key_note, True))
        else:
            post(("finished", "Kész" + (f" – {reason}." if reason else ".") + key_note, False))

    def _handle(self, message: tuple) -> None:
        kind = message[0]
        if kind == "live":
            _, rows, progress, api, status, elapsed = message
            self._show_rows(rows)
            self.progress_var.set(f"{elapsed} · {progress}")
            self.api_var.set(api + (f" · most: {status}" if status else ""))
        elif kind == "result":
            self.result_rows = list(message[1])
            self._show_rows(self.result_rows)

    def _show_rows(self, rows) -> None:
        self.result_rows = list(rows)
        self.table.show(
            [(str(r[0]), str(r[1]), str(r[2]), *(format_stat(value) for value in r[3:])) for r in rows]
        )

    def _write_csv(self, path: str) -> None:
        mplus.write_csv(path, self.result_rows)

    def gear_targets(self) -> tuple[dict, str]:
        return gearing.mplus_targets(self.result_rows), gearing.MPLUS_PREFIX


class RaidStatsWindow(StatsWindow):
    """Az aktuális raid bossainak kill-jei itemlevel szerint, a Warcraft Logs adataiból."""

    TITLE = "Raid ilvl statisztika"
    WINDOW_ATTRIBUTE = "raid_stats_window"
    OPTIONS_KEY = "raid"
    CSV_NAME = "raid_ilvl_statisztika.csv"
    module = wcl
    HINT = (
        "A Warcraft Logs adataiból számolja ki, milyen itemlevellel ölik meg az aktuális raid bossait "
        "Normal, Heroic és Mythic nehézségen, bossonként: a kill-ek száma, átlag, medián, 25. percentilis "
        "(P25: a kill-ek negyede ennél kisebb itemlevellel sikerült), minimum és maximum. Egy adatpont egy "
        "kill: a harcban részt vevő játékosok átlagos itemlevele (kérésre a játékosok egyéni itemlevele is). "
        "A Warcraft Logs API-hoz saját kulcs kell: https://www.warcraftlogs.com/api/clients → „Create Client” "
        "(Redirect URL: pl. http://localhost; a „Public Client” ne legyen bepipálva)."
    )
    METRICS = (("raid", "Raid átlag / kill"), ("players", "Játékosok egyéni itemlevele"))
    COLUMNS = (
        ("boss", "Boss", 26),
        ("kills", "Kill", 6),
        ("players", "Játékos", 7),
        ("mean", "Átlag", 7),
        ("median", "Medián", 7),
        ("p25", "P25", 7),
        ("min", "Min", 7),
        ("max", "Max", 7),
    )

    def __init__(self, app, hidden: bool = False) -> None:
        self.result: dict | None = None  # a legutóbbi eredmény (wcl_raid_ilvl_stats.run)
        super().__init__(app, hidden)

    def _build_options(self, parent: tk.Misc) -> None:
        self.client_id_var = tk.StringVar()
        self.client_secret_var = tk.StringVar()
        self.remember_var = tk.BooleanVar(value=True)
        self.zone_var = self.option("zone", "")
        self.days_var = self.option("days", "7")
        self.pages_var = self.option("pages", "100")
        self.page_size_var = self.option("page_size", "50")
        self.region_var = self.option("region", "mind")
        self.exclude_var = self.option("exclude", wcl.DEFAULT_EXCLUDE)
        self.players_var = self.option("players", "0")
        self.refresh_var = self.option("refresh", False, tk.BooleanVar)

        keys = ttk.LabelFrame(parent, text="Warcraft Logs API-kulcs", padding=8)
        keys.pack(fill="x")
        ttk.Label(keys, text="Client ID:").pack(side="left", padx=(0, 8))
        ttk.Entry(keys, textvariable=self.client_id_var, width=38).pack(side="left")
        ttk.Label(keys, text="Client Secret:").pack(side="left", padx=(16, 8))
        ttk.Entry(keys, textvariable=self.client_secret_var, width=38, show="•").pack(side="left")
        ttk.Checkbutton(keys, text="Megjegyzés ezen a gépen", variable=self.remember_var).pack(side="left", padx=(12, 0))

        box = ttk.LabelFrame(parent, text="Lekérdezés", padding=8)
        box.pack(fill="x", pady=(8, 0))
        self.field(
            box,
            0,
            "Raid:",
            ttk.Entry(box, textvariable=self.zone_var, width=30),
            "üresen: a legújabb aktív raid; különben a neve (részlet) vagy a zóna száma",
        )
        sample = ttk.Frame(box)
        ttk.Entry(sample, textvariable=self.days_var, width=6).pack(side="left")
        ttk.Label(sample, text="nap,").pack(side="left", padx=(4, 12))
        ttk.Entry(sample, textvariable=self.pages_var, width=6).pack(side="left")
        ttk.Label(sample, text="report-oldal, oldalanként").pack(side="left", padx=(4, 4))
        ttk.Entry(sample, textvariable=self.page_size_var, width=5).pack(side="left")
        ttk.Label(sample, text="report").pack(side="left", padx=(4, 16))
        ttk.Label(sample, text="Régió:").pack(side="left", padx=(0, 4))
        ttk.Combobox(sample, textvariable=self.region_var, values=WCL_REGIONS, state="readonly", width=7).pack(
            side="left"
        )
        ttk.Label(sample, text="csak ennek a guildjei (a guild nélküli logok kimaradnak)", style="Hint.TLabel").pack(
            side="left", padx=(6, 0)
        )
        self.field(box, 1, "Minta:", sample)
        self.field(
            box,
            2,
            "Kihagyott bossok:",
            ttk.Entry(box, textvariable=self.exclude_var, width=30),
            "névrészletek vesszővel (a raid zónájába sorolt Lair / world bossok)",
        )
        self.field(
            box,
            3,
            "Játékosok:",
            ttk.Entry(box, textvariable=self.players_var, width=6),
            "ennyi kill játékosainak egyéni itemlevele is, bossonként és nehézségenként (0: nem kéri le; "
            "kb. 11 API-pont / kill)",
        )
        ttk.Checkbutton(
            box, text="Minden újra letöltése (a gyorsítótárban lévő adatok helyett)", variable=self.refresh_var
        ).grid(row=4, column=1, columnspan=2, sticky="w", pady=2)

    def _load_keys(self) -> None:
        self.client_id_var.set(self.keys.get("wcl_client_id") or os.environ.get("WCL_CLIENT_ID", ""))
        self.client_secret_var.set(self.keys.get("wcl_client_secret") or os.environ.get("WCL_CLIENT_SECRET", ""))

    def _build_results(self, parent: tk.Misc) -> None:
        self.info_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.info_var, style="Strong.TLabel", wraplength=self.app.px(900), justify="left").pack(
            anchor="w"
        )
        metric = ttk.Frame(parent)
        metric.pack(anchor="w", pady=(4, 0))
        ttk.Label(metric, text="Mérőszám:").pack(side="left", padx=(0, 8))
        self.metric_var = tk.StringVar(value="raid")
        self.metric_buttons = []
        for value, text in self.METRICS:
            button = ttk.Radiobutton(metric, text=text, value=value, variable=self.metric_var, command=self._show_result)
            button.pack(side="left", padx=(0, 12))
            self.metric_buttons.append(button)
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="both", expand=True, pady=(4, 0))
        bold = self.app._fonts[0] if hasattr(self.app, "_fonts") else None
        self.tables = {}
        for difficulty, name in wcl.DIFFICULTIES.items():
            table = StatsTable(self.notebook, self.COLUMNS, height=8, total_font=bold)
            self.notebook.add(table, text=name)
            self.tables[difficulty] = table
        self._show_result()

    def has_results(self) -> bool:
        return bool(self.result and self.result.get("sections"))

    def _prepare(self, automatic: bool = False):
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()
        if not (client_id and client_secret):
            raise MissingApiKey(
                "Add meg a Warcraft Logs API-kulcsot (Client ID és Client Secret). Igénylése: "
                "https://www.warcraftlogs.com/api/clients → „Create Client”."
            )
        args = wcl.build_parser().parse_args([])
        args.client_id, args.client_secret = client_id, client_secret
        zone = self.zone_var.get().strip()
        args.zone_id, args.zone = (int(zone), None) if zone.isdigit() else (None, zone or None)
        args.days = parse_number(self.days_var.get(), "Napok száma", float, minimum=0.01)
        args.pages = parse_number(self.pages_var.get(), "Report-oldalak", minimum=1)
        args.page_size = parse_number(self.page_size_var.get(), "Oldalméret", minimum=1, maximum=100)
        region = self.region_var.get()
        args.region = None if region == "mind" else region
        args.exclude = self.exclude_var.get()
        args.players = parse_number(self.players_var.get(), "Játékosok", empty=0)
        args.refresh = self.refresh_var.get() and not automatic  # hetente ne töltsön le mindent újra
        args.cache = str(self.database)
        if not automatic:
            remember = self.remember_var.get()
            keys = {"wcl_client_id": client_id, "wcl_client_secret": client_secret}
            save_api_keys(self.database, {name: value if remember else "" for name, value in keys.items()})
        return args

    def _work(self, args) -> None:
        post = self._post
        wcl.OUTPUT = lambda line: post(("log", line.rstrip("\n")))
        try:
            cache = wcl.Cache(args.cache, refresh=args.refresh, ttl_hours=args.cache_ttl)
            try:
                result = wcl.run(args, cache)
            finally:
                cache.close()
        except wcl.Stopped:
            post(("finished", "Leállítva, mielőtt adat érkezett volna.", False))
            return
        except (wcl.StatsError, wcl.WCLError) as exc:
            post(("finished", f"Nem sikerült: {' '.join(str(exc).split())}", True))
            return
        finally:
            wcl.OUTPUT = None
        post(("result", result))
        if wcl.STOP.is_set():
            post(("finished", "Leállítva – a táblázat az addig letöltött adatokból készült.", False))
        else:
            post(("finished", "Kész.", False))

    def _handle(self, message: tuple) -> None:
        if message[0] == "result":
            self.result = message[1]
            has_players = any(metric == "játékos egyéni" for metric, _tables in self.result.get("sections", []))
            if not has_players:
                self.metric_var.set("raid")
            self.metric_buttons[1].state(["!disabled" if has_players else "disabled"])
            zone = self.result.get("zone") or {}
            counts = self.result.get("per_difficulty") or {}
            per_difficulty = ", ".join(f"{name}: {counts.get(d, 0)}" for d, name in wcl.DIFFICULTIES.items())
            self.info_var.set(
                f"{zone.get('name', '?')} · kill-ek (a duplikált logok nélkül): {self.result.get('kills', 0)} · "
                f"{per_difficulty}"
            )
            self._show_result()

    def _show_result(self) -> None:
        players = self.metric_var.get() == "players"
        sections = dict(self.result.get("sections", [])) if self.result else {}
        tables = sections.get("játékos egyéni" if players else "raid átlag / kill") or {}
        shown = [c[0] for c in self.COLUMNS if players or c[0] != "players"]
        for difficulty, table in self.tables.items():
            table.tree.configure(displaycolumns=shown)
            rows = []
            for name, counts, stats in tables.get(difficulty, []):
                values = [name, str(counts[0]), str(counts[1]) if len(counts) > 1 else ""]
                values += [format_stat(stats[key]) if stats else "–" for key in wcl.STAT_KEYS]
                rows.append(values)
            table.show(rows, totals=1 if rows else 0)
        if not self.result:
            self.metric_buttons[1].state(["disabled"])

    def _write_csv(self, path: str) -> None:
        wcl.write_csv(path, self.result["sections"])

    def gear_targets(self) -> tuple[dict, str]:
        return gearing.raid_targets(self.result["sections"]), gearing.RAID_PREFIX
