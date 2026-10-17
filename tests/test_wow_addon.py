"""A WoWLeveling addon mentéseinek beolvasása, megkeresése és importálása (wow_addon.py), valamint
maga az addon (addon/WoWLeveling), ha van Lua-értelmező a gépen."""

import random
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import wow_addon
from leveling import (
    MODES,
    Character,
    LevelingData,
    Settings,
    SpecScores,
    build_plan,
    lookahead_day,
    plan_item_levels,
    plan_raiderio_scores,
)
from wow_addon import AddonError, LuaSyntaxError, Snapshot, parse_lua
from wow_data import WOW_SPECS

D = Decimal
TESTS = Path(__file__).resolve().parent
LUA = next((shutil.which(name) for name in ("lua5.1", "luajit", "lua") if shutil.which(name)), None)

# Egy mentés, ahogy a játék kiírja (tabulátorok, ["kulcs"] = érték, a tömbelemek mellett -- [n]).
SAVED = """
WoWLevelingDB = {
\t["characters"] = {
\t\t["Thrall-Draenor"] = {
\t\t\t["name"] = "Thrall",
\t\t\t["realm"] = "Draenor",
\t\t\t["region"] = "eu",
\t\t\t["race"] = "Orc",
\t\t\t["raceFile"] = "Orc",
\t\t\t["class"] = "Shaman",
\t\t\t["classFile"] = "SHAMAN",
\t\t\t["specID"] = 263,
\t\t\t["spec"] = "Enhancement",
\t\t\t["level"] = 85,
\t\t\t["xp"] = 2999,
\t\t\t["xpMax"] = 10000,
\t\t\t["itemLevel"] = 301.5625,
\t\t\t["mythicPlusScore"] = 1234.56,
\t\t\t["updated"] = 1760700000,
\t\t},
\t\t["Jaina-Twisting Nether"] = {
\t\t\t["name"] = "Jaina",
\t\t\t["realm"] = "Twisting Nether",
\t\t\t["classFile"] = "MAGE",
\t\t\t["class"] = "Magier",
\t\t\t["specID"] = 64,
\t\t\t["level"] = 90,
\t\t\t["xp"] = 0,
\t\t\t["xpMax"] = 0,
\t\t\t["mythicPlusScore"] = 0,
\t\t\t["updated"] = 1760600000,
\t\t},
\t},
\t["version"] = 1,
}
"""


def snapshot(name="Thrall", realm="Draenor", level="85.29", updated=1760700000, **fields):
    values = dict(
        name=name,
        realm=realm,
        region="eu",
        race="",
        char_class="",
        spec="",
        level=None if level is None else D(level),
        item_level=None,
        score=None,
        updated=updated,
    )
    values.update(fields)
    return Snapshot(**values)


def entry(**fields):
    """Egy karakter bejegyzése a WoWLevelingDB táblában."""
    return {"name": "Thrall", "realm": "Draenor", **fields}


class LuaTests(unittest.TestCase):
    def test_saved_variables_file(self):
        values = parse_lua(SAVED)
        db = values["WoWLevelingDB"]
        self.assertEqual(db["version"], 1)
        thrall = db["characters"]["Thrall-Draenor"]
        self.assertEqual((thrall["xp"], thrall["itemLevel"], thrall["classFile"]), (2999, 301.5625, "SHAMAN"))
        self.assertIsInstance(thrall["xp"], int)

    def test_lua_syntax(self):
        text = r"""
        -- megjegyzés
        A = { 10, -2.5, 1e3, 0x1F, .5, true, false, nil, "x"; [==[hosszú]] szöveg]==], -- [10]
              key = 'egy \'idézet\'', ["kulcs szóközzel"] = { }, [7] = "hét", [2.0] = "kettő" }
        --[[ hosszú
             megjegyzés ]] B = "a\"b\\c\nd\065\x42\z
                                 C" ; C = nil
        D = [[
első sor
második]]
        E = "Zôltan" F = - 7
        """
        values = parse_lua(text)
        self.assertEqual(
            values["A"],
            {
                1: 10,
                2: "kettő",  # a [2.0] kulcs ugyanaz, mint a 2
                3: 1000.0,
                4: 31,
                5: 0.5,
                6: True,
                7: "hét",
                9: "x",
                10: "hosszú]] szöveg",
                "key": "egy 'idézet'",
                "kulcs szóközzel": {},
            },
        )
        self.assertEqual(values["B"], 'a"b\\c\ndABC')
        self.assertNotIn("C", values)  # a nil értékű változó nem létezik
        self.assertEqual((values["D"], values["E"], values["F"]), ("első sor\nmásodik", "Zôltan", -7))

    def test_escapes_build_utf8_text(self):
        values = parse_lua('A = "Z\\195\\180ltan" B = "\\\n" C = \'\\x41\\z   B\'')
        self.assertEqual((values["A"], values["B"], values["C"]), ("Zôltan", "\n", "AB"))

    def test_errors_tell_the_line(self):
        cases = (
            ('A = "lezáratlan', "lezáratlan szöveg"),
            ("A = {\n1,\n2", "lezáratlan tábla"),
            ("A = {1 2}", "„,” vagy „}” hiányzik"),
            ('A = "\\q"', "ismeretlen \\\\ jel"),
            ("A = valami", "ismeretlen érték"),
            ("A = 1.#INF", "„,” vagy „}” hiányzik|változónév hiányzik"),
            ("= 1", "változónév hiányzik"),
            ("A = {[nil] = 1}", "hibás táblakulcs"),
            ("A = [[nincs vége", "lezáratlan"),
        )
        for text, message in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(LuaSyntaxError, message):
                    parse_lua(text)
        with self.assertRaisesRegex(LuaSyntaxError, r"\(3\. sor\)"):
            parse_lua("A = {\n1,\n2 3}")
        with self.assertRaisesRegex(LuaSyntaxError, "túl mélyen"):
            parse_lua("A = " + "{" * 5000 + "}" * 5000)


