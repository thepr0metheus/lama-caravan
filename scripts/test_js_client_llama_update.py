#!/usr/bin/env python3
"""Actual client-llama-update.js: what a machine's ⇪ installs, and the words that say so (1.3.570).

⇪ on a machine's llama.cpp chip sends the controller's llama.cpp commit to the update route, and the route reads an empty tag as "the
latest release". A controller in a container (the NAS) has no llama.cpp checkout, so its commit is empty: ⇪ installed the latest release
while its tooltip and its confirm window said "to the controller's build". ClientLlamaUpdate makes the tag, the tooltip and the confirm
window one reading, by value: with a commit the words are the old ones and the tag is the commit; without one the words say "the latest
release" and the tag is empty; and before the controller has said what it runs there is no button to word.

The module is loaded FOR REAL; i18n and utils are stubbed (a key stands for its words, `api` and `toast` write down what they get),
state is the real one. The click is driven through `bind` with a stand-in container, as the board does it.

Run: python3 scripts/test_js_client_llama_update.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = sorted(p.stem for p in (ROOT / "static" / "js" / "i18n").glob("*.js"))

PROBE = r'''
import assert from "node:assert/strict";
const asked = [], sent = [], toasts = [];
let answer = true, apiError = null;
globalThis.__stubReturns = {
  "i18n.t": (k) => `«${k}»`,
  "utils.api": async (path, opts) => { sent.push({ path, method: opts.method, ...JSON.parse(opts.body) }); if (apiError) throw new Error(apiError); return { ok: true }; },
  "utils.toast": (message) => toasts.push(message),
};
globalThis.window = globalThis;
globalThis.confirm = (message) => { asked.push(message); return answer; };
const st = await import("../static/js/state.js");
const { ClientLlamaUpdate } = await import("../static/js/client-llama-update.js");
const en = (await import("../static/js/i18n/en.js")).default;
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };
const reset = () => { asked.length = 0; sent.length = 0; toasts.length = 0; answer = true; apiError = null; };
const view = (info) => { const u = ClientLlamaUpdate.of(info); return { offered: u.offered, follows: u.followsController, tag: u.tag, title: u.titleKey, confirm: u.confirmKey }; };

const FOLLOWS = { offered: true, follows: true, tag: "abc1234", title: "updateClientLlama", confirm: "updateClientLlamaConfirm" };
const LATEST = (offered) => ({ offered, follows: false, tag: "", title: "updateClientLlamaLatest", confirm: "updateClientLlamaLatestConfirm" });

// ── the reading of the controller ──
{
  assert.deepEqual(view({ version: "version: 9947 (abc1234)", git: { branch: "master", head: "abc1234" } }), FOLLOWS);
  pin(true, "a controller with a llama.cpp commit: ⇪ is there, sends that commit, and says 'the controller's build' — the words it always had");
  const nas = { binary: "/opt/llama-server", binaryExists: false, version: "llama-server binary not found", git: { branch: "", head: "", remote: "" } };
  assert.deepEqual(view(nas), LATEST(true));
  pin(true, "a controller in a container has no commit: ⇪ is there, sends an empty tag (the route's latest release), and says 'the latest release'");
  pin(view(nas).tag === "" && view(nas).confirm !== FOLLOWS.confirm && view(nas).title !== FOLLOWS.title,
    "negative: the words of the controller's build never stand on an empty tag");
  assert.deepEqual(view({ git: { head: "  abc1234\n" } }), FOLLOWS);
  pin(true, "the commit is sent trimmed: a newline from `git rev-parse` is not part of a tag");
  assert.deepEqual([view({ git: { head: "   " } }), view({ git: { head: null } }), view({ git: {} })], [LATEST(true), LATEST(true), LATEST(true)]);
  pin(true, "negative: a blank commit, a null one and a missing one are no commit — never the tag 'null' or 'undefined'");
  const unread = [undefined, null, {}, { version: "version: 9947 (abc1234)" }, { git: null }, { git: "abc1234" }, "abc1234", 42, []];
  assert.deepEqual(unread.map(view), unread.map(() => LATEST(false)));
  pin(true, "before the controller has said what it runs (no reading, no git block, junk) there is no button; and what it would say is the empty tag's words");
  pin(ClientLlamaUpdate.of(undefined).offered === false && ClientLlamaUpdate.of({ git: {} }).offered === true,
    "boundary: a git block with nothing in it is a controller that said it has no commit — not one that said nothing");
}

// ── the click ──
{
  reset();
  await ClientLlamaUpdate.of({ git: { head: "abc1234" } }).start("h1");
  assert.deepEqual(asked, ["«updateClientLlamaConfirm»"]);
  assert.deepEqual(sent, [{ path: "/api/fleet/llama-update", method: "POST", hostId: "h1", tag: "abc1234" }]);
  assert.deepEqual(toasts, ["«clientLlamaBuilding»"]);
  pin(true, "with a commit: the window asks the controller's-build question, the route gets that machine and that commit, the operator is told it builds");
  reset();
  await ClientLlamaUpdate.of({ git: { head: "" } }).start("h2");
  assert.deepEqual(asked, ["«updateClientLlamaLatestConfirm»"]);
  assert.deepEqual(sent, [{ path: "/api/fleet/llama-update", method: "POST", hostId: "h2", tag: "" }]);
  pin(true, "without one: the window asks the latest-release question and the route gets the empty tag — the words and the tag are one reading");
  reset();
  answer = false;
  await ClientLlamaUpdate.of({ git: { head: "abc1234" } }).start("h1");
  pin(asked.length === 1 && sent.length === 0 && toasts.length === 0, "negative: 'Cancel' sends nothing and says nothing");
  reset();
  apiError = "scout is busy";
  await ClientLlamaUpdate.of({ git: { head: "abc1234" } }).start("h1");
  assert.deepEqual(toasts, ["scout is busy"]);
  pin(sent.length === 1, "the scout's refusal is said in its own words, and not as 'building'");
  reset();
  await ClientLlamaUpdate.of(undefined).start("");
  assert.deepEqual([asked, sent], [["«updateClientLlamaLatestConfirm»"], [{ path: "/api/fleet/llama-update", method: "POST", hostId: "", tag: "" }]]);
  pin(true, "a click that finds no reading of the controller still says what it does — the latest release — and sends the same");
}

// ── the wiring ──
{
  const make = (host) => { const b = { host, handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; }, getAttribute(name) { return name === "data-update-client-llama" ? this.host : null; } }; return b; };
  const root = (buttons) => { const r = { asked: [], querySelectorAll(selector) { r.asked.push(selector); return selector === "[data-update-client-llama]" ? buttons : []; } }; return r; };
  const a = make("h1"), b = make("h2"), c = make(null);
  const r = root([a, b, c]);
  st.setState({ ...st.state, llamaCpp: { git: { head: "old0000" } } });
  ClientLlamaUpdate.bind(r);
  pin(r.asked.length === 1 && r.asked[0] === "[data-update-client-llama]" && [a, b, c].every((x) => typeof x.handlers.click === "function"),
    "every ⇪ under the container gets a click handler, found by its data attribute");
  reset();
  st.setState({ ...st.state, llamaCpp: { git: { head: "" } } });
  let stopped = 0;
  await b.handlers.click({ stopPropagation: () => { stopped++; } });
  assert.deepEqual(asked, ["«updateClientLlamaLatestConfirm»"]);
  assert.deepEqual(sent, [{ path: "/api/fleet/llama-update", method: "POST", hostId: "h2", tag: "" }]);
  pin(stopped === 1, "the click does not reach the card under it");
  pin(true, "the controller is read AT THE CLICK, not when the button was drawn: the commit was there at the bind and gone at the click — the words and the tag follow the click");
  reset();
  await c.handlers.click({ stopPropagation: () => {} });
  pin(sent.length === 1 && sent[0].hostId === "", "a button with no machine in it sends an empty one, as the handler always did — the route refuses it in its own words");
  pin(ClientLlamaUpdate.bind(null) === undefined && ClientLlamaUpdate.bind(undefined) === undefined,
    "negative: a board without its container binds nothing and does not throw");
}

// ── the words ──
{
  pin(en.updateClientLlama.includes("controller's build") && en.updateClientLlamaConfirm.includes("controller's build"),
    "the old words promise the controller's build — and are used only when there is one");
  pin(en.updateClientLlamaLatest.includes("latest release") && en.updateClientLlamaLatestConfirm.includes("latest release")
      && !en.updateClientLlamaLatest.includes("controller's build") && !en.updateClientLlamaLatestConfirm.includes("controller's build"),
    "the new words say 'the latest release' and never 'the controller's build'");
  pin(en.updateClientLlamaLatestConfirm.endsWith(en.updateClientLlamaConfirm.slice(en.updateClientLlamaConfirm.indexOf("?") + 1)),
    "the new confirm keeps what the old one said about the background build and the old binary");
  const marks = ["?", "？", "؟"];
  const tail = (s) => { const at = Math.min(...marks.map((m) => s.indexOf(m)).filter((i) => i >= 0)); return s.slice(at + 1).trim(); };
  const tails = [], same = [];
  for (const lang of JSON.parse(process.env.LANGS)) {
    const m = (await import(`../static/js/i18n/${lang}.js`)).default;
    if (!m.updateClientLlamaLatest || !m.updateClientLlamaLatestConfirm) { tails.push(lang); continue; }
    if (m.updateClientLlamaLatest === m.updateClientLlama || m.updateClientLlamaLatestConfirm === m.updateClientLlamaConfirm) same.push(lang);
    if (!m.updateClientLlamaLatestConfirm.endsWith(tail(m.updateClientLlamaConfirm))) tails.push(lang);
  }
  assert.deepEqual(tails, []);
  assert.deepEqual(same, []);
  pin(true, "in every language the latest-release words exist, differ from the controller's-build ones, and keep the old confirm's last sentences");
}

for (const why of pass) console.log("  ok  " + why);
console.log(`js client-llama-update OK: ${pass.length} pins — the reading of the controller, the click, the wiring, the words`);
'''


def wiring():
    """The board's two places that touch ⇪ go through the class: the chip draws the button from it, the render binds it, and no handler of
    its own is left to say one thing and send another."""
    render = (ROOT / "static" / "js" / "topology-render.js").read_text(encoding="utf-8")
    nodes = (ROOT / "static" / "js" / "topology-nodes.js").read_text(encoding="utf-8")
    problems = []
    if len(re.findall(r'ClientLlamaUpdate\.bind\(\$\("topologyLlamaServers"\)\)', render)) != 1:
        problems.append("topology-render.js must bind the ⇪ buttons of #topologyLlamaServers through ClientLlamaUpdate.bind, once")
    if "/api/fleet/llama-update" in render or "data-update-client-llama" in render or "llamaCpp?.git" in render:
        problems.append("topology-render.js has a ⇪ handler of its own again (the route, the data attribute or the controller's commit read by hand)")
    if "ClientLlamaUpdate.of(state.llamaCpp)" not in nodes or "update.titleKey" not in nodes or "update.offered" not in nodes:
        problems.append("llamaBuildChipHtml must draw the ⇪ from ClientLlamaUpdate: offered, titleKey")
    if re.search(r't\("updateClientLlama"\)', nodes):
        problems.append("topology-nodes.js words the ⇪ by hand again (t(\"updateClientLlama\")): the title comes from the reading")
    return problems


def main():
    problems = wiring()
    if problems:
        print("js client-llama-update FAILED (wiring):")
        for line in problems:
            print("  - " + line)
        raise SystemExit(1)
    print("  ok  the render binds ⇪ through the class once, the chip words it from the class, and no handler of its own is left")
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_client_llama_update.tmp.mjs"
    probe.write_text(PROBE)
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run([node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "i18n,utils", "LANGS": json.dumps(LANGS),
                                     "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=60)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
