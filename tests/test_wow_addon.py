"""A WoWLeveling addon mentéseinek beolvasása, megkeresése és importálása (wow_addon.py), valamint
maga az addon (addon/WoWLeveling), ha van Lua-értelmező a gépen."""

import re
import shutil
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import wow_addon
from leveling import Character, LevelingData, Settings
from wow_addon import AddonError, LuaSyntaxError, Snapshot, parse_lua

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
        target = wow_addon.install_addon(self.game)
        self.assertEqual(target, self.game / "Interface" / "AddOns" / "WoWLeveling")
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["WoWLeveling.lua", "WoWLeveling.toc"])
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
        self.assertEqual(files, ["WoWLeveling.lua"])


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


@unittest.skipIf(LUA is None, "nincs Lua-értelmező (lua5.1, luajit vagy lua)")
class AddonTests(unittest.TestCase):
    """Az addon lefuttatása a játékot utánzó környezetben (tests/addon_harness.lua)."""

    def test_addon_saves_the_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "WoWLeveling.lua"
            result = subprocess.run(
                [LUA, str(TESTS / "addon_harness.lua"), str(wow_addon.ADDON_SOURCE), str(output)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                cwd=folder,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = wow_addon.load_addon_data(output)
        chat = result.stdout
        self.assertIn("Zôltan (Twisting Nether): szint 85,29, itemlevel 301,56, M+ pontszám 1234", chat)
        # A belépés és a felszerelés cseréje után csak egyszer mentett, és csak a saját spec váltásakor.
        self.assertEqual(re.findall(r"timers: (\d+)", chat), ["1", "1", "1"])
        self.assertIn("2 karakter adatai vannak elmentve:", chat)
        self.assertIn("Zôltan (Twisting Nether): szint 86,00, itemlevel 301,56", chat)  # a titkos érték nem kell
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
                1760700660,
            ),
        )
        jaina = next(s for s in data.snapshots if s.name == "Jaina")
        self.assertEqual((jaina.level, jaina.updated), (D("90.00"), 1760000000))  # a korábbi mentés megmaradt


if __name__ == "__main__":
    unittest.main()
