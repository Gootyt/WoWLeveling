"""WoW szintezés – a telefonos alkalmazás (Kivy).

A gépi program (wow_leveling.py) párja: ugyanazt a tervet mutatja és szerkeszti (a karakterek a
mai céljukkal és a lemaradásukkal szintben, itemlevelben és Mythic+ pontszámban, tetszés szerint
rendezve; új karakter, szerkesztés, törlés, sorrend; a terv beállításai), és a gépi programmal a
felhasználó saját Firebase-adatbázisán át szinkronizál (cloud_sync.py). A számolás a gépi programé
(leveling.py), a felülettől független rész a mobile_plan.py-ban van.

Az adatok a telefonon is egy SQLite-adatbázisban vannak (storage.py), így internet nélkül is
használható; a változások a következő szinkronizáláskor mennek fel.
"""

from __future__ import annotations

import os
import ssl
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if (ROOT / "leveling.py").exists():  # a repóból futtatva (pl. kipróbáláshoz a gépen) a közös modulok ott vannak
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("KIVY_NO_ARGS", "1")

try:  # Androidon az OpenSSL nem látja a rendszer tanúsítványait: a certifi csomagé kell
    import certifi

    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
except ImportError:
    pass

from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.lang import Builder  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.properties import ListProperty, StringProperty  # noqa: E402
from kivy.uix.behaviors import ButtonBehavior  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.button import Button  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.popup import Popup  # noqa: E402
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager  # noqa: E402

import cloud_sync  # noqa: E402
import mobile_plan  # noqa: E402
import storage  # noqa: E402
from leveling import PARALLEL, REGIONS, SEQUENTIAL, LevelingData, Settings, load_data, save_data  # noqa: E402

DEVICE = "Telefon"
_kv_loaded = False
ACCOUNT_HINT = (
    "A telefon és a gépi program a saját (ingyenes) Firebase-projekteden keresztül szinkronizál. Ugyanazt "
    "a Web API-kulcsot, adatbázist és fiókot add meg, mint a gépen (a gépi programban a „Telefonos "
    "alkalmazás” keret „Beállítás…” gombjával). A projekt létrehozását a README „Szinkronizálás a "
    "telefonnal” része írja le."
)

