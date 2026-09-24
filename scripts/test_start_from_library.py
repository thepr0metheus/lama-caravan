#!/usr/bin/env python3
"""Value snapshot: a cell reads its model wherever it lives.

Until now a cell could only start from the models disk: every path was that
directory plus the relative name. A model moved into a library was then simply
gone — the start said "Model not found" about a file sitting safely on the NAS.

What is pinned, each claim together with its opposite:

* The paths: asked without a snapshot, every file is on the models disk — the
  answer the controller gave before libraries existed, and the one a command
  that is only being SHOWN still gets. Asked with one, a file that lives in a
  library is read from the library's root.
* The loading mode: a model read over the network is never mapped. llama.cpp
  keeps the input layer on the CPU and reads it from the file for every token,
  so a share that blinks takes a running cell down with it. --mmap asked for by
  the operator is overruled; --load-mode keeps everything else it said (mlock
  stays mlock, direct I/O stays direct I/O) and loses only the mapping. One
  file over the wire is enough: --no-mmap is a property of the process, not of
  a file.
* The script: a library path brings one guard more, and it comes first — the
  library's own mark in its root. Without it the share did not mount, and what
  sits under the mount point is the local disk, so the file test alone would
  report the model missing and send its reader looking for a deleted file.
* A local start is unchanged, flag for flag.
* The choice: "disk" brings the model home and the cell starts when it is here
  (the promise rides in the move's manifest, so it survives a closed tab and a
  restarted controller); "library" starts now and reads it there; nobody to ask
  — a schedule, a restart after a crash — means home if there is room and read
  where it lies if there is not. The space arithmetic is the planner's alone:
  its "no-room" refusal IS the fallback.
* The schedule brings a model home before its window opens, once per window,
  and does NOT start the cell then: the window has not come.
* A client cell is told where this controller reads each of its files — on
  this disk, in a library, a folder — so a scout that has the same file there
  (the one on the controller's own machine, a library mounted at the same
  path) reads it in place instead of copying it. A library model is no longer
  refused: the scout that lacks the library names it itself.

Run: python3 scripts/test_start_from_library.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.config_builder import (  # noqa: E402
    build_local_llama_command, model_paths, no_mmap_mode,
)
from caravan.admin.launch import render_launch_script  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402

_fail = []
LIB = {"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib",
       "files": [{"path": "q/Qwen/Q8/q.gguf", "size": 8}, {"path": "m/mm.gguf", "size": 2}]}
CFG = {"MODEL_FILE": "q/Qwen/Q8/q.gguf", "PORT": "22001", "LLAMA_MODELS_DIR": "/m"}


def refused(fn):
    """The code of the refusal a call raises, or None when it does not."""
    from caravan.common.errors import AppError
    try:
        fn()
    except AppError as exc:
        return getattr(exc, "code", "") or str(exc)
    return None


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def here(*rels):
    """A snapshot in which the named files are on this disk and the rest of the
    library's list is only in the library."""
    on_disk = {f"/m/{rel}" for rel in rels}
    return Locations([LIB], exists=lambda p: p in on_disk)


def cmd(config, where=None):
    return build_local_llama_command(config, llama_home="/h", locations=where)[1:]


