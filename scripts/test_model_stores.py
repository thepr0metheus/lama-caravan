#!/usr/bin/env python3
"""Value snapshot: model stores — where models live and whether each place is there.

What is pinned, each claim together with its opposite:

* The rule, StoreStatus.judge: the order a store is judged in; a library with
  no mark is "not mounted" and carries NO numbers (they would be the local
  disk's, since the bare mount point sits on it); a mark with another id is
  "foreign"; the controller's own directory needs no mark at all.
* The child process, run for real on temporary directories: a look reports
  the mark, the room and (for a library) what is inside, skipping hidden and
  system folders and macOS's ._ shadows; a missing directory is a "no", not an
  error; a claim refuses a bare directory, writes the mark only when forced,
  and ADOPTS a mark already there instead of overwriting it.
* The deadline: a child that does not answer is "unknown", and the caller is
  not kept waiting while it dies.
* The registry: add refuses empty, relative, duplicate and nested paths and
  saves a library in one write; remove refuses the builtin directory and
  unknown ids and leaves the files and the mark alone; statuses are reused for
  the TTL and measured again on force, after the TTL, or when the path moved.

Run: python3 scripts/test_model_stores.py
"""
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import model_stores as ms  # noqa: E402

_fail = []
GB = 2 ** 30
LIB = ms.ModelStore("lib-a", "NAS", "/mnt/lib", "library")
LOCAL = ms.ModelStore("local", "", "/home/x/models", "local", builtin=True)


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except ms.StoreRefused as exc:
        return exc.code
    return None


def judge(store, **probe):
    base = {"ok": True, "exists": True, "writable": True, "free": 900 * GB, "total": 1000 * GB}
    return ms.StoreStatus.judge(store, {**base, **probe}, 100).to_json()


class FakeProbe:
    """StoreProbe's two questions, answered from tables, every call recorded."""

    def __init__(self, claim=None):
        self.looks = {}
        self.claim_answer = claim
        self.calls = []

    def look(self, root, listing=False, limit=ms.LIST_LIMIT):
        self.calls.append(("look", root, listing))
        return self.looks.get(root, {"ok": True, "exists": True, "writable": True, "free": 900 * GB, "total": 1000 * GB})

    def claim(self, root, store_id, name, force=False):
        self.calls.append(("claim", root, store_id, name, force))
        answer = self.claim_answer
        return answer(root, store_id, name, force) if callable(answer) else answer


def marks(root, store_id, name, force):
    return {"ok": True, "exists": True, "adopted": False, "marker": {"id": store_id, "name": name}}


def make_registry(probe, clock=None, local="/home/x/models"):
    state, saves = {}, []
    reg = ms.StoreRegistry(state=lambda: state, save=lambda: saves.append(json.dumps(state.get("modelStores"))),
                           local_root=lambda: local, probe=probe, clock=clock or (lambda: 1000.0))
    return reg, state, saves


