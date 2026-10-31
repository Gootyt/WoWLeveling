#!/usr/bin/env python3
"""
raiderio_ilvl_stats.py  (v4.6)

Average / median / 25th percentile / min / max item level of Mythic+ groups,
grouped by keystone level, using the public Raider.IO API (https://raider.io/api).

IN THE WOW LEVELING PLANNER
  This script is built into the planner (wow_leveling.py): its "M+ ilvl
  statisztika" window runs the same collection in the background - from the
  leaderboard or by crawling guilds - with the statistics table updating live
  and a Stop button instead of Ctrl+C (see run() and STOP). Run on its own it
  works exactly as described below. Without the requests package it uses
  httpcompat.py (the same requests calls over the standard library's urllib).

NEW IN v4.6
  PRIVATE PROFILES ARE SKIPPED, NOT ERRORS. Raider.IO answers "403 Profile is private"
  for a character whose owner hid it; such a character is now left out like an unknown
  one (and cached as such for --cache-hours), instead of counting as a failed lookup -
  a guild with five private members in a row used to abort the whole collection. The
  summary says how many were skipped.

NEW IN v4.5
  A REFUSED API KEY NO LONGER STOPS EVERYTHING. Raider.IO answers every request made
  with a wrong or revoked key with "403 Invalid API key"; the lookups then all failed
  and the collection was aborted. Now the key is dropped at the first such answer and
  the query goes on without it (the public API needs no key, it only has a lower rate
  limit); the summary says so. An aborted collection names the last error and its
  likely cause (rate limit, Raider.IO down / no connection, requests refused), and no
  error message shows the request URL any more - it carried the API key.

NEW IN v4.4
  THE CACHE IS AN SQLITE DATABASE: by default the planner's own database,
  szintezes_adatok.sqlite next to this script, which holds everything the planner
  saves - its window and the command line share one cache (--cache FILE: a separate
  one). Downloads go into its raiderio_cache table, each one committed the moment it
  arrives; nothing is loaded into memory up front. The old default cache file,
  raiderio_ilvl_cache.json, is imported by the planner the next time it starts; an
  older cache file - JSON Lines (v4.0-v4.3) or one JSON object (v2/v3) - given with
  --cache is imported into a database next to it (the old file is left as it is).

NEW IN v4.3
  CACHED RUNS IN THE STATISTICS (--use-cached-runs, off by default). Normally only
  the runs the query itself reaches are counted - the cache just saves downloading
  them. With this option every run of the season the cache holds counts too,
  whichever earlier query (leaderboard or guild crawl) downloaded it, as long as it
  passes the filters: region, --levels, --since-days, timed only (unless
  --include-untimed), --min-ilvl / --max-ilvl and --per-level (newest runs first);
  --dungeon as well where the query uses it (a single leaderboard query), but a run
  cached before v4.3 doesn't know its dungeon, so it is left out when one dungeon is
  asked for. --affixes doesn't filter them. They are counted before the query starts
  - the table fills up at once - and the query doesn't count them again when it
  reaches them, but goes on through them as usual: a guild crawl follows their teams'
  guilds just the same (a cached run it never reaches adds no guild to the crawl).
  The sample then depends on what was queried before: the leaderboard brings mostly
  high keys, guild crawls every level.

NEW IN v4.2
  ITEM LEVEL RANGE. Item levels below 250 or above 350 are ignored (250 and 350
  themselves still count): that player is left out of the statistics (Players,
  Avg, Median, P25, Min, Max), the rest of the team still counts. A run left
  without any player because of this isn't counted as a run either (and its
  team's guilds aren't followed). Set the range with --min-ilvl / --max-ilvl
  (0 = no limit on that side). Only the statistics are filtered: the cache keeps
  every item level as downloaded, so trying another range costs no API calls.

NEW IN v4.1
  P25 column (25th percentile: a quarter of the players' item levels are below
  it) in the table, the live view and the CSV (p25_item_level, right after
  the median). Linear interpolation between the two nearest values - the same
  as Excel's PERCENTILE.INC / PERCENTILIS.TARTALMAZ.

NEW IN v4 - AS FEW API REQUESTS AS POSSIBLE
  1. NOTHING IS DOWNLOADED TWICE. Everything the script downloads goes into the
     cache (--cache, see v4.4) the moment it arrives - Ctrl+C, a crash or simply
     closing the window loses nothing.
       - RUNS (team + item levels from run-details) are kept FOREVER: a
         finished run never changes, so a run downloaded once is never
         downloaded again - not in this session, not in any later one, not
         in another mode.
       - character profiles, guild rosters, leaderboard pages and the season
         data are reused for --cache-hours (default 24): new runs / members
         show up in them over time, a day-old copy is just as good a sample.
     So a restarted crawl costs no API calls up to the point where the
     previous one stopped: the cached part is replayed in seconds (the
     statistics fill up again on the way) and downloading carries on from
     there. A cache file of an older version (v2/v3) is converted.
  2. TIMED RUNS ONLY. Only runs known to be finished within the timer are
     counted. A run over the timer is skipped without downloading anything
     when the recent-runs list / leaderboard already says so; otherwise
     run-details decides (it has num_chests and the clear time vs. the timer).
     A run nobody says anything about is left out as well. --include-untimed
     counts them all.
  3. IDLE GUILD MEMBERS ARE SKIPPED. Raider.IO crawls a character whenever it
     turns up in a new run, so a member whose last_crawled_at (when the roster
     carries it) predates the season - or the --since-days window - can't
     have a run we'd use: its profile isn't downloaded. --include-idle checks
     them anyway. --debug-guild shows whether the roster has the field.
  4. run-details is the default source of every run's team: one call gives all
     five players' item levels as of the run (cached forever), instead of up
     to five profile lookups of their CURRENT gear. --no-run-details brings
     the old profile-based way back (see "WHY v2 EXISTS").
  5. A guild that run-details names without a realm is tried on the member's
     own realm first - right most of the time - instead of always spending a
     profile lookup on finding its realm (that happens now only if the guess
     turns out wrong, e.g. on connected realms).

NEW IN v3
  1. GUILD CRAWL - every team found through /mythic-plus/run-details queues the
     guilds of its members; those guild rosters are read in turn, their teams
     queue more guilds, and so on (breadth-first, every guild is read once).
     On by default with --guild (--no-follow-guilds = the old behaviour: only
     the guilds you list). In leaderboard mode --follow-guilds starts the crawl
     from the leaderboard teams once the pages are done. Following needs the
     team of every run, so run-details is fetched for each run automatically.
  2. LIVE STATISTICS - a crawl like that practically never ends on its own, so
     the table is recomputed after EVERY run that is added and redrawn in place
     in the console (with guilds read / waiting, characters, API requests).
     Ctrl+C stops at any moment and prints the final summary. --csv is
     rewritten on every update too, so even closing the window loses nothing.
     --no-live prints the table as plain text instead (automatic when the
     output is not a console, e.g. redirected to a file).
  3. FIXES the guild mode needed for this:
     - guild member lists give the realm as a plain realm NAME and no region -
       v2 could not parse them at all (0 characters found); handled now.
     - mythic_plus_recent_runs entries have no run id field: the id (and the
       season) sits in the entry's url, so run-details works there now.
     - the cache keeps only the fields it needs (v2 stored every recent run in
       full, which grows into hundreds of MB during a long crawl).

WHY v2 EXISTS
  --debug-raw showed that a roster entry in /mythic-plus/runs carries identity,
  spec, role and talent loadout - but NO item level. So v2 looked every player
  up with /characters/profile?fields=gear (gear.item_level_equipped); v4 does
  that only with --no-run-details, run-details is cheaper and closer in time.

CAVEATS - read before trusting the numbers
  1. /mythic-plus/runs is a leaderboard ranked by SCORE, always highest first -
     the API has no "sort" or "min_level"/"max_level" parameter, and no way to
     page from the bottom. So low keystone levels are not "hard to reach with
     enough pages" - they are structurally last in line, behind every higher
     -scoring run in the region/dungeon/affix slice you queried, and raising
     --max-pages (capped at 100, or 1000 with a key) does not change that. See
     "REACHING LOW KEY LEVELS" below for the one parameter that actually helps.
  2. The profile gives the item level as of Raider.IO's LAST CRAWL of the
     character, not at the moment of the run. The script reports how far the two
     timestamps are apart; narrow it with --since-days / --max-gap-days.
  3. Unauthenticated calls are rate limited (HTTP 429 + Retry-After header; the
     script honours it). A free API key (https://raider.io/settings/apps) raises
     the limits:  --api-key KEY  or the environment variable RAIDERIO_API_KEY.

REACHING LOW KEY LEVELS (e.g. +2 to +5)
  --each-dungeon and a huge --max-pages do NOT solve this: within any single
  dungeon/region, every higher-level run outscores every lower-level one, so a
  +2 sits behind the ENTIRE population of +6..+40 runs done that season - far
  beyond page 1000 for any dungeon anyone actually plays.
  The one query parameter that can flip this around is --affixes, when a key
  bracket carries an affix unique to it. Season 2 (season-mn-2) has one such
  affix: "Lindormi's Guidance" is active on +2 through +5 ONLY, for the whole
  season (it is not one of the weekly-rotating affixes), so filtering to just
  that affix shrinks the competing pool from "every run all season" down to
  "only +2..+5 runs all season" - inside that pool a +2 is no longer racing
  against +20s. Try:
      python raiderio_ilvl_stats.py --debug-raw --affixes lindormis-guidance
  which prints the level range seen on page 0 for free, so you can confirm the
  slug is right before spending a real pull on it. If that comes back empty,
  the exact slug may differ - open a dungeon+affix combo on raider.io itself in
  a browser and read the affix slug from the resulting URL, or try the numeric
  affix id (the --debug-raw output shows it in weekly_modifiers[].id once you
  find a matching run). Whatever affix your target bracket uses, --levels
  2,3,4,5 still does the final per-level split within that filtered pool.
  For levels below that (or seasons without a level-locked affix), the fully
  general fix is --guild (below): it doesn't touch the leaderboard at all.

WHAT ABOUT LEVELS 6-17?
  No confirmed equivalent of Lindormi's Guidance is known for this range. The
  weekly-rotating affixes that turn on around +7 (Fortified, Tyrannical, ...)
  stay ON for every higher level too - a +22 run still carries Fortified AND
  Tyrannical (see a real --debug-raw dump), so filtering by e.g. "fortified"
  does not exclude 18-22, it just pools 7-9 together with 18-22, which is no
  better than --affixes all. Check it yourself, cheaply, with:
      python raiderio_ilvl_stats.py --scan-affixes all,fortified,tyrannical,lindormis-guidance
  which prints the page-0 level range for each guess side by side. If none of
  them narrows below ~18, --guild below reaches 6-17 (and every other level).

SAMPLING BY GUILD ROSTER INSTEAD OF THE LEADERBOARD (--guild)
  This ignores the score ranking entirely: it walks every member of one or
  more guilds and reads each character's mythic_plus_recent_runs (that
  character's own last 10 runs this season, in NO particular score order),
  so a +8 shows up exactly as reliably as a +20.
      python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --levels 6,7,8,9,10,11,12
      python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --guild "OtherGuild@some-realm"
  Guild spec is Name@realm or Name@realm@region (region defaults to --region).
  Each matching recent run's real team is pulled with /mythic-plus/run-details
  and counted with the item level run-details reports for every member - a
  genuine group average. That team is also where the crawl finds new guilds
  (see NEW IN v3), so the guilds you list are just the starting point: stop
  with Ctrl+C when the live table has enough runs, or bound it with
  --per-level (together with --levels), --max-guilds or --max-members.
  Only guilds of teams that pass your filters (--levels, --since-days, ...)
  are followed, so a low-level filter naturally steers the crawl towards
  guilds that play low keys.
  With --no-follow-guilds --no-run-details, each recent run contributes ONE
  data point instead: that character's own CURRENT gear, counted at most once
  per character per level ("Runs" then means characters observed at that
  level, not groups) - no call per run, but no group average either. Check
  the real field shapes first, for free, with:
      python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --debug-guild

Setup (optional - without it httpcompat.py is used):
    pip install requests

Usage:
    python raiderio_ilvl_stats.py --probe                  # where is item level exposed?
    python raiderio_ilvl_stats.py --max-pages 2            # small test run
    python raiderio_ilvl_stats.py --levels 20,21,22 --since-days 7
    python raiderio_ilvl_stats.py --each-dungeon --max-pages 30 --per-level 60 --csv ilvl.csv
    python raiderio_ilvl_stats.py --debug-raw --affixes lindormis-guidance --levels 2,3,4,5
    python raiderio_ilvl_stats.py --scan-affixes all,fortified,tyrannical,lindormis-guidance
    python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --debug-guild
    python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --levels 2,3,4,5,6,7,8,9,10 --csv live.csv
    python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --no-follow-guilds    # only this guild
    python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --include-untimed     # over-timer runs too
    python raiderio_ilvl_stats.py --max-pages 3 --follow-guilds      # leaderboard teams -> their guilds
    python raiderio_ilvl_stats.py --max-pages 5 --cache-hours 168    # reuse everything for a week
    python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --min-ilvl 260 --max-ilvl 340  # other range
"""

