"""Gear ajánló: melyik tartalom (dungeon, Mythic+, delve, prey, raid…) ad még fejlesztést egy
adott itemlevelhez – a „WoW Gearing Ajánló” HTML-oldal (wow-gearing-ajanlo-refaktoralt.html)
adatai és logikája, valamint a belépési ilvl-ek frissítése a statisztikákból (az update.py
programé).

Egy tartalom (sor) adatai:
  entry_min: minimális belépési ilvl (0 = nincs korlát)
  drop_max : a legmagasabb ilvl, amit dropból kaphatsz
  vault_max: a legmagasabb ilvl, amit a Great Vaultból kaphatsz (None = nincs érdemi
             Vault-plafon, a drop_max marad)

A Mythic+ és a raid sorok belépési ilvl-je a statisztikákból frissíthető: a kulcsszintek
játékosainak, illetve a raidbossok kill-jeinek medián itemlevele (lásd plan_transfer). A
frissített értékeket a program az adatfájlban tárolja, az itt lévő alapértékek nem változnak.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

HTML_TEMPLATE = Path(__file__).resolve().with_name("wow-gearing-ajanlo-refaktoralt.html")
MIN_ILVL = 1.0  # a megadható itemlevel tartománya (mint a HTML-oldal mezőjén)
MAX_ILVL = 500.0


@dataclass(frozen=True)
class ContentRow:
    """Egy tartalom (pl. „Mythic+ 10” vagy „Raid - Sszorak Heroic”)."""

    name: str
    entry_min: float
    drop_max: float
    vault_max: float | None

    @property
    def vault_ceiling(self) -> float:
        """A Vaultból elérhető legmagasabb ilvl (Vault-plafon nélkül a drop)."""
        return self.drop_max if self.vault_max is None else self.vault_max


@dataclass(frozen=True)
class ContentGroup:
    """Tartalomtípus (szűrő-csoport). tiered: ilvl megadásakor csak a legjobb elérhető tier
    látszik, ezért a sorok tier-sorrendben vannak."""

    id: str
    label: str
    rows: tuple[ContentRow, ...]
    tiered: bool = False


# A csoportok sorrendje = a szűrők és a táblázat alapsorrendje.
GROUPS = (
    ContentGroup(
        "dungeon",
        "Dungeon",
        (
            ContentRow("Normal Dungeon", 0, 214, None),
            ContentRow("Heroic Dungeon", 256, 276, 292),
            ContentRow("Mythic 0 (Napi Reset)", 280, 292, 302),
        ),
    ),
    ContentGroup(
        "mplus",
        "Mythic+",
        (
            ContentRow("Mythic+ 2", 288, 295, 305),
            ContentRow("Mythic+ 3", 290, 295, 305),
            ContentRow("Mythic+ 4", 291.5, 298, 308),
            ContentRow("Mythic+ 5", 293, 302, 308),
            ContentRow("Mythic+ 6", 297, 305, 311),
            ContentRow("Mythic+ 7", 299, 305, 315),
            ContentRow("Mythic+ 8", 303, 308, 315),
            ContentRow("Mythic+ 9", 303, 308, 315),
            ContentRow("Mythic+ 10", 311.6, 311, 318),
            ContentRow("Mythic+ 11", 312, 311, 318),
            ContentRow("Mythic+ 12", 318, 311, 318),
            ContentRow("Mythic+ 13", 318, 311, 318),
            ContentRow("Mythic+ 14", 320, 311, 318),
            ContentRow("Mythic+ 15", 321, 311, 318),
            ContentRow("Mythic+ 16", 322, 311, 318),
            ContentRow("Mythic+ 17", 323.2, 311, 318),
            ContentRow("Mythic+ 18", 324.3, 311, 318),
            ContentRow("Mythic+ 19", 325.3, 311, 318),
            ContentRow("Mythic+ 20", 326.6, 311, 318),
            ContentRow("Mythic+ 21", 327.8, 311, 318),
            ContentRow("Mythic+ 22", 329.2, 311, 318),
        ),
    ),
    ContentGroup(
        "delve",
        "Delve",
        (
            ContentRow("Bountiful Delve Tier 1", 0, 266, 279),
            ContentRow("Bountiful Delve Tier 2", 187, 269, 282),
            ContentRow("Bountiful Delve Tier 3", 200, 272, 285),
            ContentRow("Bountiful Delve Tier 4", 259, 276, 289),
            ContentRow("Bountiful Delve Tier 5", 268, 279, 292),
            ContentRow("Bountiful Delve Tier 6", 275, 282, 298),
            ContentRow("Bountiful Delve Tier 7", 281, 292, 302),
            ContentRow("Bountiful Delve Tier 8", 290, 295, 305),
            ContentRow("Bountiful Delve Tier 9", 296, 295, 305),
            ContentRow("Bountiful Delve Tier 10", 303, 295, 305),
            ContentRow("Bountiful Delve Tier 11", 309, 295, 305),
        ),
        tiered=True,
    ),
    ContentGroup(
        "prey",
        "Prey",
        (
            ContentRow("Prey - Normal", 1, 266, 279),
            ContentRow("Prey - Hard", 262, 279, 292),
            ContentRow("Prey - Nightmare (Szóló)", 280, 292, 305),
        ),
        tiered=True,
    ),
    ContentGroup(
        "raid",
        "Raid",
        (
            ContentRow("Raid - LFR (Venomous Abyss)", 273, 289, 292),
            ContentRow("Raid - Nek'zali the Soulcoiler Normal", 306.8, 292, 305),
            ContentRow("Raid - The Lost Explorers Normal", 305.6, 295, 305),
            ContentRow("Raid - Entombed Sentinels Normal", 305.5, 295, 305),
            ContentRow("Raid - Vashnik the Malignant Normal", 305.6, 298, 305),
            ContentRow("Raid - Sszorak Normal", 306, 298, 305),
            ContentRow("Raid - The Twin Fangs Normal", 306.5, 302, 305),
            ContentRow("Raid - The Coiled Altar Normal", 310.3, 302, 305),
            ContentRow("Raid - Ula'tek Normal", 311.2, 302, 305),
            ContentRow("Raid - Nymrissa Wavecaller Normal", 303.9, 292, 305),
            ContentRow("Raid - Kith'ix Normal", 350, 298, 305),
            ContentRow("Raid - Nek'zali the Soulcoiler Heroic", 319.4, 305, 318),
            ContentRow("Raid - The Lost Explorers Heroic", 319.4, 308, 318),
            ContentRow("Raid - Entombed Sentinels Heroic", 319.3, 308, 318),
            ContentRow("Raid - Vashnik the Malignant Heroic", 319.3, 311, 318),
            ContentRow("Raid - Sszorak Heroic", 319.8, 311, 318),
            ContentRow("Raid - The Twin Fangs Heroic", 320.2, 311, 318),
            ContentRow("Raid - The Coiled Altar Heroic", 321.2, 315, 318),
            ContentRow("Raid - Ula'tek Heroic", 321.9, 315, 318),
            ContentRow("Raid - Nymrissa Wavecaller Heroic", 317.7, 305, 318),
            ContentRow("Raid - Kith'ix Heroic", 350, 302, 318),
            ContentRow("Raid - Nek'zali the Soulcoiler Mythic", 323.9, 318, 335),
            ContentRow("Raid - The Lost Explorers Mythic", 324.1, 321, 335),
            ContentRow("Raid - Entombed Sentinels Mythic", 324.9, 321, 335),
            ContentRow("Raid - Vashnik the Malignant Mythic", 325.1, 324, 335),
            ContentRow("Raid - Sszorak Mythic", 326.1, 324, 335),
            ContentRow("Raid - The Twin Fangs Mythic", 326.6, 324, 335),
            ContentRow("Raid - The Coiled Altar Mythic", 328.5, 344, 344),
            ContentRow("Raid - Ula'tek Mythic", 330.3, 344, 344),
            ContentRow("Raid - Nymrissa Wavecaller Mythic", 324.6, 318, 335),
            ContentRow("Raid - Kith'ix Mythic", 350, 344, 305),
        ),
    ),
    ContentGroup(
        "world",
        "Világ / Daily",
        (
            ContentRow("Daily quest reward", 0, 276, None),
        ),
    ),
)


@dataclass(frozen=True)
class Status:
    priority: int  # a rendezés sorrendje és a jelmagyarázat számozása
    label: str  # a táblázat „Ajánlás” oszlopában
    legend: str  # a jelmagyarázatban


STATUSES = {
    "recommended": Status(1, "Irány farmolni!", "Ideális! (Közvetlen loot fejlesztés)"),
    "vault": Status(2, "Csak Vaultért", "Vault miatt éri meg (a drop már nem javít)"),
    "undergeared": Status(3, "Túl alacsony ilvl", "Túl alacsony ilvl (Nehéz lehet)"),
    "outgrown": Status(4, "Túlfejlett vagy", "Kimaxoltad (Nincs értelme ide menni)"),
}


def format_ilvl(value: float) -> str:
    """Legfeljebb 2 tizedes, felesleges nullák nélkül, tizedesvesszővel (288, 291,5)."""
    return js_number(value).replace(".", ",")


def js_number(value: float) -> str:
    """Szám a HTML-oldal adataiban (tizedesponttal): 276.0 → 276, 303.25 → 303.25."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class Evaluation:
    """Egy sor értékelése: az állapot (None: nincs megadva ilvl), a rendezési súly (gain:
    nagyobb = előrébb a kategórián belül) és a megjegyzés."""

    row: ContentRow
    status: str | None = None
    gain: float = 0.0
    note: str = ""


