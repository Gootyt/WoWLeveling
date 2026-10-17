"""A requests csomag annyi része, amennyit a beépített statisztikai programok
(raiderio_ilvl_stats.py, wcl_raid_ilvl_stats.py) használnak, a szabványos könyvtár
urllib moduljával – így a program a requests telepítése nélkül is működik. Ha a
requests telepítve van, a statisztikai programok azt használják.

Amit tud: Session (headers, get, post), get, post; params (a lekérdezésbe), data
(űrlap), json (JSON törzs), auth (felhasználó, jelszó: Basic), timeout. A válasznak
van status_code, headers, text, json() és raise_for_status(). A 4xx/5xx válasz nem
kivétel (mint a requests-nél sem), csak a raise_for_status() dob HTTPError-t; a
hálózati hiba és az időtúllépés ConnectionError, illetve Timeout.
"""

from __future__ import annotations

import base64
import json as _json
import socket
import urllib.error
import urllib.parse
import urllib.request


class RequestException(OSError):
    """Hiba a kérés közben (mint a requests.RequestException)."""

    def __init__(self, *args, response=None):
        super().__init__(*args)
        self.response = response


class ConnectionError(RequestException):  # a requests is így hívja
    pass


class Timeout(RequestException):
    pass


class HTTPError(RequestException):
    pass


class exceptions:  # requests.exceptions.RequestException stb.
    RequestException = RequestException
    ConnectionError = ConnectionError
    Timeout = Timeout
    HTTPError = HTTPError


class Response:
    def __init__(self, url, status_code, headers, content):
        self.url = url
        self.status_code = status_code
        self.headers = headers  # http.client.HTTPMessage: a fejlécnevek kis- és nagybetűtől függetlenek
        self.content = content

    @property
    def text(self) -> str:
        charset = self.headers.get_content_charset() if self.headers is not None else None
        return self.content.decode(charset or "utf-8", errors="replace")

    def json(self):
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} Error for url: {self.url}", response=self)


class Session:
    def __init__(self):
        self.headers = {}

    def request(self, method, url, params=None, data=None, json=None, headers=None, auth=None, timeout=None):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        all_headers = {**self.headers, **(headers or {})}
        body = None
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            all_headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8") if isinstance(data, dict) else data
            all_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        if auth is not None:
            token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
            all_headers["Authorization"] = f"Basic {token}"
        request = urllib.request.Request(url, data=body, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return Response(response.geturl(), response.status, response.headers, response.read())
        except urllib.error.HTTPError as exc:  # a 4xx/5xx is válasz, nem kivétel
            try:
                content = exc.read()
            except (AttributeError, OSError, ValueError):
                content = b""
            return Response(url, exc.code, exc.headers, content)
        except (socket.timeout, TimeoutError) as exc:
            raise Timeout(str(exc)) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise Timeout(str(exc.reason)) from exc
            raise ConnectionError(str(exc.reason)) from exc
        except OSError as exc:  # pl. megszakadt kapcsolat
            raise ConnectionError(str(exc)) from exc

    def get(self, url, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def get(url, **kwargs) -> Response:
    return Session().get(url, **kwargs)


def post(url, **kwargs) -> Response:
    return Session().post(url, **kwargs)