import argparse
import bisect
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from statistics import median
from urllib.parse import unquote

try:
    import requests
except ImportError:      # the planner works without the requests package
    import httpcompat as requests

BASE_URL = "https://raider.io/api/v1"
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json",
                        "User-Agent": "raiderio-ilvl-stats/4.0 (personal script)"})

API_KEY = None   # set from --api-key / RAIDERIO_API_KEY in main()
KEY_REJECTED = False   # Raider.IO refused API_KEY during this run, which then went on without it
DELAY = 0.4      # seconds between requests (be polite)

MAX_ERROR_STREAK = 5   # abort after this many failed lookups in a row (API down / blocked)

LIVE = None       # the LiveView while data is being collected (see main)
HTTP_CALLS = 0    # every request sent - shown in the live header and in the summary
STOP = threading.Event()   # set by the planner's Stop button: the next request or wait raises Stopped

RUN_URL_RE = re.compile(r"/(season-[^/?#]+)/(\d+)")            # .../mythic-plus-runs/season-mn-2/1234567-12-...
CHAR_PATH_RE = re.compile(r"/characters/([^/]+)/([^/]+)/([^/?#]+)")
GUILD_PATH_RE = re.compile(r"/guilds/([^/]+)/([^/]+)/([^/?#]+)")


class TooManyErrors(Exception):
    """MAX_ERROR_STREAK character lookups failed in a row. kind says how the last one failed
    (see failure_kind), last is its error message."""

    def __init__(self, message, kind=None, last=""):
        super().__init__(message)
        self.kind = kind
        self.last = last


class GaveUp(RuntimeError):
    """api_get kept getting 429 / 5xx answers or network errors. status is the last HTTP status
    (None: no answer at all)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Stopped(Exception):
    """Raised once STOP is set (the planner's Ctrl+C): the collection ends with what it has."""


class StatsError(Exception):
    """A failure that ends the whole run before any data is collected (e.g. no season data)."""


def pause(seconds):
    """time.sleep() that STOP cuts short - then Stopped is raised."""
    if STOP.wait(max(seconds, 0.0)):
        raise Stopped()


# keys that hold an *overall* item level (per-slot "item_level" is only used by the probe)
ILVL_KEYS = {"item_level_equipped", "item_level_total", "itemlevelequipped", "itemleveltotal",
             "itemlevel", "item_level", "ilvl", "itemlevelmean"}


def log(msg, err=False):
    """
    Progress / warning line. While the live view owns the console it goes into
    its "recent events" list instead - printing in between would break the
    in-place redraw.
    """
    if LIVE is not None and LIVE.active:
        LIVE.event(msg)
    else:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def live_status(text):
    if LIVE is not None:
        LIVE.set_status(text)


def live_changed():
    """Call after every run that was added to the statistics."""
    if LIVE is not None:
        LIVE.changed()


# --------------------------------------------------------------------------- HTTP

def response_message(resp):
    """Raider.IO's own explanation of an error response (e.g. "Invalid API key"), or ""."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    message = body.get("message") if isinstance(body, dict) else None
    return " ".join(str(message).split())[:200] if message else ""


def api_get(path, params, max_retries=5):
    """
    GET one Raider.IO endpoint and return the parsed JSON.
    Retries on 429 / 5xx / network errors (honouring Retry-After), then raises GaveUp. Any
    other 4xx response raises requests.HTTPError so the caller can decide what it means; its
    message names the endpoint and Raider.IO's explanation, never the URL (that carries the
    API key). An API key Raider.IO refuses is dropped for the rest of the run (KEY_REJECTED),
    and the request goes again without it - the public API needs none.
    """
    global HTTP_CALLS, API_KEY, KEY_REJECTED
    url = f"{BASE_URL}/{path}"
    params = dict(params)
    problem, status = "unknown", None
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        if API_KEY:
            params["access_key"] = API_KEY
        else:
            params.pop("access_key", None)
        if STOP.is_set():
            raise Stopped()
        if LIVE is not None:
            LIVE.before_wait()          # the screen is up to date while we wait on the network
        HTTP_CALLS += 1
        try:
            resp = SESSION.get(url, params=params, timeout=20)
        except requests.exceptions.RequestException as exc:
            problem, status = exc.__class__.__name__, None
            wait = min(2 ** attempt, 30)
        else:
            if resp.status_code != 429 and resp.status_code < 500:
                if resp.status_code < 400:
                    return resp.json()
                message = response_message(resp)
                if API_KEY and resp.status_code in (401, 403) and "key" in message.lower():
                    API_KEY, KEY_REJECTED = None, True
                    log(f"  Raider.IO refused the API key ({message}) - going on without it", err=True)
                    attempt -= 1        # the same request again, without the key
                    continue
                raise requests.HTTPError(f"{path}: HTTP {resp.status_code}" + (f" ({message})" if message else ""),
                                         response=resp)
            problem, status = f"HTTP {resp.status_code}", resp.status_code
            try:
                wait = float(resp.headers.get("Retry-After", ""))
            except ValueError:
                wait = min(2 ** attempt, 60)
        log(f"  {problem} on {path} - waiting {wait:.0f}s (attempt {attempt}/{max_retries})", err=True)
        if LIVE is not None:
            LIVE.before_wait()
        pause(wait + 0.5)
    raise GaveUp(f"{path}: giving up after {max_retries} attempts ({problem})", status)


def is_private(exc):
    """Raider.IO refused one character's data because its owner made it private (HTTP 403
    "Profile is private") - the request itself was fine."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 403 and "private" in response_message(response).lower()


def failure_kind(exc):
    """How a request failed, for the reason an aborted collection gives: 'rate_limit' (HTTP 429
    to the end), 'unavailable' (5xx or no answer at all), 'refused' (401 / 403) or None."""
    if isinstance(exc, GaveUp):
        return "rate_limit" if exc.status == 429 else "unavailable"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return "refused" if status in (401, 403) else None


def parse_ts(value):
    """ISO-8601 string (with or without trailing Z) -> aware datetime, or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _dig(obj, *keys):
    """Safe nested dict lookup: _dig(d, 'gear', 'item_level_equipped')."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _text(value, *keys):
    """A non-empty string, or - if `value` is a dict such as a realm/region object - the first
    non-empty string among `keys` (e.g. 'slug', then 'name')."""
    if isinstance(value, dict):
        for key in keys:
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def realm_slug(realm):
    """'Twisting Nether' / 'twisting-nether' / "Kel'Thuzad" -> one comparable form.
    Only used for de-duplication keys; the API itself is always sent what it gave us."""
    s = re.sub(r"['\u2019`()]", "", str(realm).strip().lower())
    return re.sub(r"[\s-]+", "-", s).strip("-")


def ref_key(region, realm, name):
    """De-duplication key for a character or a guild."""
    return f"{str(region).lower()}/{realm_slug(realm)}/{str(name).strip().lower()}"


def parse_levels(text):
    return {int(x) for x in text.split(",")} if text else None


# --------------------------------------------------------------------------- season

def get_season(slug, region, expansion_id, cache=None):
    """
    Return the season dict from mythic-plus/static-data: the one called `slug`,
    or (if slug is None) the most recently started main season. The static data is
    reused from the cache for --cache-hours (one call less per start).
    """
    key = f"static:{expansion_id}"
    entry = cache.get(key) if cache is not None else None
    if entry is not None:
        seasons = entry.get("seasons") or []
    else:
        data = api_get("mythic-plus/static-data", {"expansion_id": expansion_id})
        seasons = data.get("seasons") if isinstance(data, dict) else None
        seasons = seasons or []
        if seasons and cache is not None:
            cache.put(key, {"seasons": seasons})
    if not seasons:
        raise RuntimeError("static-data endpoint returned no seasons")
    if slug:
        for season in seasons:
            if season.get("slug") == slug:
                return season
        return {"slug": slug, "dungeons": []}      # e.g. a PTR season not listed there

    pool = [s for s in seasons if s.get("is_main_season")] or seasons
    key = region if region in ("us", "eu", "kr", "tw", "cn") else "us"

    def started(season):
        return parse_ts(_dig(season, "starts", key))

    now = datetime.now(timezone.utc)
    running = [s for s in pool if started(s) and started(s) <= now]
    return max(running, key=started) if running else pool[-1]


def season_start(season_info, region):
    """When the season started in this region (aware datetime), or None if unknown."""
    key = region if region in ("us", "eu", "kr", "tw", "cn") else "us"
    return parse_ts(_dig(season_info, "starts", key))


# --------------------------------------------------------------------------- characters & guilds

def extract_item_level(member):
    """
    Item level embedded in a roster entry (None if the API doesn't provide one -
    which is the case for /mythic-plus/runs; run-details has items.item_level_equipped).
    """
    character = member.get("character") or member
    candidates = [
        _dig(character, "itemLevel"),
        _dig(character, "item_level"),
        _dig(character, "gear", "item_level_equipped"),
        _dig(character, "items", "item_level_equipped"),
        _dig(member, "items", "item_level_equipped"),
        _dig(member, "gear", "item_level_equipped"),
        _dig(member, "itemLevel"),
    ]
    for value in candidates:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    return None


def character_ref(member, default_region=None):
    """
    (region, realm, name) of a roster member or guild member, or None.
    Leaderboard / run-details rosters give realm and region as objects ({'slug': ...});
    guild member lists give the realm as a plain realm NAME and no region at all -
    that's what default_region (the guild's region) is for.
    """
    if not isinstance(member, dict):
        return None
    ch = member.get("character")
    if not isinstance(ch, dict):
        ch = member
    name = _text(ch.get("name"))
    region = _text(ch.get("region"), "slug", "short_name")
    realm = _text(ch.get("realm"), "slug", "name")
    if not (name and region and realm):        # fall back to ".../characters/eu/realm/Name"
        for link in (ch.get("path"), ch.get("profile_url"), member.get("profile_url")):
            m = CHAR_PATH_RE.search(link) if isinstance(link, str) else None
            if m:
                region = region or unquote(m.group(1))
                realm = realm or unquote(m.group(2))
                name = name or unquote(m.group(3))
                break
    region = (region or default_region or "").lower()
    return (region, realm, name) if (name and region and realm) else None


def _guild_parts(obj):
    """(name, region, realm) as far as a guild object states them itself - from its fields
    or its /guilds/... path; None for whatever it doesn't say. A plain string is a name."""
    if isinstance(obj, str):
        return (obj.strip() or None), None, None
    if not isinstance(obj, dict):
        return None, None, None
    name = _text(obj.get("name"))
    region = _text(obj.get("region"), "slug", "short_name")
    realm = _text(obj.get("realm"), "slug", "name")
    for link in (obj.get("path"), obj.get("profile_url")):
        m = GUILD_PATH_RE.search(link) if isinstance(link, str) else None
        if m:
            region = region or unquote(m.group(1))
            realm = realm or unquote(m.group(2))
            name = name or unquote(m.group(3))
            break
    return name, region, realm


def guild_from(obj, region, realm):
    """
    A guild from whatever the API gave: a run-details roster 'guild' object (known to
    carry at least 'name'), the /characters/profile 'guild' field ({'name', 'realm'},
    realm as a realm NAME), or a /guilds/... path. A missing region/realm falls back
    to the character's own; the realm is then only a GUESS (on connected realms a
    guild can sit on a sibling realm), which resolve_guild() corrects before the
    guild is read. Returns {'region','realm','name','exact'} or None (no guild).
    """
    name, g_region, g_realm = _guild_parts(obj)
    if not name:
        return None
    exact = g_realm is not None
    g_region = (g_region or region or "").lower()
    g_realm = g_realm or realm
    if not (g_region and g_realm):
        return None
    return {"region": g_region, "realm": g_realm, "name": name, "exact": exact}


