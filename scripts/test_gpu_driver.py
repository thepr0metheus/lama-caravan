#!/usr/bin/env python3
"""Value snapshot: the GPU driver of the controller's machine — what is offered,
whether a reboot is ours to ask for, what the watcher installs.

"Driver version" is TWO numbers: the running one (in the kernel, reported by
nvidia-smi) and the installed one (in packages, reported by dpkg). After an
update they diverge and stay different until a reboot; one number instead of
two would say "updated" in a case that's really "will update after a reboot".

The machine's scout reads those facts and runs the install (scout 2.24,
caravan_scout/driver_packages.py there, with its own snapshot: dpkg's
not-installed, apt's candidates, the signed modules, the install command).
What is pinned HERE is what the controller decides from the facts: the
candidate of the same flavor (the open module was once silently swapped for
the proprietary one), the two reboot reasons, a rejected signature named as
the reason, the allowlist before anything leaves, the watcher's schedule.

Run: python3 scripts/test_gpu_driver.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import gpu_driver as gd  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# The candidates as the scout sends them: newest first, by its allowlist.
AVAILABLE = [{"package": "nvidia-driver-610", "version": "610.43.02-0ubuntu0.24.04.1"},
             {"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"},
             {"package": "nvidia-driver-595", "version": "595.84-0ubuntu0.24.04.1"},
             {"package": "nvidia-driver-595-open", "version": "595.84-0ubuntu0.24.04.1"}]
INSTALLED = [{"package": "nvidia-driver-595-open", "version": "595.84-0ubuntu0.24.04.1"},
             {"package": "nvidia-driver-590-open", "version": "590.48.01-0ubuntu0.24.04.5"}]


class FakeScout:
    """The machine's scout as gpu_driver sees it: facts in, installs out."""

    NO_SCOUT = "there is no scout on the controller's machine"

    def __init__(self, **facts):
        self.facts = {"ok": True, "running": "595.84", "runningError": "", "installed": INSTALLED,
                      "available": AVAILABLE, "secureBoot": False, "moduleLoaded": True, "signedModules": "",
                      "signedModulesInstalled": False, "rebootPending": False, "rebootPendingPackages": [],
                      **facts}
        self.posted = []
        self.reads = []

    def host_id(self):
        return "own-box"

    def read(self, path, timeout=5):
        self.reads.append(path)
        if path == "/api/host/driver":
            return dict(self.facts)
        if path == "/api/host/driver/install-status":
            return {"running": True, "tag": "driver:x", "lines": ["Reading package lists..."]}
        return {"ok": False, "error": f"unexpected {path}"}

    def post(self, path, payload=None, timeout=15):
        self.posted.append((path, payload))
        name = (payload or {}).get("package")
        if name == "nvidia-driver-999-open":
            raise AppError("own-box: no such driver package in apt: nvidia-driver-999-open", 502)
        return {"running": True, "tag": f"driver:{name}"}


def status(**facts):
    gd.machine_scout = FakeScout(**facts)
    gd._status_cache.update(t=0.0, data=None)
    return gd.driver_status(ttl=0)


