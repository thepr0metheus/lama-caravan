#!/usr/bin/env python3
"""Actual server-order.js: the order of the cards under Model servers, by value.

Under Model servers the board drew its machines first and its cloud providers after
them, always. Since 2026-10-04 the cards stand in one list in the operator's order,
kept on the controller. What is pinned here, on the real module with i18n and utils
stubbed: the rule that places a card (`rank`) and everything built on it — the keys a
topology carries, a reading older than the last save, the order a save shows at once
and the one it falls back to when refused; ↑ ↓ in a card's head, the page that scrolls with
the card, and the ends of the list the buttons say. There is no drag: the arrows are enough.

Run: python3 scripts/test_js_server_order.py
"""
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node
ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
import assert from "node:assert/strict";
const notices = [];
globalThis.__stubReturns = {
 "i18n.t": (k, p) => (p ? `${k}${JSON.stringify(p)}` : k),
 "utils.escapeHtml": (x) => String(x ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
 "utils.toast": (message) => notices.push(message),
};
const { ServerOrder, SERVER_ORDER } = await import("../static/js/server-order.js");

// ── the pure rules ──
assert.equal(ServerOrder.key("node", "box-a"), "node:box-a");
assert.equal(ServerOrder.key("cloud", "acct:2"), "cloud:acct:2");
assert.deepEqual(ServerOrder.KINDS, ["node", "cloud"]);
assert.deepEqual(ServerOrder.clean(["cloud:p", "node:a", "cloud:x:y"]), ["cloud:p", "node:a", "cloud:x:y"], "keys as sent, in their order");
assert.deepEqual(ServerOrder.clean(["node:a", "node:a", "cloud:b", "node:a"]), ["node:a", "cloud:b"], "a repeated key once, at its first place");
assert.deepEqual(ServerOrder.clean(["node:", "cloud:", "machine:a", "a", "", 5, null, { k: 1 }, ["node:a"], "node:ok"]), ["node:ok"], "negative: what is no key is not read");
for (const value of [undefined, null, "node:a", { serverOrder: ["node:a"] }, 7]) assert.deepEqual(ServerOrder.clean(value), [], `negative: ${JSON.stringify(value)} is no order`);
assert.equal(ServerOrder.same(["a", "b"], ["a", "b"]), true);
assert.equal(ServerOrder.same(["a", "b"], ["b", "a"]), false);
assert.equal(ServerOrder.same(["a"], ["a", "b"]), false);
const K = ["n:1", "c:1", "n:2", "c:2"];
assert.deepEqual(ServerOrder.moved(K, "c:2", "n:1", false), ["c:2", "n:1", "c:1", "n:2"], "before the target");
assert.deepEqual(ServerOrder.moved(K, "n:1", "c:2", true), ["c:1", "n:2", "c:2", "n:1"], "after the target");
assert.deepEqual(ServerOrder.moved(K, "n:1", "n:2", true), ["c:1", "n:2", "n:1", "c:2"]);
assert.deepEqual(ServerOrder.moved(K, "n:2", "c:1", false), ["n:1", "n:2", "c:1", "c:2"]);
assert.equal(ServerOrder.moved(K, "n:1", "c:1", false), null, "negative: a move that changes nothing is no move");
assert.equal(ServerOrder.moved(K, "c:1", "n:1", true), null);
assert.equal(ServerOrder.moved(K, "n:1", "n:1", true), null, "negative: onto itself");
assert.equal(ServerOrder.moved(K, "x:9", "n:1", true), null, "negative: a key the list does not have");
assert.equal(ServerOrder.moved(K, "n:1", "x:9", true), null);
assert.equal(ServerOrder.moved(K, "n:1", undefined, true), null, "negative: past either end");
assert.deepEqual(K, ["n:1", "c:1", "n:2", "c:2"], "the list given is not changed");

// ── what a topology carries, and a reading older than the last answer ──
const o = new ServerOrder({ post: async () => ({}) });
assert.deepEqual(o.held, { order: [], rev: -1 });
assert.equal(o.read({ layout: { serverOrder: ["cloud:p", "node:a"], serverOrderRev: 3 } }), true, "a new order: the screen changes");
assert.deepEqual([o.current(), o.held.rev], [["cloud:p", "node:a"], 3]);
assert.equal(o.read({ layout: { serverOrder: ["cloud:p", "node:a"], serverOrderRev: 3 } }), false, "the same order again: nothing changes");
assert.equal(o.read({ layout: { serverOrder: ["node:a"], serverOrderRev: 2 } }), false, "negative: a poll that left before the last save");
assert.deepEqual(o.current(), ["cloud:p", "node:a"], "  and its order is not taken");
assert.equal(o.read({ layout: { serverOrder: ["node:a", "cloud:p"], serverOrderRev: 3 } }), true, "as-is: the same revision with another order (a restored document) is taken");
assert.equal(o.read({ layout: { serverOrder: [], serverOrderRev: 4 } }), true, "an empty order is an order: the board's own");
assert.deepEqual(o.current(), []);
const fresh = new ServerOrder();
assert.equal(fresh.read(null), false, "no topology: no order, and nothing changed on screen");
assert.deepEqual(fresh.held, { order: [], rev: 0 });
assert.equal(new ServerOrder().read({ layout: { serverOrder: ["node:a"] } }), true, "no revision reads as 0 — a controller from before it");
assert.equal(new ServerOrder().read({ layout: { serverOrder: ["node:a"], serverOrderRev: "9" } }), true);
const shown = new ServerOrder();
shown.read({ layout: { serverOrder: ["node:a"], serverOrderRev: 1 } });
shown.shown = ["cloud:p", "node:a"];
assert.equal(shown.read({ layout: { serverOrder: ["node:b"], serverOrderRev: 5 } }), false, "while a save is on its way the screen keeps the order it shows");
assert.deepEqual([shown.current(), shown.held], [["cloud:p", "node:a"], { order: ["node:b"], rev: 5 }], "  though the controller's answer is taken");

// ── where a card stands ──
const r = new ServerOrder();
r.read({ layout: { serverOrder: ["cloud:p", "node:b", "cloud:gone"], serverOrderRev: 1 } });
assert.deepEqual(["cloud:p", "node:b", "cloud:gone", "node:a", "cloud:q"].map((k) => r.rank(k)), [0, 1, 2, 3, 3], "named: its index; not named: after every named one");
const present = ["node:a", "node:b", "cloud:p", "cloud:q"];   // as the lanes draw them: machines, then the cloud
assert.deepEqual(r.sorted(present, (k) => k), ["cloud:p", "node:b", "node:a", "cloud:q"], "the named ones in their order, then the rest in the lanes' order");
assert.deepEqual(new ServerOrder().sorted(present, (k) => k), present, "nothing stored: the lanes' own order — machines first, as before");
assert.deepEqual(r.sorted([{ k: "cloud:q" }, { k: "cloud:p" }], (x) => x.k).map((x) => x.k), ["cloud:p", "cloud:q"], "items are placed by the key they give");
assert.equal(r.attrs("node:b"), ' data-server-card="node:b" style="order:1"');
assert.equal(r.attrs('node:"x"'), ' data-server-card="node:&quot;x&quot;" style="order:3"', "the key is escaped");
const ctl = r.controls("node:box-a", 'Box "A"');
const named = (key) => `${key}{&quot;name&quot;:&quot;Box \\&quot;A\\&quot;&quot;}`;
assert.ok(ctl.startsWith('<span class="server-order"><button type="button" class="server-step" data-server-step="up"'), ctl);
assert.ok(ctl.includes(`<button type="button" class="server-step" data-server-step="up" data-t="server-step-up" data-t-id="node:box-a" title="${named("serverOrderUp")}" aria-label="${named("serverOrderUp")}">↑</button>`), "↑: a real button, named for a screen reader");
assert.ok(ctl.includes(`<button type="button" class="server-step" data-server-step="down" data-t="server-step-down" data-t-id="node:box-a" title="${named("serverOrderDown")}" aria-label="${named("serverOrderDown")}">↓</button>`), "↓ likewise");
assert.ok(ctl.indexOf('data-server-step="up"') < ctl.indexOf('data-server-step="down"') && ctl.endsWith("</button></span>"), "↑ then ↓, in one group");
assert.ok(!/draggable|server-grip|⠿/.test(ctl), "negative: no grip, nothing to drag — the arrows are enough (the operator, 2026-10-04)");
assert.ok(new ServerOrder().controls("node:1", undefined).includes('serverOrderUp{&quot;name&quot;:&quot;&quot;}'), "no name: an empty one, not 'undefined'");
assert.deepEqual(ServerOrder.stepped(["a", "b", "c"], "a", true), ["b", "a", "c"], "↓: one place down");
assert.deepEqual(ServerOrder.stepped(["a", "b", "c"], "c", false), ["a", "c", "b"], "↑: one place up");
assert.deepEqual([ServerOrder.stepped(["a", "b", "c"], "a", false), ServerOrder.stepped(["a", "b", "c"], "c", true), ServerOrder.stepped(["a"], "a", true), ServerOrder.stepped(["a", "b"], "x", true)], [null, null, null, null], "negative: the first up, the last down, a lone card, a card not listed — nowhere to go");

// ── a page of cards ──
function classes(initial = []) {
  const set = new Set(initial);
  return { add: (...c) => c.forEach((x) => set.add(x)), remove: (...c) => c.forEach((x) => set.delete(x)), contains: (c) => set.has(c), toString: () => [...set].join(" ") };
}
function page(keys) {
  // Where a card stands on screen: by its CSS order, then by its place in the lanes — as a flex column lays it out.
  const shownAt = (card) => [...cards].sort((x, y) => (Number(x.style.order) || 0) - (Number(y.style.order) || 0) || cards.indexOf(x) - cards.indexOf(y)).indexOf(card);
  const cards = keys.map((key, i) => {
    const card = { dataset: { serverCard: key }, style: { order: "" }, classList: classes(), top: i * 100 };
    card.getBoundingClientRect = () => ({ top: card.top, height: 80 });
    const button = (dir) => { const b = { dataset: { serverStep: dir }, disabled: false, closest: (sel) => (sel === "[data-server-step]" ? b : sel === "[data-server-card]" ? card : null), getBoundingClientRect: () => ({ top: shownAt(card) * 100 + 8, height: 20 }) }; return b; };
    card.up = button("up");
    card.down = button("down");
    card.querySelector = (sel) => (sel === '[data-server-step="up"]' ? card.up : sel === '[data-server-step="down"]' ? card.down : null);
    card.closest = (sel) => (sel === "[data-server-card]" ? card : null);
    return card;
  });
  const root = {
    dataset: {}, listeners: {}, cards,
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    querySelectorAll(sel) {
      if (sel === "[data-server-card]") return cards;
      const wanted = sel.split(",").map((s) => s.trim().replace(/^\./, ""));
      return cards.filter((c) => wanted.some((w) => c.classList.contains(w)));
    },
  };
  return { root, card: (k) => cards.find((c) => c.dataset.serverCard === k) };
}
const p = page(["node:a", "node:b", "cloud:p", "cloud:q"]);
const a = new ServerOrder();
a.read({ layout: { serverOrder: ["cloud:p", "node:b"], serverOrderRev: 1 } });
assert.equal(a.apply(p.root), true, "the cards are put in their places");
assert.deepEqual(p.root.cards.map((c) => c.style.order), ["2", "1", "0", "2"]);
assert.equal(a.apply(p.root), false, "negative: in their places already — nothing moved, nothing to redraw");
assert.deepEqual(a.onScreen(p.root), ["cloud:p", "node:b", "node:a", "cloud:q"]);
assert.equal(new ServerOrder().apply(null), false, "no page: nothing");
const ends = () => p.root.cards.map((c) => `${c.dataset.serverCard}:${c.up.disabled ? "-" : "↑"}${c.down.disabled ? "-" : "↓"}`);
assert.deepEqual(ends(), ["node:a:↑↓", "node:b:↑↓", "cloud:p:-↓", "cloud:q:↑-"], "the first card on screen has no ↑, the last no ↓; the rest have both");
a.read({ layout: { serverOrder: ["cloud:q", "node:a", "node:b", "cloud:p"], serverOrderRev: 2 } });
a.apply(p.root);
assert.deepEqual(ends(), ["node:a:↑↓", "node:b:↑↓", "cloud:p:↑-", "cloud:q:-↓"], "a new order moves the ends with it — a card that was last gets its ↓ back");

// ── a save: shown at once, sent, and what the controller answers is kept ──
{
  const posts = [], redraws = [];
  let release;
  const s = new ServerOrder({ post: (order) => { posts.push(order); return new Promise((ok) => { release = ok; }); }, redraw: () => redraws.push(1) });
  s.read({ layout: { serverOrder: [], serverOrderRev: 4 } });
  const q = page(["node:a", "cloud:p"]);
  const realDocument = globalThis.document;
  globalThis.document = q.root;   // apply() defaults to the document
  try {
    const done = s.save(["cloud:p", "node:a"]);
    assert.deepEqual(s.current(), ["cloud:p", "node:a"], "on screen before the controller answers");
    assert.deepEqual(q.root.cards.map((c) => c.style.order), ["1", "0"]);
    assert.equal(redraws.length, 1, "the cards moved: the cables follow");
    assert.deepEqual(posts, [["cloud:p", "node:a"]]);
    s.save(["node:a", "cloud:p"]);
    s.save(["cloud:p", "node:a"]);
    assert.equal(posts.length, 1, "a save on its way: the next ones wait for it");
    release({ ok: true, order: ["cloud:p", "node:a"], rev: 5 });
    await new Promise((ok) => setImmediate(ok));
    assert.deepEqual(posts, [["cloud:p", "node:a"], ["cloud:p", "node:a"]], "then only the newest is sent — the one in between was never the operator's last word");
    release({ ok: true, order: ["cloud:p", "node:a"], rev: 6 });
    await done;
    assert.deepEqual([s.held, s.shown, s.busy], [{ order: ["cloud:p", "node:a"], rev: 6 }, null, false], "the controller's answer is what the page holds now");
    assert.equal(s.read({ layout: { serverOrder: [], serverOrderRev: 4 } }), false, "negative: a poll that left before the save does not put the old order back");
    assert.deepEqual(s.current(), ["cloud:p", "node:a"]);
  } finally {
    globalThis.document = realDocument;
  }
}
{
  const s = new ServerOrder({ post: async () => { throw new Error("read-only account"); } });
  s.read({ layout: { serverOrder: ["node:a", "cloud:p"], serverOrderRev: 2 } });
  const q = page(["node:a", "cloud:p"]);
  const realDocument = globalThis.document;
  globalThis.document = q.root;
  try {
    const done = s.save(["cloud:p", "node:a"]);
    assert.deepEqual(q.root.cards.map((c) => c.style.order), ["1", "0"], "shown at once");
    await done;
    assert.equal(notices.at(-1), "read-only account", "refused: the operator is told why");
    assert.deepEqual([s.current(), s.shown, s.busy], [["node:a", "cloud:p"], null, false], "and the cards go back to what the controller holds");
    assert.deepEqual(q.root.cards.map((c) => c.style.order), ["0", "1"]);
    let sent = 0;
    s.post = () => { sent += 1; throw new Error("no network"); };   // a post that throws before it is a promise
    await s.save(["cloud:p", "node:a"]);
    s.post = async (order) => { sent += 1; return { order, rev: 3 }; };
    await s.save(["cloud:p", "node:a"]);
    assert.deepEqual([sent, s.held], [2, { order: ["cloud:p", "node:a"], rev: 3 }], "a refusal does not leave the page unable to save again");
    // a refusal whose toast fails too: every way out still releases the page and shows what the controller holds
    s.post = async () => { throw new Error("refused"); };
    const told = globalThis.__stubReturns["utils.toast"];
    globalThis.__stubReturns["utils.toast"] = () => { throw new Error("no toast"); };
    let escaped = "";
    try { await s.save(["node:a", "cloud:p"]); } catch (err) { escaped = err.message; } finally { globalThis.__stubReturns["utils.toast"] = told; }
    assert.deepEqual([escaped, s.busy, s.shown, s.current()], ["no toast", false, null, ["cloud:p", "node:a"]], "not busy, nothing shown ahead, the controller's order back");
  } finally {
    globalThis.document = realDocument;
  }
}

// ── ↑ ↓ in a card's head ──
{
  const q = page(["node:a", "node:b", "cloud:p"]);
  const saves = [], scrolled = [];
  const k = new ServerOrder({ scroll: (dy) => scrolled.push(dy) });
  k.read({ layout: { serverOrder: ["cloud:p"], serverOrderRev: 1 } });   // on screen: cloud:p, node:a, node:b
  k.apply(q.root);
  k.post = async (order) => { saves.push(order); return { order, rev: 9 }; };
  const realDocument = globalThis.document;
  globalThis.document = q.root;
  const click = (button) => ({ target: button, currentTarget: q.root, stopped: 0, stopPropagation() { this.stopped += 1; } });
  try {
    let answer;
    k.post = (order) => { saves.push(order); return new Promise((ok) => { answer = () => ok({ order, rev: 9 }); }); };
    const down = click(q.card("cloud:p").down);
    const stepping = k.step(down);
    assert.deepEqual(scrolled, [100], "the page scrolls with the card at once, not when the controller answers — the card would be seen to jump away first");
    answer();
    assert.equal(await stepping, true);
    k.post = async (order) => { saves.push(order); return { order, rev: 9 }; };
    assert.deepEqual([saves.at(-1), down.stopped], [["node:a", "cloud:p", "node:b"], 1], "↓: one place down; the click goes no further — the head under it opens and folds nothing");
    assert.deepEqual(scrolled, [100], "the page scrolls with the card: its ↓ stays under the pointer for the next click");
    await k.step(click(q.card("cloud:p").down));
    assert.deepEqual([saves.at(-1), scrolled], [["node:a", "node:b", "cloud:p"], [100, 100]], "and again: a few clicks walk a card down the list");
    assert.deepEqual([q.card("cloud:p").down.disabled, q.card("node:a").up.disabled], [true, true], "now last: its ↓ has nowhere to go; the first card's ↑ neither");
    await k.step(click(q.card("cloud:p").down));
    assert.equal(saves.length, 2, "negative: ↓ at the end — nothing moves, nothing is sent");
    await k.step(click(q.card("node:b").up));
    assert.deepEqual([saves.at(-1), scrolled.at(-1)], [["node:b", "node:a", "cloud:p"], -100], "↑: one place up, the page scrolls up with it");
    const elsewhere = { target: { closest: () => null }, currentTarget: q.root, stopped: 0, stopPropagation() { this.stopped += 1; } };
    assert.equal(await k.step(elsewhere), false, "negative: a click outside ↑ ↓ is not ours");
    assert.equal(elsewhere.stopped, 0, "  and goes on to whatever it was for");
    const stay = new ServerOrder({ scroll: (dy) => scrolled.push(dy) });
    stay.post = async (order) => ({ order, rev: 1 });
    const one = page(["node:a"]);
    globalThis.document = one.root;
    const count = scrolled.length;
    assert.equal(await stay.step({ target: one.card("node:a").down, currentTarget: one.root, stopPropagation() {} }), true);
    assert.equal(scrolled.length, count, "negative: nothing moved — the page does not scroll");
  } finally {
    globalThis.document = realDocument;
  }
}

// ── listening once ──
{
  const q = page(["node:a"]);
  const b = new ServerOrder();
  b.bind(q.root);
  b.bind(q.root);
  assert.deepEqual(Object.fromEntries(Object.entries(q.root.listeners).map(([t, l]) => [t, l.length])), { click: 1 }, "bound once, however often asked: a click on ↑ ↓ — no drag");
  b.bind(null);
  assert.ok(SERVER_ORDER instanceof ServerOrder, "the page's one order");
}
console.log("server order UI OK: rank, keys, stale readings, save and refusal, ↑ ↓ buttons and the ends");
'''
node = find_node()
if not node:
    raise SystemExit('node required')
probe = ROOT / 'scripts' / '.probe_server_order.tmp.mjs'
probe.write_text(PROBE)
try:
    harness = ROOT / 'scripts' / '_js_harness.mjs'
    result = subprocess.run([node, '--import', f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
                            env={**os.environ, 'JS_ROOT': str(ROOT/'static/js'), 'JS_STUBS': 'i18n,utils'}, capture_output=True, text=True, timeout=20)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
finally:
    probe.unlink(missing_ok=True)
raise SystemExit(result.returncode)