def parse_guild_spec(spec, default_region):
    """'Name@realm' or 'Name@realm@region' -> (region, realm_slug, guild_name)."""
    parts = [p.strip() for p in spec.split("@")]
    if len(parts) == 2:
        name, realm = parts
        region = default_region
    elif len(parts) == 3:
        name, realm, region = parts
    else:
        raise ValueError(f"--guild value {spec!r} must look like Name@realm or Name@realm@region")
    if not (name and realm and region):
        raise ValueError(f"--guild value {spec!r} must look like Name@realm or Name@realm@region")
    return region.lower(), realm, name


def fetch_guild_members(region, realm, name):
    """Raw member entries from /guilds/profile?fields=members (parsed by character_ref)."""
    data = api_get("guilds/profile", {"region": region, "realm": realm, "name": name, "fields": "members"})
    return data.get("members") or []


def timed_status(obj):
    """
    Was the key completed within the timer? True / False / None (the object doesn't say).
    Reads whatever the endpoint provides: num_chests (leaderboard, run-details),
    num_keystone_upgrades / cleared_in_time (recent runs of a profile), or the clear
    time against the timer (clear_time_ms vs keystone_time_ms / par_time_ms).
    """
    if not isinstance(obj, dict):
        return None
    for key in ("num_chests", "num_keystone_upgrades"):
        v = obj.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            return v > 0
    v = obj.get("cleared_in_time")
    if isinstance(v, bool):
        return v
    clear = obj.get("clear_time_ms")
    if isinstance(clear, (int, float)) and not isinstance(clear, bool):
        for key in ("keystone_time_ms", "par_time_ms"):
            limit = obj.get(key)
            if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit > 0:
                return clear <= limit
    v = obj.get("time_remaining_ms")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v >= 0
    return None


def passes_timer(args, c, timed):
    """
    The "timed runs only" filter: True if a run may be counted. timed is True / False /
    None (see timed_status); a run the API doesn't say anything about is NOT counted
    either - only runs known to be finished in time are. --include-untimed lets all in.
    """
    if args.include_untimed or timed is True:
        return True
    c["skipped_untimed" if timed is False else "skipped_timer_unknown"] += 1
    return False


def recent_run_fields(entry):
    """
    (level, dungeon_label, completed_at, run_id, season, timed) from one
    mythic_plus_recent_runs entry, or from the compact copy the cache keeps of one.
    Those entries have NO run id field - the id and the season sit in 'url':
        https://raider.io/mythic-plus-runs/season-mn-2/1234567-12-the-stonevault
    Other key names are still checked defensively; --debug-guild shows the real keys.
    """
    if isinstance(entry, (list, tuple)):       # compact cache copy, see compact_recent_run()
        level, run_id, season, completed, timed = (list(entry) + [None] * 5)[:5]
        return level, None, completed, run_id, season, timed
    if not isinstance(entry, dict):
        return None, None, None, None, None, None
    level = None
    for key in ("mythic_level", "level", "keystone_level"):
        v = entry.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            level = v
            break
    dungeon = entry.get("dungeon")
    if isinstance(dungeon, dict):
        dungeon = dungeon.get("slug") or dungeon.get("name")
    elif not isinstance(dungeon, str):
        dungeon = entry.get("short_name") or entry.get("dungeon_slug")
    completed = None
    for key in ("completed_at", "completedAt", "completed_timestamp"):
        v = entry.get(key)
        if v:
            completed = v
            break
    season = entry.get("season") if isinstance(entry.get("season"), str) else None
    run_id = entry.get("keystone_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool):
        run_id = None
    url = entry.get("url")
    m = RUN_URL_RE.search(url) if isinstance(url, str) else None
    if m:
        season = season or m.group(1)
        run_id = run_id if run_id is not None else int(m.group(2))
    if run_id is None:
        for key in ("run_id", "id", "mythicPlusId", "mythic_plus_id"):
            v = entry.get(key)
            if isinstance(v, int) and not isinstance(v, bool):
                run_id = v
                break
    return level, dungeon, completed, run_id, season, timed_status(entry)


def compact_recent_run(entry):
    """[level, run_id, season, completed_at, timed] - all the crawl needs of one recent run
    (a profile keeps up to 10 of them, so this is most of the cache's size)."""
    level, _dungeon, completed, run_id, season, timed = recent_run_fields(entry)
    return [level, run_id, season, completed, timed]


def pack_member(member):
    """
    Compact copy of one run-details roster entry for the run cache:
    [region, realm, name, item_level(, guild)] - guild is None (no guild), a name, or
    {'name', 'realm', 'region'} when the API stated more; it is left off when the entry
    had no 'guild' key at all. unpack_member() turns it back into the API's shape, so
    a cached team is counted exactly like a freshly downloaded one.
    """
    ref = character_ref(member) or (None, None, None)
    item = [ref[0], ref[1], ref[2], extract_item_level(member)]
    if "guild" in member:
        name, region, realm = _guild_parts(member.get("guild"))
        if not name:
            item.append(None)
        elif region or realm:
            item.append({k: v for k, v in (("name", name), ("realm", realm), ("region", region)) if v})
        else:
            item.append(name)
    return item


def unpack_member(item):
    region, realm, name, ilvl = (list(item) + [None] * 4)[:4]
    member = {"character": {"name": name, "realm": realm, "region": region}}
    if ilvl is not None:
        member["items"] = {"item_level_equipped": ilvl}
    if len(item) > 4:
        guild = item[4]
        member["guild"] = {"name": guild} if isinstance(guild, str) else guild
    return member


def pack_run(run):
    """Compact copy of one leaderboard run for the page cache:
    [run_id, level, completed_at, timed, [packed members]]."""
    run_id, level = run.get("keystone_run_id"), run.get("mythic_level")
    if not isinstance(run_id, int) or isinstance(run_id, bool):
        run_id = None
    if not isinstance(level, int) or isinstance(level, bool):
        level = None
    roster = run.get("roster") if isinstance(run.get("roster"), list) else []
    return [run_id, level, run.get("completed_at"), timed_status(run),
            [pack_member(m) for m in roster if isinstance(m, dict)]]


def unpack_run(item):
    run_id, level, completed, timed, roster = (list(item) + [None] * 5)[:5]
    return {"id": run_id, "level": level, "completed_at": completed, "timed": timed,
            "roster": [unpack_member(m) for m in roster or []]}


def fetch_profile(ref, with_runs=False):
    """
    One /characters/profile call -> compact cache entry
    {'ilvl', 'crawled', 'guild'[, 'recent_runs']}; 'guild' is None when the character
    has no guild. 'guild' costs nothing extra, so it is always asked for.
    Unknown character (400/404) or a private profile (403, see is_private) -> an empty
    entry, the latter marked 'private'.
    """
    region, realm, name = ref
    fields = "gear,guild" + (",mythic_plus_recent_runs" if with_runs else "")
    try:
        data = api_get("characters/profile",
                       {"region": region, "realm": realm, "name": name, "fields": fields})
    except requests.HTTPError as exc:
        private = is_private(exc)
        if private or getattr(exc.response, "status_code", None) in (400, 404):
            entry = {"ilvl": None, "crawled": None, "guild": None}
            if private:
                entry["private"] = True
            if with_runs:
                entry["recent_runs"] = []
            return entry
        raise
    ilvl = _dig(data, "gear", "item_level_equipped")
    if not isinstance(ilvl, (int, float)) or isinstance(ilvl, bool) or ilvl <= 0:
        ilvl = None
    guild = guild_from(data.get("guild"), region, realm)
    entry = {"ilvl": ilvl, "crawled": data.get("last_crawled_at"), "guild": guild}
    if with_runs:
        entry["recent_runs"] = [compact_recent_run(r) for r in data.get("mythic_plus_recent_runs") or []
                                if isinstance(r, dict)]
    return entry


def char_key(ref):
    return "char:" + ref_key(*ref)


def guild_key(g):
    return "guild:" + ref_key(g["region"], g["realm"], g["name"])


def run_key(season, run_id):
    return f"run:{season}/{run_id}"


class DiskCache:
    """
    Everything downloaded, kept in the raiderio_cache table of an SQLite database so that
    nothing is downloaded twice:
        run:<season>/<id>              team of one run (run-details) + whether it was
                                       timed - kept FOREVER, a finished run never changes
        char:<region>/<realm>/<name>   character profile (item level, guild, recent runs)
        guild:<region>/<realm>/<name>  guild roster (characters + their last crawl time)
        page:<region>/<season>/...     one leaderboard page
        static:<expansion id>          season list (start dates, dungeons)
    Everything but runs is reused for --cache-hours: new runs and members show up in
    them over time; older entries are deleted when the cache is opened. Every download
    is committed at once, so Ctrl+C, a crash or closing the window loses nothing. The
    database can be shared (the planner keeps all its data in one): every thread opens
    its own connection, SQLite's locking keeps the writes apart. path=None (--no-cache):
    in memory only. An older cache file (JSON Lines, or v2/v3 JSON) is imported, see
    import_legacy_cache.
    """
    PERMANENT = ("run",)

    def __init__(self, path, max_age_hours):
        self.path = path
        self.max_age = max_age_hours * 3600
        self.fresh = {}         # key -> entry downloaded in this session: valid whatever its age
        self.failed = False     # writing failed once: carry on, the session still has them (fresh)
        legacy = None
        if path and os.path.exists(path) and not is_sqlite_file(path):
            legacy = path       # an older cache file: imported into a database next to it
            self.path = path = os.path.splitext(path)[0] + ".sqlite"
            print(f"  (cache file {legacy} is in the old format - importing it into {path})", file=sys.stderr)
        try:
            self.db = open_cache_db(path or ":memory:")
        except sqlite3.Error as exc:
            print(f"  (cache {path} can't be opened: {exc} - starting with an empty cache)", file=sys.stderr)
            self.path, self.db = None, open_cache_db(":memory:")
        if legacy:
            import_legacy_cache(legacy, self.db)
        self.existed = self.db.execute("SELECT EXISTS (SELECT 1 FROM raiderio_cache)").fetchone()[0] == 1
        try:
            with self.db:       # expired: it would be downloaded again anyway
                self.db.execute("DELETE FROM raiderio_cache WHERE fetched < ? AND key NOT LIKE 'run:%'",
                                (int(time.time() - self.max_age),))
        except sqlite3.Error:
            pass

    def valid(self, key, entry, now=None):
        if key in self.fresh or key.split(":", 1)[0] in self.PERMANENT:
            return True
        return (now or time.time()) - entry.get("fetched", 0) <= self.max_age

    def get(self, key):
        entry = self.fresh.get(key)
        if entry is not None:
            return entry
        try:
            row = self.db.execute("SELECT value FROM raiderio_cache WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error:
            return None
        entry = _cache_value(row[0]) if row else None
        return entry if entry is not None and self.valid(key, entry) else None

    def counts(self):
        n = defaultdict(int)
        for kind, count in self.db.execute(
                "SELECT substr(key, 1, instr(key, ':') - 1), COUNT(*) FROM raiderio_cache GROUP BY 1"):
            n[kind] += count
        return n

    def entries(self, prefix):
        """(key, entry) of every valid entry whose key starts with prefix."""
        now = time.time()
        rows = self.db.execute("SELECT key, value FROM raiderio_cache WHERE key >= ? AND key < ?",
                               (prefix, prefix + "\U0010ffff"))
        found = {key: _cache_value(value) for key, value in rows}
        found.update((key, entry) for key, entry in self.fresh.items() if key.startswith(prefix))
        return [(key, entry) for key, entry in found.items() if entry is not None and self.valid(key, entry, now)]

    def put(self, key, entry):
        entry = dict(entry, fetched=int(time.time()))
        self.fresh[key] = entry
        try:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO raiderio_cache (key, fetched, value) VALUES (?, ?, ?)",
                                (key, entry["fetched"], json.dumps(entry, ensure_ascii=False, separators=(",", ":"))))
        except sqlite3.Error as exc:
            if not self.failed:
                self.failed = True
                log(f"  (can't write the cache {self.path}: {exc} - continuing without saving)", err=True)
        return entry

    def close(self):
        try:
            self.db.close()
        except sqlite3.Error:
            pass


# The planner's database next to this script (storage.DB_NAME): the planner's window and the
# command line share one cache.
DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "szintezes_adatok.sqlite")
CACHE_TABLE = ("CREATE TABLE IF NOT EXISTS raiderio_cache "
               "(key TEXT PRIMARY KEY, fetched INTEGER NOT NULL, value TEXT NOT NULL)")


