"""A karakterek itemlevelének és Mythic+ pontszámának lekérése a Raider.io-ról.

A Raider.io nyilvános API-ja kulcs nélkül is használható; karakterenként egy kérés:

    https://raider.io/api/v1/characters/profile?region=eu&realm=Draenor&name=Thrall
        &fields=gear,mythic_plus_scores_by_season:current

A válaszból ezek az adatok kellenek:

* az itemlevel: a felvett tárgyak átlagos itemlevele (gear.item_level_equipped). Ezt a
  Raider.io sokszor lefelé kerekítve, egész számként adja meg, ezért a program a tárgyak
  itemleveléből két tizedesre számolja ki, ahogy a játék is (16 hely, a kétkezes fegyver
  kétszer számít). Ha ez nem egyezik a Raider.io értékével (pl. hiányzik egy tárgy),
  a Raider.io értéke marad;
* a pontszám: az aktuális szezon összesített Mythic+ pontszáma
  (mythic_plus_scores_by_season[0].scores.all);
* a faj, a kaszt és az aktív spec (race, class, active_spec_name): ezek csak az üres
  mezőkbe kerülnek be.

A Raider.io a karakterek adatait időnként frissíti a játékból, így az adat néhány órával
(ritkán napokkal) régebbi is lehet a játékbelinél. Ezért a program a csökkenő értékeket
nem írja át magától (lásd profile_changes).

Csak a karakter nevét, realmjét és régióját küldi el.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from leveling import (
    ITEM_LEVEL_MAX,
    ITEM_LEVEL_STEP,
    RAIDERIO_MAX,
    RAIDERIO_STEP,
    Character,
    format_item_level,
    format_raiderio_score,
)
from wow_data import find_class, find_race, find_spec

PROFILE_URL = "https://raider.io/api/v1/characters/profile"
FIELDS = "gear,mythic_plus_scores_by_season:current"
TIMEOUT = 20  # másodperc
USER_AGENT = "WoWLeveling-szintezes-tervezo (Python urllib)"
GEAR_SLOTS = 16  # ennyi hely átlaga az itemlevel (az ing és a tabard nem számít)
_IGNORED_SLOTS = ("shirt", "tabard")


class RaiderioError(Exception):
    """A lekérés nem sikerült (magyar nyelvű üzenettel); a többi karakternél sem várható siker."""


class CharacterNotFound(RaiderioError):
    """A Raider.io nem ismeri a karaktert vagy a realmjét; a többi karakter lekérhető."""


@dataclass(frozen=True)
class Profile:
    """Egy karakter Raider.io-ról lekért adatai (None: nincs ilyen adat). A faj, a kaszt és a
    spec a program saját elnevezésével, ha ismeri (pl. „Death Knight”)."""

    item_level: Decimal | None
    score: Decimal | None
    race: str | None = None
    char_class: str | None = None
    spec: str | None = None  # a karakter aktív specje


def profile_url(region: str, realm: str, name: str) -> str:
    query = urllib.parse.urlencode(
        {"region": region, "realm": realm, "name": name, "fields": FIELDS}, quote_via=urllib.parse.quote, safe=",:"
    )
    return f"{PROFILE_URL}?{query}"


def fetch_profile(region: str, realm: str, name: str, timeout: float = TIMEOUT) -> Profile:
    """Egy karakter itemlevele és pontszáma a Raider.io-ról."""
    request = urllib.request.Request(
        profile_url(region, realm, name), headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except OSError as exc:  # URLError, időtúllépés, hálózati hiba
        raise RaiderioError(f"a Raider.io nem érhető el ({getattr(exc, 'reason', exc)}).") from exc
    except ValueError as exc:
        raise RaiderioError("a Raider.io válasza nem értelmezhető.") from exc
    if not isinstance(data, dict):
        raise RaiderioError("a Raider.io válasza nem értelmezhető.")
    return parse_profile(data)


def _http_error(exc: urllib.error.HTTPError) -> RaiderioError:
    """A hibás válasz magyar üzenete; a Raider.io a hiba okát JSON-ban („message”) küldi."""
    try:
        message = str(json.loads(exc.read().decode("utf-8", errors="replace")).get("message", ""))
    except (AttributeError, OSError, ValueError):
        message = ""
    if exc.code in (400, 404):
        lowered = message.casefold()
        if "realm" in lowered:  # „Failed to find realm … in region eu”
            return CharacterNotFound("ismeretlen realm a Raider.io-n")
        if "character" in lowered:  # „Could not find requested character”
            return CharacterNotFound("nem található a Raider.io-n")
    if exc.code == 429:
        return RaiderioError("a Raider.io túl sok kérést kapott, próbáld újra pár perc múlva.")
    detail = f": {message}" if message else ""
    return RaiderioError(f"a Raider.io hibával válaszolt ({exc.code}{detail}).")


def _number(value: object, maximum: Decimal) -> Decimal | None:
    """Nem negatív szám a válaszból (más értéknél None)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = Decimal(str(value))
    return number if number.is_finite() and 0 <= number <= maximum else None


