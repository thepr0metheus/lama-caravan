#!/usr/bin/env python3
"""Каждый модуль static/js обязан РАЗБИРАТЬСЯ как ES-модуль.

Правка списка импортов оставила `имя,,` — и доска умерла на разборе: страница
показывала загрузочных лам вечно. Уехало в прод и нашлось только тем, что кто-то
открыл доску.

Почему не поймали. `node --check` этот файл ПРОПУСКАЕТ: он разбирает не как
модуль, поэтому ошибка в списке импортов проходит насквозь. А снимки, грузящие
настоящие модули, заглушают topology-render — значит ни один пин его не читал.
Проверка, которая молча не проверяет, хуже отсутствующей: на неё полагаются.

Падает ДВУМЯ способами: модуль не разбирается; и когда разбирать стало нечего —
файлов не нашлось или node недоступен, о чём говорится вслух, а не пропускается.

Запуск: python3 scripts/check_static_modules.py
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

    # Один процесс на всё: node разбирает каждый файл как модуль, НЕ выполняя
    # его и не разрешая импорты — нас интересует ровно синтаксис.
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
    # Список файлов идёт через окружение, а не аргументом: при `node -e` argv
    # сдвигается, и первая редакция читала undefined — то есть «проверила»
    # ноль файлов и упала бы с невнятицей вместо ответа.
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
