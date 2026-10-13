#!/usr/bin/env python3
"""Value snapshot: the caravan's container on the NAS stays locked down (deploy/nas/compose.yaml).

The owner, 2026-10-11: the image's known vulnerabilities that Debian has not fixed
yet sit mostly in programs the caravan never runs — su, passwd, mount — and serve
only someone already inside. Four settings take them away from that someone: no
new privileges, no capabilities, a read-only root, and /tmp in memory. A later edit
of the compose file could drop one without a word; this snapshot names the one.

The caravan itself needs nothing more: it writes only under /data
(scripts/test_data_volume_paths.py) and binds ports above 1024.

deploy/nas/ is private to this deployment, and the public copy has no such file:
there the snapshot says so and checks the rule on its own sample only.

Run: python3 scripts/test_nas_lockdown.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy" / "nas" / "compose.yaml"

SAMPLE = """services:
  lama-caravan:
    user: "1026:100"
    network_mode: host
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
    restart: unless-stopped
"""

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Lockdown:
    """Which of the lockdown's settings a compose text lacks, by name, in order.

    Read from the text: the image has no YAML library, and the settings are four
    plain lines. A line commented out is no setting."""

    NEEDED = (
        ("no-new-privileges", r"^[ \t]+security_opt:[ \t]*\n(?:[ \t]+-[^\n]*\n)*?[ \t]+-[ \t]*no-new-privileges:true[ \t]*$"),
        ("cap_drop ALL", r"^[ \t]+cap_drop:[ \t]*\n(?:[ \t]+-[^\n]*\n)*?[ \t]+-[ \t]*ALL[ \t]*$"),
        ("read_only", r"^[ \t]+read_only:[ \t]*true[ \t]*$"),
        ("tmpfs /tmp", r"^[ \t]+tmpfs:[ \t]*\n(?:[ \t]+-[^\n]*\n)*?[ \t]+-[ \t]*/tmp[ \t]*$"),
    )

    @classmethod
    def missing(cls, text):
        return [name for name, rule in cls.NEEDED if not re.search(rule, text, re.M)]


def test_the_rule():
    print("правило — на своём образце:")
    check(Lockdown.missing(SAMPLE) == [], "все четыре настройки на месте — пропусков нет")
    for line, name in (("      - no-new-privileges:true\n", "no-new-privileges"), ("      - ALL\n", "cap_drop ALL"),
                       ("    read_only: true\n", "read_only"), ("      - /tmp\n", "tmpfs /tmp")):
        check(Lockdown.missing(SAMPLE.replace(line, "")) == [name], f"negative: без строки {line.strip()!r} — названа {name}")
    check(Lockdown.missing(SAMPLE.replace("    read_only: true", "    # read_only: true")) == ["read_only"],
          "negative: строка под комментарием — это не настройка")
    check(Lockdown.missing(SAMPLE.replace("read_only: true", "read_only: false")) == ["read_only"],
          "negative: read_only: false — не закрыт")
    check(Lockdown.missing(SAMPLE.replace("      - ALL", "      - NET_RAW")) == ["cap_drop ALL"],
          "negative: сняли одну способность вместо всех — не закрыт")


def test_the_nas_compose():
    print("compose.yaml на NAS:")
    if not COMPOSE.exists():
        print(f"  --  {COMPOSE.relative_to(ROOT)} нет в этом дереве (публичная копия): проверено только правило")
        return
    check(Lockdown.missing(COMPOSE.read_text(encoding="utf-8")) == [],
          "контейнер на NAS закрыт: no-new-privileges, cap_drop ALL, read_only, /tmp в памяти")


for fn in (test_the_rule, test_the_nas_compose):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("nas lockdown snapshot holds")
