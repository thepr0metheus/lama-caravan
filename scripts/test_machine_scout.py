#!/usr/bin/env python3
"""Value snapshot: the controller's own machine is asked through its scout
(caravan/admin/machine_scout.py) — which scout, what crosses the wire, what a
missing or silent scout answers, and how its answers become the readings the
board already draws.

A real HTTP server on 127.0.0.1 plays the scout, so what is pinned is what is
sent — method, path, token header, body — not a call into a fake object. The
machine's name and the clock are parameters; the token is a test value.

Run: python3 scripts/test_machine_scout.py
"""
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import gpu_driver, host_power, monitoring  # noqa: E402
from caravan.admin.controller_machine import ControllerMachine  # noqa: E402
from caravan.admin.machine_scout import MachineScout  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


TOKEN = {"X-Caravan-Token": "test-token"}


class FakeScout:
    """A scout on 127.0.0.1: answers from `self.answers` by path, records each request."""

    def __init__(self):
        self.answers = {}
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else None
                outer.requests.append({"method": method, "path": self.path, "body": body,
                                       "token": self.headers.get("X-Caravan-Token")})
                status, payload = outer.answers.get(self.path.split("?", 1)[0],
                                                    (404, {"error": f"not found: {self.path}"}))
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                self._answer("GET")

            def do_POST(self):  # noqa: N802
                self._answer("POST")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def asked(self, path):
        return [r for r in self.requests if r["path"].split("?", 1)[0] == path]


class Topology:
    def __init__(self, hosts):
        self._hosts = hosts

    def hosts(self):
        return self._hosts


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def closed_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


SCOUT = FakeScout()


def machine(here="own-box", url=None, clock=None, **record):
    """A MachineScout on a fleet of two machines; the controller runs on `here`.
    `record` adds to the own machine's host record (its scout's last report)."""
    topo = Topology({"box-a": {"id": "box-a", "hostname": "box-a", "agentUrl": "http://127.0.0.1:9",
                               "gpus": [{"index": "0", "name": "Other card"}]},
                     "own-box": {"id": "own-box", "hostname": "Own-Box.lan", "agentUrl": url or SCOUT.url,
                                 **record}})
    return MachineScout(topology=topo, headers=dict(TOKEN), controller=ControllerMachine(here),
                        clock=clock or Clock()), topo


def test_which_scout():
    print("какой скаут — скаут машины контроллера:")
    ms, _ = machine()
    check(ms.host_id() == "own-box", "скаут найден по имени машины: регистр и домен не мешают")
    SCOUT.requests.clear()
    lonely, _ = machine(here="elsewhere")
    check(lonely.host_id() == "", "negative: машина без скаута — пустой id, а не первый попавшийся скаут")
    check(lonely.read("/api/host/processes") == {"ok": False, "error": MachineScout.NO_SCOUT},
          "чтение без скаута — «скаута нет» и что делать")
    try:
        lonely.post("/api/host/driver/install", {"package": "nvidia-driver-610-open"})
        got = None
    except AppError as exc:
        got = (exc.status, str(exc))
    check(got == (409, MachineScout.NO_SCOUT), f"действие без скаута — 409 с той же причиной (got {got})")
    check(SCOUT.requests == [], "ни один запрос не ушёл чужому скауту")


def test_forwarding():
    print("что уходит скауту:")
    ms, _ = machine()
    SCOUT.requests.clear()
    SCOUT.answers["/api/host/processes"] = (200, {"ok": True, "processes": [{"pid": 7, "name": "llama-server"}]})
    got = ms.read("/api/host/processes")
    check(got == {"ok": True, "processes": [{"pid": 7, "name": "llama-server"}]}, "ответ скаута — как есть")
    req = SCOUT.requests[-1]
    check((req["method"], req["path"], req["token"]) == ("GET", "/api/host/processes", "test-token"),
          f"GET на его путь, с токеном флота (got {req['method']} {req['path']} {req['token']!r})")
    SCOUT.answers["/api/host/driver/install"] = (200, {"running": True, "tag": "driver:nvidia-driver-610-open"})
    got = ms.post("/api/host/driver/install", {"package": "nvidia-driver-610-open"})
    req = SCOUT.requests[-1]
    check((req["method"], req["body"], req["token"]) == ("POST", {"package": "nvidia-driver-610-open"}, "test-token"),
          f"POST с телом и токеном (got {req})")
    check(got.get("tag") == "driver:nvidia-driver-610-open", "и ответ — его задание")
    SCOUT.answers["/api/host/driver/install"] = (409, {"error": "a driver install is already running"})
    try:
        ms.post("/api/host/driver/install", {"package": "nvidia-driver-610-open"})
        got = None
    except AppError as exc:
        got = (exc.status, str(exc))
    check(got == (502, "own-box: a driver install is already running"),
          f"отказ скаута — его словами и с именем машины (got {got})")


