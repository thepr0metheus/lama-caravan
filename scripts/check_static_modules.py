#!/usr/bin/env python3
"""Every module in static/js must PARSE as an ES module.

An edit to an import list left `name,,` behind — and the board died on
parsing: the page showed its loading llamas forever. It shipped to
production and was only found because someone happened to open the board.

Why it wasn't caught. `node --check` SKIPS this file: it doesn't parse it as
a module, so an error in the import list sails right through. And the
snapshots that load the real modules stub out topology-render — meaning no
pin ever read it. A check that silently doesn't check anything is worse than
no check at all: people rely on it.

Fails TWO ways: a module fails to parse; and when there's nothing left to
parse — no files found, or node unavailable, which is stated out loud rather
than skipped over.

Run: python3 scripts/check_static_modules.py
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIRS = ("static/js", "static/js/i18n")
MIN_FILES = 20


def main():
    node = shutil.which("node")
    if not node:
        print("static modules FAILED:\n  - node не найден — разобрать модули нечем, "
              "а «не проверено» не то же самое, что «в порядке»")
        return 1

    files = sorted({p for d in JS_DIRS for p in (ROOT / d).glob("*.js")})
    if len(files) < MIN_FILES:
        print(f"static modules FAILED:\n  - найдено {len(files)} модулей в {', '.join(JS_DIRS)} — "
              f"проверка смотрит не туда")
        return 1

    # One process for everything: node parses each file as a module, WITHOUT
    # executing it and without resolving imports — only the syntax matters here.
    script = """
const { readFileSync } = require("node:fs");
const vm = require("node:vm");
const bad = [];
for (const file of JSON.parse(process.env.CARAVAN_JS_FILES)) {
  try { new vm.SourceTextModule(readFileSync(file, "utf8"), { identifier: file }); }
  catch (e) { bad.push({ file, message: String(e && e.message || e) }); }
}
process.stdout.write(JSON.stringify(bad));
"""
    # The file list travels through the environment, not as an argument:
    # with `node -e`, argv shifts, and the first version read undefined —
    # meaning it "checked" zero files and would have failed with confusion
    # instead of an answer.
    env = dict(os.environ, CARAVAN_JS_FILES=json.dumps([str(p) for p in files]))
    proc = subprocess.run([node, "--experimental-vm-modules", "-e", script],
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        print("static modules FAILED:\n  - node не смог выполнить разбор: "
              + (proc.stderr.strip().splitlines() or [""])[-1])
        return 1
    try:
        bad = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        print("static modules FAILED:\n  - разбор вернул не JSON — проверять нечем")
        return 1

    if bad:
        print("static modules FAILED:")
        for item in bad:
            rel = Path(item["file"]).relative_to(ROOT).as_posix()
            print(f"  - {rel}: {item['message']}")
        print("\n`node --check` такой файл ПРОПУСКАЕТ: он разбирает не как модуль.")
        return 1
    print(f"static modules OK: {len(files)} модулей разбираются как ES-модули")
    return 0


if __name__ == "__main__":
    sys.exit(main())
