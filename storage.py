"""A program összes adata egyetlen SQLite-adatbázisban, alapból a program mappájában
(szintezes_adatok.sqlite):

- documents tábla: a szintezés adatai (LEVELING: a beállítások, a karakterek, az ablakok és a
  gear ajánló beállításai – JSON-ban, ugyanabban a szerkezetben, mint korábban a
  szintezes_adatok.json fájlban), és ha a felhasználó kéri, az API-kulcsok (API_KEYS);
- raiderio_cache tábla: a M+ ilvl statisztika letöltött adatai (lásd raiderio_ilvl_stats.DiskCache);
- wcl_* táblák: a Raid ilvl statisztika letöltött adatai (lásd wcl_raid_ilvl_stats.Cache).

Minden szál a saját kapcsolatával dolgozik (a statisztikák a háttérben futnak): az SQLite zárolása
miatt egyszerre is írhatnak, egy írás pedig vagy teljesen megtörténik, vagy egyáltalán nem.

A korábbi változatok négy külön fájlba mentettek (szintezes_adatok.json, api_kulcsok.json,
raiderio_ilvl_cache.json, wcl_cache.sqlite). Az első indításkor a program beolvassa őket (lásd
migrate_legacy), és a regi_adatok mappába teszi őket, így semmi sem vész el.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DB_NAME = "szintezes_adatok.sqlite"
DB_SUFFIXES = (".sqlite", ".sqlite3", ".db")
LEVELING = "szintezes"  # a documents tábla kulcsai
API_KEYS = "api_kulcsok"
LEGACY_FOLDER = "regi_adatok"  # ide kerülnek a beolvasott régi fájlok
# A korábbi változatok fájljai (a szintezés adatainak fájlja az adatbázissal azonos nevű .json).
LEGACY_KEYS = "api_kulcsok.json"
LEGACY_MPLUS = "raiderio_ilvl_cache.json"
LEGACY_WCL = "wcl_cache.sqlite"
TIMEOUT = 30  # másodperc: ennyit vár, ha egy másik kapcsolat (pl. egy statisztika a háttérben) éppen ír
_SQLITE_HEADER = b"SQLite format 3\x00"


class StorageError(OSError):
    """Az adatbázis most nem nyitható meg, nem olvasható vagy nem írható (pl. egy másik futó
    program zárolja), magyar nyelvű üzenettel."""


class CorruptDatabase(StorageError):
    """A fájl nem adatbázis, vagy sérült."""


def _error(message: str, exc: sqlite3.Error) -> StorageError:
    """A sérülés (nem adatbázis, sérült lap) és a többi hiba (pl. zárolás) szétválasztása."""
    kind = StorageError if isinstance(exc, sqlite3.OperationalError) else CorruptDatabase
    return kind(f"{message}: {exc}")


def is_database_path(path) -> bool:
    """Adatbázis-e a megadott útvonal (a kiterjesztése alapján)."""
    return Path(path).suffix.lower() in DB_SUFFIXES


def database_path(path) -> Path:
    """Az adatbázis útvonala: a megadott, vagy egy régi adatfájl (.json) helyett a mellette lévő,
    azonos nevű .sqlite."""
    path = Path(path)
    return path if is_database_path(path) else path.with_suffix(".sqlite")


def is_database(path) -> bool:
    """SQLite-adatbázis-e a fájl (az eleje alapján); nem létező vagy üres fájlnál False."""
    try:
        with open(path, "rb") as handle:
            return handle.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


def connect(path) -> sqlite3.Connection:
    """Kapcsolat az adatbázishoz; ha még nincs, létrehozza (a documents táblával együtt). Minden
    szál a saját kapcsolatát használja. StorageError, ha a fájl nem adatbázis, vagy nem nyitható meg."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = None
    try:
        db = sqlite3.connect(str(path), timeout=TIMEOUT)
        db.execute(
            "CREATE TABLE IF NOT EXISTS documents (name TEXT PRIMARY KEY, saved INTEGER NOT NULL, body TEXT NOT NULL)"
        )
        db.commit()
    except sqlite3.Error as exc:
        if db is not None:
            db.close()
        raise _error(f"Az adatbázis nem nyitható meg ({path})", exc) from exc
    return db