def _average_item_level(items: object) -> Decimal | None:
    """A felvett tárgyak átlagos itemlevele, ahogy a játék számolja: 16 hely, a kétkezes fegyver
    (amikor nincs mellékkézben semmi) kétszer számít. None, ha nincs meg mind a 16 hely."""
    if not isinstance(items, dict):
        return None
    worn = {slot: item for slot, item in items.items() if slot not in _IGNORED_SLOTS and isinstance(item, dict)}
    levels = [item.get("item_level") for item in worn.values()]
    if "mainhand" in worn and "offhand" not in worn:
        levels.append(worn["mainhand"].get("item_level"))
    if len(levels) != GEAR_SLOTS or not all(isinstance(level, int) and level > 0 for level in levels):
        return None
    return Decimal(sum(levels)) / GEAR_SLOTS


def _item_level(gear: object) -> Decimal | None:
    if not isinstance(gear, dict):
        return None
    reported = _number(gear.get("item_level_equipped"), ITEM_LEVEL_MAX)
    if not reported:  # 0: nincs adat a felszerelésről
        return None
    if reported == reported.to_integral_value():  # lehet, hogy lefelé kerekítették
        average = _average_item_level(gear.get("items"))
        if average is not None and int(average) == reported:
            reported = average
    return reported.quantize(ITEM_LEVEL_STEP, rounding=ROUND_HALF_UP)


def _score(seasons: object) -> Decimal | None:
    if not isinstance(seasons, list) or not seasons or not isinstance(seasons[0], dict):
        return None
    scores = seasons[0].get("scores")
    score = _number(scores.get("all"), RAIDERIO_MAX) if isinstance(scores, dict) else None
    return None if score is None else score.quantize(RAIDERIO_STEP, rounding=ROUND_HALF_UP)


def _text(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def parse_profile(data: dict) -> Profile:
    """A Raider.io válaszából az itemlevel, az aktuális szezon pontszáma, a faj, a kaszt és a spec."""
    race, char_class, spec = _text(data.get("race")), _text(data.get("class")), _text(data.get("active_spec_name"))
    known_class = find_class(char_class) if char_class else None
    return Profile(
        item_level=_item_level(data.get("gear")),
        score=_score(data.get("mythic_plus_scores_by_season")),
        race=(find_race(race) or race) if race else None,
        char_class=known_class or char_class,
        spec=((find_spec(known_class, spec) if known_class else None) or spec) if spec else None,
    )


# A Raider.io-ról beírható adatok: a Character mezője → (megnevezés, formázás).
_FIELDS = {
    "item_level": ("itemlevel", format_item_level),
    "raiderio_score": ("Raider.io", format_raiderio_score),
    "race": ("faj", str),
    "char_class": ("kaszt", str),
    "spec": ("spec", str),
}


@dataclass(frozen=True)
class Change:
    """A Raider.io szerint egy karakter egyik adata erre változna."""

    character: Character
    attribute: str  # a Character mezője, lásd _FIELDS
    old: Decimal | str | None  # None vagy "": eddig üres
    new: Decimal | str

    def apply(self) -> None:
        setattr(self.character, self.attribute, self.new)

    def summary(self) -> str:
        """Az új érték, pl. „itemlevel 329,63” vagy „kaszt Shaman”."""
        label, form = _FIELDS[self.attribute]
        return f"{label} {form(self.new)}"

    def describe(self) -> str:
        """Pl. „Thrall: itemlevel 331,25 → 329,63”."""
        label, form = _FIELDS[self.attribute]
        old = "–" if self.old is None or self.old == "" else form(self.old)
        return f"{self.character.name}: {label} {old} → {form(self.new)}"


def profile_changes(character: Character, profile: Profile) -> tuple[list[Change], list[Change]]:
    """A Raider.io adataiból adódó változások: (növekedések, csökkenések).

    A növekedések (és az eddig üres értékek) magától átírhatók. A csökkenéseknél lehet,
    hogy csak a Raider.io adata régebbi a kézzel beírtnál, ezért ezekről előbb kérdezni kell.
    Ha a Raider.io csak egész itemlevelet ad, a beírt, ugyanilyen egész részű, pontosabb
    érték marad. A faj, a kaszt és a spec csak az üres mezőbe kerül be; a spec csak akkor,
    ha a karakter kasztja ugyanaz, mint a Raider.io-n.
    """
    rises, drops = [], []
    if profile.race and not character.race:
        rises.append(Change(character, "race", "", profile.race))
    if profile.char_class and not character.char_class:
        rises.append(Change(character, "char_class", "", profile.char_class))
    char_class = character.char_class or profile.char_class
    same_class = char_class is not None and (find_class(char_class) or char_class) == profile.char_class
    if profile.spec and not character.spec and same_class:
        rises.append(Change(character, "spec", "", profile.spec))
    for attribute, new in (("item_level", profile.item_level), ("raiderio_score", profile.score)):
        old = getattr(character, attribute)
        if new is None or new == old:
            continue
        if attribute == "item_level" and old is not None and new == new.to_integral_value() and new <= old < new + 1:
            continue
        change = Change(character, attribute, old, new)
        (rises if old is None or new > old else drops).append(change)
    return rises, drops