def section_paths():
    print("где читается файл:")
    plain = model_paths(CFG)
    check([(p.where, p.path) for p in plain.values()] == [("local", "/m/q/Qwen/Q8/q.gguf")],
          f"без снимка — всё на диске моделей: так отвечал контроллер до библиотек, и так же отвечает "
          f"команда, которую только показывают (got {[(p.where, p.path) for p in plain.values()]})")
    lib = model_paths(CFG, here())
    check([(p.where, p.path) for p in lib.values()] == [("library", "/mnt/lib/q/Qwen/Q8/q.gguf")],
          f"файла на диске нет, а библиотека его держит — читаем из библиотеки (got {[(p.where, p.path) for p in lib.values()]})")
    both = model_paths(CFG, here("q/Qwen/Q8/q.gguf"))
    check([(p.where, p.path) for p in both.values()] == [("local", "/m/q/Qwen/Q8/q.gguf")],
          f"negative: файл есть и тут, и там — читаем свой диск, а не сеть (got {[(p.where, p.path) for p in both.values()]})")
    gone = model_paths({**CFG, "MODEL_FILE": "nope.gguf"}, here())
    check([(p.where, p.path) for p in gone.values()] == [("missing", "/m/nope.gguf")],
          f"negative: нигде нет — «нет», и путь там, где его ждали (got {[(p.where, p.path) for p in gone.values()]})")
    empty = model_paths({**CFG, "MMPROJ_FILE": "", "SPEC_DRAFT_MODEL_FILE": ""}, here())
    check(list(empty) == ["MODEL_FILE"],
          f"negative: незаполненное поле ни о чём не спрашивают (got {list(empty)})")

    # Домашний каталог в сохранённом конфиге пишется двумя способами, и оба
    # значат одну папку. Найдено живьём 2026-09-16: раскрывали только один —
    # файл, лежащий на диске, выглядел «только в библиотеке», и ячейка
    # стартовала по пути в библиотеку, откуда его только что увезли.
    import os as _os
    home = _os.path.expanduser("~")
    for root, why in (("$HOME/m", "$HOME — так его пишет генератор скрипта запуска"),
                      ("${HOME}/m", "${HOME} — та же запись в фигурных скобках"),
                      ("~/m", "~ — так его набирает человек")):
        spelled = model_paths({**CFG, "LLAMA_MODELS_DIR": root})["MODEL_FILE"]
        check(spelled.path == f"{home}/m/q/Qwen/Q8/q.gguf",
              f"{why}: путь настоящий, а не четыре буквы, которые в кавычках никто не раскроет (got {spelled.path})")
    plain = model_paths({**CFG, "LLAMA_MODELS_DIR": "/abs/models"})["MODEL_FILE"]
    check(plain.path == "/abs/models/q/Qwen/Q8/q.gguf",
          f"negative: обычный абсолютный путь не трогаем (got {plain.path})")
    lives = Locations([LIB], exists=lambda p: p == f"{home}/m/q/Qwen/Q8/q.gguf")
    at_home = model_paths({**CFG, "LLAMA_MODELS_DIR": "$HOME/m"}, lives)["MODEL_FILE"]
    check(at_home.where == "local",
          f"и файл, который там лежит, найден на диске, а не в библиотеке (got {at_home.where})")


def section_mmap():
    print("модель по сети не отображается в память:")
    local = cmd(CFG)
    check("--no-mmap" not in local and "--model" in local and local[local.index("--model") + 1] == "/m/q/Qwen/Q8/q.gguf",
          f"negative: старт со своего диска не меняется — ни флага сверх того, что попросили (got {local})")
    over = cmd(CFG, here())
    check("--no-mmap" in over and over[over.index("--model") + 1] == "/mnt/lib/q/Qwen/Q8/q.gguf",
          f"из библиотеки: путь библиотеки и --no-mmap (got {over})")
    asked = cmd({**CFG, "MMAP": "1"}, here())
    check("--no-mmap" in asked and "--mmap" not in asked,
          f"оператор попросил отображение, а файл в сети — решает не он: обрыв шары уронил бы работающую ячейку "
          f"(got {[x for x in asked if 'mmap' in x]})")
    check(cmd({**CFG, "MMAP": "1"}).count("--mmap") == 1,
          "negative: на своём диске его «да» остаётся в силе")
    for mode, left, why in (("mmap+mlock", "mlock", "просили держать в памяти — держим, только без отображения"),
                            ("mmap", "none", "просили одно отображение — не остаётся ничего"),
                            ("mlock", "mlock", "negative: отображения и не просили — не трогаем"),
                            ("dio", "dio", "negative: прямое чтение не через отображение — остаётся как есть"),
                            ("none", "none", "negative: и так ничего")):
        got = cmd({**CFG, "LOAD_MODE": mode}, here())
        at = got.index("--load-mode") + 1 if "--load-mode" in got else -1
        check(at > 0 and got[at] == left and "--no-mmap" not in got,
              f"{mode} → {left}: {why} (got {got[at] if at > 0 else 'нет --load-mode'}, "
              f"no-mmap={'--no-mmap' in got})")
        check(no_mmap_mode(mode) == left, f"то же правило отдельно: no_mmap_mode({mode}) = {left}")
    check(cmd({**CFG, "LOAD_MODE": "mmap+mlock"})[-2:] != ["--load-mode", "mlock"],
          "negative: со своего диска режим загрузки такой, каким его написали")
    mm = cmd({**CFG, "MMPROJ_FILE": "m/mm.gguf"}, here("q/Qwen/Q8/q.gguf"))
    check("--no-mmap" in mm and mm[mm.index("--model") + 1] == "/m/q/Qwen/Q8/q.gguf"
          and mm[mm.index("--mmproj") + 1] == "/mnt/lib/m/mm.gguf",
          f"веса здесь, а mmproj в библиотеке — каждый читается со своего места, но отображения нет: "
          f"--no-mmap относится к процессу, а не к файлу (got {mm})")


