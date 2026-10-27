"""Szinkronizálás a gép és a telefon között egy közös Firebase Realtime Database-en át.

A felhasználó a saját (ingyenes) Firebase-projektjét használja (a beállítását lásd a README-ben, a
„Szinkronizálás a telefonnal” résznél). E-mail-címmel és jelszóval jelentkezik be (Firebase
Authentication); az adatai helye /users/<uid>/plan, amelyet a szabályok (firebase/database.rules.json)
csak a fiók tulajdonosának engednek:

    {"rev": 12, "updated": <ezredmásodperc>, "device": "PC", "data": "<a közös adatok JSON-szövegként>"}

A közös adatok (shared_part) a terv: a beállítások, a karakterek (azonosítóval, a lista sorrendjében),
a Murlok.io-pontszámok, az előretekintés, a legutóbbi Raider.io-lekérés ideje és a gear ajánló
belépési ilvl-jei. A gépenkénti adatok (az addon mappája és mentései, a statisztikák ablakainak
mezői, a gear ajánló automatikus frissítése) nem kerülnek fel. A data szövegként áll az
adatbázisban, mert a Realtime Database kulcsaiban nem lehet „/” (a spec-kulcsokban van), és az üres
listákat, null értékeket nem tárolja.

Minden írás feltételes (ETag, if-match): ha közben a másik eszköz írt, a SyncEngine újra lekéri az
adatokat, háromutasan összefésüli őket (merge: az utolsó közös állapot, a helyi és a távoli), és úgy
írja vissza – egyik eszköz sem írja felül vakon a másik változtatásait. Ha ugyanazt a mezőt mindkét
eszközön átírták, az utoljára szinkronizáló eszközé marad.

A kérések a szabványos könyvtárral mennek (httpcompat.py), így a modul a telefonos alkalmazásban
(android/main.py) is ugyanígy működik.
"""

from __future__ import annotations

import dataclasses
import json
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpcompat
import storage
from leveling import Character, LevelingData

AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
TIMEOUT = 20  # másodperc
SHARED_VERSION = 1  # a közös adatok formátuma; ha egy újabb program újabbat írt, ez nem írja felül
ATTEMPTS = 5  # ennyiszer próbál újra írni, ha közben a másik eszköz is írt
TOKEN_MARGIN = 120  # ennyi másodperccel a lejárata előtt kér új azonosító tokent
POLL_SECONDS = 30  # ilyen gyakran nézi meg, írt-e a másik eszköz (csak a változat számát kéri le)
UID = re.compile(r"[A-Za-z0-9]{1,128}")  # a Firebase-fiókok azonosítója (az adatbázis útvonalában)

# A Firebase Authentication hibakódjai magyarul (a „WEAK_PASSWORD : ...” alakból az első rész).
AUTH_MESSAGES = {
    "EMAIL_NOT_FOUND": "Nincs fiók ezzel az e-mail-címmel.",
    "INVALID_PASSWORD": "Hibás a jelszó.",
    "INVALID_LOGIN_CREDENTIALS": "Hibás az e-mail-cím vagy a jelszó.",
    "INVALID_EMAIL": "Hibás az e-mail-cím.",
    "MISSING_PASSWORD": "Add meg a jelszót.",
    "MISSING_EMAIL": "Add meg az e-mail-címet.",
    "EMAIL_EXISTS": "Ezzel az e-mail-címmel már van fiók: jelentkezz be vele.",
    "WEAK_PASSWORD": "Túl rövid a jelszó (legalább 6 karakter kell).",
    "OPERATION_NOT_ALLOWED": "A Firebase-projektben nincs bekapcsolva az e-mail/jelszó bejelentkezés.",
    "ADMIN_ONLY_OPERATION": "A Firebase-projektben ki van kapcsolva az új fiókok létrehozása.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Túl sok próbálkozás: várj egy kicsit, és próbáld újra.",
    "USER_DISABLED": "Ez a fiók le van tiltva.",
    "USER_NOT_FOUND": "A fiók már nem létezik: jelentkezz be újra.",
    "TOKEN_EXPIRED": "Lejárt a bejelentkezés: jelentkezz be újra.",
    "INVALID_REFRESH_TOKEN": "Lejárt a bejelentkezés: jelentkezz be újra.",
    "INVALID_ID_TOKEN": "Lejárt a bejelentkezés: jelentkezz be újra.",
    "PROJECT_NUMBER_MISMATCH": "A bejelentkezés egy másik Firebase-projekthez tartozik: jelentkezz be újra.",
}


