#!/usr/bin/env python3
"""Snapshot of ContainerPreflight (caravan/common/container_preflight.py): what a
container must be told before it starts, by value; then the two real entry
points, started in container mode without it, must refuse with exit code 2.

The environment and both clocks are parameters: the cases below never read
this machine's zone. Only the last part starts real processes, each with an
environment of its own.

Run: python3 scripts/test_container_preflight.py
"""
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.common.container_preflight import ContainerPreflight  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


ZONES = {"Asia/Tbilisi": 4 * 3600, "UTC": 0, "Europe/Berlin": 2 * 3600}


def zone_offset(name, at):
    if name not in ZONES:
        raise KeyError(name)
    return ZONES[name]


def preflight(env, local=4 * 3600):
    return ContainerPreflight(env=env, now=lambda: 1_790_000_000, local_offset=lambda at: local,
                              zone_offset=zone_offset)


GOOD = {"CARAVAN_CONTAINER": "1", "TZ": "Asia/Tbilisi", "LLAMA_TOPOLOGY_SERVER_IP": "10.0.0.20"}


def test_outside_a_container():
    print("вне контейнера:")
    check(preflight({}).problems() == [], "без контейнера ничего не требуется — машина знает сама")
    check(preflight({"CARAVAN_CONTAINER": "0"}).problems() == [], "CARAVAN_CONTAINER=0 — не контейнер")
    check(ContainerPreflight.in_container({"CARAVAN_CONTAINER": " 1 "}), "« 1 » с пробелами — контейнер")


def test_good_container():
    print("контейнер со всеми настройками:")
    check(preflight(GOOD).problems() == [], "пояс и адрес названы — старт разрешён")
    check(preflight({**GOOD, "TZ": ":Asia/Tbilisi"}).problems() == [], "пояс с двоеточием впереди тоже годится")
    check(preflight({**GOOD, "TZ": "UTC"}, local=0).problems() == [], "TZ=UTC, названный явно, годится")
    check(preflight({**GOOD, "LLAMA_TOPOLOGY_SERVER_IP": "caravan.home.arpa"}).problems() == [],
          "адрес именем — годится, флот его разрешит")


def test_zone():
    print("часовой пояс:")
    no_zone = preflight({**GOOD, "TZ": ""}).problems()
    check(len(no_zone) == 1 and no_zone[0].startswith("TZ is not set"), f"пояс не задан — отказ (получено {no_zone})")
    unknown = preflight({**GOOD, "TZ": "Mars/Olympus"}).problems()
    check(unknown == ["TZ=Mars/Olympus: no such time zone in this image's zone data"],
          f"неизвестный пояс — отказ с его именем (получено {unknown})")
    silent = preflight(GOOD, local=0).problems()
    check(silent == ["TZ=Asia/Tbilisi: the zone is UTC+4, but the clock runs at UTC+0 — "
                     "the image has no zone data for the C library"],
          f"имя известно, а часы идут в UTC — отказ с обоими сдвигами (получено {silent})")


def test_address():
    print("адрес для агентов:")
    for raw in ("", "127.0.0.1", "127.8.8.8", "localhost", "LOCALHOST", "0.0.0.0", "::1", "::"):
        found = preflight({**GOOD, "LLAMA_TOPOLOGY_SERVER_IP": raw}).problems()
        check(len(found) == 1 and found[0].startswith("LLAMA_TOPOLOGY_SERVER_IP"),
              f"адрес {raw!r} — отказ (получено {found})")
    check(preflight({**GOOD, "LLAMA_TOPOLOGY_SERVER_IP": "fd00::20"}).problems() == [], "адрес IPv6 сети — годится")
    proxy = preflight({**GOOD, "LLAMA_TOPOLOGY_SERVER_IP": ""}).problems(address=False)
    check(proxy == [], f"прокси адрес не спрашивает (получено {proxy})")


def test_enforce():
    print("отказ при старте:")
    stream = io.StringIO()
    try:
        preflight({"CARAVAN_CONTAINER": "1"}).enforce("lama-caravan", stream=stream)
        code = None
    except SystemExit as exc:
        code = exc.code
    text = stream.getvalue()
    check(code == 2, f"процесс выходит с кодом 2 (получено {code!r})")
    check(text.startswith("lama-caravan: will not start in a container without these settings:"),
          f"и говорит, кто и почему (получено {text[:60]!r})")
    check(text.count("\n  - ") == 2, "обе причины названы")
    stream = io.StringIO()
    preflight(GOOD).enforce("lama-caravan", stream=stream)
    check(stream.getvalue() == "", "с настройками — молчит и не останавливает")


def run_entry(script, env_extra):
    data = tempfile.mkdtemp(prefix="caravan-preflight-")
    env = {k: v for k, v in os.environ.items() if k not in ("TZ", "LLAMA_TOPOLOGY_SERVER_IP")}
    env.update({"CARAVAN_CONTAINER": "1", "CARAVAN_DATA_DIR": data, "HOME": data,
                "LLAMACPP_ADMIN_HOST": "127.0.0.1", "LLAMACPP_ADMIN_PORT": "1",
                "PYTHONDONTWRITEBYTECODE": "1", **env_extra})
    return subprocess.run([sys.executable, script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def test_real_entry_points():
    print("настоящие точки входа в режиме контейнера:")
    admin = run_entry("app.py", {})
    check(admin.returncode == 2, f"контроллер без настроек не стартует: код 2 (получено {admin.returncode})")
    check("TZ is not set" in admin.stderr and "LLAMA_TOPOLOGY_SERVER_IP is not set" in admin.stderr,
          f"и называет обе настройки (stderr: {admin.stderr[-160:]!r})")
    proxy = run_entry("agent-proxies.py", {})
    check(proxy.returncode == 2 and "TZ is not set" in proxy.stderr,
          f"прокси без пояса не стартует (код {proxy.returncode})")
    check("LLAMA_TOPOLOGY_SERVER_IP" not in proxy.stderr, "и адрес у прокси не спрашивает")
    wrong = run_entry("app.py", {"TZ": "Mars/Olympus", "LLAMA_TOPOLOGY_SERVER_IP": "10.0.0.20"})
    check(wrong.returncode == 2 and "TZ=Mars/Olympus" in wrong.stderr,
          f"с несуществующим поясом — тоже отказ (код {wrong.returncode})")
    real = subprocess.run([sys.executable, "-c",
                           "from caravan.common.container_preflight import ContainerPreflight as C;"
                           "print(repr(C(env={'CARAVAN_CONTAINER': '1', 'TZ': 'Asia/Tbilisi'}).zone_problem()))"],
                          cwd=ROOT, env={**os.environ, "TZ": "Asia/Tbilisi"}, capture_output=True, text=True, timeout=30)
    check(real.stdout.strip() == "''",
          f"настоящий пояс с настоящими данными зон проходит обе проверки (получено {real.stdout.strip() or real.stderr[-120:]})")


for fn in (test_outside_a_container, test_good_container, test_zone, test_address, test_enforce,
           test_real_entry_points):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all container-preflight snapshots hold")