def section_script():
    print("скрипт запуска:")
    local = render_launch_script(CFG)
    check('[ -f /m/q/Qwen/Q8/q.gguf ]' in local and ".caravan-store.json" not in local,
          "negative: путь со своего диска — одна проверка, файл на месте; метки хранилища тут не при чём")
    over = render_launch_script(CFG, here())
    lines = [ln for ln in over.splitlines() if ln.startswith("[ -f")]
    check(lines == ['[ -f /mnt/lib/.caravan-store.json ] || { echo "The library NAS is not mounted at /mnt/lib'
                    ' — the model stays there" >&2; exit 1; }',
                    '[ -f /mnt/lib/q/Qwen/Q8/q.gguf ] || { echo "Model not found: /mnt/lib/q/Qwen/Q8/q.gguf"'
                    ' >&2; exit 1; }'],
          f"сначала метка библиотеки с её именем, потом файл: без метки шара не смонтирована, и «модели нет» "
          f"отправило бы читателя лога искать удалённую модель вместо монтирования (got {lines})")
    check("--no-mmap" in over and "/mnt/lib/q/Qwen/Q8/q.gguf" in over.split("exec ")[1],
          "и запускающая строка читает библиотеку без отображения")
    both = render_launch_script({**CFG, "MMPROJ_FILE": "m/mm.gguf"}, here())
    marks = [ln for ln in both.splitlines() if ".caravan-store.json" in ln]
    order = [ln[:12] for ln in both.splitlines() if ln.startswith("[ -f")]
    check(len(marks) == 1 and len(order) == 3 and ".caravan" in [ln for ln in both.splitlines() if ln.startswith("[ -f")][0],
          f"из библиотеки читаются оба файла — метку проверяем ОДИН раз и раньше файлов: "
          f"это одна и та же шара (got {len(marks)} проверок метки на {len(order)} сторожей)")
    mixed = render_launch_script({**CFG, "MMPROJ_FILE": "m/mm.gguf"}, here("m/mm.gguf"))
    check('[ -f /m/m/mm.gguf ]' in mixed and len([ln for ln in mixed.splitlines() if ".caravan-store.json" in ln]) == 1,
          "negative: свой файл проверяется как свой, метка — только за тот, что в библиотеке")


