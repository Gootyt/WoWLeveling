"""World of Warcraft karakterek szintezésének ütemezése.

Ez a modul tartalmazza a program logikáját (beállítások, karakterek,
ütemterv-számítás, mentés és betöltés). A grafikus felülettől független,
így önállóan is tesztelhető.

Az ütemezés szabályai:

* A terv szerint minden karakter a kezdőszintről indul, és a céldátumáig el
  kell érnie a célszintet. A karakterek tényleges szintje ettől eltérhet: lehet
  a kezdőszint alatt vagy a célszint felett is.
* A szintek két tizedesjegy pontosságúak (pl. 83,45: 83-as szint, a következő
  szinthez szükséges tapasztalat 45%-a megvan).
* A karakterek céldátumai a lista sorrendjében, egyenletesen oszlanak el az
  első és az utolsó karakter céldátuma között.
* Párhuzamos ütemezésnél minden karakter a közös kezdő napon kezd, egymás
  utáni ütemezésnél pedig mindegyik az előző karakter céldátumát követő napon.
* A karakter a kezdőnapjától a céldátumáig (mindkét napot beleértve)
  egyenletes tempóban szintez; a „mai cél” az a szint, amelyet a mai nap
  végéig el kell érni.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from pathlib import Path

LEVEL_STEP = Decimal("0.01")  # a szintek két tizedesjegy pontosságúak
RAIDERIO_STEP = Decimal("0.1")  # a Raider.io pontszám egy tizedesjegyű (pl. 2543,7)
RAIDERIO_MAX = Decimal("99999.9")
ITEM_LEVEL_STEP = Decimal("0.01")  # az itemlevel két tizedesjegyű (pl. 326,55)
ITEM_LEVEL_MAX = Decimal("9999.99")
LEVEL_MIN = Decimal("1.00")
LEVEL_MAX = Decimal("999.99")
DEFAULT_START_LEVEL = Decimal("1.00")
DEFAULT_TARGET_LEVEL = Decimal("90.00")

PARALLEL = "parallel"  # minden karakter a közös kezdő naptól szintez
SEQUENTIAL = "sequential"  # a karakterek egymás után következnek
MODES = (PARALLEL, SEQUENTIAL)

DATA_VERSION = 2

_DATE_PATTERN = re.compile(r"\s*(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\s*\.?\s*")
_LEVEL_PATTERN = re.compile(r"(\d+)(?:[.,](\d+))?")


def parse_date(text: str) -> date:
    """Dátum beolvasása ÉÉÉÉ-HH-NN, ÉÉÉÉ.HH.NN. vagy ÉÉÉÉ/HH/NN alakban."""
    text = text.strip()
    if not text:
        raise ValueError("Hiányzik a dátum.")
    match = _DATE_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(
            f"„{text}” nem érvényes dátum – használd az ÉÉÉÉ-HH-NN formátumot (pl. 2026-10-15)."
        )
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        raise ValueError(f"„{text}” nem létező dátum.") from None


def format_date(value: date) -> str:
    return value.isoformat()


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


def goal_day_phrase(goal_day: date, today: date) -> str:
    """A célnap megnevezése névelővel: „a mai”, „a holnapi”, „a holnaputáni”, „az október 18-i”."""
    offset = (goal_day - today).days
    if 0 <= offset <= 2:
        return ("a mai", "a holnapi", "a holnaputáni")[offset]
    month = HU_MONTHS[goal_day.month - 1]
    return f"{'az' if month[0] in 'aáeéiíoóöőuúüű' else 'a'} {month} {goal_day.day}-i"


def parse_level(text: str) -> Decimal:
    """Szint beolvasása legfeljebb két tizedesjeggyel; tizedesvessző és -pont is jó."""
    text = text.strip()
    if not text:
        raise ValueError("Hiányzik a szint.")
    match = _LEVEL_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"„{text}” nem érvényes szint (példa: 83,45).")
    decimals = match.group(2)
    if decimals is not None and len(decimals) > 2:
        raise ValueError(f"„{text}”: a szint legfeljebb két tizedesjegyű lehet.")
    value = Decimal(text.replace(",", "."))
    if not LEVEL_MIN <= value <= LEVEL_MAX:
        raise ValueError(f"A szint {format_level(LEVEL_MIN)} és {format_level(LEVEL_MAX)} között lehet.")
    return value.quantize(LEVEL_STEP)


def format_level(value: Decimal) -> str:
    """Szint vagy szintkülönbség két tizedesjeggyel, tizedesvesszővel (pl. 83,45)."""
    return f"{value:.2f}".replace(".", ",")


def format_deviation(value: Decimal) -> str:
    """Előjeles szinteltérés: +2,87, −2,13 vagy 0,00."""
    if value > 0:
        return "+" + format_level(value)
    if value < 0:
        return "−" + format_level(-value)
    return format_level(abs(value))


_DECIMAL_COUNT_WORDS = {1: "egy", 2: "két"}


def _decimal_places(step: Decimal) -> int:
    """A lépésköz tizedesjegyeinek száma (0,1: 1, 0,01: 2)."""
    return -step.as_tuple().exponent


def _format_decimal(value: Decimal, step: Decimal) -> str:
    """Szám a lépésközének megfelelő számú tizedesjeggyel, tizedesvesszővel."""
    return f"{value:.{_decimal_places(step)}f}".replace(".", ",")


def _parse_decimal(text: str, name: str, example: str, maximum: Decimal, step: Decimal) -> Decimal | None:
    """Nem negatív szám beolvasása legfeljebb annyi tizedesjeggyel, amennyit a `step`
    lépésköz megenged; üres szövegnél None.

    Tizedesvessző és -pont is jó; ha mindkettő szerepel (pl. a weboldalról másolt
    „2,543.7”), a hátrébb álló a tizedesjel, a másik ezres elválasztó.
    """
    original = text.strip()
    text = original.replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if "," in text and "." in text:
        thousands = "." if text.rfind(",") > text.rfind(".") else ","
        text = text.replace(thousands, "")
    article = "az" if name[0].lower() in "aáeéiíoóöőuúüű" else "a"
    match = _LEVEL_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"„{original}” nem érvényes {name} (példa: {example}).")
    places = _decimal_places(step)
    decimals = match.group(2)
    if decimals is not None and len(decimals) > places:
        words = _DECIMAL_COUNT_WORDS[places]
        raise ValueError(f"„{original}”: {article} {name} legfeljebb {words} tizedesjegyű lehet.")
    value = Decimal(text.replace(",", "."))
    if value > maximum:
        raise ValueError(f"{article.capitalize()} {name} legfeljebb {_format_decimal(maximum, step)} lehet.")
    return value.quantize(step)


def parse_raiderio_score(text: str) -> Decimal | None:
    """Raider.io pontszám beolvasása legfeljebb egy tizedesjeggyel; üres szövegnél None."""
    return _parse_decimal(text, "Raider.io pontszám", "2543,7", RAIDERIO_MAX, RAIDERIO_STEP)


def parse_item_level(text: str) -> Decimal | None:
    """Itemlevel beolvasása legfeljebb két tizedesjeggyel; üres szövegnél None."""
    return _parse_decimal(text, "itemlevel", "327 vagy 326,55", ITEM_LEVEL_MAX, ITEM_LEVEL_STEP)


def format_raiderio_score(value: Decimal) -> str:
    """Raider.io pontszám egy tizedesjeggyel, tizedesvesszővel (pl. 2543,7)."""
    return _format_decimal(value, RAIDERIO_STEP)


def format_item_level(value: Decimal) -> str:
    """Itemlevel két tizedesjeggyel, tizedesvesszővel (pl. 326,55 vagy 327,00)."""
    return _format_decimal(value, ITEM_LEVEL_STEP)


def format_compact(value: Decimal) -> str:
    """Szám egész alakban, ha egész (pl. 3891), különben egy tizedesjeggyel (pl. 3712,5)."""
    return str(int(value)) if value == value.to_integral_value() else format_raiderio_score(value)


def _decimal_from_json(
    value: object, maximum: Decimal = RAIDERIO_MAX, step: Decimal = RAIDERIO_STEP
) -> Decimal | None:
    """Az adatfájlban tárolt nem negatív szám, pl. Raider.io pontszám (hiányzó vagy üres: None)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"hibás szám: {value!r}")
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"hibás szám: {value!r}") from None
    if not number.is_finite():
        raise ValueError(f"hibás szám: {value!r}")
    return min(max(number, Decimal(0)), maximum).quantize(step)