def open_cache_db(path):
    """A connection to the cache database (created with its table if needed)."""
    db = sqlite3.connect(path, timeout=30)
    try:
        db.execute(CACHE_TABLE)
        db.commit()
    except sqlite3.Error:
        db.close()
        raise
    return db


def is_sqlite_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _cache_value(text):
    try:
        entry = json.loads(text)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def _cache_record(line):
    """(key, entry) from one line of an old JSON Lines cache, or None if it isn't one (e.g. cut off)."""
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    if isinstance(rec, dict) and isinstance(rec.get("k"), str) and isinstance(rec.get("v"), dict):
        return rec["k"], rec["v"]
    return None


def read_legacy_cache(path):
    """{key: entry} from an older cache file: JSON Lines (v4.0-v4.3; a line cut off by a kill is
    skipped, the last line of a key wins) or one JSON object of profiles (v2/v3)."""
    data = {}
    # errors="replace": a kill in the middle of a multi-byte letter must not make the whole
    # file unreadable - only that (cut off) line is lost
    with open(path, encoding="utf-8", errors="replace") as f:
        first = f.readline()
        while first and not first.strip():
            first = f.readline()
        old = None
        if first.strip() and _cache_record(first) is None and first.lstrip().startswith("{"):
            f.seek(0)
            try:
                old = json.load(f)          # v2/v3 format: one JSON object
            except ValueError:
                old = None
        f.seek(0)
        if isinstance(old, dict):
            for key, entry in old.items():  # profiles {'region/realm/name': entry}
                parts = str(key).split("/", 2)
                if not isinstance(entry, dict) or len(parts) != 3:
                    continue
                runs = entry.get("recent_runs")
                if isinstance(runs, list):
                    entry["recent_runs"] = [compact_recent_run(r) for r in runs if isinstance(r, (dict, list))]
                data[char_key(parts)] = entry
        else:
            for line in f:
                rec = _cache_record(line) if line.strip() else None
                if rec is not None:
                    data[rec[0]] = rec[1]
    return data


def import_legacy_cache(source, target):
    """An older cache file (see read_legacy_cache) into the raiderio_cache table of `target` (a
    database path or an open connection). An entry already there stays if it is newer."""
    entries = read_legacy_cache(source)
    db = target if isinstance(target, sqlite3.Connection) else open_cache_db(str(target))
    try:
        with db:
            db.executemany(
                "INSERT INTO raiderio_cache (key, fetched, value) VALUES (?, ?, ?) ON CONFLICT (key) DO UPDATE "
                "SET fetched = excluded.fetched, value = excluded.value WHERE excluded.fetched > raiderio_cache.fetched",
                [(key, int(entry.get("fetched") or 0), json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
                 for key, entry in entries.items()])
    finally:
        if db is not target:
            db.close()
    return len(entries)


def get_profile(ref, cache, c, need_guild=False, with_runs=False):
    """
    Profile entry for one character with what the caller needs - from the cache if
    possible, otherwise one API call (then cached). None if the lookup failed.
    """
    key = char_key(ref)
    entry = cache.get(key)
    if (entry is not None and (not need_guild or "guild" in entry)
            and (not with_runs or "recent_runs" in entry)):
        c["profile_hits"] += 1
        if entry.get("private"):
            c["private_profiles"] += 1
        return entry
    try:
        entry = cache.put(key, fetch_profile(ref, with_runs))
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        c["lookup_errors"] += 1
        c["error_streak"] += 1
        log(f"  lookup failed for {'/'.join(ref)}: {exc}", err=True)
        if c["error_streak"] >= MAX_ERROR_STREAK:
            raise TooManyErrors(f"{MAX_ERROR_STREAK} character lookups failed in a row (last: {exc})",
                                failure_kind(exc), str(exc))
        return None
    c["error_streak"] = 0
    c["profile_calls"] += 1
    if entry.get("private"):
        c["private_profiles"] += 1
    pause(DELAY)
    return entry


def get_guild_members(g, cache, c):
    """
    (members, from_cache): every member of guild g as ((region, realm, name), last_crawled_at)
    - from the cache if the roster was read within --cache-hours, otherwise one
    /guilds/profile call (then cached). members is None if Raider.IO doesn't know the
    guild (remembered as well, so a wrong realm guess isn't tried again); any other
    failure is raised. last_crawled_at is None when the roster doesn't carry it.
    """
    key = guild_key(g)
    entry = cache.get(key)
    if entry is not None:
        c["guild_hits"] += 1
        members = entry.get("members")
        if members is None:
            return None, True
        return [(tuple(m[:3]), m[3] if len(m) > 3 else None) for m in members], True
    try:
        raw = fetch_guild_members(g["region"], g["realm"], g["name"])
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) not in (400, 404):
            raise
        c["guild_calls"] += 1
        cache.put(key, {"members": None})
        return None, False
    c["guild_calls"] += 1
    pause(DELAY)
    members = []
    for m in raw:
        ref = character_ref(m, default_region=g["region"])
        if ref is None:
            continue
        ch = m.get("character") if isinstance(m.get("character"), dict) else m
        crawled = _text(ch.get("last_crawled_at")) or _text(m.get("last_crawled_at"))
        members.append((ref, crawled))
    cache.put(key, {"members": [list(ref) + ([crawled] if crawled else []) for ref, crawled in members]})
    return members, False


def get_run(season, run_id, cache, c, fetch=True):
    """
    One run's team and whether it was timed: {'roster': [members in the API's shape],
    'timed': True/False/None, 'level', 'completed_at'}, or None. A run that was ever
    downloaded comes from the cache - a finished run never changes, so it is kept
    forever and never downloaded again. Otherwise one run-details call (only if
    fetch), cached at once.
    """
    key = run_key(season, run_id)
    entry = cache.get(key)
    if entry is None:
        if not fetch:
            return None
        try:
            details = api_get("mythic-plus/run-details", {"season": season, "id": run_id})
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            log(f"  run-details {run_id} failed: {exc}", err=True)
            c["details_errors"] += 1
            return None
        c["details_calls"] += 1
        pause(DELAY)
        if not isinstance(details, dict):
            return None
        roster = details.get("roster") or _dig(details, "run", "roster")
        packed = [pack_member(m) for m in roster if isinstance(m, dict)] if isinstance(roster, list) else []
        if not packed:
            return None
        entry = cache.put(key, {"level": details.get("mythic_level"),
                                "completed_at": details.get("completed_at"),
                                "dungeon": _text(details.get("dungeon"), "slug"),
                                "timed": timed_status(details), "roster": packed})
    else:
        c["run_hits"] += 1
    roster = [unpack_member(m) for m in entry.get("roster") or []]
    if not roster:
        return None
    return {"roster": roster, "timed": entry.get("timed"), "level": entry.get("level"),
            "completed_at": entry.get("completed_at")}


def member_ilvl(member, cache, c, need_guild=False):
    """(ilvl, last_crawled_at) for one roster member; (None, None) if unknown."""
    embedded = extract_item_level(member)
    if embedded is not None:
        return embedded, None
    ref = character_ref(member)
    if ref is None:
        c["no_character_ref"] += 1
        return None, None
    entry = get_profile(ref, cache, c, need_guild=need_guild)
    if entry is None:
        return None, None
    return entry.get("ilvl"), entry.get("crawled")


def member_guild(member, cache, c, char_guild):
    """
    Guild of one team member, or None (no guild / can't tell). Free whenever possible:
    a guild roster already read in this crawl, the roster entry's own 'guild' object
    (run-details has it), or the cached profile - one profile call only as a last resort.
    """
    ref = character_ref(member)
    if ref is not None:
        known = char_guild.get(ref_key(*ref))
        if known is not None:
            return known
    if isinstance(member, dict) and "guild" in member:
        g = guild_from(member.get("guild"), ref[0] if ref else None, ref[1] if ref else None)
        if g is not None:
            g["via"] = ref           # lets resolve_guild() look up the real realm later
        return g
    if ref is None:
        return None
    entry = get_profile(ref, cache, c, need_guild=True)
    guild = (entry or {}).get("guild")
    return dict(guild, exact=True) if guild else None


def resolve_guild(g, cache, c):
    """
    A guild known only by name (run-details) had its realm guessed from the member's own
    realm, and no such guild was found there: look that member up once (fields=gear,guild,
    usually cached already) to get the guild's real realm - on connected realms it can be
    a sibling realm. Returns the guild with the real realm, or g unchanged if unknown.
    """
    if g.get("exact") or not g.get("via"):
        return g
    entry = get_profile(g["via"], cache, c, need_guild=True)
    real = (entry or {}).get("guild")
    if real and real.get("realm") and str(real.get("name", "")).lower() == g["name"].lower():
        return {"region": real.get("region") or g["region"], "realm": real["realm"],
                "name": real["name"], "exact": True}
    return g


class GuildQueue:
    """Breadth-first queue of guilds still to read; every guild is queued and read once."""

    def __init__(self):
        self.items = deque()
        self.seen = set()      # keys of every guild ever queued (guessed or exact realm)
        self.done = set()      # keys of guild rosters actually read

    def add(self, g):
        key = ref_key(g["region"], g["realm"], g["name"])
        if key in self.seen:
            return False
        self.seen.add(key)
        self.items.append(g)
        return True

    def pop(self):
        return self.items.popleft()

    def __len__(self):
        return len(self.items)


def enqueue_team_guilds(roster, cache, state, queue):
    """Queue the guild of every member of one team (run roster) that isn't queued yet."""
    c = state["c"]
    for member in roster:
        g = member_guild(member, cache, c, state["char_guild"])
        if g and queue.add(g):
            c["guilds_found"] += 1


# --------------------------------------------------------------------------- statistics

def new_state():
    return {"ilvls": defaultdict(list),     # level -> SORTED item levels (see add_ilvl)
            "runs": defaultdict(int),       # level -> runs counted
            "gaps": [],                     # gear snapshot minus run time, in days
            "c": defaultdict(int),          # counters
            "seen_runs": set(),             # run ids already used (leaderboard + crawl)
            "from_cache": {},               # run id -> counted? (--use-cached-runs, before the query)
            "seen_char_level": set(),       # (character, level) pairs used by the self-gear proxy
            "checked": set(),               # characters whose recent runs were read
            "char_guild": {}}               # character -> guild, from guild rosters already read


def add_ilvl(state, level, value):
    bisect.insort(state["ilvls"][level], float(value))    # sorted -> median is instant


def ilvl_in_range(args, value):
    """True if an item level may be counted: inside --min-ilvl..--max-ilvl, both ends
    included (so 250 and 350 themselves count). 0 means no limit on that side."""
    return ((not args.min_ilvl or value >= args.min_ilvl)
            and (not args.max_ilvl or value <= args.max_ilvl))


def ilvl_range_text(args):
    """The --min-ilvl / --max-ilvl range for messages, e.g. '250-350'; None if there is none."""
    lo, hi = args.min_ilvl, args.max_ilvl
    if lo and hi:
        return f"{lo:g}-{hi:g}"
    if lo:
        return f"{lo:g} or more"
    if hi:
        return f"{hi:g} or less"
    return None


def targets_reached(args, state, wanted):
    return bool(wanted and args.per_level
                and all(state["runs"][level] >= args.per_level for level in wanted))


def add_roster_run(args, state, level, completed_dt, roster, cache, need_guild=False):
    """
    Count one run with a known team: every member's item level goes into `level`.
    An item level outside --min-ilvl..--max-ilvl is ignored - that player is left out,
    the rest of the team still counts; a run left without any player because of it
    isn't counted as a run either. Returns True if the run was counted.
    """
    c = state["c"]
    state["runs"][level] += 1
    got_any = out_of_range = False
    for member in roster:
        ilvl, crawled = member_ilvl(member, cache, c, need_guild)
        if ilvl is None:
            c["players_without_ilvl"] += 1
            continue
        if not ilvl_in_range(args, ilvl):
            c["skipped_ilvl_range"] += 1
            out_of_range = True
            continue
        crawled_dt = parse_ts(crawled)
        if completed_dt and crawled_dt:
            gap_days = (crawled_dt - completed_dt).total_seconds() / 86400
            if args.max_gap_days is not None and abs(gap_days) > args.max_gap_days:
                c["skipped_gap"] += 1
                continue
            state["gaps"].append(gap_days)
        add_ilvl(state, level, ilvl)
        got_any = True
    if got_any:
        return True
    if out_of_range:
        state["runs"][level] -= 1        # no player of it is left: not a run of the statistics
        c["runs_ilvl_range"] += 1
        return False
    c["runs_without_ilvl"] += 1
    return True


