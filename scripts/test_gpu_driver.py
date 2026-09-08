#!/usr/bin/env python3
"""Value snapshot: the GPU driver — what's installed, what's available, what gets installed.

"Driver version" is TWO numbers: the running one (in the kernel, reported by
nvidia-smi) and the installed one (in packages, reported by dpkg). After an
update they diverge and stay different until a reboot; one number instead of
two would say "updated" in a case that's really "will update after a reboot".

Both defects found on a PRODUCTION host on the very first run are pinned: a
removed package with status "not-installed" counted as installed (the status
string contains the word "installed"), and a candidate was picked by version
alone, ignoring its flavor — the open module silently swapped for the
proprietary one.

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


# Exactly what a production host prints: two open packages installed, one removed.
DPKG = (
    "nvidia-driver-590-open 590.48.01-0ubuntu0.24.04.5 install ok installed\n"
    "nvidia-driver-595-open 595.84-0ubuntu0.24.04.1 install ok installed\n"
    "nvidia-driver-595 unknown unknown ok not-installed\n"
    "nvidia-driver-nonsense 1.0 install ok installed\n"
)
SEARCH = ("nvidia-driver-590 - NVIDIA driver metapackage\n"
          "nvidia-driver-590-open - NVIDIA driver (open kernel) metapackage\n"
          "nvidia-driver-595 - NVIDIA driver metapackage\n"
          "nvidia-driver-595-open - NVIDIA driver (open kernel) metapackage\n"
          "nvidia-driver-610 - NVIDIA driver metapackage\n"
          "nvidia-driver-610-open - NVIDIA driver (open kernel) metapackage\n")
POLICY = """nvidia-driver-590:
  Installed: 590.48.01-0ubuntu0.24.04.5
  Candidate: 590.48.01-0ubuntu0.24.04.5
nvidia-driver-590-open:
  Installed: 590.48.01-0ubuntu0.24.04.5
  Candidate: 590.48.01-0ubuntu0.24.04.5
nvidia-driver-595:
  Installed: (none)
  Candidate: 595.84-0ubuntu0.24.04.1
nvidia-driver-595-open:
  Installed: 595.84-0ubuntu0.24.04.1
  Candidate: 595.84-0ubuntu0.24.04.1
nvidia-driver-610:
  Installed: (none)
  Candidate: 610.43.02-0ubuntu0.24.04.1
nvidia-driver-610-open:
  Installed: (none)
  Candidate: 610.43.02-0ubuntu0.24.04.1