def test_status():
    print("сводка:")
    st = status()
    check(st["running"] == "595.84" and st["runningError"] == "", f"работающая версия — как сказал скаут (got {st['running']!r})")
    check(st["installed"]["package"] == "nvidia-driver-595-open", f"установленная — новейшая из установленных (got {st['installed']})")
    check(st["installedAll"] == INSTALLED and st["available"] == AVAILABLE, "оба списка переданы как есть")
    check(st["newest"]["package"] == "nvidia-driver-610-open",
          f"positive: предлагается ОТКРЫТЫЙ 610 — та же разновидность, что стоит (got {st['newest']})")
    check(st["updateAvailable"] is True, "есть что ставить: 610 старше 595")
    check(st["rebootRequired"] is False, "перезагрузка не нужна: установленное и работающее совпадают")
    check(st["hostId"] == "own-box", "сказано, чья это машина")
    st = status(installed=[{"package": "nvidia-driver-595", "version": "595.84-0ubuntu0.24.04.1"}])
    check(st["newest"]["package"] == "nvidia-driver-610", "закрытый установлен — предлагается закрытый")
    st = status(installed=[])
    check(st["newest"]["package"] == "nvidia-driver-610-open", "ничего не стоит — открытый: он и рекомендован")

    print("после установки, до перезагрузки:")
    after = [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    st = status(installed=after)
    check(st["rebootRequired"] is True and st["running"] == "595.84" and st["installed"]["version"].startswith("610."),
          f"два числа расходятся — и это сказано: работает 595.84, установлен 610 (got {st['running']} / {st['installed']})")
    check(st["updateAvailable"] is False, "и второй раз то же самое не предлагается: кандидат не старше установленного")
    print("сразу после установки nvidia-smi отвечает ошибкой:")
    st = status(installed=after, running="", runningError="Failed to initialize NVML: Driver/library version mismatch")
    check(st["running"] == "" and "mismatch" in st["runningError"], "номера нет, причина — отдельным полем")
    check(st["rebootRequired"] is True, "пакеты стоят, номера нет — это и есть щель между установкой и перезагрузкой")


def test_no_scout():
    print("машина без скаута:")

    class Lonely(FakeScout):
        def read(self, path, timeout=5):
            return {"ok": False, "error": self.NO_SCOUT}

    class Silent(FakeScout):
        def read(self, path, timeout=5):
            return {"ok": False, "error": "own-box unreachable: timed out"}

    for fake, code in ((Lonely(), 409), (Silent(), 502)):
        gd.machine_scout = fake
        gd._status_cache.update(t=0.0, data=None)
        try:
            gd.driver_status(ttl=0)
            got = None
        except AppError as exc:
            got = (exc.status, str(exc))
        check(got is not None and got[0] == code and fake.read("/api/host/driver")["error"] in got[1],
              f"{'скаута нет — 409' if code == 409 else 'скаут молчит — 502'} и его причина (got {got})")


def test_update_is_guarded():
    print("что уходит к скауту:")
    scout = FakeScout()
    gd.machine_scout = scout
    got = gd.driver_update("nvidia-driver-610-open")
    check(scout.posted == [("/api/host/driver/install", {"package": "nvidia-driver-610-open"})],
          f"пакет уходит скауту машины (got {scout.posted})")
    check(got.get("tag") == "driver:nvidia-driver-610-open", "и ответ — его задание")
    for bad, why in (("nvidia-driver-610-open; rm -rf /", "команда в имени"), ("bash", "чужой пакет"),
                     ("", "пусто"), ("nvidia-driver-", "без номера")):
        try:
            gd.driver_update(bad)
            check(False, f"{why} — должен быть отказ")
        except AppError as exc:
            check(exc.status == 400, f"{why} — отказ 400 (got {exc.status})")
    check(len(scout.posted) == 1, "ни один отказ не дошёл до скаута")
    try:
        gd.driver_update("nvidia-driver-999-open")
        check(False, "несуществующий пакет — должен быть отказ")
    except AppError as exc:
        check("no such driver package in apt" in str(exc), f"форма верна, такого нет в apt — слова скаута (got {exc})")
    check(gd.driver_update_status()["lines"] == ["Reading package lists..."], "ход установки — от скаута")


def test_auto():
    print("сторож по расписанию:")
    store = {}
    import caravan.admin.state as state_mod
    state_mod.admin_state = store
    state_mod.save_admin_state = lambda: None
    gd.machine_scout = FakeScout()
    gd._status_cache.update(t=0.0, data=None)
    check(gd.auto_settings() == {"check": False, "install": False, "lastCheckAt": 0, "lastInstall": None},
          "по умолчанию сторож не смотрит и не ставит")
    check(gd.driver_watch_pass()["checked"] is False and gd.machine_scout.reads == [],
          "negative: галки сняты — проход ничего не делает, скаута не спрашивает")
    gd.set_auto_settings({"check": True})
    res = gd.driver_watch_pass(now=1000)
    check(res["checked"] is True and res["installed"] is None and res["reason"] == "auto-install off",
          f"только «смотреть»: обновление найдено, но не ставится (got {res})")
    check(gd.auto_settings()["lastCheckAt"] == 1000, "время последнего осмотра записано")
    gd.set_auto_settings({"install": True})
    check(gd.auto_settings()["check"] is True, "«ставить самому» включает и «смотреть»: ставить не глядя — это ставить что угодно")
    res = gd.driver_watch_pass(now=2000)
    check(res["installed"] == "nvidia-driver-610-open"
          and gd.machine_scout.posted == [("/api/host/driver/install", {"package": "nvidia-driver-610-open"})],
          f"обе галки: найденное обновление уходит скауту (got {res}, {gd.machine_scout.posted})")
    check((gd.auto_settings()["lastInstall"] or {}).get("version", "").startswith("610."), "и записано, что именно поставили")


def test_watch_schedule():
    """When the next pass is due — the schedule, not the timer.

    The defect: the loop slept FIRST and checked after, so every restart moved
    the first check a whole interval away. The service restarts on every
    deploy, deploys come more often than six hours, and the watcher had
    therefore never run a pass while looking switched on.
    """
    print("расписание сторожа:")
    iv = gd.WATCH_INTERVAL_SECONDS
    check(gd.watch_wait_seconds(now=1000, last=0) == iv,
          "записи нет вообще — ждём целый интервал: это не «просрочено», а первый раз под расписанием")
    check(gd.watch_wait_seconds(now=1000, last=None) == iv, "…и None читается так же, как ноль")
    check(gd.watch_wait_seconds(now=1000 + iv, last=1000) == 0,
          "интервал ровно прошёл — проход должен идти СЕЙЧАС, а не через интервал после старта")
    check(gd.watch_wait_seconds(now=1000 + iv * 5, last=1000) == 0,
          "простояли пять интервалов (перезапуски деплоями) — догоняем, а не начинаем счёт заново")
    check(gd.watch_wait_seconds(now=1000 + iv - 60, last=1000) == 60,
          "negative: минута до срока — ждём ровно её, лишнего прохода нет")
    check(gd.watch_wait_seconds(now=1000, last=1000) == iv, "negative: только что смотрели — целый интервал ожидания")
    check(gd.watch_wait_seconds(now=1000, last=1000 + iv * 10) == iv,
          "as-is: запись из будущего (скачок часов) — интервал, а не ожидание до того будущего")


def test_reboot_has_two_causes():
    print("перезагрузка: две причины, две надписи:")
    # One badge for two different reasons lied on a live host on 2026-09-07:
    # the versions already matched, yet the chip said it was "needed for the
    # kernel to switch to it". What was lit was Ubuntu's own marker.
    after = [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    st = status(installed=after)
    check(st["rebootForDriver"] is True and st["rebootPending"] is False,
          "positive: установлено новее работающего → причина именно драйверная")
    check(st["rebootRequired"] is True, "…и общий флаг для прежних читателей поднят")
    check(st["rebootPendingPackages"] == [], "пакетов ОС нет — список пуст, а не выдуман")
    st = status(installed=after, running="610.43.02", rebootPending=True,
                rebootPendingPackages=["linux-image-7.0.0-31-generic", "linux-base"])
    check(st["rebootForDriver"] is False, "negative: версии совпали — драйверной причины НЕТ, что бы ни говорил маркер ОС")
    check(st["rebootPending"] is True and st["rebootPendingPackages"] == ["linux-image-7.0.0-31-generic", "linux-base"],
          f"маркер ОС — отдельным полем и с её пакетами (got {st['rebootPendingPackages']})")
    check(st["rebootRequired"] is True, "общий флаг по-прежнему поднят — читатели не сломались")
    st = status(installed=after, rebootPending=True, rebootPendingPackages=["linux-base"])
    check(st["rebootForDriver"] is True and st["rebootPending"] is True, "обе причины разом — обе и сказаны")
    st = status(installed=after, running="610.43.02")
    check(st["rebootForDriver"] is False and st["rebootPending"] is False and st["rebootRequired"] is False,
          "ни одной причины — тишина, а не «на всякий случай»")
    st = status(installed=after, running="610.43.02", rebootPending=False, rebootPendingPackages=["stale"])
    check(st["rebootPendingPackages"] == [], "маркера нет — устаревший список пакетов не показывается")
    st = status(installed=after, running="", runningError="no card", secureBoot=True, moduleLoaded=False,
                rebootPending=True, rebootPendingPackages=["linux-base"])
    check(st["moduleRejected"] is True and st["rebootForDriver"] is False,
          "отвергнутая подпись драйверной причиной не становится — перезагрузка её не лечит")
    check(st["rebootPending"] is True, "…а маркер ОС остаётся как есть: это её повод, не наш")


def test_rejected_module_says_why():
    print("модуль отвергнут подписью:")
    after = [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    smi = "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver"
    signed = "linux-modules-nvidia-610-open-generic-hwe-24.04"
    st = status(installed=after, available=[], running="", runningError=smi, secureBoot=True, moduleLoaded=False,
                signedModules=signed, signedModulesInstalled=False)
    check(st["moduleRejected"] is True,
          "positive: Secure Boot включён, пакеты стоят, модуль не загружен → сказано, что подпись отвергнута")
    check(st["rebootRequired"] is False, "и перезагрузка НЕ предлагается: она уже была и модуль не загрузила")
    check(st["secureBoot"] is True and st["signedModules"] == signed and st["signedModulesInstalled"] is False,
          "панель знает, какого пакета не хватает и что он не стоит")
    check(st["runningError"] == f"{smi} — Secure Boot rejected the unsigned kernel module; install {signed}",
          f"причина дописана к словам nvidia-smi, которые панель показывает дословно (got {st['runningError']!r})")
    st = status(installed=after, available=[], running="", runningError=smi, secureBoot=True, moduleLoaded=False,
                signedModules=signed, signedModulesInstalled=True)
    check(st["runningError"] == f"{smi} — Secure Boot rejected the unsigned kernel module",
          "модули стоят — ставить нечего, совета «install» нет")
    st = status(installed=after, available=[], running="610.43.02", secureBoot=True, moduleLoaded=True)
    check(st["moduleRejected"] is False, "negative: модуль загружен и версия читается — обвинения нет")
    st = status(installed=after, available=[], running="", runningError="no card", secureBoot=False, moduleLoaded=False)
    check(st["moduleRejected"] is False and st["secureBoot"] is False,
          "без Secure Boot незагруженный модуль подписью не объясняется — это была бы выдумка")
    check(st["rebootRequired"] is True, "…и обычная щель «поставили, не перезагрузились» остаётся как была")


for fn in (test_status, test_no_scout, test_update_is_guarded, test_auto, test_watch_schedule,
           test_reboot_has_two_causes, test_rejected_module_says_why):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all gpu-driver snapshots hold")