def percentile(values, p):
    """
    The p-th percentile (0..100) of an already SORTED list, interpolating linearly
    between the two nearest ranks - the same definition as Excel's PERCENTILE.INC
    (PERCENTILIS.TARTALMAZ), numpy.percentile's default and statistics.quantiles(...,
    method="inclusive"). p=50 gives the ordinary median.
    """
    h = (len(values) - 1) * p / 100
    lo = int(h)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (h - lo) * (values[hi] - values[lo])


def summary_rows(state):
    """(level, runs, players, avg, median, p25, min, max) per key level.
    p25 = 25th percentile: a quarter of the players' item levels are below it."""
    rows = []
    for level in sorted(state["ilvls"]):
        v = state["ilvls"][level]              # kept sorted by add_ilvl()
        if not v:
            continue
        n = len(v)
        rows.append((level, state["runs"][level], n, round(sum(v) / n, 1),
                     round(percentile(v, 50), 1), round(percentile(v, 25), 1),
                     round(v[0], 1), round(v[-1], 1)))
    return rows


def format_table(rows):
    lines = [f"{'Level':>6} | {'Runs':>5} | {'Players':>7} | {'Avg':>7} | {'Median':>7} | "
             f"{'P25':>7} | {'Min':>5} | {'Max':>5}", "-" * 70]
    for r in rows:
        lines.append(f"{r[0]:>6} | {r[1]:>5} | {r[2]:>7} | {r[3]:>7} | {r[4]:>7} | "
                     f"{r[5]:>7} | {r[6]:>5g} | {r[7]:>5g}")
    return lines


def write_csv(path, rows):
    """Write the summary table; via a temp file, so a reader never sees half a file."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["mythic_level", "runs", "players", "avg_item_level",
                         "median_item_level", "p25_item_level", "min_item_level", "max_item_level"])
        writer.writerows(rows)
    os.replace(tmp, path)


def enable_ansi():
    """True if stdout is a console that understands ANSI cursor codes. On Windows 10+
    this also switches the console's VT mode on (Python doesn't do that by itself)."""
    try:
        if not sys.stdout.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.name != "nt":
        return os.environ.get("TERM", "") != "dumb"
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel32.GetStdHandle(-11)            # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:                        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


class LiveView:
    """
    Keeps the statistics on screen while data is collected. After every run that
    changes the numbers the table is recomputed and redrawn in place - at most once
    per --refresh-seconds, and always right before the next network wait, so what
    you see is never more than one API call behind. Without an ANSI console (or
    with --no-live) the table is printed as plain text after each run instead.
    --csv is rewritten on every update as well.
    """

    def __init__(self, state, queue, title, in_place, csv_path, min_interval):
        self.state, self.queue, self.title = state, queue, title
        self.in_place = in_place
        self.csv_path = csv_path
        self.min_interval = max(min_interval, 0.0)
        self.status = ""
        self.events = deque(maxlen=12)
        self.stats_dirty = self.screen_dirty = False
        self.last_draw = 0.0
        self.started = time.monotonic()
        self.active = False           # True while the in-place view owns the console
        self.csv_failing = False
        self.last_size = None

    # -- lifecycle
    def start(self):
        if self.in_place:
            self.active = True
            sys.stdout.write("\033[?25l\033[2J\033[H")      # hide cursor, clear screen
            self.draw()

    def stop(self, final_status=None):
        if final_status:
            self.status = final_status
        if self.stats_dirty or self.active:
            self.draw()                                    # final frame, never a stale one
        if self.active:
            self.active = False
            sys.stdout.write("\033[?25h")                  # cursor back
            sys.stdout.flush()

    # -- inputs
    def set_status(self, text):
        self.status = text
        self.screen_dirty = True
        self.refresh()

    def event(self, text):
        self.events.append(time.strftime("%H:%M:%S ") + " ".join(str(text).split()))
        self.screen_dirty = True

    def changed(self):
        self.stats_dirty = True
        self.refresh()

    def refresh(self):
        if time.monotonic() - self.last_draw >= self.min_interval:
            self.before_wait()

    def before_wait(self):
        if self.stats_dirty or (self.active and self.screen_dirty):
            self.draw()

    # -- output
    def elapsed(self):
        s = int(time.monotonic() - self.started)
        return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"

    def progress(self):
        c = self.state["c"]
        text = f"runs used {sum(self.state['runs'].values())}"
        dropped = c["skipped_untimed"] + c["skipped_timer_unknown"]
        if dropped:
            text += f" (not timed, left out: {dropped})"
        if c["skipped_ilvl_range"]:
            text += f" | ilvl out of range, left out: {c['skipped_ilvl_range']} player(s)"
        if c["guilds_done"] or len(self.queue):
            text += (f" | guilds read {c['guilds_done']}, waiting {len(self.queue)}"
                     f" | characters checked {c['chars_checked']}")
        if c["cached_runs"]:
            text += f" | counted straight from the cache: {c['cached_runs']} run(s)"
        return text

    def api_line(self):
        c = self.state["c"]
        text = (f"API requests {HTTP_CALLS} | from cache: {c['run_hits']} run(s), "
                f"{c['profile_hits']} profile(s), {c['guild_hits']} guild roster(s)"
                + (f", {c['page_hits']} leaderboard page(s)" if c["page_hits"] or c["page_calls"] else ""))
        errors = c["lookup_errors"] + c["details_errors"] + c["guild_errors"]
        return text + (f" | errors {errors}" if errors else "")

    def draw(self):
        self.last_draw = time.monotonic()
        stats_changed = self.stats_dirty
        self.stats_dirty = self.screen_dirty = False
        rows = summary_rows(self.state)
        if stats_changed and self.csv_path and rows:
            self.save_csv(rows)
        if self.active:
            width, height = shutil.get_terminal_size((100, 30))
            lines = self.render_live(rows, width, height)
            head = "\033[H"
            if (width, height) != self.last_size:           # resized: wipe leftovers
                head = "\033[2J\033[H"
                self.last_size = (width, height)
            sys.stdout.write(head + "".join(line + "\033[K\n" for line in lines) + "\033[J")
            sys.stdout.flush()
        else:
            print("\n".join([f"\n--- statistics | {self.elapsed()} | {self.progress()}",
                             f"--- {self.api_line()}"]
                            + (format_table(rows) if rows else ["(no item level data yet)"])),
                  flush=True)

    def render_live(self, rows, width, height):
        head = [f"{self.title} | {self.elapsed()} | Ctrl+C = stop + final summary",
                self.progress(), self.api_line(), f"now: {self.status}" if self.status else "", ""]
        table = format_table(rows) if rows else ["(no item level data yet - waiting for the first run)"]
        budget = max(height - 1, 5)          # never touch the last line: that would scroll
        lines = head + table
        if len(lines) > budget:
            keep = max(budget - len(head) - 1, 1)
            lines = head + table[:keep] + [f"... {len(table) - keep} more row(s) - make the window "
                                           f"taller (all rows: --csv / final summary)"]
        elif self.events and budget - len(lines) >= 3:
            lines += ["", "recent events:"] + list(self.events)[-(budget - len(lines) - 2):]
        cut = max(width - 1, 20)             # a wrapped line would break the redraw
        return [line[:cut] for line in lines[:budget]]

    def save_csv(self, rows):
        try:
            write_csv(self.csv_path, rows)
        except OSError as exc:
            if not self.csv_failing:
                log(f"could not update {self.csv_path} ({exc.__class__.__name__} - open in Excel?), "
                    f"retrying on every update", err=True)
            self.csv_failing = True
        else:
            if self.csv_failing:
                log(f"{self.csv_path} is being updated again")
            self.csv_failing = False


# --------------------------------------------------------------------------- cached runs

def add_cached_runs(args, season, regions, cache, state):
    """
    --use-cached-runs: count every run of `season` in the cache - whichever earlier query
    downloaded it - that passes the filters: one of `regions` (None: any), --levels,
    --since-days, timed only, --min-ilvl / --max-ilvl, --per-level (newest runs first) and
    --dungeon where the query uses it too (a run cached before v4.3 doesn't know its
    dungeon). Called before the query, which doesn't count these runs again: it only
    follows their teams' guilds when it reaches them (see follow_cached_team), so the
    crawl goes on just as without this option. Returns how many runs were counted.
    """
    wanted = parse_levels(args.levels)
    # like the query: --dungeon only filters a single leaderboard query
    dungeon = None if args.guild or args.each_dungeon or args.dungeon == "all" else args.dungeon
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.since_days)
              if args.since_days else None)
    c, seen, from_cache = state["c"], state["seen_runs"], state["from_cache"]
    prefix = run_key(season, "")
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    candidates = []
    for key, entry in cache.entries(prefix):
        level, completed = entry.get("level"), parse_ts(entry.get("completed_at"))
        if not isinstance(level, int) or isinstance(level, bool):
            continue
        if wanted is not None and level not in wanted:
            continue
        if cutoff and (completed is None or completed < cutoff):
            continue
        if not (args.include_untimed or entry.get("timed") is True):
            continue
        if dungeon is not None and entry.get("dungeon") != dungeon:
            continue
        roster = [unpack_member(m) for m in entry.get("roster") or []]
        refs = [ref for ref in map(character_ref, roster) if ref]
        if regions is not None and (not refs or refs[0][0] not in regions):
            continue
        run_id = key[len(prefix):]
        candidates.append((completed or oldest, int(run_id) if run_id.isdigit() else run_id, level, roster))
    counted = 0
    for completed, run_id, level, roster in sorted(candidates, key=lambda item: item[0], reverse=True):
        if STOP.is_set():
            raise Stopped()
        if run_id in seen or (args.per_level and state["runs"][level] >= args.per_level):
            continue
        from_cache[run_id] = add_roster_run(args, state, level, None if completed == oldest else completed,
                                            roster, cache)
        if from_cache[run_id]:
            counted += 1
            c["cached_runs"] += 1
            live_changed()
    return counted


def follow_cached_team(season, run_id, cache, state, queue):
    """The query reached a run --use-cached-runs counted already: it isn't counted again,
    but its team's guilds are queued as if it had been counted now."""
    team = get_run(season, run_id, cache, state["c"], fetch=False)
    if team:
        enqueue_team_guilds(team["roster"], cache, state, queue)


# --------------------------------------------------------------------------- leaderboard

def iter_pages(args, season, dungeon, cache, c):
    """
    Yield (page_number, [run, ...]) for one leaderboard query; each run is a compact
    dict {'id', 'level', 'completed_at', 'timed', 'roster'} (see pack_run). A page is
    reused from the cache for --cache-hours - the ranking shifts a little as new runs
    come in, but for a statistic a day-old page is just as good a sample.
    """
    for page in range(args.max_pages):
        key = f"page:{args.region}/{season}/{dungeon}/{args.affixes}/{page}"
        entry = cache.get(key)
        if entry is not None:
            c["page_hits"] += 1
        else:
            params = {"region": args.region, "season": season, "dungeon": dungeon,
                      "affixes": args.affixes, "page": page}
            try:
                data = api_get("mythic-plus/runs", params)
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                log(f"  page {page}: {'HTTP ' + str(status) if status else exc} - stopping this query")
                return
            c["page_calls"] += 1
            pause(DELAY)
            rankings = data.get("rankings") if isinstance(data, dict) else None
            packed = [pack_run(e.get("run", e)) for e in rankings or [] if isinstance(e, dict)]
            entry = cache.put(key, {"runs": packed})
        runs = [unpack_run(r) for r in entry.get("runs") or []]
        if not runs:
            log(f"  page {page}: no results, stopping this query")
            return
        yield page, runs