def section_rule():
    print("правило состояний:")
    ok = judge(LIB, marker={"id": "lib-a"}, files=3, bytes=7 * GB, folders=[{"name": "m", "bytes": 7 * GB, "files": 3}], more=0)
    check(ok["state"] == "ok" and ok["free"] == 900 * GB and ok["files"] == 3 and ok["size"] == 7 * GB and ok["folders"][0]["name"] == "m",
          f"библиотека на месте, со своей меткой, место есть — ok и с цифрами (got {ok})")
    bare = judge(LIB, marker=None)
    check(bare["state"] == "not-mounted" and not ({"free", "total", "files", "size", "folders"} & set(bare)),
          f"без метки — «не смонтировано» и НИ ОДНОЙ цифры: это были бы цифры локального диска под пустой точкой монтирования (got {bare})")
    foreign = judge(LIB, marker={"id": "lib-b", "name": "other"})
    check(foreign["state"] == "foreign" and "other" in foreign["detail"] and "free" not in foreign,
          f"чужая метка — «здесь другая библиотека», с её именем и без цифр (got {foreign})")
    local = judge(LOCAL, marker=None)
    check(local["state"] == "ok" and local["free"] == 900 * GB,
          f"negative: собственному каталогу контроллера метка не нужна (got {local})")
    ro = judge(LIB, marker={"id": "lib-a"}, writable=False)
    check(ro["state"] == "read-only" and ro["free"] == 900 * GB, f"записать нельзя — «только чтение», цифры есть (got {ro})")
    low = judge(LIB, marker={"id": "lib-a"}, free=ms.LOW_SPACE_BYTES - 1)
    edge = judge(LIB, marker={"id": "lib-a"}, free=ms.LOW_SPACE_BYTES)
    check(low["state"] == "low-space" and edge["state"] == "ok",
          f"мало места — строго ниже порога; ровно порог — ok (got {low['state']}, {edge['state']})")
    missing = ms.StoreStatus.judge(LIB, {"ok": True, "exists": False}, 100).to_json()
    check(missing["state"] == "missing" and "/mnt/lib" in missing["detail"], f"папки нет — «папки нет» и путь (got {missing})")
    dead = ms.StoreStatus.judge(LIB, {"ok": False, "timeout": True, "error": "no answer in 8 s"}, 100).to_json()
    check(dead["state"] == "unknown" and dead["detail"] == "no answer in 8 s" and dead["checkedAt"] == 100,
          f"не ответил — «не отвечает», причина словами и время замера (got {dead})")
    order = judge(LIB, marker=None, writable=False, free=1)
    check(order["state"] == "not-mounted",
          f"порядок: нет метки важнее «только чтения» и «мало места» — те цифры сняты не с той папки (got {order['state']})")
    garbage = ms.StoreStatus.judge(LIB, None, 5).to_json()
    check(garbage["state"] == "unknown", f"negative: вместо ответа пробника ничего — «не знаю», а не ok (got {garbage})")


