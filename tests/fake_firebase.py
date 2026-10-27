"""Egy kis Firebase-utánzat a szinkronizálás tesztjeihez (lásd test_cloud_sync.py): a Firebase
Authentication e-mail/jelszó végpontjai, és a Realtime Database REST felülete a feltételes írással
(X-Firebase-ETag, if-match, 412) és a README-ben megadott szabályokkal (mindenki csak a saját
/users/<uid> helyét olvashatja és írhatja). A válaszok formája a Firebase dokumentációja szerinti."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cloud_sync

API_KEY = "AIzaTesztKulcs-0123456789abcdef"


def etag_of(value) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


class FakeFirebase:
    def __init__(self):
        self.users = {}  # e-mail → {"password", "uid"}
        self.id_tokens = {}  # azonosító token → (uid, lejárat)
        self.refresh_tokens = {}  # hosszú lejáratú token → uid
        self.tree = {}
        self.lock = threading.RLock()
        self.log = []  # (metódus, útvonal) a tesztek ellenőrzéséhez
        self.token_seconds = 3600
        self.before_put = None  # függvény: egy PUT feldolgozása előtt fut (pl. közbeírás)
        self.unavailable = False  # minden kérésre 503
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def account(self, **values) -> cloud_sync.Account:
        return cloud_sync.Account(**{"api_key": API_KEY, "database_url": f"{self.url}/db", **values})

    def client(self, account: cloud_sync.Account | None = None) -> cloud_sync.FirebaseClient:
        return cloud_sync.FirebaseClient(
            account or self.account(), auth_url=f"{self.url}/v1/accounts", token_url=f"{self.url}/v1/token"
        )

    # --- az adatfa

    def get(self, path: str):
        node = self.tree
        for part in [part for part in path.split("/") if part]:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def set(self, path: str, value) -> None:
        parts = [part for part in path.split("/") if part]
        node = self.tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value

    def plan(self, uid: str) -> dict | None:
        return self.get(f"users/{uid}/plan")

    def shared(self, uid: str) -> dict | None:
        node = self.plan(uid)
        return None if node is None else json.loads(node["data"])

    # --- a kérések

    def _new_tokens(self, uid: str) -> tuple[str, str]:
        id_token = "id-" + secrets.token_hex(8)
        refresh_token = "rt-" + secrets.token_hex(8)
        self.id_tokens[id_token] = (uid, time.time() + self.token_seconds)
        self.refresh_tokens[refresh_token] = uid
        return id_token, refresh_token

    def expire_tokens(self) -> None:
        """Minden azonosító token lejár (a hosszú lejáratúak maradnak)."""
        with self.lock:
            self.id_tokens = {token: (uid, 0) for token, (uid, _expires) in self.id_tokens.items()}

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # csendben
                pass

            def reply(self, status: int, body, headers=None) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def auth_error(self, message: str) -> None:
                self.reply(400, {"error": {"code": 400, "message": message, "errors": [{"message": message}]}})

            def do_POST(self):
                url = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(url.query)
                fake.log.append(("POST", url.path))
                if fake.unavailable:
                    return self.reply(503, {"error": "unavailable"})
                if query.get("key") != [API_KEY]:
                    return self.auth_error("API key not valid. Please pass a valid API key.")
                with fake.lock:
                    if url.path == "/v1/token":
                        form = urllib.parse.parse_qs(self.body().decode("utf-8"))
                        uid = fake.refresh_tokens.get((form.get("refresh_token") or [""])[0])
                        if form.get("grant_type") != ["refresh_token"] or uid is None:
                            return self.auth_error("INVALID_REFRESH_TOKEN")
                        id_token, refresh_token = fake._new_tokens(uid)
                        return self.reply(200, {
                            "expires_in": str(fake.token_seconds), "token_type": "Bearer",
                            "refresh_token": refresh_token, "id_token": id_token, "user_id": uid,
                            "project_id": "123",
                        })
                    request = json.loads(self.body() or b"{}")
                    email, password = request.get("email", ""), request.get("password", "")
                    if url.path == "/v1/accounts:signUp":
                        if "@" not in email:
                            return self.auth_error("INVALID_EMAIL")
                        if email in fake.users:
                            return self.auth_error("EMAIL_EXISTS")
                        if len(password) < 6:
                            return self.auth_error("WEAK_PASSWORD : Password should be at least 6 characters")
                        fake.users[email] = {"password": password, "uid": secrets.token_hex(14)}
                    elif url.path == "/v1/accounts:signInWithPassword":
                        user = fake.users.get(email)
                        if user is None or user["password"] != password:
                            return self.auth_error("INVALID_LOGIN_CREDENTIALS")
                    else:
                        return self.reply(404, {"error": {"code": 404, "message": "Not Found"}})
                    uid = fake.users[email]["uid"]
                    id_token, refresh_token = fake._new_tokens(uid)
                    return self.reply(200, {
                        "idToken": id_token, "email": email, "refreshToken": refresh_token,
                        "expiresIn": str(fake.token_seconds), "localId": uid,
                    })

            def database(self, method: str) -> None:
                url = urllib.parse.urlsplit(self.path)
                fake.log.append((method, url.path))
                if fake.unavailable:
                    return self.reply(503, {"error": "unavailable"})
                if not url.path.startswith("/db/") or not url.path.endswith(".json"):
                    return self.reply(404, {"error": "Firebase error. Please ensure that you spelled the name of your Firebase correctly"})
                path = url.path[len("/db/"):-len(".json")]
                token = (urllib.parse.parse_qs(url.query).get("auth") or [""])[0]
                with fake.lock:
                    if token not in fake.id_tokens:
                        return self.reply(401, {"error": "Could not parse auth token."})
                    uid, expires = fake.id_tokens[token]
                    if time.time() >= expires:
                        return self.reply(401, {"error": "Auth token is expired"})
                    parts = path.split("/")
                    if len(parts) < 2 or parts[0] != "users" or parts[1] != uid:  # a szabályok
                        return self.reply(401, {"error": "Permission denied"})
                    if method == "PUT":
                        data = self.body()
                        if fake.before_put is not None:
                            hook, fake.before_put = fake.before_put, None
                            hook()
                        current = fake.get(path)
                        expected = self.headers.get("if-match")
                        if expected is not None and expected != etag_of(current):
                            return self.reply(412, current, {"ETag": etag_of(current)})
                        value = json.loads(data)
                        if isinstance(value, dict):
                            value = {
                                key: int(time.time() * 1000) if item == {".sv": "timestamp"} else item
                                for key, item in value.items()
                            }
                        fake.set(path, value)
                        return self.reply(200, value)
                    value = fake.get(path)
                    headers = {"ETag": etag_of(value)} if self.headers.get("X-Firebase-ETag") == "true" else {}
                    return self.reply(200, value, headers)

            def do_GET(self):
                self.database("GET")

            def do_PUT(self):
                self.database("PUT")

        return Handler