def test_failure_pause():
    print("пауза после отказа — по пути:")
    clock = Clock()
    ms, _ = machine(clock=clock)
    SCOUT.requests.clear()
    SCOUT.answers.pop("/api/monitor/btop", None)
    first = ms.read("/api/monitor/btop")
    check(first.get("ok") is False and first.get("error", "").startswith("own-box: not found"),
          f"старый скаут без пути — его отказ (got {first})")
    clock.now += 5
    again = ms.read("/api/monitor/btop")
    check(again == first and len(SCOUT.asked("/api/monitor/btop")) == 1,
          "через 5 с тот же ответ, а скаута не спрашивают: монитор читает каждую секунду")
    SCOUT.answers["/api/host/processes"] = (200, {"ok": True, "processes": []})
    check(ms.read("/api/host/processes").get("ok") is True, "negative: другой путь того же скаута спрашивается")
    SCOUT.answers.pop("/api/telemetry", None)
    ms.read("/api/telemetry?since=1")
    ms.read("/api/telemetry?since=2")
    check(len(SCOUT.asked("/api/telemetry")) == 1, "путь — без строки запроса: другое since той же паузы не обходит")
    clock.now += 5.1
    SCOUT.answers["/api/monitor/btop"] = (200, {"ok": True, "frame": "x"})
    check(ms.read("/api/monitor/btop").get("ok") is True and len(SCOUT.asked("/api/monitor/btop")) == 2,
          f"через {MachineScout.FAIL_PAUSE:g} с спрашивают снова — и ответ принят")
    ms.read("/api/monitor/btop")
    check(len(SCOUT.asked("/api/monitor/btop")) == 3, "удача снимает паузу: следующий раз спрашивают сразу")
    dead, _ = machine(url=f"http://127.0.0.1:{closed_port()}", clock=clock)
    got = dead.read("/api/host/processes", timeout=2)
    check(got.get("ok") is False and got.get("error", "").startswith("own-box unreachable"),
          f"скаут не отвечает — «недоступен», а не пустой список (got {got})")


