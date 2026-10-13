#!/usr/bin/env python3
"""Value snapshot: who sent a request (caravan/common/client_address.py).

On the NAS every request comes through the DSM's nginx, which connects from
127.0.0.1 and names the sender in X-Forwarded-For (appended) and X-Real-IP.
The journal and the sign-in lock read the sender from here: behind the proxy,
the address it names; anywhere else, the peer — a sender on the network could
write any address into a header.

Run: python3 scripts/test_client_address.py
"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CARAVAN_DATA_DIR", tempfile.mkdtemp(prefix="caravan-client-address-"))

from caravan.common.client_address import ClientAddress  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


XFF, REAL = ClientAddress.FORWARDED, ClientAddress.REAL_IP

CASES = [
    # (peer, headers, sender, why)
    ("127.0.0.1", {XFF: "192.0.2.44"}, "192.0.2.44", "за прокси на этой машине — адрес, который прокси назвал"),
    ("127.0.0.1", {XFF: "198.51.100.7, 192.0.2.44"}, "192.0.2.44",
     "в цепочке — последний адрес: его дописал прокси, а что до него — написал сам отправитель"),
    ("127.0.0.1", {REAL: "192.0.2.44"}, "192.0.2.44", "без X-Forwarded-For — X-Real-IP"),
    ("127.0.0.1", {XFF: "192.0.2.44", REAL: "203.0.113.1"}, "192.0.2.44", "X-Forwarded-For важнее X-Real-IP"),
    ("::1", {XFF: "192.0.2.44"}, "192.0.2.44", "петля IPv6 — тоже прокси на этой машине"),
    ("::ffff:127.0.0.1", {XFF: "192.0.2.44"}, "192.0.2.44", "петля IPv4 в записи IPv6 — тоже"),
    ("127.0.0.2", {XFF: "192.0.2.44"}, "192.0.2.44", "вся сеть 127/8 — петля"),
    ("127.0.0.1", {XFF: "2001:DB8::5"}, "2001:db8::5", "адрес IPv6 — в обычной записи"),
    ("10.0.30.77", {XFF: "192.0.2.44", REAL: "192.0.2.45"}, "10.0.30.77",
     "negative: отправитель из сети сам пишет заголовки — ему не верим, адрес соединения"),
    ("127.0.0.1", {XFF: "unknown"}, "127.0.0.1", "negative: не адрес — адрес соединения"),
    ("127.0.0.1", {XFF: "192.0.2.44, unknown"}, "127.0.0.1",
     "negative: последний в цепочке не адрес — не берём адрес раньше него, его писал отправитель"),
    ("127.0.0.1", {}, "127.0.0.1", "negative: прокси никого не назвал — адрес соединения"),
    ("127.0.0.1", None, "127.0.0.1", "negative: заголовков нет вовсе — адрес соединения"),
    ("", {XFF: "192.0.2.44"}, "", "negative: соединения нет — и отправителя нет, не догадка из заголовка"),
]


def test_cases():
    print("кто прислал запрос:")
    for peer, headers, sender, why in CASES:
        got = ClientAddress.of(peer, headers)
        check(got == sender, f"{why} (соединение {peer or '—'} → {got!r})")


def test_local():
    print("кто стоит перед караваном на этой машине:")
    check([ClientAddress.is_local(p) for p in ("127.0.0.1", "::1", "::ffff:127.0.0.1")] == [True, True, True],
          "петля IPv4, IPv6 и IPv4 в записи IPv6 — эта машина")
    check([ClientAddress.is_local(p) for p in ("10.0.30.20", "10.0.0.1", "", "localhost", None)] == [False] * 5,
          "negative: адрес сети, пусто и имя вместо адреса — не эта машина")


class SignInDesk:
    """The admin's sign-in door with its two collaborators replaced: what address do they get?"""

    def __init__(self):
        from caravan.admin import routes
        self.routes = routes
        self.seen = []

    def sign_in(self, peer, headers):
        auth = self.routes.auth_mod
        saved = auth.verify_login, auth.create_session
        auth.verify_login = lambda name, password, ip="": (self.seen.append(("verify", ip)), {"id": 1, "username": name})[1]
        auth.create_session = lambda user_id, ip="", ua="": (self.seen.append(("session", ip)), "token")[1]
        handler = type("H", (), {"client_address": (peer, 50000), "headers": headers, "wfile": io.BytesIO(),
                                 "send_response": lambda self, code: None, "send_header": lambda self, k, v: None,
                                 "end_headers": lambda self: None})()
        try:
            self.routes._post_auth_login(handler, None, {"username": "u", "password": "p"})
        finally:
            auth.verify_login, auth.create_session = saved
        got, self.seen = self.seen, []
        return got


def test_sign_in():
    print("вход в админку (замок после неверных паролей держится по адресу):")
    desk = SignInDesk()
    check(desk.sign_in("127.0.0.1", {XFF: "192.0.2.44", "User-Agent": "x"}) == [("verify", "192.0.2.44"), ("session", "192.0.2.44")],
          "за прокси DSM замок и сессия получают адрес того, кто входит, — не общий 127.0.0.1")
    check(desk.sign_in("10.0.30.77", {XFF: "192.0.2.44"}) == [("verify", "10.0.30.77"), ("session", "10.0.30.77")],
          "negative: вход прямо из сети — адрес соединения, заголовку не верим")


for fn in (test_cases, test_local, test_sign_in):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("client address snapshot holds")