def section_scout_told_where():
    print("скауту сказано, где контроллер читает каждый файл:")
    import tempfile
    from caravan.admin import fleet_clients
    with tempfile.TemporaryDirectory() as tmp:
        models = Path(tmp) / "models"
        (models / "l").mkdir(parents=True)
        (models / "l" / "local.gguf").write_bytes(b"x" * 5)
        (models / "seam" / "FP32").mkdir(parents=True)
        sent = []

        class FakeScout:
            def post(self, path, payload, timeout=0):
                sent.append((path, payload))
                return {"ok": True}

        saved = {k: getattr(fleet_clients, k) for k in
                 ("_scout", "current_locations", "assert_server_cell_port_available", "upsert_server_slot",
                  "move_server_cell")}
        fleet_clients._scout = lambda host_id: FakeScout()
        fleet_clients.current_locations = lambda wait=False: Locations([LIB], exists=os.path.isfile)
        fleet_clients.assert_server_cell_port_available = lambda *a, **k: None
        fleet_clients.upsert_server_slot = lambda *a, **k: None
        fleet_clients.move_server_cell = lambda *a, **k: None
        try:
            base = {"LLAMA_MODELS_DIR": str(models), "PORT": "22021"}
            fleet_clients.client_llama_start({"hostId": "box-a", "port": 22021, "modelPath": "l/local.gguf",
                                              "config": {**base, "MMPROJ_FILE": "m/mm.gguf",
                                                         "SPEC_DRAFT_MODEL_FILE": "gone/draft.gguf"}})
            fleet_clients.client_llama_start({"hostId": "box-a", "port": 22022, "modelPath": "q/Qwen/Q8/q.gguf",
                                              "config": {**base, "PORT": "22022"}})
            fleet_clients.client_llama_start({"hostId": "box-a", "port": 22023,
                                              "config": {**base, "PORT": "22023", "RUNNER": "seamless",
                                                         "MODEL_FILE": "seam/FP32", "SEAMLESS_TGT_LANG": "rus"}})
        finally:
            for k, v in saved.items():
                setattr(fleet_clients, k, v)
        told = [payload.get("inPlace") for _path, payload in sent]
        check(told[:1] == [{"l/local.gguf": {"path": str(models / "l" / "local.gguf"), "size": 5},
                            "m/mm.gguf": {"path": "/mnt/lib/m/mm.gguf", "library": "NAS", "size": 2}}],
              f"файл на диске контроллера — путь и настоящий размер; файл в библиотеке — путь, имя библиотеки и "
              f"размер из её списка; negative: файла нет нигде — подсказки нет (got {told[:1]})")
        check(told[1:2] == [{"q/Qwen/Q8/q.gguf": {"path": "/mnt/lib/q/Qwen/Q8/q.gguf", "library": "NAS",
                                                   "size": 8}}],
              f"модель только в библиотеке — уходит скауту с путём библиотеки, а не отказом (got {told[1:2]})")
        check(told[2:] == [{"seam/FP32": {"path": str(models / "seam" / "FP32"), "dir": True}}],
              f"модель-папка (seamless) — сказано, что это папка: её не скачать, только прочесть на месте "
              f"(got {told[2:]})")


