"""World of Warcraft játékadatok: kasztok, specializációk és fajok.

A programban ezek javaslatként jelennek meg, bármi más is beírható.
Felület nélkül is használható (a Murlok.io-lekérés is innen ismeri a speceket).
"""

from __future__ import annotations

# Kasztok és specializációik, a játékbeli angol elnevezésekkel.
WOW_SPECS = {
    "Death Knight": ("Blood", "Frost", "Unholy"),
    "Demon Hunter": ("Havoc", "Vengeance", "Devourer"),
    "Druid": ("Balance", "Feral", "Guardian", "Restoration"),
    "Evoker": ("Devastation", "Preservation", "Augmentation"),
    "Hunter": ("Beast Mastery", "Marksmanship", "Survival"),
    "Mage": ("Arcane", "Fire", "Frost"),
    "Monk": ("Brewmaster", "Mistweaver", "Windwalker"),
    "Paladin": ("Holy", "Protection", "Retribution"),
    "Priest": ("Discipline", "Holy", "Shadow"),
    "Rogue": ("Assassination", "Outlaw", "Subtlety"),
    "Shaman": ("Elemental", "Enhancement", "Restoration"),
    "Warlock": ("Affliction", "Demonology", "Destruction"),
    "Warrior": ("Arms", "Fury", "Protection"),
}
WOW_CLASSES = tuple(WOW_SPECS)
ALL_SPECS = tuple(sorted({spec for specs in WOW_SPECS.values() for spec in specs}))
WOW_RACES = (
    "Blood Elf",
    "Dark Iron Dwarf",
    "Dracthyr",
    "Draenei",
    "Dwarf",
    "Earthen",
    "Gnome",
    "Goblin",
    "Haranir",
    "Highmountain Tauren",
    "Human",
    "Kul Tiran",
    "Lightforged Draenei",
    "Mag'har Orc",
    "Mechagnome",
    "Night Elf",
    "Nightborne",
    "Orc",
    "Pandaren",
    "Tauren",
    "Troll",
    "Undead",
    "Void Elf",
    "Vulpera",
    "Worgen",
    "Zandalari Troll",
)


def specs_for_class(class_name: str) -> tuple[str, ...]:
    """Az ismert kaszt specjei; üres vagy ismeretlen kasztnál az összes spec."""
    wanted = class_name.strip().casefold()
    for name, specs in WOW_SPECS.items():
        if name.casefold() == wanted:
            return specs
    return ALL_SPECS