def section_child():
    print("дочерний процесс на настоящих папках:")
    probe = ms.StoreProbe(timeout=60)
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp) / "lib"
        (lib / "Qwen" / "unsloth" / "Q4").mkdir(parents=True)
        (lib / "Qwen" / "unsloth" / "Q4" / "q.gguf").write_bytes(b"x" * 3000)
        (lib / "Qwen" / "unsloth" / "Q4" / "._q.gguf").write_bytes(b"y" * 10)
        (lib / "Small").mkdir()
        (lib / "Small" / "s.gguf").write_bytes(b"x" * 100)
        for system in ("#recycle", "@eaDir", ".hidden"):
            (lib / system).mkdir()
            (lib / system / "old.gguf").write_bytes(b"x" * 5000)
        (lib / "root.gguf").write_bytes(b"x" * 50)
        (lib / "notes.txt").write_text("not a model")

        # The refusal gets a directory of its own: were it the same one, a broken
        # refusal would leave a mark behind and fail the next pin as well.
        empty = Path(tmp) / "bare"
        empty.mkdir()
        bare = probe.claim(empty, "lib-bare", "NAS")
        check(bare.get("refused") == "not-a-mount" and not (empty / ms.MARKER_NAME).exists(),
              f"голая папка (не точка монтирования, без метки) — отказ, и метка НЕ записана (got {bare})")
        forced = probe.claim(lib, "lib-new", "NAS", force=True)
        mark = json.loads((lib / ms.MARKER_NAME).read_text())
        check(forced.get("adopted") is False and mark["id"] == "lib-new" and mark["name"] == "NAS",
              f"подтверждено — метка записана с id и именем (got {forced})")
        before = (lib / ms.MARKER_NAME).read_text()
        again = probe.claim(lib, "lib-other", "other name")
        check(again.get("adopted") is True and again["marker"]["id"] == "lib-new" and (lib / ms.MARKER_NAME).read_text() == before,
              f"метка уже есть — её УСЫНОВЛЯЕМ, а не переписываем: та же библиотека с другого хоста остаётся собой (got {again})")

        look = probe.look(lib, listing=True, limit=2)
        names = [f["name"] for f in look.get("folders", [])]
        check(look.get("ok") is True and (look.get("marker") or {}).get("id") == "lib-new"
              and look.get("writable") is True and look.get("total", 0) > 0,
              f"взгляд: метка, запись, место (got keys {sorted(look)})")
        check(look.get("files") == 3 and look.get("bytes") == 3150,
              f"внутри считаются только модели: ._-тени macOS, #recycle и @eaDir Synology, скрытые папки и не-модели не в счёт "
              f"(got {look.get('files')}, {look.get('bytes')})")
        check(names == ["Qwen", "Small"] and look.get("more") == 1,
              f"верхние папки — крупные первыми, по лимиту, остаток назван числом, а не спрятан (got {names}, more={look.get('more')})")
        entries = [e[:2] for e in look.get("entries", [])]
        check(entries == [["Qwen/unsloth/Q4/q.gguf", 3000], ["Small/s.gguf", 100], ["root.gguf", 50]]
              and all(abs(e[2] - time.time()) < 600 for e in look.get("entries", [])) and look.get("entriesMore") == 0,
              f"тот же обход называет GGUF-файлы для дерева: путь от корня, размер, время; тени macOS, #recycle, @eaDir и скрытые — нет (got {entries})")
        capped = probe.look(lib, listing=True, files_limit=2)
        check([e[0] for e in capped.get("entries", [])] == ["Qwen/unsloth/Q4/q.gguf", "Small/s.gguf"] and capped.get("entriesMore") == 1,
              f"список файлов обрезан лимитом — остаток назван числом (got {capped.get('entries')}, {capped.get('entriesMore')})")
        plain = probe.look(lib)
        check("folders" not in plain and "files" not in plain and plain.get("ok") is True,
              "negative: без просьбы перечислять — только состояние, без обхода папок")
        gone = probe.look(Path(tmp) / "nope")
        check(gone == {"ok": True, "exists": False}, f"папки нет — это ответ «нет», а не ошибка пробника (got {gone})")

        # A model that is a whole folder — a whisper cache, a checkpoint. The
        # library has to name it as one thing, or a moved cache would vanish
        # from the page and have no way back.
        cache = lib / "whisper" / "models--Systran--faster-whisper-large-v3"
        (cache / "blobs").mkdir(parents=True)
        (cache / "snapshots" / "abc").mkdir(parents=True)
        (cache / "blobs" / "deadbeef").write_bytes(b"x" * 1000)
        (cache / "snapshots" / "abc" / "model.safetensors").symlink_to("../../blobs/deadbeef")
        (lib / "sd" / "ckpt").mkdir(parents=True)
        (lib / "sd" / "ckpt" / "model.safetensors").write_bytes(b"y" * 400)
        folders = probe.look(lib, listing=True)
        dirs = [(d[0], d[1], d[2]) for d in folders.get("dirs", [])]
        check(dirs == [("sd/ckpt", "safetensors", 400),
                       ("whisper/models--Systran--faster-whisper-large-v3", "whisper", 1000)],
              f"папка-модель названа целиком: путь, вид и вес — и ссылка внутри кэша НЕ считается вторым разом "
              f"(сам блоб уже посчитан) (got {dirs})")
        check(not any(e[0].startswith("whisper/") or e[0].startswith("sd/") for e in folders.get("entries", [])),
              f"negative: файлы ВНУТРИ папки-модели по отдельности не называются — она одна вещь (got {folders.get('entries')})")
        check(folders.get("files") == 5 and folders.get("bytes") == 4550,
              f"папки входят в счёт как по одному предмету каждая (got {folders.get('files')}, {folders.get('bytes')})")
        inner = [d[0] for d in folders.get("dirs", [])]
        check("whisper/models--Systran--faster-whisper-large-v3/snapshots/abc" not in inner,
              f"negative: снимок внутри кэша полон .safetensors-ссылок, но он ЧАСТЬ кэша, а не отдельная модель — "
              f"иначе один перенос увёз бы половину (got {inner})")

        reg, _state, _saves = make_registry(probe, local=str(Path(tmp) / "local"))
        other = Path(tmp) / "other"
        other.mkdir()
        (other / "m.gguf").write_bytes(b"x")
        store = reg.add(str(other), "Other", force=True)
        reg.remove(store["id"])
        check((other / ms.MARKER_NAME).exists() and (other / "m.gguf").exists(),
              "убрать из списка — не стереть: файлы и метка на месте, и та же папка найдётся по метке снова")