def section_every_start():
    print("скрипт пишется заново на каждом старте:")
    from caravan.admin import cell_ops

    wrote, slot = [], {"config": dict(CFG), "artifact": {"startScript": "/old/start.sh"}}
    saved = {k: getattr(cell_ops, k) for k in
             ("is_controller_host", "for_config", "cell_service_status", "listening_pid",
              "cell_service_action", "state", "save_admin_state", "uses_command_path",
              "write_server_cell_artifacts", "current_locations", "topo", "client_llama_start")}

    class Topo:
        def slot(self, host, port):
            return slot

        def put_slot(self, host, port, value):
            slot.update(value)

    cell_ops.is_controller_host = lambda host: True
    cell_ops.for_config = lambda cfg: type("R", (), {"vram_gated": False})()
    cell_ops.cell_service_status = lambda port: {"ActiveState": "inactive"}
    cell_ops.listening_pid = lambda port: (0, "")
    cell_ops.cell_service_action = lambda port, action: {"ok": True}
    cell_ops.client_llama_start = lambda payload: {"ok": True, "sent": payload}
    cell_ops.state = lambda: {}
    cell_ops.save_admin_state = lambda: None
    cell_ops.uses_command_path = lambda cfg: False
    waits = []
    snapshot = here("q/Qwen/Q8/q.gguf")
    cell_ops.current_locations = lambda wait=False: (waits.append(wait), snapshot)[1]
    cell_ops.write_server_cell_artifacts = (
        lambda host, port, cfg, locations=None: wrote.append(locations) or {"startScript": "/new/start.sh"})
    cell_ops.topo = Topo()
    client = []
    try:
        cell_ops.server_cell_action({"hostId": "controller", "port": 22001, "action": "start"})
        cell_ops.server_cell_action({"hostId": "controller", "port": 22001, "action": "restart"})
        # A client cell downloads its model FROM THIS CONTROLLER, and the
        # controller serves what is on its own disk.
        cell_ops.is_controller_host = lambda host: False
        slot["model"] = CFG["MODEL_FILE"]
        cell_ops.current_locations = lambda wait=False: here()
        client.append(refused(lambda: cell_ops.server_cell_action(
            {"hostId": "forge", "port": 22021, "action": "start"})))
        cell_ops.current_locations = lambda wait=False: here("q/Qwen/Q8/q.gguf")
        client.append(cell_ops.server_cell_action({"hostId": "forge", "port": 22021, "action": "start"}).get("ok"))
    finally:
        for k, v in saved.items():
            setattr(cell_ops, k, v)
    check(client[0] is None,
          f"defect-history: клиентская ячейка с моделью в библиотеке больше не отказана — скаут прочтёт её на "
          f"месте, если у него та же библиотека по тому же пути, а если нет — сам назовёт её (got {client[0]})")
    check(client[1] is True,
          f"negative: модель на диске контроллера — клиентская ячейка стартует как раньше (got {client[1]})")
    check(wrote == [snapshot, snapshot],
          f"каждый старт и перезапуск пишет start.sh заново, даже когда он уже есть: между двумя стартами "
          f"модель могла переехать, а старый скрипт всё ещё показывает на этот диск (got {len(wrote)} раз(а))")
    check(waits == [True, True],
          f"и снимок берётся СВЕЖИЙ: старт — единственное место, которому можно подождать NAS, "
          f"иначе ячейка поедет по памяти пятнадцатисекундной давности (got {waits})")


def section_choice():
    print("откуда запускать — решение:")
    from caravan.admin import cell_ops

    calls = []
    saved = {k: getattr(cell_ops, k) for k in ("model_paths",)}

    class Runner:
        def start(self, paths, target, source_id=None, then=None):
            calls.append({"paths": list(paths), "to": target, "from": source_id, "then": then})
            if "no-room" in paths[0]:
                from caravan.admin.store_moves import MoveRefused
                raise MoveRefused("the disk has no room", "no-room")
            return {"id": "mv-1"}

    import caravan.admin.store_moves as sm
    keep_runner = sm.runner
    sm.runner = lambda: Runner()
    try:
        home = cell_ops.bring_home("controller", 22001, dict(CFG), "", here("q/Qwen/Q8/q.gguf"))
        check(home is None and calls == [],
              f"модель на этом диске — решать нечего, ячейка стартует сразу (got {home}, {calls})")
        cell_ops.bring_home("controller", 22001, dict(CFG), "library", here())
        check(calls == [], "«запустить из библиотеки» — ни одного переноса: читаем там, где лежит")
        job = cell_ops.bring_home("controller", 22001, dict(CFG), "disk", here())
        check(job == {"id": "mv-1"} and len(calls) == 1
              and calls[0] == {"paths": ["q/Qwen/Q8/q.gguf"], "to": "local", "from": "lib-a",
                               "then": {"start": {"hostId": "controller", "port": 22001}}},
              f"«вернуть и запустить» — перенос из библиотеки на этот диск, и задание НЕСЁТ обещание "
              f"запустить ячейку, когда файл приедет (got {calls})")
        calls.clear()
        auto = cell_ops.bring_home("controller", 22001, dict(CFG), "", here())
        check(auto == {"id": "mv-1"} and calls[0]["then"],
              "никого не спросить (расписание, перезапуск после сбоя) — модель едет домой, раз место есть")
        calls.clear()
        nofetch = cell_ops.bring_home("controller", 22001, dict(CFG), "", here(), then_start=False)
        check(nofetch == {"id": "mv-1"} and calls[0]["then"] == {},
              f"предзагрузка перед окном расписания — тот же перенос, но БЕЗ обещания запустить: "
              f"окно ещё не наступило (got {calls[0]['then']})")
        calls.clear()
        tight = {**CFG, "MODEL_FILE": "q/no-room.gguf"}
        lib = {**LIB, "files": [{"path": "q/no-room.gguf", "size": 8}]}
        from caravan.admin.model_locator import Locations
        nowhere = Locations([lib], exists=lambda p: False)
        fell = refused(lambda: cell_ops.bring_home("controller", 22001, tight, "", nowhere))
        check(fell is None,
              "места на диске нет, а спросить некого — читаем из библиотеки: арифметика места живёт "
              "в планировщике, второй копии её здесь нет")
        hand = refused(lambda: cell_ops.bring_home("controller", 22001, tight, "disk", nowhere))
        check(hand == "no-room",
              f"negative: но если «вернуть» попросили руками — отказ с причиной, а не тихая подмена решения (got {hand})")
    finally:
        sm.runner = keep_runner
        for k, v in saved.items():
            setattr(cell_ops, k, v)


