#!/usr/bin/env python3
"""Одна сборка llama.cpp на дерево: install-llama.sh берёт замок рядом с деревом.

На машине, где работают и контроллер, и скаут, оба собирают llama.cpp в одну
и ту же папку: контроллер — этим скриптом, скаут — своим update-llama.sh.
Каждый охранял сборку только внутри своего процесса. Две сборки разом дают
бинарь наполовину от одного коммита и наполовину от другого — франкен-сборку,
к которой когда-то свелись все падения. Оба скрипта берут один и тот же
замок; второй говорит, что занято, и останавливается (код 75).

Скрипт запускается по-настоящему, с поддельным flock (занято / свободно),
деревом и архивом во временной папке; до сборки дело не доходит.

Запуск: python3 scripts/test_install_llama_lock.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install-llama.sh"
LOCK_LINE = 'exec 9>"${LLAMA_DIR%/}.caravan-build.lock"'
FAKE_FLOCK = """#!/usr/bin/env bash
echo "$*" >> "$FLOCK_LOG"
[[ "$FLOCK_ANSWER" == "free" ]]
"""

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def run(action, answer, tmp):
    fake_bin = tmp / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    (fake_bin / "flock").write_text(FAKE_FLOCK)
    (fake_bin / "flock").chmod(0o755)
    log = tmp / "flock.log"
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}", "HOME": str(tmp / "home"),
           "FLOCK_LOG": str(log), "FLOCK_ANSWER": answer, "LLAMA_BUILDS_DIR": str(tmp / "builds")}
    done = subprocess.run(["bash", str(SCRIPT), "--llama-dir", str(tmp / "llama.cpp"), action],
                          capture_output=True, text=True, env=env, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    return done.returncode, done.stdout + done.stderr, calls


def main():
    print("одна сборка llama.cpp на дерево:")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        code, out, calls = run("--archive-current", "busy", tmp)
        beside = (tmp / "llama.cpp.caravan-build.lock").exists()
        inside = (tmp / "llama.cpp").exists()
    check(code == 75 and calls == ["-n 9"] and "another llama.cpp build or restore is running in" in out,
          f"замок занят (скаут собирает то же дерево) — сборка/архив не идут: код 75 и сказано почему "
          f"(код {code}, flock {calls})")
    check(beside and not inside, "файл замка — рядом с деревом, не внутри: свежий git clone не откажется от папки")
    with tempfile.TemporaryDirectory() as t:
        code, out, calls = run("--list-builds", "busy", Path(t))
    check(calls == [] and code != 75, "negative: список сборок ничего не меняет и замка не ждёт")
    with tempfile.TemporaryDirectory() as t:
        code, out, calls = run("--archive-current", "free", Path(t))
    check(calls == ["-n 9"] and code != 75 and "another llama.cpp build" not in out,
          "negative: замок свободен — скрипт идёт дальше")
    check(SCRIPT.read_text(encoding="utf-8").count(LOCK_LINE) == 1,
          "файл замка назван одной строкой — той же, что у update-llama.sh скаута (сверяется на стороне скаута)")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\ninstall-llama lock OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
