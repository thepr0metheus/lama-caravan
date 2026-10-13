#!/usr/bin/env python3
"""Actual pools.js and pool-step-dialog.js: a pool's card with its steps, the step window.

A pool is what an agent's cable goes to (the operator, 2026-10-10): an ordered chain of steps,
each one account with ONE model. The card draws the ladder, says which step serves and why the
others wait — on the proxy's word, or that the proxy is silent — and writes the pool whole
(POST /api/pools/save) with only what the pool keeps. Deleting a pool asks where its cables go;
a step leaves by its own ✕; a pool has no port of its own (1.3.487). The step window
chooses an account — or connects a new one and comes back with it — and ONE of its models, from
a list that is said to be unread rather than drawn as empty.

The modules are loaded FOR REAL; i18n and utils are stubbed: a key stands for its words, and
every write is recorded.

Run: python3 scripts/test_js_pools.py
"""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
import assert from "node:assert/strict";
const calls = [], applied = [], notices = [];
let reply = async (path) => ({ topology: { saved: path } });
globalThis.__stubReturns = {
  // A key stands for its words, with its values after it: "poolCreated(name=Fast)".
  "i18n.t": (k, p) => (p ? `${k}(${Object.entries(p).map(([a, b]) => `${a}=${b}`).join(",")})` : k),
  "utils.escapeHtml": (x) => String(x ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
  "utils.api": async (path, options) => { calls.push([path, options ? JSON.parse(options.body) : null]); return reply(path, options); },
  "utils.toast": (message) => notices.push(message),
  "utils.copyText": async () => true,
};
const { PoolCards } = await import("../static/js/pools.js");
const { PoolStepDialog } = await import("../static/js/pool-step-dialog.js");

const sub = { id: "sub", name: "Sub <A>", accountType: "openai-subscription", subscription: true, hasCredential: true, oauthEmail: "a@example.test" };
const key = { id: "or", name: "Router", type: "openrouter", hasCredential: true, keyLast4: "ab12" };
const bare = { id: "bare", name: "Bare", type: "custom", hasCredential: false };
const alias = { ...sub, id: "sub-test", name: "Sub test", testAliasOf: "sub" };
const step = (id, accountId, model, extra = {}) => ({ id, accountId, model, enabled: true, switchAt: {}, ...extra });
const POOL = () => ({ id: "work", name: "Work", contextAuto: true,
  switchMax: 90, steps: [step("sub", "sub", "gpt-6", { switchAt: { "18000": 10 }, usageAccountId: "sub", switchReached: null, readAt: 5 }),
    step("or", "or", "deepseek-v4", { unlisted: true })] });
const cardsWith = (over = {}, data = {}) => {
  const c = new PoolCards({ apply: (top) => applied.push(top), ...over });
  c.set({ pools: [POOL()], accounts: [sub, key, bare, alias], runtime: { available: true, pools: {}, events: [] }, ...data });
  return c;
};
const count = (html, re) => (html.match(re) || []).length;

// ── the card ──
{
  const cards = cardsWith({}, { runtime: { available: true, pools: { work: { selectedStepId: "sub", decidedAt: 0,
    steps: [{ stepId: "sub", reason: "ready" }, { stepId: "or", reason: "quota" }] } }, events: [] } });
  cards.limits = (pool, s, owner) => `<bars pool="${pool.id}" step="${s.id}" owner="${owner}"></bars>`;
  cards.icon = (a) => `<i icon="${a.id}"></i>`;
  cards.price = (m) => (m === "gpt-6" ? "$1 · $3" : "");
  const html = cards.html();
  assert.ok(html.includes('data-topology-cloud-input="1" data-pool-id="work"'), "the cable lands on the pool's card");
  assert.ok(html.includes('data-pool-card="work"') && html.includes('data-t="pool-card"'));
  // The operator, 2026-10-11: the folded view is not needed — the card is always open.
  const article = html.slice(html.indexOf("<article"), html.indexOf(">", html.indexOf("<article")) + 1);
  assert.ok(!article.includes("data-t-state") && !html.includes("data-pool-card-fold") && !html.includes("pool-brief") && html.includes("pool-ladder"),
    "always open: no fold switch, no folded list, the steps drawn");
  // ... and each step carries its number inside it: no column of numbered circles beside the cards.
  assert.ok(/<div class="pool-step-head">\s*<span class="pool-rank" aria-hidden="true">1<\/span>/.test(html)
    && /<div class="pool-step-head">\s*<span class="pool-rank" aria-hidden="true">2<\/span>/.test(html), "the step's number leads its own head");
  // The foot: "+ Add step" across the card, then one bar with the parts' switches.
  assert.ok(html.includes('class="ghost-action pool-add-step"') && /class="pool-bar">\s*<div class="pool-parts">/.test(html)
    && /<div class="pool-parts"><button class="pool-part-head" type="button" data-pool-part="work:settings" aria-expanded="false">/.test(html),
    "the foot: the add button, then the bar with the settings switch");
  assert.ok(!html.includes('data-pool-part="work:history"'), "negative: no switches yet — no history switch");
  assert.ok(html.includes("Sub &lt;A>") && !html.includes("Sub <A>"), "names are escaped");
  assert.ok(html.includes("<code title=\"gpt-6\">gpt-6</code>") && html.includes("deepseek-v4"), "each step names its model");
  assert.equal(count(html, /data-pool-step="(sub|or)"/g), 2);
  assert.ok(html.includes('<bars pool="work" step="sub" owner="sub">'), "a subscription step draws its limit bars with the step's own levels");
  assert.ok(!html.includes('<bars pool="work" step="or"'), "negative: a key account's step has no subscription bars");
  assert.ok(html.includes('data-t-state="serving"') && html.includes("poolServing"), "the step the proxy chose serves");
  assert.ok(html.includes('class="pool-status reserve"') && html.includes("poolQuota"), "a step resting for its limit says so");
  assert.ok(html.includes('pool-step-unlisted'), "a model the provider no longer lists is marked");
  assert.ok(html.includes("$1 · $3"), "the model's price stands on its line");
  assert.ok(html.includes("poolLast: <strong>Sub &lt;A> · gpt-6</strong>"), "the last request names the step: account · model");
  // The operator, 2026-10-11: a pool always goes by the order set — nothing on the card picks a step by hand.
  assert.ok(!html.includes("data-pool-mode=") && !html.includes("pool-modes") && !html.includes("data-pool-field=\"manualDuration\""),
    "no mode switch and no 'until' in the head");
  assert.ok(!html.includes("data-pool-use=") && !html.includes('data-step-field="automatic"'),
    "no 'Use this step' and no 'Automatic selection' under a step");
  assert.equal(count(html, /data-step-field="enabled"/g), 2, "each step keeps its Enabled switch: off takes it out of the order");
  assert.equal(count(html, /<span class="pool-grip" data-pool-grip tabindex="0" role="button" /g), 2,
    "a step is carried by its grip, which the keyboard reaches too (Alt+↑/↓)");
  assert.ok(!html.includes("draggable="), "negative: no drag of the browser's own — step-carry.js carries the step");
  assert.ok(!html.includes("pool-port") && !html.includes("data-pool-port-") && html.includes('data-pool-add-step="work"'),
    "negative: a pool has no port of its own any more (the owner, 2026-10-12) — no row, no ⧉, ✕ or ＋ port");
  assert.ok(!html.includes("data-pool-delete="), "a pool with steps is deleted from its settings, shut by default");
}
// a subscription nobody signed into: no limits are asked for, and the step says why it waits
{
  const cards = cardsWith();
  const asked = [];
  cards.limits = (pool, s, owner) => { asked.push(owner); return "<bars></bars>"; };
  cards.refresh = (owner) => `<refresh ${owner}>`;
  cards.set({ pools: [{ ...POOL(), steps: [step("sub", "sub", "gpt-6")] }], accounts: [{ ...sub, hasCredential: false }], runtime: { available: true, pools: {} } });
  const html = cards.html();
  assert.deepEqual([asked, html.includes("<refresh"), html.includes("poolLoginNeeded")], [[], false, true],
    "negative: no sign-in, no reading — a read would only draw 'unavailable' under the step");
}
// the account's ⚙ is the original's for a TEST step, and the TEST mark shows
{
  const cards = cardsWith();
  cards.set({ pools: [{ ...POOL(), steps: [step("sub-test", "sub-test", "gpt-6")] }], accounts: [sub, alias], runtime: { available: false } });
  const html = cards.html();
  assert.ok(html.includes('data-pool-edit-account="sub"') && !html.includes('data-pool-edit-account="sub-test"'));
  assert.ok(html.includes(">TEST<") && html.includes("poolAliasHint"));
  assert.ok(html.includes("poolLast: <strong>poolProxySilent</strong>"), "a silent proxy is said, not drawn as 'no request'");
}
// the last request refused by the pool itself: said with its time, not drawn as "no request yet"
{
  const cards = cardsWith({}, { runtime: { available: true, pools: { work: { selectedStepId: null, decidedAt: 1000000,
    steps: [{ stepId: "sub", reason: "reserve" }, { stepId: "or", reason: "quota" }] } }, events: [] } });
  const html = cards.html();
  assert.ok(html.includes('poolLast: <strong class="pool-last-refused">poolLastRefused</strong> · '), "a refusal is the last request's fate, with its time");
  assert.ok(!html.includes("poolNoRequest"), "negative: a pool refusing every request is not 'never called'");
  cards.runtime = { available: true, pools: {}, events: [] };
  assert.ok(cards.html().includes("poolLast: <strong>poolNoRequest</strong>"), "no state for the pool: no request since the proxy started");
}
// status: the proxy's word, a sign-in missing, nothing known — and no word for a hand pick
{
  const cards = cardsWith();
  const pool = POOL();
  const st = (rows, extra = {}) => ({ selectedStepId: "", steps: rows, ...extra });
  assert.deepEqual(cards.status(pool, pool.steps[0], st([{ stepId: "sub", reason: "ready" }], { selectedStepId: "sub" })).look, "serving");
  assert.deepEqual(cards.status(pool, pool.steps[0], st([{ stepId: "sub", reason: "reserve" }], { selectedStepId: "sub" })).text, "poolStopReached",
    "negative: the step chosen last but now at its stop is not 'serving'");
  // Below its switch a step gives way (2026-10-11): it still serves when no step above its own switch is fit.
  const giving = cards.status(pool, pool.steps[0], st([{ stepId: "sub", reason: "switch", eligible: true }], { selectedStepId: "sub" }));
  assert.deepEqual([giving.look, giving.text, giving.title], ["serving", "poolServing", "poolSwitchReached"],
    "a step giving way that serves says it serves, and why it was given way to, in its hover");
  const waiting = cards.status(pool, pool.steps[0], st([{ stepId: "sub", reason: "switch", eligible: true }], { selectedStepId: "or" }));
  assert.deepEqual([waiting.look, waiting.text], ["reserve", "poolSwitchReached"], "one giving way while another serves says so, in amber");
  assert.equal(cards.status(pool, pool.steps[0], st([{ stepId: "sub", reason: "reserve" }])).look, "stop", "a step at its stop — in the stop's red");
  // A hand pick kept from before 1.3.463 draws nothing: the proxy does not obey it. Until then a picked
  // step at its level stood green "Manual selection" while the pool refused every request.
  const kept = { ...pool, mode: "manual", manualStepId: "sub", manualUntil: 4102444800 };
  assert.equal(cards.status(kept, kept.steps[0], st([{ stepId: "sub", reason: "reserve" }])).look, "stop",
    "negative: a once-picked step at its stop is not drawn as serving");
  assert.equal(cards.status(kept, kept.steps[0], st([])).text, "poolNoRequest", "negative: nor before the proxy said a word");
  assert.equal(cards.status(pool, step("b", "bare", "m"), null).text, "cloudNoKeyYet", "a key account without its key says so before the proxy");
  assert.equal(cards.status(pool, step("s", "sub", "m"), st([])).text, "poolNoRequest");
  assert.equal(cards.status(pool, step("s", "sub", "m"), st([{ stepId: "s", reason: "mystery" }])).text, "poolUnavailable", "an unknown reason is not guessed");
  cards.runtime = { available: false };
  assert.equal(cards.status(pool, step("s", "sub", "m"), null).text, "poolProxySilent");
  const looks = Object.fromEntries(Object.entries(PoolCards.REASONS).map(([r, [k, look]]) => [r, look]));
  assert.deepEqual(Object.keys(looks).sort(), __PROXY_REASONS__,
    "every reason the proxy gives (caravan/proxy/pool_steps.py) has its words, and no word stands for a reason it never gives");
}
// what goes back to the server: only what the pool keeps
{
  const out = PoolCards.payload({ ...POOL(), mode: "manual", manualStepId: "sub", manualUntil: 5 });
  assert.deepEqual(Object.keys(out).sort(), ["contextAuto", "contextLength", "id", "name", "steps"],
    "negative: a hand pick the board still holds is not sent back");
  assert.deepEqual(Object.keys(out.steps[0]).sort(), ["accountId", "enabled", "id", "model", "stopAt", "switchAt"],
    "negative: the level reached, the reading's time and the marks stay on the board");
  assert.equal(out.contextLength, "", "no window stated is sent as blank, not as zero");
  const steps = [{ id: "a" }, { id: "b" }, { id: "c" }];
  assert.deepEqual(PoolCards.ordered(steps, ["c", "a", "b"]).map((s) => s.id), ["c", "a", "b"], "the order a carried step left behind");
  assert.equal(PoolCards.ordered(steps, ["a", "b", "c"]), null, "an order that changes nothing saves nothing");
  assert.equal(PoolCards.ordered(steps, ["a", "b"]), null, "negative: an order that leaves a step out is no order");
  assert.equal(PoolCards.ordered(steps, ["a", "a", "b"]), null, "negative: a step twice is no order");
  assert.equal(PoolCards.ordered(steps, ["a", "b", "x"]), null, "negative: a step the pool does not have");
}
// ── acting on the card ──
function event(dataset, { type = "click", stepId = "sub", poolId = "work", value = "", checked = false, input = false } = {}) {
  const e = { dataset, disabled: false, value, checked, type: input ? "checkbox" : "button",
    matches: (selector) => input ? selector === "input, select" : selector === "button",
    hasAttribute: (attribute) => Object.hasOwn(dataset, attribute.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())),
    closest: (selector) => selector === "[data-pool-id]" ? { dataset: { poolId } } : selector === "[data-pool-step]" ? { dataset: { poolStep: stepId } } : e };
  return { type, target: e, stopPropagation() {} };
}
{
  const cards = cardsWith();
  const saved = () => calls.at(-1)[1].pool;
  const before = calls.length;
  for (const gone of [{ poolUse: "or" }, { poolMode: "manual" }, { poolField: "manualDuration" }, { stepField: "automatic" }]) {
    await cards.handle(event(gone, gone.poolField || gone.stepField ? { type: "change", input: true, value: "3600" } : {}));
  }
  assert.equal(calls.length, before, "negative: the controls of the hand pick, should an old page send them, save nothing");
  await cards.handle(event({ stepField: "enabled" }, { type: "change", input: true, stepId: "or", checked: false }));
  assert.deepEqual([calls.at(-1)[0], saved().steps[1].enabled], ["/api/pools/save", false]);
  assert.equal(cards.pools[0].steps[1].enabled, true, "the board's copy is not edited in place");
  await cards.handle(event({ poolMove: "-1" }, { stepId: "or" }));
  assert.deepEqual(saved().steps.map((s) => s.id), ["or", "sub"]);
  const n = calls.length;
  await cards.handle(event({ poolMove: "-1" }, { stepId: "sub" }));
  assert.equal(calls.length, n, "the first step has no step above it");
  await cards.handle(event({ poolField: "name" }, { type: "change", input: true, value: "  Work  " }));
  assert.equal(calls.length, n, "an unchanged name saves nothing");
  await cards.handle(event({ poolField: "name" }, { type: "change", input: true, value: "Night" }));
  assert.equal(saved().name, "Night");
  await cards.handle(event({ poolField: "contextLength" }, { type: "change", input: true, value: " " }));
  assert.equal(saved().contextLength, "", "a cleared window is sent blank: the server drops it");
  await cards.handle(event({ poolField: "contextAuto" }, { type: "change", input: true, checked: false }));
  assert.equal(saved().contextAuto, false);
  const m = calls.length;
  await cards.handle(event({ stepField: "enabled" }, { input: true }));
  assert.equal(calls.length, m, "a click on a checkbox does not save its old value");
  reply = async () => { throw new Error("save failed"); };
  const failed = event({ poolMove: "1" }, { stepId: "sub" });
  await cards.handle(failed);
  assert.equal(failed.target.disabled, false);
  assert.equal(notices.at(-1), "save failed");
  reply = async (path) => ({ topology: { saved: path } });
  assert.deepEqual(applied.at(-1), { saved: "/api/pools/save" }, "the board is drawn from the controller's answer");
}
// the window doors: "+ Add step", "+ New pool", ⚙ — and no write
{
  const opened = [], edited = [];
  const cards = cardsWith({ addStep: (id) => opened.push(id), editAccount: (id) => edited.push(id) });
  const n = calls.length;
  await cards.handle(event({ poolAddStep: "work" }));
  await cards.handle(event({ poolNew: "" }));
  await cards.handle(event({ poolEditAccount: "or" }));
  assert.deepEqual([opened, edited, calls.length], [["work", ""], ["or"], n]);
}
// folding: a step opens in place; the card itself does not fold
{
  let redraws = 0;
  const cards = new PoolCards({});
  cards.set({ pools: [POOL()], accounts: [sub, key], runtime: { available: true, pools: {}, events: [] } });
  const n = calls.length;
  await cards.handle(event({ poolCardFold: "" }), () => { redraws += 1; });
  assert.deepEqual([redraws, calls.length, cards.html().includes("pool-ladder")], [0, n, true],
    "negative: the card's old fold switch, should a stale page send it, folds nothing and saves nothing");
  const stepEl = { dataset: { poolStep: "or" }, classes: new Set(), classList: { toggle(c, on) { on ? stepEl.classes.add(c) : stepEl.classes.delete(c); } },
    querySelector: () => ({ attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }) };
  const button = { closest: (sel) => (sel === "[data-pool-step]" ? stepEl : { dataset: { poolId: "work" } }) };
  cards.foldStep(button);
  assert.ok(cards.open.has("work/or") && stepEl.classes.has("open"), "a step opens in place and is remembered by pool and step");
  cards.foldStep(button);
  assert.ok(!cards.open.has("work/or") && !stepEl.classes.has("open"));
}
// the pool's parts that open under its foot: settings (the window, the deletion) and the history
{
  const cards = cardsWith({}, { runtime: { available: true, pools: {}, events: [
    { poolId: "work", from: "sub", to: "or", at: 10, mode: "manual", reasons: [{ stepId: "sub", reason: "reserve" }] },
    { poolId: "other", from: "x", to: "y", at: 11, reasons: [] }] } });
  let html = cards.html();
  assert.ok(html.includes('data-pool-part="work:settings"') && html.includes('data-pool-part="work:history"'));
  assert.ok(!html.includes('data-t="pool-settings"') && !html.includes('class="pool-event"'), "both shut until opened");
  await cards.handle(event({ poolPart: "work:settings" }), () => {});
  await cards.handle(event({ poolPart: "work:history" }), () => {});
  html = cards.html();
  assert.ok(html.includes('data-pool-field="contextLength"') && html.includes('data-pool-delete="work"'));
  assert.equal(count(html, /class="pool-event"/g), 1, "only this pool's switches");
  assert.ok(html.includes("Sub &lt;A> · gpt-6 → Router · deepseek-v4") && html.includes("<small>Sub &lt;A> · gpt-6: reserve</small>"),
    "a switch says its steps and reasons — not the mode an older proxy wrote beside them");
}
// an empty pool, no pool at all, and the accounts no step uses
{
  const cards = cardsWith();
  cards.set({ pools: [{ ...POOL(), steps: [] }], accounts: [sub, key, alias], runtime: { available: true } });
  let html = cards.html();
  assert.ok(html.includes('data-t="pool-empty"') && html.includes('data-pool-add-step="work"') && html.includes('data-pool-delete="work"'));
  assert.ok(!html.includes("data-pool-mode=") && !html.includes("pool-last"), "nothing to choose between: no modes, no last request");
  assert.ok(html.includes('data-t="pool-loose"') && html.includes('data-t-id="sub"') && html.includes('data-t-id="or"'),
    "accounts no step uses are listed, never left out of sight");
  assert.ok(!html.includes('data-t-id="sub-test"'), "negative: a legacy alias is not an account of its own");
  cards.set({ pools: [], accounts: [], runtime: {} });
  html = cards.html();
  assert.ok(html.includes('data-t="pool-none"') && html.includes("data-pool-new") && !html.includes("pool-loose"));
  cards.set({ pools: [POOL()], accounts: [sub, key], runtime: {} });
  assert.ok(!cards.html().includes("pool-loose"), "every account in a step: no strip");
}
// deleting a pool: the controller says what leads to it; with nothing, a plain question
{
  const asked = [];
  const cards = cardsWith({ confirm: async (msg, opts) => { asked.push([msg, opts.title]); return true; } });
  cards.set({ pools: [POOL(), { ...POOL(), id: "night", name: "Night" }], accounts: [sub, key], runtime: {} });
  reply = async (path) => path.startsWith("/api/pools/refs")
    ? { held: { cables: 0, rules: [] }, refs: {} } : { deleted: "work", topology: { t: 1 } };
  calls.length = 0;
  await cards.remove("work");
  assert.deepEqual(calls.map((c) => c[0]), ["/api/pools/refs?id=work", "/api/pools/delete"]);
  assert.deepEqual(calls[1][1], { id: "work" }, "nothing held: no resolution is sent");
  assert.equal(asked[0][0], "poolDeleteText(name=Work)", "the plain question: no ports to name — a pool has none");
  assert.equal(notices.at(-1), 'poolDeleted(name=Work)');
  assert.ok(!asked[0][0].includes("poolDeleteClients"), "negative: no client calls it — not a word about clients");
  // the clients of the entry that call it by name lose it with it: the window names them first (2026-10-11)
  reply = async (path) => path.startsWith("/api/pools/refs")
    ? { held: { cables: 0, rules: [] }, refs: {}, clients: ["Hermes", "Bot"] } : { deleted: "work", topology: { t: 1 } };
  asked.length = 0;
  await cards.remove("work");
  assert.ok(asked[0][0].startsWith('poolDeleteText(name=Work) poolDeleteClients(names=Hermes, Bot)'),
    "the clients that lose it are named in the question, before anything is deleted");
  // held: where do the cables go — onto another pool, or disconnected
  const offered = [];
  cards.choose = async (msg, opts) => { offered.push([msg, opts.choices]); return "night"; };
  reply = async (path) => path.startsWith("/api/pools/refs")
    ? { held: { cables: 2, rules: ["default"] }, refs: {}, clients: ["Hermes"] } : { deleted: "work", moved: 3, onto: "night", topology: { t: 2 } };
  calls.length = 0;
  await cards.remove("work");
  assert.deepEqual(offered[0][1], [{ value: "night", label: "Night" }, { value: PoolCards.CUT, label: "portCloseCut" }]);
  assert.ok(offered[0][0].includes("portCloseDefault"), "a router's default among them is said");
  assert.ok(offered[0][0].includes("poolDeleteClients(names=Hermes)"), "the clients are named when the kanban holds it too");
  assert.deepEqual(calls[1][1], { id: "work", resolution: { moveTo: "night" } });
  assert.equal(notices.at(-1), 'poolDeletedMoved(name=Work,onto=Night,n=3)');
  cards.choose = async () => PoolCards.CUT;
  reply = async (path) => path.startsWith("/api/pools/refs") ? { held: { cables: 1, rules: [] } } : { cut: 1, topology: {} };
  calls.length = 0;
  await cards.remove("work");
  assert.deepEqual(calls[1][1], { id: "work", resolution: { cut: true } });
  cards.choose = async () => null;
  calls.length = 0;
  assert.equal(await cards.remove("work"), null);
  assert.deepEqual(calls.map((c) => c[0]), ["/api/pools/refs?id=work"], "negative: cancelled — nothing is deleted");
  reply = async () => ({ refs: {} });
  calls.length = 0;
  assert.equal(await cards.remove("work"), null);
  assert.equal(notices.at(-1), "poolDeleteUnknown", "the controller could not say what leads to it: the pool stays");
  reply = async () => { throw new Error("refs down"); };
  assert.equal(await cards.remove("work"), null);
  assert.equal(notices.at(-1), "refs down");
  reply = async (path) => ({ topology: { saved: path } });
}
// a step leaves by its ✕; the card opens and closes no port (the owner, 2026-10-12)
{
  let ok = false;
  const cards = cardsWith({ confirm: async () => ok });
  calls.length = 0;
  assert.equal(await cards.removeStep("work", "or"), null);
  assert.equal(calls.length, 0, "cancelled: the step stays");
  ok = true;
  await cards.removeStep("work", "or");
  assert.deepEqual(calls.at(-1), ["/api/pools/remove-step", { poolId: "work", stepId: "or" }]);
  assert.equal(await cards.removeStep("work", "ghost"), null, "a step the pool does not have asks nothing");
  assert.ok(cards.openPort === undefined && cards.closePort === undefined && PoolCards.address === undefined,
    "negative: no port is opened, closed or addressed from a pool's card — every client comes in through the entry");
  reply = async (path) => ({ topology: { saved: path } });
}
// a carried step's order is saved (step-carry.js carries it); the lane waits while the carrier is busy
{
  const cards = cardsWith();
  assert.equal(cards.inFlight(), false, "no carrier yet: nothing in flight");
  cards.carry = { busy: true };
  assert.equal(cards.inFlight(), true, "a step carried, landing or being saved holds the lane");
  cards.carry.busy = false;
  assert.equal(cards.inFlight(), false);
  calls.length = 0;
  const saved = await cards.sort("work", ["or", "sub"]);
  assert.deepEqual([calls.at(-1)[0], calls.at(-1)[1].pool.steps.map((s) => s.id)], ["/api/pools/save", ["or", "sub"]]);
  assert.deepEqual(saved, { topology: { saved: "/api/pools/save" } }, "the save's answer is what sort answers (1.3.503)");
  const n = calls.length;
  assert.equal(await cards.sort("work", ["sub", "or"]), null);
  assert.equal(await cards.sort("work", ["sub"]), null);
  assert.equal(await cards.sort("nope", ["or", "sub"]), null);
  assert.equal(calls.length, n, "negative: the same order, a partial one or another pool's saves nothing — and answers null");
  const was = reply;
  reply = async () => { throw new Error("pool changed"); };
  const before = notices.length;
  assert.equal(await cards.sort("work", ["or", "sub"]), null, "negative: a refused save answers null — the board draws the kept order");
  assert.equal(notices.at(-1), "pool changed", "and the toast says why");
  assert.equal(notices.length, before + 1);
  reply = was;
}