def evaluate(ilvl: float, row: ContentRow) -> Evaluation:
    """Megéri-e a tartalom ezzel az itemlevellel:
    recommended: a drop még fejleszt (gain: mennyivel);
    vault: csak a Vault-plafon fejleszt (gain: mennyivel);
    undergeared: a belépési ilvl alatt (gain: a negatív hiány – a legközelebbi cél kerül előre);
    outgrown: már a Vault sem fejleszt (gain <= 0 – a legmagasabb szintű tartalom elöl)."""
    ceiling = row.vault_ceiling
    if ilvl < row.entry_min:
        missing = row.entry_min - ilvl
        return Evaluation(row, "undergeared", -missing, f"{format_ilvl(missing)} ilvl hiányzik")
    if ilvl < row.drop_max:
        gain = row.drop_max - ilvl
        return Evaluation(row, "recommended", gain, f"dropból még +{format_ilvl(gain)} ilvl")
    if ilvl < ceiling:
        gain = ceiling - ilvl
        return Evaluation(row, "vault", gain, f"Vaultból még +{format_ilvl(gain)} ilvl")
    return Evaluation(row, "outgrown", ceiling - ilvl)


def best_reachable_row(group: ContentGroup, ilvl: float) -> ContentRow:
    """A tier-es csoport legjobb elérhető tierje: az utolsó, amelynek a belépési ilvl-jét már
    eléred; ha egyiket sem, az első."""
    reachable = [row for row in group.rows if ilvl >= row.entry_min]
    return reachable[-1] if reachable else group.rows[0]