class StuckChild:
    def __init__(self):
        self.killed = 0

    def communicate(self, timeout=None):
        raise subprocess.TimeoutExpired("probe", timeout)

    def kill(self):
        self.killed += 1

    def wait(self):
        time.sleep(1.5)


class Garbage:
    def communicate(self, timeout=None):
        return "not json", "Traceback (most recent call last):\nPermissionError: [Errno 13] denied"


def section_deadline():
    print("срок ответа:")
    child = StuckChild()
    probe = ms.StoreProbe(timeout=0.2, spawn=lambda *a, **k: child)
    started = time.time()
    res = probe.look("/mnt/dead")
    took = time.time() - started
    check(res.get("ok") is False and res.get("timeout") is True and "0.2" in res.get("error", ""),
          f"молчание — «не отвечает», и срок назван словами (got {res})")
    check(child.killed == 1 and took < 1.0,
          f"ребёнка убили и его смерти НЕ ждём: застрявший в NFS процесс умирает по таймауту монтирования, "
          f"и ожидание вернулось бы в поток запроса (kill={child.killed}, took={took:.2f}s)")
    res2 = ms.StoreProbe(spawn=lambda *a, **k: Garbage()).look("/x")
    check(res2 == {"ok": False, "error": "PermissionError: [Errno 13] denied"},
          f"мусор вместо ответа — ошибка с последней строкой stderr (got {res2})")

    def no_python(*a, **k):
        raise OSError("no such interpreter")
    res3 = ms.StoreProbe(spawn=no_python).look("/x")
    check(res3.get("ok") is False and "no such interpreter" in res3.get("error", ""),
          f"пробник не стартовал — сказано почему (got {res3})")