def collect(args, season, dungeons, cache, state, queue):
    """Walk the leaderboard and fill `state` (also on Ctrl+C - state is mutated in place).
    With --follow-guilds the guild of every team member is queued for crawl_guilds()."""
    wanted = parse_levels(args.levels)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.since_days)
              if args.since_days else None)
    c, seen, follow = state["c"], state["seen_runs"], args.follow_guilds

    queries = dungeons if args.each_dungeon else [args.dungeon]
    for dungeon in queries:
        if args.each_dungeon:
            log(f"--- dungeon: {dungeon}")
        for page, runs in iter_pages(args, season, dungeon, cache, c):
            live_status(f"leaderboard {dungeon}, page {page}")
            for run in runs:
                level, run_id = run["level"], run["id"]
                if level is None or (run_id is not None and run_id in seen):
                    continue
                if run_id is not None:
                    seen.add(run_id)
                if run_id in state["from_cache"]:       # counted already (--use-cached-runs)
                    if follow and state["from_cache"][run_id]:
                        follow_cached_team(season, run_id, cache, state, queue)
                    continue
                if wanted is not None and level not in wanted:
                    continue
                if args.per_level and state["runs"][level] >= args.per_level:
                    continue
                completed = parse_ts(run["completed_at"])
                if cutoff and (completed is None or completed < cutoff):
                    c["skipped_old"] += 1
                    continue
                timed = run["timed"]
                if timed is False and not args.include_untimed:
                    passes_timer(args, c, timed)         # over the timer: nothing downloaded
                    continue

                # the team from run-details (item levels as of the run, 1 call for all 5
                # players, cached forever) - or the leaderboard roster + profile lookups
                # with --no-run-details; a team downloaded before is free either way
                team = get_run(season, run_id, cache, c, fetch=args.use_run_details) \
                    if run_id is not None else None
                if team and team["timed"] is not None:
                    timed = team["timed"]                 # run-details has the final word
                if not passes_timer(args, c, timed):
                    continue
                roster = team["roster"] if team else run["roster"]
                counted = add_roster_run(args, state, level, completed, roster, cache, need_guild=follow)
                if follow and counted:
                    enqueue_team_guilds(roster, cache, state, queue)
                live_changed()

            levels = [r["level"] for r in runs if r["level"] is not None]
            span = f"{min(levels)}-{max(levels)}" if levels else "?"
            log(f"  page {page}: levels {span} ({len(runs)} runs) | downloaded: {c['details_calls']} "
                f"run(s), {c['profile_calls']} profile(s) | from cache: {c['run_hits']} run(s), "
                f"{c['profile_hits']} profile(s)" + (f" | guilds queued {len(queue)}" if follow else ""))
            if targets_reached(args, state, wanted):
                return "reached --per-level for every requested level"
    return None


# --------------------------------------------------------------------------- guild crawl

def crawl_guilds(args, season, started, cache, state, queue):
    """
    Read guild rosters from `queue` (breadth-first) and every member's recent runs
    (NOT score-sorted, see "SAMPLING BY GUILD ROSTER"). With follow on, every team
    pulled via run-details queues the guilds of its members, so this can go on for a
    very long time: the live view keeps the table current, Ctrl+C stops it.
    `started` is the season's start (or None). Returns why it stopped.
    """
    wanted = parse_levels(args.levels)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.since_days)
              if args.since_days else None)
    c = state["c"]
    follow = args.follow_guilds
    use_details = args.use_run_details or follow
    seen_runs, seen_char_level = state["seen_runs"], state["seen_char_level"]
    checked, char_guild = state["checked"], state["char_guild"]
    warned_no_id = False
    # Raider.IO crawls a character whenever it turns up in a new run, so a member whose
    # last_crawled_at (when the roster carries it) predates the season - or the
    # --since-days window - can't have a run we'd use: its profile isn't downloaded.
    idle_before = None if args.include_idle else max((t for t in (started, cutoff) if t), default=None)

    while len(queue):
        if targets_reached(args, state, wanted):
            return "reached --per-level for every requested level"
        if args.max_guilds and c["guilds_done"] >= args.max_guilds:
            return f"reached --max-guilds {args.max_guilds}"
        g = queue.pop()
        if not g.get("exact") and g.get("via"):
            # the same guild is often found again through a member on another (connected)
            # realm; if the roster that lists this member has been read meanwhile, that is
            # the real guild - known for free, no guess to try
            known = char_guild.get(ref_key(*g["via"]))
            if known is not None and known["name"].lower() == g["name"].lower():
                g = known
        key = ref_key(g["region"], g["realm"], g["name"])
        if key in queue.done:
            c["guilds_found"] -= 1     # a realm guess that turned out to be a guild already read
            continue
        queue.done.add(key)
        label = f"{g['name']}@{g['realm']}@{g['region']}"
        live_status(f"guild {label} - reading the roster")
        try:
            roster, from_cache = get_guild_members(g, cache, c)
            if roster is None and not g.get("exact") and g.get("via"):
                # run-details names the guild only, so its realm was guessed from the
                # member's own realm - right most of the time, and then free. It wasn't
                # there: the member's profile tells the real realm (connected realms).
                real = resolve_guild(g, cache, c)
                real_key = ref_key(real["region"], real["realm"], real["name"])
                if real.get("exact") and real_key != key:
                    queue.seen.add(real_key)
                    if real_key in queue.done:
                        c["guilds_found"] -= 1
                        continue
                    queue.done.add(real_key)
                    g, key = real, real_key
                    label = f"{g['name']}@{g['realm']}@{g['region']}"
                    roster, from_cache = get_guild_members(g, cache, c)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            c["guild_errors"] += 1
            log(f"  guild {label}: failed to fetch roster ({exc})", err=True)
            continue
        if roster is None:
            c["guilds_not_found"] += 1
            log(f"  guild {label}: not found on Raider.IO")
            continue
        c["guilds_done"] += 1

        this_guild = {"region": g["region"], "realm": g["realm"], "name": g["name"], "exact": True}
        members, idle = [], 0
        for ref, crawled in roster:
            k = ref_key(*ref)
            char_guild[k] = this_guild
            if k in checked:
                continue
            crawled_dt = parse_ts(crawled) if idle_before else None
            if crawled_dt and crawled_dt < idle_before:
                idle += 1
                continue
            members.append(ref)
        c["skipped_idle"] += idle
        log(f"  guild {label}{' (cache)' if from_cache else ''}: {len(roster)} member(s), "
            f"{len(members)} to check" + (f", {idle} idle skipped" if idle else "")
            + (f" | {len(queue)} guild(s) waiting" if follow else ""))

        for i, ref in enumerate(members, 1):
            if args.max_members and c["chars_checked"] >= args.max_members:
                return f"reached --max-members {args.max_members}"
            if targets_reached(args, state, wanted):
                return "reached --per-level for every requested level"
            k = ref_key(*ref)
            if k in checked:
                continue
            checked.add(k)
            c["chars_checked"] += 1
            live_status(f"guild {label} - member {i}/{len(members)}: {ref[2]}")
            entry = get_profile(ref, cache, c, with_runs=True)
            if entry is None:
                continue

            for run_entry in entry.get("recent_runs") or []:
                level, _dungeon, completed, run_id, run_season, timed = recent_run_fields(run_entry)
                if level is None:
                    continue
                if run_season and run_season != season:
                    c["skipped_other_season"] += 1
                    continue
                if run_id in state["from_cache"]:       # counted already (--use-cached-runs)
                    if run_id not in seen_runs:
                        seen_runs.add(run_id)
                        if follow and state["from_cache"][run_id]:
                            follow_cached_team(run_season or season, run_id, cache, state, queue)
                    continue
                if wanted is not None and level not in wanted:
                    continue
                if args.per_level and state["runs"][level] >= args.per_level:
                    continue
                completed_dt = parse_ts(completed)
                if cutoff and (completed_dt is None or completed_dt < cutoff):
                    c["skipped_old"] += 1
                    continue
                if run_id is not None and run_id in seen_runs:
                    continue   # this team was already counted (or rejected) through someone else
                if timed is False and not args.include_untimed:
                    passes_timer(args, c, timed)            # over the timer: not even downloaded
                    if run_id is not None:
                        seen_runs.add(run_id)
                    continue

                team = None
                if use_details and run_id is not None:       # cached forever once downloaded
                    team = get_run(run_season or season, run_id, cache, c)
                if team and team["timed"] is not None:
                    timed = team["timed"]                    # run-details has the final word
                if not passes_timer(args, c, timed):
                    if run_id is not None:
                        seen_runs.add(run_id)
                    continue
                if team:
                    seen_runs.add(run_id)
                    counted = add_roster_run(args, state, level, completed_dt, team["roster"], cache)
                    if follow and counted:
                        enqueue_team_guilds(team["roster"], cache, state, queue)
                    live_changed()
                    continue

                if use_details:
                    # wanted the real team but didn't get one: no usable run id in this
                    # entry, or run-details had nothing for it
                    c["run_details_unavailable"] += 1
                    if run_id is None and not warned_no_id:
                        warned_no_id = True
                        log("  a recent run had no run id / url - its team can't be fetched, "
                            "the character's own gear is used for it", err=True)

                pair = (k, level)             # self-gear proxy: at most one point per char per level
                if pair in seen_char_level:
                    continue
                seen_char_level.add(pair)
                ilvl = entry.get("ilvl")
                if ilvl is None:
                    c["players_without_ilvl"] += 1
                    continue
                if not ilvl_in_range(args, ilvl):
                    c["skipped_ilvl_range"] += 1
                    continue
                crawled_dt = parse_ts(entry.get("crawled"))
                if completed_dt and crawled_dt:
                    gap_days = (crawled_dt - completed_dt).total_seconds() / 86400
                    if args.max_gap_days is not None and abs(gap_days) > args.max_gap_days:
                        c["skipped_gap"] += 1
                        continue
                    state["gaps"].append(gap_days)
                state["runs"][level] += 1
                add_ilvl(state, level, ilvl)
                live_changed()

    return "the guild queue is empty - nothing left to crawl" if follow else None


# --------------------------------------------------------------------------- output

def summary_lines(state, queue=None, ilvl_range=None):
    """The final summary as lines of text: the table, the API use and what the counters say."""
    c = state["c"]
    rows = summary_rows(state)
    lines = []
    if rows:
        lines.append("")
        lines += format_table(rows)
        lines.append("(Players = roster slots with a known item level)")
        lines.append("(P25 = 25th percentile: a quarter of the item levels are below it)")
        if ilvl_range:
            lines.append(f"(Only item levels {ilvl_range} are counted, the rest is ignored - "
                         f"--min-ilvl / --max-ilvl)")
    else:
        lines += ["", "No item level data was collected.",
                  "Run with --probe to see where the API exposes item level, and check that",
                  "--levels / --since-days / --max-gap-days / --min-ilvl / --max-ilvl aren't",
                  "filtering everything out."]

    lines += ["", f"API use: {HTTP_CALLS} request(s) - downloaded {c['details_calls']} run(s), "
              f"{c['profile_calls']} profile(s), {c['guild_calls']} guild roster(s), "
              f"{c['page_calls']} leaderboard page(s)"
              + (f", {c['lookup_errors']} lookup(s) failed" if c["lookup_errors"] else "")]
    lines.append(f"From the cache: {c['run_hits']} run(s), {c['profile_hits']} profile(s), "
                 f"{c['guild_hits']} guild roster(s), {c['page_hits']} leaderboard page(s)")
    if c["cached_runs"]:
        lines.append(f"Counted straight from the cache (--use-cached-runs): {c['cached_runs']} run(s) "
                     f"downloaded by earlier queries")
    waiting = len(queue) if queue is not None else 0
    if c["guilds_done"] or waiting:
        lines.append(f"Guild crawl: {c['guilds_done']} guild roster(s) read, {waiting} still waiting, "
                     f"{c['chars_checked']} character(s) checked, {c['guilds_found']} guild(s) "
                     f"discovered through teams")
    gaps = state["gaps"]
    if gaps:
        spread = sorted(abs(g) for g in gaps)
        p90 = spread[int(0.9 * (len(spread) - 1))]
        lines.append(f"Gear snapshot vs. run time (n={len(gaps)}): median {median(gaps):+.1f} days, "
                     f"90% within +/-{p90:.1f} days  (positive = snapshot is newer than the run)")
    for key, text in (("players_without_ilvl", "roster slot(s) without item level (character unknown "
                                               "to Raider.IO, not crawled yet, or lookup failed)"),
                      ("runs_without_ilvl", "run(s) had no item level for any roster member"),
                      ("skipped_untimed", "run(s) skipped for going over the timer (--include-untimed "
                                          "counts them too)"),
                      ("skipped_timer_unknown", "run(s) skipped because the API didn't say whether they "
                                                "were timed (--include-untimed counts them too)"),
                      ("skipped_idle", "guild member(s) skipped as idle - not crawled by Raider.IO "
                                       "since the season / --since-days window started "
                                       "(--include-idle checks them too)"),
                      ("private_profiles", "character(s) skipped because their Raider.IO profile is private"),
                      ("skipped_old", "run(s) skipped by --since-days"),
                      ("skipped_gap", "player(s) skipped by --max-gap-days"),
                      ("skipped_ilvl_range", f"player(s) skipped for an item level outside the allowed "
                                             f"range ({ilvl_range})"),
                      ("runs_ilvl_range", f"run(s) not counted at all: no player of the team was left "
                                          f"within the allowed item level range ({ilvl_range})"),
                      ("skipped_other_season", "recent run(s) from another season skipped"),
                      ("no_character_ref", "roster member(s) without region/realm/name"),
                      ("run_details_unavailable", "recent run(s) without a usable team (no run id, "
                                                  "or run-details failed) - the character's own gear "
                                                  "was used instead"),
                      ("details_errors", "run-details call(s) failed"),
                      ("guilds_not_found", "queued guild(s) not found on Raider.IO"),
                      ("guild_errors", "guild roster fetch(es) failed")):
        if c[key]:
            lines.append(f"({c[key]} {text})")
    if KEY_REJECTED:
        lines.append("(Raider.IO refused the API key, so the query went on without it - correct or remove "
                     "--api-key / RAIDERIO_API_KEY)")
    return lines