def build_items(
    ilvl: float | None, active_ids, show_all_tiers: bool = False, groups=GROUPS
) -> list[Evaluation]:
    """A megjelenítendő sorok a bepipált csoportokból, értékelve és rendezve: az állapot
    szerint, azon belül a nagyobb nyereség, majd a magasabb Vault-plafon előre (egyezésnél az
    adatok sorrendje marad). ilvl nélkül értékelés nélkül, az adatok sorrendjében."""
    collapse = ilvl is not None and not show_all_tiers
    rows = [
        row
        for group in groups
        if group.id in active_ids
        for row in ([best_reachable_row(group, ilvl)] if collapse and group.tiered else group.rows)
    ]
    if ilvl is None:
        return [Evaluation(row) for row in rows]
    return sorted(
        (evaluate(ilvl, row) for row in rows),
        key=lambda item: (STATUSES[item.status].priority, -item.gain, -item.row.vault_ceiling),
    )


def with_entry_mins(entry_mins: dict[str, float], groups=GROUPS) -> tuple[ContentGroup, ...]:
    """A csoportok a statisztikákból frissített belépési ilvl-ekkel (a többi sor az alapértékkel)."""
    return tuple(
        replace(
            group, rows=tuple(replace(row, entry_min=entry_mins.get(row.name, row.entry_min)) for row in group.rows)
        )
        for group in groups
    )


