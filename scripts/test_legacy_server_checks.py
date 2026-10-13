#!/usr/bin/env python3
"""Value snapshot: what /api/state asks of the legacy single server, and what it says.

The legacy server (`llamacpp-current.service`, one llama-server on the controller's
own port) lost its page in 1.3.365; System → Diagnostics still shows its unit and
its port, and Repair names its PID. Until 1.3.485 every /api/state also ran
journalctl for 160 lines of its journal and asked its port four times (/health,
/props, /v1/models, /metrics) for summaries no page showed — and asked the port
even with the unit off, so any other server there (8080 is many programs'
default) read as the legacy server "ready".

What's pinned. The answer carries `service` and `diagnostics`, and neither `logs`
nor `runtime`; building it runs no journalctl and asks the port nothing while the
unit is not active. The diagnostics rows by value: the unit active and its port
ready, the unit active and the port refusing, the unit off (muted, the port not
asked — even when something would answer there), systemctl failing, an active
unit nobody probed ("not asked", not "ready"), and a container, which has no unit
to ask. The probe asks `/props` on the configured port, 8080 when none is set.

Each part runs in a child process with a fresh data folder, as the controller
imports its paths once; programs and HTTP requests are caught, not run.

Run: python3 scripts/test_legacy_server_checks.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


CHILD = r'''
import json, os, subprocess, sys, tempfile, urllib.request
from pathlib import Path

started, asked = [], []
class _Caught:
    def __init__(self, args, *a, **k):
        started.append(list(args) if isinstance(args, (list, tuple)) else [str(args)])
        raise FileNotFoundError(f"caught: {args!r}")
subprocess.Popen = _Caught
def _urlopen(req, *a, **k):
    asked.append(req.full_url if hasattr(req, "full_url") else str(req))
    raise OSError("caught")
urllib.request.urlopen = _urlopen

from caravan.admin import status, systemd_ctl

out = {}
bus_dir = Path(tempfile.mkdtemp(prefix="caravan-bus-"))
(bus_dir / "bus").write_text("")
systemd_ctl.user_systemd_env = lambda: {"XDG_RUNTIME_DIR": str(bus_dir), "DBUS_SESSION_BUS_ADDRESS": ""}

def rows(diag):
    return [[c["kind"], c["title"], c["detail"]] for c in diag["checks"]]

def run_case(service, probe_answer=None, give_probe=True):
    calls = []
    def probe():
        calls.append(1)
        return probe_answer
    diag = systemd_ctl.user_service_diagnostics(service, probe=probe if give_probe else None)
    return {"rows": rows(diag), "legacyActive": diag["legacyActive"], "probed": len(calls)}

ACTIVE = {"ok": True, "ActiveState": "active", "SubState": "running", "MainPID": "4242", "error": ""}
OFF = {"ok": True, "ActiveState": "inactive", "SubState": "dead", "MainPID": "0", "error": ""}
BROKEN = {"ok": False, "error": "Failed to connect to bus: No medium found\n"}

if os.environ.get("PART") == "diagnostics":
    systemd_ctl.IS_CONTAINER = False
    out["activeReady"] = run_case(ACTIVE, {"default_generation_settings": {"n_ctx": 4096}})
    out["activeRefused"] = run_case(ACTIVE, {"ok": False, "error": "<urlopen error [Errno 111] Connection refused>"})
    out["off"] = run_case(OFF, {"default_generation_settings": {}})
    out["broken"] = run_case(BROKEN, {"default_generation_settings": {}})
    out["activeUnasked"] = run_case(ACTIVE, give_probe=False)
    from caravan.admin import proxy_supervisor
    proxy_supervisor.status = lambda: {"active": True, "pid": 77, "respawns": 0}
    systemd_ctl.IS_CONTAINER = True
    out["container"] = run_case(ACTIVE, {"default_generation_settings": {}})
    systemd_ctl.IS_CONTAINER = False
    asked.clear()
    status.legacy_port_props({"PORT": "8123"})
    status.legacy_port_props({})
    out["probeUrls"] = list(asked)
elif os.environ.get("PART") == "stateActive":
    status.service_status = lambda: dict(ACTIVE)
    port = status.parse_config().get("PORT") or "8080"
    answer = status.state()
    out["port"] = str(port)
    out["asked"] = list(asked)
    out["diagRows"] = rows(answer["diagnostics"])
elif os.environ.get("PART") == "state":
    answer = status.state()
    out["keys"] = sorted(answer)
    out["serviceOk"] = answer["service"].get("ok")
    out["diagRows"] = rows(answer["diagnostics"])
    out["started"] = [a[0] for a in started]
    out["asked"] = list(asked)
print(json.dumps(out))
'''


def child(part, container=False):
    data = tempfile.mkdtemp(prefix="caravan-legacy-")
    env = {**os.environ, "CARAVAN_DATA_DIR": data, "HOME": data, "PYTHONDONTWRITEBYTECODE": "1", "PART": part}
    if container:
        env["CARAVAN_CONTAINER"] = "1"
    else:
        env.pop("CARAVAN_CONTAINER", None)
    run = subprocess.run([sys.executable, "-c", CHILD], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        print(run.stdout[-2000:], run.stderr[-2000:])
        check(False, f"дочерний процесс ({part}) упал с кодом {run.returncode}")
        return {}
    return json.loads(run.stdout.strip().splitlines()[-1])


BUS = ["good", "systemd user bus"]
UNIT = "llamacpp-current.service (legacy)"
PORT = "llama.cpp HTTP (legacy port)"
SKIPPED = ["muted", PORT, "legacy single-server not running — check skipped"]


def section_diagnostics():
    print("строки диагностики:")
    got = child("diagnostics")
    if not got:
        return
    bus_ok = lambda r: r[0][:2] == BUS  # noqa: E731
    a = got["activeReady"]
    check(bus_ok(a["rows"]) and a["rows"][1:] == [["good", UNIT, "active / running, PID 4242"],
                                                  ["good", PORT, "ready on configured port"]]
          and a["legacyActive"] is True and a["probed"] == 1,
          f"служба работает, порт отвечает — обе строки good, порт спрошен один раз (got {a})")
    a = got["activeRefused"]
    check(a["rows"][2] == ["warn", PORT, "<urlopen error [Errno 111] Connection refused>"] and a["probed"] == 1,
          f"служба работает, порт отказал — warn со словами отказа (got {a['rows'][2]}, {a['probed']})")
    a = got["off"]
    check(a["rows"][1:] == [["muted", UNIT, "inactive / dead, PID 0 — off is normal when serving via cells"], SKIPPED]
          and a["probed"] == 0 and a["legacyActive"] is False,
          f"negative: служба выключена — порт НЕ спрашивается, даже если там кто-то ответил бы «ready»; "
          f"строки приглушены (got {a})")
    a = got["broken"]
    check(a["rows"][1:] == [["bad", UNIT, "Failed to connect to bus: No medium found"], SKIPPED] and a["probed"] == 0,
          f"systemctl не ответил — строка bad со словами systemctl, порт не спрошен (got {a})")
    a = got["activeUnasked"]
    check(a["rows"][2] == ["warn", PORT, "the port was not asked"],
          f"absence: служба работает, а пробы нет — «не спрошен», а не «ready» (got {a['rows'][2]})")
    a = got["container"]
    titles = [r[1] for r in a["rows"]]
    check(titles == ["container mode", "data dir writable", "proxy child"] and a["probed"] == 0,
          f"negative: в контейнере службы нет — ни строк службы, ни пробы порта (got {titles}, {a['probed']})")
    check(got["probeUrls"] == ["http://127.0.0.1:8123/props", "http://127.0.0.1:8080/props"],
          f"проба — /props на порту из настроек, без порта — 8080 (got {got['probeUrls']})")


def section_state():
    print("ответ /api/state:")
    got = child("state")
    if not got:
        return
    keys = got["keys"]
    check("logs" not in keys and "runtime" not in keys,
          f"negative: ни журнала, ни сводок старого сервера в ответе (got {keys})")
    check({"service", "diagnostics", "config", "llamaCpp", "projectGit"} <= set(keys),
          "служба старого сервера и проверки остаются: «Repair» называет её PID, Diagnostics — строки")
    check("journalctl" not in got["started"], f"negative: journalctl не запускается (got {got['started']})")
    check("systemctl" in got["started"], f"systemctl спрошен о службе — один источник строк (got {got['started']})")
    check(not any(u.endswith(("/health", "/v1/models", "/metrics")) for u in got["asked"]),
          f"negative: ни /health, ни /v1/models, ни /metrics старого порта (got {got['asked']})")
    check(not any(u.endswith("/props") for u in got["asked"]) and got["serviceOk"] is False,
          f"systemctl не ответил — служба не active, порт не спрошен вовсе (got {got['asked']})")
    check([r[1] for r in got["diagRows"]][1:] == [UNIT, PORT] and got["diagRows"][2] == SKIPPED,
          f"строки диагностики в ответе — те же, что строит диагностика (got {got['diagRows']})")
    got = child("stateActive")
    if not got:
        return
    check(got["asked"] == [f"http://127.0.0.1:{got['port']}/props"],
          f"служба работает — ответ спрашивает ровно /props на её порту, один раз (got {got['asked']})")
    check(got["diagRows"][2] == ["warn", PORT, "caught"],
          f"порт не ответил — строка warn со словами отказа, не «ready» (got {got['diagRows'][2]})")


def main():
    section_diagnostics()
    section_state()
    if _fail:
        print(f"\nlegacy server checks FAILED: {len(_fail)}")
        return 1
    print("\nlegacy server checks OK: /api/state без журнала и сводок; порт спрашивается только у работающей службы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