"""


def _fake_run(smi="595.84"):
    def run(cmd, **kwargs):
        head = cmd[0]
        if head == "nvidia-smi":
            return {"ok": not smi.startswith("Failed"), "stdout": smi + "\n", "stderr": ""}
        if head == "dpkg-query":
            return {"ok": True, "stdout": DPKG, "stderr": ""}
        if head == "apt-cache" and "search" in cmd:
            return {"ok": True, "stdout": SEARCH, "stderr": ""}
        if head == "apt-cache" and "policy" in cmd:
            return {"ok": True, "stdout": POLICY, "stderr": ""}
        return {"ok": False, "stdout": "", "stderr": "unexpected " + " ".join(cmd)}
    gd.run = run
    gd._status_cache.update(t=0.0, data=None)


def test_reading():
    print("что стоит и что доступно:")
    _fake_run()
    installed = gd.installed_packages()
    check([row["package"] for row in installed] == ["nvidia-driver-595-open", "nvidia-driver-590-open"],
          f"установленные — только те, у кого статус ровно «installed», новейший первым (got {installed})")
    check(all(row["version"] != "unknown" for row in installed),
          "снятый пакет («not-installed» — в статусе тоже есть слово installed) не считается установленным")
    available = gd.available_packages()
    check(available[0]["version"].startswith("610."),
          f"кандидаты отсортированы по версии, новейший первым (got {available[:2]})")
    check(all(row["version"] != "(none)" for row in available),
          "пакет без кандидата в список не попадает")
    check(not any(row["package"] == "nvidia-driver-nonsense" for row in installed),
          "имя не той формы отсеивается белым списком")


def test_status():
    print("сводка:")
    _fake_run()
    st = gd.driver_status(ttl=0)
    check(st["running"] == "595.84" and st["runningError"] == "",
          f"работающая версия — от nvidia-smi (got {st['running']!r})")
    check(st["installed"]["package"] == "nvidia-driver-595-open",
          f"установленная — от dpkg (got {st['installed']})")
    check(st["newest"]["package"] == "nvidia-driver-610-open",
          f"positive: предлагается ОТКРЫТЫЙ 610 — та же разновидность, что стоит (got {st['newest']})")
    check(st["updateAvailable"] is True, "есть что ставить: 610 старше 595")
    check(st["rebootRequired"] is False,
          "перезагрузка не нужна: установленное и работающее совпадают")

    print("после установки, до перезагрузки:")
    _fake_run(smi="595.84")
    gd.installed_packages = lambda: [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    gd._status_cache.update(t=0.0, data=None)
    st = gd.driver_status(ttl=0)
    check(st["rebootRequired"] is True and st["running"] == "595.84"
          and st["installed"]["version"].startswith("610."),
          f"два числа расходятся — и это сказано: работает 595.84, установлен 610 (got {st['running']} / {st['installed']})")
    check(st["updateAvailable"] is False,
          "и второй раз то же самое не предлагается: кандидат не старше установленного")
    print("сразу после установки nvidia-smi отвечает ошибкой:")
    _fake_run(smi="Failed to initialize NVML: Driver/library version mismatch")
    gd.installed_packages = lambda: [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    gd._status_cache.update(t=0.0, data=None)
    st = gd.driver_status(ttl=0)
    check(st["running"] == "",
          f"positive: номера нет — и в поле версии пусто, а не предложение с ошибкой (got {st['running']!r})")
    check("mismatch" in st["runningError"],
          f"причина названа отдельным полем (got {st['runningError']!r})")
    check(st["rebootRequired"] is True,
          "пакеты стоят, номера нет — это и есть щель между установкой и перезагрузкой")

    gd.installed_packages = _orig_installed
    gd._status_cache.update(t=0.0, data=None)


def test_update_is_guarded():
    print("что уезжает в apt:")
    _fake_run()
    started = []
    import caravan.admin.status as status_mod
    status_mod._start_shared_job = lambda cmd, tag: started.append((cmd, tag)) or {"ok": True, "tag": tag}
    gd.driver_update("nvidia-driver-610-open")
    cmd, tag = started[-1]
    check(cmd[-1] == "nvidia-driver-610-open" and "apt-get" in cmd and "-y" in cmd,
          f"ставится названный пакет неинтерактивным apt (got {cmd})")
    check(tag == "driver:nvidia-driver-610-open", f"задание помечено пакетом (got {tag})")
    for bad, why in (("nvidia-driver-610-open; rm -rf /", "команда в имени"),
                     ("bash", "чужой пакет"),
                     ("", "пусто"),
                     ("nvidia-driver-", "без номера")):
        try:
            gd.driver_update(bad)
            check(False, f"{why} — должен быть отказ")
        except AppError as exc:
            check(exc.status == 400, f"{why} — отказ 400 (got {exc.status})")
    try:
        gd.driver_update("nvidia-driver-999-open")
        check(False, "несуществующий пакет — должен быть отказ")
    except AppError as exc:
        check(exc.status == 404,
              f"форма верна, но такого кандидата в apt нет — 404 (got {exc.status})")
    check(len(started) == 1, "ни один отказ не дошёл до apt")


def test_auto():
    print("сторож по расписанию:")
    _fake_run()
    store = {}
    class _State(dict):
        pass
    import caravan.admin.state as state_mod
    state_mod.admin_state = store
    state_mod.save_admin_state = lambda: None
    check(gd.auto_settings() == {"check": False, "install": False, "lastCheckAt": 0, "lastInstall": None},
          "по умолчанию сторож не смотрит и не ставит")
    check(gd.driver_watch_pass()["checked"] is False,
          "negative: галки сняты — проход ничего не делает, в apt не ходит")
    gd.set_auto_settings({"check": True})
    res = gd.driver_watch_pass(now=1000)
    check(res["checked"] is True and res["installed"] is None and res["reason"] == "auto-install off",
          f"только «смотреть»: обновление найдено, но не ставится (got {res})")
    check(gd.auto_settings()["lastCheckAt"] == 1000, "время последнего осмотра записано")
    started = []
    import caravan.admin.status as status_mod
    status_mod._start_shared_job = lambda cmd, tag: started.append(tag) or {"ok": True}
    gd.set_auto_settings({"install": True})
    check(gd.auto_settings()["check"] is True,
          "«ставить самому» включает и «смотреть»: ставить не глядя — это ставить что угодно")
    res = gd.driver_watch_pass(now=2000)
    check(res["installed"] == "nvidia-driver-610-open" and started == ["driver:nvidia-driver-610-open"],
          f"обе галки: найденное обновление запускается (got {res}, {started})")
    check((gd.auto_settings()["lastInstall"] or {}).get("version", "").startswith("610."),
          "и записано, что именно поставили")


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
    check(gd.watch_wait_seconds(now=1000, last=None) == iv,
          "…и None читается так же, как ноль")
    check(gd.watch_wait_seconds(now=1000 + iv, last=1000) == 0,
          "интервал ровно прошёл — проход должен идти СЕЙЧАС, а не через интервал после старта")
    check(gd.watch_wait_seconds(now=1000 + iv * 5, last=1000) == 0,
          "простояли пять интервалов (перезапуски деплоями) — догоняем, а не начинаем счёт заново")
    check(gd.watch_wait_seconds(now=1000 + iv - 60, last=1000) == 60,
          "negative: минута до срока — ждём ровно её, лишнего прохода в apt нет")
    check(gd.watch_wait_seconds(now=1000, last=1000) == iv,
          "negative: только что смотрели — целый интервал ожидания")
    check(gd.watch_wait_seconds(now=1000, last=1000 + iv * 10) == iv,
          "as-is: запись из будущего (скачок часов) — интервал, а не ожидание до того будущего")


def test_unreadable_card_says_why():
    """"No cards" and "can't ask a card" are different messages.

    nvidia-smi exits with code ZERO and prints the trouble to stdout, exactly
    where numbers are expected. After a driver update (before a reboot) the
    board wrote "no GPU" about a card that was installed and running —
    absence drawn as normal. There is a reason, and it must be shown.
    """
    print("нечитаемая карта называет причину:")
    import caravan.admin.monitoring as mon
    # ok=False with an EMPTY stderr — exactly what a production host
    # returned: NVML's complaint sits in stdout, while the run() wrapper
    # still says "not ok". The first version read only stderr on this
    # branch and gave back an empty reason — "no GPU" on the board again.
    fail_not_ok = {"ok": False, "stderr": "",
                   "stdout": "Failed to initialize NVML: Driver/library version mismatch\nNVML library version: 610.43\n"}
    fail = {"ok": True, "stderr": "",
            "stdout": "Failed to initialize NVML: Driver/library version mismatch\nNVML library version: 610.43\n"}
    good = {"ok": True, "stderr": "",
            "stdout": "NVIDIA GeForce RTX 5090, 32607, 30231, 2376, 0, 0, 48, 27.31, 0000:01:00.0, 5, 5, 16, 16, 14001, 14001, GPU-abc\n"}
    check(mon._nvidia_failure(fail) == "Failed to initialize NVML: Driver/library version mismatch",
          f"positive: жалоба из stdout — это причина (got {mon._nvidia_failure(fail)!r})")
    check(mon._nvidia_failure(good) == "",
          "negative: строка с числами причиной не считается — это данные")
    mon.run = lambda *a, **k: fail
    st = mon.gpu_state()
    check(st["ok"] is False and st["gpus"] == [] and "mismatch" in st["error"],
          f"gpu_state: пустой список ВМЕСТЕ с причиной, а не молча (got {st})")
    sample = mon.gpu_sample()
    check(sample["ok"] is False and "mismatch" in sample["error"],
          f"gpu_sample: та же причина, а не «returned no GPU row» (got {sample})")
    mon.run = lambda *a, **k: fail_not_ok
    st = mon.gpu_state()
    check(st["ok"] is False and st.get("gpus") == [] and "mismatch" in st["error"],
          f"ok=False и пустой stderr: причина всё равно найдена в stdout (got {st})")
    check("mismatch" in mon.gpu_sample()["error"],
          "и у выборки тоже — обе ветки читают оба потока")

    mon.run = lambda *a, **k: good
    st = mon.gpu_state()
    check(st["ok"] is True and len(st["gpus"]) == 1 and st["gpus"][0]["name"].startswith("NVIDIA"),
          f"positive: живая карта читается как раньше (got {len(st.get('gpus', []))} строк)")

    # The reason must reach the NODE CARD, not stay stuck in the server's own
    # answer: the board draws nodes, and "no GPU" lives there (found by a
    # live check — the first version only put the field on server_obj, and
    # nothing changed on the board).
    import inspect
    import caravan.admin.topology as topo
    src = inspect.getsource(topo.topology_nodes) if hasattr(topo, "topology_nodes") else inspect.getsource(topo)
    check('"gpuError": server_obj.get("gpuError")' in src,
          "узел контроллера несёт gpuError дальше, к карточке")



# ── Secure Boot: signed modules ──────────────────────────────────────────────
# 2026-09-07: the update button installed the driver and only the driver. The
# module was built through DKMS, signed with an ephemeral kernel-build key,
# and after the reboot the kernel rejected the signature — the card
# disappeared entirely. The pins below cover that a SECOND package gets
# installed, that it's picked by the RUNNING kernel's series, and that a
# rejected module is named as the reason, not left as emptiness.
MODULES_POLICY = """linux-modules-nvidia-610-open-generic-hwe-24.04:
  Installed: (none)
  Candidate: 7.0.0-31.31~24.04.1
