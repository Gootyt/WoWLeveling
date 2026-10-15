"""World of Warcraft karakterek szintezésének ütemezése.

Ez a modul tartalmazza a program logikáját (beállítások, karakterek,
ütemterv-számítás, mentés és betöltés). A grafikus felülettől független,
így önállóan is tesztelhető.

Az ütemezés szabályai:

* Minden karakter 1-es szintről indul.
* A karakterek céldátumai (amikorra el kell érniük a maximum szintet) a lista
  sorrendjében, egyenletesen oszlanak el az első és az utolsó karakter
  céldátuma között.
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
from enum import Enum
from pathlib import Path

START_LEVEL = 1  # minden karakter 1-es szintről indul
DEFAULT_MAX_LEVEL = 90
MAX_LEVEL_LIMIT = 999

PARALLEL = "parallel"  # minden karakter a közös kezdő naptól szintez
SEQUENTIAL = "sequential"  # a karakterek egymás után következnek
MODES = (PARALLEL, SEQUENTIAL)

DATA_VERSION = 1

_DATE_PATTERN = re.compile(r"\s*(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\s*\.?\s*")


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


def parse_max_level(text: str) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise ValueError("A maximum szint csak egész szám lehet.") from None
    if not START_LEVEL < value <= MAX_LEVEL_LIMIT:
        raise ValueError(f"A maximum szint {START_LEVEL + 1} és {MAX_LEVEL_LIMIT} között lehet.")
    return value


def parse_level(text: str, max_level: int) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise ValueError("A szint csak egész szám lehet.") from None
    if not START_LEVEL <= value <= max_level:
        raise ValueError(f"A szint {START_LEVEL} és {max_level} között lehet.")
    return value


@dataclass
class Settings:
    """A szintezés időkerete és a maximum szint."""

    start_date: date  # a szintezés kezdete
    first_max_date: date  # eddig kell az első karakternek elérnie a maximum szintet
    last_max_date: date  # eddig kell az utolsó karakternek elérnie a maximum szintet
    max_level: int = DEFAULT_MAX_LEVEL
    mode: str = PARALLEL

    @classmethod
    def default(cls, today: date | None = None) -> Settings:
        today = today or date.today()
        return cls(
            start_date=today,
            first_max_date=today + timedelta(weeks=2),
            last_max_date=today + timedelta(weeks=8),
        )

    def errors(self) -> list[str]:
        """A beállítások hibái emberi nyelven; üres lista, ha minden rendben van."""
        problems = []
        if self.first_max_date < self.start_date:
            problems.append("Az első karakter céldátuma nem lehet korábbi a szintezés kezdeténél.")
        if self.last_max_date < self.first_max_date:
            problems.append("Az utolsó karakter céldátuma nem lehet korábbi az első karakterénél.")
        if not START_LEVEL < self.max_level <= MAX_LEVEL_LIMIT:
            problems.append(f"A maximum szint {START_LEVEL + 1} és {MAX_LEVEL_LIMIT} között lehet.")
        if self.mode not in MODES:
            problems.append(f"Ismeretlen ütemezési mód: {self.mode}.")
        return problems

    def to_dict(self) -> dict:
        return {
            "start_date": format_date(self.start_date),
            "first_max_date": format_date(self.first_max_date),
            "last_max_date": format_date(self.last_max_date),
            "max_level": self.max_level,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        max_level = int(data.get("max_level", DEFAULT_MAX_LEVEL))
        mode = data.get("mode", PARALLEL)
        return cls(
            start_date=date.fromisoformat(data["start_date"]),
            first_max_date=date.fromisoformat(data["first_max_date"]),
            last_max_date=date.fromisoformat(data["last_max_date"]),
            max_level=min(max(max_level, START_LEVEL + 1), MAX_LEVEL_LIMIT),
            mode=mode if mode in MODES else PARALLEL,
        )


@dataclass(eq=False)  # két azonos nevű karakter is különböző lehet
class Character:
    name: str
    char_class: str = ""
    level: int = START_LEVEL
    # Csak a program futása alatt használt azonosító, nem kerül mentésre.
    uid: str = field(default_factory=lambda: uuid.uuid4().hex, repr=False)

    def to_dict(self) -> dict:
        return {"name": self.name, "class": self.char_class, "level": self.level}

    @classmethod
    def from_dict(cls, data: dict) -> Character:
        name = str(data["name"]).strip()
        if not name:
            raise ValueError("üres karakternév")
        return cls(
            name=name,
            char_class=str(data.get("class", "")).strip(),
            level=max(START_LEVEL, int(data.get("level", START_LEVEL))),
        )


class Status(Enum):
    DONE = "done"  # elérte a maximum szintet
    NOT_STARTED = "not_started"  # még nem kezdődött el a szintezése
    AHEAD = "ahead"  # a mai célnál is magasabb szinten jár
    GOAL_MET = "goal_met"  # pontosan a mai célnál tart
    ON_TRACK = "on_track"  # a tegnapi célt elérte, a maira még van hátra
    BEHIND = "behind"  # a tegnapi célt sem érte el
    OVERDUE = "overdue"  # lejárt a céldátuma, de még nincs maximum szinten


@dataclass(frozen=True)
class CharacterPlan:
    """Egy karakter ütemterve egy adott napon."""

    character: Character
    position: int  # sorszám a listában (1-től)
    start: date  # a karakter szintezésének kezdőnapja
    deadline: date  # eddig kell elérnie a maximum szintet
    goal_today: int | None  # a mai nap végéig elérendő szint (None: kész vagy még nem kezdte)
    days_left: int | None  # hátralévő szintezési napok a céldátumig, a mai napot is beleértve
    pace: float | None  # a szükséges átlagos tempó (szint/nap)
    status: Status
    status_text: str

    @property
    def levels_due_today(self) -> int:
        """Ennyi szintet kell még ma szerezni a mai cél eléréséhez."""
        if self.goal_today is None:
            return 0
        return max(0, self.goal_today - self.character.level)


def deadlines(settings: Settings, count: int) -> list[date]:
    """A karakterek céldátumai a lista sorrendjében.

    Az első karakteré az első, az utolsóé az utolsó céldátum, a többieké
    egyenletesen (egész napra kerekítve) oszlik el a kettő között.
    """
    if count <= 0:
        return []
    if count == 1:
        return [settings.first_max_date]
    span = (settings.last_max_date - settings.first_max_date).days
    steps = count - 1
    return [
        settings.first_max_date + timedelta(days=(2 * span * index + steps) // (2 * steps))
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


def target_level(start: date, deadline: date, max_level: int, day: date) -> int:
    """A `day` nap végéig elérendő szint.

    A karakter a `start` napon 1-es szintről indul, és a `deadline` nap
    végéig egyenletes tempóban éri el a `max_level` szintet.
    """
    if day < start:
        return START_LEVEL
    if day >= deadline:
        return max_level
    total_days = (deadline - start).days + 1
    elapsed_days = (day - start).days + 1
    return START_LEVEL + (max_level - START_LEVEL) * elapsed_days // total_days


def build_plan(
    settings: Settings, characters: list[Character], today: date | None = None
) -> list[CharacterPlan]:
    """Az összes karakter ütemterve a megadott (alapértelmezés szerint a mai) napon."""
    today = today or date.today()
    windows = leveling_windows(settings, len(characters))
    return [
        _plan_character(character, position, start, deadline, settings.max_level, today)
        for position, (character, (start, deadline)) in enumerate(zip(characters, windows), start=1)
    ]


def _plan_character(
    character: Character, position: int, start: date, deadline: date, max_level: int, today: date
) -> CharacterPlan:
    level = character.level
    remaining = max_level - level

    def plan(status, text, goal=None, days_left=None, pace=None):
        return CharacterPlan(character, position, start, deadline, goal, days_left, pace, status, text)

    if remaining <= 0:
        return plan(Status.DONE, "Kész – elérte a maximum szintet")
    if today > deadline:
        return plan(
            Status.OVERDUE, f"Lejárt a céldátum – még {remaining} szint", goal=max_level, days_left=0
        )

    days_left = (deadline - max(today, start)).days + 1
    pace = remaining / days_left
    if today < start:
        if level > START_LEVEL:
            text = f"Előrébb jár (+{level - START_LEVEL} szint)"
            return plan(Status.AHEAD, text, days_left=days_left, pace=pace)
        text = f"Még nem kezdődött (indulás: {format_date(start)})"
        return plan(Status.NOT_STARTED, text, days_left=days_left, pace=pace)

    goal = target_level(start, deadline, max_level, today)
    expected = target_level(start, deadline, max_level, today - timedelta(days=1))
    if level > goal:
        status, text = Status.AHEAD, f"Előrébb jár (+{level - goal} szint)"
    elif level == goal:
        status, text = Status.GOAL_MET, "Mai cél teljesítve"
    elif level >= expected:
        status, text = Status.ON_TRACK, f"Ütemben – ma még {goal - level} szint"
    else:
        status, text = Status.BEHIND, f"Lemaradásban – ma még {goal - level} szint"
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
        return cls(
            settings=Settings.from_dict(data["settings"]),
            characters=[Character.from_dict(item) for item in data.get("characters", [])],
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
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
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
