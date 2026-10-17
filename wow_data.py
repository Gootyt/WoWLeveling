"""World of Warcraft játékadatok: kasztok, specializációk, szerepek, páncéltípusok,
fajok, frakciók és a választható faj–kaszt kombinációk (Midnight, 12.1-es patch).

A programban ezek javaslatként jelennek meg, bármi más is beírható.
Felület nélkül is használható (a karakterjavaslat is innen ismeri a combókat).
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
    found = find_class(class_name)
    return WOW_SPECS[found] if found else ALL_SPECS


# Szerepek; a DPS specek közelharci (melee) és távolsági (ranged) csoportra oszlanak.
TANK = "tank"
HEALER = "healer"
MELEE = "melee DPS"
RANGED = "ranged DPS"
ROLES = (TANK, HEALER, MELEE, RANGED)
_ROLE_SPECS = {
    TANK: {
        "Death Knight": ("Blood",),
        "Demon Hunter": ("Vengeance",),
        "Druid": ("Guardian",),
        "Monk": ("Brewmaster",),
        "Paladin": ("Protection",),
        "Warrior": ("Protection",),
    },
    HEALER: {
        "Druid": ("Restoration",),
        "Evoker": ("Preservation",),
        "Monk": ("Mistweaver",),
        "Paladin": ("Holy",),
        "Priest": ("Discipline", "Holy"),
        "Shaman": ("Restoration",),
    },
    MELEE: {
        "Death Knight": ("Frost", "Unholy"),
        "Demon Hunter": ("Havoc",),
        "Druid": ("Feral",),
        "Hunter": ("Survival",),
        "Monk": ("Windwalker",),
        "Paladin": ("Retribution",),
        "Rogue": ("Assassination", "Outlaw", "Subtlety"),
        "Shaman": ("Enhancement",),
        "Warrior": ("Arms", "Fury"),
    },
    RANGED: {
        "Demon Hunter": ("Devourer",),
        "Druid": ("Balance",),
        "Evoker": ("Devastation", "Augmentation"),
        "Hunter": ("Beast Mastery", "Marksmanship"),
        "Mage": ("Arcane", "Fire", "Frost"),
        "Priest": ("Shadow",),
        "Shaman": ("Elemental",),
        "Warlock": ("Affliction", "Demonology", "Destruction"),
    },
}
# (kaszt, spec) → szerep
SPEC_ROLES = {
    (char_class, spec): role
    for role, classes in _ROLE_SPECS.items()
    for char_class, specs in classes.items()
    for spec in specs
}

# Páncéltípusok.
CLOTH = "cloth"
LEATHER = "leather"
MAIL = "mail"
PLATE = "plate"
ARMOR_TYPES = (CLOTH, LEATHER, MAIL, PLATE)
CLASS_ARMOR = {
    "Death Knight": PLATE,
    "Demon Hunter": LEATHER,
    "Druid": LEATHER,
    "Evoker": MAIL,
    "Hunter": MAIL,
    "Mage": CLOTH,
    "Monk": LEATHER,
    "Paladin": PLATE,
    "Priest": CLOTH,
    "Rogue": LEATHER,
    "Shaman": MAIL,
    "Warlock": CLOTH,
    "Warrior": PLATE,
}

# Frakciók és a bennük választható fajok, a karakterkészítő sorrendjében: elöl az
# alapfajok, utánuk a szövetséges (allied) fajok, amelyeket előbb fel kell oldani.
# A Pandaren, a Dracthyr, az Earthen és a Haranir mindkét frakcióban választható.
ALLIANCE = "Alliance"
HORDE = "Horde"
FACTIONS = (ALLIANCE, HORDE)
FACTION_RACES = {
    ALLIANCE: (
        "Human",
        "Dwarf",
        "Night Elf",
        "Gnome",
        "Draenei",
        "Worgen",
        "Pandaren",
        "Dracthyr",
        "Void Elf",
        "Lightforged Draenei",
        "Dark Iron Dwarf",
        "Kul Tiran",
        "Mechagnome",
        "Earthen",
        "Haranir",
    ),
    HORDE: (
        "Orc",
        "Undead",
        "Tauren",
        "Troll",
        "Blood Elf",
        "Goblin",
        "Pandaren",
        "Dracthyr",
        "Nightborne",
        "Highmountain Tauren",
        "Mag'har Orc",
        "Zandalari Troll",
        "Vulpera",
        "Earthen",
        "Haranir",
    ),
}

# Faj–kaszt kombinációk (forrás: warcraft.wiki.gg, „Class by race”). Ezt a hat
# kasztot minden faj választhatja, a többit csak az alább felsorolt fajok.
# A 12.2-es patchtől a Night Elf, a Troll és az Undead is lehet Paladin.
_CLASSES_FOR_ALL_RACES = ("Hunter", "Mage", "Priest", "Rogue", "Warlock", "Warrior")
_RACE_EXTRA_CLASSES = {
    "Blood Elf": ("Death Knight", "Demon Hunter", "Monk", "Paladin"),
    "Dark Iron Dwarf": ("Death Knight", "Monk", "Paladin", "Shaman"),
    "Dracthyr": ("Evoker",),
    "Draenei": ("Death Knight", "Monk", "Paladin", "Shaman"),
    "Dwarf": ("Death Knight", "Monk", "Paladin", "Shaman"),
    "Earthen": ("Monk", "Paladin", "Shaman"),
    "Gnome": ("Death Knight", "Monk"),
    "Goblin": ("Death Knight", "Monk", "Shaman"),
    "Haranir": ("Druid", "Monk", "Shaman"),
    "Highmountain Tauren": ("Death Knight", "Druid", "Monk", "Shaman"),
    "Human": ("Death Knight", "Monk", "Paladin"),
    "Kul Tiran": ("Death Knight", "Druid", "Monk", "Shaman"),
    "Lightforged Draenei": ("Death Knight", "Monk", "Paladin"),
    "Mag'har Orc": ("Death Knight", "Monk", "Shaman"),
    "Mechagnome": ("Death Knight", "Monk"),
    "Night Elf": ("Death Knight", "Demon Hunter", "Druid", "Monk"),
    "Nightborne": ("Death Knight", "Monk"),
    "Orc": ("Death Knight", "Monk", "Shaman"),
    "Pandaren": ("Death Knight", "Monk", "Shaman"),
    "Tauren": ("Death Knight", "Druid", "Monk", "Paladin", "Shaman"),
    "Troll": ("Death Knight", "Druid", "Monk", "Shaman"),
    "Undead": ("Death Knight", "Monk"),
    "Void Elf": ("Death Knight", "Demon Hunter", "Monk"),
    "Vulpera": ("Death Knight", "Monk", "Shaman"),
    "Worgen": ("Death Knight", "Druid", "Monk"),
    "Zandalari Troll": ("Death Knight", "Druid", "Monk", "Paladin", "Shaman"),
}
# Faj → a választható kasztjai (a WOW_CLASSES sorrendjében).
RACE_CLASSES = {
    race: tuple(
        char_class for char_class in WOW_CLASSES if char_class in _CLASSES_FOR_ALL_RACES or char_class in extras
    )
    for race, extras in _RACE_EXTRA_CLASSES.items()
}


# A specializációk játékbeli azonosítói (specID; a WoWLeveling addon ezt menti), a WOW_SPECS
# sorrendjében; SPEC_IDS: azonosító → (kaszt, spec).
_CLASS_SPEC_IDS = {
    "Death Knight": (250, 251, 252),
    "Demon Hunter": (577, 581, 1480),
    "Druid": (102, 103, 104, 105),
    "Evoker": (1467, 1468, 1473),
    "Hunter": (253, 254, 255),
    "Mage": (62, 63, 64),
    "Monk": (268, 270, 269),
    "Paladin": (65, 66, 70),
    "Priest": (256, 257, 258),
    "Rogue": (259, 260, 261),
    "Shaman": (262, 263, 264),
    "Warlock": (265, 266, 267),
    "Warrior": (71, 72, 73),
}
SPEC_IDS = {
    spec_id: (char_class, spec)
    for char_class, ids in _CLASS_SPEC_IDS.items()
    for spec_id, spec in zip(ids, WOW_SPECS[char_class])
}
# A fajok játékbeli, nyelvtől független nevei (pl. „NightElf”) közül azok, amelyekből a
# find_race nem ismeri fel a fajt.
RACE_FILE_NAMES = {"Scourge": "Undead", "EarthenDwarf": "Earthen"}


def _name_key(text: str) -> str:
    """Összehasonlítási kulcs: kisbetűs, csak betűk és számok („Mag’har orc” = „Mag'har Orc”)."""
    return "".join(char for char in text.casefold() if char.isalnum())


_CLASS_KEYS = {_name_key(name): name for name in WOW_CLASSES}
_RACE_KEYS = {_name_key(name): name for name in WOW_RACES}


def find_class(text: str) -> str | None:
    """A beírt kaszt játékbeli neve (kis- és nagybetűtől, szóközöktől függetlenül), vagy None."""
    return _CLASS_KEYS.get(_name_key(text))


def find_spec(char_class: str, text: str) -> str | None:
    """A beírt spec játékbeli neve az adott (már azonosított) kasztnál, vagy None."""
    key = _name_key(text)
    return next((spec for spec in WOW_SPECS.get(char_class, ()) if _name_key(spec) == key), None)


def find_race(text: str) -> str | None:
    """A beírt faj játékbeli neve, vagy None."""
    return _RACE_KEYS.get(_name_key(text))


def role_of(class_text: str, spec_text: str) -> str | None:
    """A beírt kaszt és spec szerepe (lásd character_role); None, ha nem tudható."""
    char_class = find_class(class_text)
    if char_class is None:
        return None
    return character_role(char_class, find_spec(char_class, spec_text))


def role_label(role: str) -> str:
    """A szerep kiírása nagy kezdőbetűvel: „Tank”, „Healer”, „Melee DPS”, „Ranged DPS”."""
    return role[:1].upper() + role[1:]


def character_role(char_class: str, spec: str | None) -> str | None:
    """A (már azonosított) kaszt és spec szerepe. Spec nélkül csak akkor ismert, ha a
    kaszt minden specje ugyanazt a szerepet tölti be (pl. Mage: ranged DPS, Rogue:
    melee DPS; a Hunter nem, mert a Survival melee)."""
    if spec is not None:
        return SPEC_ROLES[(char_class, spec)]
    roles = {SPEC_ROLES[(char_class, item)] for item in WOW_SPECS[char_class]}
    return roles.pop() if len(roles) == 1 else None
