"""A telefonos szinkronizálás ablakai a gépi programban (a szinkronizálás maga a cloud_sync.py-ban
van): a Firebase-fiók beállítása (AccountDialog), és az első szinkronizáláskor a kérdés, melyik terv
maradjon meg (ChoiceDialog)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

ACCOUNT_TITLE = "Telefonos szinkronizálás (Firebase)"
ACCOUNT_HINT = (
    "A telefonos alkalmazás és ez a program a saját (ingyenes) Firebase-projekteden keresztül szinkronizál: "
    "a terv (a beállítások és a karakterek) a felhőben is megvan, és mindkettő átveszi a másik "
    "változtatásait. A projekt létrehozását a README „Szinkronizálás a telefonnal” része írja le. Itt és "
    "a telefonon is ugyanazt a Web API-kulcsot, adatbázist és fiókot add meg."
)
URL_HINT = "pl. https://valami-default-rtdb.europe-west1.firebasedatabase.app"


class AccountDialog(tk.Toplevel):
    """A Firebase-projekt adatai és a bejelentkezés. A jelszót nem tárolja: a bejelentkezés után
    csak egy hosszú lejáratú token marad meg (a program adatbázisában)."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title(f"{ACCOUNT_TITLE} – {app.root.title()}")
        self.transient(app.root)
        self.resizable(False, False)
        account = app.cloud.account
        self.api_key_var = tk.StringVar(value=account.api_key)
        self.url_var = tk.StringVar(value=account.database_url)
        self.email_var = tk.StringVar(value=account.email)
        self.password_var = tk.StringVar()
        self.message_var = tk.StringVar()

        body = ttk.Frame(self, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text=ACCOUNT_HINT, style="Hint.TLabel", wraplength=app.px(560), justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        fields = (
            ("Web API-kulcs:", self.api_key_var, {}),
            ("Adatbázis címe:", self.url_var, {}),
            ("E-mail-cím:", self.email_var, {}),
            ("Jelszó:", self.password_var, {"show": "•"}),
        )
        self.entries = {}
        row = 1
        for text, variable, options in fields:
            ttk.Label(body, text=text).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            entry = ttk.Entry(body, textvariable=variable, width=54, **options)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self.entries[text] = entry
            row += 1
            if text == "Adatbázis címe:":
                ttk.Label(body, text=URL_HINT, style="Hint.TLabel").grid(row=row, column=1, sticky="w")
                row += 1
        buttons = ttk.Frame(body)
        buttons.grid(row=row, column=1, sticky="w", pady=(8, 0))
        self.sign_in_button = ttk.Button(buttons, text="Bejelentkezés", command=self.sign_in)
        self.sign_in_button.pack(side="left")
        self.create_button = ttk.Button(buttons, text="Új fiók létrehozása", command=lambda: self.sign_in(create=True))
        self.create_button.pack(side="left", padx=(6, 0))
        self.sign_out_button = ttk.Button(buttons, text="Kijelentkezés", command=self.sign_out)
        self.sign_out_button.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Bezárás", command=self.close).pack(side="left", padx=(6, 0))
        self.status_label = ttk.Label(body, textvariable=self.message_var, wraplength=app.px(560), justify="left")
        self.status_label.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Return>", lambda _event: self.sign_in())
        self.bind("<Escape>", lambda _event: self.close())
        self.show_status(*app.cloud.status)
        first = next((entry for entry in self.entries.values() if not entry.get()), self.entries["Jelszó:"])
        first.focus_set()

    def sign_in(self, create: bool = False) -> None:
        try:
            self.app.cloud.sign_in(
                self.api_key_var.get(), self.url_var.get(), self.email_var.get(), self.password_var.get(), create
            )
        except ValueError as exc:
            self.show_status(f"⚠ {exc}", True)
            return
        self.password_var.set("")

    def sign_out(self) -> None:
        try:
            self.app.cloud.sign_out()
        except ValueError as exc:
            self.show_status(f"⚠ {exc}", True)

    def show_status(self, text: str, problem: bool) -> None:
        account = self.app.cloud.account
        if not problem and not account.signed_in:  # itt a főablak „Beállítás…” tanácsa nem segít
            text = (
                "Jelentkezz be a fiókoddal, vagy hozz létre egyet (az e-mail-cím és a jelszó kell hozzá, a "
                "telefonon ugyanezzel jelentkezz be)."
                if account.configured or self.api_key_var.get()
                else "Add meg a Firebase-projekted Web API-kulcsát és az adatbázis címét, majd jelentkezz be."
            )
        self.message_var.set(text)
        self.status_label.configure(style="Error.TLabel" if problem else "Hint.TLabel")
        self.sign_out_button.state(["!disabled" if self.app.cloud.account.signed_in else "disabled"])

    def close(self) -> None:
        self.app.cloud_dialog = None
        self.destroy()


class ChoiceDialog(tk.Toplevel):
    """Az első szinkronizáláskor, ha a felhőben is és itt is van terv: melyik maradjon meg."""

    def __init__(self, app, question: str, answer):
        super().__init__(app.root)
        self.app = app
        self.question = question
        self._answer = answer
        self.title(f"Melyik terv maradjon? – {app.root.title()}")
        self.transient(app.root)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        ttk.Label(body, text=question, wraplength=app.px(480), justify="left").grid(row=0, column=0, sticky="w")
        ttk.Label(
            body,
            text="Ha a felhőbelit választod, az itteni terv egy másolatát a program mappájába menti.",
            style="Hint.TLabel",
            wraplength=app.px(480),
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, sticky="e", pady=(12, 0))
        self.remote_button = ttk.Button(buttons, text="A felhőbeli maradjon", command=lambda: self.choose("remote"))
        self.remote_button.pack(side="left")
        self.local_button = ttk.Button(buttons, text="Az itteni maradjon", command=lambda: self.choose("local"))
        self.local_button.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Most ne", command=lambda: self.choose(None)).pack(side="left", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", lambda: self.choose(None))
        self.bind("<Escape>", lambda _event: self.choose(None))
        self.remote_button.focus_set()

    def choose(self, choice: str | None) -> None:
        self.app.cloud_choice = None
        self.destroy()
        self._answer(choice)