def print_summary(state, queue=None, ilvl_range=None):
    for line in summary_lines(state, queue, ilvl_range):
        print(line)
    return summary_rows(state)


# --------------------------------------------------------------------------- diagnostics

def find_ilvl_paths(obj, path="", found=None):
    """Recursively list (path, value) of item-level-looking numeric fields."""
    if found is None:
        found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}" if path else str(key)
            if (str(key).lower() in ILVL_KEYS and isinstance(value, (int, float))
                    and not isinstance(value, bool)):
                found.append((here, value))
            find_ilvl_paths(value, here, found)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            find_ilvl_paths(value, f"{path}[{i}]", found)
    return found


def unique_paths(found):
    """Collapse roster[0]/roster[1]/... into roster[]; overall levels ('equipped', 'total') first."""
    seen, out = set(), []
    for path, value in found:
        pattern = re.sub(r"\[\d+\]", "[]", path)
        if pattern not in seen:
            seen.add(pattern)
            out.append((pattern, value))
    rank = lambda pv: 0 if "equipped" in pv[0].lower() else 1 if "total" in pv[0].lower() else 2
    return sorted(out, key=rank)


def report(label, obj, dump):
    print(label)
    roster = obj.get("roster") if isinstance(obj, dict) else None
    if roster:
        print(f"    roster[0] keys: {', '.join(map(str, roster[0].keys()))}")
    paths = unique_paths(find_ilvl_paths(obj))
    if paths:
        for path, value in paths[:8]:
            print(f"    item level field: {path} = {value}")
    else:
        print("    no item level field in this response")
    dump[label] = obj


def first_page(args, season):
    data = api_get("mythic-plus/runs", {"region": args.region, "season": season,
                                        "dungeon": args.dungeon, "affixes": args.affixes,
                                        "page": 0})
    return [entry.get("run", entry) for entry in (data.get("rankings") or [])], data


def run_scan_affixes(args, season):
    """
    Try each of several --affixes guesses against page 0 and report the level
    range (plus the top run's REAL weekly_modifiers) for each, side by side -
    the fast way to see whether a guess actually narrows the level range,
    without spending a full collection run on each one to find out. Read-only,
    page 0 of each guess only; writes no files.
    """
    slugs = [s.strip() for s in args.scan_affixes.split(",") if s.strip()]
    if not slugs:
        print("--scan-affixes needs at least one comma-separated value, e.g. fortified,tyrannical")
        return
    print(f"scanning {len(slugs)} affix value(s) - region={args.region} dungeon={args.dungeon}\n")
    width = max(len(s) for s in slugs)
    for slug in slugs:
        probe_args = argparse.Namespace(**{**vars(args), "affixes": slug})
        try:
            runs, _ = first_page(probe_args, season)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"  {slug:<{width}}  failed: {exc}")
            continue
        if not runs:
            print(f"  {slug:<{width}}  no runs returned (probably not a valid slug)")
            continue
        levels = sorted({r.get("mythic_level") for r in runs if r.get("mythic_level") is not None})
        span = f"{levels[0]}-{levels[-1]}" if levels else "?"
        mods = runs[0].get("weekly_modifiers") or []
        tags = ", ".join(m.get("slug", "?") for m in mods) or "none"
        print(f"  {slug:<{width}}  levels {span:<8} ({len(levels)} distinct: {levels})  "
              f"top run's real affixes: {tags}")
        pause(DELAY)
    print("\nA narrow, low level span here means that slug gates on level the way "
          "lindormis-guidance gates on 2-5. If every guess still shows high levels (or the "
          "same span as 'all'), none of them isolate a low bracket the way you'd need.")


def run_debug_raw(args, season):
    """
    Print the *shape* of one leaderboard entry, plus the level range across the
    whole page-0 batch (cheap way to test a --dungeon/--affixes/--region guess:
    does it return anything, and what levels does it actually reach?). Saves
    the complete sample entry to a file.
    """
    runs, data = first_page(args, season)
    if not runs:
        print("The leaderboard returned no runs for this region/dungeon/affixes combination.")
        return
    sample = (data.get("rankings") or [{}])[0]
    with open("debug_raw_run.json", "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2, ensure_ascii=False)
    run = runs[0]
    roster = run.get("roster") or [{}]
    print(f"entry keys        : {', '.join(sample.keys())}")
    print(f"run keys          : {', '.join(run.keys())}")
    print(f"roster[0] keys    : {', '.join(roster[0].keys())}")
    print(f"character keys    : {', '.join((roster[0].get('character') or {}).keys())}")
    paths = unique_paths(find_ilvl_paths(sample))
    print("item level fields : " + (", ".join(f"{p}={v}" for p, v in paths) if paths else "none"))

    levels = sorted({r.get("mythic_level") for r in runs if r.get("mythic_level") is not None})
    if levels:
        print(f"\npage 0 levels     : {levels[0]}-{levels[-1]} across {len(runs)} runs "
              f"({len(levels)} distinct level(s): {levels})")
    modifiers = run.get("weekly_modifiers") or []
    if modifiers:
        tags = ", ".join(f"{m.get('name')} (slug={m.get('slug')}, id={m.get('id')})"
                         for m in modifiers)
        print(f"top run's affixes : {tags}")
    timer = {k: run.get(k) for k in ("num_chests", "clear_time_ms", "keystone_time_ms", "time_remaining_ms")
             if k in run}
    flags = [timed_status(r) for r in runs]
    print(f"top run's timer   : {timer or 'no timer fields'} -> timed={timed_status(run)}")
    print(f"page 0 timed      : {flags.count(True)} timed, {flags.count(False)} over the timer, "
          f"{flags.count(None)} unknown (unknown ones are decided by run-details)")
    print("\nComplete JSON of the top-ranked entry saved to debug_raw_run.json (nothing truncated).")


def run_debug_guild(args, season):
    """
    Inspect ONE real character's mythic_plus_recent_runs entry from the first
    --guild given, so the field names recent_run_fields() reads (level, dungeon,
    completed_at, run id from the url) can be checked - or fixed - before trusting
    a full --guild crawl. Saves the complete profile response to a file.
    """
    if not args.guild:
        print("--debug-guild needs at least one --guild Name@realm value")
        return
    try:
        region, realm, name = parse_guild_spec(args.guild[0], args.region)
    except ValueError as exc:
        print(f"  {exc}")
        return
    print(f"guild: {name}@{realm}@{region}\n")
    try:
        raw_members = fetch_guild_members(region, realm, name)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"failed to fetch guild roster: {exc}")
        return
    print(f"roster size: {len(raw_members)} member(s)")
    if not raw_members:
        print("(empty or unknown guild - double check the name/realm/region)")
        return
    print(f"member[0] keys          : {', '.join(raw_members[0].keys())}")
    print(f"member[0].character keys: {', '.join((raw_members[0].get('character') or {}).keys())}")
    crawled = _dig(raw_members[0], "character", "last_crawled_at") or raw_members[0].get("last_crawled_at")
    crawled_text = crawled if crawled else ("NOT in the roster - idle members can not "
                                            "be skipped, every profile is downloaded")
    print(f"member[0] last_crawled_at: {crawled_text}")   # (one line: Python < 3.12 needs it so)

    refs = [r for r in (character_ref(m, default_region=region) for m in raw_members) if r]
    if not refs:
        print("\nCould not extract a (region, realm, name) reference from any member - "
              "check the keys above; character_ref() may need a new fallback path.")
        return
    print(f"parsed characters       : {len(refs)} of {len(raw_members)}")
    ref = refs[0]
    print(f"\nchecking character: {'/'.join(ref)}")
    raw = api_get("characters/profile", {"region": ref[0], "realm": ref[1], "name": ref[2],
                                         "fields": "gear,guild,mythic_plus_recent_runs"})
    with open("debug_guild_run.json", "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
    print(f"guild field             : {raw.get('guild')}")
    runs = raw.get("mythic_plus_recent_runs") or []
    print(f"mythic_plus_recent_runs: {len(runs)} entr{'y' if len(runs) == 1 else 'ies'} this season")
    if not runs:
        print("(this character has none - re-run --debug-guild, a later member may have some)")
        return
    entry = runs[0]
    print(f"entry[0] keys           : {', '.join(entry.keys())}")
    print(f"entry[0] url            : {entry.get('url')}")
    level, dungeon, completed, run_id, run_season, timed = recent_run_fields(entry)
    print(f"parsed                  : level={level} dungeon={dungeon} "
          f"completed_at={completed} run_id={run_id} season={run_season} "
          f"timed={'unknown (no timer field found - see the keys above)' if timed is None else timed}")
    if run_id is None:
        print("-> no usable run id found: the team of these runs can't be fetched, so guilds can't "
              "be followed (edit recent_run_fields() if the keys above hold an id somewhere else)")
    else:
        print("-> run id found: run-details can fetch the team of this run, guild following works")
    print("\nComplete profile JSON saved to debug_guild_run.json (nothing truncated).")


def run_probe(args, season):
    """Check, for one real run, which endpoints expose an item level."""
    print("PROBE - where does the API expose item level?\n")
    dump = {}
    runs, _ = first_page(args, season)
    if not runs:
        print("The leaderboard returned no runs - nothing to probe.")
        return
    run = runs[0]
    run_id = run.get("keystone_run_id")
    report("1) /mythic-plus/runs  (leaderboard entry)", run, dump)

    try:
        details = api_get("mythic-plus/run-details", {"season": season, "id": run_id})
        report("2) /mythic-plus/run-details", details, dump)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"2) /mythic-plus/run-details\n    failed: {exc}")

    logged = next((r for r in runs if r.get("logged_run_id")), None)
    label = "3) /live-tracking/user/activity/mythic-plus  (combat-log data, logged runs only)"
    if logged is None:
        print(f"{label}\n    skipped - none of the {len(runs)} runs on page 0 is live-tracked "
              f"(logged_run_id is empty)")
    else:
        try:
            activity = api_get("live-tracking/user/activity/mythic-plus",
                               {"season": season, "run_id": logged.get("keystone_run_id")})
            report(label, activity, dump)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"{label}\n    failed: {exc}")

    roster = run.get("roster") or []
    ref = character_ref(roster[0]) if roster else None
    if ref:
        label = f"4) /characters/profile?fields=gear  ({'/'.join(ref)})"
        try:
            profile = api_get("characters/profile",
                              {"region": ref[0], "realm": ref[1], "name": ref[2], "fields": "gear"})
            report(label, profile, dump)
            print(f"    last_crawled_at = {profile.get('last_crawled_at')}   "
                  f"run completed_at = {run.get('completed_at')}")
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"{label}\n    failed: {exc}")

    with open("probe_output.json", "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2, ensure_ascii=False)
    print("\nFull responses saved to probe_output.json")


# --------------------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(
        description="Average item level per Mythic+ key level, via the Raider.IO API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with --probe first if you want to see where item level is exposed.")
    p.add_argument("--region", default="eu", choices=["us", "eu", "kr", "tw", "cn", "world"])
    p.add_argument("--season", default=None, help="e.g. season-mn-2; auto-detected if omitted")
    p.add_argument("--expansion-id", type=int, default=11,
                   help="used for season auto-detection (11 = Midnight)")
    p.add_argument("--dungeon", default="all", help="dungeon slug, or 'all'")
    p.add_argument("--each-dungeon", action="store_true",
                   help="query every dungeon of the season separately (reaches lower keys; ignores --dungeon)")
    p.add_argument("--affixes", default="all")
    p.add_argument("--levels", default=None,
                   help="comma-separated key levels to keep, e.g. 18,19,20 (default: everything seen)")
    p.add_argument("--per-level", type=int, default=0,
                   help="stop collecting a key level after this many runs (0 = no limit); with "
                        "--levels the whole run/crawl stops once every level has this many")
    p.add_argument("--since-days", type=int, default=None,
                   help="only use runs completed within the last N days")
    p.add_argument("--max-gap-days", type=float, default=None,
                   help="drop players whose gear snapshot is more than N days away from the run")
    p.add_argument("--min-ilvl", type=float, default=250,
                   help="ignore item levels below this (default 250; 0 = no lower limit)")
    p.add_argument("--max-ilvl", type=float, default=350,
                   help="ignore item levels above this (default 350; 0 = no upper limit)")
    p.add_argument("--max-pages", type=int, default=5,
                   help="leaderboard pages per query (API limit: 100, or 1000 with a key)")
    p.add_argument("--use-run-details", dest="use_run_details", action="store_true",
                   help="(default) take every run's team and item levels from mythic-plus/run-details: "
                        "1 call per run, cached forever")
    p.add_argument("--no-run-details", dest="use_run_details", action="store_false",
                   help="leaderboard: look every player up with /characters/profile instead (their "
                        "current gear, up to 5 calls per run); guild mode without following: count "
                        "the character's own gear once per run (no extra calls). Ignored while "
                        "guilds are followed, which needs the real teams")
    p.add_argument("--include-untimed", action="store_true",
                   help="also count runs that went over the timer, or whose timing the API doesn't "
                        "give (default: only runs known to be timed)")
    p.add_argument("--include-idle", action="store_true",
                   help="also download the profile of guild members Raider.IO hasn't crawled since "
                        "the season (or the --since-days window) started - they can't have a run "
                        "we'd use, so by default they are skipped")
    p.add_argument("--cache", default=DEFAULT_CACHE,
                   help="cache database (SQLite; default: the planner's database, szintezes_adatok.sqlite "
                        "next to this script): downloaded runs (kept forever), character profiles, guild "
                        "rosters, leaderboard pages and season data (valid for --cache-hours); an older "
                        "JSON Lines cache file given here is imported into a database next to it")
    p.add_argument("--cache-hours", type=float, default=24,
                   help="how long cached profiles, guild rosters, leaderboard pages and season data "
                        "stay valid (runs never expire)")
    p.add_argument("--no-cache", action="store_true", help="don't read/write the cache file")
    p.add_argument("--use-cached-runs", action="store_true",
                   help="also count every run of the season already in the cache (downloaded by any "
                        "earlier query) that passes the filters - region, --levels, --since-days, timed "
                        "only, --min-ilvl/--max-ilvl, --per-level, --dungeon - not just the runs this "
                        "query reaches")
    p.add_argument("--api-key", default=None, help="Raider.IO access key (or env RAIDERIO_API_KEY)")
    p.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    p.add_argument("--csv", default=None,
                   help="also write the summary to this CSV file (rewritten after every run)")
    p.add_argument("--probe", action="store_true",
                   help="test which endpoints expose item level for one real run, then exit")
    p.add_argument("--debug-raw", action="store_true",
                   help="show the structure of one leaderboard entry (full JSON saved to a file), then exit")
    p.add_argument("--scan-affixes", default=None,
                   help="comma-separated affix slugs to test against page 0, e.g. "
                        "all,fortified,tyrannical,lindormis-guidance - prints the level range "
                        "seen for each guess, then exits (no data collection)")
    p.add_argument("--guild", action="append", default=[], metavar="Name@realm[@region]",
                   help="sample from this guild's roster instead of the leaderboard (reaches "
                        "every key level, not just the highest-scoring ones); repeat for "
                        "several guilds. region defaults to --region if omitted.")
    p.add_argument("--follow-guilds", dest="follow_guilds", action="store_true",
                   help="also crawl the guild of everyone found in a team (run roster), then the "
                        "guilds of THEIR teams, and so on. Default ON with --guild; in "
                        "leaderboard mode it starts once the leaderboard pages are done")
    p.add_argument("--no-follow-guilds", dest="follow_guilds", action="store_false",
                   help="only read the --guild(s) given (the v2 behaviour)")
    p.add_argument("--max-guilds", type=int, default=0,
                   help="stop the crawl after reading this many guild rosters (0 = no limit)")
    p.add_argument("--max-members", type=int, default=None,
                   help="stop the crawl after checking this many characters (default: no cap)")
    p.add_argument("--no-live", action="store_true",
                   help="don't redraw the statistics in place; print them as plain text after "
                        "each run instead (automatic when the output is not a console)")
    p.add_argument("--refresh-seconds", type=float, default=0.5,
                   help="redraw the live statistics at most this often (default 0.5)")
    p.add_argument("--debug-guild", action="store_true",
                   help="show one real character's mythic_plus_recent_runs entry from the first "
                        "--guild (full JSON saved to a file), then exit")
    p.set_defaults(follow_guilds=None, use_run_details=True)
    return p