def section_registry():
    print("реестр хранилищ:")
    # The refusals get a registry of their own: a refusal that breaks would save
    # its path, and every pin below would then read a list it did not expect.
    lone = FakeProbe(claim=marks)
    reg0, _state0, saves0 = make_registry(lone)
    for bad, code in (("", "no-path"), ("mnt/lib", "not-absolute"), ("/home/x/models", "duplicate"),
                      ("/home/x/models/nas", "nested"), ("/home/x", "nested")):
        got = refused(reg0.add, bad)
        check(got == code, f"negative: {bad!r} — отказ {code} (got {got})")
    check(not lone.calls and not saves0, "эти отказы — до пробника: ни одного похода в папку и ни одной записи состояния")
    probe = FakeProbe(claim=marks)
    reg, state, saves = make_registry(probe)
    added = reg.add("/mnt/lib/", "NAS library")
    check(added["id"].startswith("lib-") and added["path"] == "/mnt/lib" and added["role"] == "library" and added["adopted"] is False,
          f"добавлена: id из метки, путь нормализован, роль «библиотека» (got {added})")
    check(state["modelStores"] == [{"id": added["id"], "name": "NAS library", "path": "/mnt/lib"}] and len(saves) == 1,
          f"сохранена ОДНОЙ записью состояния (got {state.get('modelStores')}, saves={len(saves)})")
    check(refused(reg.add, "/mnt/lib") == "duplicate", "negative: тот же путь второй раз — отказ")
    check([s.id for s in reg.stores()] == ["local", added["id"]],
          "свой каталог всегда первый и в состоянии не хранится, библиотеки — за ним")

    adopt = FakeProbe(claim={"ok": True, "exists": True, "adopted": True, "marker": {"id": "lib-known", "name": "Known"}})
    reg2, _s2, _v2 = make_registry(adopt)
    got2 = reg2.add("/mnt/other", "typed name")
    check(got2["id"] == "lib-known" and got2["name"] == "Known" and got2["adopted"] is True,
          f"метка уже есть — берём её id и имя, а не придуманные: это та же библиотека (got {got2})")
    check(refused(reg2.add, "/mnt/other-mount") == "duplicate",
          "negative: та же метка по второму пути — отказ: одна библиотека не бывает в списке дважды")

    for answer, code in (({"ok": True, "exists": True, "refused": "not-a-mount"}, "not-a-mount"),
                         ({"ok": True, "exists": False}, "missing"),
                         ({"ok": False, "timeout": True, "error": "no answer in 8 s"}, "unreachable"),
                         ({"ok": True, "exists": True, "refused": "not-writable", "error": "EROFS"}, "not-writable")):
        reg3, state3, saves3 = make_registry(FakeProbe(claim=answer))
        got3 = refused(reg3.add, "/mnt/x")
        check(got3 == code and not state3.get("modelStores") and not saves3,
              f"negative: пробник ответил {code} — отказ, ничего не сохранено (got {got3})")
    forced = FakeProbe(claim=marks)
    reg4, _s4, _v4 = make_registry(forced)
    reg4.add("/mnt/y", force=True)
    check(forced.calls[-1][-1] is True, "подтверждённая попытка доезжает до пробника с force")

    check(refused(reg.remove, "local") == "builtin", "negative: собственный каталог не убирается — он меняется через ✎")
    check(refused(reg.remove, "lib-none") == "unknown-id", "negative: неизвестный id — отказ")
    reg.remove(added["id"])
    check(state["modelStores"] == [] and [s.id for s in reg.stores()] == ["local"], "убрана — из списка")


def section_cache():
    print("память о замерах:")
    now = [1000.0]
    probe = FakeProbe(claim=marks)
    reg, state, _saves = make_registry(probe, clock=lambda: now[0])
    lib = reg.add("/mnt/lib", "NAS")
    probe.looks["/mnt/lib"] = {"ok": True, "exists": True, "writable": True, "free": 900 * GB, "total": 1000 * GB,
                               "marker": {"id": lib["id"]}, "files": 1, "bytes": GB, "folders": [], "more": 0}
    probe.calls.clear()
    first = reg.statuses()
    n1 = len(probe.calls)
    reg.statuses()
    n2 = len(probe.calls)
    now[0] += ms.STATUS_TTL_S - 1
    reg.statuses()
    n3 = len(probe.calls)
    check((n1, n2, n3) == (2, 2, 2), f"в пределах памяти второй раз в папки не ходим (calls {n1}, {n2}, {n3})")
    reg.statuses(force=True)
    check(len(probe.calls) == 4, f"force — меряем заново (calls {len(probe.calls)})")
    now[0] += ms.STATUS_TTL_S
    reg.statuses()
    check(len(probe.calls) == 6, f"память истекла — меряем заново (calls {len(probe.calls)})")
    looks = [c for c in probe.calls if c[0] == "look"]
    check(all(c[2] is (c[1] == "/mnt/lib") for c in looks),
          f"перечислять содержимое просим только у библиотеки, у своего диска — только состояние (got {looks[:2]})")
    check(first[0]["id"] == "local" and first[0]["builtin"] is True and first[1]["files"] == 1 and first[1]["state"] == "ok",
          f"строка статуса несёт и само хранилище, и его замер (got {first[1]})")
    state["modelStores"][0]["path"] = "/mnt/lib2"
    probe.looks["/mnt/lib2"] = {"ok": True, "exists": False}
    rows = {r["id"]: r for r in reg.statuses()}
    check(rows[lib["id"]]["state"] == "missing" and rows[lib["id"]]["path"] == "/mnt/lib2",
          f"путь сменился — старый замер за новый не выдаём (got {rows[lib['id']]['state']})")


