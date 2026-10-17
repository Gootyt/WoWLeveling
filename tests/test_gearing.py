"""A gear ajánló adatainak, logikájának és az adatátvitelnek (update.py) a tesztjei."""

import tempfile
import unittest
from pathlib import Path

import gearing
from gearing import ContentGroup, ContentRow

ALL = {group.id for group in gearing.GROUPS}


def names(items):
    return [item.row.name for item in items]


class EvaluateTests(unittest.TestCase):
    def test_statuses_and_notes(self):
        row = ContentRow("Mythic+ 10", 311.6, 311, 318)
        cases = (
            (300, "undergeared", -11.6, "11,6 ilvl hiányzik"),
            (311.6, "vault", 6.4, "Vaultból még +6,4 ilvl"),  # a drop (311) már nem javít
            (318, "outgrown", 0, ""),
        )
        for ilvl, status, gain, note in cases:
            with self.subTest(ilvl=ilvl):
                item = gearing.evaluate(ilvl, row)
                self.assertEqual((item.status, round(item.gain, 2), item.note), (status, gain, note))
        item = gearing.evaluate(305.25, ContentRow("Mythic+ 8", 303, 308, 315))
        self.assertEqual((item.status, item.gain, item.note), ("recommended", 2.75, "dropból még +2,75 ilvl"))
        self.assertEqual(ContentRow("Daily", 0, 276, None).vault_ceiling, 276)  # Vault-plafon nélkül a drop

    def test_order_follows_status_gain_and_vault_ceiling(self):
        items = gearing.build_items(305.25, ALL)
        self.assertEqual(names(items)[:6], ["Mythic+ 8", "Mythic+ 9", "Mythic+ 7", "Mythic+ 6", "Mythic+ 4", "Mythic+ 5"])
        statuses = [gearing.STATUSES[item.status].priority for item in items]
        self.assertEqual(statuses, sorted(statuses))
        # A Delve és a Prey csoportból csak a legjobb elérhető tier látszik, kérésre mind.
        self.assertEqual([n for n in names(items) if "Delve" in n], ["Bountiful Delve Tier 10"])
        all_tiers = gearing.build_items(305.25, {"delve"}, show_all_tiers=True)
        self.assertEqual(len(all_tiers), 11)
        self.assertEqual(names(gearing.build_items(100, {"delve", "prey"})), ["Bountiful Delve Tier 1", "Prey - Normal"])

    def test_without_ilvl_the_data_order_shows(self):
        items = gearing.build_items(None, {"dungeon", "world"})
        self.assertEqual(names(items), ["Normal Dungeon", "Heroic Dungeon", "Mythic 0 (Napi Reset)", "Daily quest reward"])
        self.assertTrue(all(item.status is None for item in items))
        self.assertEqual(gearing.build_items(300, set()), [])

    def test_entry_overrides(self):
        groups = gearing.with_entry_mins({"Mythic+ 10": 309.5})
        rows = {row.name: row for group in groups for row in group.rows}
        self.assertEqual((rows["Mythic+ 10"].entry_min, rows["Mythic+ 11"].entry_min), (309.5, 312))
        self.assertEqual(rows["Mythic+ 10"].drop_max, 311)

    def test_formats(self):
        self.assertEqual([gearing.format_ilvl(v) for v in (276.0, 291.5, 6.6299999999999955)], ["276", "291,5", "6,63"])
        self.assertEqual(gearing.js_number(303.25), "303.25")


