#!/usr/bin/env python3
"""Value snapshot: finding the scouts on the local network (caravan/admin/scout_scan.py).

Pinned against a network that is a pair of functions: which networks a scan
takes — the controller's own /24s when none is typed, never a public one and
never more than 1024 addresses; that every address is knocked on and those
that answer are asked /api/pairing; that only a caravan-scout counts; and how
a found scout is told — free, already on this board, or held by another
controller. Nothing is changed by a scan.

Run: python3 scripts/test_scout_scan.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from caravan.admin.scout_scan import ScoutScan  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn, *args):
    try:
        fn(*args)
    except AppError as exc:
        return exc.status, str(exc)
    return None


SCOUT = {"service": "caravan-scout", "version": "2.25.1", "controllerUrl": "", "tokenRequired": False}


class Network:
    """A home network: the addresses that take a connection, and what each answers."""

    def __init__(self):
        self.open = {"10.0.30.20", "10.0.30.23", "10.0.30.24", "10.0.30.50", "10.0.30.70"}
        self.answers = {
            "10.0.30.20": {**SCOUT, "hostId": "sierra-pc", "hostname": "sierra-pc"},
            "10.0.30.23": {**SCOUT, "hostId": "alpha", "hostname": "foxtrot-pc", "controllerUrl": "https://c.example"},
            "10.0.30.24": {**SCOUT, "hostId": "bravo", "hostname": "", "controllerUrl": "http://10.0.0.9:7990"},
            "10.0.30.50": {"service": "something-else"},
        }
        self.knocked = []
        self.asked = []

    def connect(self, address, port, timeout):
        self.knocked.append((address, port))
        if address == "10.0.30.60":
            raise OSError("no route")
        return address in self.open

    def ask(self, url, timeout):
        self.asked.append(url)
        address = url.split("//", 1)[1].split(":", 1)[0]
        if address == "10.0.30.70":
            raise ValueError("not JSON")
        return self.answers[address]


def scan_with(net, known=("alpha",), own=("10.0.20.10",)):
    return ScoutScan(known=lambda: set(known), own=lambda: list(own), connect=net.connect, ask=net.ask)


def test_networks():
    print("какие сети берёт поиск:")
    scan = scan_with(Network())
    check([str(n) for n in scan.networks("")] == ["10.0.20.0/24"], "пусто — своя /24 контроллера")
    check([str(n) for n in ScoutScan(own=lambda: ["10.0.20.10", "10.0.20.7", "10.0.30.5"]).networks(None)]
          == ["10.0.20.0/24", "10.0.30.0/24"], "своих адресов несколько — их /24 без повторов")
    check([str(n) for n in scan.networks(" 10.0.30.0/24, 10.0.30.20 ; 10.0.30.0/24")]
          == ["10.0.30.0/24", "10.0.30.20/32"], "сети и адреса через запятые и пробелы, без повторов")
    for bad, why in (("8.8.8.0/24", "публичная сеть"), ("10.0.0.0/20", "больше 1024 адресов"), ("box!", "не адрес"),
                     ("127.0.0.0/24", "петля"), ("fd00::/120", "IPv6")):
        got = refused(scan.networks, bad)
        check(got is not None and got[0] == 400, f"negative: {why} — отказ 400 ({bad})")
    check(refused(ScoutScan(own=lambda: []).networks, "") is not None, "negative: ни сети, ни своего адреса — отказ, а не пустой поиск")
    check(ScoutScan.port(None) == 8092 and ScoutScan.port(" 9000 ") == 9000, "порт по умолчанию 8092, введённый — как есть")
    for port in ("0", "65536", "x"):
        check(refused(ScoutScan.port, port) is not None, f"negative: порт {port!r} — отказ")
    import ipaddress
    check(ScoutScan.addresses([ipaddress.ip_network("10.0.30.20/30"), ipaddress.ip_network("10.0.30.20/32")])
          == ["10.0.30.21", "10.0.30.22", "10.0.30.20"], "адреса сети — её узлы; /32 — сам адрес")


def test_scan():
    print("поиск:")
    net = Network()
    got = scan_with(net).scan("10.0.30.0/24")
    check((got["networks"], got["port"], got["scanned"]) == (["10.0.30.0/24"], 8092, 254),
          "ответ называет сеть, порт и сколько адресов спрошено")
    check(len(net.knocked) == 254 and all(port == 8092 for _a, port in net.knocked), "постучались в каждый адрес на порт скаута")
    check(sorted(net.asked) == sorted(f"http://{a}:8092/api/pairing" for a in net.open),
          "/api/pairing спросили только у тех, кто открыл порт")
    check(got["found"] == [
        {"address": "10.0.30.20", "port": 8092, "hostId": "sierra-pc", "name": "sierra-pc", "version": "2.25.1", "state": "free"},
        {"address": "10.0.30.23", "port": 8092, "hostId": "alpha", "name": "foxtrot-pc", "version": "2.25.1", "state": "here"},
        {"address": "10.0.30.24", "port": 8092, "hostId": "bravo", "name": "bravo", "version": "2.25.1", "state": "taken"}],
        "найдены скауты по порядку адресов: свободный, уже на доске, занятый другим контроллером")
    check(all(f["address"] not in ("10.0.30.50", "10.0.30.60", "10.0.30.70") for f in got["found"]),
          "negative: чужой сервис, недоступный адрес и ответ не JSON — не скауты")
    net = Network()
    got = scan_with(net).scan("10.0.30.20", 9000)
    check(net.knocked == [("10.0.30.20", 9000)] and got["port"] == 9000 and got["scanned"] == 1, "один адрес и свой порт")


for fn in (test_networks, test_scan):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("scout scan snapshot holds")
