#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wcl_raid_ilvl_stats.py
======================
Warcraft Logs (v2 GraphQL API) alapú statisztika: milyen item levellel ölik meg
SIKERESEN az aktuális raid bossait Normal, Heroic és Mythic nehézségen.
Bossonként és nehézségenként: kill-ek száma, átlag, medián, 25. percentilis (P25),
minimum, maximum.

A WoW szintezés tervezőben
  A program a tervező (wow_leveling.py) „Raid ilvl statisztika” ablakából is fut: ugyanez
  a számolás a háttérben, az eredmény táblázatokban látszik, a Ctrl+C helyett pedig a
  „Leállítás” gomb állítja meg (lásd run(), OUTPUT és STOP). Önállóan, parancssorból
  ugyanúgy működik, mint eddig. A requests csomag nélkül a httpcompat.py-t használja
  (ugyanazok a hívások a szabványos könyvtár urllib moduljával).

Mérőszámok
  * alapértelmezett: a kill "raid átlag" item levele (ReportFight.averageItemLevel,
    vagyis a harcban részt vevő játékosok átlagos ilvl-je) - minden talált kill-re
  * --players N: ezen felül bossonként/nehézségenként legfeljebb N kill
    játékosainak EGYÉNI item levele (report.playerDetails). Drága: kb. 11 API
    pont / kill, az óránkénti keret 3600 pont (elfogyáskor a script kivár).

Mintavétel: az API a zóna reportjait feltöltési sorrendben adja, összes darabszám
nélkül, ezért a script az utolsó --days napot időablakokra bontja, és mindegyikből
olvas egy oldalnyi reportot - így a minta a teljes időszakot lefedi. Előtte egy
teszt-lekéréssel megnézi, hogyan szűr az API időre (ha kell, napos ablakokra vált).
Ugyanazt a kill-t több logger is feltöltheti - ezeket a script összevonja.

