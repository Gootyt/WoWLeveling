"""Javaslat új karakterre: melyik class/spec/faj combó hiányzik leginkább a listáról.

A meglévő karaktereket öt szempont szerint vizsgálja, ebben a sorrendben: szerep
(tank, healer, melee DPS, ranged DPS), páncéltípus (cloth, leather, mail, plate),
kaszt, spec és faj. A választott frakcióban létrehozható combók közül az a legjobb,
amelyik az első szempont szerint hiányzik leginkább; ha ebben több is egyforma, az,
amelyik a második szerint, és így tovább.

* A szerepnél és a páncéltípusnál nem az egyforma darabszám a cél, hanem az az arány,
  ahogy a frakció összes class/spec/faj combója között előfordulnak (pl. a Horde
  combóinak kb. 12%-a tank). Az jön előbb, amelyik ettől a legjobban elmarad: ahol a
  meglévő karakterek száma a legkisebb ahhoz képest, amennyi az arány szerint egy újabb
  karakterrel együtt járna neki. (Így a karakterek eloszlása lépésről lépésre a
  legközelebb marad az arányokhoz.)
* A kasztnál, a specnél és a fajnál az jön előbb, amelyikből a legkevesebb van.

Ha minden szempont szerint egyformák, a magasabb Murlok.io-pontszámú class/spec jön
előbb, végül a kasztok ábécérendje és a fajok karakterkészítőbeli sorrendje dönt (az
alapfajok a szövetséges fajok előtt).

A felismerhetetlen (kézzel beírt) kasztot, specet vagy fajt a számolás kihagyja; spec
nélkül a szerep csak akkor számít, ha a kaszt minden specje ugyanazt a szerepet tölti
be (pl. Mage: ranged DPS).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from leveling import Character, SpecScores, format_compact
from wow_data import (
    CLASS_ARMOR,
    FACTION_RACES,
    RACE_CLASSES,
    SPEC_ROLES,
    WOW_CLASSES,
    WOW_SPECS,
    character_role,
    find_class,
    find_race,
    find_spec,
)

ASPECTS = ("szerep", "páncéltípus", "kaszt", "spec", "faj")  # a szempontok, a vizsgálat sorrendjében
PROPORTIONAL = 2  # az első két szempont (szerep, páncéltípus) a combók közti arányához igazodik


@dataclass(frozen=True)
class Combo:
    """Egy létrehozható class/spec/faj combó."""

    race: str
    char_class: str
    spec: str
    role: str
    armor: str
    counts: tuple[int, ...]  # hány meglévő karakter egyezik vele az egyes szempontok (ASPECTS) szerint
    spec_score: Decimal | None  # a class/spec Murlok.io-pontszáma, ha van
    # A rangsor alapja (kisebb: jobban hiányzik): a szerepnél és a páncéltípusnál a meglévő
    # karakterek száma mínusz amennyi az arány szerint egy újabbal együtt járna, utána a
    # kaszt, a spec és a faj darabszáma.
    balance: tuple = ()

    @property
    def name(self) -> str:
        """Pl. „Tauren Holy Paladin”."""
        return f"{self.race} {self.spec} {self.char_class}"

    @property
    def aspect_values(self) -> tuple[str, ...]:
        """A combó értékei az egyes szempontok szerint, pl. („healer”, „plate”, „Paladin”, …)."""
        return (self.role, self.armor, self.char_class, f"{self.spec} {self.char_class}", self.race)


def _percent(share: Fraction) -> str:
    """Arány egész százalékra kerekítve, pl. „37%”."""
    return f"{int(share * 100 + Fraction(1, 2))}%"


@dataclass(frozen=True)
class Recommendation:
    """Az ajánlott combó, a hozzá tartozó magyarázattal."""

    faction: str
    best: Combo
    alternatives: tuple[Combo, ...]  # a következő legjobb combók, más-más class/spec
    tied: int  # hány másik class/spec hiányzik ugyanennyire (ezek közül a Murlok.io-pontszám döntött)
    character_count: int
    has_scores: bool  # vannak-e Murlok.io-pontszámok
    shares: tuple[Fraction, Fraction] = (Fraction(0), Fraction(0))  # a javasolt szerep és páncéltípus aránya
    known: tuple[int, int] = (0, 0)  # hány meglévő karakternek ismert a szerepe, illetve a páncéltípusa

    def describe(self) -> str:
        best = self.best
        if self.character_count:
            lines = [
                f"A meglévő {self.character_count} karakter alapján ez hiányzik leginkább (sorban a szerep, "
                "a páncéltípus, a kaszt, a spec és a faj szerint). A szerepet és a páncéltípust ahhoz méri, "
                f"hogy az összes {self.faction} combó hány százaléka ilyen:"
            ]
        else:
            lines = [
                "Még nincs karakter a listán, ezért az a szerep és páncéltípus az első, amelyik az összes "
                f"{self.faction} combó között a leggyakoribb:"
            ]
        for index, (aspect, value, count) in enumerate(zip(ASPECTS, best.aspect_values, best.counts)):
            have = f"{count} karakter" if count else "még egy sincs"
            if index < PROPORTIONAL:
                if self.known[index]:
                    have += f" ({_percent(Fraction(count, self.known[index]))})"
                have += f"; az összes combó {_percent(self.shares[index])}-a"
            lines.append(f"• {aspect} – {value}: {have}")
        score = None if best.spec_score is None else format_compact(best.spec_score)
        if self.tied:
            same = f"Ugyanennyire hiányzik még {self.tied} másik class/spec is"
            if score is not None:
                lines.append(f"{same}; közülük ennek a legmagasabb a Murlok.io-pontszáma ({score}).")
            elif self.has_scores:
                lines.append(
                    f"{same}; Murlok.io-pontszám egyiküknél sincs, így a kasztok ábécérendje döntött."
                )
            else:
                lines.append(
                    f"{same}. Murlok.io-pontszámok még nincsenek (a karakterlistában kérheted le őket), "
                    "így a kasztok ábécérendje döntött."
                )
        elif score is not None:
            lines.append(f"Murlok.io-pontszám: {score}.")
        if self.alternatives:
            names = ", ".join(combo.name for combo in self.alternatives)
            lines.append(f"\nUtána következnének: {names}.")
        return "\n".join(lines)


def combo_shares(faction: str) -> tuple[dict[str, Fraction], dict[str, Fraction]]:
    """A szerepek és a páncéltípusok aránya a frakció összes class/spec/faj combója között."""
    if faction not in FACTION_RACES:
        raise ValueError(f"Ismeretlen frakció: {faction}")
    roles, armors = Counter(), Counter()
    for race in FACTION_RACES[faction]:
        for char_class in RACE_CLASSES[race]:
            for spec in WOW_SPECS[char_class]:
                roles[SPEC_ROLES[(char_class, spec)]] += 1
                armors[CLASS_ARMOR[char_class]] += 1
    total = sum(roles.values())
    return (
        {role: Fraction(count, total) for role, count in roles.items()},
        {armor: Fraction(count, total) for armor, count in armors.items()},
    )


def _aspect_values(character: Character) -> tuple:
    """Egy meglévő karakter értékei az egyes szempontok szerint (None: nem ismert)."""
    char_class = find_class(character.char_class)
    spec = find_spec(char_class, character.spec) if char_class else None
    return (
        character_role(char_class, spec) if char_class else None,
        CLASS_ARMOR[char_class] if char_class else None,
        char_class,
        (char_class, spec) if spec else None,
        find_race(character.race),
    )


def _count_aspects(characters: list[Character]) -> list[Counter]:
    """Szempontonként hány meglévő karakternek melyik az értéke."""
    counters = [Counter() for _ in ASPECTS]
    for character in characters:
        for counter, value in zip(counters, _aspect_values(character)):
            if value is not None:
                counter[value] += 1
    return counters


def ranked_combos(characters: list[Character], spec_scores: SpecScores, faction: str) -> list[Combo]:
    """A frakcióban létrehozható összes combó, a legjobb javaslattal kezdve (lásd a modul leírását)."""
    shares = combo_shares(faction)
    counters = _count_aspects(characters)
    # Az arányos szempontoknál: az ismert értékű karakterek száma, az újjal együtt.
    slots = [sum(counter.values()) + 1 for counter in counters[:PROPORTIONAL]]

    ranked = []
    for race_index, race in enumerate(FACTION_RACES[faction]):
        for char_class in RACE_CLASSES[race]:
            for spec_index, spec in enumerate(WOW_SPECS[char_class]):
                role, armor = SPEC_ROLES[(char_class, spec)], CLASS_ARMOR[char_class]
                values = (role, armor, char_class, (char_class, spec), race)
                counts = tuple(counter[value] for counter, value in zip(counters, values))
                balance = tuple(
                    counts[index] - shares[index][values[index]] * slots[index] for index in range(PROPORTIONAL)
                ) + counts[PROPORTIONAL:]
                score = spec_scores.scores.get(SpecScores.spec_key(char_class, spec))
                key = (
                    balance,
                    score is None,  # a pontszám nélküliek a végére
                    -(score or Decimal(0)),
                    WOW_CLASSES.index(char_class),
                    spec_index,
                    race_index,
                )
                ranked.append((key, Combo(race, char_class, spec, role, armor, counts, score, balance)))
    ranked.sort(key=lambda item: item[0])
    return [combo for _, combo in ranked]


def recommend_combo(
    characters: list[Character], spec_scores: SpecScores, faction: str, alternatives: int = 3
) -> Recommendation:
    """A választott frakcióban leginkább hiányzó class/spec/faj combó, és utána a következő
    `alternatives` darab, más-más class/spec (mindegyik a hozzá legjobb fajjal)."""
    ranked = ranked_combos(characters, spec_scores, faction)
    best = ranked[0]
    seen = {(best.char_class, best.spec)}
    tied = {(combo.char_class, combo.spec) for combo in ranked if combo.balance == best.balance} - seen
    others = []
    for combo in ranked:
        if len(others) == alternatives:
            break
        if (combo.char_class, combo.spec) not in seen:
            seen.add((combo.char_class, combo.spec))
            others.append(combo)
    role_shares, armor_shares = combo_shares(faction)
    counters = _count_aspects(characters)
    return Recommendation(
        faction=faction,
        best=best,
        alternatives=tuple(others),
        tied=len(tied),
        character_count=len(characters),
        has_scores=bool(spec_scores.scores),
        shares=(role_shares[best.role], armor_shares[best.armor]),
        known=(sum(counters[0].values()), sum(counters[1].values())),
    )
