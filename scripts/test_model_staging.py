#!/usr/bin/env python3
"""Value snapshot: updating a model file in place and keeping the previous one.

The asymmetry everything follows from: the NEW build can always be
downloaded again, the OLD one never can (it differs precisely because the
author rebuilt it, and it no longer exists on HF). From that: the
replacement runs WITHOUT a second copy by default — space costs more than a
rollback; whoever wants the opposite turns on the checkbox, and the previous
file is preserved as a HARD LINK before the download. A link, not a copy: same
inode, no need to read seventeen gigabytes. And the link is made BEFORE the
swap — after `os.replace` the old name no longer exists.

A rollback is free to discard the new file: that one can always be downloaded again.

Run: python3 scripts/test_model_staging.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.model_staging as ms  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        live = d / "model-Q4_K_XL.gguf"
        live.write_bytes(b"OLD-BUILD" * 100)
        old_inode = live.stat().st_ino

        print("места на диске:")
        try:
            ms.check_room(live, 10 ** 15)
            check(False, "терабайт на этот диск не влезет — должен быть отказ")
        except AppError as exc:
            check(exc.status == 409 and "free" in str(exc),
                  f"отказ называет и нужное, и свободное (got {exc})")
        room = ms.check_room(live, 1)
        check(room["need"] > ms.DISK_MARGIN_BYTES,
              "в нужное входит ЗАПАС: пока идёт закачка, рядом лежит .part")

        print("сохранение прежней сборки:")
        kept = ms.link_prev(live)
        check(kept.endswith(".gguf.prev"), f"имя — <файл>.gguf.prev (got {kept})")
        check(ms.prev_path(live).stat().st_ino == old_inode,
              "сохранена ЖЁСТКОЙ ССЫЛКОЙ: тот же инод, семнадцать гигабайт никто не копировал")
        # The swap, the way the downloader does it: rename, not writing into the same inode.
        (d / "new.part").write_bytes(b"NEW-BUILD" * 90)
        (d / "new.part").replace(live)
        check(live.read_bytes() == b"NEW-BUILD" * 90, "после подмены рабочим стал новый файл")
        check(ms.prev_path(live).read_bytes() == b"OLD-BUILD" * 100,
              "а прежняя сборка цела — ссылка держит старый инод")
        check(live.stat().st_ino != old_inode,
              "у рабочего имени ДРУГОЙ инод: работающий процесс держит старый и не вздрагивает")

        print("повторное сохранение:")
        inode2 = live.stat().st_ino
        ms.link_prev(live)
        check(ms.prev_path(live).stat().st_ino == inode2,
              "поверх существующего .prev — снова ссылка, а не копия")

        print("откат:")
        (d / "n2.part").write_bytes(b"THIRD" * 80)
        (d / "n2.part").replace(live)
        back = ms.restore_prev(live)
        check(live.read_bytes() == b"NEW-BUILD" * 90,
              "positive: вернулась сохранённая сборка")
        check(not ms.prev_path(live).exists(), "и .prev израсходован — второго отката из ниоткуда нет")
        check(back["restored"] == str(live), f"ответ называет восстановленный файл (got {back})")
        try:
            ms.restore_prev(live)
            check(False, "откатывать нечего — должен быть отказ")
        except AppError as exc:
            check(exc.status == 404, f"откатывать нечего — 404 (got {exc.status})")

        print("освобождение места:")
        ms.link_prev(live)
        size = ms.prev_path(live).stat().st_size
        freed = ms.drop_prev(live)
        check(freed["freed"] == size and not ms.prev_path(live).exists(),
              f"удаление .prev называет освобождённое (got {freed}, ждали {size})")
        check(ms.drop_prev(live)["freed"] == 0,
              "второй раз — ноль и без ошибки: удалять нечего")

        print("нечего сохранять:")
        check(ms.link_prev(d / "нет-такого.gguf") == "",
              "файла нет — ссылку не выдумываем, возвращаем пустоту")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("model-staging snapshots hold")


if __name__ == "__main__":
    main()