def prepare_args(args):
    """
    Check the parsed options and fill in what depends on others (--follow-guilds).
    Raises ValueError with the message to show. Returns the guilds the crawl starts
    from, as (region, realm, name).
    """
    if args.levels:
        try:
            parse_levels(args.levels)
        except ValueError:
            raise ValueError("--levels must be comma-separated integers, e.g. 18,19,20") from None
    if args.min_ilvl < 0 or args.max_ilvl < 0:
        raise ValueError("--min-ilvl / --max-ilvl can't be negative (0 = no limit)")
    if args.min_ilvl and args.max_ilvl and args.min_ilvl > args.max_ilvl:
        raise ValueError("--min-ilvl can't be higher than --max-ilvl")
    seeds = [parse_guild_spec(spec, args.region) for spec in args.guild]
    if args.follow_guilds is None:
        args.follow_guilds = bool(args.guild)
    return seeds


def run(args, seeds, make_view, info=print):
    """
    The collection itself - what main() runs, and what the planner's window runs in a
    background thread. make_view(state, queue, title) gives the live view (a LiveView or
    the planner's own); info() shows a line before the view takes over. Returns
    (reason, state, queue, ilvl_range) - reason says why the collection ended early,
    if it did - or None after a diagnostic mode (--probe, --debug-raw, --scan-affixes,
    --debug-guild). Raises StatsError if the season can't be looked up, ValueError for
    options that don't work together, and Stopped if STOP is set before the collection.
    """
    global API_KEY, KEY_REJECTED, DELAY, LIVE, HTTP_CALLS
    HTTP_CALLS = 0
    API_KEY = args.api_key or os.environ.get("RAIDERIO_API_KEY")
    KEY_REJECTED = False
    DELAY = max(args.delay, 0.0)
    page_limit = 1000 if API_KEY else 100
    if args.max_pages > page_limit:
        info(f"(--max-pages lowered to {page_limit}, the API limit{'' if API_KEY else ' without a key'})")
        args.max_pages = page_limit
    ilvl_range = ilvl_range_text(args)

    cache = DiskCache(None if args.no_cache else args.cache, args.cache_hours)
    try:
        if cache.path:
            n = cache.counts()
            info(f"cache {cache.path}: {n['run']} run(s), {n['char']} profile(s), {n['guild']} guild "
                 f"roster(s), {n['page']} leaderboard page(s) - runs are kept forever, the rest for "
                 f"{args.cache_hours:g} h" if cache.existed else f"cache {cache.path}: empty so far")
        try:
            season_info = get_season(args.season, args.region, args.expansion_id, cache)
            season = season_info["slug"]
            if args.guild:
                info(f"season={season}  guild(s)={', '.join(args.guild)}"
                     f"  follow team members' guilds={'yes' if args.follow_guilds else 'no'}"
                     f"  runs: {'all' if args.include_untimed else 'timed only'}"
                     f"  ilvl: {ilvl_range or 'any'}\n")
            else:
                info(f"season={season}  region={args.region}  dungeon={args.dungeon}  "
                     f"affixes={args.affixes}  runs: {'all' if args.include_untimed else 'timed only'}"
                     f"  ilvl: {ilvl_range or 'any'}\n")

            if args.scan_affixes:
                run_scan_affixes(args, season)
                return None
            if args.debug_raw:
                run_debug_raw(args, season)
                return None
            if args.debug_guild:
                run_debug_guild(args, season)
                return None
            if args.probe:
                run_probe(args, season)
                return None
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            raise StatsError(f"Raider.IO request failed: {exc}") from exc

        dungeons = [d["slug"] for d in season_info.get("dungeons") or [] if d.get("slug")]
        if args.each_dungeon and not dungeons and not args.guild:
            raise ValueError("static-data lists no dungeons for this season - use --dungeon <slug> instead")

        started = season_start(season_info, args.region)
        state = new_state()
        queue = GuildQueue()
        for region, realm, name in seeds:
            queue.add({"region": region, "realm": realm, "name": name, "exact": True})

        if args.guild:
            mode = "guild crawl" if args.follow_guilds else "guild roster(s)"
        else:
            mode = f"leaderboard {args.region}" + (" + guild crawl" if args.follow_guilds else "")
        runs_kind = "all runs" if args.include_untimed else "timed runs only"
        title = f"Raider.IO ilvl | {season} | {mode} | {runs_kind}"
        if ilvl_range:
            title += f" | ilvl {ilvl_range}"
        if args.use_cached_runs:
            title += " | + cached runs"
        LIVE = make_view(state, queue, title)
        if args.follow_guilds:
            info("Following the guilds of every team member - this can run for a very long time. "
                 "The statistics update after every run; Ctrl+C stops with a final summary.")
        reason = None
        try:
            LIVE.start()
            if args.use_cached_runs:
                live_status("runs in the cache")
                regions = None if args.region == "world" else {args.region} | {seed[0] for seed in seeds}
                counted = add_cached_runs(args, season, regions, cache, state)
                log(f"  counted straight from the cache: {counted} run(s) downloaded by earlier queries")
            if args.guild:
                reason = crawl_guilds(args, season, started, cache, state, queue)
            else:
                reason = collect(args, season, dungeons, cache, state, queue)
                if args.follow_guilds and reason is None:
                    reason = crawl_guilds(args, season, started, cache, state, queue)
        except KeyboardInterrupt:
            reason = "stopped with Ctrl+C - summarizing what was collected so far"
        except Stopped:
            reason = "stopped - summarizing what was collected so far"
        except TooManyErrors as exc:
            guess = {"rate_limit": "rate limit", "unavailable": "Raider.IO down or no connection",
                     "refused": "requests refused"}.get(exc.kind)
            reason = f"aborted: {exc}{f' - {guess}?' if guess else ''} - summarizing what was collected so far"
            state["abort"] = {"kind": exc.kind, "last": exc.last}
        finally:
            try:
                LIVE.stop(f"finished - {reason}" if reason else "finished")
            finally:
                LIVE = None
        return reason, state, queue, ilvl_range
    finally:
        cache.close()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):    # player names may contain non-ASCII letters
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    p = build_parser()
    args = p.parse_args(argv)
    try:
        seeds = prepare_args(args)
    except ValueError as exc:
        p.error(str(exc))
    in_place = not args.no_live and enable_ansi()

    def console_view(state, queue, title):
        return LiveView(state, queue, title, in_place, args.csv, args.refresh_seconds)

    try:
        result = run(args, seeds, console_view)
    except StatsError as exc:
        sys.exit(str(exc))
    except ValueError as exc:
        p.error(str(exc))
    if result is None:          # a diagnostic mode
        return
    reason, state, queue, ilvl_range = result
    if reason:
        print(f"\n{reason[0].upper()}{reason[1:]}.")
    rows = print_summary(state, queue, ilvl_range)
    if args.csv and rows:
        try:
            write_csv(args.csv, rows)
            print(f"\nWrote summary to {args.csv}")
        except OSError as exc:
            print(f"\nCould not write {args.csv}: {exc} (open in Excel?)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:          # during start-up (season lookup, cache load)
        sys.exit("\nstopped")