class SyncError(Exception):
    """A szinkronizálás most nem sikerült (magyar nyelvű üzenettel); később újra lehet próbálni."""


class AuthError(SyncError):
    """Be kell jelentkezni (újra), vagy a bejelentkezés adatai hibásak."""


class ChoiceNeeded(SyncError):
    """Az első szinkronizáláskor a felhőben is és ezen az eszközön is van terv: a felhasználó döntse el,
    melyik maradjon (lásd SyncEngine.sync, first)."""

    def __init__(self, remote: dict, device: str, updated: int | None):
        count = len(remote.get("characters") or [])
        source = f", utoljára a(z) „{device}” eszközről" if device else ""
        super().__init__(f"A felhőben már van egy terv ({count} karakterrel{source}).")
        self.remote, self.device, self.updated = remote, device, updated


@dataclass
class Account:
    """A Firebase-projekt adatai és a bejelentkezés (a jelszó nem, csak a hosszú lejáratú token)."""

    api_key: str = ""  # a projekt Web API-kulcsa (Project settings → General)
    database_url: str = ""  # a Realtime Database címe, perjel nélkül a végén
    email: str = ""
    uid: str = ""
    refresh_token: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.database_url)

    @property
    def signed_in(self) -> bool:
        return self.configured and bool(self.uid and self.refresh_token)

    def to_dict(self) -> dict:
        return {
            "api_key": self.api_key,
            "database_url": self.database_url,
            "email": self.email,
            "uid": self.uid,
            "refresh_token": self.refresh_token,
        }

    @classmethod
    def from_dict(cls, data) -> Account:
        data = data if isinstance(data, dict) else {}
        values = {name: data.get(name) for name in ("api_key", "database_url", "email", "uid", "refresh_token")}
        return cls(**{name: value if isinstance(value, str) else "" for name, value in values.items()})


def normalize_database_url(text: str) -> str:
    """A Realtime Database címe, ahogy a Firebase-konzolból másolható (pl.
    https://valami-default-rtdb.europe-west1.firebasedatabase.app/), perjel nélkül a végén. ValueError,
    ha nem ilyen."""
    url = text.strip().rstrip("/")
    host = url[len("https://"):]
    if not url.startswith("https://") or "." not in host or re.search(r"[\s?#/]", host):
        raise ValueError(
            "Az adatbázis címe https://-sel kezdődik, pl. https://valami-default-rtdb.europe-west1.firebasedatabase.app"
        )
    return url


def normalize_api_key(text: str) -> str:
    key = text.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", key):
        raise ValueError("A Web API-kulcs betűkből és számokból áll (általában „AIza”-val kezdődik).")
    return key


