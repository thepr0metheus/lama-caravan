#!/usr/bin/env python3
"""Value snapshot: on the NAS the models library is the controller's models folder.

The owner, 2026-10-12: every downloaded model in one place, the library on the NAS, and a
scout fetches a model through the caravan, never from the share — so the share's rights are
given to the caravan alone. Both halves rest on the controller's ONE models folder: Hugging
Face downloads land in it (POST /api/hf/download) and a scout's download reads from it
(GET /api/models/download). The controller on the NAS ran with an empty folder of its own
instead, and the library's 400 GB were on no screen.

deploy/nas/compose.yaml therefore mounts the library's share at /data/models and adds the
share's ACL group to the container (a container gets no supplementary groups, and the
share lets in only its group). This snapshot names the half that a later edit drops.

deploy/nas/ is private to this deployment, and the public copy has no such file: there the
snapshot says so and checks the rule on its own sample only.

Run: python3 scripts/test_nas_models_library.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy" / "nas" / "compose.yaml"

SAMPLE = """services:
  lama-caravan:
    user: "1026:100"
    group_add:
      - "65542"
    volumes:
      - ../../data:/data
      - /volume1/lama-caravan-models:/data/models
"""

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Library:
    """Which half of the library's mount a compose text lacks, by name, in order.

    Read from the text, like the lockdown snapshot: the image has no YAML library. A line
    commented out is no setting."""

    SHARE = "/volume1/lama-caravan-models"
    FOLDER = "/data/models"     # the controller's models folder in the container (caravan/admin/paths.py)
    GROUP = "65542"             # lama_caravan_nas on the NAS
    NEEDED = (
        ("library mount", r"^[ \t]+volumes:[ \t]*\n(?:[ \t]+-[^\n]*\n)*?[ \t]+-[ \t]*\"?" + re.escape(SHARE)
         + ":" + re.escape(FOLDER) + r"(?::rw)?\"?[ \t]*$"),
        ("library group", r"^[ \t]+group_add:[ \t]*\n(?:[ \t]+-[^\n]*\n)*?[ \t]+-[ \t]*[\"']?" + GROUP + r"[\"']?[ \t]*$"),
    )

    @classmethod
    def missing(cls, text):
        return [name for name, rule in cls.NEEDED if not re.search(rule, text, re.M)]


def test_the_rule():
    print("правило — на своём образце:")
    check(Library.missing(SAMPLE) == [], "библиотека — папка моделей, группа библиотеки добавлена")
    check(Library.missing(SAMPLE.replace("      - /volume1/lama-caravan-models:/data/models\n", "")) == ["library mount"],
          "negative: без подключения библиотеки — названо library mount")
    check(Library.missing(SAMPLE.replace(":/data/models", ":/library")) == ["library mount"],
          "negative: библиотека в другой папке — контроллер её не раздаёт, названо library mount")
    check(Library.missing(SAMPLE.replace(":/data/models", ":/data/models:ro")) == ["library mount"],
          "negative: только чтение — загрузка с Hugging Face не запишет, названо library mount")
    check(Library.missing(SAMPLE.replace('      - "65542"\n', "")) == ["library group"],
          "negative: без группы — права библиотеки контейнер не пускают, названо library group")
    check(Library.missing(SAMPLE.replace('      - "65542"', '      # - "65542"')) == ["library group"],
          "negative: строка под комментарием — это не настройка")
    check(Library.missing(SAMPLE.replace('"65542"', '"65540"')) == ["library group"],
          "negative: чужая группа — названо library group")


def test_the_nas_compose():
    print("compose.yaml на NAS:")
    if not COMPOSE.exists():
        print(f"  --  {COMPOSE.relative_to(ROOT)} нет в этом дереве (публичная копия): проверено только правило")
        return
    missing = Library.missing(COMPOSE.read_text(encoding="utf-8"))
    check(missing == [], "библиотека NAS подключена как /data/models, группа lama_caravan_nas у контейнера есть"
          + (f" — нет: {', '.join(missing)}" if missing else ""))


for fn in (test_the_rule, test_the_nas_compose):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("nas models library snapshot holds")
