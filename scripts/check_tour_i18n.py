#!/usr/bin/env python3
"""CI guard: every UI language ships a complete onboarding-tour translation.

Sources of truth and the checks against them:
  - LANGS in static/js/i18n-data.js — the app's language list;
  - TOUR_STRINGS in static/js/onboarding-strings.js must cover exactly the
    LANGS codes, and every language must carry exactly the key set of `en`
    (a missing key would surface as a raw key name in the tour card);
  - HF_TOUR in static/js/hf-text.js must cover exactly the LANGS codes, each
    with the nav labels and the same number of steps, anchored to the same
    elements, as `en`;
  - HF_LANGS in static/js/hf-text.js is an inline mirror of LANGS (the /hf page
    stays independent of the big dictionary) — codes and order must match.

Stdlib-only, no JS runtime needed: the dictionaries are parsed by their fixed
formatting (language blocks at a known indent, one string per line).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []


def fail(msg):
    errors.append(msg)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ── LANGS: the app's language list ───────────────────────────────────────────
i18n = read("static/js/i18n-data.js")
langs_src = re.search(r"export const LANGS = \[(.*?)\n\];", i18n, re.S)
if not langs_src:
    sys.exit("check_tour_i18n: LANGS not found in static/js/i18n-data.js")
LANGS = re.findall(r'code: "(\w+)"', langs_src.group(1))
if len(LANGS) < 2:
    sys.exit(f"check_tour_i18n: suspiciously short LANGS: {LANGS}")

# ── TOUR_STRINGS: index/kanban/config tours ──────────────────────────────────
tours = read("static/js/onboarding-strings.js")
tour_blocks = dict(re.findall(r"^(\w+): \{\n(.*?)\n\},", tours, re.S | re.M))
if "en" not in tour_blocks:
    sys.exit("check_tour_i18n: could not parse TOUR_STRINGS (no `en` block)")


def tour_keys(block):
    return set(re.findall(r'^  (\w+): "', block, re.M))


en_keys = tour_keys(tour_blocks["en"])
if len(en_keys) < 40:
    sys.exit(f"check_tour_i18n: en block parsed to only {len(en_keys)} keys")

for code in LANGS:
    if code not in tour_blocks:
        fail(f"TOUR_STRINGS: language `{code}` is missing entirely")
        continue
    keys = tour_keys(tour_blocks[code])
    for k in sorted(en_keys - keys):
        fail(f"TOUR_STRINGS.{code}: missing key {k}")
    for k in sorted(keys - en_keys):
        fail(f"TOUR_STRINGS.{code}: unknown key {k} (not in en)")
for code in sorted(set(tour_blocks) - set(LANGS)):
    fail(f"TOUR_STRINGS: language `{code}` is not in LANGS (dead translation)")

# ── HF_TOUR: the /hf page tour ───────────────────────────────────────────────
hf = read("static/js/hf-text.js")
hf_src = re.search(r"^export const HF_TOUR = \{\n(.*?)\n\};", hf, re.S | re.M)
if not hf_src:
    sys.exit("check_tour_i18n: HF_TOUR not found in static/js/hf-text.js")
hf_blocks = dict(re.findall(r"^  (\w+): \{\n(.*?)\n  \},", hf_src.group(1), re.S | re.M))
if "en" not in hf_blocks:
    sys.exit("check_tour_i18n: could not parse HF_TOUR (no `en` block)")

HF_KEYS = ("btn:", "label:", "langPick:", "next:", "back:", "done:", "skip:")
en_steps = len(re.findall(r"^      \[", hf_blocks["en"], re.M))
# A translated step still points at the same element: the anchor is code, not text.
en_anchors = re.findall(r'^      \[(null|"[^"]*"),', hf_blocks["en"], re.M)
en_bodies = re.findall(r'^       ("(?:[^"\\]|\\.)*")\],$', hf_blocks["en"], re.M)
if len(en_bodies) != en_steps:
    sys.exit(f"check_tour_i18n: HF_TOUR.en has {en_steps} steps but {len(en_bodies)} bodies parsed")
if en_steps < 3:
    sys.exit(f"check_tour_i18n: HF_TOUR.en parsed to only {en_steps} steps")

for code in LANGS:
    if code not in hf_blocks:
        fail(f"HF_TOUR: language `{code}` is missing entirely")
        continue
    block = hf_blocks[code]
    for key in HF_KEYS:
        if key not in block:
            fail(f"HF_TOUR.{code}: missing {key.rstrip(':')}")
    steps = len(re.findall(r"^      \[", block, re.M))
    if steps != en_steps:
        fail(f"HF_TOUR.{code}: {steps} steps, en has {en_steps}")
    anchors = re.findall(r'^      \[(null|"[^"]*"),', block, re.M)
    if anchors != en_anchors:
        fail(f"HF_TOUR.{code}: step anchors {anchors} differ from en {en_anchors}")
    if code != "en":
        # A step body still in English is a language the tour never reached.
        for i, body in enumerate(re.findall(r'^       ("(?:[^"\\]|\\.)*")\],$', block, re.M)):
            if i < len(en_bodies) and body == en_bodies[i]:
                fail(f"HF_TOUR.{code}: step {i + 1} is still the English text")
for code in sorted(set(hf_blocks) - set(LANGS)):
    fail(f"HF_TOUR: language `{code}` is not in LANGS (dead translation)")

# ── HF_LANGS: the /hf page's inline mirror of LANGS ──────────────────────────
hf_langs_src = re.search(r"^export const HF_LANGS = \[(.*?)\n\];", hf, re.S | re.M)
if not hf_langs_src:
    sys.exit("check_tour_i18n: HF_LANGS not found in static/js/hf-text.js")
hf_langs = re.findall(r'\["(\w+)"', hf_langs_src.group(1))
if hf_langs != LANGS:
    fail(f"HF_LANGS does not mirror LANGS:\n  LANGS    = {LANGS}\n  HF_LANGS = {hf_langs}")

if errors:
    print(f"check_tour_i18n: FAIL ({len(errors)} problems)")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print(f"check_tour_i18n: OK — {len(LANGS)} languages × {len(en_keys)} tour keys, "
      f"HF tour {en_steps} steps, HF_LANGS mirror intact")
