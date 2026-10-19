"""A beépített statisztikai programok (raiderio_ilvl_stats.py, wcl_raid_ilvl_stats.py), a
requests-pótló httpcompat.py és a statisztikai ablakok mezőinek tesztjei – hálózat nélkül."""

import io
import json
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import httpcompat
import raiderio_ilvl_stats as mplus
import wcl_raid_ilvl_stats as wcl

try:
    import stats_windows
except ImportError:  # tkinter nélkül
    stats_windows = None

REAL_WCL_CLIENT = wcl.WCLClient  # a tesztek egy része pótolja


class HttpCompatTests(unittest.TestCase):
    def response(self, body=b"{}", status=200, headers=None):
        message = mock.MagicMock()
        message.__enter__.return_value = message
        message.status = status
        message.geturl.return_value = "https://example.test/x"
        message.read.return_value = body
        message.headers = _headers(headers or {"Content-Type": "application/json; charset=utf-8"})
        return message

    def test_get_with_params_and_session_headers(self):
        session = httpcompat.Session()
        session.headers.update({"Accept": "application/json", "User-Agent": "teszt"})
        with mock.patch.object(httpcompat.urllib.request, "urlopen", return_value=self.response(b'{"a": 1}')) as urlopen:
            response = session.get("https://example.test/api", params={"name": "Héléna", "realm": "Twisting Nether"}, timeout=5)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/api?name=H%C3%A9l%C3%A9na&realm=Twisting+Nether")
        self.assertEqual((request.get_method(), request.get_header("User-agent")), ("GET", "teszt"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)
        self.assertEqual((response.status_code, response.json()), (200, {"a": 1}))
        response.raise_for_status()  # 200: nincs hiba

    def test_post_json_form_and_basic_auth(self):
        with mock.patch.object(httpcompat.urllib.request, "urlopen", return_value=self.response()) as urlopen:
            httpcompat.post("https://example.test/token", data={"grant_type": "client_credentials"}, auth=("id", "titok"))
            form = urlopen.call_args.args[0]
            httpcompat.Session().post("https://example.test/graphql", json={"query": "{ x }"})
            graphql = urlopen.call_args.args[0]
        self.assertEqual(form.data, b"grant_type=client_credentials")
        self.assertEqual(form.get_header("Authorization"), "Basic aWQ6dGl0b2s=")
        self.assertEqual(json.loads(graphql.data), {"query": "{ x }"})
        self.assertEqual(graphql.get_header("Content-type"), "application/json")

    def test_error_statuses_are_responses(self):
        error = urllib.error.HTTPError(
            "https://example.test/x", 429, "Too Many", _headers({"Retry-After": "7"}), io.BytesIO(b'{"message": "lassabban"}')
        )
        with mock.patch.object(httpcompat.urllib.request, "urlopen", side_effect=error):
            response = httpcompat.get("https://example.test/x")
        self.assertEqual((response.status_code, response.headers.get("retry-after")), (429, "7"))
        self.assertEqual(response.json()["message"], "lassabban")
        with self.assertRaises(httpcompat.HTTPError) as caught:
            response.raise_for_status()
        self.assertIs(caught.exception.response, response)
        self.assertIsInstance(caught.exception, httpcompat.exceptions.RequestException)

    def test_network_errors(self):
        with mock.patch.object(httpcompat.urllib.request, "urlopen", side_effect=urllib.error.URLError("nincs net")):
            with self.assertRaisesRegex(httpcompat.ConnectionError, "nincs net"):
                httpcompat.get("https://example.test/x")
        with mock.patch.object(httpcompat.urllib.request, "urlopen", side_effect=TimeoutError("lassú")):
            with self.assertRaises(httpcompat.Timeout):
                httpcompat.get("https://example.test/x")


def _headers(values):
    from email.message import Message

    message = Message()
    for key, value in values.items():
        message[key] = value
    return message


# --------------------------------------------------------------------------- Raider.io (M+)

SEASON = {
    "slug": "season-mn-2",
    "is_main_season": True,
    "starts": {"eu": "2026-09-01T00:00:00Z"},
    "dungeons": [{"slug": "the-stonevault"}],
}


def member(name, ilvl, guild="Solutions"):
    return {
        "character": {"name": name, "realm": {"slug": "ragnaros"}, "region": {"slug": "eu"}},
        "items": {"item_level_equipped": ilvl},
        "guild": {"name": guild},
    }


def us_member(name, ilvl):
    character = member(name, ilvl)
    character["character"]["region"] = {"slug": "us"}
    return character


def leaderboard_run(run_id, level, chests=1):
    return {
        "run": {
            "keystone_run_id": run_id,
            "mythic_level": level,
            "completed_at": "2026-10-10T20:00:00Z",
            "num_chests": chests,
            "roster": [],
        }
    }


class FakeRaiderio:
    """A Raider.io API helyett: a ranglista egy oldala és a futások csapatai."""

    def __init__(self, on_details=None, affix_runs=None):
        self.calls = []
        self.on_details = on_details
        self.affix_runs = affix_runs or {}  # affix → a ranglistán szereplő futások (a többinél mind)
        self.teams = {
            1: (12, [member("Thrall", 320), member("Jaina", 330.5), member("Arthas", 400)]),  # 400: tartományon kívül
            2: (12, [member("Uther", 325)]),
            3: (15, [member("Sylvanas", 335)]),
        }

    def __call__(self, path, params, max_retries=5):
        self.calls.append(path)
        if path == "mythic-plus/static-data":
            return {"seasons": [SEASON]}
        if path == "mythic-plus/runs":
            if params["page"] > 0:
                return {"rankings": []}
            if params["affixes"] in self.affix_runs:
                return {"rankings": [leaderboard_run(i, self.teams[i][0]) for i in self.affix_runs[params["affixes"]]]}
            runs = [leaderboard_run(run_id, level) for run_id, (level, _team) in self.teams.items()]
            return {"rankings": runs + [leaderboard_run(4, 15, chests=0)]}  # időn túli: kimarad
        if path == "mythic-plus/run-details":
            if self.on_details:
                self.on_details(params["id"])
            level, team = self.teams[params["id"]]
            return {
                "mythic_level": level,
                "completed_at": "2026-10-10T20:00:00Z",
                "num_chests": 1,
                "dungeon": {"slug": "the-stonevault", "name": "The Stonevault"},
                "roster": team,
            }
        raise AssertionError(path)


class FakeGuildRaiderio:
    """A guildek bejárásához: a Solutions tagjának futásából derül ki a Bravo, abból a Charlie."""

    GUILDS = {"solutions": ["Thrall"], "bravo": ["Jaina"], "charlie": ["Uther"]}
    RUNS = {  # futás → (kulcsszint, csapat)
        1: (12, [member("Thrall", 320, "Solutions"), member("Jaina", 330, "Bravo")]),
        2: (12, [member("Jaina", 330, "Bravo"), member("Uther", 325, "Charlie")]),
        3: (14, [member("Uther", 325, "Charlie")]),
    }
    RECENT = {"thrall": [1], "jaina": [2], "uther": [3]}  # a tagok legutóbbi futásai

    def __init__(self):
        self.calls = []
        self.completed = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def __call__(self, path, params, max_retries=5):
        self.calls.append(path)
        if path == "mythic-plus/static-data":
            return {"seasons": [SEASON]}
        if path == "mythic-plus/runs":  # a ranglistán csak az 1-es futás van
            return {"rankings": [leaderboard_run(1, 12)] if params["page"] == 0 else []}
        if path == "guilds/profile":
            names = self.GUILDS[params["name"].lower()]
            return {"members": [{"character": {"name": name, "realm": "Ragnaros", "region": "eu"}} for name in names]}
        if path == "characters/profile":
            recent = [
                {
                    "mythic_level": self.RUNS[run_id][0],
                    "completed_at": self.completed,
                    "num_keystone_upgrades": 1,
                    "url": f"https://raider.io/mythic-plus-runs/season-mn-2/{run_id}-12-the-stonevault",
                }
                for run_id in self.RECENT[params["name"].lower()]
            ]
            return {"gear": {"item_level_equipped": 300}, "guild": None, "mythic_plus_recent_runs": recent}
        if path == "mythic-plus/run-details":
            level, team = self.RUNS[params["id"]]
            return {"mythic_level": level, "completed_at": self.completed, "num_chests": 1, "roster": team}
        raise AssertionError(path)


class RaiderioStatsTests(unittest.TestCase):
    def setUp(self):
        mplus.STOP.clear()

    def tearDown(self):
        mplus.STOP.clear()

    def args(self, *argv):
        args = mplus.build_parser().parse_args(["--no-cache", "--delay", "0", *argv])
        return args, mplus.prepare_args(args)

    @staticmethod
    def quiet_view(state, guild_queue, title):
        view = mplus.LiveView(state, guild_queue, title, in_place=False, csv_path=None, min_interval=0)
        view.draw = lambda: None
        return view

    def test_leaderboard_statistics(self):
        args, seeds = self.args("--max-pages", "2")
        lines = []
        with mock.patch.object(mplus, "api_get", FakeRaiderio()):
            reason, state, guild_queue, ilvl_range = mplus.run(args, seeds, self.quiet_view, info=lines.append)
        self.assertIsNone(reason)
        self.assertEqual(ilvl_range, "250-350")
        rows = mplus.summary_rows(state)
        # 12-es szint: 2 futás, 3 játékos (a 400-as kimarad); 15-ös: 1 futás (az időn túli nem számít).
        self.assertEqual(rows, [(12, 2, 3, 325.2, 325.0, 322.5, 320.0, 330.5), (15, 1, 1, 335.0, 335.0, 335.0, 335.0, 335.0)])
        self.assertEqual(state["c"]["skipped_untimed"], 1)
        self.assertIn("season=season-mn-2", lines[0])
        summary = "\n".join(mplus.summary_lines(state, guild_queue, ilvl_range))
        self.assertIn("(1 player(s) skipped for an item level outside the allowed range (250-350))", summary)

    def test_cached_run_filters(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        cache = mplus.DiskCache(str(Path(folder.name) / "cache.json"), 24)
        self.addCleanup(cache.close)
        now = datetime.now(timezone.utc)

        def put(run_id, level, days_ago, team, timed=True, dungeon="the-stonevault", season="season-mn-2"):
            completed = (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
            roster = [mplus.pack_member(m) for m in team]
            entry = {"level": level, "completed_at": completed, "timed": timed, "roster": roster}
            if dungeon:
                entry["dungeon"] = dungeon
            cache.put(mplus.run_key(season, run_id), entry)

        put(1, 12, 1, [member("Thrall", 320), member("Jaina", 330)])
        put(2, 12, 2, [member("Uther", 325)])
        put(3, 12, 40, [member("Arthas", 300)])  # régi
        put(4, 15, 1, [member("Sylvanas", 335)], timed=False)  # időn túli
        put(5, 15, 1, [us_member("Varian", 331)])  # más régió
        put(6, 15, 1, [member("Anduin", 333)], dungeon=None)  # 4.3 előtti: nem tudja a dungeont
        put(7, 15, 1, [member("Garrosh", 340)], season="season-mn-1")  # előző szezon
        put(8, 18, 1, [member("Illidan", 400)])  # tartományon kívüli itemlevel: nem számít

        def counted(*argv, regions=frozenset({"eu"}), seen=()):
            args, _seeds = self.args(*argv)
            state = mplus.new_state()
            state["seen_runs"].update(seen)
            number = mplus.add_cached_runs(args, "season-mn-2", regions, cache, state)
            self.assertEqual(number, state["c"]["cached_runs"])
            return number, {level: runs for level, runs in state["runs"].items() if runs}, state

        number, runs, state = counted()
        self.assertEqual((number, runs), (4, {12: 3, 15: 1}))
        self.assertEqual(state["c"]["runs_ilvl_range"], 1)  # Illidan csapata
        # A lekérdezés ezeket már nem számolja újra (a beszámoltak csapatait viszont követi).
        self.assertEqual(state["from_cache"], {1: True, 2: True, 3: True, 6: True, 8: False})
        self.assertEqual(counted("--since-days", "30")[1], {12: 2, 15: 1})
        self.assertEqual(counted("--levels", "15")[1], {15: 1})
        self.assertEqual(counted("--include-untimed")[1], {12: 3, 15: 2})
        self.assertEqual(counted("--dungeon", "the-stonevault")[1], {12: 3})
        self.assertEqual(counted("--dungeon", "the-stonevault", "--each-dungeon")[1], {12: 3, 15: 1})  # ott nem szűr
        self.assertEqual(counted(regions=None)[1], {12: 3, 15: 2})  # „world”: minden régió
        self.assertEqual(counted(seen={1})[1], {12: 2, 15: 1})
        # Szintenként legfeljebb egy futás: a legújabb.
        _number, runs, state = counted("--per-level", "1")
        self.assertEqual((runs, state["ilvls"][12]), ({12: 1, 15: 1}, [320.0, 330.0]))

    def test_cached_runs_are_counted_with_the_query(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        fake = FakeRaiderio(affix_runs={"fortified": [3]})  # ezzel az affixszel csak a 3-as futás látszik
        titles = []

        def query(*argv):
            args = mplus.build_parser().parse_args(
                ["--cache", str(Path(folder.name) / "cache.json"), "--delay", "0", "--max-pages", "1", *argv]
            )
            seeds = mplus.prepare_args(args)

            def view(state, guild_queue, title):
                titles.append(title)
                return self.quiet_view(state, guild_queue, title)

            with mock.patch.object(mplus, "api_get", fake):
                _reason, state, guild_queue, ilvl_range = mplus.run(args, seeds, view, info=lambda line: None)
            return state, "\n".join(mplus.summary_lines(state, guild_queue, ilvl_range))

        first, _summary = query()  # mindhárom csapatot letölti (és a gyorsítótárba teszi)
        self.assertEqual(dict(first["runs"]), {12: 2, 15: 1})
        only_reached, _summary = query("--affixes", "fortified")
        self.assertEqual(dict(only_reached["runs"]), {15: 1})  # alapból csak az elért futások számítanak
        downloads = fake.calls.count("mythic-plus/run-details")
        state, summary = query("--affixes", "fortified", "--use-cached-runs")
        self.assertEqual(mplus.summary_rows(state), mplus.summary_rows(first))
        self.assertEqual(state["c"]["cached_runs"], 3)  # a 3-ast a lekérdezés már nem számolja újra
        self.assertEqual(fake.calls.count("mythic-plus/run-details"), downloads)  # semmit sem tölt le újra
        self.assertIn("Counted straight from the cache (--use-cached-runs): 3 run(s)", summary)
        self.assertTrue(titles[-1].endswith(" | + cached runs"))
        self.assertNotIn("cached runs", titles[0])

    def test_cached_runs_keep_the_guild_crawl_going(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        fake = FakeGuildRaiderio()

        def crawl(*argv):
            args = mplus.build_parser().parse_args(
                ["--cache", str(Path(folder.name) / "cache.json"), "--delay", "0", "--max-pages", "1", *argv]
            )
            seeds = mplus.prepare_args(args)
            with mock.patch.object(mplus, "api_get", fake):
                reason, state, _queue, _range = mplus.run(args, seeds, self.quiet_view, info=lambda line: None)
            return reason, state

        reason, first = crawl("--guild", "Solutions@Ragnaros")  # a csapatokon át mindhárom guildet bejárja
        self.assertEqual((first["c"]["guilds_done"], dict(first["runs"])), (3, {12: 2, 14: 1}))
        calls = len(fake.calls)
        # A gyorsítótárból előre beszámolt futások csapatain át is továbbjut (és nem számolja őket újra).
        reason, state = crawl("--guild", "Solutions@Ragnaros", "--use-cached-runs")
        self.assertEqual((state["c"]["guilds_done"], dict(state["runs"])), (3, {12: 2, 14: 1}))
        self.assertEqual(state["c"]["cached_runs"], 3)
        self.assertEqual(len(fake.calls), calls)  # mindent a gyorsítótárból vett
        self.assertEqual(reason, "the guild queue is empty - nothing left to crawl")
        # Ugyanígy, ha a ranglistáról indul, és a csapattagok guildjeit követi.
        reason, state = crawl("--follow-guilds", "--use-cached-runs")
        self.assertEqual((state["c"]["guilds_done"], dict(state["runs"])), (3, {12: 2, 14: 1}))
        self.assertEqual(reason, "the guild queue is empty - nothing left to crawl")

    def test_stop_ends_the_collection_with_what_it_has(self):
        def stop_at_second_team(run_id):
            if run_id == 2:
                mplus.STOP.set()  # a második csapat letöltése közben leállítják

        args, seeds = self.args()
        with mock.patch.object(mplus, "api_get", FakeRaiderio(on_details=stop_at_second_team)):
            reason, state, _queue, _range = mplus.run(args, seeds, self.quiet_view, info=lambda line: None)
        self.assertEqual(reason, "stopped - summarizing what was collected so far")
        self.assertEqual(dict(state["runs"]), {12: 1})  # az első csapat megmaradt

    def test_stop_before_the_collection(self):
        mplus.STOP.set()
        args, seeds = self.args()
        with mock.patch.object(mplus.SESSION, "get") as get:
            with self.assertRaises(mplus.Stopped):
                mplus.run(args, seeds, self.quiet_view, info=lambda line: None)
        get.assert_not_called()

    def test_pause_is_cut_short_by_stop(self):
        mplus.pause(0)  # nincs leállítás: nem dob
        started = time.monotonic()
        mplus.STOP.set()
        with self.assertRaises(mplus.Stopped):
            mplus.pause(30)
        self.assertLess(time.monotonic() - started, 5)

    def test_season_lookup_failure(self):
        args, seeds = self.args()
        with mock.patch.object(mplus, "api_get", side_effect=RuntimeError("HTTP 503")):
            with self.assertRaisesRegex(mplus.StatsError, "Raider.IO request failed: HTTP 503"):
                mplus.run(args, seeds, self.quiet_view, info=lambda line: None)

    def test_option_checks(self):
        for argv, message in (
            (["--levels", "18,x"], "--levels must be comma-separated"),
            (["--min-ilvl", "300", "--max-ilvl", "200"], "--min-ilvl can't be higher"),
            (["--guild", "Solutions"], "must look like Name@realm"),
        ):
            with self.subTest(argv=argv):
                args = mplus.build_parser().parse_args(argv)
                with self.assertRaisesRegex(ValueError, message):
                    mplus.prepare_args(args)
        args = mplus.build_parser().parse_args(["--guild", "Solutions@ragnaros"])
        self.assertEqual(mplus.prepare_args(args), [("eu", "ragnaros", "Solutions")])
        self.assertTrue(args.follow_guilds)  # guildeknél alapból követi a csapattagok guildjeit


# --------------------------------------------------------------------------- Warcraft Logs (raid)

ZONE = {
    "id": 50,
    "name": "Teszt Raid",
    "frozen": False,
    "difficulties": [{"id": 1}, {"id": 3}, {"id": 4}, {"id": 5}],
    "encounters": [
        {"id": 1, "name": "Első Boss"},
        {"id": 2, "name": "Második Boss"},
        {"id": 3, "name": "Harmadik Boss"},
        {"id": 4, "name": "Negyedik Boss"},
        {"id": 9, "name": "Nymrissa Wavecaller"},
    ],
}


def fight(fight_id, encounter, difficulty, ilvl, start):
    return {
        "id": fight_id,
        "encounterID": encounter,
        "difficulty": difficulty,
        "kill": True,
        "size": 20,
        "startTime": start,
        "endTime": start + 300_000,
        "averageItemLevel": ilvl,
    }


class FakeWCL:
    """A Warcraft Logs API helyett (a WCLClient pótlása)."""

    instances = []
    stop_after_reports = False

    def __init__(self, client_id, client_secret):
        self.calls = 0
        self.rate = None
        self.report_limit_cap = None
        FakeWCL.instances.append(self)

    def query(self, query, variables=None):
        if wcl.STOP.is_set():
            raise wcl.Stopped()
        self.calls += 1
        if "worldData" in query:
            return {"worldData": {"expansions": [{"id": 11, "name": "Midnight", "zones": [ZONE]}]}}
        if "reports(" in query:
            if variables["limit"] == 50 and variables["endTime"] - variables["startTime"] == 3 * wcl.HOUR_MS:
                return {"reportData": {"reports": {"data": [], "has_more_pages": False}}}  # időszűrés-teszt
            if FakeWCL.stop_after_reports:
                wcl.STOP.set()
            now = wcl.now_ms()
            report = {
                "code": "abc123",
                "startTime": now - wcl.DAY_MS,
                "endTime": now - wcl.DAY_MS + 3 * wcl.HOUR_MS,
                "guild": {"id": 7, "server": {"region": {"slug": "eu"}}},
                "fights": [
                    fight(1, 1, 4, 330.4, 1_000),
                    fight(2, 2, 4, 332.0, 2_000_000),
                    fight(3, 1, 5, 340.0, 4_000_000),
                    fight(4, 9, 4, 320.0, 6_000_000),  # kihagyott (Lair) boss
                    fight(5, 1, 1, 300.0, 8_000_000),  # LFR: kimarad
                ],
            }
            return {"reportData": {"reports": {"data": [report], "has_more_pages": False}}}
        raise AssertionError(query)

    def usage(self):
        return "API pont: ?"


class RaidStatsTests(unittest.TestCase):
    def setUp(self):
        wcl.STOP.clear()
        FakeWCL.instances = []
        FakeWCL.stop_after_reports = False
        self.lines = []
        wcl.OUTPUT = self.lines.append
        patcher = mock.patch.object(wcl, "WCLClient", FakeWCL)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        wcl.OUTPUT = None
        wcl.STOP.clear()

    def run_stats(self, *argv):
        args = wcl.parse_args(["--client-id", "id", "--client-secret", "titok", "--days", "2", "--pages", "4", *argv])
        cache = wcl.Cache(None)
        try:
            return wcl.run(args, cache)
        finally:
            cache.close()

    def test_tables_per_difficulty_and_boss(self):
        result = self.run_stats()
        self.assertEqual(result["zone"]["name"], "Teszt Raid")
        self.assertEqual((result["kills"], result["per_difficulty"]), (3, {4: 2, 5: 1}))
        (metric, tables), = result["sections"]
        self.assertEqual(metric, "raid átlag / kill")
        heroic = {name: (counts, stats) for name, counts, stats in tables[4]}
        self.assertEqual(list(heroic), ["Első Boss", "Második Boss", "Harmadik Boss", "Negyedik Boss", "Összes boss"])
        self.assertEqual(heroic["Első Boss"][0], (1,))
        self.assertEqual(heroic["Összes boss"][1]["mean"], 331.2)
        self.assertIsNone(heroic["Harmadik Boss"][1])  # nincs kill
        self.assertNotIn("Nymrissa Wavecaller", heroic)
        output = "\n".join(self.lines)
        self.assertIn("Zóna: Teszt Raid (id 50), 4 boss", output)
        self.assertIn("=== Heroic - raid átlag item level kill-enként ===", output)

    def test_csv_for_excel(self):
        result = self.run_stats()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "raid.csv"
            wcl.write_csv(str(path), result["sections"])
            text = path.read_text(encoding="utf-8-sig")
        self.assertIn("Heroic;raid átlag / kill;Első Boss;1;;330,4;330,4;330,4;330,4;330,4", text)

    def test_stop_keeps_what_was_downloaded(self):
        FakeWCL.stop_after_reports = True  # az első report-oldal után leállítják
        result = self.run_stats()
        self.assertEqual(result["kills"], 3)
        self.assertIn("Megszakítva - az eddig letöltött reportokkal számolok tovább", "\n".join(self.lines))

    def test_missing_keys_and_unknown_zone(self):
        args = wcl.parse_args(["--days", "2"])
        args.client_id = args.client_secret = None
        with self.assertRaisesRegex(wcl.StatsError, "Hiányzik az API kulcs"):
            wcl.run(args, wcl.Cache(None))
        with self.assertRaisesRegex(wcl.StatsError, 'Nincs "Nincs ilyen" nevű zóna'):
            self.run_stats("--zone", "Nincs ilyen")

    def test_rate_limit_wait_is_cut_short_by_stop(self):
        client = REAL_WCL_CLIENT.__new__(REAL_WCL_CLIENT)
        client.rate = {"limitPerHour": 3600, "pointsSpentThisHour": 3599, "pointsResetIn": 1800}
        client.rate_time = time.time()
        client.last_cost = 10
        wcl.STOP.set()
        started = time.monotonic()
        with self.assertRaises(wcl.Stopped):
            client._wait_for_budget()
        self.assertLess(time.monotonic() - started, 5)


# --------------------------------------------------------------------------- az ablakok mezői


@unittest.skipIf(stats_windows is None, "a tkinter nincs telepítve")
class StatsFieldTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(stats_windows.parse_levels_text("2-5, 10;12"), "2,3,4,5,10,12")
        self.assertIsNone(stats_windows.parse_levels_text("  "))
        for text in ("x", "5-2", "0", "2-"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                stats_windows.parse_levels_text(text)

    def test_numbers(self):
        self.assertEqual(stats_windows.parse_number(" 7 ", "Napok"), 7)
        self.assertEqual(stats_windows.parse_number("2,5", "Napok", float), 2.5)
        self.assertEqual(stats_windows.parse_number("", "Napok", empty=0), 0)
        for text, maximum, message in (
            ("x", None, "Napok: egész számot adj meg."),
            ("-1", None, "Napok: legalább 0 lehet."),
            ("101", 100, "Napok: 0 és 100 közötti szám lehet."),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                stats_windows.parse_number(text, "Napok", maximum=maximum)
        with self.assertRaisesRegex(ValueError, "számot adj meg"):
            stats_windows.parse_number("nan", "Itemlevel", float)

    def test_guilds(self):
        self.assertEqual(
            stats_windows.parse_guilds(" Solutions@Ragnaros ; Echo@Tarren Mill@EU, ", "eu"),
            ["Solutions@Ragnaros", "Echo@Tarren Mill@EU"],
        )
        for text, message in (("", "legalább egy guildet"), ("Solutions", "Név@realm"), ("A@b@xx", "Név@realm")):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                stats_windows.parse_guilds(text, "eu")
        with self.assertRaisesRegex(ValueError, "konkrét régiót"):
            stats_windows.parse_guilds("Solutions@Ragnaros", "world")

    def test_api_keys_file(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            self.assertEqual(stats_windows.load_api_keys(folder), {})
            stats_windows.save_api_keys(folder, {"wcl_client_id": "id", "wcl_client_secret": "titok"})
            stats_windows.save_api_keys(folder, {"raiderio_api_key": "rio"})
            self.assertEqual(
                stats_windows.load_api_keys(folder),
                {"wcl_client_id": "id", "wcl_client_secret": "titok", "raiderio_api_key": "rio"},
            )
            stats_windows.save_api_keys(folder, {"wcl_client_id": "", "wcl_client_secret": "", "raiderio_api_key": ""})
            self.assertFalse((folder / stats_windows.KEYS_FILE_NAME).exists())  # üresen törlődik
            (folder / stats_windows.KEYS_FILE_NAME).write_text("nem json", encoding="utf-8")
            self.assertEqual(stats_windows.load_api_keys(folder), {})

    def test_format(self):
        self.assertEqual((stats_windows.format_stat(329.44), stats_windows.format_stat(None)), ("329,4", "–"))


if __name__ == "__main__":
    unittest.main()
