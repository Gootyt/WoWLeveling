"""A közös adatbázis (storage.py) tesztjei: a dokumentumok, a hibák szétválasztása, a két
statisztika gyorsítótára ugyanabban a fájlban, és a korábbi változatok külön fájljainak beolvasása."""

import contextlib
import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import raiderio_ilvl_stats as mplus
import storage
import wcl_raid_ilvl_stats as wcl


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / storage.DB_NAME

    def names(self, folder=None):
        return sorted(path.name for path in (folder or self.folder).iterdir())


class DocumentTests(StorageTestCase):
    def test_documents(self):
        self.assertIsNone(storage.read_document(self.path, storage.LEVELING))
        self.assertFalse(self.path.exists())  # az olvasás nem hoz létre adatbázist
        storage.write_document(self.path, storage.LEVELING, '{"név": "Thrall"}')
        storage.write_document(self.path, storage.API_KEYS, "{}")
        storage.write_document(self.path, storage.LEVELING, '{"név": "Árvíztűrő tükörfúrógép"}')  # felülírja
        self.assertEqual(storage.read_document(self.path, storage.LEVELING), '{"név": "Árvíztűrő tükörfúrógép"}')
        storage.delete_document(self.path, storage.API_KEYS)
        self.assertIsNone(storage.read_document(self.path, storage.API_KEYS))
        self.assertEqual(self.names(), [storage.DB_NAME])  # nem marad mellette naplófájl
        self.assertTrue(storage.is_database(self.path))

    def test_paths(self):
        self.assertEqual(storage.database_path(Path("a") / "masik_terv.json"), Path("a") / "masik_terv.sqlite")
        for name in ("terv.sqlite", "terv.SQLITE3", "terv.db"):
            self.assertEqual(storage.database_path(name), Path(name))
        (self.folder / "terv.json").write_text("{}", encoding="utf-8")
        self.assertFalse(storage.is_database(self.folder / "terv.json"))
        self.assertFalse(storage.is_database(self.path))  # még nincs meg

    def test_corrupt_and_locked_databases(self):
        self.path.write_bytes(b"ez nem adatbazis" * 100)
        with self.assertRaises(storage.CorruptDatabase):
            storage.read_document(self.path, storage.LEVELING)
        with self.assertRaises(storage.CorruptDatabase):
            storage.write_document(self.path, storage.LEVELING, "{}")
        locked = self.folder / "zarolt.sqlite"
        storage.write_document(locked, storage.LEVELING, "{}")
        other = sqlite3.connect(locked)
        self.addCleanup(other.close)
        other.execute("BEGIN EXCLUSIVE")  # pl. egy másik program éppen ír bele
        with mock.patch.object(storage, "TIMEOUT", 0.1), self.assertRaises(storage.StorageError) as caught:
            storage.read_document(locked, storage.LEVELING)
        self.assertNotIsInstance(caught.exception, storage.CorruptDatabase)  # nem sérült: nem szabad félretenni
        other.rollback()
        self.assertEqual(storage.read_document(locked, storage.LEVELING), "{}")