def section_prefetch():
    print("возврат заранее, перед окном расписания:")
    from caravan.admin import cell_schedule as cs

    def at(wday, hhmm):
        hour, minute = (int(x) for x in hhmm.split(":"))
        return time.struct_time((2026, 9, 14 + wday, hour, minute, 0, wday, 257 + wday, 0))

    sched = {"enabled": True, "start": "22:00", "stop": "08:00", "days": [1]}
    for when, left, why in ((at(1, "21:45"), 15, "за 15 минут до окна"),
                            (at(1, "22:00"), 0, "в самое начало окна — ноль, а не сутки"),
                            (at(1, "12:00"), 600, "днём того же дня"),
                            (at(2, "09:00"), 6 * 1440 + 22 * 60 - 9 * 60, "окно только по вторникам — ждём следующей недели")):
        check(cs.minutes_to_window(sched, when) == left,
              f"{why}: {left} мин (got {cs.minutes_to_window(sched, when)})")
    check(cs.minutes_to_window({"start": "08:00", "stop": "08:00", "days": [1]}, at(1, "07:00")) is None,
          "negative: окно нулевой длины не открывается никогда — не «сейчас»")
    check(cs.minutes_to_window({"start": "22:00", "stop": "08:00", "days": []}, at(1, "07:00")) == 15 * 60,
          "пустой список дней — это «каждый день», как и в самом расписании")

    asked = []
    keep = cs.PREFETCH_MIN
    import caravan.admin.cell_ops as ops
    keep_bring, keep_where = ops.bring_home, None
    import caravan.admin.model_locator as locator
    keep_where = locator.current_locations
    ops.bring_home = lambda h, p, c, choice, where, then_start=True: asked.append((p, choice, then_start)) or {"id": "mv-2"}
    locator.current_locations = lambda wait=False: here()
    try:
        slot = {"hostId": "controller", "port": 22001, "config": dict(CFG)}
        # Сначала «рано» — на чистой записи: сделай это после успешной
        # предзагрузки, и сторож «раз на окно» скрыл бы отсутствие проверки.
        check(cs.prefetch_tick(slot, sched, at(1, "12:00")) is False and asked == [],
              f"negative: за десять часов до окна — рано: место занято зря, и модель успела бы устареть (got {asked})")
        check(cs.prefetch_tick(slot, sched, at(1, "21:45")) is True and asked == [(22001, "", False)],
              f"за 15 минут до окна модель едет домой, и ячейка при этом НЕ запускается (got {asked})")
        check(cs.prefetch_tick(slot, sched, at(1, "21:46")) is False and len(asked) == 1,
              f"negative: следующий тик через минуту второй раз тот же перенос не заводит (got {len(asked)})")
    finally:
        ops.bring_home, locator.current_locations = keep_bring, keep_where
        cs.PREFETCH_MIN = keep


def main():
    section_paths()
    section_mmap()
    section_script()
    section_every_start()
    section_scout_told_where()
    section_choice()
    section_prefetch()
    print()
    if _fail:
        print(f"start from library FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("start from library OK: где файл, режим загрузки, сторожа скрипта, выбор при старте, "
          "предзагрузка по расписанию")
    return 0


if __name__ == "__main__":
    sys.exit(main())