def _level_from_json(value: object) -> Decimal:
    """Az adatfájlban tárolt szint beolvasása (a megengedett tartományba szorítva)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise TypeError(f"hibás szint: {value!r}")
    try:
        level = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"hibás szint: {value!r}") from None
    if not level.is_finite():
        raise ValueError(f"hibás szint: {value!r}")
    return min(max(level, LEVEL_MIN), LEVEL_MAX).quantize(LEVEL_STEP)


@dataclass
class Settings:
    """A szintezés időkerete, kezdő- és célszintje."""

    start_date: date  # a szintezés kezdete
    first_target_date: date  # eddig kell az első karakternek elérnie a célszintet
    last_target_date: date  # eddig kell az utolsó karakternek elérnie a célszintet
    start_level: Decimal = DEFAULT_START_LEVEL  # a terv szerint innen indulnak a karakterek
    target_level: Decimal = DEFAULT_TARGET_LEVEL  # ezt kell elérniük a céldátumig
    mode: str = PARALLEL

    @classmethod
    def default(cls, today: date | None = None) -> Settings:
        today = today or date.today()
        return cls(
            start_date=today,
            first_target_date=today + timedelta(weeks=2),
            last_target_date=today + timedelta(weeks=8),
        )

    def errors(self) -> list[str]:
        """A beállítások hibái emberi nyelven; üres lista, ha minden rendben van."""
        problems = []
        if self.first_target_date < self.start_date:
            problems.append("Az első karakter céldátuma nem lehet korábbi a szintezés kezdeténél.")
        if self.last_target_date < self.first_target_date:
            problems.append("Az utolsó karakter céldátuma nem lehet korábbi az első karakterénél.")
        for name, level in (("kezdőszint", self.start_level), ("célszint", self.target_level)):
            if not LEVEL_MIN <= level <= LEVEL_MAX:
                problems.append(
                    f"A {name} {format_level(LEVEL_MIN)} és {format_level(LEVEL_MAX)} között lehet."
                )
        if self.target_level <= self.start_level:
            problems.append("A célszintnek nagyobbnak kell lennie a kezdőszintnél.")
        if self.mode not in MODES:
            problems.append(f"Ismeretlen ütemezési mód: {self.mode}.")
        return problems

    def to_dict(self) -> dict:
        return {
            "start_date": format_date(self.start_date),
            "first_target_date": format_date(self.first_target_date),
            "last_target_date": format_date(self.last_target_date),
            "start_level": float(self.start_level),
            "target_level": float(self.target_level),
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        # Az első változat fájljaiban „max. szint” szerepelt, és mindenki 1-es szintről indult.
        first = data["first_target_date"] if "first_target_date" in data else data["first_max_date"]
        last = data["last_target_date"] if "last_target_date" in data else data["last_max_date"]
        target = data.get("target_level", data.get("max_level", DEFAULT_TARGET_LEVEL))
        mode = data.get("mode", PARALLEL)
        return cls(
            start_date=date.fromisoformat(data["start_date"]),
            first_target_date=date.fromisoformat(first),
            last_target_date=date.fromisoformat(last),
            start_level=_level_from_json(data.get("start_level", DEFAULT_START_LEVEL)),
            target_level=_level_from_json(target),
            mode=mode if mode in MODES else PARALLEL,
        )


@dataclass(eq=False)  # két azonos nevű karakter is különböző lehet
class Character:
    name: str
    char_class: str = ""
    spec: str = ""  # specializáció, pl. Frost
    level: Decimal = DEFAULT_START_LEVEL
    race: str = ""  # faj, pl. Orc
    realm: str = ""  # szerver, pl. Draenor
    raiderio_score: Decimal | None = None  # Raider.io (Mythic+) pontszám, ha meg van adva
    item_level: Decimal | None = None  # itemlevel, ha meg van adva
    # Csak a program futása alatt használt azonosító, nem kerül mentésre.
    uid: str = field(default_factory=lambda: uuid.uuid4().hex, repr=False)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "realm": self.realm,
            "race": self.race,
            "class": self.char_class,
            "spec": self.spec,
            "level": float(self.level),
            "raiderio_score": None if self.raiderio_score is None else float(self.raiderio_score),
            "item_level": None if self.item_level is None else float(self.item_level),
        }

    @classmethod
    def from_dict(cls, data: dict, default_level: Decimal = DEFAULT_START_LEVEL) -> Character:
        name = str(data["name"]).strip()
        if not name:
            raise ValueError("üres karakternév")
        return cls(
            name=name,
            char_class=str(data.get("class", "")).strip(),
            spec=str(data.get("spec", "")).strip(),
            level=_level_from_json(data.get("level", default_level)),
            race=str(data.get("race", "")).strip(),
            realm=str(data.get("realm", "")).strip(),
            raiderio_score=_decimal_from_json(data.get("raiderio_score")),
            item_level=_decimal_from_json(data.get("item_level"), ITEM_LEVEL_MAX, ITEM_LEVEL_STEP),
        )


class Status(Enum):
    DONE = "done"  # elérte a célszintet
    NOT_STARTED = "not_started"  # még nem kezdődött el a szintezése
    AHEAD = "ahead"  # a mai célnál is magasabb szinten jár
    GOAL_MET = "goal_met"  # pontosan a mai célnál tart
    ON_TRACK = "on_track"  # a tegnapi célt elérte, a maira még van hátra
    BEHIND = "behind"  # a tegnapi célt sem érte el (vagy kezdés előtt a kezdőszint alatt van)
    OVERDUE = "overdue"  # lejárt a céldátuma, de még nincs célszinten


@dataclass(frozen=True)
class CharacterPlan:
    """Egy karakter ütemterve egy adott napon."""

    character: Character
    position: int  # sorszám a listában (1-től)
    start: date  # a karakter szintezésének kezdőnapja
    deadline: date  # eddig kell elérnie a célszintet
    goal: Decimal | None  # a célnap (alapból a mai nap) végéig elérendő szint (None: kész vagy még nem kezdte)
    deviation: Decimal  # a jelenlegi szint eltérése a célnapra tervezett szinttől (+: előrébb jár)
    days_left: int | None  # hátralévő szintezési napok a céldátumig, a mai napot is beleértve
    pace: Decimal | None  # a szükséges átlagos tempó (szint/nap), felfelé kerekítve
    status: Status
    status_text: str
    spec_score: Decimal | None = None  # a karakter specjének pontszáma a Murlok.io rangsorában

    @property
    def levels_due(self) -> Decimal:
        """Ennyi szint hiányzik még a célnap (alapból a mai nap) céljáig."""
        if self.goal is None:
            return Decimal("0.00")
        return max(Decimal("0.00"), self.goal - self.character.level)


def deadlines(settings: Settings, count: int) -> list[date]:
    """A karakterek céldátumai a lista sorrendjében.

    Az első karakteré az első, az utolsóé az utolsó céldátum, a többieké
    egyenletesen (egész napra kerekítve) oszlik el a kettő között.
    """
    if count <= 0:
        return []
    if count == 1:
        return [settings.first_target_date]
    span = (settings.last_target_date - settings.first_target_date).days
    steps = count - 1
    return [
        settings.first_target_date + timedelta(days=(2 * span * index + steps) // (2 * steps))
        for index in range(count)
    ]


def leveling_windows(settings: Settings, count: int) -> list[tuple[date, date]]:
    """(kezdőnap, céldátum) párok a karakterek sorrendjében."""
    ends = deadlines(settings, count)
    windows = []
    for index, end in enumerate(ends):
        if settings.mode == SEQUENTIAL and index > 0:
            start = ends[index - 1] + timedelta(days=1)
        else:
            start = settings.start_date
        windows.append((min(start, end), end))
    return windows


def planned_level(start: date, deadline: date, from_level: Decimal, to_level: Decimal, day: date) -> Decimal:
    """A `day` nap végéig elérendő szint (két tizedesjegyre lefelé kerekítve).

    A karakter a `start` napon `from_level` szintről indul, és a `deadline`
    nap végéig egyenletes tempóban éri el a `to_level` szintet.
    """
    if day < start:
        return from_level
    if day >= deadline:
        return to_level
    total_days = (deadline - start).days + 1
    elapsed_days = (day - start).days + 1
    progress = (to_level - from_level) * elapsed_days / total_days
    return from_level + progress.quantize(LEVEL_STEP, rounding=ROUND_FLOOR)


def build_plan(
    settings: Settings,
    characters: list[Character],
    today: date | None = None,
    spec_scores: SpecScores | None = None,
    goal_day: date | None = None,
) -> list[CharacterPlan]:
    """Az összes karakter ütemterve a megadott (alapértelmezés szerint a mai) napon.

    A cél, a szinteltérés és az állapot a `goal_day` napra vonatkozik (alapból a mai
    nap, lásd lookahead_day), a hátralévő napok és a tempó mindig a valódi mai naptól.
    """
    today = today or date.today()
    goal_day = goal_day or today
    windows = leveling_windows(settings, len(characters))
    return [
        _plan_character(
            character,
            position,
            start,
            deadline,
            settings,
            today,
            spec_scores.score_for(character) if spec_scores is not None else None,
            goal_day,
        )
        for position, (character, (start, deadline)) in enumerate(zip(characters, windows), start=1)
    ]


def lookahead_day(settings: Settings, characters: list[Character], today: date | None = None) -> date:
    """Az első nap a mai naptól, amelynek tervezett szintjét még nem érte el minden karakter.

    Ha minden karakter elérte a célszintet (vagy nincs karakter), a mai nap.
    """
    today = today or date.today()
    if all(character.level >= settings.target_level for character in characters):
        return today
    windows = leveling_windows(settings, len(characters))
    last_day = max(end for _, end in windows)
    day = today
    while day < last_day and all(
        character.level >= planned_level(start, end, settings.start_level, settings.target_level, day)
        for character, (start, end) in zip(characters, windows)
    ):
        day += timedelta(days=1)
    return day


def _plan_character(
    character: Character,
    position: int,
    start: date,
    deadline: date,
    settings: Settings,
    today: date,
    spec_score: Decimal | None = None,
    goal_day: date | None = None,
) -> CharacterPlan:
    level = character.level
    start_level, target = settings.start_level, settings.target_level
    remaining = target - level
    goal_day = goal_day or today
    # A célnapra tervezett szint: kezdés előtt a kezdőszint, a céldátumtól a célszint.
    planned = planned_level(start, deadline, start_level, target, goal_day)

    def plan(status, text, goal=None, days_left=None, pace=None):
        return CharacterPlan(
            character=character,
            position=position,
            start=start,
            deadline=deadline,
            goal=goal,
            deviation=level - planned,
            days_left=days_left,
            pace=pace,
            status=status,
            status_text=text,
            spec_score=spec_score,
        )

    if remaining <= 0:
        return plan(Status.DONE, "Kész – elérte a célszintet")
    if today > deadline:
        text = f"Lejárt a céldátum – még {format_level(remaining)} szint"
        return plan(Status.OVERDUE, text, goal=target, days_left=0)

    days_left = (deadline - max(today, start)).days + 1
    pace = (remaining / days_left).quantize(LEVEL_STEP, rounding=ROUND_CEILING)
    if goal_day < start:
        if level > start_level:
            status, text = Status.AHEAD, f"Előrébb jár (+{format_level(level - start_level)} szint)"
        elif level < start_level:
            status, text = Status.BEHIND, f"Kezdőszint alatt (−{format_level(start_level - level)} szint)"
        else:
            status, text = Status.NOT_STARTED, f"Még nem kezdődött (indulás: {format_date(start)})"
        return plan(status, text, days_left=days_left, pace=pace)

    goal = planned
    expected = planned_level(start, deadline, start_level, target, goal_day - timedelta(days=1))
    # A mai célnál „ma még”, előretekintéskor pl. „a holnapi célig még”.
    still = "ma még" if goal_day == today else f"{goal_day_phrase(goal_day, today)} célig még"
    if level > goal:
        status, text = Status.AHEAD, f"Előrébb jár (+{format_level(level - goal)} szint)"
    elif level == goal:
        met = "Mai cél" if goal_day == today else f"{goal_day_phrase(goal_day, today).capitalize()} cél"
        status, text = Status.GOAL_MET, f"{met} teljesítve"
    elif level >= expected:
        status, text = Status.ON_TRACK, f"Ütemben – {still} {format_level(goal - level)} szint"
    else:
        status, text = Status.BEHIND, f"Lemaradásban – {still} {format_level(goal - level)} szint"
    return plan(status, text, goal=goal, days_left=days_left, pace=pace)


# Az „Állapot” szerinti rendezés sorrendje: elöl a legsürgősebbek.
STATUS_URGENCY = (
    Status.OVERDUE,
    Status.BEHIND,
    Status.ON_TRACK,
    Status.GOAL_MET,
    Status.AHEAD,
    Status.NOT_STARTED,
    Status.DONE,
)

# A magyar ábécében az ö/ő az o, az ü/ű az u után következik.
_HUNGARIAN_LETTERS = str.maketrans({"ö": "o\uffff", "ő": "o\uffff", "ü": "u\uffff", "ű": "u\uffff"})


def _text_sort_key(text: str) -> tuple[str, str]:
    """Kis- és nagybetűt nem megkülönböztető, a magyar ábécéhez igazodó rendezési kulcs."""
    folded = unicodedata.normalize("NFC", text.casefold())
    base = unicodedata.normalize("NFD", folded.translate(_HUNGARIAN_LETTERS))
    return "".join(char for char in base if not unicodedata.combining(char)), folded


# A lista oszlopai szerinti rendezési kulcsok; None: nincs érték (a lista végére kerül).
SORT_KEYS = {
    "position": lambda plan: plan.position,
    "name": lambda plan: _text_sort_key(plan.character.name),
    "class": lambda plan: (
        (_text_sort_key(plan.character.char_class), _text_sort_key(plan.character.spec))
        if plan.character.char_class
        else None
    ),
    "spec": lambda plan: _text_sort_key(plan.character.spec) if plan.character.spec else None,
    "race": lambda plan: _text_sort_key(plan.character.race) if plan.character.race else None,
    "realm": lambda plan: _text_sort_key(plan.character.realm) if plan.character.realm else None,
    "item_level": lambda plan: plan.character.item_level,
    "raiderio": lambda plan: plan.character.raiderio_score,
    "murlok": lambda plan: plan.spec_score,
    "level": lambda plan: plan.character.level,
    "start": lambda plan: plan.start,
    "deadline": lambda plan: plan.deadline,
    "goal": lambda plan: plan.goal,
    "deviation": lambda plan: plan.deviation,
    "days": lambda plan: plan.days_left,
    "pace": lambda plan: plan.pace,
    "status": lambda plan: (STATUS_URGENCY.index(plan.status), plan.deviation),
}


def sort_plans(plans: list[CharacterPlan], key: str = "position", descending: bool = False) -> list[CharacterPlan]:
    """A tervek rendezése a `key` oszlop szerint.

    Csak a megjelenítés sorrendjét adja meg, a karakterek sorrendjét (és így a
    céldátumokat) nem változtatja. Az üres értékek mindig a végére kerülnek, az
    egyenlő értékűek pedig a lista eredeti sorrendjében maradnak.
    """
    get = SORT_KEYS[key]
    present = [plan for plan in plans if get(plan) is not None]
    missing = [plan for plan in plans if get(plan) is None]
    return sorted(present, key=get, reverse=descending) + missing


def _number_article(number: int) -> str:
    """Határozott névelő sorszám elé: „az 1.”, „az 5.”, „az 50.”, de „a 2.”, „a 10.”."""
    digits = str(number)
    return "az" if digits[0] == "5" or (digits[0] == "1" and len(digits) % 3 == 1) else "a"


@dataclass(frozen=True)
class DayProgress:
    """A karakterek együttes haladása, a terv napjaiban kifejezve."""

    today: int  # a szintezés hányadik napja van ma (1: a kezdőnap; 0 vagy kevesebb: még nem kezdődött el)
    total_days: int  # a terv hossza napokban, a kezdőnaptól az utolsó céldátumig
    reached_day: int  # ennek a napnak a tervezett szintjét érték el együtt (0: még az 1. napét sem)
    character_count: int
    finished: bool  # minden karakter elérte a célszintet

    @property
    def days_ahead(self) -> int:
        """Hány nappal járnak a mai cél előtt (+) vagy mögött (−)."""
        return self.reached_day - min(self.today, self.total_days)

    def describe(self) -> str:
        if self.finished:
            return "A szintezés kész: minden karakter elérte a célszintet."
        single = self.character_count == 1
        subject = "A karakter" if single else "A karakterek együtt"
        if self.reached_day == 0:
            level = f"{subject} még az 1. nap szintjét sem {'érte' if single else 'érték'} el"
        else:
            article = _number_article(self.reached_day)
            level = f"{subject} {article} {self.reached_day}. nap szintjén {'áll' if single else 'állnak'}"
        if self.today < 1:
            wait = 1 - self.today
            when = "holnap" if wait == 1 else f"{wait} nap múlva"
            start = f"A szintezés {when} kezdődik."
            return f"{start} {level}." if self.reached_day else start
        if self.today <= self.total_days:
            day = f"Ma a szintezés {self.today}. napja van (összesen {self.total_days} nap)."
        else:
            day = f"A tervezett {self.total_days} nap letelt."
        if self.days_ahead > 0:
            comparison = f"{self.days_ahead} nappal a terv előtt"
        elif self.days_ahead == 0:
            comparison = "pont a mai célnál"
        else:
            comparison = f"{-self.days_ahead} nappal a mai cél mögött"
        return f"{day} {level} – {comparison}."


def day_progress(settings: Settings, characters: list[Character], today: date | None = None) -> DayProgress | None:
    """Az összes karakter együttes szintje a terv hányadik napjának felel meg.

    Összeadja, hány szintet léptek a karakterek a kezdőszinthez képest (legfeljebb
    a célszintig; a kezdőszint alatti karakterek hiánya levonódik), és megkeresi az
    utolsó napot, amelynek végére a terv szerint összesen ennyi szint volt esedékes.
    """
    if not characters:
        return None
    today = today or date.today()
    windows = leveling_windows(settings, len(characters))
    total_days = (max(end for _, end in windows) - settings.start_date).days + 1
    if total_days < 1:
        return None
    gained = sum(min(c.level, settings.target_level) - settings.start_level for c in characters)

    def planned_gain(day_number: int) -> Decimal:
        day = settings.start_date + timedelta(days=day_number - 1)
        return sum(
            planned_level(start, end, settings.start_level, settings.target_level, day) - settings.start_level
            for start, end in windows
        )

    reached = 0
    while reached < total_days and planned_gain(reached + 1) <= gained:
        reached += 1
    return DayProgress(
        today=(today - settings.start_date).days + 1,
        total_days=total_days,
        reached_day=reached,
        character_count=len(characters),
        finished=all(c.level >= settings.target_level for c in characters),
    )


ESTIMATE_LIMIT_DAYS = 3650  # ennél (kb. 10 évnél) távolabbi céldátumot nem javasol a program
_TOO_SLOW = "Az eddigi tempóval ez több mint 10 évig tartana, ilyen céldátumot nem érdemes beállítani."


@dataclass(frozen=True)
class TargetDateEstimate:
    """Az első és az utolsó céldátum az eddigi tempó alapján (lásd estimate_target_dates)."""

    first_target_date: date
    last_target_date: date
    days: int  # a szintezés lezárt napjainak száma: a kezdőnaptól a tegnapi napig
    first_reason: str  # hogyan adódott az első céldátum
    last_reason: str  # hogyan adódott az utolsó céldátum


def _days_needed(remaining: Decimal, gained: Decimal, days: int) -> int:
    """Hány nap kell a hátralévő szintekhez, ha eddig `days` nap alatt `gained` szint jött össze."""
    needed = int((remaining * days / gained).to_integral_value(rounding=ROUND_CEILING))
    if needed > ESTIMATE_LIMIT_DAYS:
        raise ValueError(_TOO_SLOW)
    return needed


def _daily_pace(gained: Decimal, days: int) -> str:
    return format_level((gained / days).quantize(LEVEL_STEP, rounding=ROUND_HALF_UP))


def estimate_target_dates(
    settings: Settings, characters: list[Character], today: date | None = None
) -> TargetDateEstimate:
    """Az első és az utolsó karakter céldátuma a karakterek eddigi tempója alapján.

    A mostani szinteket a tegnapi nap végéig elértnek tekinti, a mai nap tehát még
    szintezési nap. Az eddigi tempó: a kezdőnaptól tegnapig a kezdőszint felett
    megszerzett szintek (legfeljebb a célszintig) osztva a napok számával.

    * Az első céldátum: amikor a lista első karaktere a saját eddigi tempójával
      eléri a célszintet. Ha még nem lépett túl a kezdőszinten, a karakterek
      együttes tempójával számol; ha már célszinten van, a céldátuma legkésőbb a
      tegnapi nap.
    * Az utolsó céldátum párhuzamos ütemezésnél a legkorábbi nap, amellyel a
      karakterek együtt (lásd day_progress) elérik a terv tegnapi célját; egymás
      utáni ütemezésnél pedig az a nap, amikorra az együttes eddigi tempóval minden
      hátralévő szint meglesz. Nem lehet korábbi az első céldátumnál.

    A beállítások közül csak a kezdőnapot, a kezdő- és a célszintet, valamint az
    ütemezést használja (és az első céldátumot, ha az első karakter már célszinten
    van). ValueError-t dob, ha nincs miből számolni.
    """
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    days = (today - settings.start_date).days
    start, target = settings.start_level, settings.target_level
    if not characters:
        raise ValueError("Még nincs karakter a listán, így nincs miből számolni.")
    if days < 1:
        when = "ma kezdődik" if days == 0 else f"még nem kezdődött el (kezdete: {format_date(settings.start_date)})"
        raise ValueError(
            f"A szintezés {when}, így még nincs lezárt nap, amelynek a tempójából számolni lehetne "
            "(a mai nap még nem számít bele)."
        )
    if target <= start:
        raise ValueError("A célszintnek nagyobbnak kell lennie a kezdőszintnél.")
    if all(character.level >= target for character in characters):
        raise ValueError("Minden karakter elérte már a célszintet, nincs mit kiszámolni.")
    gains = [max(min(character.level, target) - start, Decimal(0)) for character in characters]
    total_gain = sum(gains)
    if total_gain <= 0:
        raise ValueError(
            "A kezdés óta még egyik karakter sem lépett túl a kezdőszinten, így nincs eddigi tempó, "
            "amiből számolni lehetne."
        )

    first = characters[0]
    if first.level >= target:
        first_date = max(settings.start_date, min(settings.first_target_date, yesterday))
        first_reason = f"{first.name} már elérte a célszintet, ezért a céldátuma legkésőbb a tegnapi nap."
    else:
        remaining = target - first.level
        if gains[0] > 0:
            needed = _days_needed(remaining, gains[0], days)
            first_reason = (
                f"{first.name} eddig napi {_daily_pace(gains[0], days)} szintet lépett, így a hátralévő "
                f"{format_level(remaining)} szintet {needed} nap alatt szerzi meg."
            )
        else:
            needed = _days_needed(remaining, total_gain, days)
            first_reason = (
                f"{first.name} még nem lépett túl a kezdőszinten, ezért a karakterek együttes tempójával "
                f"(napi {_daily_pace(total_gain, days)} szint) számolva a hátralévő {format_level(remaining)} "
                f"szintet {needed} nap alatt szerzi meg."
            )
        first_date = today + timedelta(days=needed - 1)

    if len(characters) == 1:
        last_date, last_reason = first_date, "Egyetlen karakter van, így ez megegyezik az első céldátummal."
    elif settings.mode == SEQUENTIAL:
        remaining = sum(max(target - character.level, Decimal(0)) for character in characters)
        needed = _days_needed(remaining, total_gain, days)
        last_date = max(first_date, today + timedelta(days=needed - 1))
        last_reason = (
            f"A karakterek együtt eddig napi {_daily_pace(total_gain, days)} szintet léptek, így a hátralévő "
            f"összesen {format_level(remaining)} szint {needed} nap alatt lesz meg."
        )
        if last_date > today + timedelta(days=needed - 1):
            last_reason += " Az utolsó céldátum azonban nem lehet korábbi az elsőnél."
    else:
        last_date = _parallel_last_date(settings, characters, first_date, today)
        last_reason = "Ezzel a dátummal a karakterek együttes szintje éppen eléri a terv tegnapi célját."
    return TargetDateEstimate(first_date, last_date, days, first_reason, last_reason)


def _parallel_last_date(settings: Settings, characters: list[Character], first_date: date, today: date) -> date:
    """A legkorábbi utolsó céldátum (legalább `first_date`), amellyel a párhuzamos terv
    szerint a tegnapi nap végére esedékes szintek összege nem több, mint amennyit a
    karakterek együtt elértek (ugyanúgy számolva, mint a day_progress)."""
    start, target = settings.start_level, settings.target_level
    yesterday = today - timedelta(days=1)
    gained = sum(min(character.level, target) - start for character in characters)

    def reached(last: date) -> bool:
        trial = replace(settings, first_target_date=first_date, last_target_date=last)
        due = sum(
            planned_level(window_start, end, start, target, yesterday) - start
            for window_start, end in leveling_windows(trial, len(characters))
        )
        return due <= gained

    # Későbbi utolsó céldátummal a köztes céldátumok sem korábbiak, így a tegnapra
    # esedékes szintek sem nőnek: a legkorábbi megfelelő nap felezéssel kereshető.
    low, high = first_date, today + timedelta(days=ESTIMATE_LIMIT_DAYS - 1)
    if not reached(high):
        raise ValueError(_TOO_SLOW)
    while low < high:
        middle = low + timedelta(days=(high - low).days // 2)
        if reached(middle):
            high = middle
        else:
            low = middle + timedelta(days=1)
    return low


SPEC_SCORES_MAX_AGE = timedelta(hours=8)  # a Murlok.io is 8 óránként frissíti a rangsorait


@dataclass
class SpecScores:
    """A Murlok.io Mythic+ rangsoraiból lekért, specenkénti pontszámok."""

    scores: dict[str, Decimal] = field(default_factory=dict)  # kulcs: spec_key(kaszt, spec)
    fetched_at: datetime | None = None  # a lekérés időpontja (helyi idő)

    @staticmethod
    def spec_key(char_class: str, spec: str) -> str:
        return f"{char_class.strip()}/{spec.strip()}".casefold()

    def score_for(self, character: Character) -> Decimal | None:
        """A karakter kasztjához és specjéhez tartozó pontszám (ha mindkettő meg van adva)."""
        if not character.char_class.strip() or not character.spec.strip():
            return None
        return self.scores.get(self.spec_key(character.char_class, character.spec))

    def is_stale(self, now: datetime | None = None) -> bool:
        """Igaz, ha még nincs adat, vagy régebbi annál, ahogy a Murlok.io frissül."""
        now = now or datetime.now()
        return self.fetched_at is None or now - self.fetched_at >= SPEC_SCORES_MAX_AGE

    def to_dict(self) -> dict:
        return {
            "fetched_at": None if self.fetched_at is None else self.fetched_at.isoformat(timespec="seconds"),
            "scores": {key: float(value) for key, value in sorted(self.scores.items())},
        }

    @classmethod
    def from_dict(cls, data: dict) -> SpecScores:
        scores = {}
        for key, value in dict(data.get("scores", {})).items():
            score = _decimal_from_json(value)
            if score is not None:
                scores[str(key).casefold()] = score
        fetched_at = data.get("fetched_at")
        return cls(scores=scores, fetched_at=datetime.fromisoformat(fetched_at) if fetched_at else None)


def murlok_order(characters: list[Character], spec_scores: SpecScores) -> list[Character]:
    """Szintezési sorrend a Murlok.io-pontszámok alapján.

    Körönként minden class/specből egy karakter kerül sorra, mindig a legmagasabb
    szintű a még hátralévők közül; egy körön belül a magasabb pontszámú spec van
    elöl. Akinek nincs pontszáma (nincs megadva vagy ismeretlen a class/spec), a
    végére kerül. Egyenlőség esetén a mostani sorrend dönt.
    """
    groups: dict[str, list[Character]] = {}  # spec kulcsa → karakterei, a mostani sorrendben
    unranked = []
    for character in characters:
        if spec_scores.score_for(character) is None:
            unranked.append(character)
        else:
            groups.setdefault(SpecScores.spec_key(character.char_class, character.spec), []).append(character)
    for members in groups.values():
        members.sort(key=lambda character: character.level, reverse=True)
    ranked_specs = sorted(groups, key=lambda key: spec_scores.scores[key], reverse=True)
    rounds = max((len(members) for members in groups.values()), default=0)
    order = [
        groups[key][round_index]
        for round_index in range(rounds)
        for key in ranked_specs
        if round_index < len(groups[key])
    ]
    return order + unranked


@dataclass
class LevelingData:
    """A program összes mentendő adata."""

    settings: Settings
    characters: list[Character] = field(default_factory=list)
    spec_scores: SpecScores = field(default_factory=SpecScores)  # a Murlok.io-ról lekért adatok
    # A lista a következő nap céljait mutassa, ha a mai célt minden karakter teljesítette.
    look_ahead: bool = True

    def to_dict(self) -> dict:
        return {
            "version": DATA_VERSION,
            "settings": self.settings.to_dict(),
            "characters": [character.to_dict() for character in self.characters],
            "spec_scores": self.spec_scores.to_dict(),
            "view": {"look_ahead": self.look_ahead},
        }

    @classmethod
    def from_dict(cls, data: dict) -> LevelingData:
        settings = Settings.from_dict(data["settings"])
        try:
            spec_scores = SpecScores.from_dict(data.get("spec_scores") or {})
        except (ArithmeticError, AttributeError, TypeError, ValueError):
            spec_scores = SpecScores()  # a sérült gyorsítótár miatt ne vesszenek el az adatok
        view = data.get("view")
        look_ahead = view.get("look_ahead", True) if isinstance(view, dict) else True
        return cls(
            settings=settings,
            characters=[Character.from_dict(item, settings.start_level) for item in data.get("characters", [])],
            spec_scores=spec_scores,
            look_ahead=look_ahead if isinstance(look_ahead, bool) else True,
        )


def load_data(path: str | os.PathLike) -> LevelingData:
    """Az adatok betöltése.

    FileNotFoundError-t dob, ha a fájl nem létezik, és ValueError-t,
    ha a tartalma nem értelmezhető.
    """
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    try:
        return LevelingData.from_dict(raw)
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Hiányzó vagy hibás adat a fájlban ({exc!r}).") from exc


def save_data(path: str | os.PathLike, data: LevelingData) -> None:
    """Az adatok mentése. Előbb ideiglenes fájlba ír, így megszakadt mentés
    esetén sem sérül a korábbi adatfájl."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise
