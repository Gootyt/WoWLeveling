"""A telefonos alkalmazás felülettől független része: a karakterlista kártyáinak szövegei és
rendezése, a karakterek felvétele, szerkesztése, törlése és átrendezése (a „Sorrend” képernyő sorai
is), valamint a terv beállításai
– ugyanazzal a számolással és ellenőrzéssel, mint a gépi program (leveling.py). A Kivy-felület
(main.py) csak megjeleníti őket; így ez a rész a szokásos tesztekkel is ellenőrizhető
(tests/test_mobile_plan.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import storage
from leveling import (
    MODES,
    PARALLEL,
    REGIONS,
    Character,
    LevelingData,
    Settings,
    Status,
    build_plan,
    deadlines,
    format_date,
    format_deviation,
    format_item_level,
    format_level,
    format_raiderio_score,
    goal_day_phrase,
    lookahead_day,
    parse_date,
    parse_item_level,
    parse_level,
    parse_position,
    parse_raiderio_score,
    sort_plans,
)
from leveling import move_character as move_to_position
from wow_data import WOW_CLASSES, WOW_RACES, specs_for_class

# Az állapotok színe a kártyákon (RGBA, 0–1): a gépi program listájának színeihez hasonlóan.
TONES = {
    Status.DONE: (0.55, 0.55, 0.6, 1),
    Status.NOT_STARTED: (0.6, 0.6, 0.65, 1),
    Status.AHEAD: (0.35, 0.8, 0.45, 1),
    Status.GOAL_MET: (0.35, 0.8, 0.45, 1),
    Status.ON_TRACK: (0.95, 0.8, 0.3, 1),
    Status.BEHIND: (0.95, 0.4, 0.4, 1),
    Status.OVERDUE: (0.95, 0.3, 0.3, 1),
}
GOOD, BAD, NEUTRAL = (0.35, 0.8, 0.45, 1), (0.95, 0.4, 0.4, 1), (0.8, 0.8, 0.85, 1)
CLASSES = ("",) + WOW_CLASSES  # az üres: nincs megadva
RACES = ("",) + WOW_RACES

# A lista rendezései (a kártyákon látható értékek szerint): kulcs (leveling.SORT_KEYS) → felirat. Mind
# a hasznosabb iránnyal kezd: elöl a legsürgősebb, a legnagyobb lemaradás, a legkisebb érték, illetve
# ábécérendben; a „Fordítva” kapcsoló megfordítja. Az üres értékűek mindig a végére kerülnek.
SORTS = {
    "status": "Állapot",
    "position": "Terv szerinti sorrend",
    "deviation": "Szint-lemaradás",
    "level": "Szint",
    "item_level_deviation": "Itemlevel-lemaradás",
    "item_level": "Itemlevel",
    "raiderio_deviation": "Mythic+ lemaradás",
    "raiderio": "Mythic+ pontszám",
    "name": "Név",
}
DEFAULT_SORT = ("status", False)  # mint a gépi program listája: elöl a legsürgősebbek, a kész karakterek a végén


@dataclass(frozen=True)
class Card:
    """Egy karakter kártyája a listában."""

    uid: str
    title: str  # „1. Thrall (Draenor)”
    subtitle: str  # „Enhancement Shaman · Orc”
    level: str  # „Szint 83,45 · cél 84,10 · −0,65”
    status: str  # a program listájának állapota, pl. „Lemaradásban – ma még 0,65 szint”
    tone: tuple  # az állapot színe
    gear: str  # „Itemlevel 301,56 · terv 300,50 · +1,06” (üres, ha nincs se itemlevel, se terv)
    gear_tone: tuple
    mplus: str  # „M+ 1234,0 · terv 1234,0 · 0,0”
    mplus_tone: tuple


@dataclass(frozen=True)
class OrderRow:
    """Egy karakter sora a „Sorrend” képernyőn (a terv sorrendjében)."""

    uid: str
    title: str  # „3. Thrall (Draenor)”, mint a kártyán
    subtitle: str  # „Enhancement Shaman · szint 83,45 · céldátum: 2026-11-06”


def card_title(position: int, character: Character) -> str:
    """A karakter címe a helyével a tervben, pl. „1. Thrall (Draenor)”."""
    return f"{position}. {character.name}" + (f" ({character.realm})" if character.realm else "")


def goal_day(data: LevelingData, today: date) -> date:
    """A nap, amelynek a céljaival a lista számol (előretekintéssel a holnapi is lehet)."""
    return lookahead_day(data.settings, data.characters, today) if data.look_ahead else today


def _tone(deviation) -> tuple:
    if deviation is None:
        return NEUTRAL
    return BAD if deviation < 0 else GOOD


def _value_line(label: str, value, planned, deviation, formatter) -> str:
    parts = [f"{label} {'–' if value is None else formatter(value)}"]
    if planned is not None:
        parts.append(f"terv {formatter(planned)}")
    if deviation is not None:
        parts.append(format_deviation(deviation, formatter))
    return " · ".join(parts)


def cards(data: LevelingData, today: date, sort: str = "position", descending: bool = False) -> list[Card]:
    """A lista kártyái a `sort` szerint rendezve (lásd SORTS); a címükben a karakter helye a tervben."""
    plans = build_plan(data.settings, data.characters, today, data.spec_scores, goal_day(data, today))
    result = []
    for plan in sort_plans(plans, sort, descending):
        character = plan.character
        subtitle = " · ".join(
            part for part in (" ".join(p for p in (character.spec, character.char_class) if p), character.race) if part
        )
        level = f"Szint {format_level(character.level)}"
        if plan.goal is not None:
            level += f" · cél {format_level(plan.goal)}"
        level += f" · {format_deviation(plan.deviation)}"
        has_gear = character.item_level is not None or plan.planned_item_level is not None
        has_score = character.raiderio_score is not None or plan.planned_raiderio is not None
        result.append(
            Card(
                uid=character.uid,
                title=card_title(plan.position, character),
                subtitle=subtitle,
                level=level,
                status=plan.status_text,
                tone=TONES[plan.status],
                gear=_value_line(
                    "Itemlevel", character.item_level, plan.planned_item_level, plan.item_level_deviation, format_item_level
                )
                if has_gear
                else "",
                gear_tone=_tone(plan.item_level_deviation),
                mplus=_value_line(
                    "M+", character.raiderio_score, plan.planned_raiderio, plan.raiderio_deviation, format_raiderio_score
                )
                if has_score
                else "",
                mplus_tone=_tone(plan.raiderio_deviation),
            )
        )
    return result


def summary(data: LevelingData, today: date) -> str:
    """Egy sor a lista fölé: hány karakter, és mennyi a mai (vagy az előretekintés napjának) teendője."""
    if not data.characters:
        return "Még nincs karakter: az „Új karakter” gombbal vehetsz fel, vagy szinkronizálj a gépről."
    day = goal_day(data, today)
    plans = build_plan(data.settings, data.characters, today, data.spec_scores, day)
    done = sum(plan.status is Status.DONE for plan in plans)
    due = sum(plan.levels_due for plan in plans)
    parts = [f"{len(plans)} karakter", f"célszinten: {done}"]
    if day != today:
        parts.append(f"{goal_day_phrase(day, today)} célig: {format_level(due)} szint")
    else:
        parts.append(f"mai teendő: {format_level(due)} szint" if due else "mára nincs több teendő")
    return " · ".join(parts)


# --- a lista rendezése ------------------------------------------------------------------


def load_sort(database) -> tuple[str, bool]:
    """A lista rendezése (kulcs, fordítva-e), ahogy a telefonon legutóbb választották; ha még nincs
    (vagy olvashatatlan), az alapértelmezett. Csak a telefoné: a felhőbe nem kerül fel."""
    try:
        text = storage.read_document(database, storage.PHONE_VIEW)
        view = json.loads(text) if text else {}
    except (OSError, ValueError):
        return DEFAULT_SORT
    if not isinstance(view, dict):
        return DEFAULT_SORT
    sort, descending = view.get("sort"), view.get("descending", False)
    if not isinstance(sort, str) or sort not in SORTS or not isinstance(descending, bool):
        return DEFAULT_SORT
    return sort, descending


def save_sort(database, sort: str, descending: bool) -> None:
    storage.write_document(database, storage.PHONE_VIEW, json.dumps({"sort": sort, "descending": descending}))


# --- a karakterek szerkesztése ----------------------------------------------------------


def character_form(data: LevelingData, character: Character | None) -> dict:
    """A szerkesztő mezők szövegei (új karakternél üresek; a helye a tervben csak a meglévőnél van:
    az új a lista végére kerül)."""
    if character is None:
        return {"name": "", "realm": "", "class": "", "spec": "", "race": "", "level": "", "item_level": "", "score": ""}
    return {
        "position": str(position_of(data, character.uid)),
        "name": character.name,
        "realm": character.realm,
        "class": character.char_class,
        "spec": character.spec,
        "race": character.race,
        "level": format_level(character.level),
        "item_level": "" if character.item_level is None else format_item_level(character.item_level),
        "score": "" if character.raiderio_score is None else format_raiderio_score(character.raiderio_score),
    }


def spec_choices(char_class: str) -> tuple:
    return ("",) + specs_for_class(char_class) if char_class else ("",)


def find(data: LevelingData, uid: str | None) -> Character | None:
    return next((character for character in data.characters if character.uid == uid), None)


def position_of(data: LevelingData, uid: str | None) -> int | None:
    """A karakter helye a terv sorrendjében (1-től), vagy None, ha nincs ilyen karakter."""
    return next((index for index, character in enumerate(data.characters, start=1) if character.uid == uid), None)


def save_character(data: LevelingData, uid: str | None, form: dict) -> Character:
    """A szerkesztett (uid: None esetén az új, a lista végére kerülő) karakter; a meglévő a „position”
    mezőben megadott helyre is kerül a terv sorrendjében. ValueError magyar üzenettel, ha valamelyik
    mező hibás; ekkor az adatok nem változnak."""
    name = form.get("name", "").strip()
    if not name:
        raise ValueError("Add meg a karakter nevét.")
    level_text = form.get("level", "")
    try:
        level = parse_level(level_text) if level_text.strip() else data.settings.start_level
    except ValueError as exc:
        raise ValueError(f"Szint: {exc}") from exc
    try:
        item_level = parse_item_level(form.get("item_level", ""))
    except ValueError as exc:
        raise ValueError(f"Itemlevel: {exc}") from exc
    try:
        score = parse_raiderio_score(form.get("score", ""))
    except ValueError as exc:
        raise ValueError(f"Mythic+ pontszám: {exc}") from exc
    char_class = form.get("class", "").strip()
    spec = form.get("spec", "").strip()
    if spec and spec not in specs_for_class(char_class):
        spec = ""  # a kaszt közben megváltozott
    character = find(data, uid)
    if uid is not None and character is None:
        raise ValueError("Ez a karakter közben törlődött (pl. a másik eszközön).")
    position = None
    if character is not None and "position" in form:
        try:
            position = parse_position(form["position"], len(data.characters))
        except ValueError as exc:
            raise ValueError(f"Hely a tervben: {exc}") from exc
    if character is None:
        character = Character(name)
        data.characters.append(character)
    character.name, character.realm, character.race = name, form.get("realm", "").strip(), form.get("race", "").strip()
    character.char_class, character.spec, character.level = char_class, spec, level
    character.item_level, character.raiderio_score = item_level, score
    if position is not None:
        move_to_position(data.characters, character, position)
    return character


def delete_character(data: LevelingData, uid: str) -> None:
    data.characters[:] = [character for character in data.characters if character.uid != uid]


def move_character(data: LevelingData, uid: str, offset: int) -> bool:
    """A karakter eggyel feljebb (offset=-1) vagy lejjebb (+1) a terv sorrendjében; igaz, ha mozdult."""
    position = position_of(data, uid)
    if position is None or not 1 <= position + offset <= len(data.characters):
        return False
    return move_to_position(data.characters, find(data, uid), position + offset)


def order_rows(data: LevelingData) -> list[OrderRow]:
    """A „Sorrend” képernyő sorai: a karakterek a terv sorrendjében, a céldátumukkal (ez a sorrendből
    adódik, így átrendezéskor látszik, mi változott)."""
    rows = []
    ends = deadlines(data.settings, len(data.characters))
    for position, (character, deadline) in enumerate(zip(data.characters, ends), start=1):
        kind = " ".join(part for part in (character.spec, character.char_class) if part)
        details = [kind] if kind else []
        details += [f"szint {format_level(character.level)}", f"céldátum: {format_date(deadline)}"]
        rows.append(OrderRow(character.uid, card_title(position, character), " · ".join(details)))
    return rows


# --- a terv beállításai -----------------------------------------------------------------


def settings_form(data: LevelingData) -> dict:
    settings = data.settings
    return {
        "start_date": format_date(settings.start_date),
        "first_target_date": format_date(settings.first_target_date),
        "last_target_date": format_date(settings.last_target_date),
        "start_level": format_level(settings.start_level),
        "target_level": format_level(settings.target_level),
        "target_item_level": "" if settings.target_item_level is None else format_item_level(settings.target_item_level),
        "region": settings.region.upper(),
        "mode": settings.mode,
        "look_ahead": data.look_ahead,
    }


def save_settings(data: LevelingData, form: dict) -> None:
    """A terv beállításai a mezőkből. ValueError (a hibák soronként), ha valamelyik hibás; ekkor az
    adatok nem változnak."""
    values, problems = {}, []
    fields = (
        ("start_date", "Szintezés kezdete", parse_date),
        ("first_target_date", "Első karakter céldátuma", parse_date),
        ("last_target_date", "Utolsó karakter céldátuma", parse_date),
        ("start_level", "Kezdőszint", parse_level),
        ("target_level", "Célszint", parse_level),
        ("target_item_level", "Célitemlevel", parse_item_level),
    )
    for key, label, parse in fields:
        try:
            values[key] = parse(str(form.get(key, "")))
        except ValueError as exc:
            problems.append(f"{label}: {exc}")
    if problems:
        raise ValueError("\n".join(problems))
    region = str(form.get("region", "")).lower()
    mode = form.get("mode", PARALLEL)
    settings = Settings(
        mode=mode if mode in MODES else PARALLEL, region=region if region in REGIONS else "eu", **values
    )
    problems = settings.errors()
    if problems:
        raise ValueError("\n".join(problems))
    data.settings = settings
    data.look_ahead = bool(form.get("look_ahead", True))