A WCL a raid zónájába sorolja a Lair / world bossokat is (Nymrissa Wavecaller,
Kith'ix) - ezeket alapból kihagyja, lásd --exclude.

Cache: a letöltött adatokat egy SQLite adatbázisba menti, alapból a tervezőébe (a script
melletti szintezes_adatok.sqlite wcl_ előtagú tábláiba, így a tervező ablaka és a parancssor
közös cache-t használ; a korábbi wcl_cache.sqlite fájlt a tervező a következő indításakor
beolvassa). Egy újabb futás csak azt kéri le az API-tól, ami még nincs meg:
  * report-oldalak időablakonként. Az ablakok rögzített rácsra illeszkednek (a még
    folyamatban lévő legutolsó ablak kimarad), így ugyanazzal az ablakhosszal
    (--days / --pages arány) futtatva a már letöltött ablakok a cache-ből jönnek,
    és csak az újak töltődnek le. A lezárulásuk után 12 órán belül letöltött
    ablakokhoz még kerülhettek fel logok: ezeket --cache-ttl óra (alap: 6) után
    újra lekéri; a később letöltött ablakok véglegesek.
  * a --players egyéni item levelei kill-enként. A kill-minta is futásról futásra
    stabil, így többnyire a korábban már letöltött kill-ek kerülnek bele újra.
  * a zónalista (1 napig) és az időszűrés-teszt eredménye (7 napig).
  A 30 napja nem használt bejegyzéseket magától törli.
  --refresh: minden újra letöltése, --no-cache: kikapcsolás, --cache FILE: másik fájl.

API kulcs (egyszer kell): https://www.warcraftlogs.com/api/clients -> "Create Client"
  Name: bármi, Redirect URL: pl. http://localhost, "Public Client": NE pipáld be.
  A Client ID / Client Secret megadása:
    cmd:         set WCL_CLIENT_ID=xxxx
                 set WCL_CLIENT_SECRET=yyyy
    PowerShell:  $env:WCL_CLIENT_ID="xxxx"; $env:WCL_CLIENT_SECRET="yyyy"
    vagy:        --client-id xxxx --client-secret yyyy

Használat (előtte egyszer: pip install requests - nem kötelező, nélküle a httpcompat.py fut)
  python wcl_raid_ilvl_stats.py --probe            ellenőrzés, nyers válaszok -> wcl_probe_output.json
  python wcl_raid_ilvl_stats.py                    utolsó 7 nap, raid átlag ilvl
  python wcl_raid_ilvl_stats.py --days 14 --pages 150 --csv stat.csv
  python wcl_raid_ilvl_stats.py --players 5        + játékosonkénti ilvl (kb. 1300 API pont)
  python wcl_raid_ilvl_stats.py --save kills.json  a letöltött kill-lista mentése
  python wcl_raid_ilvl_stats.py --load kills.json  újraszámolás report-letöltés nélkül
  python wcl_raid_ilvl_stats.py --exclude ""       a Lair / world bossok is kerüljenek bele
  python wcl_raid_ilvl_stats.py --list-zones       zónák listája (ha kézzel kell --zone-id)
  python wcl_raid_ilvl_stats.py --refresh          minden újra letöltése (a cache frissül)
  python wcl_raid_ilvl_stats.py --no-cache         cache nélkül (nem olvas belőle, nem ír bele)
"""

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import statistics
import sys
import threading
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime

try:
    import requests
except ImportError:        # a requests nélkül a szabványos urllib-bel (httpcompat.py)
    import httpcompat as requests

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"

DIFFICULTIES = {3: "Normal", 4: "Heroic", 5: "Mythic"}   # Warcraft Logs difficulty ID-k
MYTHIC_PLUS_DIFFICULTY = 10
NON_RAID_ZONE_WORDS = ("mythic+", "world boss", "lair", "delve")
DEFAULT_EXCLUDE = "Nymrissa,Kith'ix"    # a WCL a raid zónájába sorolja őket, de nem raid bossok
PLAYER_DETAILS_COST = 11                # kb. ennyi API pont egy kill playerDetails-e (probe alapján)
REPORT_CODE_RE = re.compile(r"^[A-Za-z0-9]+$")
COMPLEXITY_RE = re.compile(r"complexity should be (\d+) but got (\d+)", re.IGNORECASE)
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS

# A tervező adatbázisa a script mellett (storage.DB_NAME): a tervező ablakáé és a parancssoré a közös cache.
DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "szintezes_adatok.sqlite")
CACHE_SCHEMA = 1            # ha a lekérdezések vagy a tárolt formátum változik, növeld (a régi cache törlődik)
CACHE_SETTLE_HOURS = 12     # a lezárulása után legalább ennyivel letöltött időablak végleges
CACHE_KEEP_DAYS = 30        # az ennyi napja nem használt bejegyzések törlődnek
ZONES_TTL_HOURS = 24        # a zónalista ennyi ideig jön a cache-ből
TIMEFILTER_TTL_DAYS = 7     # az időszűrés-teszt eredménye ennyi ideig jön a cache-ből

_mean = getattr(statistics, "fmean", statistics.mean)

STOP = threading.Event()    # a tervező „Leállítás” gombja: a következő lekérés vagy várakozás Stopped-ot dob
OUTPUT = None               # ha meg van adva (a tervező ablaka), a kiírások ide mennek a konzol helyett


class Stopped(Exception):
    """A STOP beállítása után (a tervező Ctrl+C-je): a letöltés leáll, az eddigi adatokkal számol tovább."""


class StatsError(Exception):
    """A futást megszakító hiba; parancssorból futtatva ezzel a szöveggel lép ki."""


def out(message="", err=False):
    """Kiírás a konzolra - vagy, ha a tervező ablakából fut, oda (OUTPUT)."""
    if OUTPUT is not None:
        OUTPUT(str(message))
    else:
        print(message, file=sys.stderr if err else sys.stdout)


def pause(seconds):
    """Várakozás (mint a time.sleep), amit a STOP félbeszakít: ekkor Stopped."""
    if STOP.wait(max(0.0, seconds)):
        raise Stopped()

RATE_FIELDS = "rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }"

ZONES_QUERY = """
query {
  __RATE__
  worldData {
    expansions {
      id
      name
      zones {
        id
        name
        frozen
        difficulties { id name }
        encounters { id name }
      }
    }
  }
}
""".replace("__RATE__", RATE_FIELDS)

REPORTS_QUERY = """
query ($zoneID: Int!, $page: Int!, $limit: Int!, $startTime: Float!, $endTime: Float!) {
  __RATE__
  reportData {
    reports(zoneID: $zoneID, page: $page, limit: $limit,
            startTime: $startTime, endTime: $endTime) {
      has_more_pages
      data {
        code
        startTime
        endTime
        guild { id server { region { slug } } }
        fights(killType: Kills) {
          id
          encounterID
          difficulty
          kill
          size
          startTime
          endTime
          averageItemLevel
        }
      }
    }
  }
}
""".replace("__RATE__", RATE_FIELDS)

PROBE_FIGHT_QUERY = """
query ($code: String!, $fightIDs: [Int]!) {
  __RATE__
  reportData {
    report(code: $code) {
      code
      title
      startTime
      zone { id name }
      fights(fightIDs: $fightIDs) {
        id name encounterID difficulty kill size startTime endTime
        averageItemLevel friendlyPlayers
      }
      playerDetails(fightIDs: $fightIDs)
    }
  }
}
""".replace("__RATE__", RATE_FIELDS)


# --------------------------------------------------------------------------- API

class WCLError(Exception):
    """GraphQL / HTTP hiba; a .data a részleges válasz (ha volt)."""

    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data or {}


def _retry_after(resp):
    try:
        value = resp.headers.get("Retry-After")
        return max(1, int(float(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


class WCLClient:
    def __init__(self, client_id, client_secret):
        self.session = requests.Session()
        self.session.headers["Authorization"] = "Bearer " + self._get_token(client_id, client_secret)
        self.rate = None          # utolsó rateLimitData
        self.rate_time = 0.0      # mikor érkezett
        self.last_cost = 0.0      # az utolsó lekérés ára (pont)
        self.calls = 0
        self.report_limit_cap = None   # a komplexitási korlát miatt megtanult max oldalméret

    @staticmethod
    def _get_token(client_id, client_secret):
        try:
            resp = requests.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                                 auth=(client_id, client_secret), timeout=30)
        except requests.RequestException as exc:
            raise StatsError(f"Nem érem el a Warcraft Logs-ot: {exc}")
        if resp.status_code != 200:
            raise StatsError(f"Token kérés sikertelen (HTTP {resp.status_code}) - jó a Client ID / Secret?\n"
                     f"{resp.text[:300]}")
        return resp.json()["access_token"]

    def _seconds_to_reset(self):
        if not self.rate:
            return 0.0
        return max(0.0, (self.rate.get("pointsResetIn") or 0) - (time.time() - self.rate_time))

    def _wait_for_budget(self):
        """Ha a következő lekérés már nem férne bele az óránkénti keretbe, kivárja a nullázódást."""
        if not self.rate:
            return
        limit = self.rate.get("limitPerHour") or 0
        spent = self.rate.get("pointsSpentThisHour") or 0
        reset_in = self._seconds_to_reset()
        if limit and reset_in > 0 and spent + max(0.03 * limit, 2 * self.last_cost) >= limit:
            out(f"  ... elfogyott az óránkénti API keret ({spent:.0f}/{limit} pont), "
                  f"várok {reset_in / 60:.1f} percet a nullázódásig", err=True)
            pause(reset_in + 5)
            self.rate = None

    def _update_rate(self, rate):
        old = (self.rate or {}).get("pointsSpentThisHour")
        new = rate.get("pointsSpentThisHour") or 0
        if old is not None and new >= old:
            self.last_cost = new - old
        self.rate, self.rate_time = rate, time.time()

    def query(self, query, variables=None, attempts=6):
        payload = {"query": query, "variables": variables or {}}
        for attempt in range(1, attempts + 1):
            if STOP.is_set():
                raise Stopped()
            self._wait_for_budget()
            try:
                resp = self.session.post(API_URL, json=payload, timeout=120)
            except requests.RequestException as exc:
                wait = 10 * attempt
                out(f"  ! hálózati hiba ({exc}), újra {wait} mp múlva", err=True)
                pause(wait)
                continue
            self.calls += 1
            if resp.status_code == 429:
                wait = _retry_after(resp)
                if wait is None:
                    wait = self._seconds_to_reset() + 5 if self.rate else 60
                out(f"  ! HTTP 429 (API keret), várok {wait / 60:.1f} percet", err=True)
                pause(wait)
                self.rate = None
                continue
            if resp.status_code >= 500:
                wait = 10 * attempt
                out(f"  ! HTTP {resp.status_code}, újra {wait} mp múlva", err=True)
                pause(wait)
                continue
            if resp.status_code != 200:
                raise WCLError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            try:
                body = resp.json()
            except ValueError:
                raise WCLError(f"nem JSON válasz: {resp.text[:300]}")
            data = body.get("data") or {}
            if data.get("rateLimitData"):
                self._update_rate(data["rateLimitData"])
            if body.get("errors"):
                msg = "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e)
                                for e in body["errors"])
                raise WCLError(msg, data)
            return data
        raise WCLError("többszöri próbálkozás után sem sikerült a lekérés")

    def usage(self):
        if not self.rate:
            return "API pont: ?"
        return (f"API pont: {self.rate.get('pointsSpentThisHour') or 0:.0f}"
                f"/{self.rate.get('limitPerHour', '?')} ebben az órában")


# ------------------------------------------------------------------------- cache

# A cache táblái wcl_ előtaggal, hogy egy közös adatbázisban (a tervezőé, szintezes_adatok.sqlite)
# se ütközzenek más táblákkal; a sémájuk változata a schema_versions táblában van.
CACHE_TABLES = """
CREATE TABLE IF NOT EXISTS wcl_meta (key TEXT PRIMARY KEY, saved INTEGER NOT NULL, value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS wcl_pages (key TEXT PRIMARY KEY, w_end INTEGER NOT NULL,
    fetched INTEGER NOT NULL, used INTEGER NOT NULL, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS wcl_players (report TEXT NOT NULL, fight INTEGER NOT NULL,
    used INTEGER NOT NULL, body BLOB NOT NULL, PRIMARY KEY (report, fight));
"""
CACHE_NAMES = ("meta", "pages", "players")  # a táblák az előtag nélkül (a régi cache fájlokban így hívták őket)
VERSIONS_TABLE = "CREATE TABLE IF NOT EXISTS schema_versions (component TEXT PRIMARY KEY, version INTEGER NOT NULL)"


def _tables(db, schema="main"):
    return {row[0] for row in db.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table'")}


def prepare_cache_db(db):
    """A cache táblái a megnyitott adatbázisban: ha a sémájuk régebbi, törlődnek és újra létrejönnek.
    Egy régi, önálló cache fájl (előtag nélküli táblák, PRAGMA user_version) tábláit átnevezi."""
    db.execute(VERSIONS_TABLE)
    tables = _tables(db)
    if "pages" in tables and "wcl_pages" not in tables:  # a 2026. októberi előtti cache fájl
        if db.execute("PRAGMA user_version").fetchone()[0] == CACHE_SCHEMA:
            for name in CACHE_NAMES:
                if name in tables:
                    db.execute(f"ALTER TABLE {name} RENAME TO wcl_{name}")
            db.execute("INSERT OR REPLACE INTO schema_versions (component, version) VALUES ('wcl', ?)", (CACHE_SCHEMA,))
        else:
            db.executescript("DROP TABLE IF EXISTS meta; DROP TABLE IF EXISTS pages; DROP TABLE IF EXISTS players;")
    row = db.execute("SELECT version FROM schema_versions WHERE component = 'wcl'").fetchone()
    if row is None or row[0] != CACHE_SCHEMA:
        db.executescript("DROP TABLE IF EXISTS wcl_meta; DROP TABLE IF EXISTS wcl_pages; DROP TABLE IF EXISTS wcl_players;")
    db.executescript(CACHE_TABLES)
    db.execute("INSERT OR REPLACE INTO schema_versions (component, version) VALUES ('wcl', ?)", (CACHE_SCHEMA,))
    db.commit()


def import_cache_file(source, target):
    """Egy régi, önálló cache fájl (wcl_cache.sqlite) adatai a target adatbázis cache tábláiba; a
    target-ben már meglévő bejegyzéseket felülírja. Régebbi sémájú fájlból nincs mit átvenni."""
    db = sqlite3.connect(str(target), timeout=30)
    try:
        prepare_cache_db(db)
        db.execute("ATTACH DATABASE ? AS old", (str(source),))
        try:
            tables = _tables(db, "old")
            version = db.execute("PRAGMA old.user_version").fetchone()[0]
            prefixed = "wcl_pages" in tables
            if prefixed:
                row = (db.execute("SELECT version FROM old.schema_versions WHERE component = 'wcl'").fetchone()
                       if "schema_versions" in tables else None)
                version = row[0] if row else None
            if version == CACHE_SCHEMA:
                with db:
                    for name in CACHE_NAMES:
                        table = f"wcl_{name}" if prefixed else name
                        if table in tables:
                            db.execute(f"INSERT OR REPLACE INTO main.wcl_{name} SELECT * FROM old.{table}")
        finally:
            db.execute("DETACH DATABASE old")
    finally:
        db.close()


def now_ms():
    return int(time.time() * 1000)


def _pack(obj):
    return zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _unpack(blob):
    return json.loads(zlib.decompress(blob).decode("utf-8"))


class Cache:
    """Helyi cache egyetlen SQLite fájlban (a Python beépített sqlite3 moduljával).
    Tárolja a zónalistát, az időszűrés-teszt eredményét, az időablakonként letöltött
    report-oldalakat és a kill-enkénti egyéni item leveleket (playerDetails).
    path=None (--no-cache): csak memóriában él, semmit nem olvas be és nem ment el.
    refresh=True (--refresh): olvasáskor mindig "nincs találat", de az új adatokat elmenti."""

    def __init__(self, path, refresh=False, ttl_hours=6.0):
        self.path = path
        self.refresh = refresh
        self.ttl_ms = max(0.0, ttl_hours) * HOUR_MS
        self._write_warned = False
        self._touches = []          # a 'legutóbb használva' frissítései, a következő írással kerülnek a fájlba
        try:
            self.db = sqlite3.connect(path or ":memory:", timeout=30)
            prepare_cache_db(self.db)
        except sqlite3.Error as exc:
            raise StatsError(f"A cache fájl nem nyitható meg ({path}): {exc}\n"
                     "Töröld a fájlt, vagy futtasd a --no-cache kapcsolóval.")

    def _write(self, sql, rows):
        """Írás + azonnali mentés (így megszakításkor sem vész el a már letöltött adat).
        Ha nem sikerül (pl. egy másik futás zárolja a fájlt), csak figyelmeztet."""
        try:
            self._flush_touches()
            self.db.executemany(sql, rows)
            self.db.commit()
        except sqlite3.Error as exc:
            try:
                self.db.rollback()  # egy félbemaradt írás se zárolja tovább az adatbázist
            except sqlite3.Error:
                pass
            if not self._write_warned:
                out(f"  ! nem sikerült a cache-be írni ({exc}) - a futás folytatódik", err=True)
                self._write_warned = True

    def _touch(self, sql, params):
        """A 'legutóbb használva' időbélyeg frissítése - csak a következő írással (vagy a lezáráskor)
        kerül a fájlba, mert a közös adatbázisban (lásd storage.py) egy nyitva hagyott írási
        tranzakció feltartaná a program többi mentését. Ha nem sikerül, nem baj."""
        self._touches.append((sql, params))

    def _flush_touches(self):
        touches, self._touches = self._touches, []
        for sql, params in touches:
            self.db.execute(sql, params)

    def get_meta(self, key, max_age_ms=None):
        if self.refresh:
            return None
        row = self.db.execute("SELECT saved, value FROM wcl_meta WHERE key = ?", (key,)).fetchone()
        if row is None or (max_age_ms is not None and now_ms() - row[0] > max_age_ms):
            return None
        return _unpack(row[1])

    def set_meta(self, key, value):
        self._write("INSERT OR REPLACE INTO wcl_meta (key, saved, value) VALUES (?, ?, ?)",
                    [(key, now_ms(), _pack(value))])

    def get_page(self, key):
        """Egy időablak egy report-oldala, ha megvan és még érvényes. A lezárulása után
        legalább CACHE_SETTLE_HOURS órával letöltött oldal végleges; a korábban letöltött
        csak ttl-ig használható, mert azóta még kerülhettek fel logok az ablakba."""
        if self.refresh:
            return None
        row = self.db.execute("SELECT w_end, fetched, body FROM wcl_pages WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        w_end, fetched, body = row
        now = now_ms()
        if fetched - w_end < CACHE_SETTLE_HOURS * HOUR_MS and now - fetched > self.ttl_ms:
            return None
        self._touch("UPDATE wcl_pages SET used = ? WHERE key = ?", (now, key))
        return _unpack(body)

    def put_page(self, key, w_end, block):
        now = now_ms()
        self._write("INSERT OR REPLACE INTO wcl_pages (key, w_end, fetched, used, body) VALUES (?, ?, ?, ?, ?)",
                    [(key, w_end, now, now, _pack(block))])

    def get_players(self, keys):
        """{(report, fight): [ilvl, ...]} a cache-ben már meglévő kill-ekre."""
        found = {}
        if self.refresh:
            return found
        now = now_ms()
        for report, fight in keys:
            row = self.db.execute("SELECT body FROM wcl_players WHERE report = ? AND fight = ?",
                                  (report, fight)).fetchone()
            if row is not None:
                found[(report, fight)] = _unpack(row[0])
                self._touch("UPDATE wcl_players SET used = ? WHERE report = ? AND fight = ?",
                            (now, report, fight))
        return found

    def put_players(self, values):
        """Csak a nem üres eredményeket menti (az üres többnyire API hibát jelent)."""
        now = now_ms()
        rows = [(report, fight, now, _pack(v)) for (report, fight), v in values.items() if v]
        if rows:
            self._write("INSERT OR REPLACE INTO wcl_players (report, fight, used, body) VALUES (?, ?, ?, ?)", rows)

    def close(self):
        """A régóta nem használt bejegyzések törlése, mentés, lezárás."""
        try:
            self._flush_touches()
            cutoff = now_ms() - CACHE_KEEP_DAYS * DAY_MS
            self.db.execute("DELETE FROM wcl_pages WHERE used < ?", (cutoff,))
            self.db.execute("DELETE FROM wcl_players WHERE used < ?", (cutoff,))
            # VACUUM nincs: a közös adatbázisban az egész fájlt átírná, és addig feltartaná a program
            # mentéseit. A felszabadult helyet az SQLite az új adatokhoz újra felhasználja.
            self.db.commit()
        except sqlite3.Error as exc:
            out(f"  ! cache karbantartás sikertelen: {exc}", err=True)
        finally:
            self.db.close()


# ------------------------------------------------------------------------- zónák

def load_expansions(api, cache):
    expansions = cache.get_meta("zones", max_age_ms=ZONES_TTL_HOURS * HOUR_MS)
    if expansions is None:
        data = api().query(ZONES_QUERY)
        expansions = (data.get("worldData") or {}).get("expansions") or []
        if expansions:
            cache.set_meta("zones", expansions)
    return expansions


def is_raid_zone(zone):
    name = (zone.get("name") or "").lower()
    if any(word in name for word in NON_RAID_ZONE_WORDS):
        return False
    diff_ids = {d.get("id") for d in zone.get("difficulties") or []}
    if MYTHIC_PLUS_DIFFICULTY in diff_ids:
        return False
    return set(DIFFICULTIES) <= diff_ids and len(zone.get("encounters") or []) >= 4


def pick_zone(expansions, zone_id=None, zone_name=None):
    zones = [z for exp in expansions for z in exp.get("zones") or []]
    if zone_id is not None:
        for zone in zones:
            if zone.get("id") == zone_id:
                return zone
        raise StatsError(f"Nincs {zone_id} azonosítójú zóna (lásd: --list-zones).")
    if zone_name:
        hits = [z for z in zones if zone_name.lower() in (z.get("name") or "").lower()]
        if not hits:
            raise StatsError(f'Nincs "{zone_name}" nevű zóna (lásd: --list-zones).')
        return max(hits, key=lambda z: (not z.get("frozen"), z.get("id") or 0))
    # automatikus: a legújabb kiegészítő legújabb, nem lezárt raid zónája
    for exp in sorted(expansions, key=lambda e: e.get("id") or 0, reverse=True):
        candidates = [z for z in exp.get("zones") or [] if not z.get("frozen") and is_raid_zone(z)]
        if candidates:
            return max(candidates, key=lambda z: z.get("id") or 0)
    raise StatsError("Nem találtam aktív raid zónát - add meg kézzel: --zone-id vagy --zone (lásd: --list-zones).")


def print_zone_list(expansions, how_many=2):
    for exp in sorted(expansions, key=lambda e: e.get("id") or 0, reverse=True)[:how_many]:
        out(f"\n{exp.get('name')} (expansion id {exp.get('id')})")
        for zone in sorted(exp.get("zones") or [], key=lambda z: z.get("id") or 0, reverse=True):
            diffs = ",".join(str(d.get("id")) for d in zone.get("difficulties") or [])
            state = "lezárt" if zone.get("frozen") else "aktív"
            kind = "raid" if is_raid_zone(zone) else "-"
            out(f"  id {zone.get('id'):>5} | {state:<6} | {kind:<4} | "
                  f"{len(zone.get('encounters') or []):>2} boss | diff [{diffs}] | {zone.get('name')}")


def split_encounters(zone, exclude):
    """A zóna bossai -> (megtartott, kihagyott); exclude: vesszővel elválasztott névrészletek."""
    words = [w.strip().lower() for w in (exclude or "").split(",") if w.strip()]
    kept, dropped = [], []
    for enc in zone.get("encounters") or []:
        (dropped if any(w in enc["name"].lower() for w in words) else kept).append(enc)
    return kept, dropped


# ------------------------------------------------------------ reportok, kill-ek

def fmt_ts(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def reduced_limit(exc, limit):
    """Ha a hiba az API lekérdezési komplexitás-korlátja ("Max query complexity should be
    50000 but got 81005"), visszaad egy beférő, kisebb oldalméretet; különben None."""
    match = COMPLEXITY_RE.search(str(exc))
    if not match or limit <= 1:
        return None
    allowed, got = int(match.group(1)), int(match.group(2))
    return max(1, min(limit - 1, int(limit * allowed / got * 0.9)))


def query_reports(client, zone_id, w_start, w_end, page, limit):
    """-> (report-oldal, a ténylegesen használt oldalméret)"""
    while True:
        if client.report_limit_cap:
            limit = min(limit, client.report_limit_cap)
        try:
            data = client.query(REPORTS_QUERY, {"zoneID": zone_id, "page": page, "limit": limit,
                                                "startTime": float(w_start), "endTime": float(w_end)})
            return (data.get("reportData") or {}).get("reports") or {}, limit
        except WCLError as exc:
            smaller = reduced_limit(exc, limit)
            if smaller is None:
                raise
            out(f"  ! Túl összetett lekérdezés ({limit} report/oldal) -> {smaller} report/oldal",
                  err=True)
            client.report_limit_cap = smaller


def detect_time_filter(client, zone_id, now):
    """Egy 2 nappal korábbi, 3 órás ablakkal megnézi, mire szűr az API időben.
    Ha van az ablakon túlnyúló report, a szűrés a report kezdésére (vagy átfedésre)
    vonatkozik - ekkor a kis időablakok sem hagyják ki a hosszú logokat."""
    w_end = now - 2 * DAY_MS
    w_start = w_end - 3 * HOUR_MS
    block, _ = query_reports(client, zone_id, w_start, w_end, 1, 50)
    reports = [r for r in block.get("data") or [] if r]
    spill = sum(1 for r in reports
                if (r.get("endTime") or 0) > w_end or (r.get("startTime") or w_start) < w_start)
    return len(reports), spill


def make_windows(now, days, pages, fine):
    """fine=True: 'pages' darab egyforma ablak, ablakonként 1 oldal;
    fine=False: napos ablakok, ablakonként több oldal (így a hosszú logok is beleférnek).
    Az ablakok rögzített rácsra illeszkednek (az ablakhossz egész számú többszörösei
    1970-től), és csak lezárult ablakok kerülnek bele: így egy későbbi futás ugyanazokat
    az ablakokat kapja, és a már letöltötteket a cache-ből veheti."""
    count = max(1, pages) if fine else max(1, math.ceil(days))
    per_window = 1 if fine else max(1, math.ceil(pages / count))
    step = max(60_000, int(round(days * DAY_MS / count)))
    end = now // step * step
    windows = [(end - (i + 1) * step, end - i * step) for i in range(count)]
    return windows, per_window


def page_key(zone_id, w_start, w_end, page, limit):
    return f"{zone_id}:{w_start}:{w_end}:{page}:{limit}"


def time_filter_verdict(api, cache, zone_id, now):
    """detect_time_filter eredménye; az egyértelmű eredményt a cache megjegyzi."""
    key = f"timefilter:{zone_id}"
    saved = cache.get_meta(key, max_age_ms=TIMEFILTER_TTL_DAYS * DAY_MS)
    if saved:
        return saved["reports"], saved["spill"], " (cache)"
    n_test, spill = detect_time_filter(api(), zone_id, now)
    if spill > 0 or n_test >= 10:
        cache.set_meta(key, {"reports": n_test, "spill": spill})
    return n_test, spill, ""


def collect_reports(api, cache, zone_id, days, pages, page_size, seed):
    now = now_ms()
    n_test, spill, note = time_filter_verdict(api, cache, zone_id, now)   # hibánál a hívó írja ki a teendőt
    fine = spill > 0
    windows, per_window = make_windows(now, days, pages, fine)
    if fine:
        hours = (windows[0][1] - windows[0][0]) / HOUR_MS
        out(f"  Időszűrés teszt{note}: {spill}/{n_test} report nyúlik túl a tesztablakon -> "
              f"{len(windows)} db {hours:.1f} órás ablak, ablakonként 1 oldal")
    else:
        reason = ("kevés report a tesztablakban" if n_test < 10
                  else "egy report sem nyúlik túl a tesztablakon")
        out(f"  Időszűrés teszt{note}: {reason} -> {len(windows)} napos ablak, "
              f"ablakonként legfeljebb {per_window} oldal")

    reports, seen = [], set()

    def add(block):
        added = 0
        for rep in block.get("data") or []:
            code = (rep or {}).get("code")
            if code and code not in seen:
                seen.add(code)
                reports.append(rep)
                added += 1
        return added

    # 1) ami a cache-ben megvan (és még érvényes), az onnan jön
    cap = cache.get_meta("report_limit_cap")
    limit = min(page_size, cap) if cap else page_size
    todo = []                                   # (ablak kezdete, vége, első hiányzó oldal)
    for w_start, w_end in windows:
        page = 1
        while page <= per_window:
            block = cache.get_page(page_key(zone_id, w_start, w_end, page, limit))
            if block is None:
                break
            add(block)
            page = page + 1 if block.get("has_more_pages") else per_window + 1
        if page <= per_window:
            todo.append((w_start, w_end, page))
    if cache.path:
        out(f"  Cache: {len(windows) - len(todo)}/{len(windows)} ablak megvolt ({len(reports)} report), "
              f"letöltendő: {len(todo)} ablak")
    if not todo:
        return reports

    # 2) a hiányzók letöltése véletlen sorrendben (megszakítva is szórt marad a minta)
    client = api()
    random.Random(seed).shuffle(todo)
    failures = 0
    try:
        for n, (w_start, w_end, first_page) in enumerate(todo, 1):
            added = 0
            for page in range(first_page, per_window + 1):
                try:
                    block, used_limit = query_reports(client, zone_id, w_start, w_end, page, page_size)
                    failures = 0
                except WCLError as exc:
                    failures += 1
                    out(f"  ! kihagyott oldal: {exc}", err=True)
                    break
                cache.put_page(page_key(zone_id, w_start, w_end, page, used_limit), w_end, block)
                added += add(block)
                if not block.get("has_more_pages"):
                    break
            out(f"  [{n:>3}/{len(todo)}] {fmt_ts(w_start)} - {fmt_ts(w_end)}: "
                  f"+{added} report (össz. {len(reports)}) | {client.usage()}")
            if failures >= 5:
                out("  ! 5 egymás utáni hibás lekérés - leállok a report-gyűjtéssel.", err=True)
                break
    except (KeyboardInterrupt, Stopped):
        out("\n  Megszakítva - az eddig letöltött reportokkal számolok tovább "
              "(a letöltött oldalak a cache-ben maradnak).")
    if client.report_limit_cap and client.report_limit_cap != cap:
        cache.set_meta("report_limit_cap", client.report_limit_cap)
    return reports


def extract_kills(reports, encounter_ids):
    kills, info = [], Counter()
    for rep in reports:
        guild = rep.get("guild") or {}
        region = (((guild.get("server") or {}).get("region") or {}).get("slug") or "").lower() or None
        for fight in rep.get("fights") or []:
            if not fight.get("kill") or fight.get("encounterID") not in encounter_ids:
                continue
            if fight.get("difficulty") not in DIFFICULTIES:
                info["other_difficulty"] += 1          # pl. LFR
                continue
            ilvl = fight.get("averageItemLevel")
            if not isinstance(ilvl, (int, float)) or ilvl <= 0:
                info["no_ilvl"] += 1
                continue
            kills.append({
                "report": rep["code"],
                "fight": fight.get("id"),
                "encounter": fight["encounterID"],
                "difficulty": fight["difficulty"],
                "size": fight.get("size"),
                "ilvl": round(float(ilvl), 2),
                "time": (rep.get("startTime") or 0) + (fight.get("startTime") or 0),
                "duration": (fight["endTime"] - fight["startTime"]
                             if isinstance(fight.get("endTime"), (int, float))
                             and isinstance(fight.get("startTime"), (int, float)) else None),
                "guild": guild.get("id"),
                "region": region,
            })
    return kills, info


def dedupe_kills(kills, window_ms=120_000, ilvl_tolerance=1.5, duration_tolerance_ms=3_000):
    """Ugyanazt a kill-t gyakran többen is feltöltik (több logger egy raidben).
    Duplikátum: azonos boss + nehézség + létszám, 2 percen belüli pull, ~azonos
    harchossz és raid átlag ilvl, és nem két különböző guild reportja."""
    accepted, recent = [], defaultdict(list)
    for kill in sorted(kills, key=lambda k: k["time"]):
        bucket = recent[(kill["encounter"], kill["difficulty"], kill.get("size"))]
        duplicate = False
        for other in reversed(bucket):
            if kill["time"] - other["time"] > window_ms:
                break
            g1, g2 = kill.get("guild"), other.get("guild")
            d1, d2 = kill.get("duration"), other.get("duration")
            if ((g1 is None or g2 is None or g1 == g2)
                    and (d1 is None or d2 is None or abs(d1 - d2) <= duration_tolerance_ms)
                    and abs(kill["ilvl"] - other["ilvl"]) <= ilvl_tolerance):
                duplicate = True
                break
        if not duplicate:
            bucket.append(kill)
            accepted.append(kill)
    return accepted


# ------------------------------------------------------- egyéni (játékos) ilvl

def player_ilvl(entry):
    """Egy playerDetails játékos-bejegyzés item levele (több lehetséges mezőnévvel)."""
    values = [entry.get(k) for k in ("minItemLevel", "maxItemLevel")]
    values = [float(v) for v in values if isinstance(v, (int, float)) and v > 0]
    if values:
        return sum(values) / len(values)
    for key in ("itemLevel", "ilvl", "averageItemLevel"):
        value = entry.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def player_entries(details):
    """A playerDetails JSON-ból a játékos-bejegyzések listája (tanks/healers/dps)."""
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            return []
    node = details
    for key in ("data", "playerDetails"):
        if isinstance(node, dict) and key in node:
            node = node[key]
    if not isinstance(node, dict):
        return []
    return [p for role in ("tanks", "healers", "dps") for p in node.get(role) or [] if isinstance(p, dict)]


def sample_kills(kills, per_cell, seed):
    """Bossonként/nehézségenként legfeljebb per_cell kill. A sorrendet a kill azonosítójából
    képzett hash adja: ez ugyanolyan véletlen minta, mint egy sorsolás, de futásról futásra
    stabil, így a korábban letöltött (cache-elt) playerDetails-ek többsége újra bekerül."""
    def rank(kill):
        return hashlib.sha1(f"{seed}:{kill['report']}:{kill['fight']}".encode()).hexdigest()

    cells = defaultdict(list)
    for kill in kills:
        cells[(kill["difficulty"], kill["encounter"])].append(kill)
    sample = []
    for key in sorted(cells):
        sample.extend(sorted(cells[key], key=rank)[:per_cell])
    return sample


def fetch_player_batch(client, kills):
    """Egy HTTP kérés több kill playerDetails-ével (GraphQL aliasokkal).
    Ha az API túl összetettnek találja, kettévágja és külön kéri le."""
    by_report = defaultdict(list)
    for kill in kills:
        if REPORT_CODE_RE.match(str(kill["report"])) and kill.get("fight") is not None:
            by_report[kill["report"]].append(int(kill["fight"]))
    codes = list(by_report)
    if not codes:
        return {}
    parts = []
    for ri, code in enumerate(codes):
        fields = " ".join(f"f{fid}: playerDetails(fightIDs: [{fid}])" for fid in by_report[code])
        parts.append(f'r{ri}: report(code: "{code}") {{ {fields} }}')
    query = "query { " + RATE_FIELDS + " reportData { " + " ".join(parts) + " } }"
    try:
        data = client.query(query)
    except WCLError as exc:
        if COMPLEXITY_RE.search(str(exc)) and len(kills) > 1:
            half = len(kills) // 2
            result = fetch_player_batch(client, kills[:half])
            result.update(fetch_player_batch(client, kills[half:]))
            return result
        out(f"  ! playerDetails hiba (a többi kill adata megmarad): {exc}", err=True)
        data = exc.data
    result = {}
    report_data = (data or {}).get("reportData") or {}
    for ri, code in enumerate(codes):
        rep = report_data.get(f"r{ri}") or {}
        for fid in by_report[code]:
            result[(code, fid)] = [v for v in map(player_ilvl, player_entries(rep.get(f"f{fid}"))) if v]
    return result


def fetch_player_ilvls(api, cache, sample, batch_size):
    """playerDetails kill-enként, batch_size kill / kérés; ami a cache-ben megvan, azt nem kéri le."""
    sample = [k for k in sample if k.get("fight") is not None]
    result = cache.get_players([(k["report"], int(k["fight"])) for k in sample])
    missing = [k for k in sample if (k["report"], int(k["fight"])) not in result]
    cached = f", ebből {len(sample) - len(missing)} a cache-ből" if cache.path else ""
    out(f"\nEgyéni item levelek: {len(sample)} kill{cached} -> letöltendő {len(missing)} kill "
          f"playerDetails-e (becsült költség ~{PLAYER_DETAILS_COST * len(missing)} API pont; "
          "óránként 3600 a keret, elfogyáskor kivárok)")
    if not missing:
        return result
    client = api()
    try:
        for start in range(0, len(missing), batch_size):
            batch = fetch_player_batch(client, missing[start:start + batch_size])
            cache.put_players(batch)
            result.update(batch)
            done = min(start + batch_size, len(missing))
            out(f"  playerDetails: {done}/{len(missing)} kill | {client.usage()}")
    except (KeyboardInterrupt, Stopped):
        out("\n  Megszakítva - az eddig letöltött playerDetails-ekkel számolok tovább "
              "(a cache-ben megmaradnak).")
    return result


# --------------------------------------------------------------- statisztika

# a táblázatok és a CSV statisztika-oszlopai ebben a sorrendben (a summarize() kulcsai)
STAT_KEYS = ("mean", "median", "p25", "min", "max")


def percentile(values, p):
    """A p. percentilis lineáris interpolációval - ugyanaz a módszer, mint az Excel
    PERCENTILIS.TARTALMAZ (PERCENTILE.INC) függvényéé, így a CSV-ből ellenőrizhető.
    Mindig a min-max tartományba esik, p=50-nél megegyezik a mediánnal,
    egyetlen értéknél maga az érték."""
    data = sorted(values)
    pos = (len(data) - 1) * p / 100
    lo = int(pos)
    if lo + 1 >= len(data):
        return data[-1]
    return data[lo] + (data[lo + 1] - data[lo]) * (pos - lo)


def summarize(values):
    if not values:
        return None
    return {"mean": _mean(values), "median": statistics.median(values),
            "p25": percentile(values, 25), "min": min(values), "max": max(values)}


def raid_avg_cells(kills):
    cells = defaultdict(lambda: {"kills": 0, "values": []})
    for kill in kills:
        cell = cells[(kill["difficulty"], kill["encounter"])]
        cell["kills"] += 1
        cell["values"].append(kill["ilvl"])
    return cells


def player_cells(sample, player_values):
    cells = defaultdict(lambda: {"kills": 0, "values": []})
    for kill in sample:
        values = player_values.get((kill["report"], int(kill["fight"])))
        if values:
            cell = cells[(kill["difficulty"], kill["encounter"])]
            cell["kills"] += 1
            cell["values"].extend(values)
    return cells


def build_tables(cells, zone, with_players=False):
    """{difficulty: [(boss, számlálók, összesítés), ..., ("Összes boss", ...)]}"""
    def row(name, kills, values):
        counts = (kills, len(values)) if with_players else (kills,)
        return name, counts, summarize(values)

    tables = {}
    for diff in DIFFICULTIES:
        rows, total_kills, total_values = [], 0, []
        for enc in zone.get("encounters") or []:
            cell = cells.get((diff, enc["id"])) or {"kills": 0, "values": []}
            total_kills += cell["kills"]
            total_values.extend(cell["values"])
            rows.append(row(enc["name"], cell["kills"], cell["values"]))
        rows.append(row("Összes boss", total_kills, total_values))
        tables[diff] = rows
    return tables


def print_tables(title, tables, count_headers):
    headers = ["Boss", *count_headers, "Átlag", "Medián", "P25", "Min", "Max"]
    for diff, rows in tables.items():
        out(f"\n=== {DIFFICULTIES[diff]} - {title} ===")
        if not rows[-1][1][0]:
            out("(nincs kill a mintában)")
            continue
        body = []
        for name, counts, stats in rows:
            stat_cols = ([f"{stats[k]:.1f}" for k in STAT_KEYS]
                         if stats else ["-"] * len(STAT_KEYS))
            body.append([name, *(str(c) for c in counts), *stat_cols])
        widths = [max(len(r[i]) for r in [headers] + body) for i in range(len(headers))]

        def line(cols):
            return "  ".join(c.ljust(widths[i]) if i == 0 else c.rjust(widths[i])
                             for i, c in enumerate(cols))

        rule = "-" * len(line(headers))
        out(line(headers))
        out(rule)
        for r in body[:-1]:
            out(line(r))
        out(rule)
        out(line(body[-1]))


def write_csv(path, sections):
    """Magyar Excel-barát CSV: ';' elválasztó, tizedesvessző, UTF-8 BOM."""
    def hu(x):
        return f"{x:.1f}".replace(".", ",")

    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Nehézség", "Mérőszám", "Boss", "Kill", "Játékos",
                         "Átlag", "Medián", "25. percentilis", "Min", "Max"])
        for metric, tables in sections:
            for diff, rows in tables.items():
                for name, counts, stats in rows:
                    players = counts[1] if len(counts) > 1 else ""
                    values = ([hu(stats[k]) for k in STAT_KEYS]
                              if stats else [""] * len(STAT_KEYS))
                    writer.writerow([DIFFICULTIES[diff], metric, name, counts[0], players, *values])


# ---------------------------------------------------------------------- probe

def run_probe(client, zone, out_path, days):
    out = {"zone": zone}
    now = int(time.time() * 1000)

    out("\n[1] Legfrissebb 10 report a zónára...")
    reports = []
    try:
        block, _ = query_reports(client, zone["id"], now - int(days * DAY_MS), now, 1, 10)
        out["reports_page_1"] = block
        reports = [r for r in block.get("data") or [] if r]
        starts = [r.get("startTime") or 0 for r in reports]
        if len(starts) >= 3:
            if starts == sorted(starts, reverse=True):
                order = "kezdési idő szerint csökkenő"
            elif starts == sorted(starts):
                order = "kezdési idő szerint növekvő"
            else:
                order = "nem kezdési idő szerint (valószínűleg feltöltési sorrend)"
            out(f"    sorrend: {order}, has_more_pages={block.get('has_more_pages')}")
    except WCLError as exc:
        out["reports_error"] = str(exc)
        out(f"    HIBA: {exc}")

    first_kill = None
    for rep in reports:
        fights = rep.get("fights") or []
        minutes = ((rep.get("endTime") or 0) - (rep.get("startTime") or 0)) / 60000
        out(f"    {rep.get('code')}: kezdés {fmt_ts(rep.get('startTime') or 0)}, "
              f"{minutes:.0f} perc, {len(fights)} kill")
        for fight in fights:
            out(f"       #{fight.get('id')}: encounter {fight.get('encounterID')}, "
                  f"diff {fight.get('difficulty')}, size {fight.get('size')}, "
                  f"averageItemLevel = {fight.get('averageItemLevel')}")
            if first_kill is None and fight.get("kill"):
                first_kill = (rep["code"], fight["id"])

    out("\n[2] Időszűrés teszt (3 órás ablak, 2 nappal ezelőtt)...")
    try:
        n_test, spill = detect_time_filter(client, zone["id"], now)
        out["time_filter_test"] = {"reports": n_test, "spill": spill}
        verdict = ("a report kezdésére szűr -> kis időablakok" if spill
                   else "nincs túlnyúló report -> napos ablakok")
        out(f"    {n_test} report, ebből {spill} nyúlik túl az ablakon: {verdict}")
    except WCLError as exc:
        out["time_filter_error"] = str(exc)
        out(f"    HIBA: {exc}")

    if first_kill:
        out(f"\n[3] Egy kill részletei + playerDetails ({first_kill[0]} #{first_kill[1]})...")
        before = (client.rate or {}).get("pointsSpentThisHour")
        try:
            detail = client.query(PROBE_FIGHT_QUERY, {"code": first_kill[0], "fightIDs": [first_kill[1]]})
            out["kill_detail"] = detail
            details = ((detail.get("reportData") or {}).get("report") or {}).get("playerDetails")
            entries = player_entries(details)
            values = [v for v in map(player_ilvl, entries) if v]
            out(f"    {len(entries)} játékos-bejegyzés, ebből {len(values)} item levellel: {values[:10]}")
            after = (client.rate or {}).get("pointsSpentThisHour")
            if before is not None and after is not None and after >= before:
                out(f"    a lekérés ára: ~{after - before:.1f} API pont")
        except WCLError as exc:
            out["kill_detail_error"] = str(exc)
            out(f"    HIBA: {exc}")
    elif reports:
        out("    (nincs kill ezen az oldalon - futtasd újra később)")

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    out(f"\nNyers válaszok elmentve: {out_path}  |  {client.usage()}")


# ----------------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(
        description="Warcraft Logs: milyen item levellel ölik meg az aktuális raid bossait "
                    "(Normal / Heroic / Mythic) - átlag, medián, 25. percentilis, min, max.",
        epilog="Részletes leírás a fájl elején.")
    ap.add_argument("--client-id", default=os.environ.get("WCL_CLIENT_ID"),
                    help="WCL API Client ID (vagy WCL_CLIENT_ID környezeti változó)")
    ap.add_argument("--client-secret", default=os.environ.get("WCL_CLIENT_SECRET"),
                    help="WCL API Client Secret (vagy WCL_CLIENT_SECRET)")
    ap.add_argument("--zone-id", type=int, help="WCL zóna ID (alap: automatikusan a legújabb aktív raid)")
    ap.add_argument("--zone", help='zóna névrészlet, pl. "Venomous"')
    ap.add_argument("--list-zones", action="store_true", help="a két legújabb kiegészítő zónái")
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDE, metavar="NEVEK",
                    help=f'kihagyott bossok névrészletei, vesszővel (alap: "{DEFAULT_EXCLUDE}"; '
                         'mindet megtartja: --exclude "")')
    ap.add_argument("--days", type=float, default=7, help="hány napra visszamenőleg (alap: 7)")
    ap.add_argument("--pages", type=int, default=100,
                    help="beolvasott report-oldalak száma = időablakok száma (alap: 100)")
    ap.add_argument("--page-size", type=int, default=50,
                    help="report oldalanként (alap: 50; az API komplexitás-korlátja kb. 60-nál van)")
    ap.add_argument("--region", choices=["eu", "us", "kr", "tw", "cn"],
                    help="csak ennek a régiónak a guildjei (guild nélküli logok kimaradnak)")
    ap.add_argument("--players", type=int, default=0, metavar="N",
                    help="egyéni játékos ilvl is: bossonként/nehézségenként N kill mintájából")
    ap.add_argument("--player-batch", type=int, default=8,
                    help="hány kill playerDetails-e menjen egy kérésbe (alap: 8)")
    ap.add_argument("--seed", type=int, default=42, help="a véletlen mintavétel magja")
    ap.add_argument("--csv", metavar="FILE", help="eredmény CSV-be (';' elválasztó, tizedesvessző)")
    ap.add_argument("--save", metavar="FILE", help="nyers kill-lista mentése JSON-ba")
    ap.add_argument("--load", metavar="FILE", help="mentett kill-lista betöltése (nincs report-letöltés)")
    ap.add_argument("--probe", action="store_true", help="nyers API válaszok mentése ellenőrzéshez")
    ap.add_argument("--probe-out", default="wcl_probe_output.json", metavar="FILE")
    ap.add_argument("--cache", default=DEFAULT_CACHE, metavar="FILE",
                    help="cache adatbázis (alap: a tervezőé, szintezes_adatok.sqlite a script mellett)")
    ap.add_argument("--no-cache", action="store_true", help="cache nélkül: nem olvas belőle és nem is ír bele")
    ap.add_argument("--refresh", action="store_true",
                    help="mindent újra letölt, a cache tartalmát figyelmen kívül hagyva (az új adatok bekerülnek)")
    ap.add_argument("--cache-ttl", type=float, default=6, metavar="ÓRA",
                    help=f"a lezárulásuk után {CACHE_SETTLE_HOURS} órán belül letöltött (akkor még friss) "
                         "időablakokat ennyi óra után újra lekéri, mert azóta újabb logok kerülhettek fel (alap: 6)")
    return ap