class SnapshotTests(unittest.TestCase):
    def snapshots(self, *entries):
        return wow_addon.snapshots_from_db({"characters": {str(index): item for index, item in enumerate(entries)}})

    def test_saved_file_gives_the_programs_names_and_values(self):
        found = {s.name: s for s in wow_addon.snapshots_from_db(parse_lua(SAVED)["WoWLevelingDB"])}
        thrall, jaina = found["Thrall"], found["Jaina"]
        expected = ("Thrall", "Draenor", "eu", "Orc", "Shaman", "Enhancement", D("85.29"), D("301.56"), D("1234.6"))
        self.assertEqual(thrall, Snapshot(*expected, updated=1760700000))
        # A német „Magier” helyett is Mage; a 0 pontszám nem pontszám; a maximális szinten nincs tapasztalat.
        self.assertEqual(
            (jaina.char_class, jaina.spec, jaina.race, jaina.level, jaina.score, jaina.region),
            ("Mage", "Frost", "", D("90.00"), None, ""),
        )
        self.assertEqual((thrall.key, jaina.key), ("draenor/thrall", "twistingnether/jaina"))

    def test_level_includes_the_experience(self):
        cases = (
            ({"level": 85, "xp": 2999, "xpMax": 10000}, D("85.29")),  # lefelé kerekít
            ({"level": 85, "xp": 29, "xpMax": 100}, D("85.29")),
            ({"level": 85, "xp": 9999, "xpMax": 10000}, D("85.99")),
            ({"level": 85, "xp": 12000, "xpMax": 10000}, D("85.99")),  # sosem éri el a következő szintet
            ({"level": 12}, D("12.00")),
            ({"level": 0}, None),
            ({"level": "85"}, None),
            ({"level": 85, "xp": True, "xpMax": 10}, D("85.00")),
        )
        for fields, level in cases:
            with self.subTest(fields=fields):
                self.assertEqual(self.snapshots(entry(**fields))[0].level, level)

    def test_classes_races_and_specs(self):
        cases = (
            ({"classFile": "DEATHKNIGHT", "class": "Todesritter", "specID": 250}, ("Death Knight", "Blood")),
            ({"classFile": "DEMONHUNTER", "specID": 1480}, ("Demon Hunter", "Devourer")),
            ({"classFile": "SHAMAN", "specID": 1444, "spec": "Initial"}, ("Shaman", "")),  # kezdő spec
            ({"classFile": "SHAMAN", "specID": 62, "spec": "Enhancement"}, ("Shaman", "Enhancement")),  # rossz ID
            ({"classFile": "SHAMAN", "spec": "Verstärkung"}, ("Shaman", "")),  # ismeretlen név
            ({"class": "Necromancer", "spec": "Bone"}, ("Necromancer", "")),
            ({}, ("", "")),
        )
        for fields, expected in cases:
            with self.subTest(fields=fields):
                found = self.snapshots(entry(**fields))[0]
                self.assertEqual((found.char_class, found.spec), expected)
        races = (
            ({"raceFile": "Scourge", "race": "Untoter"}, "Undead"),
            ({"raceFile": "EarthenDwarf"}, "Earthen"),
            ({"raceFile": "HighmountainTauren"}, "Highmountain Tauren"),
            ({"raceFile": "MagharOrc"}, "Mag'har Orc"),
            ({"raceFile": "Haranir"}, "Haranir"),
            ({"raceFile": "Ogre", "race": "Ogre"}, "Ogre"),  # ismeretlen: a játékbeli név
            ({"race": "Night Elf"}, "Night Elf"),
        )
        for fields, race in races:
            with self.subTest(fields=fields):
                self.assertEqual(self.snapshots(entry(**fields))[0].race, race)

    def test_incomplete_entries_are_left_out(self):
        found = self.snapshots(
            entry(itemLevel=-1, mythicPlusScore=100000, updated=-5),
            {"name": "Jaina"},
            {"realm": "Draenor"},
            {"name": " ", "realm": "Draenor"},
        )
        self.assertEqual([(s.name, s.item_level, s.score, s.updated) for s in found], [("Thrall", None, None, 0)])
        self.assertEqual(wow_addon.snapshots_from_db({"characters": {"x": "szöveg", "y": 5}}), [])
        self.assertEqual(wow_addon.snapshots_from_db(None), [])

    def test_item_level_and_score_rounding(self):
        found = self.snapshots(entry(itemLevel=301.565, mythicPlusScore=2543.75))[0]
        self.assertEqual((found.item_level, found.score), (D("301.57"), D("2543.8")))
        self.assertEqual(found.describe(), "Thrall (Draenor) – itemlevel 301,57")
        full = snapshot(race="Orc", char_class="Shaman", spec="Enhancement", item_level=D("301.56"))
        described = "Thrall (Draenor) – szint: 85,29, Orc Shaman, Enhancement, itemlevel 301,56"
        self.assertEqual(full.describe(), described)


class FilesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "World of Warcraft"
        self.game = self.root / "_retail_"
        (self.game / "Interface" / "AddOns").mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def save(self, account, text=SAVED):
        folder = self.game / "WTF" / "Account" / account / "SavedVariables"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "WoWLeveling.lua"
        path.write_text(text, encoding="utf-8")
        return path

    def test_saved_variables_are_found_from_any_folder_of_the_game(self):
        first, second = self.save("111#1"), self.save("222#2")
        (self.game / "WTF" / "Account" / "333#1" / "SavedVariables").mkdir(parents=True)  # ebben nincs mentés
        account = first.parent.parent
        places = (
            self.root,
            self.game,
            self.game / "WTF",
            self.game / "WTF" / "Account",
            self.game / "Interface" / "AddOns",
        )
        for place in places:
            with self.subTest(place=place):
                self.assertEqual(wow_addon.find_saved_variables(place), [first, second])
        self.assertEqual(wow_addon.find_saved_variables(account), [first])
        self.assertEqual(wow_addon.find_saved_variables(first.parent), [first])
        self.assertEqual(wow_addon.find_saved_variables(str(second)), [second])
        with self.assertRaisesRegex(AddonError, "Nem létezik"):
            wow_addon.find_saved_variables(self.root / "nincs")
        empty = Path(self.temp_dir.name) / "üres"
        empty.mkdir()
        with self.assertRaisesRegex(AddonError, "Még nincs mentett adat"):
            wow_addon.find_saved_variables(empty)

    def test_game_folder(self):
        path = self.save("111#1")
        for place in (self.root, self.game, path, path.parent, self.game / "Interface" / "AddOns"):
            with self.subTest(place=place):
                self.assertEqual(wow_addon.game_folder(place), self.game)
        other = Path(self.temp_dir.name) / "máshol"
        other.mkdir()
        self.assertIsNone(wow_addon.game_folder(other))

    def test_accounts_are_merged_and_problems_reported(self):
        self.save("111#1")
        newer = SAVED.replace("1760700000", "1760800000").replace('["level"] = 85', '["level"] = 86')
        newer = newer.replace('\t["version"] = 1,', '\t["lastError"] = "hiba a játékban",\n\t["version"] = 1,')
        self.save("222#2", newer)
        broken = self.save("333#3", "WoWLevelingDB = {")
        data = wow_addon.load_addon_data(self.root)
        self.assertEqual(len(data.files), 3)
        self.assertEqual(
            [(s.name, s.level, s.updated) for s in data.snapshots],
            [("Jaina", D("90.00"), 1760600000), ("Thrall", D("86.29"), 1760800000)],  # Thrallnál a későbbi mentés
        )
        self.assertEqual(len(data.problems), 2)
        self.assertIn(f"{broken} nem az addon mentése, vagy sérült (lezáratlan tábla", data.problems[1])
        self.assertEqual(data.problems[0], "az addon hibát jelzett: hiba a játékban")
        self.assertEqual(data.saved_at.timestamp(), 1760800000)
        with self.assertRaisesRegex(AddonError, "nem olvashatók be: .*sérült"):
            wow_addon.load_addon_data(broken)
        empty = wow_addon.load_addon_data(self.save("444#4", "\nWoWLevelingDB = nil\n"))
        self.assertEqual((empty.snapshots, empty.problems, empty.saved_at), ([], [], None))

    def test_addon_is_installed_into_the_game(self):
        self.assertIsNone(wow_addon.installed_addon(self.root))
        target = wow_addon.install_addon(self.game)
        self.assertEqual(target, self.game / "Interface" / "AddOns" / "WoWLeveling")
        self.assertEqual(
            sorted(path.name for path in target.iterdir()),
            ["Plan.lua", "PlanData.lua", "WoWLeveling.lua", "WoWLeveling.toc"],
        )
        for place in (self.root, self.game, target):
            with self.subTest(place=place):
                self.assertEqual(wow_addon.installed_addon(place), target)
        (target / "WoWLeveling.lua").write_text("-- régi változat", encoding="utf-8")
        wow_addon.install_addon(self.game)  # frissítés
        source = wow_addon.ADDON_SOURCE / "WoWLeveling.lua"
        self.assertEqual((target / "WoWLeveling.lua").read_bytes(), source.read_bytes())

    def test_toc_file(self):
        toc = (wow_addon.ADDON_SOURCE / "WoWLeveling.toc").read_text(encoding="utf-8")
        directives = dict(re.findall(r"^## (\w+): (.*)$", toc, re.MULTILINE))
        self.assertEqual(directives["SavedVariables"], wow_addon.DB_VARIABLE)
        versions = [int(version) for version in directives["Interface"].split(",")]
        self.assertIn(120105, versions)  # 12.1.5 (2026. október)
        files = [line for line in toc.splitlines() if line.strip() and not line.startswith("#")]
        self.assertEqual(files, ["PlanData.lua", "Plan.lua", "WoWLeveling.lua"])  # előbb az adatok
        self.assertRegex(directives["Version"], r"^\d+\.\d+\.\d+$")
        # A program nélkül telepítve még nincs terv (a program ezt írja felül).
        placeholder = (wow_addon.ADDON_SOURCE / wow_addon.PLAN_FILE).read_text(encoding="utf-8")
        self.assertEqual(parse_lua(placeholder), {})

    def test_plan_is_written_into_the_installed_addon(self):
        target = wow_addon.install_addon(self.game)
        settings = Settings(date(2026, 10, 1), date(2026, 10, 10), date(2026, 10, 20), target_item_level=D("330.5"))
        thrall = Character(
            "Thrall", "death knight", "Frost", D("83.29"), realm="Twisting Nether", item_level=D("301.56"),
            raiderio_score=D("1234.6"),
        )
        data = LevelingData(settings, [thrall, Character("Jaina")], SpecScores({"death knight/frost": D("3700.5")}))
        data.addon_imported = {"twistingnether/thrall": 1760700000}
        payload = wow_addon.plan_payload(data, datetime(2026, 10, 17, 12, 30))
        self.assertEqual(
            {key: value for key, value in payload.items() if key != "characters"},
            {
                "version": 1,
                "generated": int(datetime(2026, 10, 17, 12, 30).timestamp()),
                "lookAhead": True,
                "specScores": True,
                "startLevel": 100,
                "targetLevel": 9000,
                "targetItemLevel": 33050,
            },
        )
        self.assertEqual(
            payload["characters"][0],
            {
                "name": "Thrall",
                "realm": "Twisting Nether",
                "class": "DEATHKNIGHT",
                "level": 8329,
                "itemLevel": 30156,
                "score": 123460,
                "start": "2026-10-01",
                "deadline": "2026-10-10",
                "specKey": "death knight/frost",
                "specScore": 370050,
                "addonUpdated": 1760700000,  # ennél újabb mentése az addonban frissebb a program adatánál
            },
        )
        jaina = payload["characters"][1]
        self.assertEqual((jaina["class"], jaina["itemLevel"], jaina["deadline"]), (None, None, "2026-10-20"))
        path = wow_addon.write_plan(target, payload)
        self.assertEqual(path, target / "PlanData.lua")
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("-- A WoW szintezés tervező írta (2026-10-17 12:30)"))
        written = parse_lua(text)[wow_addon.PLAN_VARIABLE]
        self.assertEqual(written["characters"][1]["name"], "Thrall")  # a Lua-tömb 1-től számozott
        self.assertEqual(written["characters"][2], {k: v for k, v in payload["characters"][1].items() if v is not None})
        self.assertEqual(sorted(p.name for p in target.iterdir())[:2], ["Plan.lua", "PlanData.lua"])  # nincs .tmp

        # Egy régebbi addont előbb frissít (különben nem olvasná be a tervet).
        (target / "WoWLeveling.toc").write_text("## Version: 1.0.0\n\nWoWLeveling.lua\n", encoding="utf-8")
        (target / "Plan.lua").unlink()
        wow_addon.write_plan(target, payload)
        self.assertEqual(wow_addon.addon_version(target), wow_addon.addon_version(wow_addon.ADDON_SOURCE))
        self.assertTrue((target / "Plan.lua").is_file())
        rewritten = parse_lua((target / "PlanData.lua").read_text(encoding="utf-8"))
        self.assertEqual(rewritten[wow_addon.PLAN_VARIABLE], written)

    def test_lua_strings_are_escaped(self):
        text = 'A "b" \\ c\nd\te\x01 Zôltan'
        self.assertEqual(parse_lua(f"X = {wow_addon.lua_value({'s': text, 'list': [1, True, False]})}")["X"], {
            "s": text, "list": {1: 1, 2: True, 3: False},
        })
        with self.assertRaises(TypeError):
            wow_addon.lua_value(1.5)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.data = LevelingData(Settings.default())

    def plan(self, *snapshots, imported=None, skipped=()):
        return wow_addon.plan_import(self.data.characters, list(snapshots), imported or {}, list(skipped))

    def test_matching_characters_are_updated(self):
        thrall = Character("thrall", realm="draenor", level=D("84.10"), item_level=D("290"), raiderio_score=D("900"))
        zoltan = Character("Zoltan", realm="TwistingNether", char_class="Shaman", spec="Elemental")
        jaina = Character("Jaina")  # realm nélkül: név szerint
        self.data.characters = [thrall, zoltan, jaina]
        plan = self.plan(
            snapshot(item_level=D("301.56"), score=D("1234.6"), race="Orc", char_class="Shaman", spec="Enhancement"),
            snapshot("Zôltan", "Twisting Nether", "70.00", char_class="Shaman", spec="Enhancement", race="Orc"),
            snapshot("Jaina", "Kazzak", "90.00", char_class="Mage", spec="Frost", score=None),
        )
        self.assertEqual(
            [change.describe() for change in plan.changes],
            [
                "thrall: név thrall → Thrall",
                "thrall: szint 84,10 → 85,29",
                "thrall: itemlevel 290,00 → 301,56",
                "thrall: Raider.io 900,0 → 1234,6",
                "thrall: faj – → Orc",
                "thrall: kaszt – → Shaman",
                "thrall: spec – → Enhancement",
                "Zoltan: név Zoltan → Zôltan",  # a játékbeli írásmód
                "Zoltan: szint 1,00 → 70,00",
                "Zoltan: faj – → Orc",  # a beírt spec marad
                "Jaina: realm – → Kazzak",
                "Jaina: szint 1,00 → 90,00",
                "Jaina: kaszt – → Mage",
                "Jaina: spec – → Frost",
            ],
        )
        self.assertEqual((plan.matched, plan.updated_count(), plan.new), (3, 3, []))
        plan.apply(self.data)
        self.assertEqual(
            (thrall.name, thrall.level, zoltan.name, jaina.realm), ("Thrall", D("85.29"), "Zôltan", "Kazzak")
        )
        self.assertEqual(
            self.data.addon_imported,
            {"draenor/thrall": 1760700000, "twistingnether/zoltan": 1760700000, "kazzak/jaina": 1760700000},
        )

    def test_spec_only_for_the_same_class(self):
        priest = Character("Thrall", realm="Draenor", char_class="priest")
        self.data.characters = [priest]
        plan = self.plan(snapshot(char_class="Shaman", spec="Enhancement", race="Orc"))
        self.assertEqual([change.attribute for change in plan.changes], ["level", "race"])
        priest.char_class = "Shaman"
        plan = self.plan(snapshot(char_class="Shaman", spec="Enhancement"))
        self.assertEqual([change.new for change in plan.changes], [D("85.29"), "Enhancement"])

    def test_only_newer_saves_are_used(self):
        thrall = Character("Thrall", realm="Draenor", level=D("85.50"))  # kézzel átírva
        self.data.characters = [thrall]
        plan = self.plan(snapshot(), imported={"draenor/thrall": 1760700000})
        self.assertEqual((plan.changes, plan.imported, plan.matched), ([], {}, 1))
        plan = self.plan(snapshot(updated=1760700001), imported={"draenor/thrall": 1760700000})
        self.assertEqual([change.new for change in plan.changes], [D("85.29")])
        self.assertEqual(plan.imported, {"draenor/thrall": 1760700001})

    def test_missing_values_do_not_clear_the_data(self):
        thrall = Character("Thrall", realm="Draenor", level=D("80"), item_level=D("290"), raiderio_score=D("900"))
        self.data.characters = [thrall]
        plan = self.plan(snapshot(level=None))
        self.assertEqual(plan.changes, [])
        self.assertEqual(plan.imported, {"draenor/thrall": 1760700000})

    def test_unknown_characters_are_offered(self):
        self.data.characters = [Character("Thrall", realm="Draenor"), Character("Jaina"), Character("Jaina")]
        sylvanas = snapshot("Sylvanas", level="90.00")
        arthas = snapshot("Arthas", level="80.00")
        anduin = snapshot("Anduin", level="90.00")
        # Két Jaina is van a listán realm nélkül, és két realmen is van Varian: egyik sem egyértelmű.
        jaina = snapshot("Jaina", "Kazzak")
        varians = (snapshot("Varian", "Kazzak"), snapshot("Varian", "Draenor"))
        self.data.characters.append(Character("Varian"))
        plan = self.plan(sylvanas, arthas, jaina, anduin, *varians, skipped=["draenor/arthas"])
        self.assertEqual(plan.new, [anduin, sylvanas, jaina, *varians])  # a magasabb szintűek elöl
        self.assertEqual(plan.skipped, [arthas])
        self.assertEqual((plan.matched, plan.changes), (0, []))

    def test_duplicates_on_the_list_are_all_updated(self):
        first, second = Character("Thrall", realm="Draenor"), Character("Thrall", realm="Draenor")
        self.data.characters = [first, second]
        plan = self.plan(snapshot())
        self.assertEqual([change.character for change in plan.changes], [first, second])
        self.assertEqual(plan.updated_count(), 2)

    def test_new_characters_are_added_or_skipped(self):
        self.data.addon_skipped = ["kazzak/jaina"]
        thrall = snapshot(
            race="Orc", char_class="Shaman", spec="Enhancement", item_level=D("301.56"), score=D("1234.6")
        )
        anduin = snapshot("Anduin", level=None, updated=1760700100)
        jaina = snapshot("Jaina", "Kazzak")
        added = wow_addon.add_new_characters(self.data, [thrall, anduin, jaina], [thrall, anduin])
        self.assertEqual(added, self.data.characters)
        self.assertEqual(
            [(c.name, c.realm, c.race, c.char_class, c.spec, c.level, c.item_level, c.raiderio_score) for c in added],
            [
                ("Thrall", "Draenor", "Orc", "Shaman", "Enhancement", D("85.29"), D("301.56"), D("1234.6")),
                ("Anduin", "Draenor", "", "", "", D("1.00"), None, None),  # szint nélkül a kezdőszint
            ],
        )
        self.assertEqual(self.data.addon_imported, {"draenor/thrall": 1760700000, "draenor/anduin": 1760700100})
        wow_addon.add_new_characters(self.data, [snapshot("Varian")], [])
        self.assertEqual(self.data.addon_skipped, ["kazzak/jaina", "draenor/varian"])
        # A kihagyott, de később kézzel felvett karakter adatai frissülnek, és lekerül a kihagyottak közül.
        self.data.characters.append(Character("Varian", realm="Draenor"))
        plan = wow_addon.plan_import(
            self.data.characters, [snapshot("Varian")], self.data.addon_imported, self.data.addon_skipped
        )
        self.assertEqual((plan.unskip, [change.attribute for change in plan.changes]), (["draenor/varian"], ["level"]))
        plan.apply(self.data)
        self.assertEqual(self.data.addon_skipped, ["kazzak/jaina"])