class FirebaseClient:
    """A Firebase Authentication és a Realtime Database REST felülete, annyi, amennyi a
    szinkronizáláshoz kell. A bejelentkezés adatai az account-ban vannak (a hívó menti el őket)."""

    def __init__(self, account: Account, auth_url: str = AUTH_URL, token_url: str = TOKEN_URL, session=None):
        self.account = account
        self.auth_url, self.token_url = auth_url, token_url
        self.session = session or httpcompat.Session()
        self._id_token = ""
        self._expires = 0.0

    # --- bejelentkezés

    def sign_in(self, email: str, password: str) -> None:
        self._password_auth("signInWithPassword", email, password)

    def sign_up(self, email: str, password: str) -> None:
        """Új fiók a projektben (utána be is van jelentkezve)."""
        self._password_auth("signUp", email, password)

    def sign_out(self) -> None:
        self.account.uid = self.account.refresh_token = ""
        self._id_token, self._expires = "", 0.0

    def _password_auth(self, action: str, email: str, password: str) -> None:
        if not self.account.configured:
            raise AuthError("Előbb add meg a Firebase-projekt adatait (API-kulcs, adatbázis címe).")
        response = self._call(
            "POST",
            f"{self.auth_url}:{action}",
            params={"key": self.account.api_key},
            json={"email": email.strip(), "password": password, "returnSecureToken": True},
        )
        data = self._auth_json(response)
        uid = data.get("localId")
        if not isinstance(uid, str) or not UID.fullmatch(uid) or not data.get("refreshToken"):
            raise SyncError("Váratlan válasz jött a Firebase-től.")
        self.account.email = str(data.get("email") or email.strip())
        self.account.uid = uid
        self.account.refresh_token = str(data["refreshToken"])
        self._remember(str(data.get("idToken") or ""), data.get("expiresIn"))

    def _token(self) -> str:
        """Érvényes azonosító token; ha lejárt (vagy hamarosan lejár), a hosszú lejáratú tokennel újat kér."""
        if not self.account.signed_in:
            raise AuthError("Nincs bejelentkezve.")
        if self._id_token and time.time() < self._expires - TOKEN_MARGIN:
            return self._id_token
        response = self._call(
            "POST",
            self.token_url,
            params={"key": self.account.api_key},
            data={"grant_type": "refresh_token", "refresh_token": self.account.refresh_token},
        )
        data = self._auth_json(response)
        if not data.get("id_token"):
            raise SyncError("Váratlan válasz jött a Firebase-től.")
        self.account.refresh_token = str(data.get("refresh_token") or self.account.refresh_token)
        self._remember(str(data["id_token"]), data.get("expires_in"))
        return self._id_token

    def _remember(self, token: str, expires_in) -> None:
        try:
            seconds = float(expires_in)
        except (TypeError, ValueError):
            seconds = 3600.0
        self._id_token, self._expires = token, time.time() + seconds

    def _call(self, method: str, url: str, **kwargs):
        try:
            return self.session.request(method, url, timeout=TIMEOUT, **kwargs)
        except httpcompat.RequestException as exc:
            raise SyncError(f"Nincs kapcsolat a Firebase-szel ({exc}).") from exc

    @staticmethod
    def _auth_json(response) -> dict:
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code == 200 and isinstance(data, dict):
            return data
        if response.status_code >= 500 or data is None:
            raise SyncError(f"A Firebase most nem érhető el ({response.status_code}).")
        error = data.get("error") if isinstance(data, dict) else None
        message = str(error.get("message", "")) if isinstance(error, dict) else str(error or "")
        code = message.split(":", 1)[0].strip()
        if "API key not valid" in message or code == "API_KEY_INVALID":
            raise AuthError("Hibás a Web API-kulcs.")
        raise AuthError(AUTH_MESSAGES.get(code, f"A Firebase-bejelentkezés nem sikerült ({message or response.status_code})."))

    # --- adatbázis

    def _plan_path(self) -> str:
        if not UID.fullmatch(self.account.uid):
            raise AuthError("Nincs bejelentkezve.")
        return f"users/{self.account.uid}/plan"

    def _db(self, method: str, path: str, value=None, etag: str | None = None, want_etag: bool = False):
        """(állapotkód, a hely tartalma, ETag); a 412 (közben más írt) nem hiba."""
        url = f"{self.account.database_url}/{path}.json"
        for attempt in range(2):
            headers = {}
            if want_etag:
                headers["X-Firebase-ETag"] = "true"
            if etag:
                headers["if-match"] = etag
            kwargs = {"params": {"auth": self._token()}, "headers": headers}
            if value is not None:
                kwargs["json"] = value
            response = self._call(method, url, **kwargs)
            if response.status_code == 401 and attempt == 0 and "expired" in response.text.lower():
                self._id_token = ""  # a token közben lejárt: újat kér, és még egyszer megpróbálja
                continue
            break
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        status = response.status_code
        if status in (200, 412):
            return status, body, response.headers.get("ETag") if response.headers is not None else None
        problem = body.get("error") if isinstance(body, dict) else None
        if status in (401, 403):
            if "permission" in str(problem).lower():
                raise SyncError(
                    "Az adatbázis nem engedi az írást vagy az olvasást: ellenőrizd a szabályait (lásd README)."
                )
            raise AuthError("Lejárt a bejelentkezés: jelentkezz be újra.")
        if status == 404:
            raise SyncError("Nincs ilyen adatbázis: ellenőrizd a címét.")
        raise SyncError(f"Az adatbázis hibát jelzett ({status}{': ' + str(problem) if problem else ''}).")

    def read_plan(self):
        """(a /users/<uid>/plan tartalma vagy None, ETag)."""
        _status, body, etag = self._db("GET", self._plan_path(), want_etag=True)
        return body, etag

    def read_rev(self) -> int | None:
        """A távoli adatok változatának száma (néhány bájt): ebből látszik, írt-e azóta más."""
        _status, body, _etag = self._db("GET", self._plan_path() + "/rev")
        return body if isinstance(body, int) and not isinstance(body, bool) else None

    def write_plan(self, node: dict, etag: str | None):
        """Feltételes írás: (sikerült-e, és ha nem, a hely mostani tartalma és ETagje)."""
        status, body, new_etag = self._db("PUT", self._plan_path(), value=node, etag=etag, want_etag=True)
        return status == 200, body, new_etag


