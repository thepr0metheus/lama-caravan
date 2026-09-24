#!/usr/bin/env python3
"""scripts/deploy.sh узнаёт свой коммит, как бы его ни сократили.

git удлиняет короткий хеш там, где семь знаков в ЭТОМ репозитории
неоднозначны, и контроллер ответил c64d7fee на локальный c64d7fe. Строки
сравнивались целиком: удачный деплой кричал MISMATCH, выходил с ошибкой и
не сообщал CI (2026-09-24). Функция same_commit из самого скрипта
запускается bash'ем по-настоящему.

Запуск: python3 scripts/test_deploy_same_commit.py
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def same(a, b):
    text = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    fn = re.search(r"^same_commit\(\) \{.*?^\}", text, re.M | re.S).group(0)
    return subprocess.run(["bash", "-c", fn + '\nsame_commit "$1" "$2"', "_", a, b]).returncode == 0


def main():
    print("свой коммит под любым сокращением:")
    check(same("c64d7fe", "c64d7fe"), "одинаковые — тот же")
    check(same("c64d7fee", "c64d7fe") and same("c64d7fe", "c64d7fee"),
          "defect-history: восемь знаков на контроллере, семь локально — тот же коммит, в обе стороны")
    check(same("c64d7feead4d", "c64d7fe"), "полный и короткий — тот же")
    check(not same("c64d7fe", "c64d7ff") and not same("c64d7fee", "c64d7fea"),
          "negative: другой коммит — не тот же")
    check(not same("", "c64d7fe") and not same("c64d7fe", "") and not same("", ""),
          "negative: пустой ответ (сервис молчит) — не совпадение, а MISMATCH")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\ndeploy same-commit OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