def join_refresh():
    """Wait for the registry's background measurement, if one is running."""
    for t in threading.enumerate():
        if t.name == "store-refresh":
            t.join(5)


def section_library_files():
    print("файлы библиотек для дерева:")
    now = [100 * 86400.0]
    probe = FakeProbe(claim=marks)
    reg, _state, _saves = make_registry(probe, clock=lambda: now[0])
    lib = reg.add("/mnt/lib", "NAS")
    gone = reg.add("/mnt/gone", "Old", force=True)
    probe.looks["/mnt/lib"] = {"ok": True, "exists": True, "writable": True, "free": 900 * GB, "total": 1000 * GB,
                               "marker": {"id": lib["id"]}, "files": 2, "bytes": 30, "folders": [], "more": 0,
                               "entries": [["A/a/Q4/a.gguf", 10, now[0] - 3 * 86400], ["b.gguf", 20, now[0] + 50]], "entriesMore": 4,
                               "dirs": [["whisper/models--openai--whisper", "whisper", 70, now[0] - 86400]], "dirsMore": 2}
    probe.looks["/mnt/gone"] = {"ok": True, "exists": True, "writable": True, "free": 5 * GB, "total": 10 * GB,
                                "marker": None, "entries": [["local-disk.gguf", 1, now[0]]]}
    probe.calls.clear()
    rows = {r["id"]: r for r in reg.library_files()}
    check(list(rows) == [lib["id"], gone["id"]], f"только библиотеки — свой диск дерево и так рисует (got {list(rows)})")
    check(rows[lib["id"]]["files"] == [{"path": "A/a/Q4/a.gguf", "size": 10, "ageDays": 3, "mtime": int(now[0] - 3 * 86400)},
                                       {"path": "b.gguf", "size": 20, "ageDays": 0, "mtime": int(now[0] + 50)},
                                       {"path": "whisper/models--openai--whisper", "kind": "whisper", "size": 70,
                                        "ageDays": 1, "mtime": int(now[0] - 86400)}]
          and rows[lib["id"]]["more"] == 6 and rows[lib["id"]]["state"] == "ok" and rows[lib["id"]]["name"] == "NAS"
          and rows[lib["id"]]["path"] == "/mnt/lib",
          f"библиотека на месте — её GGUF с размером, возрастом в днях (время из будущего — ноль, не минус) и временем, "
          f"папки-модели рядом с файлами и с указанным видом, остаток (файлы и папки вместе) числом, "
          f"и корень, откуда ЭТОТ хост её читает (got {rows[lib['id']]})")
    check(rows[gone["id"]]["files"] == [] and rows[gone["id"]]["state"] == "not-mounted",
          f"negative: не смонтирована — ни одного файла, даже если под точкой что-то лежит: это был бы локальный диск (got {rows[gone['id']]})")
    looked = len(probe.calls)
    reg.statuses()
    reg.library_files()
    check(len(probe.calls) == looked, f"одна прогулка по библиотеке на период памяти: панель и дерево читают один замер (calls {looked} → {len(probe.calls)})")
    reg.library_files(force=True)
    check(len(probe.calls) > looked, "force — меряем заново")
    check(all(all(k not in r for k in ("entries", "entriesMore", "dirs", "dirsMore")) for r in reg.statuses()),
          "панели хранилищ список файлов и папок не уходит — он для дерева, а панель перерисовывается после каждого действия")

    # The board and the picker never wait for the NAS: the last measurement is
    # read as it is, and a stale one is measured again on a thread of its own.
    # The thread is held at the probe until the answer is read — a caller that
    # waited for the probe would be held with it.
    probe.looks["/mnt/lib"] = {**probe.looks["/mnt/lib"], "entries": [["C/c/Q8/c.gguf", 30, now[0]]], "entriesMore": 0}
    now[0] += ms.STATUS_TTL_S + 1
    gate = threading.Event()
    plain_look = probe.look
    probe.look = lambda root, listing=False, limit=ms.LIST_LIMIT: gate.wait(5) and plain_look(root, listing, limit)
    looked = len(probe.calls)
    stale = {r["id"]: r for r in reg.library_files(wait=False)}[lib["id"]]
    gate.set()
    join_refresh()
    probe.look = plain_look
    fresh = {r["id"]: r for r in reg.library_files(wait=False)}[lib["id"]]
    before, after = [f["path"] for f in stale["files"]], [f["path"] for f in fresh["files"]]
    check(before == ["A/a/Q4/a.gguf", "b.gguf", "whisper/models--openai--whisper"]
          and after == ["C/c/Q8/c.gguf", "whisper/models--openai--whisper"],
          f"без ожидания — последний замер как есть; устаревший перемеряется в фоне, и следующий вопрос видит новый (got {before} → {after})")
    check(len(probe.calls) > looked and reg._refreshing is False, "замер в фоне прошёл и отпустил очередь")
    now[0] += ms.STATUS_TTL_S + 1
    looked = len(probe.calls)
    reg._refreshing = True
    reg.library_files(wait=False)
    join_refresh()
    reg._refreshing = False
    check(len(probe.calls) == looked, "negative: пока идёт один замер в фоне, второй не начинается — мёртвый NAS не копит потоки")