# --- a közös adatok ----------------------------------------------------------------------


def shared_part(data: LevelingData) -> dict:
    """A szinkronizált adatok (a terv), JSON-ban tárolható alakban."""
    full = data.to_dict()
    return {
        "version": SHARED_VERSION,
        "settings": full["settings"],
        "characters": full["characters"],
        "spec_scores": full["spec_scores"],
        "look_ahead": full["view"]["look_ahead"],
        "raiderio_fetched_at": full["raiderio"]["fetched_at"],
        "gear_entry_min": full["gear_entry_min"],
    }


def apply_shared(data: LevelingData, shared: dict) -> LevelingData:
    """A közös adatok átvétele a data-ba, helyben: a gépenkénti adatok maradnak, és a megmaradó
    karakterek ugyanazok az objektumok (csak az adataik változnak), így a nyitott ablakok hivatkozásai
    is jók maradnak. Visszaadja a data-t. SyncError, ha a közös adatok hibásak (ekkor nem változik)."""
    full = data.to_dict()
    full["settings"] = shared["settings"]
    full["characters"] = shared["characters"]
    full["spec_scores"] = shared.get("spec_scores") or {}
    full["view"]["look_ahead"] = shared.get("look_ahead", True)
    full["raiderio"] = {"fetched_at": shared.get("raiderio_fetched_at")}
    full["gear_entry_min"] = shared.get("gear_entry_min") or {}
    try:
        new = LevelingData.from_dict(full)
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise SyncError(f"Hibás adat jött a felhőből ({exc!r}).") from exc
    existing = {character.uid: character for character in data.characters}
    characters = []
    for character in new.characters:
        old = existing.get(character.uid)
        if old is not None:
            for item in dataclasses.fields(Character):
                setattr(old, item.name, getattr(character, item.name))
            character = old
        characters.append(character)
    data.characters[:] = characters
    data.settings, data.spec_scores, data.look_ahead = new.settings, new.spec_scores, new.look_ahead
    data.raiderio_fetched_at, data.gear_entry_min = new.raiderio_fetched_at, new.gear_entry_min
    return data


def check_shared(shared) -> dict:
    """A felhőből jött közös adatok szerkezete rendben van-e (az összefésüléshez); SyncError, ha nem."""
    if not isinstance(shared, dict) or not isinstance(shared.get("settings"), dict):
        raise SyncError("A felhőben lévő adatok hibásak (nincsenek beállítások).")
    version = shared.get("version")
    if isinstance(version, int) and version > SHARED_VERSION:
        raise SyncError("A felhőbe a program egy újabb változata írt: frissítsd ezt is, és próbáld újra.")
    characters = shared.get("characters")
    if not isinstance(characters, list) or not all(
        isinstance(item, dict) and isinstance(item.get("id"), str) for item in characters
    ):
        raise SyncError("A felhőben lévő adatok hibásak (a karakterlista).")
    if len({item["id"] for item in characters}) != len(characters):
        raise SyncError("A felhőben lévő adatok hibásak (két karakternek ugyanaz az azonosítója).")
    return shared


def _pick(base, local, remote):
    """Háromutas választás egy értékre: aki változtatott, azé; ha mindkettő, a helyié (az utoljára
    szinkronizáló eszközé)."""
    if local == remote or remote == base:
        return local
    if local == base:
        return remote
    return local


def _merge_fields(base: dict, local: dict, remote: dict) -> dict:
    keys = list(local) + [key for key in remote if key not in local]
    return {key: _pick(base.get(key), local.get(key), remote.get(key)) for key in keys}


def _merge_order(base: list, local: list, remote: list, kept: set) -> list:
    """A karakterek sorrendje: ha csak az egyik eszközön rendezték át, az; ha mindkettőn, a helyi. Az
    újak a lista szerinti előzőjük után kerülnek (az eszközükön látott helyükre)."""

    def among(order, ids):
        return [uid for uid in order if uid in ids]

    old = {uid for uid in base if uid in kept}
    base_order, local_order, remote_order = among(base, old), among(local, old), among(remote, old)
    final = remote_order if local_order == base_order else local_order
    for order in (local, remote):
        for index, uid in enumerate(order):
            if uid in kept and uid not in final:
                previous = next((order[j] for j in range(index - 1, -1, -1) if order[j] in final), None)
                final.insert(0 if previous is None else final.index(previous) + 1, uid)
    return final