KV = """
#:import dp kivy.metrics.dp

<Label>:
    font_size: '15sp'

<Button>:
    font_size: '15sp'
    size_hint_y: None
    height: dp(46)

<TextInput>:
    font_size: '16sp'
    multiline: False
    write_tab: False
    size_hint_y: None
    height: dp(44)

<Spinner>:
    size_hint_y: None
    height: dp(44)

<ToggleButton>:
    size_hint_y: None
    height: dp(44)

<WrapLabel@Label>:
    size_hint_y: None
    text_size: self.width, None
    height: self.texture_size[1] + dp(4)
    halign: 'left'
    valign: 'middle'

<FormLabel@WrapLabel>:
    color: 0.72, 0.74, 0.8, 1
    font_size: '14sp'

<Card>:
    orientation: 'vertical'
    size_hint_y: None
    height: self.minimum_height
    padding: dp(12), dp(8)
    spacing: dp(1)
    canvas.before:
        Color:
            rgba: (0.24, 0.25, 0.3, 1) if self.state == 'down' else (0.15, 0.16, 0.2, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]
    WrapLabel:
        text: root.title
        bold: True
        font_size: '17sp'
    WrapLabel:
        text: root.subtitle
        color: 0.7, 0.72, 0.78, 1
        font_size: '13sp'
        height: (self.texture_size[1] + dp(2)) if root.subtitle else 0
    WrapLabel:
        text: root.level
        color: root.tone
    WrapLabel:
        text: root.status
        color: root.tone
        font_size: '13sp'
    WrapLabel:
        text: root.gear
        color: root.gear_tone
        font_size: '14sp'
        height: (self.texture_size[1] + dp(2)) if root.gear else 0
    WrapLabel:
        text: root.mplus
        color: root.mplus_tone
        font_size: '14sp'
        height: (self.texture_size[1] + dp(2)) if root.mplus else 0

<TopBar@BoxLayout>:
    size_hint_y: None
    height: dp(52)
    padding: dp(6)
    spacing: dp(6)
    canvas.before:
        Color:
            rgba: 0.1, 0.11, 0.14, 1
        Rectangle:
            pos: self.pos
            size: self.size

<ListScreen>:
    BoxLayout:
        orientation: 'vertical'
        TopBar:
            Label:
                text: 'WoW szintezés'
                bold: True
                font_size: '18sp'
                halign: 'left'
                text_size: self.size
                valign: 'middle'
            Button:
                text: 'Szinkron'
                size_hint_x: None
                width: dp(92)
                on_release: app.sync_now()
            Button:
                text: 'Terv'
                size_hint_x: None
                width: dp(64)
                on_release: app.open_plan()
            Button:
                text: 'Fiók'
                size_hint_x: None
                width: dp(64)
                on_release: app.open_account()
        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            padding: dp(10), dp(6)
            WrapLabel:
                id: status
                font_size: '13sp'
                color: app.status_color
                text: app.status_text
            WrapLabel:
                id: summary
                font_size: '14sp'
            BoxLayout:
                size_hint_y: None
                height: dp(44)
                spacing: dp(6)
                Label:
                    text: 'Rendezés:'
                    font_size: '14sp'
                    color: 0.72, 0.74, 0.8, 1
                    size_hint_x: None
                    width: self.texture_size[0] + dp(2)
                Spinner:
                    id: sort
                ToggleButton:
                    id: reverse
                    text: 'Fordítva'
                    size_hint_x: None
                    width: dp(92)
        ScrollView:
            id: scroll
            do_scroll_x: False
            GridLayout:
                id: cards
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                padding: dp(8)
                spacing: dp(8)
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            padding: dp(6)
            Button:
                text: '+ Új karakter'
                on_release: app.edit_character(None)

<FormScreen>:
    BoxLayout:
        orientation: 'vertical'
        TopBar:
            Label:
                id: title
                bold: True
                font_size: '18sp'
                halign: 'left'
                text_size: self.size
                valign: 'middle'
            Button:
                text: 'Vissza'
                size_hint_x: None
                width: dp(84)
                on_release: app.show_list()
        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: form
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                padding: dp(12)
                spacing: dp(6)
"""


class Card(ButtonBehavior, BoxLayout):
    """Egy karakter a listában; koppintásra a szerkesztője nyílik meg. (A karakter azonosítója nem
    lehet uid: az a Kivy saját azonosítója minden widgetnél.)"""

    character_id = StringProperty("")
    title = StringProperty("")
    subtitle = StringProperty("")
    level = StringProperty("")
    status = StringProperty("")
    tone = ListProperty([1, 1, 1, 1])
    gear = StringProperty("")
    gear_tone = ListProperty([1, 1, 1, 1])
    mplus = StringProperty("")
    mplus_tone = ListProperty([1, 1, 1, 1])

    def on_release(self):
        App.get_running_app().edit_character(self.character_id)


class ListScreen(Screen):
    pass


class FormScreen(Screen):
    """Egy űrlap (a karakteré, a terv beállításai vagy a fiók) címmel és Vissza gombbal."""

    def clear(self, title: str):
        self.ids.title.text = title
        self.ids.form.clear_widgets()
        return self.ids.form


def wrap_label(text: str = "", **options) -> Label:
    """Egy több sorba törő felirat, amely annyi helyet foglal, amennyi a szövegének kell (üresen semennyit)."""
    label = Label(text=text, size_hint_y=None, halign="left", valign="middle", **options)

    def fit(widget, _value=None):
        widget.height = widget.texture_size[1] + dp(6) if widget.text else 0

    label.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)))
    label.bind(texture_size=fit, text=fit)
    fit(label)
    return label