def test_readings():
    print("показания машины из ответов скаута:")
    ms, _ = machine()
    monitoring.machine_scout = ms
    first = {"index": 0, "memUsedMiB": 100.0, "memTotalMiB": 24576.0, "utilPct": 5.0, "powerW": 30.0, "tempC": 40.0}
    last = {"index": 0, "memUsedMiB": 8000.0, "memTotalMiB": 24576.0, "utilPct": 37.0, "powerW": 212.5, "tempC": 61.0}
    SCOUT.answers["/api/telemetry"] = (200, {"ok": True, "samples": [{"t": 1, "gpus": [first]}, {"t": 2, "gpus": [last]}]})
    SCOUT.requests.clear()
    got = monitoring.gpu_sample()
    check(got == {"ok": True, "utilPct": 37.0, "memoryUsedMiB": 8000.0, "memoryTotalMiB": 24576.0, "memoryPct": 32.6,
                  "temperatureC": 61.0, "powerW": 212.5},
          f"карта — из ПОСЛЕДНЕГО замера, в именах, которые рисует доска (got {got})")
    check(SCOUT.requests[-1]["path"].startswith("/api/telemetry?since="), "спрашивается только новое (since)")
    SCOUT.answers["/api/telemetry"] = (200, {"ok": True, "samples": [{"t": 2, "gpus": [{**last, "powerW": None}]}]})
    check(monitoring.gpu_sample()["powerW"] == 0, "as-is: значение, которое скаут не прочёл, — 0, как было у nvidia-smi здесь")
    SCOUT.answers["/api/telemetry"] = (200, {"ok": True, "samples": []})
    check(monitoring.gpu_sample() == {"ok": False, "error": "the scout on the controller's machine has no sample yet"},
          "замеров ещё нет — так и сказано, а не 0 %")
    SCOUT.answers["/api/telemetry"] = (200, {"ok": True, "samples": [{"t": 3, "gpus": []}]})
    check(monitoring.gpu_sample() == {"ok": False, "error": "no GPU on the controller's machine"},
          "замер без карт — «карты нет», а не простаивающая карта")
    lonely, _ = machine(here="elsewhere")
    monitoring.machine_scout = lonely
    check(monitoring.gpu_sample() == {"ok": False, "error": MachineScout.NO_SCOUT}, "скаута нет — его причина")
    check(monitoring.top_processes() == [], "процессов без скаута нет — пустой список, панель пишет «нет данных»")
    monitoring.machine_scout = ms
    SCOUT.answers["/api/host/processes"] = (200, {"ok": True, "processes": [{"pid": 7, "cpuPct": 91.0}]})
    check(monitoring.top_processes() == [{"pid": 7, "cpuPct": 91.0}], "процессы машины — список скаута")

    print("список карт машины — из отчёта её скаута:")
    card = {"index": "0", "name": "NVIDIA GeForce RTX 5090", "memoryTotalMiB": "32607", "memoryUsedMiB": "28201"}
    reported, _ = machine(gpus=[card], gpuError="")
    monitoring.machine_scout = reported
    SCOUT.requests.clear()
    got = monitoring.gpu_state()
    check(got == {"ok": True, "gpus": [card]} and SCOUT.requests == [],
          f"карты — те, что скаут прислал в отчёте; nvidia-smi не запускается, скаута лишний раз не спрашивают (got {got})")
    got["gpus"][0]["name"] = "changed"
    check(reported.host()["gpus"][0]["name"] == "NVIDIA GeForce RTX 5090", "ответ — копия: правка его не меняет запись хоста")
    mismatch = "Failed to initialize NVML: Driver/library version mismatch"
    monitoring.machine_scout, _ = machine(gpus=[], gpuError=mismatch)
    check(monitoring.gpu_state() == {"ok": False, "gpus": [], "error": mismatch},
          "карт нет — причина словами nvidia-smi от скаута (2.25), а не «карт нет»")
    monitoring.machine_scout, _ = machine(gpus=[])
    check(monitoring.gpu_state() == {"ok": False, "gpus": [], "error": ""},
          "as-is: скаут причины не назвал (старый или карт правда нет) — пустая причина, доска пишет «нет карт»")
    monitoring.machine_scout = lonely
    check(monitoring.gpu_state() == {"ok": False, "gpus": [], "error": MachineScout.NO_SCOUT},
          "negative: скаута нет — его причина; карты чужой машины не выдаются за свои")
    check(lonely.host() == {}, "без скаута записи хоста нет — пусто, а не первая попавшаяся")
    monitoring.machine_scout = ms

    print("снимки терминала:")
    SCOUT.answers["/api/monitor/nvidia-smi"] = (200, {"ok": True, "output": "  NVIDIA-SMI 610.57  ", "time": 1234,
                                                      "source": "nvidia-smi"})
    check(monitoring.monitor_snapshot("nvidia-smi") == {"kind": "nvidia-smi", "ok": True, "output": "NVIDIA-SMI 610.57",
                                                        "time": 1234, "source": "nvidia-smi"},
          "nvidia-smi — вывод скаута и его время")
    SCOUT.answers["/api/monitor/nvidia-smi"] = (200, {"ok": False, "error": "nvidia-smi: not found"})
    snap = monitoring.monitor_snapshot("nvidia-smi")
    check(snap["ok"] is False and snap["output"] == "nvidia-smi: not found", f"отказ — словами скаута в окне (got {snap})")
    SCOUT.answers["/api/monitor/btop"] = (200, {"ok": True, "frame": "CPU 12%  MEM 40%", "top": "PID 1"})
    snap = monitoring.monitor_snapshot("btop")
    check(snap["ok"] is True and snap["source"] == "btop" and "CPU 12%" in snap["output"] and "html" in snap,
          f"кадр btop нарисован здесь тем же рендером (got {snap.get('source')}, {snap.get('output', '')[:20]!r})")
    SCOUT.answers["/api/monitor/btop"] = (200, {"ok": True, "frame": "", "top": "PID USER %CPU"})
    snap = monitoring.monitor_snapshot("btop")
    check(snap["source"] == "top" and snap["output"] == "btop snapshot unavailable; showing top fallback.\n\nPID USER %CPU",
          f"кадра нет — top скаута и пометка (got {snap})")
    lonely_snap = MachineScout.NO_SCOUT
    monitoring.machine_scout = lonely
    snap = monitoring.monitor_snapshot("btop")
    check(snap["ok"] is False and snap["output"] == lonely_snap, f"без скаута — причина, а не пустое окно (got {snap})")
    try:
        monitoring.monitor_snapshot("htop")
        got = None
    except AppError as exc:
        got = exc.status
    check(got == 404, "negative: неизвестный снимок — 404, скаута не спрашивают")


