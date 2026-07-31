#!/usr/bin/env python3
"""CI guard: every i18n key the UI asks for must actually be defined.

check_messages_i18n.py compares the LANGUAGES against each other — it proves
they agree, not that they cover what the code asks for. So a new panel could
ship calling nine keys that exist nowhere, the guard stayed green, and the UI
rendered its own key names as labels. That happened; this closes it.

t() falls back to the key, so a miss is cosmetic rather than fatal — which is
exactly why nothing caught it. Cosmetic and invisible is still shipped-broken.

Three lookup routes, because the UI has three:

  1. t("key") in the static JS            → static/js/i18n/en.js (+ tours)
  2. [data-i18n*] in the static HTML       → the same dictionary, resolved by
     applyLanguage(); this route was UNCHECKED until a mistyped
     data-i18n-aria showed what that costs — an aria-label whose value is the
     key itself, which a screen reader then reads aloud, letter salad and all.
     A missed [data-i18n] is at least visible on screen; a missed name is only
     audible, and only to the people least able to work around it.
  3. hfT("key") in static/hf.js            → hf.js's OWN 20-language HFS table,
     a separate dictionary that predates the shared one.

Dynamic keys (t(someVar), t(`x${y}`)) cannot be checked and are skipped: this
looks only at plain string literals.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = ROOT / "static" / "js" / "i18n" / "en.js"
# Long-form tour texts deliberately live apart from the short UI strings, but
# they resolve through the same t() — so both files define the known set.
TOURS = ROOT / "static" / "js" / "onboarding-strings.js"
JS_DIRS = [ROOT / "static" / "js", ROOT / "static"]

HF = ROOT / "static" / "hf.js"

# A literal key, and NOT the head of a built one: t("period_" + n) is dynamic
# and unknowable from here, so the trailing `+` disqualifies the match.
CALL = re.compile(r'\bt\(\s*"([A-Za-z][\w.]*)"(?!\s*\+)')
HF_CALL = re.compile(r'\bhfT\(\s*"([A-Za-z][\w.]*)"(?!\s*\+)')
# Keys defined in the en block — the canonical set; the other guard proves the
# rest match it.
DEF = re.compile(r'^\s{4}([A-Za-z][\w]*)\s*:', re.M)
# Every attribute applyLanguage() turns into text or a name. Keep this in step
# with static/js/i18n.js — an attribute added there and forgotten here is an
# unchecked lookup, which is the hole this half of the guard exists to close.
# [data-fieldhelp] is deliberately absent: its values are raw env-var names
# looked up in a different table, with the key itself as the intended fallback.
I18N_ATTRS = ("data-i18n", "data-i18n-placeholder", "data-title-i18n",
              "data-i18n-tip", "data-i18n-aria")
ATTR = re.compile(r'\b(' + "|".join(I18N_ATTRS) + r')="([A-Za-z][\w.]*)"')


def check_lang_wiring() -> list:
    """Every page that offers a language picker must say what to repaint.

    i18n.js used to answer that itself, by importing the BOARD's renderAll()
    and calling it everywhere. On the two pages that have no board that threw
    — `state` is null there — so switching language left the page half
    translated and put an uncaught error in the console. Two rules keep it
    from coming back:

      1. i18n.js must not import a page's renderer. It is shared by all of
         them; the moment it knows about one, it is guessing about the rest.
      2. A page that calls setupLangSelect() must also call onLangChange().
         Forgetting it is silent: attribute text still updates, and anything
         the page builds with t() into innerHTML quietly keeps the old
         language until the next refresh.
    """
    problems = []
    src = (ROOT / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    for m in re.finditer(r'^import .*? from "\./([\w-]+)\.js";', src, re.M):
        if m.group(1) in ("topology-render", "canvas", "polling", "models-page",
                          "system-page", "main"):
            problems.append(
                f"i18n.js imports ./{m.group(1)}.js — a shared module must not "
                f"reach into a page's renderer; register it with onLangChange()")
    for path in sorted((ROOT / "static" / "js").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        if "setupLangSelect()" not in text or path.name == "i18n.js":
            continue
        if "onLangChange(" not in text:
            problems.append(
                f"{path.relative_to(ROOT)} offers the language picker but never "
                f"calls onLangChange() — anything it renders with t() will keep "
                f"the old language")
    return problems


def main() -> int:
    # English is its own module since the split — and it is still the canonical
    # set, because t() falls back to it for every key another language lacks.
    if not EN.exists():
        print(f"cannot find {EN}", file=sys.stderr)
        return 1
    src = EN.read_text(encoding="utf-8")
    known = set(re.findall(r'^\s{2}([A-Za-z][\w]*)\s*:', src, re.M))
    # fieldHelp lives one level deeper and is looked up by its own helper.
    known |= set(re.findall(r'^\s{4}([A-Za-z][\w]*)\s*:', src, re.M))
    if TOURS.exists():
        tsrc = TOURS.read_text(encoding="utf-8")
        known |= set(re.findall(r'^\s{2}([A-Za-z][\w]*)\s*:', tsrc, re.M))

    # hf.js carries its own table. Read the `en:` block only — the other guard
    # proves the remaining nineteen agree with it.
    hf_known = set()
    hf_text = ""
    if HF.exists():
        hf_text = HF.read_text(encoding="utf-8")
        start = re.search(r'^  en:\s*\{$', hf_text, re.M)
        end = re.search(r'^  ru:\s*\{$', hf_text, re.M)
        if not start or not end:
            print("cannot find the en/ru blocks of hf.js's HFS table",
                  file=sys.stderr)
            return 1
        hf_known = set(re.findall(r'\b([A-Za-z][\w]*)\s*:\s*"',
                                  hf_text[start.end():end.start()]))

    missing = {}
    checked = 0

    def note(key, where, pool):
        nonlocal checked
        checked += 1
        if key not in pool:
            missing.setdefault(key, []).append(where)

    for d in JS_DIRS:
        for path in sorted(d.glob("*.js")):
            if path.name == "i18n-data.js":
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT)
            for m in CALL.finditer(text):
                note(m.group(1), f"{rel}:{text.count(chr(10), 0, m.start()) + 1}", known)
    for m in HF_CALL.finditer(hf_text):
        note(m.group(1),
             f"static/hf.js:{hf_text.count(chr(10), 0, m.start()) + 1} (hfT)",
             hf_known)
    for path in sorted((ROOT / "static").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for m in ATTR.finditer(text):
            note(m.group(2),
                 f"{rel}:{text.count(chr(10), 0, m.start()) + 1} ({m.group(1)})",
                 known)

    wiring = check_lang_wiring()

    if missing:
        print(f"i18n: {len(missing)} key(s) asked for but not defined:", file=sys.stderr)
        for key in sorted(missing):
            print(f"  - {key}  ({', '.join(missing[key][:3])})", file=sys.stderr)
        print("t()/[data-i18n*] keys go in every static/js/i18n/<lang>.js; "
              "hfT() keys go in the HFS table in static/hf.js", file=sys.stderr)
    if wiring:
        for problem in wiring:
            print(f"i18n wiring: {problem}", file=sys.stderr)
    if missing or wiring:
        return 1
    print(f"i18n calls OK: {checked} lookups resolve — t(\"…\") in JS, "
          f"[data-i18n*] in HTML, hfT(\"…\") on /hf "
          f"({len(known)} shared keys + {len(hf_known)} hf keys defined)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
