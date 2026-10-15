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
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from enum import Enum
from pathlib import Path

LEVEL_STEP = Decimal("0.01")  # a szintek két tizedesjegy pontosságúak
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
    level: Decimal = DEFAULT_START_LEVEL
    # Csak a program futása alatt használt azonosító, nem kerül mentésre.
    uid: str = field(default_factory=lambda: uuid.uuid4().hex, repr=False)

    def to_dict(self) -> dict:
        return {"name": self.name, "class": self.char_class, "level": float(self.level)}

    @classmethod
    def from_dict(cls, data: dict, default_level: Decimal = DEFAULT_START_LEVEL) -> Character:
        name = str(data["name"]).strip()
        if not name:
            raise ValueError("üres karakternév")
        return cls(
            name=name,
            char_class=str(data.get("class", "")).strip(),
            level=_level_from_json(data.get("level", default_level)),
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
    goal_today: Decimal | None  # a mai nap végéig elérendő szint (None: kész vagy még nem kezdte)
    days_left: int | None  # hátralévő szintezési napok a céldátumig, a mai napot is beleértve
    pace: Decimal | None  # a szükséges átlagos tempó (szint/nap), felfelé kerekítve
    status: Status
    status_text: str

    @property
    def levels_due_today(self) -> Decimal:
        """Ennyi szintet kell még ma szerezni a mai cél eléréséhez."""
        if self.goal_today is None:
            return Decimal("0.00")
        return max(Decimal("0.00"), self.goal_today - self.character.level)


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
    settings: Settings, characters: list[Character], today: date | None = None
) -> list[CharacterPlan]:
    """Az összes karakter ütemterve a megadott (alapértelmezés szerint a mai) napon."""
    today = today or date.today()
    windows = leveling_windows(settings, len(characters))
    return [
        _plan_character(character, position, start, deadline, settings, today)
        for position, (character, (start, deadline)) in enumerate(zip(characters, windows), start=1)
    ]


def _plan_character(
    character: Character, position: int, start: date, deadline: date, settings: Settings, today: date
) -> CharacterPlan:
    level = character.level
    start_level, target = settings.start_level, settings.target_level
    remaining = target - level

    def plan(status, text, goal=None, days_left=None, pace=None):
        return CharacterPlan(character, position, start, deadline, goal, days_left, pace, status, text)

    if remaining <= 0:
        return plan(Status.DONE, "Kész – elérte a célszintet")
    if today > deadline:
        text = f"Lejárt a céldátum – még {format_level(remaining)} szint"
        return plan(Status.OVERDUE, text, goal=target, days_left=0)

    days_left = (deadline - max(today, start)).days + 1
    pace = (remaining / days_left).quantize(LEVEL_STEP, rounding=ROUND_CEILING)
    if today < start:
        if level > start_level:
            status, text = Status.AHEAD, f"Előrébb jár (+{format_level(level - start_level)} szint)"
        elif level < start_level:
            status, text = Status.BEHIND, f"Kezdőszint alatt (−{format_level(start_level - level)} szint)"
        else:
            status, text = Status.NOT_STARTED, f"Még nem kezdődött (indulás: {format_date(start)})"
        return plan(status, text, days_left=days_left, pace=pace)

    goal = planned_level(start, deadline, start_level, target, today)
    expected = planned_level(start, deadline, start_level, target, today - timedelta(days=1))
    if level > goal:
        status, text = Status.AHEAD, f"Előrébb jár (+{format_level(level - goal)} szint)"
    elif level == goal:
        status, text = Status.GOAL_MET, "Mai cél teljesítve"
    elif level >= expected:
        status, text = Status.ON_TRACK, f"Ütemben – ma még {format_level(goal - level)} szint"
    else:
        status, text = Status.BEHIND, f"Lemaradásban – ma még {format_level(goal - level)} szint"
    return plan(status, text, goal=goal, days_left=days_left, pace=pace)


@dataclass
class LevelingData:
    """A program összes mentendő adata."""

    settings: Settings
    characters: list[Character] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": DATA_VERSION,
            "settings": self.settings.to_dict(),
            "characters": [character.to_dict() for character in self.characters],
        }

    @classmethod
    def from_dict(cls, data: dict) -> LevelingData:
        settings = Settings.from_dict(data["settings"])
        return cls(
            settings=settings,
            characters=[Character.from_dict(item, settings.start_level) for item in data.get("characters", [])],
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
