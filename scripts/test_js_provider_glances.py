#!/usr/bin/env python3
"""Actual provider-glances.js: the cloud providers on the main board, and where the kanban's pools lead.

The owner, 2026-10-12: the main board's third column holds the machines and, under them, the cloud
providers — each a block of its accounts, added there and never with its models (the kanban has
them). The kanban's card is cabled to the machines and accounts its pools lead to: PoolReach says
which — an account a row calls, a machine one of whose cells a row calls — by value, with the
negatives a cable must not be drawn for. ProviderGlances draws each provider the controller puts on
the board: its name, its accounts as rows — whether each can serve, a subscription's windows (no ⟳)
and the small ↺ of its saved resets, an API key's spend, a fault — its «＋» and, while empty, its ✕;
the «＋»s, ✕, ↺ and ⚙ are delegated from the column, and a reading that lands draws the blocks again.

The module is loaded FOR REAL; i18n, utils, cloud.js, usage-stats.js and topology-nodes.js are
stubbed: a key stands for its words, and a reading's HTML for its arguments. The saved resets are a
stand-in passed to the class.

Run: python3 scripts/test_js_provider_glances.py
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
import assert from "node:assert/strict";
const landed = new Set();
globalThis.__stubValues = { "usage-stats.READING_LANDED": landed,
  "cloud.CLOUD_PICKER_META": { "openai-subscription": { color: "#22c55e" }, openrouter: { color: "#a78bfa" } } };
globalThis.__stubReturns = {
  "i18n.t": (k) => k,
  "utils.escapeHtml": (x) => String(x ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
  "cloud.cloudPickerTileIcon": (kind) => `<svg kind="${kind}"></svg>`,
  "cloud.cloudProviderName": (kind) => `name:${kind}`,
  "cloud.cloudApiIssuesHtml": (a) => (a.id === "bad" ? "<tripped/>" : ""),
  "usage-stats.subscriptionUsageHtml": (owner, opts) => `<bars owner="${owner}" refresh="${opts?.refresh}"></bars>`,
  "usage-stats.proxySpendHtml": (id, opts) => `<spend id="${id}" zero="${opts?.zero}"></spend>`,
};
const { PoolReach, ProviderGlances } = await import("../static/js/provider-glances.js");
const st = await import("../static/js/state.js");
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };

// ── where the kanban's pools lead ──
{
  const top = {
    routers: [
      { outputs: [{ id: "srv:22008", upstreamHost: "10.0.0.5", upstreamType: "llama" }, { id: "eng:o1", upstreamHost: "10.0.0.6" },
        { id: "cb:x", upstreamType: "cloud", upstreamHost: "" }] },
      { outputs: [{ id: "srv:22008", upstreamHost: "9.9.9.9" }] },
    ],
    pools: [
      { steps: [{ kind: "account", accountId: "sub" }, { kind: "output", output: "srv:22008" },
        { kind: "account", accountId: "key", enabled: false }, { kind: "open" }] },
      { steps: [{ kind: "account", accountId: "sub" }, { kind: "output", output: "eng:o1" }, { kind: "output", output: "srv:gone" },
        { kind: "output", output: "cb:x" }, { kind: "output", output: "srv:22008" }] },
    ],
  };
  const machineOf = (address) => ({ "10.0.0.5": "box-a", "10.0.0.6": "box-b" })[address] || address;
  const reach = PoolReach.of(top, machineOf);
  assert.deepEqual(reach, { accounts: ["sub"], machines: [{ key: "box-a", outputs: ["srv:22008"] }, { key: "box-b", outputs: ["eng:o1"] }] });
  pin(true, "an account a row calls, once however many rows call it; a machine one of whose cells a row calls, with its outputs, once each");
  pin(!reach.accounts.includes("key"), "negative: a row switched off leads nowhere — no cable says a request can go there");
  pin(reach.machines.every((m) => m.key !== "9.9.9.9"), "the first router that has the output says where it answers: one place, not a guess per router");
  pin(!JSON.stringify(reach).includes("srv:gone") && !JSON.stringify(reach).includes("cb:x"),
    "negative: an output gone from every router, and a pool's own cloud output, lead to no machine");
  assert.deepEqual(PoolReach.of({}, machineOf), { accounts: [], machines: [] });
  assert.deepEqual(PoolReach.of(undefined, machineOf), { accounts: [], machines: [] });
  pin(true, "boundary: no pools, no topology — nothing reached, not a failure");
}

// ── the providers' blocks ──
const sub = { id: "sub", name: "Sub <A>", accountType: "openai-subscription", subscription: true, hasCredential: true };
const alias = { id: "sub-test", name: "Sub test", subscription: true, hasCredential: true, testAliasOf: "sub" };
const key = { id: "or", name: "Router", type: "openrouter", hasCredential: true };
const noKey = { id: "bare", name: "Bare", type: "custom", hasCredential: false };
const noLogin = { id: "sub2", name: "Sub 2", subscription: true, hasCredential: false };
const bad = { id: "bad", name: "Bad", type: "openai", hasCredential: true };
const TOP = () => ({ cloudAccounts: [sub, alias, key, noKey, noLogin, bad], boardProviders: [
  { kind: "openai-subscription", accounts: ["sub", "sub-test", "sub2"] }, { kind: "openrouter", accounts: ["or"] },
  { kind: "custom", accounts: ["bare"] }, { kind: "openai", accounts: ["bad"] }, { kind: "anthropic", accounts: [] },
  { kind: "ollama", accounts: ["gone"] }] });
const make = () => {
  const reads = [], spends = [], edits = [], adds = [], connects = [], removes = [], chosen = [];
  const resets = { reads: [], read(a) { this.reads.push(a.id); }, chipHtml: (a) => `<chip ${a.testAliasOf || a.id}>`, choose: (a) => chosen.push(a.id) };
  const glances = new ProviderGlances({ readUsage: (o) => reads.push(o), readSpend: () => spends.push(1), edit: (id) => edits.push(id),
    add: () => adds.push(1), connect: (k) => connects.push(k), remove: (k) => removes.push(k), resets, landed });
  return { glances, reads, spends, edits, adds, connects, removes, chosen, resets };
};
const group = (html, kind) => {
  const at = html.indexOf(`data-provider-group="${kind}"`);
  assert.ok(at >= 0, `group ${kind}`);
  return html.slice(at, html.indexOf("</section>", at));
};
const row = (html, id) => {
  const at = html.indexOf(`data-board-provider="${id}"`);
  assert.ok(at >= 0, `row ${id}`);
  const next = html.indexOf('data-board-provider="', at + 10);
  const end = html.indexOf("</section>", at);
  return html.slice(at, next > 0 && next < end ? next : end);
};
{
  const { glances } = make();
  const none = glances.html({ cloudAccounts: [sub], boardProviders: [] });
  pin(none.includes('data-t="provider-none"') && none.includes("boardProvidersNone") && !none.includes("provider-group"),
    "no provider on the board: the line that says so and what ＋ does — not an empty column (an account with no provider is the controller's to place)");
}
{
  const { glances, reads, spends, resets } = make();
  const html = glances.html(TOP());
  pin(JSON.stringify([...html.matchAll(/data-provider-group="([^"]+)"/g)].map((m) => m[1]))
      === JSON.stringify(["openai-subscription", "openrouter", "custom", "openai", "anthropic", "ollama"]),
    "a block per provider, in the order the controller gives");
  const subs = group(html, "openai-subscription");
  pin(subs.includes("<strong>providerGroupSubscriptions</strong>") && subs.includes('<svg kind="openai-subscription"></svg>')
      && subs.includes("--provider-accent:#22c55e") && subs.includes('<span class="provider-group-count">3</span>')
      && JSON.stringify([...subs.matchAll(/data-board-provider="([^"]+)"/g)].map((m) => m[1])) === JSON.stringify(["sub", "sub-test", "sub2"]),
    "the subscriptions' block: its name, its sign in its colour, how many, its accounts as rows in the controller's order");
  pin(subs.includes('data-provider-group-add="openai-subscription"') && subs.includes("＋ providerAddSubscription") && !subs.includes("data-provider-remove"),
    "its «＋ subscription» at the foot; negative: a block with accounts has no ✕ — they go first");
  const s = row(html, "sub");
  pin(s.includes('<bars owner="sub" refresh="false"></bars>') && s.includes("<chip sub>") && s.includes("cloudConnected")
      && s.includes('data-t-state="ready"') && s.includes('data-provider-edit="sub"') && s.includes("Sub &lt;A>") && !s.includes("Sub <A>"),
    "a signed-in subscription's row: its windows as last read, no ⟳; the small ↺ of its saved resets; connected; ⚙; its name escaped");
  pin(!s.includes("<spend") && !/gpt|model/i.test(s), "negative: no spend line and no model on a subscription's row — its models are the kanban's");
  const a = row(html, "sub-test");
  pin(a.includes('<bars owner="sub"') && a.includes("<chip sub>") && a.includes('data-provider-edit="sub"'),
    "a test alias reads its original's windows and resets, and ⚙ opens the original's window");
  const n = row(html, "sub2");
  pin(n.includes("poolLoginNeeded") && n.includes('data-t-state="waiting"') && !n.includes("<bars") && !n.includes("<chip"),
    "a subscription nobody signed into: sign-in needed; negative: no windows and no resets asked for");
  const k = row(html, "or");
  pin(k.includes('<spend id="or" zero="true"></spend>') && !k.includes("<bars") && !k.includes("<chip")
      && group(html, "openrouter").includes("＋ providerAddKey") && group(html, "openrouter").includes("<strong>name:openrouter</strong>")
      && !group(html, "openrouter").includes("provider-group-count"),
    "an API key's row: its spend through the caravan, said as zero once read; its block «＋ API key»; negative: no bars, no resets, "
    + "and a block of one account counts nothing — a count says more than one");
  pin(row(html, "bare").includes("cloudNoKeyYet") && !row(html, "bare").includes("<spend") && group(html, "custom").includes("＋ providerAddEndpoint")
      && group(html, "custom").includes("--provider-accent:#94a3b8"),
    "a key not entered yet: said so, nothing read for it; the custom block adds an address, in the plain colour of a provider with none");
  pin(row(html, "bad").includes('<div class="provider-issues"><tripped/></div>') && !s.includes("provider-issues"),
    "a tripped endpoint is said on its row; negative: a healthy one has no fault line");
  const empty = group(html, "anthropic");
  pin(empty.includes("providerEmpty") && empty.includes('data-provider-remove="anthropic"') && empty.includes("＋ providerAddKey")
      && !empty.includes("provider-group-count") && !empty.includes("data-board-provider"),
    "an empty provider: said empty, its ✕ to take it off and its «＋»; negative: no count, no row");
  pin(!group(html, "ollama").includes("data-board-provider") && group(html, "ollama").includes("providerEmpty"),
    "boundary: an id the accounts lack (one deleted between the two readings) draws no row");
  assert.deepEqual([reads, spends.length, resets.reads], [["sub", "sub"], 2, ["sub", "sub-test"]]);
  pin(true, "the windows are read for each signed-in subscription (the alias by its original), the resets for each, the spend once per API key with its key (two here)");
}

// ── the column: the "＋"s, ✕, ↺ and ⚙ delegated; a reading draws the blocks again ──
{
  const { glances, edits, adds, connects, removes, chosen } = make();
  const column = { dataset: {}, listeners: {}, addEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || 0) + 1; this.fn = fn; } };
  const container = { innerHTML: "", isConnected: true, parentElement: column };
  let after = 0;
  glances.mount(container, TOP(), { after: () => { after += 1; } });
  glances.mount(container, TOP(), { after: () => { after += 1; } });
  pin(container.innerHTML.includes('data-provider-group="openai-subscription"'), "mounted: the blocks stand in the column's container");
  pin(column.listeners.click === 1 && landed.size === 1, "the column's listener and the reading's callback are bound once, however often it is drawn");
  const el = (attr, value) => ({ hasAttribute: (n) => n === attr, dataset: { [attr.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())]: value } });
  const click = (target) => column.fn({ target: { closest: () => target }, stopPropagation() {} });
  click(el("data-provider-add", ""));
  click(el("data-provider-group-add", "openai-subscription"));
  click(el("data-provider-remove", "anthropic"));
  click(el("data-pool-resets", "sub"));
  click(el("data-provider-edit", "sub"));
  column.fn({ target: { closest: () => null }, stopPropagation() {} });
  assert.deepEqual([adds.length, connects, removes, chosen, edits], [1, ["openai-subscription"], ["anthropic"], ["sub"], ["sub"]]);
  pin(true, "«＋ Add cloud provider» opens the picker, a block's «＋» connects an account of it, ✕ takes an empty one off, ↺ opens the account's resets, ⚙ its window; negative: a click elsewhere does nothing");
  st.setTopology({ cloudAccounts: [sub, key], boardProviders: [{ kind: "openrouter", accounts: ["or"] }] });
  [...landed][0]();
  pin(container.innerHTML.includes('data-board-provider="or"') && !container.innerHTML.includes('data-board-provider="sub"') && after === 1,
    "a reading that lands draws the blocks the board holds now, then what follows them (the cables, whose ends moved)");
  container.isConnected = false;
  [...landed][0]();
  pin(after === 1, "negative: a column no longer in the page is not drawn into, and nothing follows");
  pin(new ProviderGlances({ landed: new Set(), resets: {} }).redraw() === false, "boundary: nothing mounted — nothing drawn, said as false");
}
for (const why of pass) console.log("  ok  " + why);
console.log(`js provider-glances OK: ${pass.length} pins — where the kanban's pools lead, each provider a block of its accounts, its ＋ and ✕, a reading draws again`);
'''


def main():
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_provider_glances.tmp.mjs"
    probe.write_text(PROBE)
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run([node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"),
                                     "JS_STUBS": "i18n,utils,dialogs,cloud,usage-stats,topology-nodes"},
                                capture_output=True, text=True, timeout=30)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
