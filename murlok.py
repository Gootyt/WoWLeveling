"""Specenkénti Mythic+ pontszámok lekérése a Murlok.io rangsoraiból.

A Murlok.io a Blizzard Battle.net API adataiból 8 óránként frissülő
rangsorokat közöl a tank, healer és DPS specekről
(https://murlok.io/meta/<szerep>/m+). Minden spec mellett egy pontszám áll;
ezt jeleníti meg a program a karakterek listájában.

Csak ezt a három nyilvános oldalt kéri le, személyes adatot nem küld.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from decimal import Decimal

BASE_URL = "https://murlok.io"
ROLES = ("tank", "healer", "dps")
TIMEOUT = 20  # másodperc
USER_AGENT = "WoWLeveling-szintezes-tervezo (Python urllib)"


class MurlokError(Exception):
    """A lekérés vagy az oldal feldolgozása nem sikerült (magyar nyelvű üzenettel)."""


def meta_url(role: str) -> str:
    return f"{BASE_URL}/meta/{role}/m+"


def fetch_page(url: str, timeout: float = TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise MurlokError(f"a Murlok.io hibával válaszolt ({exc.code}).") from exc
    except OSError as exc:  # URLError, időtúllépés, hálózati hiba
        raise MurlokError(f"a Murlok.io nem érhető el ({getattr(exc, 'reason', exc)}).") from exc


def parse_meta_page(html: str) -> dict[str, Decimal]:
    """Egy rangsoroldal spec-pontszámai; kulcs: SpecScores.spec_key(kaszt, spec)."""
    # Az oldal feldolgozása a valódi Murlok.io-oldal szerkezetének ismeretében készül el.
    raise MurlokError("a Murlok.io-oldal feldolgozása még nem készült el.")


def fetch_spec_scores() -> dict[str, Decimal]:
    """Mindhárom szerep (tank, healer, DPS) rangsorának lekérése és összefésülése."""
    scores: dict[str, Decimal] = {}
    for role in ROLES:
        scores.update(parse_meta_page(fetch_page(meta_url(role))))
    if not scores:
        raise MurlokError("a Murlok.io oldalain nem találtam spec-pontszámokat.")
    return scores
