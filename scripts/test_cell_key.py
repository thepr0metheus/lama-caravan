#!/usr/bin/env python3
"""Snapshot of caravan/common/cell_key.py — the key a cell answers to.

Pins by value: what a cell's key looks like, that the proxy and the admin get
the same key for a port from the same master and a different one for another
port or master, when there is no key at all (and nothing pretends there is),
how the master is created once and read by everyone after, and what a cell's
process and the proxy's request carry.

Run: python3 scripts/test_cell_key.py
"""
import hashlib
import hmac
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.common.cell_key import CellKeys  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


MASTER = "11" * 32
OTHER = "22" * 32


def keys_with(tmp, text=MASTER, name="cell-key"):
    path = Path(tmp) / name
    path.write_text(text + "\n", encoding="utf-8")
    return CellKeys(path)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("ключ ячейки:")
        k = keys_with(tmp)
        key = k.for_port(22001)
        expect = "cck1_" + hmac.new(bytes.fromhex(MASTER), b"cell:22001", hashlib.sha256).hexdigest()[:40]
        check(key == expect, "ключ = cck1_ + первые 40 hex от HMAC-SHA256(мастер, «cell:<порт>»)")
        check(bool(re.fullmatch(r"cck1_[0-9a-f]{40}", key or "")), "форма: префикс и 40 hex — узнаётся в логе и в утечке")
        check(k.for_port(22001) == key and CellKeys(k.path).for_port(22001) == key,
              "тот же мастер и порт — тот же ключ: у прокси и у контроллера он один")
        check(k.for_port("22001") == key, "порт строкой — тот же порт")
        check(k.for_port(22002) != key, "другой порт — другой ключ: утёкший ключ открывает одну ячейку")
        check(keys_with(tmp, OTHER, "other").for_port(22001) != key, "другой мастер — другой ключ")

        print("ключа нет — так и сказано:")
        none = CellKeys(Path(tmp) / "absent")
        check(none.for_port(22001) is None, "мастера нет — ключа нет (None), а не пустая строка")
        check(not (Path(tmp) / "absent").exists(), "вопрос без create мастер не заводит")
        check(none.headers(22001) == {}, "без мастера запрос к ячейке идёт без заголовка")
        check(none.env(22001, create=False) == {}, "без мастера ячейке нечего передать")
        check([k.for_port(p) for p in (0, 65536, -1, "abc", None, "", 3.5, "22001.0", [22001])] == [None] * 9,
              "не порт — None: ноль, вне диапазона, текст, пусто, дробь, список")
        check(k.for_port(" 22001 ") == key, "пробелы вокруг порта-строки не мешают")
        check(k.for_port(True) is None and k.for_port(False) is None, "булево — не порт, хоть int(True) == 1")
        empty = keys_with(tmp, "", "empty")
        check(empty.for_port(22001) is None and empty.headers(22001) == {}, "пустой файл мастера — ключа нет")

        print("мастер заводится один раз:")
        path = Path(tmp) / "sub" / "cell-key"
        first = CellKeys(path)
        made = first.for_port(22001, create=True)
        check(path.exists() and made is not None, "create заводит мастер (и папку) и сразу даёт ключ")
        check(stat.S_IMODE(os.stat(path).st_mode) == 0o600, "файл мастера — только владельцу (0600)")
        check(bool(re.fullmatch(r"[0-9a-f]{64}\n", path.read_text())), "мастер — 32 случайных байта в hex")
        second = CellKeys(path)
        check(second.for_port(22001, create=True) == made, "второй процесс с create читает тот же мастер, а не заводит свой")
        check(CellKeys(path).for_port(22001) == made, "читатель без create — тот же ключ")
        raced = keys_with(tmp, MASTER, "raced")
        check(raced._create() == bytes.fromhex(MASTER) and raced.path.read_text().strip() == MASTER,
              "гонка: файл появился между проверкой и созданием — чужой мастер читается, а не затирается")

        print("новый мастер доходит до работающего процесса:")
        live = keys_with(tmp, MASTER, "live")
        before = live.for_port(22001)
        live.path.write_text(OTHER + "\n", encoding="utf-8")
        os.utime(live.path, ns=(1, 1))
        check(live.for_port(22001) != before and live.for_port(22001) == keys_with(tmp, OTHER, "o2").for_port(22001),
              "файл сменился — ключи от нового мастера, без рестарта")
        live.path.unlink()
        check(live.for_port(22001) is None, "файл удалён — ключа нет, старый мастер не держится в памяти")

        print("что несут запрос и процесс ячейки:")
        check(k.headers(22001) == {"Authorization": f"Bearer {key}"}, "запрос прокси: Authorization: Bearer <ключ>")
        env = k.env(22001)
        check(env == {"LLAMA_API_KEY": key, "VLLM_API_KEY": key, "CARAVAN_CELL_KEY": key},
              "процесс ячейки: три имени — llama-server, vLLM, серверы каравана — с одним ключом")
        check(k.env(22002)["CARAVAN_CELL_KEY"] != key, "у другой ячейки — свой ключ")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("cell keys OK: ключ ячейки, его отсутствие и мастер — значениями")


if __name__ == "__main__":
    main()