def read_document(path, name: str) -> str | None:
    """Egy dokumentum szövege (None, ha nincs). Nem létező adatbázist nem hoz létre."""
    if not Path(path).exists():
        return None
    db = connect(path)
    try:
        row = db.execute("SELECT body FROM documents WHERE name = ?", (name,)).fetchone()
    except sqlite3.Error as exc:
        raise _error(f"Az adatbázis nem olvasható ({path})", exc) from exc
    finally:
        db.close()
    return None if row is None else row[0]


def write_document(path, name: str, body: str) -> None:
    """Egy dokumentum mentése (egy tranzakcióban: megszakadt mentésnél a korábbi változat marad)."""
    db = connect(path)
    try:
        with db:
            db.execute(
                "INSERT OR REPLACE INTO documents (name, saved, body) VALUES (?, ?, ?)", (name, int(time.time()), body)
            )
    except sqlite3.Error as exc:
        raise _error(f"Nem sikerült menteni az adatbázisba ({path})", exc) from exc
    finally:
        db.close()


def delete_document(path, name: str) -> None:
    db = connect(path)
    try:
        with db:
            db.execute("DELETE FROM documents WHERE name = ?", (name,))
    except sqlite3.Error as exc:
        raise _error(f"Nem sikerült törölni az adatbázisból ({path})", exc) from exc
    finally:
        db.close()


# --- A korábbi változatok fájljai -----------------------------------------------------


@dataclass
class Migration:
    """A régi fájlok beolvasásának eredménye."""

    moved: list[Path] = field(default_factory=list)  # a beolvasott fájlok új helye (a regi_adatok mappában)
    skipped: list[Path] = field(default_factory=list)  # félretéve, de nem beolvasva: ezek az adatok már megvoltak
    problems: list[str] = field(default_factory=list)  # a be nem olvasható fájlok (ezek a helyükön maradnak)


def _set_aside(file: Path) -> Path:
    """A beolvasott régi fájl áthelyezése a regi_adatok mappába (ha ott már van ilyen nevű, időbélyeggel)."""
    folder = file.parent / LEGACY_FOLDER
    folder.mkdir(exist_ok=True)
    target = folder / file.name
    if target.exists():
        target = folder / f"{file.stem}.{datetime.now():%Y%m%d-%H%M%S}{file.suffix}"
    file.replace(target)
    return target


def migrate_legacy(path) -> Migration:
    """A korábbi változatok külön fájljainak beolvasása az adatbázis mellől: a szintezés adatai (az
    adatbázissal azonos nevű .json) és az API-kulcsok, ha még nincsenek az adatbázisban, valamint a
    két statisztika gyorsítótára. A fájlok a regi_adatok mappába kerülnek (a beolvasottak a moved, a
    már az adatbázisban lévő adatokéi a skipped listába); ami nem olvasható be, a helyén marad (és a
    problems sorolja fel)."""
    path = Path(path)
    folder = path.parent
    result = Migration()

    def migrate(file: Path, load) -> None:
        if not file.is_file() or file.resolve() == path.resolve():
            return
        try:
            imported = load(file)
            (result.moved if imported else result.skipped).append(_set_aside(file))
        except (OSError, ValueError, sqlite3.Error, ImportError) as exc:
            result.problems.append(f"{file.name}: {exc}")

    def document(name: str):
        def load(file: Path) -> bool:
            if read_document(path, name) is not None:  # ami már az adatbázisban van, azt nem írja felül
                return False
            # utf-8-sig: a Jegyzettömbbel szerkesztett fájlok elején ott lehet a BOM
            write_document(path, name, file.read_bytes().decode("utf-8-sig", errors="replace"))
            return True

        return load

    def mplus_cache(file: Path) -> bool:
        import raiderio_ilvl_stats

        raiderio_ilvl_stats.import_legacy_cache(file, path)
        return True

    def wcl_cache(file: Path) -> bool:
        import wcl_raid_ilvl_stats

        wcl_raid_ilvl_stats.import_cache_file(file, path)
        return True

    migrate(path.with_suffix(".json"), document(LEVELING))
    migrate(folder / LEGACY_KEYS, document(API_KEYS))
    migrate(folder / LEGACY_MPLUS, mplus_cache)
    migrate(folder / LEGACY_WCL, wcl_cache)
    return result
