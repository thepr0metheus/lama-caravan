#!/usr/bin/env python3
"""CI guard: every t("key") in the static JS must exist in i18n-data.js.

check_messages_i18n.py compares the LANGUAGES against each other — it proves
they agree, not that they cover what the code asks for. So a new panel could
ship calling nine keys that exist nowhere, the guard stayed green, and the UI
rendered its own key names as labels. That happened; this closes it.

t() falls back to the key, so a miss is cosmetic rather than fatal — which is
exactly why nothing caught it. Cosmetic and invisible is still shipped-broken.

Dynamic keys (t(someVar), t(`x${y}`)) cannot be checked and are skipped: this
looks only at plain string literals.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "static" / "js" / "i18n-data.js"
# Long-form tour texts deliberately live apart from the short UI strings, but
# they resolve through the same t() — so both files define the known set.
TOURS = ROOT / "static" / "js" / "onboarding-strings.js"
JS_DIRS = [ROOT / "static" / "js", ROOT / "static"]

# A literal key, and NOT the head of a built one: t("period_" + n) is dynamic
# and unknowable from here, so the trailing `+` disqualifies the match.
CALL = re.compile(r'\bt\(\s*"([A-Za-z][\w.]*)"(?!\s*\+)')
# Keys defined in the en block — the canonical set; the other guard proves the
# rest match it.
DEF = re.compile(r'^\s{4}([A-Za-z][\w]*)\s*:', re.M)


def main() -> int:
    src = DATA.read_text(encoding="utf-8")
    start = src.find("\n  en: {")
    end = src.find("\n  ru: {")
    if start < 0 or end < 0:
        print("cannot locate the en block in i18n-data.js", file=sys.stderr)
        return 1
    known = set(DEF.findall(src[start:end]))
    # fieldHelp lives one level deeper and is looked up by its own helper.
    known |= set(re.findall(r'^\s{6}([A-Za-z][\w]*)\s*:', src[start:end], re.M))
    if TOURS.exists():
        tsrc = TOURS.read_text(encoding="utf-8")
        known |= set(re.findall(r'^\s{2}([A-Za-z][\w]*)\s*:', tsrc, re.M))

    missing = {}
    for d in JS_DIRS:
        for path in sorted(d.glob("*.js")):
            if path.name == "i18n-data.js":
                continue
            text = path.read_text(encoding="utf-8")
            for m in CALL.finditer(text):
                key = m.group(1)
                if key not in known:
                    line = text.count("\n", 0, m.start()) + 1
                    missing.setdefault(key, []).append(
                        f"{path.relative_to(ROOT)}:{line}")
    if missing:
        print(f"i18n: {len(missing)} key(s) used in JS but not defined:", file=sys.stderr)
        for key in sorted(missing):
            print(f"  - {key}  ({', '.join(missing[key][:3])})", file=sys.stderr)
        print("add them to every language block in static/js/i18n-data.js", file=sys.stderr)
        return 1
    print(f"i18n calls OK: every t(\"…\") literal in static JS resolves "
          f"({len(known)} keys defined)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