def random_plan(rng: random.Random) -> tuple[LevelingData, date]:
    """Véletlen terv és nap az addon számolásának ellenőrzéséhez (sok egyezéssel és határesettel)."""
    start = date(2026, 9, 1) + timedelta(days=rng.randint(0, 60))
    first = start + timedelta(days=rng.randint(0, 30))
    last = first + timedelta(days=rng.randint(0, 45))
    start_level = Decimal(rng.choice((1, 10, 70, 80, 85)))
    target_level = start_level + rng.randint(1, 15)
    target_item_level = rng.choice((None, Decimal(rng.randint(29000, 33500)) / 100))
    settings = Settings(start, first, last, start_level, target_level, rng.choice(MODES), target_item_level)
    pairs = [(char_class, spec) for char_class, specs in WOW_SPECS.items() for spec in specs]
    if rng.random() < 0.5:
        pairs = rng.sample(pairs, 3)  # kevés spec: több karakter egy specben (Murlok.io-körök)
    scores = {}
    if rng.random() < 0.85:
        for char_class, spec in rng.sample(pairs, rng.randint(1, len(pairs))):
            scores[SpecScores.spec_key(char_class, spec)] = Decimal(rng.choice((0, rng.randint(15000, 40000)))) / 10
    levels = [start_level + Decimal(rng.randint(-200, int(target_level - start_level) * 100 + 200)) / 100]
    characters = []
    for index in range(rng.randint(0, 8)):
        char_class, spec = rng.choice(pairs) if rng.random() < 0.85 else ("", "")
        level = rng.choice(levels) if rng.random() < 0.3 else start_level + Decimal(
            rng.randint(-200, int(target_level - start_level) * 100 + 200)
        ) / 100
        levels.append(level)
        item_level = None if rng.random() < 0.2 else Decimal(rng.randint(27000, 34000)) / 100
        score = None if rng.random() < 0.25 else Decimal(rng.choice((0, rng.randint(0, 40000)))) / 10
        characters.append(
            Character(
                f"Karakter{index}",
                char_class,
                spec,
                max(Decimal(1), level),
                realm=rng.choice(("Draenor", "")),
                item_level=item_level,
                raiderio_score=score,
            )
        )
    data = LevelingData(settings, characters, SpecScores(scores), look_ahead=rng.random() < 0.6)
    return data, start + timedelta(days=rng.randint(-10, 80))