def test_power():
    print("выключение машины контроллера:")
    ms, topo = machine()
    keep = (host_power.machine_scout, host_power.topo, host_power._scout_headers)
    host_power.machine_scout, host_power.topo, host_power._scout_headers = ms, topo, lambda: dict(TOKEN)
    try:
        SCOUT.requests.clear()
        SCOUT.answers["/api/host/poweroff"] = (200, {"ok": True})
        got = host_power.host_power({"hostId": "controller"}, "poweroff")
        req = SCOUT.requests[-1]
        check((req["method"], req["path"], req["token"]) == ("POST", "/api/host/poweroff", "test-token"),
              f"старое имя машины контроллера уходит её скауту (got {req['method']} {req['path']})")
        check(got["hostId"] == "own-box" and got["action"] == "poweroff", "в ответе — её настоящий id")
        SCOUT.answers["/api/host/reboot"] = (500, {"error": "sudo: a password is required"})
        try:
            host_power.host_power({"hostId": "controller"}, "reboot")
            got = None
        except AppError as exc:
            got = (exc.status, str(exc))
        check(got == (502, "own-box: sudo: a password is required"),
              f"отказ скаута — его словами, а не «client unreachable» у ответившей машины (got {got})")
        host_power.machine_scout, _ = machine(here="elsewhere")
        SCOUT.requests.clear()
        try:
            host_power.host_power({"hostId": "controller"}, "reboot")
            got = None
        except AppError as exc:
            got = (exc.status, str(exc))
        check(got == (409, MachineScout.NO_SCOUT) and SCOUT.requests == [],
              f"без скаута — 409 «скаута нет», и ни один скаут не выключен (got {got})")
    finally:
        host_power.machine_scout, host_power.topo, host_power._scout_headers = keep


def test_driver_over_the_wire():
    print("драйвер — по проводу:")
    ms, _ = machine()
    gpu_driver.machine_scout = ms
    gpu_driver._status_cache.update(t=0.0, data=None)
    facts = {"ok": True, "running": "610.57.04", "runningError": "", "secureBoot": True, "moduleLoaded": True,
             "installed": [{"package": "nvidia-driver-610-open", "version": "610.57.04-0ubuntu1"}],
             "available": [{"package": "nvidia-driver-610-open", "version": "610.57.04-0ubuntu1"}],
             "signedModules": "linux-modules-nvidia-610-open-generic", "signedModulesInstalled": True,
             "rebootPending": False, "rebootPendingPackages": []}
    SCOUT.answers["/api/host/driver"] = (200, facts)
    SCOUT.requests.clear()
    st = gpu_driver.driver_status(ttl=0)
    check([r["path"] for r in SCOUT.requests] == ["/api/host/driver"], "факты — одним запросом к скауту машины")
    check(st["running"] == "610.57.04" and st["updateAvailable"] is False and st["rebootRequired"] is False
          and st["hostId"] == "own-box", f"решение из фактов: обновлять нечего, перезагрузка не нужна (got {st})")
    SCOUT.answers["/api/host/driver/install"] = (200, {"running": True, "tag": "driver:nvidia-driver-610-open"})
    gpu_driver.driver_update("nvidia-driver-610-open")
    check(SCOUT.requests[-1]["body"] == {"package": "nvidia-driver-610-open"}, "установка — пакет в теле")
    SCOUT.answers["/api/host/driver/install-status"] = (200, {"running": False, "result": "ok", "lines": ["done"]})
    check(gpu_driver.driver_update_status() == {"running": False, "result": "ok", "lines": ["done"]},
          "ход установки — ответ скаута как есть")
    SCOUT.answers["/api/host/driver"] = (200, {"ok": False, "error": "dpkg-query: command not found"})
    gpu_driver._status_cache.update(t=0.0, data=None)
    gpu_driver.machine_scout, _ = machine()
    try:
        gpu_driver.driver_status(ttl=0)
        got = None
    except AppError as exc:
        got = (exc.status, str(exc))
    check(got == (502, "the driver of the controller's machine cannot be read: dpkg-query: command not found"),
          f"скаут не прочёл — 502 и его слова (got {got})")


for fn in (test_which_scout, test_forwarding, test_failure_pause, test_readings, test_power, test_driver_over_the_wire):
    fn()

SCOUT.server.shutdown()
print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all machine-scout snapshots hold")
