#!/usr/bin/env python3
"""The caravan's parts take their colours, font sizes and radii from one place (static/css/ui.css), step 0 of the redesign.

The screens grew a look each (2026-10-25, the owner: "a Frankenstein"): a new function came with its own buttons, heights
and colours, so the board spoke three window languages. The foundation gives every part one home — a token in ui.css's
`:root`, a rule for each part beside it, the markup in static/js/ui-parts.js — and this check keeps it so.

What fails:
- a raw colour (#hex, rgb(), rgba(), hsl(), hsla()) in a UI file's rules outside its `:root` token block;
- a font size not taken from a token (`font-size:` or `font:` without var(--ui-fs-…)) in a UI file's rules;
- a radius that is not a token, 0, 50% or 999px (a pill) in a UI file's rules;
- a var(--ui-…) used without a fallback that ui.css does not declare (a typo draws nothing, and nothing says so);
- a ui- class the parts draw, in any of their kinds, that ui.css does not style; a colour in an inline style a part writes.

The classes are taken from the parts themselves: every part is drawn by node in every kind it declares, so a class put
together from a kind (`ui-band--${tone}`) is checked as it is drawn. `UI_CSS` lists the stylesheets already moved onto the
parts; a screen converted later joins it, and then takes no colour of its own either.

Negative self-test: scripts/test_guards_fail.py (a raw colour in a rule, a class the stylesheet does not have).

Run: python3 scripts/check_ui_tokens.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _node import find_node, node_search_paths, node_args  # noqa: E402

TOKENS = ROOT / "static" / "css" / "ui.css"
#: The stylesheets moved onto the parts: their rules take colours, font sizes and radii from the tokens only.
UI_CSS = ["static/css/ui.css", "static/css/machine.css", "static/css/add-model.css"]
PARTS = ROOT / "static" / "js" / "ui-parts.js"

COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(")
RADIUS_OK = re.compile(r"^(?:var\(--ui-r\d\)|0|50%|999px)(?:\s+(?:var\(--ui-r\d\)|0|50%|999px))*$")

# Draws every part in every kind it declares and prints the html: the classes and inline styles are read from what is drawn.
DRAW = r"""
import { pathToFileURL } from "node:url";
const P = await import(pathToFileURL(process.argv[1]).href);
const out = [];
const add = (part) => out.push(part.html());
for (const kind of P.Button.KINDS) add(new P.Button({ kind, text: "Go", icon: "plus", label: "Go" }));
add(new P.Button({ kind: "plain", text: "Off", disabled: true, title: "why" }));
for (const name of Object.keys(P.Icon.PATHS)) out.push(P.Icon.svg(name));
add(new P.Switch({ label: "s" })); add(new P.Switch({ label: "s", on: true, busy: true, disabled: true }));
add(new P.Seg({ label: "g", options: [{ text: "a", count: 1, on: true }, { text: "b" }] }));
add(new P.Pill({ text: "p", count: 2, on: true }));
for (const tone of P.Badge.TONES) add(new P.Badge({ tone, text: "b" }));
for (const tone of P.Band.TONES) add(new P.Band({ tone, title: "t", sub: "s", action: "" }));
for (const noteTone of P.Row.NOTES) add(new P.Row({ title: "r", facts: "f", value: "1", note: noteTone ? "n" : "", noteTone, live: true, open: "data-x", label: "l", cols: "1fr" }));
add(new P.Row({ title: "plain" }));
const parts = [1, 2, 3, 4, 5, 6].map((series) => ({ value: 1, series })).concat(P.Meter.KINDS.map((kind) => ({ value: 1, kind })));
add(new P.Meter({ label: "m", side: "x", value: "1", unit: "u", total: 100, parts, foot: "f" }));
add(new P.Meter({ label: "m", tile: false }));
const blocks = [1, 2, 3, 4, 5, 6].map((series) => ({ value: 10, series, name: "n", figure: "1", pick: "data-x", on: series === 1 }))
  .concat(P.Lane.KINDS.map((kind) => ({ value: 15, kind, name: "n", figure: "1" })));
