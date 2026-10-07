#!/usr/bin/env python3
"""Snapshot of what the controller answers about its own machine, in a container
and on the machine, by value.

Since 1.3.439 the machine is asked through its scout (caravan/admin/machine_scout.py):
power, the GPU driver, the GPU reading, the busiest processes, the terminal
snapshots — and since 1.3.440 the list of its cards. The cases below have no
scout — an empty fleet in a fresh data folder — so each of those answers
"there is no scout on the controller's machine", the same way in both modes.
The service journal is the controller's own and still read here: in a
container it points at `docker logs`.

Each mode runs in a child process — CARAVAN_CONTAINER is read once, at import,
as in production — and every program start there is caught: a container
answer must come BEFORE any attempt to run systemctl, sudo or nvidia-smi,
not after it failed.

Run: python3 scripts/test_container_answers.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.machine_scout import MachineScout  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


CHILD = r'''
import json, subprocess
started = []
class _Caught:
    def __init__(self, args, *a, **k):
        started.append(list(args) if isinstance(args, (list, tuple)) else [str(args)])
        raise FileNotFoundError(f"caught: {args!r}")
subprocess.Popen = _Caught

from caravan.common.errors import AppError
from caravan.admin import gpu_driver, host_power, monitoring, systemd_ctl
from caravan.admin.paths import IS_CONTAINER

def refused(fn, *args):
    try:
        fn(*args)
    except AppError as exc:
        return [exc.status, str(exc)]
    return None

out = {"inContainer": IS_CONTAINER}
# Through the scout. Actions only where they must be refused: with a scout
# they would act, and a test never powers a machine off.
out.update({
    "power": refused(host_power.host_power, {"hostId": "controller"}, "poweroff"),
    "driver": refused(gpu_driver.driver_status),
    "driverUpdate": refused(gpu_driver.driver_update, "nvidia-driver-580"),
    "watch": gpu_driver.start_watch_thread().is_alive(),
    "gpu": monitoring.gpu_sample(),
    "processes": monitoring.top_processes(),
    "smi": monitoring.monitor_snapshot("nvidia-smi"),
    "btop": monitoring.monitor_snapshot("btop"),
    "gpuState": monitoring.gpu_state(),
})
if IS_CONTAINER:
    out["journal"] = systemd_ctl.logs()
out["started"] = started
print(json.dumps(out))
'''


def child(container):
    data = tempfile.mkdtemp(prefix="caravan-answers-")
    env = {**os.environ, "CARAVAN_DATA_DIR": data, "HOME": data, "PYTHONDONTWRITEBYTECODE": "1"}
    if container:
        env["CARAVAN_CONTAINER"] = "1"
    else:
        env.pop("CARAVAN_CONTAINER", None)
    run = subprocess.run([sys.executable, "-c", CHILD], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        print(run.stdout, run.stderr)
        return {}
    return json.loads(run.stdout.strip().splitlines()[-1])


NO_SCOUT = MachineScout.NO_SCOUT


def through_the_scout(got, mode):
    """The answers that go through the machine's scout: the same in both modes."""
    check(got.get("started") == [], f"{mode}: ни одна программа машины не запускалась (получено {got.get('started')})")
    check(got.get("power") == [409, NO_SCOUT], f"{mode}: выключение — 409 «скаута нет» (получено {got.get('power')})")
    check(got.get("driver") == [409, f"the driver of the controller's machine cannot be read: {NO_SCOUT}"],
          f"{mode}: драйвер — 409 и та же причина (получено {got.get('driver')})")
    check(got.get("driverUpdate") == [409, NO_SCOUT], f"{mode}: обновление драйвера — 409 (получено {got.get('driverUpdate')})")
    check(got.get("watch") is True, f"{mode}: сторож драйвера запущен — он спрашивает скаута")
    check(got.get("gpu") == {"ok": False, "error": NO_SCOUT}, f"{mode}: видеокарта — «скаута нет», а не 0 % (получено {got.get('gpu')})")
    check(got.get("processes") == [], f"{mode}: процессы — пусто, а не процессы контроллера")
    for kind in ("smi", "btop"):
        snap = got.get(kind) or {}
        check(snap.get("ok") is False and snap.get("output") == NO_SCOUT, f"{mode}: снимок {kind} — причина в окне (получено {snap})")
    check(got.get("gpuState") == {"ok": False, "gpus": [], "error": NO_SCOUT},
          f"{mode}: список карт — «скаута нет», а не «карт нет» (получено {got.get('gpuState')})")


def test_in_a_container():
    print("контроллер в контейнере, скаута нет:")
    got = child(container=True)
    check(got.get("inContainer") is True, "флаг контейнера прочитан при импорте")
    through_the_scout(got, "контейнер")
    check(str(got.get("journal", "")).startswith("The journal is unavailable in a container"),
          f"журнал службы — «недоступно» и куда смотреть (получено {got.get('journal')!r})")


def test_outside_a_container():
    print("контроллер на машине, скаута нет:")
    got = child(container=False)
    check(got.get("inContainer") is False, "флаг контейнера не стоит")
    through_the_scout(got, "на машине")
    check("journal" not in got, "журнал на машине не подменяется ответом контейнера")


for fn in (test_in_a_container, test_outside_a_container):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all container-answer snapshots hold")