def section_mount_facts():
    print("почему хранилище не отвечает:")
    with tempfile.TemporaryDirectory() as tmp:
        mounts = Path(tmp) / "mountinfo"
        fstab = Path(tmp) / "fstab"
        mounts.write_text(
            "25 30 0:22 / /proc rw,nosuid - proc proc rw\n"
            "31 25 0:26 / /mnt/lib rw,relatime - nfs4 172.16.0.30:/volume1/lib rw,vers=4.1\n"
            "32 25 0:27 / /mnt/lib rw,relatime - nfs4 nas.lan:/volume1/lib rw,vers=4.1\n"
            "33 25 0:28 / /mnt/smb rw,relatime - cifs //nas.lan/share rw\n"
            "34 25 0:29 / /mnt/disk rw,relatime - ext4 /dev/sdb1 rw\n"
            "35 25 0:30 / /mnt/odd rw,relatime - fuse.odd odd-fs rw\n", encoding="utf-8")
        fstab.write_text("# comment\nnas.lan:/volume1/lib /mnt/lib nfs4 defaults 0 0\n"
                         "/dev/sdb1 /mnt/disk ext4 defaults 0 0\n", encoding="utf-8")
        knocks = []

        def knock(host, port):
            knocks.append((host, port))
            return host == "nas.lan"

        facts = ms.MountFacts(mounts=str(mounts), fstab=str(fstab), knock=knock)
        lib = facts.at("/mnt/lib")
        check(lib == {"inFstab": True, "source": "nas.lan:/volume1/lib", "type": "nfs4", "host": "nas.lan", "answers": True},
              f"смонтировано: источник и тип берутся у ПОСЛЕДНЕГО монтирования в этой точке — читатель попадает в него (got {lib})")
        check(knocks == [("nas.lan", 2049)], f"стучимся по порту вида монтирования, один раз (got {knocks})")
        smb = facts.at("/mnt/smb")
        check((smb["host"], smb["answers"], knocks[-1]) == ("nas.lan", True, ("nas.lan", 445)),
              f"//host/share — тоже машина, порт другой (got {smb})")
        disk = facts.at("/mnt/disk")
        check((disk["host"], disk["answers"], disk["inFstab"]) == ("", None, True),
              f"negative: устройство не называет машину — стучаться некуда, «не знаю», а не «не отвечает» (got {disk})")
        odd = facts.at("/mnt/odd")
        check((odd["source"], odd["answers"]) == ("odd-fs", None), f"negative: вид монтирования без порта — тоже «не знаю» (got {odd})")
        none = facts.at("/mnt/nothing")
        check(none == {"inFstab": False, "source": "", "type": "", "host": "", "answers": None},
              f"negative: в этой точке ничего не смонтировано и в fstab её нет (got {none})")
        silent = ms.MountFacts(mounts=str(mounts), fstab=str(fstab), knock=lambda h, p: False).at("/mnt/lib")
        check(silent["answers"] is False, "машина молчит — так и сказано")
        gone = ms.MountFacts(mounts=str(Path(tmp) / "nope"), fstab=str(Path(tmp) / "nope")).at("/mnt/lib")
        check(gone == {"inFstab": False, "source": "", "type": "", "host": "", "answers": None},
              f"negative: файлов системы нет — пусто, без падения (got {gone})")

    probe = FakeProbe(claim=marks)
    reg, _state, _saves = make_registry(probe)
    probe.looks["/mnt/lib"] = {"ok": False, "timeout": True, "error": "no answer in 8 s"}
    added = reg.add("/mnt/lib", "NAS")
    reg.mount_facts = ms.MountFacts(mounts="/nonexistent", fstab="/nonexistent")
    rows = {r["id"]: r for r in reg.statuses(force=True)}
    check(rows[added["id"]]["state"] == "unknown" and rows[added["id"]]["mount"]["source"] == "",
          f"у неотвечающего хранилища в ответе есть раздел «чем смонтировано» (got {rows[added['id']].get('mount')})")
    check("mount" not in rows["local"], "negative: у здорового хранилища этого раздела нет — объяснять нечего")