add(new P.Lane({ label: "l", side: "s", free: "f", total: 100, blocks, foot: "f" }));
add(new P.Lane({ label: "l" }));
for (const tone of P.Band.TONES) add(new P.Band({ tone, title: "t", sub: "s", inline: true }));
add(new P.Tabs({ label: "t", tabs: [{ text: "a", count: 3, on: true }, { text: "b" }], cls: "ui-win-tabs" }));
add(new P.Addr({ text: "10.0.0.1:1", label: "copy" }));
for (const tag of P.Frame.TAGS) add(new P.Frame({ tag, title: "w", facts: "f", body: "b", foot: "" }));
for (const kind of P.Frame.KINDS) add(new P.Frame({ kind, title: "w", band: "x", body: "b" }));
add(new P.Menu({ label: "m", items: [{ text: "a" }, "-", { text: "b", danger: true, disabled: true, title: "why" }] }));
console.log(JSON.stringify(out));
"""


def rules(css):
    """(selector, body) of each rule outside `:root`, comments left out; nested @media rules read like the others."""
    text = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)
            if not sel.strip().startswith(":root")]


def declared(css):
    return set(re.findall(r"(--ui-[\w-]+)\s*:", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))


def styled_classes(css):
    return set(re.findall(r"\.(ui-[\w-]+)", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))


def css_problems(rel, css, known):
    bad = []
    for sel, body in rules(css):
        for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
            value = value.strip()
            if prop.startswith("--"):
                continue
            if COLOUR.search(value):
                bad.append(f"{rel}: {sel} {{ {prop}: {value} }} — a raw colour: take a token from ui.css :root")
            if prop == "font-size" and "var(--ui-fs-" not in value:
                bad.append(f"{rel}: {sel} {{ font-size: {value} }} — a font size not from a token (--ui-fs-…)")
            if prop == "font" and "var(--ui-fs-" not in value and value != "inherit":
                bad.append(f"{rel}: {sel} {{ font: {value} }} — a font size not from a token (--ui-fs-…)")
            if prop.endswith("radius") and not RADIUS_OK.match(value):
                bad.append(f"{rel}: {sel} {{ {prop}: {value} }} — a radius not from a token (--ui-r1…4, 0, 50%, 999px)")
        for name in re.findall(r"var\((--ui-[\w-]+)\s*\)", body):
            if name not in known:
                bad.append(f"{rel}: {sel} uses {name}, which ui.css does not declare")
    return bad


def drawn():
    node = find_node()
    if node is None:
        print("ui tokens: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return None
    proc = subprocess.run(node_args(node, "--input-type=module", "-e", DRAW, str(PARTS)), capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise SystemExit(f"ui tokens: the parts did not draw:\n{proc.stderr.strip()[:1200]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main():
    css = TOKENS.read_text(encoding="utf-8")
    known = declared(css)
    problems = []
    for rel in UI_CSS:
        problems += css_problems(rel, (ROOT / rel).read_text(encoding="utf-8"), known)
    js = PARTS.read_text(encoding="utf-8")
    for name in re.findall(r"var\((--ui-[\w-]+)\s*\)", js):
        if name not in known:
            problems.append(f"static/js/ui-parts.js uses {name}, which ui.css does not declare")

    html = drawn()
    if html is None:
        return 0
    styled = set()
    for rel in UI_CSS:
        styled |= styled_classes((ROOT / rel).read_text(encoding="utf-8"))
    used = set()
    for h in html:
        for value in re.findall(r'class="([^"]*)"', h):
            used |= {c for c in value.split() if c.startswith("ui-")}
        for style in re.findall(r'style="([^"]*)"', h):
            if COLOUR.search(style) or re.search(r"\b(?:color|background)\s*:", style):
                problems.append(f"a part writes a colour in an inline style: {style!r} — a colour is a class of ui.css")
    for cls in sorted(used - styled):
        problems.append(f"the parts draw .{cls}, which no UI stylesheet styles")

    if problems:
        print(f"ui tokens: FAILED ({len(problems)})", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 1
    print(f"ui tokens OK: {len(UI_CSS)} stylesheet(s) on the tokens, {len(known)} tokens, {len(used)} classes the parts draw — all styled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