def expected_rows(data: LevelingData, today: date) -> dict:
    """A program szerinti legnagyobb lemaradások, ahogy az addon is kiírja (századokban, a
    pontszám tizedekben); a lista sorrendjében az első a legkisebb eltéréssel."""
    settings, characters = data.settings, data.characters
    goal_day = lookahead_day(settings, characters, today) if data.look_ahead else today

    def most_behind(rows, scale):
        best = None
        for character, current, planned in rows:
            if current is not None and planned is not None and (best is None or current - planned < best[1]):
                best = (character, current - planned, planned)
        if best is None:
            return {"problem": True}
        if best[1] >= 0:
            return {"ok": True}
        return {"name": best[0].name, "target": int(best[2] * scale), "missing": int(-best[1] * scale)}

    plans = build_plan(settings, characters, today, data.spec_scores, goal_day)
    levels = ((p.character, p.character.level, p.character.level - p.deviation) for p in plans)
    rows = {"level": most_behind(levels, 100)}
    for key, plan, value, scale in (
        ("itemLevel", plan_item_levels(characters, data.spec_scores, settings.target_item_level), "item_level", 100),
        ("score", plan_raiderio_scores(characters, data.spec_scores, settings.target_item_level), "raiderio_score", 10),
    ):
        rows[key] = (
            {"problem": True}
            if plan.step is None
            else most_behind(((c, getattr(c, value), plan.planned.get(c)) for c in characters), scale)
        )
    rows["goalDay"] = (goal_day - date(1970, 1, 1)).days
    return rows