def form_label(text: str) -> Label:
    return wrap_label(text, color=(0.72, 0.74, 0.8, 1), font_size="14sp")


def button_row(*buttons) -> BoxLayout:
    row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
    for button in buttons:
        row.add_widget(button)
    return row


class WowApp(App):
    """Az alkalmazás: a helyi adatok, a képernyők és a szinkronizálás."""

    status_text = StringProperty("")
    status_color = ListProperty([0.7, 0.72, 0.78, 1])

    def __init__(self, database: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        self._database = database
        self.today = date.today()
        self.account_status = None  # a fiók képernyőjének állapotsora, ha már megnyitották

    @property
    def database(self) -> Path:
        return self._database or Path(self.user_data_dir) / storage.DB_NAME

    # --- indulás és leállás

    def build(self):
        global _kv_loaded
        self.title = "WoW szintezés"
        if not _kv_loaded:  # egyszer elég (a tesztek több alkalmazást is indítanak)
            Builder.load_string(KV)
            _kv_loaded = True
        Window.softinput_mode = "below_target"  # a billentyűzet ne takarja el a mezőt
        Window.bind(on_keyboard=self._on_key)
        self.data = self._load()
        self.list_sort = mobile_plan.load_sort(self.database)  # (kulcs, fordítva-e); csak ezen a telefonon
        self.manager = ScreenManager(transition=NoTransition())
        self.list_screen = ListScreen(name="list")
        self.form_screen = FormScreen(name="form")
        self.manager.add_widget(self.list_screen)
        self.manager.add_widget(self.form_screen)
        ids = self.list_screen.ids
        ids.sort.values = list(mobile_plan.SORTS.values())
        ids.sort.text = mobile_plan.SORTS[self.list_sort[0]]
        ids.reverse.state = "down" if self.list_sort[1] else "normal"
        ids.sort.bind(text=self._sort_changed)  # a kezdőértékek után: azok még nem változtatások
        ids.reverse.bind(state=self._sort_changed)
        self.sync = cloud_sync.SyncController(
            self.database,
            DEVICE,
            lambda: self.data,
            self._remote_changed,
            self._sync_status,
            self._ask_choice,
            lambda ms, function: Clock.schedule_once(lambda _dt: function(), ms / 1000),
            where="a „Fiók” gombbal",
        )
        Clock.schedule_interval(self._check_day, 60)
        self.refresh()
        return self.manager

    def _load(self) -> LevelingData:
        try:
            return load_data(self.database)
        except FileNotFoundError:
            return LevelingData(Settings.default())
        except (OSError, ValueError):  # sérült helyi adat: a felhőből úgyis visszajön
            return LevelingData(Settings.default())

    def on_pause(self):
        self.save(push=False)
        return True

    def on_resume(self):
        self._check_day()
        self.sync.sync_now(automatic=True)

    def on_stop(self):
        self.save(push=False)
        self.sync.close()

    def save(self, push: bool = True) -> None:
        try:
            save_data(self.database, self.data)
        except OSError as exc:
            self._sync_status(f"⚠ Nem sikerült menteni: {exc}", True)
            return
        if push:
            self.sync.local_changed()

    def _check_day(self, *_args) -> None:
        if date.today() != self.today:
            self.today = date.today()
            self.refresh()

    def _on_key(self, _window, key, *_args):
        if key == 27 and self.manager.current != "list":  # az Android vissza gombja
            self.show_list()
            return True
        return False

    # --- a lista

    def refresh(self) -> None:
        screen = self.list_screen
        screen.ids.summary.text = mobile_plan.summary(self.data, self.today)
        container = screen.ids.cards
        container.clear_widgets()
        for card in mobile_plan.cards(self.data, self.today, *self.list_sort):
            container.add_widget(
                Card(
                    character_id=card.uid,
                    title=card.title,
                    subtitle=card.subtitle,
                    level=card.level,
                    status=card.status,
                    tone=card.tone,
                    gear=card.gear,
                    gear_tone=card.gear_tone,
                    mplus=card.mplus,
                    mplus_tone=card.mplus_tone,
                )
            )

    def _sort_changed(self, *_args) -> None:
        ids = self.list_screen.ids
        sort = next((key for key, label in mobile_plan.SORTS.items() if label == ids.sort.text), self.list_sort[0])
        self.list_sort = (sort, ids.reverse.state == "down")
        try:
            mobile_plan.save_sort(self.database, *self.list_sort)
        except OSError as exc:  # a rendezés így is érvényes, csak a következő indításkor nem lesz meg
            self._sync_status(f"⚠ Nem sikerült menteni a rendezést: {exc}", True)
        self.refresh()
        ids.scroll.scroll_y = 1  # az új sorrend eleje látsszon

    def show_list(self) -> None:
        self.manager.current = "list"
        self.refresh()

    def sync_now(self) -> None:
        if not self.sync.account.signed_in:
            self.open_account()
            return
        self.sync.sync_now()

    # --- a karakter szerkesztése

    def edit_character(self, uid: str | None) -> None:
        from kivy.uix.spinner import Spinner
        from kivy.uix.textinput import TextInput

        character = mobile_plan.find(self.data, uid)
        if uid is not None and character is None:
            self.show_list()
            return
        form = self.form_screen.clear("Új karakter" if character is None else character.name)
        values = mobile_plan.character_form(character)
        fields = {}

        def text_field(key, label, hint="", input_type="text"):
            form.add_widget(form_label(label))
            field = TextInput(text=values[key], hint_text=hint, input_type=input_type)
            form.add_widget(field)
            fields[key] = field

        text_field("name", "Név (kötelező)")
        text_field("realm", "Realm")
        form.add_widget(form_label("Kaszt"))
        class_box = Spinner(text=values["class"], values=mobile_plan.CLASSES)
        form.add_widget(class_box)
        form.add_widget(form_label("Spec"))
        spec_box = Spinner(text=values["spec"], values=mobile_plan.spec_choices(values["class"]))
        form.add_widget(spec_box)

        def class_changed(_box, char_class):
            spec_box.values = mobile_plan.spec_choices(char_class)
            if spec_box.text not in spec_box.values:
                spec_box.text = ""

        class_box.bind(text=class_changed)
        form.add_widget(form_label("Faj"))
        race_box = Spinner(text=values["race"], values=mobile_plan.RACES)
        form.add_widget(race_box)
        text_field("level", "Szint (két tizedes: 83,45)", hint="üresen: a kezdőszint", input_type="number")
        text_field("item_level", "Itemlevel", hint="nem kötelező", input_type="number")
        text_field("score", "Mythic+ (Raider.io) pontszám", hint="nem kötelező", input_type="number")
        message = wrap_label(color=mobile_plan.BAD)
        form.add_widget(message)
        self.message = message  # a hibák (a tesztek is innen olvassák)

        def save(*_args):
            entered = {key: field.text for key, field in fields.items()}
            entered.update({"class": class_box.text, "spec": spec_box.text, "race": race_box.text})
            try:
                mobile_plan.save_character(self.data, uid, entered)
            except ValueError as exc:
                message.text = str(exc)
                return
            self.save()
            self.show_list()

        buttons = [Button(text="Mentés", on_release=save)]
        form.add_widget(button_row(*buttons, Button(text="Mégse", on_release=lambda *_: self.show_list())))
        if character is not None:

            def move(offset):
                if mobile_plan.move_character(self.data, uid, offset):
                    self.save()
                    self.show_list()

            hint = mobile_plan.move_hint(*self.list_sort)  # más rendezésben nem látszana, hová került
            form.add_widget(
                button_row(
                    Button(text="Feljebb", disabled=bool(hint), on_release=lambda *_: move(-1)),
                    Button(text="Lejjebb", disabled=bool(hint), on_release=lambda *_: move(1)),
                    Button(text="Törlés", on_release=lambda *_: self._confirm_delete(character)),
                )
            )
            if hint:
                form.add_widget(form_label(hint))
        self.manager.current = "form"
        self.fields = fields  # a tesztekhez

    def _confirm_delete(self, character) -> None:
        content = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        content.add_widget(wrap_label(f"Biztosan törlöd: {character.name}? A gépen is törlődik."))
        popup = Popup(title="Törlés", content=content, size_hint=(0.9, None), height=dp(220), auto_dismiss=True)

        def delete(*_args):
            popup.dismiss()
            mobile_plan.delete_character(self.data, character.uid)
            self.save()
            self.show_list()

        content.add_widget(
            button_row(Button(text="Törlés", on_release=delete), Button(text="Mégse", on_release=lambda *_: popup.dismiss()))
        )
        popup.open()
        self.popup = popup

    # --- a terv beállításai

    def open_plan(self) -> None:
        from kivy.uix.checkbox import CheckBox
        from kivy.uix.spinner import Spinner
        from kivy.uix.textinput import TextInput
        from kivy.uix.togglebutton import ToggleButton

        form = self.form_screen.clear("A terv beállításai")
        values = mobile_plan.settings_form(self.data)
        fields = {}
        for key, label, hint in (
            ("start_date", "Szintezés kezdete", "ÉÉÉÉ-HH-NN"),
            ("first_target_date", "Első karakter célszinten", "ÉÉÉÉ-HH-NN"),
            ("last_target_date", "Utolsó karakter célszinten", "ÉÉÉÉ-HH-NN"),
            ("start_level", "Kezdőszint", ""),
            ("target_level", "Célszint", ""),
            ("target_item_level", "Célitemlevel", "nem kötelező (pl. 326,55)"),
        ):
            form.add_widget(form_label(label))
            field = TextInput(text=values[key], hint_text=hint)
            form.add_widget(field)
            fields[key] = field
        form.add_widget(form_label("Régió (a Raider.io-lekéréshez)"))
        region_box = Spinner(text=values["region"], values=[region.upper() for region in REGIONS])
        form.add_widget(region_box)
        form.add_widget(form_label("Ütemezés"))
        parallel = ToggleButton(text="Párhuzamosan", group="mode", state="down" if values["mode"] == PARALLEL else "normal")
        sequential = ToggleButton(text="Egymás után", group="mode", state="down" if values["mode"] == SEQUENTIAL else "normal")
        form.add_widget(button_row(parallel, sequential))
        look_ahead_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        look_ahead = CheckBox(active=values["look_ahead"], size_hint_x=None, width=dp(40))
        look_ahead_row.add_widget(look_ahead)
        look_ahead_row.add_widget(wrap_label("Ha a mai célt mindenki teljesítette, a következő nap céljait mutassa"))
        form.add_widget(look_ahead_row)
        message = wrap_label(color=mobile_plan.BAD)
        form.add_widget(message)
        self.message = message  # a hibák (a tesztek is innen olvassák)

        def save(*_args):
            entered = {key: field.text for key, field in fields.items()}
            entered.update(
                region=region_box.text,
                mode=SEQUENTIAL if sequential.state == "down" else PARALLEL,
                look_ahead=look_ahead.active,
            )
            try:
                mobile_plan.save_settings(self.data, entered)
            except ValueError as exc:
                message.text = str(exc)
                return
            self.save()
            self.show_list()

        form.add_widget(button_row(Button(text="Mentés", on_release=save), Button(text="Mégse", on_release=lambda *_: self.show_list())))
        self.manager.current = "form"
        self.fields = fields

    # --- a Firebase-fiók

    def open_account(self) -> None:
        from kivy.uix.textinput import TextInput

        form = self.form_screen.clear("Szinkronizálás (Firebase)")
        account = self.sync.account
        form.add_widget(wrap_label(ACCOUNT_HINT, color=(0.72, 0.74, 0.8, 1), font_size="14sp"))
        fields = {}
        for key, label, value, options in (
            ("api_key", "Web API-kulcs", account.api_key, {}),
            ("database_url", "Adatbázis címe", account.database_url, {"hint_text": "https://…firebasedatabase.app"}),
            ("email", "E-mail-cím", account.email, {"input_type": "mail"}),
            ("password", "Jelszó", "", {"password": True}),
        ):
            form.add_widget(form_label(label))
            field = TextInput(text=value, **options)
            form.add_widget(field)
            fields[key] = field
        message = wrap_label(color=mobile_plan.BAD)
        form.add_widget(message)
        self.message = message  # a hibák (a tesztek is innen olvassák)

        def sign_in(create):
            try:
                self.sync.sign_in(
                    fields["api_key"].text, fields["database_url"].text, fields["email"].text, fields["password"].text, create
                )
            except ValueError as exc:
                message.text = str(exc)
                return
            message.text = ""
            fields["password"].text = ""

        def sign_out(*_args):
            try:
                self.sync.sign_out()
            except ValueError as exc:
                message.text = str(exc)

        form.add_widget(
            button_row(
                Button(text="Bejelentkezés", on_release=lambda *_: sign_in(False)),
                Button(text="Új fiók", on_release=lambda *_: sign_in(True)),
            )
        )
        form.add_widget(button_row(Button(text="Kijelentkezés", on_release=sign_out)))
        self.account_status = wrap_label(font_size="14sp")
        form.add_widget(self.account_status)
        self._show_account_status(self.status_text, self.status_color == list(mobile_plan.BAD))
        self.manager.current = "form"
        self.fields = fields

    # --- a szinkronizálás eseményei (a felület szálán)

    def _remote_changed(self) -> None:
        self.save(push=False)
        if self.manager.current == "list":
            self.refresh()

    def _sync_status(self, text: str, problem: bool) -> None:
        text = text.replace("⚠ ", "")  # a Kivy betűkészletében nincs ilyen jel; a piros szín jelzi
        self.status_text = text
        self.status_color = list(mobile_plan.BAD if problem else (0.7, 0.72, 0.78, 1))
        if self.account_status is not None:  # a fiók képernyőjén is
            self._show_account_status(text, problem)

    def _show_account_status(self, text: str, problem: bool) -> None:
        account = self.sync.account
        if not problem and not account.signed_in:  # itt a „Fiók gombbal…” tanács nem segít
            text = (
                "Jelentkezz be a fiókoddal (ugyanazzal, mint a gépen), vagy hozz létre egyet."
                if account.configured
                else "Add meg a Firebase-projekted Web API-kulcsát és az adatbázis címét, majd jelentkezz be."
            )
        self.account_status.text = text
        self.account_status.color = mobile_plan.BAD if problem else (0.7, 0.72, 0.78, 1)

    def _ask_choice(self, question: str, answer) -> None:
        content = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        content.add_widget(wrap_label(question))
        popup = Popup(title="Melyik terv maradjon?", content=content, size_hint=(0.95, None), height=dp(420), auto_dismiss=False)

        def choose(choice):
            popup.dismiss()
            answer(choice)
            self.refresh()

        content.add_widget(Button(text="A felhőbeli maradjon", on_release=lambda *_: choose("remote")))
        content.add_widget(Button(text="Az itteni maradjon", on_release=lambda *_: choose("local")))
        content.add_widget(Button(text="Most ne", on_release=lambda *_: choose(None)))
        popup.open()
        self.popup = popup


if __name__ == "__main__":
    WowApp().run()