def parse_args(argv=None):
    args = build_parser().parse_args(argv)
    args.page_size = max(1, min(100, args.page_size))
    return args


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = parse_args()
    try:
        cache = Cache(None if args.no_cache else args.cache, refresh=args.refresh, ttl_hours=args.cache_ttl)
        try:
            run(args, cache)
        finally:
            cache.close()
    except StatsError as exc:
        sys.exit(str(exc))


def run(args, cache):
    """A teljes lekérdezés és számolás (ezt futtatja a main(), és a tervező ablaka is, a
    háttérben). Visszaadja az eredményt: {"zone", "sections", "kills", "per_difficulty"}
    (sections: [(mérőszám, build_tables() táblázatai)]), vagy None a --list-zones és a
    --probe után. Hibánál StatsError-t dob; a STOP-ra a letöltés az eddigi adatokkal zárul."""
    client = None

    def api():
        """A WCL kapcsolat csak akkor jön létre, ha tényleg kell (ha minden a cache-ben van, soha)."""
        nonlocal client
        if client is None:
            if not (args.client_id and args.client_secret):
                raise StatsError("Hiányzik az API kulcs: állítsd be a WCL_CLIENT_ID és WCL_CLIENT_SECRET "
                         "környezeti változót, vagy add meg: --client-id ... --client-secret ...\n"
                         "Kulcs igénylése: https://www.warcraftlogs.com/api/clients")
            client = WCLClient(args.client_id, args.client_secret)
            client.report_limit_cap = cache.get_meta("report_limit_cap")
        return client

    if cache.path:
        out(f"Cache: {cache.path}" + ("  (--refresh: minden újra letöltődik)" if args.refresh else ""))
    else:
        out("Cache: kikapcsolva (--no-cache)")

    if args.load:
        with open(args.load, encoding="utf-8") as fh:
            saved = json.load(fh)
        zone_all, raw_kills = saved["zone"], saved["kills"]
        meta = saved.get("meta") or {}
        out(f"Betöltve: {args.load} (készült: {saved.get('created', '?')}, "
              f"{meta.get('reports', '?')} report, {len(raw_kills)} nyers kill)")
    else:
        expansions = load_expansions(api, cache)
        if args.list_zones:
            print_zone_list(expansions)
            return None
        zone_all = pick_zone(expansions, args.zone_id, args.zone)

    kept, dropped = split_encounters(zone_all, args.exclude)
    zone = dict(zone_all, encounters=kept)
    out(f"Zóna: {zone['name']} (id {zone['id']}), {len(kept)} boss: "
          + ", ".join(e["name"] for e in kept))
    if dropped:
        out("Kihagyva (--exclude): " + ", ".join(e["name"] for e in dropped))
    if not kept:
        raise StatsError("Az --exclude minden bosst kiszűrt.")

    if not args.load:
        if args.probe:
            run_probe(api(), zone_all, args.probe_out, args.days)
            return None
        out(f"Reportok: utolsó {args.days:g} nap, kb. {args.pages} oldal x {args.page_size} report")
        try:
            reports = collect_reports(api, cache, zone["id"], args.days, args.pages, args.page_size, args.seed)
        except WCLError as exc:
            raise StatsError(f"\nA report-lista lekérése nem sikerült: {exc}\n"
                     "Futtasd a --probe kapcsolóval, és nézd meg / küldd el a kimenetét.")
        if not reports:
            raise StatsError("\nEgyetlen report sem jött le (lásd a fenti hibákat) - a mentést kihagytam. "
                     "Ha nem egyértelmű az ok, futtasd a --probe kapcsolóval.")
        raw_kills, info = extract_kills(reports, {e["id"] for e in zone_all.get("encounters") or []})
        starts = [r["startTime"] for r in reports if r.get("startTime")]
        span = f"{fmt_ts(min(starts))} - {fmt_ts(max(starts))}" if starts else "?"
        out(f"\nReportok: {len(reports)} (kezdések: {span}) | ilvl nélküli kill: {info['no_ilvl']} | "
              f"LFR/egyéb kill (kihagyva): {info['other_difficulty']}")
        if args.save:
            payload = {"created": datetime.now().isoformat(timespec="seconds"), "zone": zone_all,
                       "meta": {"days": args.days, "pages": args.pages, "page_size": args.page_size,
                                "reports": len(reports), "span": span},
                       "kills": raw_kills}
            with open(args.save, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            out(f"Nyers kill-lista mentve: {args.save}")

    kept_ids = {e["id"] for e in kept}
    raw_kills = [k for k in raw_kills if k["encounter"] in kept_ids]
    if args.region:
        before = len(raw_kills)
        raw_kills = [k for k in raw_kills if k.get("region") == args.region]
        out(f"Régió szűrő ({args.region}): {before} -> {len(raw_kills)} kill")

    kills = dedupe_kills(raw_kills)
    per_diff = Counter(k["difficulty"] for k in kills)
    out(f"Raid kill-ek: {len(raw_kills)}, duplikált logok nélkül: {len(kills)}  ->  "
          + ", ".join(f"{name}: {per_diff.get(d, 0)}" for d, name in DIFFICULTIES.items()))
    if not kills:
        raise StatsError("Nincs feldolgozható kill. Növeld a --days / --pages értékét, vagy futtasd a --probe-ot.")

    raid_tables = build_tables(raid_avg_cells(kills), zone)
    print_tables("raid átlag item level kill-enként", raid_tables, ["Kill"])
    out("\n(Egy adatpont = egy kill: a harcban részt vevő játékosok átlagos item levele.)")
    out("(P25 = 25. percentilis: az adatpontok kb. negyede van ez alatt, háromnegyede felette.)")
    sections = [("raid átlag / kill", raid_tables)]

    if args.players > 0:
        sample = sample_kills(kills, args.players, args.seed)
        player_values = fetch_player_ilvls(api, cache, sample, max(1, args.player_batch))
        player_tables = build_tables(player_cells(sample, player_values), zone, with_players=True)
        print_tables("játékosok egyéni item levele", player_tables, ["Kill", "Játékos"])
        sections.append(("játékos egyéni", player_tables))

    if args.csv:
        write_csv(args.csv, sections)
        out(f"\nCSV mentve: {args.csv}")
    if client is not None:
        out(f"\nÖsszesen {client.calls} API kérés | {client.usage()}")
    elif not args.load or args.players > 0:
        out("\nEgyetlen API kérés sem kellett - minden adat a cache-ből jött.")
    return {"zone": zone, "sections": sections, "kills": len(kills), "per_difficulty": dict(per_diff)}


if __name__ == "__main__":
    main()