@unittest.skipIf(LUA is None, "nincs Lua-értelmező (lua5.1, luajit vagy lua)")
class PlanTests(unittest.TestCase):
    """Az addon (Plan.lua) ugyanazt számolja-e, mint a program (leveling.py)."""

    def test_addon_computes_what_the_program_does(self):
        rng = random.Random(20261017)
        cases, expected = [], []
        # Kézzel: senki sincs lemaradásban itemlevelben (a két legnagyobb arány egyenlő: 10/1 = 20/2).
        settings = Settings(date(2026, 10, 1), date(2026, 10, 10), date(2026, 10, 20), target_item_level=Decimal(330))
        even = LevelingData(
            settings, [Character("A", item_level=Decimal(320)), Character("B", item_level=Decimal(310))]
        )
        for data, today in [(even, date(2026, 10, 5))] + [random_plan(rng) for _ in range(400)]:
            cases.append({"data": wow_addon.plan_payload(data, datetime(2026, 10, 17, 12)), "today": today.isoformat()})
            expected.append(expected_rows(data, today))
        with tempfile.TemporaryDirectory() as folder:
            cases_path, output = Path(folder) / "esetek.lua", Path(folder) / "eredmenyek.lua"
            cases_path.write_text(f"Cases = {wow_addon.lua_value(cases)}\n", encoding="utf-8")
            plan_lua = wow_addon.ADDON_SOURCE / "Plan.lua"
            result = subprocess.run(
                [LUA, str(TESTS / "plan_harness.lua"), str(plan_lua), str(cases_path), str(output)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            results = parse_lua(output.read_text(encoding="utf-8"))["Results"]
        kinds = set()
        for index, want in enumerate(expected):
            got = results[index + 1]
            for key in ("level", "itemLevel", "score"):
                row = got[key]
                got[key] = {"problem": True} if "problem" in row else row
                kinds.add((key, next(iter(want[key]))))
            with self.subTest(case=index):
                self.assertEqual(got, want)
        # A véletlen esetek között minden fajta eredmény előfordult.
        self.assertEqual(len(kinds), 9, kinds)

    def test_rounding_and_dates(self):
        script = (
            "local ns = {}\n"
            f"assert(loadfile({str(wow_addon.ADDON_SOURCE / 'Plan.lua')!r}))('WoWLeveling', ns)\n"
            "local P = ns.Plan\n"
            "print(P.RoundHalfUp(5, 2), P.RoundHalfUp(-5, 2), P.RoundHalfUp(7, 3), P.RoundHalfUp(-7, 3))\n"
            "print(P.ParseDay('1970-01-01'), P.ParseDay('2026-10-17'),\n"
            "    P.ParseDay('2028-02-29') - P.ParseDay('2028-02-28'))\n"
            "print(P.PlannedLevel(10, 19, 100, 9000, 9), P.PlannedLevel(10, 19, 100, 9000, 10), "
            "P.PlannedLevel(10, 19, 100, 9000, 14), P.PlannedLevel(10, 19, 100, 9000, 19))\n"
        )
        result = subprocess.run([LUA, "-"], input=script, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        days = (date(2026, 10, 17) - date(1970, 1, 1)).days
        self.assertEqual(
            result.stdout.split(),
            ["3", "-3", "2", "-2", "0", str(days), "1", "100", "990", "4550", "9000"],
        )


@unittest.skipIf(LUA is None, "nincs Lua-értelmező (lua5.1, luajit vagy lua)")
class AddonTests(unittest.TestCase):
    """Az addon lefuttatása a játékot utánzó környezetben (tests/addon_harness.lua)."""

    HARNESS_TIME = 1760700000  # a harness órája indításkor

    def run_addon(self, addon_dir: Path) -> tuple[str, Path, dict]:
        """A harness kimenete (chat és ablak), és a játék által kiírt mentés (fájl és tartalom)."""
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        output = folder / "WoWLeveling.lua"
        result = subprocess.run(
            [LUA, str(TESTS / "addon_harness.lua"), str(addon_dir), str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=folder,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout, output, parse_lua(output.read_text(encoding="utf-8"))[wow_addon.DB_VARIABLE]

    @staticmethod
    def windows(chat: str) -> dict:
        """Az ablak kiírt állapotai: név → {"shown", "level", "itemLevel", "score", "footer"} (színkódok nélkül)."""
        plain = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", chat)
        dumps, current = {}, None
        for line in plain.splitlines():
            if match := re.match(r"window (\w+): (\S+)$", line):
                current = dumps[match.group(1)] = {"shown": match.group(2) == "látszik"}
            elif match := re.match(r"row (\w+): (.*)$", line):
                current[match.group(1)] = [cell.strip() for cell in match.group(2).split(" | ")]
            elif line.startswith("footer: "):
                current["footer"] = line[len("footer: "):]
        return dumps

    def test_addon_saves_the_characters(self):
        chat, output, _db = self.run_addon(wow_addon.ADDON_SOURCE)
        data = wow_addon.load_addon_data(output)
        self.assertIn("Zôltan (Twisting Nether): szint 85,29, itemlevel 301,56, M+ pontszám 1234", chat)
        # A belépés és a felszerelés cseréje után csak egyszer mentett (és megnyitotta az ablakot),
        # szintlépéskor és a saját spec váltásakor mentett; a terv nélküli ablak nem frissül magától.
        self.assertEqual(re.findall(r"timers: (\d+)", chat), ["2", "0", "1", "1", "0"])
        login = self.windows(chat)["login"]
        self.assertTrue(login["shown"])
        self.assertEqual(
            [login["level"][0], login["itemLevel"][0]],
            ["Még nincs szinkronizált terv.", "A programban: Szinkronizálás, majd /reload."],
        )
        self.assertIn("2 karakter adatai vannak elmentve:", chat)
        self.assertIn("Zôltan (Twisting Nether): szint 86,05, itemlevel 301,56", chat)  # a titkos érték nem kell
        self.assertIn("hiba: ", chat)
        self.assertIn("UnitLevel: próba hiba", chat)
        self.assertEqual(data.problems, [])  # a kilépéskori mentés már sikerült
        zoltan = next(s for s in data.snapshots if s.name == "Zôltan")
        self.assertEqual(
            zoltan,
            Snapshot(
                "Zôltan",
                "Twisting Nether",
                "eu",
                "Orc",
                "Shaman",
                "Elemental",  # a régi spec-függvényekkel lekérve
                D("86.28"),
                D("303.25"),
                D("1500.5"),
                1760700000 + 600 + 86400 + 60,  # a harness órája kilépéskor
            ),
        )
        jaina = next(s for s in data.snapshots if s.name == "Jaina")
        self.assertEqual((jaina.level, jaina.updated), (D("90.00"), 1760000000))  # a korábbi mentés megmaradt

    def plan_data(self, **overrides) -> LevelingData:
        """A harness karaktereinek terve; overrides: név → (szint, itemlevel, pontszám) a program adata helyett."""
        today = date.fromtimestamp(self.HARNESS_TIME)
        settings = Settings(
            today - timedelta(days=5), today + timedelta(days=5), today + timedelta(days=5), D(80), D(90),
            target_item_level=D(320),
        )
        values = {"Zôltan": ("84.50", 300, 1200), "Jaina": ("90.00", 305, 1500), "Thrall": ("85.40", 290, 900)}
        values.update(overrides)
        specs = {"Zôltan": ("Shaman", "Enhancement"), "Jaina": ("Mage", "Frost"), "Thrall": ("Shaman", "Elemental")}
        realms = {"Zôltan": "Twisting Nether", "Jaina": "Draenor", "Thrall": "Draenor"}
        characters = [
            Character(name, *specs[name], D(level), realm=realms[name], item_level=D(ilvl), raiderio_score=D(score))
            for name, (level, ilvl, score) in values.items()
        ]
        scores = {"mage/frost": D(3600), "shaman/enhancement": D(3500), "shaman/elemental": D(3400)}
        return LevelingData(settings, characters, SpecScores(scores), look_ahead=False)

    @staticmethod
    def window_rows(data: LevelingData, today: date) -> dict:
        """Amit az ablaknak mutatnia kell a program számolása szerint (lásd expected_rows)."""
        shown = {}
        for key, scale, digits in (("level", 100, 2), ("itemLevel", 100, 2), ("score", 10, 1)):
            row = expected_rows(data, today)[key]
            text = lambda value: f"{D(value) / scale:.{digits}f}".replace(".", ",")  # noqa: E731
            if "name" in row:
                shown[key] = [row["name"], f"cél: {text(row['target'])}", f"hiányzik: {text(row['missing'])}"]
            else:
                shown[key] = ["senki sincs lemaradásban" if "ok" in row else row, "", ""]
        return shown

    def test_window_shows_the_largest_lag(self):
        # A program szinkronizálja a tervet az addon egy másolatába.
        addon = Path(tempfile.mkdtemp()) / wow_addon.ADDON_NAME
        self.addCleanup(shutil.rmtree, addon.parent)
        shutil.copytree(wow_addon.ADDON_SOURCE, addon)
        synced = self.plan_data()
        payload = wow_addon.plan_payload(synced, datetime.fromtimestamp(self.HARNESS_TIME - 3600))
        wow_addon.write_plan(addon, payload)
        chat, _output, db = self.run_addon(addon)
        windows = self.windows(chat)
        today = date.fromtimestamp(self.HARNESS_TIME)

        # Belépéskor: Zôltan élő adataival (85,29, 301,56, 1234), Jaina az addon újabb mentésével
        # (90, 310,25), Thrall a program adataival. Zôltan a legnagyobb lemaradásban szintben.
        live = {"Jaina": ("90.00", "310.25", 1500)}
        expected = self.window_rows(self.plan_data(Zôltan=("85.29", "301.56", 1234), **live), today)
        login = windows["login"]
        self.assertEqual({key: login[key] for key in expected}, expected)
        self.assertEqual(login["level"], ["Zôltan", "cél: 85,45", "hiányzik: 0,16"])
        self.assertEqual(login["itemLevel"][0], "Thrall")
        self.assertEqual(login["score"][0], "Jaina")
        stamp = datetime.fromtimestamp(payload["generated"]).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(login["footer"], f"Szinkronizálva: {stamp} · automatikus frissítés: Zôltan")
        # A listán van, így a tapasztalattól magától frissül; szintlépéskor kiesik a listából.
        self.assertEqual(re.findall(r"timers: (\d+)", chat), ["2", "1", "2", "1", "0"])
        xp = self.window_rows(self.plan_data(Zôltan=("85.40", "301.56", 1234), **live), today)
        self.assertEqual(windows["xp"]["level"], xp["level"])
        self.assertEqual(xp["level"], ["Zôltan", "cél: 85,45", "hiányzik: 0,05"])  # Thrall-lal egyenlő: az első
        levelup = self.window_rows(self.plan_data(Zôltan=("86.00", "301.56", 1234), **live), today)
        self.assertEqual({key: windows["levelup"][key] for key in levelup}, levelup)
        self.assertEqual(windows["levelup"]["level"][0], "Thrall")
        self.assertEqual(windows["levelup"]["footer"], f"Szinkronizálva: {stamp}")
        # Másnap az új szintcélokkal.
        nextday = self.window_rows(self.plan_data(Zôltan=("86.05", "301.56", 1234), **live), today + timedelta(days=1))
        self.assertEqual({key: windows["nextday"][key] for key in nextday}, nextday)
        self.assertEqual(windows["nextday"]["level"], ["Thrall", "cél: 86,36", "hiányzik: 0,96"])
        # Ki- és bekapcsolható; a helyét és az állapotát megjegyzi.
        self.assertEqual((windows["off"]["shown"], windows["on"]["shown"]), (False, True))
        self.assertEqual(
            db["window"], {"hidden": False, "point": "TOPLEFT", "relativePoint": "TOPLEFT", "x": 100, "y": -50}
        )


if __name__ == "__main__":
    unittest.main()
