"""A WoWLeveling addon mentett adatainak beolvasása és importálása.

Az addon (addon/WoWLeveling) a játékban minden karakterről elmenti a nevét, a realmjét, a
régióját, a faját, a kasztját, az aktív specjét, a szintjét és a tapasztalatát, a felvett
tárgyak átlagos itemlevelét és a Mythic+ pontszámát. A játék ezeket kilépéskor,
kijelentkezéskor és /reload után írja ki, Lua-értékadásként (WoWLevelingDB = {...}):

    World of Warcraft/_retail_/WTF/Account/<FIÓK>/SavedVariables/WoWLeveling.lua

A program a megadott útvonalon (a World of Warcraft mappája, a _retail_, a WTF, egy fiók
mappája vagy maga a fájl) megkeresi a fiókok mentéseit (find_saved_variables), beolvassa
őket (load_addon_data), és frissíti velük a listán lévő karaktereket (plan_import):

* A karaktereket név és realm szerint párosítja, a kis- és nagybetűktől, az ékezetektől és
  a realm szóközeitől függetlenül. A realm nélküli karaktert név szerint, ha egyértelmű.
* Csak az előző importálás óta készült mentéseket használja, így a programban kézzel átírt
  adatokat csak a játékból jövő újabb adatok írják felül.
* A szint (a tapasztalattal együtt, két tizedesre: 85,29), az itemlevel és a Mythic+
  pontszám (ha nem nulla) a játékbeli értékre változik, a karakter neve a játékbeli
  írásmódra. A realm, a faj, a kaszt és a spec csak az üres mezőbe kerül be, a spec csak
  akkor, ha a karakter kasztja is ugyanaz.
* A listán nem szereplő karaktereket a felhasználó veheti fel (add_new_characters); akiket
  nem kér, azokat a program nem kínálja fel újra.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from leveling import (
    ITEM_LEVEL_MAX,
    ITEM_LEVEL_STEP,
    LEVEL_MAX,
    LEVEL_MIN,
    LEVEL_STEP,
    RAIDERIO_MAX,
    RAIDERIO_STEP,
    Character,
    LevelingData,
    format_item_level,
    format_level,
    format_raiderio_score,
)
from wow_data import RACE_FILE_NAMES, SPEC_IDS, WOW_SPECS, find_class, find_race, find_spec

ADDON_NAME = "WoWLeveling"
ADDON_SOURCE = Path(__file__).resolve().with_name("addon") / ADDON_NAME  # a telepítendő addon
SAVED_VARIABLES = f"{ADDON_NAME}.lua"  # a mentett adatok fájlja
DB_VARIABLE = "WoWLevelingDB"  # a mentett adatok változója (lásd a .toc fájlt)
# A megadott mappa alatt ezeken a helyeken keresi a mentéseket; az első találat számít.
_SEARCH_PATTERNS = (
    SAVED_VARIABLES,  # a SavedVariables mappa
    f"SavedVariables/{SAVED_VARIABLES}",  # egy fiók mappája
    f"*/SavedVariables/{SAVED_VARIABLES}",  # az Account mappa
    f"Account/*/SavedVariables/{SAVED_VARIABLES}",  # a WTF mappa
    f"WTF/Account/*/SavedVariables/{SAVED_VARIABLES}",  # a _retail_ mappa
    f"_retail_/WTF/Account/*/SavedVariables/{SAVED_VARIABLES}",  # a World of Warcraft mappa
)
_LATEST_TIME = 32503680000  # 3000. január 1.: ennél későbbi mentési idő nem lehet valódi


class AddonError(Exception):
    """A mentett adatok nem olvashatók be (magyar nyelvű üzenettel)."""


class LuaSyntaxError(ValueError):
    """A fájl nem a várt Lua-értékadásokból áll."""


# --- A Lua-fájl beolvasása ------------------------------------------------------------

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_LONG_BRACKET = re.compile(r"\[(=*)\[")
_SPACE = re.compile(r"\s+")
_CONSTANTS = {"true": True, "false": False, "nil": None}
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "\n": "\n",
}


class _LuaReader:
    """A SavedVariables fájlok nyelvének (Lua-értékadások táblákkal, szövegekkel, számokkal,
    logikai értékekkel) beolvasója. A Lua táblák Python szótárak lesznek; a sorszám nélküli
    elemek kulcsa 1-től számozott egész, ahogy a Luában."""

    def __init__(self, text: str) -> None:
        self.text = text[1:] if text.startswith("\ufeff") else text
        self.pos = 0

    def error(self, message: str) -> LuaSyntaxError:
        line = self.text.count("\n", 0, self.pos) + 1
        return LuaSyntaxError(f"{message} ({line}. sor)")

    def at_end(self) -> bool:
        self.skip_space()
        return self.pos >= len(self.text)

    def skip_space(self) -> None:
        text = self.text
        while True:
            match = _SPACE.match(text, self.pos)
            if match:
                self.pos = match.end()
            if not text.startswith("--", self.pos):
                return
            self.pos += 2
            if _LONG_BRACKET.match(text, self.pos):
                self.long_bracket()
            else:
                end = text.find("\n", self.pos)
                self.pos = len(text) if end < 0 else end + 1

    def expect(self, token: str) -> None:
        self.skip_space()
        if not self.text.startswith(token, self.pos):
            raise self.error(f"„{token}” hiányzik")
        self.pos += len(token)

    def name(self) -> str:
        self.skip_space()
        match = _NAME.match(self.text, self.pos)
        if not match:
            raise self.error("változónév hiányzik")
        self.pos = match.end()
        return match.group()

    def long_bracket(self) -> str:
        """[[…]] vagy [==[…]==] szöveg (vagy megjegyzés) tartalma."""
        match = _LONG_BRACKET.match(self.text, self.pos)
        close = "]" + match.group(1) + "]"
        end = self.text.find(close, match.end())
        if end < 0:
            raise self.error("lezáratlan [[ ]] szöveg vagy megjegyzés")
        content = self.text[match.end() : end]
        self.pos = end + len(close)
        for newline in ("\r\n", "\n\r", "\n", "\r"):  # a nyitó utáni sortörés nem része
            if content.startswith(newline):
                return content[len(newline) :]
        return content

    def value(self) -> object:
        self.skip_space()
        text, pos = self.text, self.pos
        if pos >= len(text):
            raise self.error("hiányzó érték")
        char = text[pos]
        if char == "{":
            return self.table()
        if char in "\"'":
            return self.string()
        if char == "[" and _LONG_BRACKET.match(text, pos):
            return self.long_bracket()
        if char == "-":
            self.pos += 1
            self.skip_space()
            number = self.number()
            return -number
        if char.isdigit() or char == ".":
            return self.number()
        match = _NAME.match(text, pos)
        if match and match.group() in _CONSTANTS:
            self.pos = match.end()
            return _CONSTANTS[match.group()]
        raise self.error("ismeretlen érték")

    def number(self) -> int | float:
        match = _NUMBER.match(self.text, self.pos)
        if not match:
            raise self.error("hibás szám")
        self.pos = match.end()
        token = match.group()
        if token[:2] in ("0x", "0X"):
            return int(token, 16)
        if any(char in token for char in ".eE"):
            return float(token)
        return int(token)

    def string(self) -> str:
        text = self.text
        quote = text[self.pos]
        plain = re.compile(r"[^\\\r\n" + quote + "]+")
        self.pos += 1
        out = bytearray()
        while True:
            match = plain.match(text, self.pos)
            if match:
                out += match.group().encode("utf-8", errors="surrogateescape")
                self.pos = match.end()
            if self.pos >= len(text) or text[self.pos] in "\r\n":
                raise self.error("lezáratlan szöveg")
            char = text[self.pos]
            self.pos += 1
            if char == quote:
                return out.decode("utf-8", errors="replace")
            out += self.escape()  # char == "\\"

    def escape(self) -> bytes:
        """A \\ utáni rész értéke (a pozíció már a \\ után áll)."""
        text, pos = self.text, self.pos
        char = text[pos : pos + 1]
        if char in _ESCAPES:
            self.pos += 1
            if char == "\n" and text.startswith("\r", self.pos):  # \ + sortörés (\n\r)
                self.pos += 1
            return _ESCAPES[char].encode("utf-8")
        if char == "\r":  # \ + sortörés (\r vagy \r\n)
            self.pos += 2 if text.startswith("\n", pos + 1) else 1
            return b"\n"
        digits = re.match(r"\d{1,3}", text[pos : pos + 3])
        if digits:
            code = int(digits.group())
            if code > 255:
                raise self.error("hibás \\ddd karakterkód")
            self.pos += len(digits.group())
            return bytes([code])
        hex_digits = re.match(r"x([0-9a-fA-F]{2})", text[pos : pos + 3])
        if hex_digits:
            self.pos += 3
            return bytes([int(hex_digits.group(1), 16)])
        if char == "z":  # \z: a következő szóközök kimaradnak
            match = _SPACE.match(text, pos + 1)
            self.pos = match.end() if match else pos + 1
            return b""
        raise self.error("ismeretlen \\ jel a szövegben")

    def table(self) -> dict:
        self.pos += 1  # {
        result: dict = {}
        index = 1
        while True:
            self.skip_space()
            text, pos = self.text, self.pos
            if pos >= len(text):
                raise self.error("lezáratlan tábla")
            if text[pos] == "}":
                self.pos += 1
                return result
            if text[pos] == "[" and not _LONG_BRACKET.match(text, pos):  # [kulcs] = érték
                self.pos += 1
                key = self.value()
                if key is None or (isinstance(key, float) and math.isnan(key)):
                    raise self.error("hibás táblakulcs")
                if isinstance(key, float) and key.is_integer():
                    key = int(key)
                self.expect("]")
                self.expect("=")
                self._store(result, key, self.value())
            else:
                match = _NAME.match(text, pos)
                after = match and _SPACE.match(text, match.end())
                equals = (after.end() if after else match.end()) if match else -1
                if match and match.group() not in _CONSTANTS and text.startswith("=", equals) and not text.startswith(
                    "==", equals
                ):  # név = érték
                    self.pos = equals + 1
                    self._store(result, match.group(), self.value())
                else:  # sorszám nélküli elem
                    self._store(result, index, self.value())
                    index += 1
            self.skip_space()
            if self.pos >= len(self.text):
                raise self.error("lezáratlan tábla")
            if self.text.startswith((",", ";"), self.pos):
                self.pos += 1
            elif not self.text.startswith("}", self.pos):
                raise self.error("„,” vagy „}” hiányzik")

    @staticmethod
    def _store(table: dict, key: object, value: object) -> None:
        if value is None:  # a Luában a nil értékű kulcs nem létezik
            table.pop(key, None)
        else:
            table[key] = value


def parse_lua(text: str) -> dict:
    """Egy SavedVariables fájl értékadásai: változónév → érték (a Lua táblák szótárak)."""
    reader = _LuaReader(text)
    values = {}
    try:
        while not reader.at_end():
            name = reader.name()
            reader.expect("=")
            value = reader.value()
            if value is None:
                values.pop(name, None)
            else:
                values[name] = value
            reader.skip_space()
            if reader.text.startswith(";", reader.pos):
                reader.pos += 1
    except RecursionError:
        raise reader.error("túl mélyen egymásba ágyazott táblák") from None
    return values


# --- Egy karakter mentett adatai -------------------------------------------------------


def _fold(text: str) -> str:
    """Kisbetűs, ékezet nélküli alak („Zôltan” → „zoltan”)."""
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def name_key(name: str) -> str:
    return _fold(name)


def realm_key(realm: str) -> str:
    """A realm összehasonlítási kulcsa: csak a betűk és a számok („Twisting Nether” =
    „TwistingNether” = „twisting-nether”)."""
    return "".join(char for char in _fold(realm) if char.isalnum())


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decimal(value: object, maximum: Decimal, step: Decimal) -> Decimal | None:
    """Pozitív szám a megadott pontossággal (más értéknél, és ha túl nagy: None)."""
    if not _is_number(value) or value <= 0:
        return None
    number = Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP)
    return number if number <= maximum else None


@dataclass(frozen=True)
class Snapshot:
    """Egy karakter adatai az addon mentéséből. A faj, a kaszt és a spec a program
    elnevezésével (pl. „Undead”, „Death Knight”); "", ha nem ismert."""

    name: str
    realm: str
    region: str  # pl. "eu"
    race: str
    char_class: str
    spec: str
    level: Decimal | None  # a tapasztalattal együtt, pl. 85,29
    item_level: Decimal | None
    score: Decimal | None  # a Mythic+ pontszám (nulla helyett None)
    updated: int  # a mentés ideje (Unix-idő; 0, ha nem ismert)

    @property
    def key(self) -> str:
        """A karakter azonosítója a program adatfájljában (pl. „twistingnether/zoltan”)."""
        return f"{realm_key(self.realm)}/{name_key(self.name)}"

    def describe(self) -> str:
        """Pl. „Zôltan (Twisting Nether) – szint: 85,29, Orc Shaman, Enhancement, itemlevel 301,56”."""
        parts = [] if self.level is None else [f"szint: {format_level(self.level)}"]
        kind = " ".join(part for part in (self.race, self.char_class) if part)
        parts += [part for part in (kind, self.spec) if part]
        if self.item_level is not None:
            parts.append(f"itemlevel {format_item_level(self.item_level)}")
        return f"{self.name} ({self.realm})" + (" – " + ", ".join(parts) if parts else "")


def _class_of(entry: dict) -> str:
    localized = _text(entry.get("class"))
    return find_class(_text(entry.get("classFile"))) or find_class(localized) or localized


def _race_of(entry: dict) -> str:
    race_file = _text(entry.get("raceFile"))
    localized = _text(entry.get("race"))
    return RACE_FILE_NAMES.get(race_file) or find_race(race_file) or find_race(localized) or localized


def _spec_of(entry: dict, char_class: str) -> str:
    """Az aktív spec, ha a kaszt egyik ismert specje (a kezdő karakterek „Initial” specje nem)."""
    spec_id = entry.get("specID")
    known = SPEC_IDS.get(spec_id) if _is_number(spec_id) else None
    if known is not None and known[0] == char_class:
        return known[1]
    if char_class in WOW_SPECS:
        return find_spec(char_class, _text(entry.get("spec"))) or ""
    return ""


def _level_of(entry: dict) -> Decimal | None:
    """A szint a tapasztalattal együtt: a tizedesek a következő szintig megszerzett
    tapasztalat lefelé kerekített százaléka (85-ös szint, 29,99% → 85,29)."""
    level = entry.get("level")
    if not _is_number(level) or level < 1:
        return None
    value = Decimal(int(level))
    xp, xp_max = entry.get("xp"), entry.get("xpMax")
    if _is_number(xp) and _is_number(xp_max) and xp_max > 0 and xp > 0:
        value += Decimal(min(int(xp * 100 // xp_max), 99)) / 100
    return min(max(value, LEVEL_MIN), LEVEL_MAX).quantize(LEVEL_STEP)


def _snapshot(entry: dict) -> Snapshot | None:
    name, realm = _text(entry.get("name")), _text(entry.get("realm"))
    if not name or not realm:
        return None
    char_class = _class_of(entry)
    updated = entry.get("updated")
    return Snapshot(
        name=name,
        realm=realm,
        region=_text(entry.get("region")).lower(),
        race=_race_of(entry),
        char_class=char_class,
        spec=_spec_of(entry, char_class),
        level=_level_of(entry),
        item_level=_decimal(entry.get("itemLevel"), ITEM_LEVEL_MAX, ITEM_LEVEL_STEP),
        score=_decimal(entry.get("mythicPlusScore"), RAIDERIO_MAX, RAIDERIO_STEP),
        updated=int(updated) if _is_number(updated) and 0 <= updated <= _LATEST_TIME else 0,
    )


def snapshots_from_db(db: object) -> list[Snapshot]:
    """A WoWLevelingDB tábla karakterei (a hiányos bejegyzések nélkül)."""
    characters = db.get("characters") if isinstance(db, dict) else None
    entries = characters.values() if isinstance(characters, dict) else ()
    snapshots = (_snapshot(entry) for entry in entries if isinstance(entry, dict))
    return [snapshot for snapshot in snapshots if snapshot is not None]


# --- A mentések megkeresése és beolvasása ----------------------------------------------


def game_folder(path: str | os.PathLike) -> Path | None:
    """A játék (retail) mappája, amelyben az Interface és a WTF mappa van: a megadott mappa
    vagy az, amelyikben a megadott fájl vagy mappa van (pl. a WTF fölötti). A World of
    Warcraft mappájánál a benne lévő _retail_ mappa. None, ha nem található."""
    path = Path(path).expanduser()
    for folder in (path, *path.parents):
        if (folder / "_retail_").is_dir():
            return folder / "_retail_"
        if folder.name.casefold() == "_retail_" or (folder / "WTF").is_dir() or (folder / "Interface").is_dir():
            return folder
    return None


def default_wow_folders() -> list[Path]:
    """A World of Warcraft szokásos telepítési helyei közül a létezők."""
    if sys.platform == "win32":
        bases = [os.environ.get(name) for name in ("ProgramFiles(x86)", "ProgramFiles")]
        candidates = [Path(base) / "World of Warcraft" for base in bases if base]
        candidates += [Path("C:/World of Warcraft"), Path("C:/Games/World of Warcraft")]
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/World of Warcraft")]
    else:
        candidates = []
    return [folder for folder in candidates if folder.is_dir()]


def find_saved_variables(path: str | os.PathLike) -> list[Path]:
    """A megadott útvonalon (vagy alatta) lévő mentések, fiókonként egy-egy fájl.
    AddonError, ha az útvonal nem létezik, vagy nincs rajta mentés."""
    path = Path(path).expanduser()
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise AddonError(f"Nem létezik ez a mappa vagy fájl: {path}")
    folders = [path]
    game = game_folder(path)
    if game is not None and game != path:
        folders.append(game)
    for folder in folders:
        for pattern in _SEARCH_PATTERNS:
            found = sorted(item for item in folder.glob(pattern) if item.is_file())
            if found:
                return found
    raise AddonError(
        f"Még nincs mentett adat ({SAVED_VARIABLES}) ezen a helyen: {path}\n"
        "Telepítsd az addont, lépj be vele a játékba, majd lépj ki (vagy írd be: /reload). "
        "Ha máshová telepítetted a játékot, add meg a World of Warcraft mappáját."
    )


@dataclass
class AddonData:
    """Az addon beolvasott mentései."""

    snapshots: list[Snapshot]  # karakterenként a legújabb mentés
    files: list[Path]  # a beolvasott fájlok (fiókonként egy)
    problems: list[str] = field(default_factory=list)  # a nem olvasható fájlok és az addon által jelzett hibák

    @property
    def saved_at(self) -> datetime | None:
        """A legutóbbi mentés ideje (helyi idő)."""
        latest = max((snapshot.updated for snapshot in self.snapshots), default=0)
        return datetime.fromtimestamp(latest) if latest else None


def load_addon_data(path: str | os.PathLike) -> AddonData:
    """Az addon összes mentése a megadott útvonalról (lásd find_saved_variables). Ha egy
    karakter több fiók mentésében is szerepel, a legújabb számít. AddonError, ha nincs
    mentés, vagy egyik sem olvasható be."""
    files = find_saved_variables(path)
    latest: dict[str, Snapshot] = {}
    problems = []
    failed = 0  # a nem olvasható fájlok száma
    for file in files:
        try:
            values = parse_lua(file.read_bytes().decode("utf-8", errors="surrogateescape"))
        except OSError as exc:
            problems.append(f"{file} nem olvasható ({exc.strerror or exc})")
            failed += 1
            continue
        except LuaSyntaxError as exc:
            problems.append(f"{file} nem az addon mentése, vagy sérült ({exc})")
            failed += 1
            continue
        db = values.get(DB_VARIABLE)
        for snapshot in snapshots_from_db(db):
            known = latest.get(snapshot.key)
            if known is None or snapshot.updated > known.updated:
                latest[snapshot.key] = snapshot
        error = _text(db.get("lastError")) if isinstance(db, dict) else ""
        if error:
            problems.append(f"az addon hibát jelzett: {error}")
    if failed == len(files):
        raise AddonError("A mentett adatok nem olvashatók be: " + "; ".join(problems))
    snapshots = sorted(latest.values(), key=lambda snapshot: (name_key(snapshot.name), realm_key(snapshot.realm)))
    return AddonData(snapshots, files, problems)


def install_addon(game: Path) -> Path:
    """Az addon bemásolása (vagy frissítése) a játék Interface/AddOns mappájába; a
    telepített addon mappája."""
    target = game / "Interface" / "AddOns" / ADDON_NAME
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(ADDON_SOURCE.iterdir()):
        if source.is_file() and source.suffix in (".toc", ".lua"):
            shutil.copyfile(source, target / source.name)
    return target


# --- Importálás ------------------------------------------------------------------------

# Az addonból beírható adatok: a Character mezője → (megnevezés, formázás).
_FIELDS = {
    "name": ("név", str),
    "realm": ("realm", str),
    "level": ("szint", format_level),
    "item_level": ("itemlevel", format_item_level),
    "raiderio_score": ("Raider.io", format_raiderio_score),
    "race": ("faj", str),
    "char_class": ("kaszt", str),
    "spec": ("spec", str),
}


@dataclass(frozen=True)
class Change:
    """Az addon szerint egy karakter egyik adata erre változik."""

    character: Character
    attribute: str  # a Character mezője, lásd _FIELDS
    old: Decimal | str | None  # None vagy "": eddig üres
    new: Decimal | str

    def apply(self) -> None:
        setattr(self.character, self.attribute, self.new)

    def describe(self) -> str:
        """Pl. „Zôltan: szint 84,50 → 85,29”."""
        label, form = _FIELDS[self.attribute]
        old = "–" if self.old is None or self.old == "" else form(self.old)
        return f"{self.character.name}: {label} {old} → {form(self.new)}"


@dataclass
class ImportPlan:
    """Az importálás eredménye (lásd plan_import)."""

    changes: list[Change] = field(default_factory=list)  # a lista karaktereinek változásai
    imported: dict[str, int] = field(default_factory=dict)  # a felhasznált mentések: kulcs → ideje
    matched: int = 0  # hány mentés tartozik a lista karaktereihez
    new: list[Snapshot] = field(default_factory=list)  # a listán nem szereplő karakterek
    skipped: list[Snapshot] = field(default_factory=list)  # a korábban nem kért, listán nem szereplők
    unskip: list[str] = field(default_factory=list)  # a korábban nem kért, de azóta felvett karakterek

    def updated_count(self) -> int:
        """Hány karakter adata változik."""
        return len({change.character.uid for change in self.changes})

    def apply(self, data: LevelingData) -> None:
        for change in self.changes:
            change.apply()
        data.addon_imported.update(self.imported)
        data.addon_skipped = [key for key in data.addon_skipped if key not in self.unskip]


def _matching(characters: list[Character], snapshot: Snapshot, unique_name: bool) -> list[Character]:
    """A lista karakterei, amelyekhez a mentés tartozik: az azonos nevűek és realmúak, vagy
    ha ilyen nincs, az egyetlen azonos nevű, realm nélküli (ha a név a mentésekben is egyedi)."""
    name = name_key(snapshot.name)
    same_name = [character for character in characters if name_key(character.name) == name]
    realm = realm_key(snapshot.realm)
    same_realm = [character for character in same_name if realm_key(character.realm) == realm]
    if same_realm:
        return same_realm
    without_realm = [character for character in same_name if not character.realm.strip()]
    return without_realm if unique_name and len(without_realm) == 1 else []


def _changes(character: Character, snapshot: Snapshot) -> list[Change]:
    changes = []

    def change(attribute: str, new: Decimal | str | None) -> None:
        old = getattr(character, attribute)
        if new is not None and new != "" and new != old:
            changes.append(Change(character, attribute, old, new))

    change("name", snapshot.name)
    if not character.realm.strip():
        change("realm", snapshot.realm)
    change("level", snapshot.level)
    change("item_level", snapshot.item_level)
    change("raiderio_score", snapshot.score)
    if not character.race:
        change("race", snapshot.race)
    if not character.char_class:
        change("char_class", snapshot.char_class)
    char_class = character.char_class or snapshot.char_class
    if not character.spec and (find_class(char_class) or char_class) == snapshot.char_class:
        change("spec", snapshot.spec)
    return changes


def plan_import(
    characters: list[Character], snapshots: list[Snapshot], imported: dict[str, int], skipped: list[str]
) -> ImportPlan:
    """Mi változik a karaktereknél az addon mentései szerint (lásd a modul leírását).

    imported: az eddig felhasznált mentések ideje (LevelingData.addon_imported); skipped: a
    felhasználó által nem kért karakterek (LevelingData.addon_skipped).
    """
    plan = ImportPlan()
    name_counts = Counter(name_key(snapshot.name) for snapshot in snapshots)
    for snapshot in snapshots:
        key = snapshot.key
        targets = _matching(characters, snapshot, name_counts[name_key(snapshot.name)] == 1)
        if not targets:
            (plan.skipped if key in skipped else plan.new).append(snapshot)
            continue
        plan.matched += 1
        if key in skipped:
            plan.unskip.append(key)
        if key in imported and snapshot.updated <= imported[key]:
            continue  # ezt a mentést már beolvasta
        for character in targets:
            plan.changes += _changes(character, snapshot)
        plan.imported[key] = snapshot.updated
    plan.new.sort(key=lambda snapshot: (-(snapshot.level or 0), name_key(snapshot.name)))
    return plan


def new_character(snapshot: Snapshot, default_level: Decimal) -> Character:
    """Új karakter a mentés adataival (szint nélkül a megadott szinttel)."""
    return Character(
        name=snapshot.name,
        realm=snapshot.realm,
        race=snapshot.race,
        char_class=snapshot.char_class,
        spec=snapshot.spec,
        level=snapshot.level if snapshot.level is not None else default_level,
        item_level=snapshot.item_level,
        raiderio_score=snapshot.score,
    )


def add_new_characters(data: LevelingData, offered: list[Snapshot], chosen: list[Snapshot]) -> list[Character]:
    """A felkínált új karakterek közül a választottak felvétele a lista végére (a felkínálás
    sorrendjében); a többit a program megjegyzi, és nem kínálja fel újra. A felvett karakterek."""
    added = []
    for snapshot in offered:
        if snapshot in chosen:
            character = new_character(snapshot, data.settings.start_level)
            data.characters.append(character)
            data.addon_imported[snapshot.key] = snapshot.updated
            added.append(character)
        elif snapshot.key not in data.addon_skipped:
            data.addon_skipped.append(snapshot.key)
    return added