def _merge_characters(base: list, local: list, remote: list) -> list:
    by_base = {item["id"]: item for item in base}
    by_local = {item["id"]: item for item in local}
    by_remote = {item["id"]: item for item in remote}
    merged = {}
    for uid in list(by_local) + [uid for uid in by_remote if uid not in by_local]:
        old, mine, theirs = by_base.get(uid), by_local.get(uid), by_remote.get(uid)
        if mine is not None and theirs is not None:
            merged[uid] = _merge_fields(old or {}, mine, theirs)
        elif mine is not None:  # a másik eszközön törölték (vagy itt vették fel)
            if old is None or mine != old:
                merged[uid] = mine  # új, vagy itt közben átírták: marad
        elif old is None or theirs != old:  # itt törölték (vagy ott vették fel)
            merged[uid] = theirs
    order = _merge_order(
        [item["id"] for item in base], [item["id"] for item in local], [item["id"] for item in remote], set(merged)
    )
    return [merged[uid] for uid in order]


def _newer(local, remote):
    """A két időpont (ÉÉÉÉ-HH-NNTÓÓ:PP:MM vagy None) közül a későbbi."""
    values = [value for value in (local, remote) if isinstance(value, str)]
    return max(values) if values else None


def merge(base: dict | None, local: dict, remote: dict) -> dict:
    """A helyi és a távoli közös adatok összefésülése az utolsó közös állapothoz (base) képest: amit
    csak az egyik eszközön változtattak, az átkerül; ha ugyanazt mindkettőn, a helyi marad. A
    karakterek az azonosítójuk szerint párosulnak; a törölt karakter csak akkor tűnik el, ha a másik
    eszközön közben nem írták át."""
    base = base or {}
    merged = {
        "version": max(SHARED_VERSION, local.get("version") or 0, remote.get("version") or 0),
        "settings": _merge_fields(base.get("settings") or {}, local["settings"], remote["settings"]),
        "characters": _merge_characters(base.get("characters") or [], local["characters"], remote["characters"]),
        "look_ahead": _pick(base.get("look_ahead"), local.get("look_ahead"), remote.get("look_ahead")),
        "raiderio_fetched_at": _newer(local.get("raiderio_fetched_at"), remote.get("raiderio_fetched_at")),
        "gear_entry_min": _pick(base.get("gear_entry_min"), local.get("gear_entry_min"), remote.get("gear_entry_min")),
    }
    old, mine, theirs = base.get("spec_scores"), local.get("spec_scores"), remote.get("spec_scores")
    if mine != old and theirs != old and mine != theirs:  # mindkét eszköz lekérte közben: a frissebb marad
        mine_at, theirs_at = ((scores or {}).get("fetched_at") or "" for scores in (mine, theirs))
        merged["spec_scores"] = theirs if theirs_at > mine_at else mine
    else:
        merged["spec_scores"] = _pick(old, mine, theirs)
    return merged


# --- a szinkronizálás --------------------------------------------------------------------


@dataclass
class RemoteState:
    """Amit a legutóbb a felhőben látott: a változat száma, és melyik eszköz mikor írta."""

    rev: int
    device: str = ""
    updated: int | None = None  # ezredmásodperc (Unix-idő)


def parse_node(node) -> tuple[RemoteState, dict | None]:
    """A /users/<uid>/plan tartalma: (állapot, közös adatok vagy None, ha még nincs feltöltve)."""
    if node is None:
        return RemoteState(0), None
    if not isinstance(node, dict):
        raise SyncError("A felhőben lévő adatok hibásak.")
    rev, device, updated = node.get("rev"), node.get("device"), node.get("updated")
    state = RemoteState(
        rev if isinstance(rev, int) and not isinstance(rev, bool) else 0,
        device if isinstance(device, str) else "",
        updated if isinstance(updated, int) and not isinstance(updated, bool) else None,
    )
    text = node.get("data")
    if text is None:
        return state, None
    try:
        shared = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        shared = None
    if shared is None:
        raise SyncError("A felhőben lévő adatok hibásak (nem olvashatók).")
    return state, check_shared(shared)