linux-modules-nvidia-610-open-generic:
  Installed: (none)
  Candidate: 6.8.0-139.139
linux-modules-nvidia-610-open-7.0.0-31-generic:
  Installed: (none)
  Candidate: 7.0.0-31.31~24.04.1
"""


def _fake_boot(sb="SecureBoot enabled", dpkg_installed=(), policy=MODULES_POLICY):
    def run(cmd, **kwargs):
        head = cmd[0]
        if head == "mokutil":
            return {"ok": True, "stdout": sb + "\n", "stderr": ""}
        if head == "apt-cache" and "policy" in cmd:
            return {"ok": True, "stdout": policy, "stderr": ""}
        if head == "dpkg-query":
            name = cmd[-1]
            if name in dpkg_installed:
                return {"ok": True, "stdout": f"{name} 7.0.0-31.31~24.04.1 install ok installed\n", "stderr": ""}
            return {"ok": True, "stdout": "", "stderr": ""}
        return {"ok": False, "stdout": "", "stderr": "unexpected " + " ".join(cmd)}
    gd.run = run
    gd.running_kernel = lambda: "7.0.0-31-generic"
    gd._os_release_id = lambda: "24.04"
    gd._status_cache.update(t=0.0, data=None)


def test_secure_boot():
    print("Secure Boot и подписанные модули:")
    _fake_boot()
    check(gd.secure_boot_enabled() is True, "positive: «SecureBoot enabled» читается как включённый")
    _fake_boot(sb="SecureBoot disabled")
    check(gd.secure_boot_enabled() is False, "negative: «SecureBoot disabled» — выключенный")
    _fake_boot(sb="This system doesn't support Secure Boot")
    check(gd.secure_boot_enabled() is False, "и невнятный ответ mokutil — тоже «нет»")

    _fake_boot()
    got = gd.signed_modules_package("nvidia-driver-610-open")
    check(got == "linux-modules-nvidia-610-open-generic-hwe-24.04",
          f"выбран HWE-метапакет: его версия начинается с серии работающего ядра 7.0.0-31 (got {got!r})")
    check(gd.signed_modules_package("nvidia-driver-610") == "",
          "разновидность не подменяется: для проприетарного драйвера открытые модули не предлагаются")
    check(gd.signed_modules_package("rm -rf /") == "" and gd.signed_modules_package("") == "",
          "имя не той формы даёт пустоту, а не строку для apt")

    # A kernel from a different series: the HWE candidate no longer fits, and
    # can't be taken — it would drag in YET ANOTHER kernel, and a module for
    # the current one would never show up.
    gd.running_kernel = lambda: "6.8.0-139-generic"
    check(gd.signed_modules_package("nvidia-driver-610-open") == "linux-modules-nvidia-610-open-generic",
          "на GA-ядре выбирается GA-метапакет — по версии, а не по порядку в списке")
    gd.running_kernel = lambda: "9.9.9-1-generic"
    check(gd.signed_modules_package("nvidia-driver-610-open") == "",
          "ни один кандидат не под это ядро → пусто, а не «первый попавшийся»")


def test_update_command():
    print("командная строка обновления:")
    gd.running_kernel = lambda: "7.0.0-31-generic"
    plain = gd._update_command("nvidia-driver-610-open", "")
    check(plain == ["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get",
                    "install", "-y", "--no-install-recommends", "nvidia-driver-610-open"],
          f"без Secure Boot — один apt-get, как было (got {plain})")
    both = gd._update_command("nvidia-driver-610-open", "linux-modules-nvidia-610-open-generic-hwe-24.04")
    line = both[-1]
    check(both[:4] == ["sudo", "-n", "bash", "-c"], f"с модулями — один шаг оболочки (got {both[:4]})")
    check("nvidia-driver-610-open linux-modules-nvidia-610-open-generic-hwe-24.04" in line,
          "оба пакета ставятся ОДНОЙ транзакцией apt")
    check("dkms remove" in line and "-k 7.0.0-31-generic" in line,
          "сборка DKMS для работающего ядра снимается: updates/dkms/ выше kernel/ в порядке поиска, "
          "и modprobe брал бы неподписанный модуль")
    check(line.rstrip().endswith("depmod -a 7.0.0-31-generic"),
          f"и зависимости пересчитываются последним шагом (got ...{line[-40:]!r})")
    check(" && " in line.split("dkms")[0],
          "снятие DKMS выполняется только если apt УСПЕЛ: иначе останемся без обоих модулей")


def test_update_installs_modules():
    print("обновление под Secure Boot:")
    import caravan.admin.status as status_mod
    started = []
    status_mod._start_shared_job = lambda cmd, tag: started.append((cmd, tag)) or {"ok": True, "tag": tag}
    _fake_boot()
    gd.available_packages = lambda: [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    gd.driver_update("nvidia-driver-610-open")
    cmd, tag = started[-1]
    line = cmd[-1]
    check("linux-modules-nvidia-610-open-generic-hwe-24.04" in line,
          f"positive: подписанные модули уезжают в apt ВМЕСТЕ с драйвером (got {line[:120]!r})")
    check("nvidia-driver-610-open" in line and tag == "driver:nvidia-driver-610-open",
          "и сам драйвер там же, метка задания не изменилась")

    _fake_boot(sb="SecureBoot disabled")
    gd.available_packages = lambda: [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    gd.driver_update("nvidia-driver-610-open")
    cmd, _ = started[-1]
    check(cmd[-1] == "nvidia-driver-610-open" and "bash" not in cmd,
          f"negative: без Secure Boot команда прежняя, ничего лишнего (got {cmd})")


def test_reboot_has_two_causes():
    print("перезагрузка: две причины, две надписи:")
    # The real file reader — before status() replaces it with a stub.
    real_reader = gd.reboot_pending_packages
    # One badge for two different reasons lied on a live host on 2026-09-07:
    # the versions already matched (610.43.02 on both sides), yet the chip
    # said it was "needed for the kernel to switch to it". What was actually
    # lit was Ubuntu's own marker about linux-image. The same class of defect
    # as "no GPU": one label standing in for two states.
    def status(running="595.84", installed_v="610.43.02-0ubuntu0.24.04.1",
               marker=False, pkgs=(), sb="SecureBoot disabled", loaded=True):
        _fake_boot(sb=sb)
        gd.installed_packages = lambda: [{"package": "nvidia-driver-610-open", "version": installed_v}]
        gd.available_packages = lambda: []
        gd.running_version = lambda: (running, "" if running else "no answer")
        gd.module_loaded = lambda name="nvidia": loaded
        gd._reboot_pending = lambda: marker
        gd.reboot_pending_packages = lambda: list(pkgs)
        gd._status_cache.update(t=0.0, data=None)
        return gd.driver_status(ttl=0)

    st = status()
    check(st["rebootForDriver"] is True and st["rebootPending"] is False,
          "positive: установлено новее работающего → причина именно драйверная")
    check(st["rebootRequired"] is True, "…и общий флаг для прежних читателей поднят")
    check(st["rebootPendingPackages"] == [], "пакетов ОС нет — список пуст, а не выдуман")

    st = status(running="610.43.02", marker=True,
                pkgs=("linux-image-7.0.0-31-generic", "linux-base"))
    check(st["rebootForDriver"] is False,
          "negative: версии совпали — драйверной причины НЕТ, что бы ни говорил маркер ОС")
    check(st["rebootPending"] is True, "но маркер ОС поднят отдельным полем")
    check(st["rebootPendingPackages"] == ["linux-image-7.0.0-31-generic", "linux-base"],
          f"и названо, ради чего ОС просит (got {st['rebootPendingPackages']})")
    check(st["rebootRequired"] is True, "общий флаг по-прежнему поднят — читатели не сломались")

    st = status(marker=True, pkgs=("linux-base",))
    check(st["rebootForDriver"] is True and st["rebootPending"] is True,
          "обе причины разом — обе и сказаны")

    st = status(running="610.43.02")
    check(st["rebootForDriver"] is False and st["rebootPending"] is False
          and st["rebootRequired"] is False,
          "ни одной причины — тишина, а не «на всякий случай»")

    st = status(running="610.43.02", marker=True)
    check(st["rebootPending"] is True and st["rebootPendingPackages"] == [],
          "маркер есть, списка пакетов нет — причина названа, состав не выдуман")

    # The file reader itself — against a real file: above it's stubbed out
    # entirely, and a mutant "don't strip the newline" would have sailed
    # through (found by a mutant).
    import tempfile
    real_pkgs = gd.REBOOT_MARKER_PKGS
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "reboot-required.pkgs"
            f.write_text("linux-image-7.0.0-31-generic\n\n  linux-base  \n")
            gd.REBOOT_MARKER_PKGS = str(f)
            got = real_reader()
            check(got == ["linux-image-7.0.0-31-generic", "linux-base"],
                  f"файл читается построчно, пустые строки и пробелы срезаны (got {got!r})")
            gd.REBOOT_MARKER_PKGS = str(Path(tmp) / "нет-такого")
            check(real_reader() == [],
                  "нет файла — пустой список, а не исключение наружу")
    finally:
        gd.REBOOT_MARKER_PKGS = real_pkgs

    st = status(running="", sb="SecureBoot enabled", loaded=False, marker=True,
                pkgs=("linux-base",))
    check(st["moduleRejected"] is True and st["rebootForDriver"] is False,
          "отвергнутая подпись драйверной причиной не становится — перезагрузка её не лечит")
    check(st["rebootPending"] is True,
          "…а маркер ОС остаётся как есть: это её повод, не наш")


def test_rejected_module_says_why():
    print("модуль отвергнут подписью:")
    _fake_boot()
    gd.installed_packages = lambda: [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    gd.available_packages = lambda: []
    gd.running_version = lambda: ("", "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver")
    gd.module_loaded = lambda name="nvidia": False
    gd._status_cache.update(t=0.0, data=None)
    st = gd.driver_status(ttl=0)
    check(st["moduleRejected"] is True,
          "positive: Secure Boot включён, пакеты стоят, модуль не загружен → сказано, что подпись отвергнута")
    check(st["rebootRequired"] is False,
          "и перезагрузка НЕ предлагается: она уже была и модуль не загрузила")
    check(st["secureBoot"] is True and st["signedModules"].startswith("linux-modules-nvidia-610-open"),
          f"панель знает, какого пакета не хватает (got {st['signedModules']!r})")
    check(st["signedModulesInstalled"] is False, "и что он не стоит")
    check("Secure Boot rejected" in st["runningError"]
          and "linux-modules-nvidia-610-open" in st["runningError"],
          f"и та же причина дописана в текст, который панель уже показывает дословно "
          f"(got {st['runningError']!r})")
    check(st["runningError"].startswith("NVIDIA-SMI has failed"),
          "поверх исходного сообщения nvidia-smi, а не вместо него")

    gd.module_loaded = lambda name="nvidia": True
    gd.running_version = lambda: ("610.43.02", "")
    gd._status_cache.update(t=0.0, data=None)
    st = gd.driver_status(ttl=0)
    check(st["moduleRejected"] is False,
          "negative: модуль загружен и версия читается — обвинения нет")

    _fake_boot(sb="SecureBoot disabled")
    gd.installed_packages = lambda: [{"package": "nvidia-driver-610-open", "version": "610.43.02-0ubuntu0.24.04.1"}]
    gd.available_packages = lambda: []
    gd.running_version = lambda: ("", "no card")
    gd.module_loaded = lambda name="nvidia": False
    gd._status_cache.update(t=0.0, data=None)
    st = gd.driver_status(ttl=0)
    check(st["moduleRejected"] is False and st["secureBoot"] is False,
          "без Secure Boot незагруженный модуль подписью не объясняется — это была бы выдумка")
    check(st["rebootRequired"] is True,
          "…и обычная щель «поставили, не перезагрузились» остаётся как была")


_orig_installed = gd.installed_packages
test_reading()
test_status()
test_update_is_guarded()
test_auto()
test_watch_schedule()
test_unreadable_card_says_why()
test_secure_boot()
test_update_command()
test_update_installs_modules()
test_rejected_module_says_why()
test_reboot_has_two_causes()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all gpu-driver snapshots hold")