# --------------------------------------------------------------------------- adatátvitel (update.py)

MPLUS_PREFIX = "Mythic+ "  # a statisztikából frissülő sorok neve így kezdődik
RAID_PREFIX = "Raid - "
TOTAL_ROW = "Összes boss"  # a raid statisztika összesítő sora: ehhez nincs tartalom
RAID_METRIC = "raid átlag / kill"  # a raid statisztika mérőszáma, amelynek a mediánja számít


def mplus_targets(summary_rows) -> dict[str, float | None]:
    """A Mythic+ statisztika soraiból (raiderio_ilvl_stats.summary_rows: kulcsszint, futás,
    játékos, átlag, medián, …) a sorok új belépési ilvl-je: {"Mythic+ 10": medián}."""
    return {f"{MPLUS_PREFIX}{row[0]}": row[4] for row in summary_rows}


def raid_targets(sections) -> dict[str, float | None]:
    """A raid statisztika eredményéből (wcl_raid_ilvl_stats.run: sections) a sorok új belépési
    ilvl-je: {"Raid - Sszorak Heroic": medián}, egy tizedesre kerekítve (mint a CSV-ben). A még
    meg nem ölt boss mediánja None; az „Összes boss” sor kimarad."""
    from wcl_raid_ilvl_stats import DIFFICULTIES

    targets = {}
    for metric, tables in sections:
        if metric != RAID_METRIC:
            continue
        for difficulty, rows in tables.items():
            for name, _counts, stats in rows:
                if name != TOTAL_ROW:
                    median = None if stats is None else round(stats["median"], 1)
                    targets[f"{RAID_PREFIX}{name} {DIFFICULTIES[difficulty]}"] = median
    return targets


def _parse_number(text: str) -> float | None:
    """'301,8' vagy '301.8' → 301.8; üres mező → None."""
    text = (text or "").strip().replace(",", ".")
    return float(text) if text else None


