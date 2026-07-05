#!/usr/bin/env python3
"""CI guard: every en message key (and en fieldHelp entry) must exist in all
languages of static/js/i18n-data.js. Companion to check_tour_i18n.py — keeps
new UI strings from silently shipping as en+ru only."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "static" / "js" / "i18n-data.js"

NODE_SNIPPET = """
import(process.argv[1]).then(({ LANGS, messages }) => {
  const out = {};
  for (const { code } of LANGS) {
    const m = messages[code] || {};
    out[code] = {
      keys: Object.keys(m).filter(k => typeof m[k] === "string"),
      fieldHelp: Object.keys(m.fieldHelp || {}),
    };
  }
  console.log(JSON.stringify(out));
});
"""


def main() -> int:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_SNIPPET, str(DATA)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"i18n-data.js failed to load: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    data = json.loads(proc.stdout)
    en_keys, en_help = set(data["en"]["keys"]), set(data["en"]["fieldHelp"])
    failed = False
    for lang, entry in data.items():
        if lang == "en":
            continue
        missing = sorted(en_keys - set(entry["keys"]))
        missing_help = sorted(en_help - set(entry["fieldHelp"]))
        if missing or missing_help:
            failed = True
            print(f"{lang}: missing {len(missing)} keys, {len(missing_help)} fieldHelp", file=sys.stderr)
            for k in missing[:10]:
                print(f"  - {k}", file=sys.stderr)
    if failed:
        print("add the missing translations to static/js/i18n-data.js", file=sys.stderr)
        return 1
    print(f"messages i18n OK: {len(en_keys)} keys + {len(en_help)} fieldHelp across {len(data)} languages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