class TransferTests(unittest.TestCase):
    GROUPS = (
        ContentGroup("mplus", "Mythic+", (ContentRow("Mythic+ 2", 288, 295, 305), ContentRow("Mythic+ 3", 290, 295, 305))),
        ContentGroup(
            "raid",
            "Raid",
            (
                ContentRow("Raid - LFR (Venomous Abyss)", 273, 289, 292),
                ContentRow("Raid - Sszorak Heroic", 319.8, 311, 318),
                ContentRow("Raid - Kith'ix Heroic", 350, 302, 318),
            ),
        ),
    )

    def test_plan(self):
        targets = {"Mythic+ 2": 288.0, "Mythic+ 3": 289.14, "Mythic+ 30": 340.0, "Raid - Sszorak Heroic": 320.0}
        plan = gearing.plan_transfer(targets, self.GROUPS, [gearing.MPLUS_PREFIX])
        self.assertEqual(plan.changed, [("Mythic+ 3", 290, 289.14)])
        self.assertEqual((plan.unchanged, plan.no_data), (["Mythic+ 2"], []))
        # A raid sorokat ez a (Mythic+) átvitel nem nézi, de az ismeretlen adatokat jelzi.
        self.assertEqual(plan.orphans, ["Mythic+ 30", "Raid - Sszorak Heroic"])
        self.assertEqual(plan.values(), {"Mythic+ 3": 289.14})

        plan = gearing.plan_transfer(
            {"Raid - Sszorak Heroic": 319.8, "Raid - Kith'ix Heroic": None}, self.GROUPS, [gearing.RAID_PREFIX]
        )
        self.assertEqual(plan.unchanged, ["Raid - Sszorak Heroic"])
        self.assertEqual(plan.no_data, [("Raid - LFR (Venomous Abyss)", 273), ("Raid - Kith'ix Heroic", 350)])

    def test_targets_from_statistics_results(self):
        rows = [(2, 8162, 37590, 287.2, 288.0, 279.0, 250.0, 347.0), (10, 1, 5, 309.5, 311.6, 303.0, 250.0, 348.0)]
        self.assertEqual(gearing.mplus_targets(rows), {"Mythic+ 2": 288.0, "Mythic+ 10": 311.6})
        stats = {"mean": 318.0, "median": 319.84, "p25": 317.0, "min": 248.6, "max": 325.4}
        tables = {
            4: [("Sszorak", (1276,), stats), ("Kith'ix", (0,), None), ("Összes boss", (1276,), stats)],
        }
        sections = [("raid átlag / kill", tables), ("játékos egyéni", {4: [("Sszorak", (5, 100), dict(stats, median=330.0))]})]
        self.assertEqual(
            gearing.raid_targets(sections), {"Raid - Sszorak Heroic": 319.8, "Raid - Kith'ix Heroic": None}
        )

    def write(self, folder, name, text):
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8-sig")
        return path

    def test_read_csv_files(self):
        with tempfile.TemporaryDirectory() as folder:
            live = self.write(
                folder,
                "live.csv",
                "mythic_level,runs,players,avg_item_level,median_item_level,p25_item_level,min_item_level,max_item_level\n"
                "2,8162,37590,287.2,288.0,279.0,250.0,347.0\n4,3571,17222,290.8,291.4,284.0,250.0,344.0\n",
            )
            stat = self.write(
                folder,
                "stat.csv",
                "Nehézség;Mérőszám;Boss;Kill;Játékos;Átlag;Medián;25. percentilis;Min;Max\n"
                "Heroic;raid átlag / kill;Sszorak;1276;;318,0;319,8;317,7;248,6;325,4\n"
                "Heroic;raid átlag / kill;Kith'ix;0;;;;;;\n"
                "Heroic;raid átlag / kill;Összes boss;16178;;318,4;320,0;317,3;248,6;327,7\n"
                "Heroic;játékos egyéni;Sszorak;5;100;330,0;330,0;329,0;320,0;340,0\n",
            )
            self.assertEqual(gearing.read_stats_csv(live), ({"Mythic+ 2": 288.0, "Mythic+ 4": 291.4}, "Mythic+ "))
            self.assertEqual(
                gearing.read_stats_csv(stat),
                ({"Raid - Sszorak Heroic": 319.8, "Raid - Kith'ix Heroic": None}, "Raid - "),
            )
            other = self.write(folder, "mas.csv", "a,b\n1,2\n")
            with self.assertRaisesRegex(ValueError, "nem a Mythic\\+ .* vagy a raid"):
                gearing.read_stats_csv(other)
            broken = self.write(folder, "live2.csv", "mythic_level,runs\n2,10\n")
            with self.assertRaisesRegex(ValueError, "hiányzó oszlop\\(ok\\): median_item_level"):
                gearing.read_stats_csv(broken)


class HtmlTests(unittest.TestCase):
    def test_template_matches_the_programs_data(self):
        html = gearing.HTML_TEMPLATE.read_text(encoding="utf-8")
        new_html, missing = gearing.update_html(html, gearing.GROUPS)
        self.assertEqual((new_html == html, missing), (True, []))  # az alapértékek = a HTML-oldal adatai

    def test_only_the_numbers_change(self):
        html = (
            'const GROUPS = [\n  { name: "Mythic+ 2",  entryMin: 288.0,    dropMax: 295, vaultMax: 305 },\r\n'
            '  { name: "Daily", entryMin: 0, dropMax: 276, vaultMax: null },\n'
            '  { name: "Régi sor", entryMin: 1, dropMax: 2, vaultMax: 3 },\n];'
        )
        groups = (
            ContentGroup(
                "x",
                "X",
                (
                    ContentRow("Mythic+ 2", 288, 296, 305.5),
                    ContentRow("Daily", 0, 276, None),
                    ContentRow("Új sor", 1, 2, 3),
                ),
            ),
        )
        new_html, missing = gearing.update_html(html, groups)
        self.assertEqual(
            new_html,
            'const GROUPS = [\n  { name: "Mythic+ 2",  entryMin: 288.0,    dropMax: 296, vaultMax: 305.5 },\r\n'
            '  { name: "Daily", entryMin: 0, dropMax: 276, vaultMax: null },\n'
            '  { name: "Régi sor", entryMin: 1, dropMax: 2, vaultMax: 3 },\n];',
        )
        self.assertEqual(missing, ["Új sor"])
        with self.assertRaises(ValueError):
            gearing.update_html("<html></html>", groups)


if __name__ == "__main__":
    unittest.main()