def section_repath():
    print("смена пути библиотеки:")
    probe = FakeProbe(claim=marks)
    reg, state, saves = make_registry(probe)
    added = reg.add("/mnt/lib", "NAS")
    sid = added["id"]
    probe.looks["/mnt/new"] = {"ok": True, "exists": True, "writable": True, "marker": {"id": sid, "name": "NAS"}}
    probe.looks["/mnt/other"] = {"ok": True, "exists": True, "writable": True, "marker": {"id": "lib-zzz", "name": "Other"}}
    probe.looks["/mnt/bare"] = {"ok": True, "exists": True, "writable": True}
    probe.looks["/mnt/dead"] = {"ok": False, "timeout": True, "error": "no answer in 8 s"}
    before = len(saves)
    moved = reg.repath(sid, "/mnt/new/")
    check(moved["store"]["path"] == "/mnt/new" and state["modelStores"][0]["path"] == "/mnt/new" and len(saves) == before + 1,
          f"та же библиотека по новому пути: путь нормализован, записан одной записью (got {moved})")
    check(reg.repath(sid, "/mnt/new")["store"]["path"] == "/mnt/new" and len(saves) == before + 1,
          "тот же путь второй раз — ничего не пишется")
    for bad, code in (("/mnt/other", "other-library"), ("/mnt/bare", "not-a-mount"), ("/mnt/dead", "unreachable"),
                      ("mnt/rel", "not-absolute"), ("", "no-path"), ("/home/x/models", "duplicate"),
                      ("/home/x/models/inner", "nested")):
        check(refused(reg.repath, sid, bad) == code, f"negative: {bad!r} — отказ {code}")
    check(refused(reg.repath, "local", "/tmp/x") == "builtin", "negative: свой каталог меняется ✎ на странице, не этим")
    check(refused(reg.repath, "lib-nope", "/mnt/new") == "unknown-id", "negative: неизвестная библиотека")
    check(state["modelStores"][0]["path"] == "/mnt/new", "после всех отказов путь остался прежним")


def main():
    section_rule()
    section_child()
    section_deadline()
    section_registry()
    section_mount_facts()
    section_repath()
    section_cache()
    section_library_files()
    print()
    if _fail:
        print(f"model stores FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("model stores OK: правило состояний, дочерний процесс, срок ответа, реестр и память замеров")
    return 0


if __name__ == "__main__":
    sys.exit(main())
