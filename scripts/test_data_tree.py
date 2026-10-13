#!/usr/bin/env python3
"""Value snapshot: caravan/admin/data_tree.py — the data folder's subfolders made
before any writer needs them, or a stop that says why they cannot be.

Found 2026-10-07 on a fresh NAS install: the data folder carried a Synology ACL,
the container (same uid, no supplementary groups) could not write it, and the
controller died on its first mkdir with a traceback, restarted forever, and the
browser saw only 502. The refusals below are driven through the class's own
filesystem parameters, so no test needs a folder it cannot write.

Run: python3 scripts/test_data_tree.py
"""
import errno
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.data_tree import DataTree  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refuse(code, where):
    def make(path):
        if str(path).endswith("/state") or str(path) == where:
            raise (PermissionError if code in (errno.EACCES, errno.EPERM) else OSError)(code, "refused", where)
        path.mkdir(parents=True, exist_ok=True)
    return make


print("папка данных: создана или названа причина отказа:")
with tempfile.TemporaryDirectory() as tmp:
    tree = DataTree(Path(tmp) / "data")
    check(tree.problem() == "" and sorted(p.name for p in (Path(tmp) / "data").iterdir()) == sorted(DataTree.SUBDIRS),
          "папка пишется — шесть подпапок на месте, пробного файла не осталось")
    tree.prepare("lama-caravan")
    check(True, "prepare() на пишущейся папке не останавливает процесс")

    acl = DataTree("/data", make=refuse(errno.EACCES, "/data/state"), uid=1026, gid=100)
    said = acl.problem()
    check("cannot write the data folder /data (/data/state: refused) as uid 1026, gid 100" in said
          and "chmod 755" in said and "ACL" in said,
          "отказ в правах — названы папка, место, пользователь и лекарство (chmod 755 от ACL Synology)")
    out = io.StringIO()
    try:
        acl.prepare("lama-caravan", stream=out)
        stopped = None
    except SystemExit as exc:
        stopped = exc.code
    check(stopped == 2 and out.getvalue().startswith("lama-caravan: will not start: cannot write the data folder"),
          "prepare() останавливает процесс с кодом 2 и причиной, а не трейсбеком")

    ro = DataTree("/data", make=refuse(errno.EROFS, "/data/state"), uid=1026, gid=100)
    said = ro.problem()
    check(said.startswith("cannot make the data folder /data (/data/state: refused)") and "chmod" not in said,
          "negative: не права (только-чтение) — причина без чужого лекарства")

    existing = Path(tmp) / "existing"
    for sub in DataTree.SUBDIRS:
        (existing / sub).mkdir(parents=True)

    def probe(folder):
        raise PermissionError(errno.EACCES, "refused", str(folder / ".write-probe"))
    said = DataTree(existing, probe=probe, uid=1026, gid=100).problem()
    check("cannot write the data folder" in said and ".write-probe" in said,
          "negative: папки уже есть, но писать нельзя — это тоже отказ, а не «всё готово»")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("data tree snapshot holds")
