"""A telefonos alkalmazás felülettől független része: a karakterlista kártyáinak szövegei, a
karakterek felvétele, szerkesztése, törlése és átrendezése, valamint a terv beállításai – ugyanazzal
a számolással és ellenőrzéssel, mint a gépi program (leveling.py). A Kivy-felület (main.py) csak
megjeleníti őket; így ez a rész a szokásos tesztekkel is ellenőrizhető (tests/test_mobile_plan.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from leveling import (
    MODES,
    PARALLEL,
    REGIONS,
    Character,
    LevelingData,
    Settings,
    Status,
    build_plan,
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
    parse_raiderio_score,
)
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


def cards(data: LevelingData, today: date) -> list[Card]:
    """A lista kártyái a karakterek sorrendjében (a terv szerinti helyükkel)."""
    plans = build_plan(data.settings, data.characters, today, data.spec_scores, goal_day(data, today))
    result = []
    for plan in plans:
        character = plan.character
        title = f"{plan.position}. {character.name}" + (f" ({character.realm})" if character.realm else "")
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
                title=title,
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


# --- a karakterek szerkesztése ----------------------------------------------------------


def character_form(character: Character | None) -> dict:
    """A szerkesztő mezők szövegei (új karakternél üresek)."""
    if character is None:
        return {"name": "", "realm": "", "class": "", "spec": "", "race": "", "level": "", "item_level": "", "score": ""}
    return {
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


def save_character(data: LevelingData, uid: str | None, form: dict) -> Character:
    """A szerkesztett (uid: None esetén az új, a lista végére kerülő) karakter. ValueError magyar
    üzenettel, ha valamelyik mező hibás; ekkor az adatok nem változnak."""
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
    if character is None:
        character = Character(name)
        data.characters.append(character)
    character.name, character.realm, character.race = name, form.get("realm", "").strip(), form.get("race", "").strip()
    character.char_class, character.spec, character.level = char_class, spec, level
    character.item_level, character.raiderio_score = item_level, score
    return character


def delete_character(data: LevelingData, uid: str) -> None:
    data.characters[:] = [character for character in data.characters if character.uid != uid]


def move_character(data: LevelingData, uid: str, offset: int) -> bool:
    """A karakter eggyel feljebb (offset=-1) vagy lejjebb (+1) a listában; igaz, ha mozdult."""
    characters = data.characters
    index = next((i for i, character in enumerate(characters) if character.uid == uid), None)
    if index is None or not 0 <= index + offset < len(characters):
        return False
    characters[index], characters[index + offset] = characters[index + offset], characters[index]
    return True


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