class CacheTests(StorageTestCase):
    """A két statisztika gyorsítótára a közös adatbázisban, a szintezés adatai mellett."""

    def test_mplus_cache(self):
        storage.write_document(self.path, storage.LEVELING, "{}")
        cache = mplus.DiskCache(str(self.path), 24)
        self.assertFalse(cache.existed)
        cache.put("char:eu/ragnaros/thrall", {"ilvl": 330})
        cache.put("run:season-mn-2/1", {"level": 12})
        cache.close()
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE raiderio_cache SET fetched = fetched - 25 * 3600")  # egy nappal később
        cache = mplus.DiskCache(str(self.path), 24)
        self.assertTrue(cache.existed)
        self.assertIsNone(cache.get("char:eu/ragnaros/thrall"))  # lejárt: megnyitáskor törlődött
        self.assertEqual(cache.get("run:season-mn-2/1")["level"], 12)  # a lefutott futás nem változik: marad
        self.assertEqual(dict(cache.counts()), {"run": 1})
        cache.close()
        self.assertEqual(storage.read_document(self.path, storage.LEVELING), "{}")  # a többi adat megmaradt

    def test_old_mplus_cache_file(self):
        old = self.folder / storage.LEGACY_MPLUS
        now = int(time.time())
        lines = [
            json.dumps({"k": "char:eu/ragnaros/thrall", "v": {"ilvl": 330, "fetched": now}}),
            json.dumps({"k": "run:season-mn-2/1", "v": {"level": 12, "fetched": now}}),
            '{"k": "run:season-mn-2/2", "v": {"lev',  # a program leállításakor félbeszakadt sor
        ]
        old.write_text("\n".join(lines), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            cache = mplus.DiskCache(str(old), 24)  # parancssorból megadva: a mellette lévő adatbázisba kerül
        self.assertEqual(cache.path, str(self.folder / "raiderio_ilvl_cache.sqlite"))
        self.assertEqual(cache.get("char:eu/ragnaros/thrall")["ilvl"], 330)
        self.assertEqual(dict(cache.counts()), {"char": 1, "run": 1})
        cache.close()
        self.assertTrue(old.exists())  # a régi fájl megmarad

    def old_wcl_cache(self, version=wcl.CACHE_SCHEMA):
        """Egy 2026 októbere előtti, önálló WCL cache fájl: előtag nélküli táblák, a séma változata a
        user_versionben."""
        old = self.folder / storage.LEGACY_WCL
        with contextlib.closing(sqlite3.connect(old)) as db:
            db.executescript(wcl.CACHE_TABLES.replace("wcl_", ""))
            db.execute(f"PRAGMA user_version = {version}")
            db.execute("INSERT INTO meta VALUES ('zones', ?, ?)", (wcl.now_ms(), wcl._pack([{"id": 46}])))
            db.commit()
        return old

    def tables(self, path):
        with contextlib.closing(sqlite3.connect(path)) as db:
            return wcl._tables(db)

    def test_old_wcl_cache_file(self):
        old = self.old_wcl_cache()
        storage.write_document(self.path, storage.LEVELING, "{}")
        wcl.import_cache_file(old, self.path)
        cache = wcl.Cache(str(self.path))
        self.assertEqual(cache.get_meta("zones"), [{"id": 46}])
        cache.close()
        self.assertEqual(storage.read_document(self.path, storage.LEVELING), "{}")
        # A régi fájl közvetlenül is használható (pl. parancssorból): a táblái átneveződnek.
        cache = wcl.Cache(str(old))
        self.assertEqual(cache.get_meta("zones"), [{"id": 46}])
        cache.close()
        self.assertEqual(self.tables(old), {"schema_versions", "wcl_meta", "wcl_pages", "wcl_players"})

    def test_wcl_cache_does_not_hold_up_saving(self):
        cache = wcl.Cache(str(self.path))
        self.addCleanup(cache.db.close)
        cache.put_page("oldal", 0, {"x": 1})
        cache.put_players({("report", 1): [300]})
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE wcl_pages SET used = 0")  # régóta nem használt
        self.assertEqual(cache.get_page("oldal"), {"x": 1})
        self.assertEqual(cache.get_players([("report", 1)]), {("report", 1): [300]})
        # A program közben is tud menteni: a cache nem hagy nyitva írási tranzakciót.
        with mock.patch.object(storage, "TIMEOUT", 0.5):
            storage.write_document(self.path, storage.LEVELING, "{}")
        cache.close()
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            # A használat ideje a lezáráskor bekerült, így a régóta nem használtak törlése nem vitte el.
            self.assertGreater(db.execute("SELECT used FROM wcl_pages").fetchone()[0], 0)

    def test_outdated_wcl_cache_is_dropped(self):
        old = self.old_wcl_cache(version=wcl.CACHE_SCHEMA - 1)
        wcl.import_cache_file(old, self.path)  # a régebbi sémájú fájlból nincs mit átvenni
        cache = wcl.Cache(str(self.path))
        self.assertIsNone(cache.get_meta("zones"))
        cache.set_meta("zones", [{"id": 47}])
        cache.close()
        storage.write_document(self.path, storage.LEVELING, "{}")
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE schema_versions SET version = version - 1 WHERE component = 'wcl'")
        cache = wcl.Cache(str(self.path))
        self.assertIsNone(cache.get_meta("zones"))  # a régebbi sémájú cache törlődik...
        cache.close()
        self.assertEqual(storage.read_document(self.path, storage.LEVELING), "{}")  # ...a többi adat marad


class MigrationTests(StorageTestCase):
    def test_nothing_to_migrate(self):
        self.assertEqual(storage.migrate_legacy(self.path), storage.Migration())
        self.assertEqual(self.names(), [])  # adatbázist sem hoz létre

    def test_old_files_are_imported_and_set_aside(self):
        # A Jegyzettömb UTF-8 mentéskor BOM-ot tehet a fájl elejére.
        (self.folder / "szintezes_adatok.json").write_text('﻿{"characters": []}', encoding="utf-8")
        (self.folder / storage.LEGACY_KEYS).write_text('{"raiderio_api_key": "rio"}', encoding="utf-8")
        line = {"k": "run:season-mn-2/7", "v": {"level": 12, "fetched": 1760000000}}
        (self.folder / storage.LEGACY_MPLUS).write_text(json.dumps(line) + "\n", encoding="utf-8")
        migration = storage.migrate_legacy(self.path)
        moved = ["szintezes_adatok.json", storage.LEGACY_KEYS, storage.LEGACY_MPLUS]
        self.assertEqual([path.name for path in migration.moved], moved)
        self.assertEqual((migration.skipped, migration.problems), ([], []))
        self.assertEqual(self.names(), [storage.LEGACY_FOLDER, storage.DB_NAME])
        self.assertEqual(self.names(self.folder / storage.LEGACY_FOLDER), sorted(moved))
        self.assertEqual(storage.read_document(self.path, storage.LEVELING), '{"characters": []}')
        self.assertEqual(storage.read_document(self.path, storage.API_KEYS), '{"raiderio_api_key": "rio"}')
        cache = mplus.DiskCache(str(self.path), 24)
        self.assertEqual(cache.get("run:season-mn-2/7")["level"], 12)
        cache.close()
        self.assertEqual(storage.migrate_legacy(self.path), storage.Migration())  # másodszor már nincs mit

    def test_data_in_the_database_is_not_overwritten(self):
        storage.write_document(self.path, storage.API_KEYS, '{"raiderio_api_key": "uj"}')
        folder = self.folder / storage.LEGACY_FOLDER
        folder.mkdir()
        (folder / storage.LEGACY_KEYS).write_text("{}", encoding="utf-8")  # egy korábban félretett
        (self.folder / storage.LEGACY_KEYS).write_text('{"raiderio_api_key": "regi"}', encoding="utf-8")
        (self.folder / "szintezes_adatok.json").write_text("{}", encoding="utf-8")
        migration = storage.migrate_legacy(self.path)
        self.assertEqual([path.name for path in migration.moved], ["szintezes_adatok.json"])
        (skipped,) = migration.skipped
        self.assertRegex(skipped.name, r"^api_kulcsok\.\d{8}-\d{6}\.json$")  # a korábbi mellé, időbélyeggel
        self.assertEqual(skipped.read_text(encoding="utf-8"), '{"raiderio_api_key": "regi"}')
        self.assertEqual(storage.read_document(self.path, storage.API_KEYS), '{"raiderio_api_key": "uj"}')
        self.assertEqual(storage.read_document(self.path, storage.LEVELING), "{}")

    def test_unreadable_files_stay_in_place(self):
        (self.folder / storage.LEGACY_WCL).write_bytes(b"ez nem adatbazis" * 100)
        (self.folder / storage.LEGACY_KEYS).write_text("{}", encoding="utf-8")
        migration = storage.migrate_legacy(self.path)
        self.assertEqual([path.name for path in migration.moved], [storage.LEGACY_KEYS])
        (problem,) = migration.problems
        self.assertTrue(problem.startswith(f"{storage.LEGACY_WCL}: "), problem)
        self.assertIn(storage.LEGACY_WCL, self.names())


if __name__ == "__main__":
    unittest.main()