// ── the step window ──
const catalogue = { models: [{ id: "gpt-6", chat: true, contextLength: 400000 }, { id: "gpt-6-mini", chat: true }, { id: "tts-2", chat: false }], fetchedAt: 100 };
const dialog = (over = {}) => {
  const renders = [];
  const d = new PoolStepDialog({ apply: (top) => applied.push(top), render: () => renders.push(1), price: (m) => (m === "gpt-6" ? "$1 · $3" : ""), ...over });
  d.set({ accounts: [{ ...sub, modelsCheckedAt: 50 }, { ...key }, bare, alias], pools: [POOL()] });
  return [d, renders];
};
{
  const [d] = dialog();
  assert.equal(d.html(), "", "closed: nothing drawn");
  d.open("work");
  let html = d.html();
  assert.ok(html.includes('poolStepTitle(pool=Work)') && html.includes('data-t-state="account"'));
  assert.equal(count(html, /data-pool-step-account="/g), 3, "every account but a legacy alias");
  assert.ok(html.includes('data-pool-step-connect') && html.includes(" disabled>poolAddStep<"), "nothing chosen: the step cannot be added");
  assert.ok(html.includes("a@example.test") && html.includes('cloudKeyShort(last4=ab12)') && html.includes("cloudNoKeyYet"),
    "each account says how it signs in, or that it does not");
  d.open("");
  assert.ok(d.html().includes("poolNewTitle") && d.html().includes(" disabled>poolCreate<"));
}
// choosing an account reads its list — fetched from the provider first when never read
{
  const [d] = dialog();
  reply = async (path) => (path.startsWith("/api/cloud-accounts/catalogue") ? catalogue : { total: 3 });
  calls.length = 0;
  d.open("work");
  d.pick("or");
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(calls.map((c) => c[0]), ["/api/cloud-accounts/check-models", "/api/cloud-accounts/catalogue?id=or"],
    "a list the controller never fetched is fetched, then read");
  calls.length = 0;
  d.pick("sub");
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(calls.map((c) => c[0]), ["/api/cloud-accounts/catalogue?id=sub"], "a list checked before is only read");
  const html = d.html();
  assert.ok(html.includes('data-t-state="model"') && html.includes('data-pool-step-model="gpt-6"') && html.includes("🪟 400K"));
  assert.ok(html.indexOf("gpt-6-mini") < html.indexOf("poolStepNotChat") && html.indexOf("poolStepNotChat") < html.indexOf("tts-2"),
    "chat models first, the rest under their own line");
  assert.ok(html.includes("$1 · $3") && html.includes("poolStepChecked"));
  calls.length = 0;
  d.pick("bare");
  assert.equal(calls.length, 0, "an account without a sign-in is not asked for a list");
  assert.ok(d.html().includes("poolStepUnsigned") && d.html().includes("data-pool-step-custom"), "it says why, and a model can still be typed");
  assert.ok(!d.html().includes("data-pool-step-query") && !d.html().includes("data-pool-step-check"), "negative: no list to search or check — neither is drawn");
  reply = async () => { throw new Error("provider down"); };
  d.pick("or");
  await new Promise((r) => setImmediate(r));
  assert.ok(d.html().includes('poolStepListFailed(error=provider down)'), "a refused read is said, not drawn as 'no models'");
  reply = async (path) => ({ topology: { saved: path } });
}
// the list: search, the limit on rows, nothing found
{
  const [d] = dialog();
  d.open("work");
  d.form.accountId = "or";
  d.catalogues.set("or", { models: Array.from({ length: PoolStepDialog.ROWS + 5 }, (_, i) => ({ id: `m-${i}`, chat: true })), fetchedAt: 1 });
  const account = d.account("or");
  assert.equal(count(d.rowsHtml(account), /data-pool-step-model=/g), PoolStepDialog.ROWS);
  assert.ok(d.rowsHtml(account).includes('poolStepMore(n=5)'));
  d.form.query = "M-12";
  assert.deepEqual([...d.rowsHtml(account).matchAll(/data-pool-step-model="([^"]+)"/g)].map((x) => x[1]), ["m-12", "m-120", "m-121", "m-122", "m-123", "m-124"],
    "the search ignores case");
  d.form.query = "zzz";
  assert.ok(d.rowsHtml(account).includes("poolStepNoMatch"));
  d.catalogues.set("or", { models: [], fetchedAt: null });
  d.form.query = "";
  assert.equal(d.rowsHtml(account), "", "an unread list draws no rows; the line above it says why");
  assert.ok(d.html().includes("poolStepNeverChecked"));
}
// adding the step, making the pool
{
  const [d] = dialog();
  d.open("work");
  calls.length = 0;
  assert.equal(await d.submit(), null);
  assert.equal(notices.at(-1), "poolStepNeedsAccount");
  d.form.accountId = "or";
  assert.equal(await d.submit(), null);
  assert.equal(notices.at(-1), "poolStepNeedsModel");
  assert.equal(calls.length, 0, "negative: nothing is sent without an account and a model");
  d.form.model = "deepseek-v4";
  d.form.custom = "  my-model  ";
  assert.equal(d.chosenModel(), "my-model", "a typed id is the operator's last word");
  reply = async () => ({ pool: { id: "work" }, topology: { t: 5 } });
  await d.submit();
  assert.deepEqual(calls.at(-1), ["/api/pools/add-step", { poolId: "work", accountId: "or", model: "my-model" }]);
  assert.equal(notices.at(-1), 'poolStepAdded(step=Router · my-model,pool=Work)');
  assert.equal(d.form, null, "the window closes on success");
  assert.deepEqual(applied.at(-1), { t: 5 });
  d.open("");
  d.form.accountId = "sub";
  d.form.model = "gpt-6";
  d.form.name = " Fast ";
  reply = async () => ({ pool: { id: "Fast", name: "Fast" }, topology: { t: 6 } });
  await d.submit();
  assert.deepEqual(calls.at(-1), ["/api/pools/create", { name: "Fast", accountId: "sub", model: "gpt-6" }]);
  assert.equal(notices.at(-1), 'poolCreated(name=Fast)');
  d.open("work");
  d.form.accountId = "sub";
  d.form.model = "gpt-6";
  reply = async () => { throw new Error("unknown account"); };
  await d.submit();
  assert.deepEqual([notices.at(-1), d.form.busy, d.form.accountId], ["unknown account", false, "sub"], "a refusal keeps the window and what was chosen");
  reply = async (path) => ({ topology: { saved: path } });
}
// connecting a new account from the window: it steps aside, and comes back with the account
{
  let after = null;
  const [d] = dialog({ connect: (fn) => { after = fn; } });
  d.open("work");
  d.connectNew();
  assert.equal(d.html(), "", "the window steps aside while the account window is open");
  d.set({ accounts: [...d.accounts, { id: "new", name: "New", hasCredential: false }], pools: d.pools });
  after("new");
  assert.deepEqual([d.form.away, d.form.accountId], [false, "new"], "back with the new account chosen");
  d.connectNew();
  after(null);
  assert.deepEqual([d.form.away, d.form.accountId], [false, "new"], "no account made: back as it was");
  d.connectNew();
  after("ghost");
  assert.equal(d.form.accountId, "new", "an id the board does not know chooses nothing");
}
// the window's clicks and typing
{
  const [d] = dialog();
  const node = (attrs, extra = {}) => ({ dataset: {}, closest: (sel) => (sel.split(", ").some((s) => attrs[s]) ? attrs[sel.split(", ").find((s) => attrs[s])] : null), matches: (sel) => !!attrs[sel], ...extra });
  d.open("work");
  d.form.accountId = "sub";
  d.catalogues.set("sub", catalogue);
  d.click({ target: node({ "[data-pool-step-model]": { dataset: { poolStepModel: "gpt-6-mini" } } }) });
  assert.deepEqual([d.form.model, d.form.custom], ["gpt-6-mini", ""]);
  const box = { innerHTML: "" };
  const submit = { disabled: false };
  const root = { querySelector: (sel) => (sel === "[data-pool-step-models]" ? box : sel === "[data-pool-step-submit]" ? submit : null) };
  d.typed({ target: node({ "[data-pool-step-query]": true }, { value: "mini" }) }, root);
  assert.ok(box.innerHTML.includes("gpt-6-mini") && !box.innerHTML.includes('"gpt-6"'), "the search redraws the rows in place");
  d.typed({ target: node({ "[data-pool-step-custom]": true }, { value: "x" }) }, root);
  assert.equal(submit.disabled, false);
  d.form.model = "";
  d.typed({ target: node({ "[data-pool-step-custom]": true }, { value: "" }) }, root);
  assert.equal(submit.disabled, true, "nothing chosen and nothing typed: the step cannot be added");
  d.click({ target: node({ "[data-pool-step-close]": true }) });
  assert.equal(d.form, null, "× closes");
  d.open("");
  const overlay = { dataset: { poolStepOverlay: "" } };
  overlay.closest = (sel) => (sel === "[data-pool-step-overlay]" ? overlay : null);
  d.click({ target: overlay });
  assert.equal(d.form, null, "a click on the backdrop closes");
  d.open("");
  const inside = { dataset: {}, closest: (sel) => (sel === "[data-pool-step-overlay]" ? overlay : null) };
  d.click({ target: inside });
  assert.notEqual(d.form, null, "negative: a click inside the window does not close it");
}
console.log("pools UI OK: the card and its steps, statuses on the proxy's word, writes of what the pool keeps, a step's fold on an always-open card, the foot's bar and parts, the empty pool and none, accounts in no pool, deletion with its cables, a step's removal, no own ports, the order a carried step leaves; the step window: accounts, lists read or said unread, search, add and create, connecting a new account");
'''


def css_rules():
    """What the card's look rests on in modals.css — the parts a value test of the markup cannot see.

    The operator, 2026-10-11: a step shows its limit bars only while the pointer is on it, a control
    in it has focus, or it is opened — the step that serves as well — and the pool's name and its last
    request stand on one line. A rule lost from the CSS would bring the old card back unnoticed."""
    css = (ROOT / "static" / "css" / "modals.css").read_text(encoding="utf-8")
    wanted = {
        ".pool-step:not(.open):not(:hover):not(:focus-within) > .sub-usage-panel { display: none; }":
            "every step's bars, the serving one's too, are hidden until hover, focus or opening",
        ".pool-ident { flex: 1 1 240px; min-width: 0; display: flex; flex-wrap: wrap; align-items: baseline;":
            "the pool's name and its last request share one line",
    }
    missing = [why for rule, why in wanted.items() if rule not in css]
    for why in wanted.values():
        print(("  ok  " if why not in missing else " FAIL ") + why)
    return not missing


def proxy_reasons():
    """The reasons the proxy gives a row, read from its own source: each `"reason": "<word>"` it
    writes and the words its REASON table gives a provider's status. The board's table of words
    (PoolCards.REASONS) is pinned against this list, so a reason added to the proxy without words
    — or words kept for a reason the proxy no longer gives — turns this snapshot red."""
    src = (ROOT / "caravan" / "proxy" / "pool_steps.py").read_text(encoding="utf-8")
    words = set(re.findall(r'"reason": "([a-z_]+)"', src))
    table = re.search(r"REASON = \{([^}]*)\}", src)
    words |= set(re.findall(r'"([a-z_]+)"', table.group(1) if table else ""))
    return sorted(words)


def main():
    node = find_node()
    if not node:
        raise SystemExit("node required")
    if not css_rules():
        raise SystemExit("pools UI FAILED: the card's CSS lost a rule it rests on")
    reasons = proxy_reasons()
    if len(reasons) < 10:
        raise SystemExit(f"pools UI FAILED: the proxy's reasons could not be read from pool_steps.py ({reasons})")
    probe = ROOT / "scripts" / ".probe_pools.tmp.mjs"
    probe.write_text(PROBE.replace("__PROXY_REASONS__", json.dumps(reasons)))
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run([node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "i18n,utils,dialogs"}, capture_output=True, text=True, timeout=30)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
