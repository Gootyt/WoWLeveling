"""Specenkénti Mythic+ pontszámok lekérése a Murlok.io rangsoraiból.

A Murlok.io a Blizzard Battle.net API adataiból 8 óránként frissülő
rangsorokat közöl a tank, healer és DPS specekről
(https://murlok.io/meta/<szerep>/m+). Minden spec mellett egy pontszám áll;
ezt jeleníti meg a program a karakterek listájában.

Csak ezt a három nyilvános oldalt kéri le, személyes adatot nem küld.

Az oldalakon minden spec egy ilyen elem (az attribútumok sorrendje változhat):

    <a class="… meta-item …" href="/death-knight/unholy/m+">
      <div class="h3">13</div> … <div class="h3">Unholy Death Knight</div> …
      <li class="vi-media-object …"><svg>…</svg> 3891 </li> …
    </a>
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from leveling import SpecScores

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


_SPEC_PATH = re.compile(r"/([a-z0-9-]+)/([a-z0-9-]+)/m\+")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class _MetaPageParser(HTMLParser):
    """Kigyűjti a rangsor elemeiből a spec azonosítóját és pontszámát."""

    def __init__(self) -> None:
        super().__init__()
        self.scores: dict[str, Decimal] = {}
        self._spec: str | None = None  # a feldolgozás alatt álló rangsorelem specje
        self._score_text: list[str] | None = None  # a pontszámot tartalmazó <li> szövege

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "a" and "meta-item" in classes:
            path = urllib.parse.urlparse(attributes.get("href") or "").path
            match = _SPEC_PATH.fullmatch(path)
            if match:
                class_slug, spec_slug = match.groups()
                self._spec = SpecScores.spec_key(class_slug.replace("-", " "), spec_slug.replace("-", " "))
        elif tag == "li" and "vi-media-object" in classes and self._spec and self._spec not in self.scores:
            self._score_text = []

    def handle_data(self, data: str) -> None:
        if self._score_text is not None:
            self._score_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._score_text is not None:
            text = "".join(self._score_text).strip()
            self._score_text = None
            if _NUMBER.fullmatch(text):
                try:
                    self.scores[self._spec] = Decimal(text.replace(",", ""))
                except InvalidOperation:
                    pass
        elif tag == "a":
            self._spec = None
            self._score_text = None


def parse_meta_page(html: str) -> dict[str, Decimal]:
    """Egy rangsoroldal spec-pontszámai; kulcs: SpecScores.spec_key(kaszt, spec)."""
    parser = _MetaPageParser()
    parser.feed(html)
    parser.close()
    return parser.scores


def fetch_spec_scores() -> dict[str, Decimal]:
    """Mindhárom szerep (tank, healer, DPS) rangsorának lekérése és összefésülése."""
    scores: dict[str, Decimal] = {}
    for role in ROLES:
        page_scores = parse_meta_page(fetch_page(meta_url(role)))
        if not page_scores:  # valószínűleg megváltozott az oldal felépítése
            raise MurlokError(f"a Murlok.io {role} rangsorában nem találtam pontszámokat.")
        scores.update(page_scores)
    return scores