def make_node(rev: int, shared: dict, device: str) -> dict:
    return {
        "rev": rev,
        "updated": {".sv": "timestamp"},  # az adatbázis saját órája szerint
        "device": device,
        "data": json.dumps(shared, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    }


@dataclass
class Base:
    """Az utolsó közös állapot: amit ez az eszköz legutóbb a felhővel egyeztetett."""

    rev: int
    data: dict

    def to_dict(self) -> dict:
        return {"rev": self.rev, "data": self.data}

    @classmethod
    def from_dict(cls, data) -> Base | None:
        if not isinstance(data, dict) or not isinstance(data.get("rev"), int):
            return None
        try:
            return cls(data["rev"], check_shared(data.get("data")))
        except SyncError:
            return None  # a sérült utolsó állapot olyan, mintha még nem szinkronizált volna


class SyncEngine:
    """A szinkronizálás menete egy eszközön. A sync() hálózatot használ, ezért egy háttérszálban fut;
    a helyi adatok pillanatképét kapja (shared_part), és visszaadja, mire kell a helyieket cserélni."""

    def __init__(self, client: FirebaseClient, base: Base | None = None, device: str = "PC"):
        self.client = client
        self.base = base
        self.device = device
        self.remote: RemoteState | None = None  # amit legutóbb a felhőben látott

    def changed_remotely(self) -> bool:
        """Írt-e azóta a felhőbe más (csak a változat számát kéri le)."""
        return self.base is None or self.client.read_rev() != self.base.rev

    def sync(self, local: dict, first: str = "ask") -> dict | None:
        """Egy szinkronizálás. Visszaadja az új közös adatokat, ha a helyieket le kell cserélni rájuk
        (a másik eszköz változtatásai miatt), vagy None-t, ha a helyiek változatlanul jók.

        first: mi legyen, ha ez az első szinkronizálás, és a felhőben is van terv: "ask" (ha itt nincs
        karakter, a felhőbeli marad, különben ChoiceNeeded), "remote" (a felhőbeli marad) vagy "local"
        (az ezen az eszközön lévő kerül fel helyette)."""
        if self.base is not None and local == self.base.data and not self.changed_remotely():
            return None
        node, etag = self.client.read_plan()
        for _attempt in range(ATTEMPTS):
            state, remote = parse_node(node)
            self.remote = state
            if remote is None:
                merged = local
            elif self.base is not None:
                merged = merge(self.base.data, local, remote)
            elif first == "remote" or (first == "ask" and not local.get("characters")):
                merged = remote
            elif first == "local":
                merged = local
            else:
                raise ChoiceNeeded(remote, state.device, state.updated)
            if merged == remote:
                self.base = Base(state.rev, remote)
                return None if merged == local else merged
            written, node, etag = self.client.write_plan(make_node(state.rev + 1, merged, self.device), etag)
            if written:
                self.base = Base(state.rev + 1, merged)
                self.remote = RemoteState(state.rev + 1, self.device, int(time.time() * 1000))
                return None if merged == local else merged
            # Közben a másik eszköz írt: a mostani tartalommal (node, etag) újra összefésüli.
        raise SyncError("A másik eszköz közben folyamatosan írt: próbáld újra.")


# --- az alkalmazások vezérlője ---------------------------------------------------------------

CHECK_MS = 200  # ilyen gyakran nézi meg a felület szála, végzett-e a háttérszál
PUSH_DELAY_MS = 2000  # egy helyi változás után ennyivel később tölt fel (a gyors egymás utániakat egyben)
NOT_CONFIGURED = "Nincs beállítva: a „Beállítás…” gombbal kapcsolható be (a Firebase-projekted adataival)."


class SyncController:
    """A szinkronizálás egy alkalmazásban – a gépen a Tk, a telefonon a Kivy felülete alatt, ugyanígy.
    A hálózati munka egy háttérszálban fut; az eredményt a felület szálán alkalmazza. Induláskor, a
    helyi változások után (kicsit késleltetve) és félpercenként szinkronizál; ha közben helyben is
    változtattak, azt is megtartja.

    database: a helyi adatbázis (ide menti a fiókot és az utolsó közös állapotot, lásd storage.py)
    device: az eszköz neve a felhőben (pl. „PC”, „Telefon”)
    get_data(): az alkalmazás adatai (LevelingData)
    on_change(): a másik eszköz változtatásai bekerültek az adatokba (a felület frissít és ment)
    on_status(szöveg, gond-e): a szinkronizálás állapota
    ask_choice(kérdés, answer): az első szinkronizáláskor, ha a felhőben is és itt is van terv; a
        felület megkérdezi, melyik maradjon, és meghívja: answer("remote"), answer("local") vagy answer(None)
    call_later(ms, függvény): a függvény futtatása a felület szálán ms ezredmásodperc múlva
    """

    def __init__(self, database, device: str, get_data, on_change, on_status, ask_choice, call_later):
        self.database = Path(database)
        self.device = device
        self.get_data, self.on_change, self.on_status = get_data, on_change, on_status
        self.ask_choice, self.call_later = ask_choice, call_later
        self.account = Account.from_dict(self._load(storage.CLOUD))
        self._client = FirebaseClient(self.account, auth_url=AUTH_URL, token_url=TOKEN_URL)
        self._engine = SyncEngine(self._client, Base.from_dict(self._load(storage.CLOUD_BASE)), device)
        self._jobs: queue.Queue = queue.Queue()
        self._results: queue.Queue = queue.Queue()
        self.busy = False  # fut egy feladat a háttérszálban
        self._again = False  # közben újabb szinkronizálást kértek
        self._generation = 0  # a késleltetett feltöltésekből csak a legutóbbi fut le
        self._blocked = False  # bejelentkezési gond: magától nem próbálkozik, amíg be nem jelentkezik újra
        self._closed = False
        self.last_sync: datetime | None = None
        self.remote: RemoteState | None = None
        self.status = ("", False)
        threading.Thread(target=self._work, name="cloud-sync", daemon=True).start()
        self._show_status()
        call_later(CHECK_MS, self._check)
        call_later(POLL_SECONDS * 1000, self._poll)
        if self.account.signed_in:
            self.sync_now(automatic=True)

    # --- a felület szálán

    def local_changed(self) -> None:
        """Helyben változtak az adatok: kicsit később feltölti őket."""
        if not self.account.signed_in or self._blocked or self._closed:
            return
        self._generation += 1
        generation = self._generation

        def push() -> None:
            if generation == self._generation:
                self.sync_now(automatic=True)

        self.call_later(PUSH_DELAY_MS, push)

    def sync_now(self, first: str = "ask", automatic: bool = False) -> None:
        """Szinkronizálás most (a háttérszálban). automatic: magától indult, nem a felhasználó kérte."""
        if self._closed or not self.account.signed_in or (automatic and self._blocked):
            if not automatic:
                self._show_status()
            return
        if self.busy:
            self._again = True
            return
        self.busy = True
        if not automatic:
            self._show_status("Szinkronizálás…")
        self._jobs.put(("sync", shared_part(self.get_data()), first))

    def sign_in(self, api_key: str, database_url: str, email: str, password: str, create: bool = False) -> None:
        """Bejelentkezés (create: új fiók létrehozása) a háttérszálban; az eredménye az állapotban
        látszik. ValueError, ha a megadott adatok formailag hibásak."""
        api_key, database_url = normalize_api_key(api_key), normalize_database_url(database_url)
        if not email.strip() or not password:
            raise ValueError("Add meg az e-mail-címet és a jelszót.")
        if self.busy:
            raise ValueError("Éppen szinkronizál: próbáld újra egy pillanat múlva.")
        self.busy = True
        self._show_status("Bejelentkezés…")
        self._jobs.put(("sign_up" if create else "sign_in", api_key, database_url, email.strip(), password))

    def sign_out(self) -> None:
        """Kijelentkezés: a szinkronizálás leáll, a helyi adatok maradnak."""
        if self.busy:
            raise ValueError("Éppen szinkronizál: próbáld újra egy pillanat múlva.")
        self._client.sign_out()
        self._engine.base = None
        self.last_sync = self.remote = None
        self._store(storage.CLOUD, self.account.to_dict())
        self._store(storage.CLOUD_BASE, None)
        self._show_status()

    def close(self) -> None:
        self._closed = True
        self._jobs.put(None)

    def _poll(self) -> None:
        if self._closed:
            return
        self.sync_now(automatic=True)
        self.call_later(POLL_SECONDS * 1000, self._poll)

    def _check(self) -> None:
        if self._closed:
            return
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                break
            self._handle(*result)
        self.call_later(CHECK_MS, self._check)

    def _handle(self, kind: str, job: tuple, *values) -> None:
        self.busy = False
        if kind == "synced":
            incoming, base, remote, account = values
            self._store(storage.CLOUD_BASE, base)
            self._store(storage.CLOUD, account)
            self.remote, self.last_sync, self._blocked = remote, datetime.now(), False
            if incoming is not None:
                sent, current = job[1], shared_part(self.get_data())
                if current != sent:  # közben itt is változtattak: azok is megmaradnak
                    incoming = merge(sent, current, incoming)
                try:
                    apply_shared(self.get_data(), incoming)
                except SyncError as exc:
                    self._show_status(str(exc), True)
                    return
                self.on_change()
            self._show_status()
        elif kind == "signed_in":
            account, reset = values
            self._store(storage.CLOUD, account)
            if reset:
                self._store(storage.CLOUD_BASE, None)
            self._blocked = False
            self.sync_now()
        elif kind == "choice":
            (problem,) = values
            self._show_status("Melyik terv maradjon? (lásd a kérdést)", True)
            question = (
                f"{problem}\n\nEzen az eszközön is van egy terv. Melyik maradjon meg? A másik helyére kerül "
                "(és onnantól a kettő együtt változik)."
            )
            self.ask_choice(question, self._answer)
        else:  # "error"
            (problem,) = values
            text = str(problem) if isinstance(problem, SyncError) else f"Váratlan hiba: {problem!r}"
            if job[0] != "sync":  # a bejelentkezés nem sikerült (a korábbi bejelentkezés maradt)
                self._show_status(f"⚠ {text}", True)
            elif isinstance(problem, AuthError):
                self._blocked = True
                self._store(storage.CLOUD, self.account.to_dict())
                self._show_status(f"⚠ {text}", True)
            else:
                self._show_status(f"⚠ {text} Fél perc múlva újra próbálja.", True)
        if self._again:
            self._again = False
            self.sync_now(automatic=True)

    def _answer(self, choice: str | None) -> None:
        if choice not in ("remote", "local"):
            self._show_status("Nem szinkronizált: döntsd el, melyik terv maradjon (Szinkronizálás most).", True)
            return
        if choice == "remote":  # az itteni terv lecserélődik: előbb félreteszi, hogy ne vesszen el
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.database.with_name(f"{self.database.stem}.elozo-terv-{stamp}.json")
            try:
                backup.write_text(json.dumps(self.get_data().to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
        self.sync_now(first=choice)

    def _show_status(self, text: str | None = None, problem: bool = False) -> None:
        if text is None:
            account = self.account
            if not account.configured:
                text = NOT_CONFIGURED
            elif not account.signed_in:
                text = "Nincs bejelentkezve: a „Beállítás…” gombbal jelentkezhetsz be."
            elif self.last_sync is None:
                text = f"Bejelentkezve: {account.email}"
            else:
                text = f"Szinkronizálva: {self.last_sync:%H:%M} · {account.email}"
                remote = self.remote
                if remote is not None and remote.device and remote.updated:
                    written = datetime.fromtimestamp(remote.updated / 1000)
                    text += f" · a felhőbe utoljára: {remote.device}, {written:%m-%d %H:%M}"
        self.status = (text, problem)
        self.on_status(text, problem)

    def _load(self, name: str):
        try:
            text = storage.read_document(self.database, name)
            return json.loads(text) if text else None
        except (OSError, ValueError):
            return None

    def _store(self, name: str, value) -> None:
        try:
            if value is not None:
                storage.write_document(self.database, name, json.dumps(value, ensure_ascii=False))
            elif self.database.exists():
                storage.delete_document(self.database, name)
        except OSError:
            pass  # a következő sikeres szinkronizáláskor újra megpróbálja

    # --- a háttérszálban

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                result = self._run(job)
            except Exception as exc:  # egy váratlan hiba se állítsa le a szálat: az állapotban látszik
                result = ("error", job, exc)
            self._results.put(result)

    def _run(self, job: tuple) -> tuple:
        kind = job[0]
        if kind == "sync":
            try:
                incoming = self._engine.sync(job[1], job[2])
            except ChoiceNeeded as exc:
                return ("choice", job, exc)
            except SyncError as exc:
                return ("error", job, exc)
            base = None if self._engine.base is None else self._engine.base.to_dict()
            return ("synced", job, incoming, base, self._engine.remote, self.account.to_dict())
        _kind, api_key, database_url, email, password = job
        saved = self.account.to_dict()
        self._client.sign_out()
        self.account.api_key, self.account.database_url = api_key, database_url
        try:
            if kind == "sign_up":
                self._client.sign_up(email, password)
            else:
                self._client.sign_in(email, password)
        except SyncError as exc:
            for name, value in saved.items():  # a korábbi bejelentkezés marad
                setattr(self.account, name, value)
            return ("error", job, exc)
        previous = (saved["uid"], saved["database_url"])
        reset = (self.account.uid, self.account.database_url) != previous  # más fiók: elölről
        if reset:
            self._engine.base = None
        return ("signed_in", job, self.account.to_dict(), reset)