def read_stats_csv(path) -> tuple[dict[str, float | None], str]:
    """Egy statisztika CSV-je (a parancssori programok --csv kimenete, vagy a statisztikai
    ablakok „CSV mentése…” gombjáé): a sorok új belépési ilvl-je és az érintett sorok
    névkezdete. A formátumot a fejléc dönti el: a Mythic+ statisztikáé vesszővel tagolt
    (mythic_level, median_item_level, …), a raidé pontosvesszővel, tizedesvesszővel
    (Nehézség, Mérőszám, Boss, Medián, …). Hibás fájlnál ValueError."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        text = handle.read()
    header = text.splitlines()[0] if text else ""
    if "mythic_level" in header:
        rows = list(csv.DictReader(text.splitlines(), delimiter=","))
        _require(path, rows, ("mythic_level", "median_item_level"))
        targets = {
            f"{MPLUS_PREFIX}{row['mythic_level'].strip()}": _parse_number(row["median_item_level"])
            for row in rows
            if (row.get("mythic_level") or "").strip()
        }
        return targets, MPLUS_PREFIX
    if "Nehézség" in header:
        rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
        _require(path, rows, ("Nehézség", "Boss", "Medián"))
        targets = {}
        for row in rows:
            boss, difficulty = (row.get("Boss") or "").strip(), (row.get("Nehézség") or "").strip()
            metric = (row.get("Mérőszám") or RAID_METRIC).strip()
            if boss and difficulty and boss != TOTAL_ROW and metric == RAID_METRIC:
                targets[f"{RAID_PREFIX}{boss} {difficulty}"] = _parse_number(row["Medián"])
        return targets, RAID_PREFIX
    raise ValueError(f"{Path(path).name}: nem a Mythic+ (live.csv) vagy a raid (stat.csv) statisztika CSV-je.")


def _require(path, rows, columns) -> None:
    present = set(rows[0]) if rows else set()
    missing = [column for column in columns if column not in present]
    if missing or not rows:
        raise ValueError(f"{Path(path).name}: hiányzó oszlop(ok): {', '.join(missing) or 'nincs adatsor'}")


@dataclass
class TransferPlan:
    """Mi változna az adatátvitellel (mint az update.py kimenete)."""

    changed: list[tuple[str, float, float]] = field(default_factory=list)  # (sor, régi, új)
    unchanged: list[str] = field(default_factory=list)  # már naprakész
    no_data: list[tuple[str, float]] = field(default_factory=list)  # (sor, marad) – nincs hozzá adat
    orphans: list[str] = field(default_factory=list)  # adat, amelyhez nincs sor (pl. elírt bossnév)

    def values(self) -> dict[str, float]:
        """Az átírandó belépési ilvl-ek."""
        return {name: new for name, _old, new in self.changed}


def plan_transfer(targets: dict[str, float | None], groups, prefixes) -> TransferPlan:
    """Az update.py szabályai szerint: ahol van adat, ott a belépési ilvl az új érték (két
    tizedesre); ahol nincs (a statisztikában nem szereplő szint, még meg nem ölt boss), ott
    változatlan marad. Csak a `prefixes` névkezdetű sorokat nézi (pl. csak a Mythic+ sorokat,
    ha csak a Mythic+ statisztika adatai jöttek)."""
    plan = TransferPlan()
    seen = set()
    for group in groups:
        for row in group.rows:
            if not row.name.startswith(tuple(prefixes)):
                continue
            seen.add(row.name)
            new = targets.get(row.name)
            if new is None:
                plan.no_data.append((row.name, row.entry_min))
                continue
            new = float(js_number(new))
            if new == row.entry_min:
                plan.unchanged.append(row.name)
            else:
                plan.changed.append((row.name, row.entry_min, new))
    plan.orphans = sorted(name for name, value in targets.items() if value is not None and name not in seen)
    return plan


# --------------------------------------------------------------------------- HTML-oldal

# Egy sor a HTML-oldal adataiban: { name: "...", entryMin: <szám>, dropMax: <szám>, vaultMax: <szám vagy null>
_HTML_ROW = re.compile(
    r'(?P<head>\{\s*name:\s*"(?P<name>[^"]*)",\s*entryMin:\s*)(?P<entry>\d+(?:\.\d+)?)'
    r"(?P<mid1>,\s*dropMax:\s*)(?P<drop>\d+(?:\.\d+)?)"
    r"(?P<mid2>,\s*vaultMax:\s*)(?P<vault>\d+(?:\.\d+)?|null)"
)


def update_html(html: str, groups) -> tuple[str, list[str]]:
    """A HTML-oldal adatainak frissítése a program adataival (belépési, drop és Vault ilvl),
    úgy, hogy minden más bájt – és a változatlan számok írásmódja is – ugyanaz marad.
    Visszaadja az új HTML-t és azokat a sorokat, amelyek nincsenek meg az oldalon."""
    rows = {row.name: row for group in groups for row in group.rows}
    seen = set()

    def number(old: str, new: float | None) -> str:
        if new is None:
            return "null"
        return old if old != "null" and float(old) == float(js_number(new)) else js_number(new)

    def replace_row(match) -> str:
        row = rows.get(match["name"])
        if row is None:
            return match[0]
        seen.add(row.name)
        return (
            match["head"]
            + number(match["entry"], row.entry_min)
            + match["mid1"]
            + number(match["drop"], row.drop_max)
            + match["mid2"]
            + number(match["vault"], row.vault_max)
        )

    new_html = _HTML_ROW.sub(replace_row, html)
    if not seen:
        raise ValueError("A HTML-ben nem található egyetlen { name: ..., entryMin: ... } sor sem.")
    return new_html, [name for name in rows if name not in seen]
