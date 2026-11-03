#!/usr/bin/env python3
"""Value snapshot: the page a cell serves itself, linked from its card (1.3.613) — static/js/cell-page.js PageCell (the card's 🌐).

PersonaPlex serves its own page at the root of its port, and a microphone needs a secure page: the page is reached at an https name of its own on the reverse proxy in
front of the cell, which the cell's PAGE_URL names. The form an address must have is one pattern, the program's, and the browser reads it from the runner's registry row.
Both are held to ONE table of cases, contract/cell_page.json (the program's half: rust/crates/admin/tests/contract.rs): an address one side keeps and the other refuses
would be a link the card draws to a page the save refused, or a page the save kept and the card never links.

Pinned by value, each claim with a positive and a negative: the table; the registry rows (PersonaPlex alone serves a page); the card's 🌐 — open on a running cell with
its address, shut saying why (no address, not a page's, stopped), none for a runner without a page, the address escaped in its attribute.

Words are read from static/js/i18n/en.js programmatically.

Run: python3 scripts/test_cell_page.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contract import Contract  # noqa: E402
from _node import find_node, node_args, node_search_paths, probe_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


#: (what a config names, what is kept: the address trimmed, "" for none, None for a refusal). Both sides answer each.
CASES = [(row["said"], row["kept"]) for row in Contract.table("cell_page")["cases"]]
TABLES = Contract.table("controller")
PATTERN = TABLES["pagePattern"]


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
let REG = JSON.parse(process.env.PAGE_REGISTRY);
globalThis.__stubReturns = { "llama-edit.runnerRegistry": () => REG };
const st = await import(pathToFileURL(root + "/state.js").href);
st.setState({ runners: REG });
const { PageCell } = await import(pathToFileURL(root + "/cell-page.js").href);
const out = {};
const CASES = JSON.parse(process.env.PAGE_CASES);
out.addresses = CASES.map((raw) => new PageCell({ hostId: "m1", port: 22021, runner: "personaplex", config: { PAGE_URL: raw } }).address);

const tag = (h) => { const m = String(h).match(/^<(a|button)\b[^>]*>/); if (!m) return null;
  const a = (n) => (m[0].match(new RegExp(" " + n + '="([^"]*)"')) || [])[1] ?? null;
  return { tag: m[1], cls: a("class"), t: a("data-t"), id: a("data-t-id"), page: a("data-cell-page"), href: a("href"), target: a("target"),
           title: a("title"), disabled: / disabled[ >]/.test(m[0]), label: String(h).replace(/<[^>]*>/g, "") }; };
const pp = (config) => new PageCell({ hostId: "m1", port: 22021, runner: "personaplex", config });
out.running = tag(pp({ PAGE_URL: " https://personaplex.example.org " }).buttonHtml(true));
out.stopped = tag(pp({ PAGE_URL: "https://personaplex.example.org" }).buttonHtml(false));
out.none = tag(pp({}).buttonHtml(true));
out.noneStopped = tag(pp({ PAGE_URL: "  " }).buttonHtml(false));
out.bad = tag(pp({ PAGE_URL: "http://personaplex.example.org" }).buttonHtml(true));
out.quoted = pp({ PAGE_URL: 'https://personaplex.example.org/x"onmouseover="alert(1)' }).buttonHtml(true);
out.other = new PageCell({ hostId: "m1", port: 22024, runner: "minicpm-omni", config: { PAGE_URL: "https://personaplex.example.org" } }).buttonHtml(true);
out.unknown = new PageCell({ hostId: "m1", port: 22030, runner: "", config: { PAGE_URL: "https://personaplex.example.org" } }).buttonHtml(true);
out.spec = [pp({}).spec, new PageCell({ runner: "minicpm-omni" }).spec];
// A row whose pattern the browser cannot read draws no link — not any link.
REG = [{ id: "broken", page: { field: "PAGE_URL", pattern: "(" } }];
const broken = new PageCell({ hostId: "m1", port: 22031, runner: "broken", config: { PAGE_URL: "https://personaplex.example.org" } });
out.broken = [broken.address, tag(broken.buttonHtml(true))];
// A row that names another field reads that one.
REG = [{ id: "other-field", page: { field: "SITE", pattern: process.env.PAGE_PATTERN } }];
out.otherField = [new PageCell({ runner: "other-field", config: { SITE: "https://site.example.org", PAGE_URL: "https://personaplex.example.org" } }).address,
  new PageCell({ runner: "other-field", config: { PAGE_URL: "https://personaplex.example.org" } }).address];
console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if not node:
        print(f"cell page: node not found (looked in {', '.join(node_search_paths())})")
        return 1
    en = json.loads(subprocess.run(
        node_args(node, "--input-type=module", "-e",
                  f"const m = await import({json.dumps((ROOT / 'static/js/i18n/en.js').as_uri())}); console.log(JSON.stringify(m.default));"),
        capture_output=True, text=True, check=True, timeout=60).stdout)
    reg = TABLES["runners"]
    harness = ROOT / "scripts" / "_js_harness.mjs"
    probe_path = ROOT / "scripts" / ".probe_cell_page.tmp.mjs"
    probe_path.write_text(PROBE)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "llama-edit,form",
               "PAGE_REGISTRY": json.dumps(reg), "PAGE_PATTERN": PATTERN, "PAGE_CASES": json.dumps([raw for raw, _kept in CASES]),
               "LANG": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(probe_args(node, harness, probe_path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        probe_path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"cell page FAILED: node exited {run.returncode}")
        return 1
    o = json.loads(run.stdout.strip().splitlines()[-1])

    def w(key, **args):
        """The English words of `key`, as an attribute carries them (utils.js escapeHtml)."""
        text = en[key]
        for k, v in args.items():
            text = text.replace("{" + k + "}", str(v))
        return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                .replace("'", "&#39;"))

    print("one table of addresses, the card by the program's pattern:")
    for (raw, kept), js in zip(CASES, o["addresses"]):
        check(js == (kept or ""), f"{raw!r}: the card {'links ' + repr(kept) if kept else 'draws no link'} (card {js!r})")
    accepted = [raw for raw, kept in CASES if kept]
    refused = [raw for raw, kept in CASES if kept is None]
    check(len(accepted) >= 9 and len(refused) >= 20, f"the table holds both: {len(accepted)} kept, {len(refused)} refused")

    print("the runners' rows:")
    rows = {r["id"]: r for r in reg}
    pages = {rid: r["page"] for rid, r in rows.items() if "page" in r}
    check(pages == {"personaplex": {"field": "PAGE_URL", "pattern": PATTERN}},
          f"PersonaPlex's row says it serves a page: the field and the pattern the card matches ({sorted(pages)})")
    check("page" not in rows["minicpm-omni"] and "page" not in rows["llama-server"],
          "negative: no other runner's row says so — MiniCPM-o is talked to in the board's own window")
    field_help = json.loads((ROOT / "rust/crates/admin/src/config/field_help.json").read_text(encoding="utf-8"))
    check(field_help.get("PAGE_URL", "").startswith("The https address of the page") and en.get("fieldHelp", {}).get("PAGE_URL") == field_help["PAGE_URL"],
          "PAGE_URL's help is the same in the program's words and the form's dictionary")

    print("the card's 🌐:")
    # A button the module did not draw is None: read as an empty one, so a broken module fails its checks, not the test.
    for key in ("running", "stopped", "none", "noneStopped", "bad"):
        o[key] = o[key] or {}
    o["broken"][1] = o["broken"][1] or {}
    run_ = o["running"]
    check(run_ == {"tag": "a", "cls": "node-action-btn ok page", "t": "cell-page", "id": "m1:22021", "page": "m1:22021",
                   "href": "https://personaplex.example.org", "target": None,
                   "title": w("pageOpenTitle", address="https://personaplex.example.org"), "disabled": False,
                   "label": "🌐" + w("pageOpen")},
          f"a running cell with its address: a link to that address, in this tab (no target), named for the tests ({run_})")
    check(o["stopped"] and o["stopped"] == {**o["stopped"], "tag": "button", "disabled": True, "title": w("pageOpenStopped"), "href": None, "t": None},
          "negative: stopped — shut, saying to start it; nothing to follow")
    check(o["none"].get("tag") == "button" and o["none"].get("disabled") is True
          and o["none"].get("title") == w("pageNeedsUrl", field="PAGE_URL")
          and o["noneStopped"].get("title") == w("pageNeedsUrl", field="PAGE_URL"),
          "negative: no address — shut, saying where to write one, stopped or running (the missing address is the thing to fix)")
    check(o["bad"].get("tag") == "button" and o["bad"].get("disabled") is True and o["bad"].get("title") == w("pageBadUrl", field="PAGE_URL"),
          "negative: an address that is no page's — shut, saying so, and no link to plain http")
    check('href="https://personaplex.example.org/x&quot;onmouseover=&quot;alert(1)"' in o["quoted"]
          and ' onmouseover=' not in o["quoted"],
          "the address escaped in its attribute: a quote in it stays inside the href")
    check(o["other"] == "" and o["unknown"] == "" and o["spec"] == [{"field": "PAGE_URL", "pattern": PATTERN}, None],
          "negative: a runner that serves no page gets no 🌐 at all, whatever its config holds")
    check(o["broken"][0] == "" and o["broken"][1].get("disabled") is True and o["broken"][1].get("title") == w("pageBadUrl", field="PAGE_URL"),
          "negative: a pattern the browser cannot read draws no link, and says the address is not a page's")
    check(o["otherField"] == ["https://site.example.org", ""],
          "the field is the row's to name: another field is read, PAGE_URL then is not")

    if _fail:
        print(f"\ncell page FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("\ncell page OK: one form of a page's address, at the save and on the card")
    return 0


if __name__ == "__main__":
    sys.exit(main())
