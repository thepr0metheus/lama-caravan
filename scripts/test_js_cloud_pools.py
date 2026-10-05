#!/usr/bin/env python3
"""Actual cloud-pools.js: render real identities, the priority ladder, and exercise policy writes."""
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node
ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
import assert from "node:assert/strict";
const calls = [], applied = [], notices = [];
globalThis.__stubReturns = {
 "i18n.t": (k) => k,
 "utils.escapeHtml": (x) => String(x ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
 "utils.api": async (path, options) => { calls.push([path, JSON.parse(options.body)]); return { topology: { saved: true }, account: { id: "a-test" } }; },
 "utils.toast": (message) => notices.push(message),
};
const { SubscriptionPoolCards } = await import("../static/js/cloud-pools.js");
const a = { id: "a", name: "Owner <A>", accountType: "openai-subscription", oauthEmail: "owner@example.test" };
const alias = { ...a, id: "a-test", name: "Test", testAliasOf: "a" };
const source = { id: "p", name: "Work", isPool: true, pool: { id: "p", name: "Work", mode: "auto", members: [{ accountId: "a", enabled: true, automatic: true }, { accountId: "a-test", enabled: true, automatic: true }] } };
const cards = new SubscriptionPoolCards({ accounts: [a, alias, source], runtime: { available: true, pools: { p: { selectedAccountId: "a-test", members: [{ accountId: "a", reason: "disabled" }, { accountId: "a-test", reason: "ready" }] } } }, limits: (id) => `<quota owner="${id}"></quota>`, apply: (top) => applied.push(top) });
const html = cards.controls(source);
assert.ok(html.includes('data-pool-id="p"') && html.includes('data-pool-use="a-test"'));
assert.ok(html.includes("TEST") && html.includes("poolAliasHint"));
assert.equal((html.match(/quota owner="a"/g) || []).length, 2);
assert.ok(html.includes("Owner &lt;A>") && !html.includes("Owner <A>"));
assert.ok(html.includes('data-cloud-edit-account="a"') && !html.includes('data-cloud-edit-account="a-test"'));
assert.ok(cards.controls(a).includes('data-pool-create="a"'));
assert.ok(!html.includes('data-pool-alias=') && !cards.controls(a).includes('data-pool-alias='));
assert.ok(cards.controls(alias).includes("poolAliasHint") && !cards.controls(alias).includes('data-pool-alias="a-test"'));
function event(dataset, { type = "click", member = "a-test", value = "", checked = false, input = false } = {}) {
 const e = { dataset, disabled: false, value, checked, type: input ? "checkbox" : "button", matches: (selector) => input ? selector === "input, select" : selector === "button", hasAttribute: (attribute) => Object.hasOwn(dataset, attribute.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())),
 closest: (selector) => selector === "[data-pool-id]" ? { dataset: { poolId: "p" } } : selector === "[data-pool-member]" ? { dataset: { poolMember: member } } : e };
 return { type, target: e, stopPropagation() {} };
}
await cards.handle(event({ poolUse: "a-test" }));
assert.equal(calls.at(-1)[1].pool.mode, "manual");
assert.equal(calls.at(-1)[1].pool.manualAccountId, "a-test");
assert.equal(source.pool.mode, "auto");
await cards.handle(event({ memberField: "enabled" }, { type: "change", input: true, member: "a", checked: false }));
assert.equal(calls.at(-1)[1].pool.members[0].enabled, false);
await cards.handle(event({ poolMove: "-1" }));
assert.equal(calls.at(-1)[1].pool.members[0].accountId, "a-test");
await cards.handle(event({ poolCreate: "a" }));
assert.equal(calls.at(-1)[1].adoptAccountId, "a");
await cards.handle(event({ poolRemove: "" }));
assert.deepEqual(calls.at(-1)[1].pool.members.map((m) => m.accountId), ["a"]);
const before = calls.length;
await cards.handle(event({ memberField: "enabled" }, { input: true }));
assert.equal(calls.length, before); // clicking a checkbox does not save its old value
const failed = event({ poolUse: "a" });
globalThis.__stubReturns["utils.api"] = async () => { throw new Error("save failed"); };
await cards.handle(failed);
assert.equal(failed.target.disabled, false);
assert.equal(notices.at(-1), "save failed");
const connected = [];
cards.connect = (id) => connected.push(id);
const writesBeforeConnect = calls.length;
await cards.handle(event({ poolConnect: "p" }));
assert.deepEqual(connected, ["p"]);
assert.equal(calls.length, writesBeforeConnect);
assert.ok(cards.controls(source).includes('data-pool-connect="p"'));
const second = { ...a, id: "second", name: "Second", hasCredential: true };
const realSource = { ...source, pool: { ...source.pool, members: [{ accountId: "a", enabled: true, automatic: true }, { accountId: "second", enabled: true, automatic: true }] } };
const realCards = new SubscriptionPoolCards({ accounts: [a, second, realSource], limits: (id) => `<quota owner="${id}"></quota>` });
const realHtml = realCards.controls(realSource);
assert.ok(realHtml.includes('data-cloud-edit-account="a"') && realHtml.includes('data-cloud-edit-account="second"'));
assert.ok(!realHtml.includes('TEST') && !realHtml.includes('poolAliasHint'));
assert.ok(realHtml.includes('data-pool-connect="p"'));

// ── the ladder: members in priority order, one rung each ──
// The error-recovery check above left the write failing; the ladder checks write again.
globalThis.__stubReturns["utils.api"] = async (path, options) => { calls.push([path, JSON.parse(options.body)]); return { topology: { saved: true }, account: { id: "a-test" } }; };
const T = (html, re) => (html.match(re) || []).length;
const poolOf = (members, extra = {}) => ({ id: "p", name: "Work", isPool: true, pool: { id: "p", name: "Work", mode: "auto", members, ...extra } });
const acct = (id, extra = {}) => ({ id, name: id.toUpperCase(), accountType: "openai-subscription", oauthEmail: `${id}@example.test`, ...extra });
const trio = [acct("x"), acct("y"), acct("z")];
const members3 = ["x", "y", "z"].map((accountId) => ({ accountId, enabled: true, automatic: true }));
const runtimeOf = (selected, rows) => ({ available: true, pools: { p: { selectedAccountId: selected, members: rows.map(([accountId, reason]) => ({ accountId, reason })) } } });
const ladder = (opts, source) => new SubscriptionPoolCards({ accounts: [...trio, source], ...opts }).controls(source);
const pills = (html) => [...html.matchAll(/class="pool-status ([a-z]+)" title="[^"]*">([^<]*)</g)].map((m) => [m[1], m[2]]);
{
  const src = poolOf(members3, { returnToPrimary: true });
  const html = ladder({}, src);
  assert.equal(T(html, /<li class="pool-rung">/g), 3);
  assert.deepEqual([...html.matchAll(/class="pool-rank" aria-hidden="true">(\d)</g)].map((m) => m[1]), ["1", "2", "3"]);
  assert.equal(T(html, /class="pool-link"/g), 2, "a connector between the rungs, not after the last");
  assert.equal(T(ladder({}, poolOf([members3[0]])), /class="pool-link"/g), 0, "one rung: nothing to fall through to");
  assert.ok(html.includes('<ol class="pool-ladder">') && html.includes("poolFallsThrough"));
  assert.ok(html.includes('data-pool-field="returnToPrimary" checked') && html.includes("poolReturn"));
  assert.ok(!ladder({}, poolOf(members3, { returnToPrimary: false })).includes('data-pool-field="returnToPrimary" checked'));
  assert.ok(/class="pool-mode on" aria-checked="true" data-pool-mode="auto"/.test(html) && /class="pool-mode" aria-checked="false" data-pool-mode="manual"/.test(html));
  assert.ok(/class="pool-mode on" aria-checked="true" data-pool-mode="manual"/.test(ladder({}, poolOf(members3, { mode: "manual", manualAccountId: "x" }))));
  assert.ok(html.includes('draggable="true" data-pool-grip') && T(html, /data-pool-grip/g) === 3);
}
// the status pill: what the proxy says, serving only on its word
{
  const src = poolOf(members3);
  const serving = ladder({ runtime: runtimeOf("y", [["x", "reserve"], ["y", "ready"], ["z", "ready"]]) }, src);
  assert.deepEqual(pills(serving), [["reserve", "poolReserve"], ["serving", "poolServing"], ["ready", "poolReady"]]);
  assert.equal(T(serving, /class="pool-step serving"/g), 1);
  const spent = ladder({ runtime: runtimeOf("x", [["x", "reserve"], ["y", "ready"], ["z", "weird"]]) }, src);
  assert.deepEqual(pills(spent), [["reserve", "poolReserve"], ["ready", "poolReady"], ["unknown", "poolUnavailable"]], "chosen but spent: the reason, not 'serving'; an unknown reason is 'unavailable', not a guess");
  assert.equal(T(spent, /pool-step serving/g), 0);
  const rows = ladder({ runtime: runtimeOf("", [["x", "disabled"], ["y", "manual_only"], ["z", "quota"]]) }, src);
  assert.deepEqual(pills(rows), [["off", "poolDisabled"], ["off", "poolManualOnly"], ["reserve", "poolReserve"]]);
  assert.deepEqual(pills(ladder({}, src)), [["unknown", "poolUnknown"], ["unknown", "poolUnknown"], ["unknown", "poolUnknown"]], "no runtime: not measured, not ready");
  const login = ladder({ runtime: runtimeOf("x", [["x", "ready"], ["y", "ready"], ["z", "ready"]]) }, poolOf([{ ...members3[0], pendingLogin: true }, members3[1], members3[2]]));
  assert.deepEqual(pills(login)[0], ["login", "poolLoginNeeded"], "a member that has not signed in says so, whatever the proxy last said");
  const manual = ladder({}, poolOf(members3, { mode: "manual", manualAccountId: "z" }));
  assert.deepEqual(pills(manual), [["unknown", "poolUnknown"], ["unknown", "poolUnknown"], ["serving", "poolManual"]], "picked by hand: it says so before the proxy has answered");
  assert.equal(T(manual, /data-pool-use=/g), 5, "in manual mode the rungs not picked carry a Use button in their head, besides the one under it");
  assert.equal(T(ladder({}, src), /data-pool-use=/g), 3);
  assert.ok(/class="ghost-action selected" type="button" data-pool-use="z"/.test(manual));
}
// the head says numbers, loud only when a reset is uncertain; the rest waits under the fold
{
  const src = poolOf(members3);
  const summary = (owner, id) => ({ x: { resets: 3, cost: "$809" }, y: { resets: null }, z: { pending: true, resets: 1 } })[id];
  const html = ladder({ summary, limits: (id) => `<quota owner="${id}"></quota>`, resets: (id) => `<resets owner="${id}"></resets>`, spend: (id) => `<spend id="${id}"></spend>` }, src);
  assert.equal(T(html, /↺ \d/g), 2, "an unread balance is not '0 resets'");
  assert.ok(html.includes("↺ 3") && html.includes("≈ $809") && html.includes("↺ 1") && !html.includes("≈ $0"));
  assert.equal(T(html, /class="pool-warn"/g), 1);
  assert.equal(T(html, /↺/g), 2, "an unread balance writes nothing — not '↺ null'");
  assert.equal(T(html, /≈/g), 1, "no cost, no '≈' — a rung that cost nothing says nothing");
  const bare = new SubscriptionPoolCards({ accounts: [] });
  assert.equal(bare.meta({ resets: null, pending: false, cost: "" }), "", "nothing read, nothing written");
  assert.equal(bare.meta({}), "");
  assert.ok(bare.meta({ resets: 0, cost: "" }).includes("↺ 0") && !bare.meta({ resets: 0, cost: "" }).includes("≈"), "a measured zero is a zero");
  assert.ok(bare.meta({ resets: null, cost: "$5" }).includes("≈ $5") && !bare.meta({ resets: null, cost: "$5" }).includes("↺"));
  assert.ok(html.includes('class="pool-step open" data-pool-member="z"') && html.includes('class="pool-step" data-pool-member="x"'), "an uncertain reset opens its rung; the others start shut");
  const more = html.indexOf('class="pool-step-more"');
  for (const id of ["x", "y", "z"]) {
    const at = html.indexOf(`data-pool-member="${id}"`), next = html.indexOf('data-pool-member="', at + 5);
    const part = html.slice(at, next < 0 ? undefined : next), fold = part.indexOf('class="pool-step-more"');
    assert.ok(part.indexOf(`<quota owner="${id}">`) < fold, "the bars sit above the fold");
    assert.ok(part.indexOf(`<resets owner="${id}">`) > fold && part.indexOf(`<spend id="${id}">`) > part.indexOf(`<resets owner="${id}">`), "resets and spend under it");
  }
  const kept = new SubscriptionPoolCards({ accounts: [...trio, src] });
  kept.open.add("y");
  const keptHtml = kept.controls(src);
  assert.ok(keptHtml.includes('class="pool-step open" data-pool-member="y"') && keptHtml.includes('aria-expanded="true"'));
  assert.ok(ladder({}, poolOf([...members3, { accountId: "gone", enabled: true, automatic: true }])).includes('class="pool-step missing" data-pool-member="gone"'));
  assert.ok(ladder({}, poolOf([...members3, { accountId: "gone", enabled: true, automatic: true }])).includes("gone · poolUnavailable"));
}
// the top of the card: the icon, the name as the title itself, the last decision, the mode — no form above the ladder
{
  const ICON = '<span class="cloud-account-icon">ICON</span>';
  const withIcon = (src, icon, opts = {}) => new SubscriptionPoolCards({ accounts: [...trio, src], ...opts }).controls(src, icon);
  const topOf = (html) => html.slice(html.indexOf('<header class="pool-top">'), html.indexOf("</header>"));
  const named = (name, extra = {}) => poolOf(members3, { name, ...extra });
  const top = topOf(withIcon(named("Work <1>"), ICON));
  assert.ok(top.startsWith('<header class="pool-top">'), "the card draws its own top");
  assert.ok(top.indexOf("ICON") > 0 && top.indexOf("ICON") < top.indexOf('data-pool-field="name"'), "the lane's icon leads the title");
  assert.ok(!topOf(ladder({}, named("Work"))).includes("ICON") && ladder({}, named("Work")).includes('<header class="pool-top">'), "no icon given: none drawn");
  assert.ok(top.includes('<input class="pool-name-input" data-pool-field="name" value="Work &lt;1>"'), "the name is the title, an input that reads as text; its text is escaped");
  assert.ok(top.indexOf('data-pool-field="name"') < top.indexOf('class="pool-last"') && top.indexOf('class="pool-last"') < top.indexOf('class="pool-modes"'), "name, then the last decision under it, then the mode at the right");
  assert.equal(top.replaceAll(/(aria-label|title)="poolName"/g, "").includes("poolName"), false, "'Pool name' is no visible label any more — only the name for a screen reader and a tooltip");
  assert.ok(top.includes('class="pool-name-pen" aria-hidden="true"'));
  assert.ok(/class="pool-name-input"[^\n]* aria-label="poolName"/.test(top), "the field that looks like text still has a name for a screen reader");
  const size = (name) => Number((topOf(withIcon(named(name), "")).match(/class="pool-name-input"[^>]* size="(\d+)"/) || [])[1]);
  assert.equal(size("W"), 8, "a short name still gets a field to click");
  assert.equal(size("OpenAI — подписки"), 18, "one more than the letters of the name");
  assert.equal(size("😀".repeat(10)), 11, "letters, not UTF-16 halves");
  assert.equal(T(top, /pool-until/g), 0, "auto mode: no 'until'");
  const manualTop = topOf(withIcon(named("Work", { mode: "manual", manualAccountId: "x" }), ""));
  assert.ok(manualTop.indexOf('class="pool-until"') > 0 && manualTop.indexOf('class="pool-until"') < manualTop.indexOf('class="pool-modes"'), "manual mode: the 'until' list stands beside the switch, before it");
  assert.equal(T(manualTop, /data-pool-field="manualDuration"/g), 1);
}
// a rung's head: the grip, who it is, what it says and does — and the refresh button is HERE, not among the bars
{
  const rungHtml = (id, opts = {}, src = poolOf(members3)) => {
    const html = ladder({ refresh: (owner) => `<refresh owner="${owner}"></refresh>`, limits: (owner) => `<quota owner="${owner}"></quota>`, ...opts }, src);
    const at = html.indexOf(`data-pool-member="${id}"`), next = html.indexOf('data-pool-member="', at + 5);
    return html.slice(at, next < 0 ? undefined : next);
  };
  const part = rungHtml("y");
  const order = ['class="pool-step-head"', "data-pool-grip", 'class="pool-step-id"', 'class="pool-step-name"', 'class="pool-status', 'class="pool-step-mail"', 'class="pool-step-tools"', 'class="pool-step-meta"', "<refresh owner=", "data-pool-fold", "<quota owner=", 'class="pool-step-more"'].map((m) => part.indexOf(m));
  assert.ok(order.every((at) => at > 0) && order.every((at, i) => i === 0 || at > order[i - 1]), "head: grip, identity (name, state, mailbox), tools (numbers, refresh, fold); then the bars; then what is folded");
  assert.equal(T(part, /<refresh owner="y"/g), 1);
  assert.ok(part.indexOf("<refresh owner=") < part.indexOf('class="pool-step-more"'), "the refresh button is not under the fold");
  assert.ok(part.includes('class="pool-step-name" title="Y"') && part.includes('class="pool-step-mail" title="y@example.test"'), "a name or a mailbox the lane cuts short says itself in a tooltip");
  const alias = { id: "y-test", name: "Y test", accountType: "openai-subscription", oauthEmail: "y@example.test", testAliasOf: "y" };
  const members = [...members3, { accountId: "y-test", enabled: true, automatic: true }];
  const aliasHtml = new SubscriptionPoolCards({ accounts: [...trio, alias, poolOf(members)], refresh: (owner) => `<refresh owner="${owner}"></refresh>` }).controls(poolOf(members));
  const aliasAt = aliasHtml.indexOf('data-pool-member="y-test"');
  assert.ok(aliasHtml.slice(aliasAt).includes('<refresh owner="y"></refresh>'), "a TEST member re-reads its original's limits — the bars are the original's");
  const noMail = new SubscriptionPoolCards({ accounts: [{ ...trio[0], oauthEmail: "" }, trio[1], trio[2], poolOf(members3)] }).controls(poolOf(members3));
  assert.equal(T(noMail, /class="pool-step-mail"/g), 2, "no mailbox, no empty line under the name");
  assert.equal(T(ladder({}, poolOf(members3)), /pool-step-tools/g), 3);
  assert.equal(ladder({}, poolOf(members3)).includes("<refresh"), false, "no callback, no button");
}
// the number of saved resets is a button when there is one to use — and it opens a window of choice, nothing more
{
  const bare = new SubscriptionPoolCards({ accounts: [] });
  const chip = bare.meta({ resets: 3 }, "own<er>");
  assert.ok(chip.includes('<button class="pool-resets" type="button" data-pool-resets="own&lt;er>" title="resetChoose" aria-label="resetChoose">↺ 3</button>'), "a number to press, naming whose resets it opens; the same words for the hand and for the screen reader");
  const none = bare.meta({ resets: 0 }, "o");
  assert.ok(none.includes('<span class="pool-resets none" title="resetAvailable">↺ 0</span>') && !none.includes("<button"), "no reset to use: nothing to press");
  assert.equal(bare.meta({ resets: null }, "o").includes("pool-resets"), false, "unread: no counter at all");
  const both = bare.meta({ pending: true, resets: 2 }, "o");
  assert.ok(both.indexOf("pool-warn") >= 0 && both.indexOf("pool-warn") < both.indexOf("pool-resets"), "the warning stands before the counter");
  const alias = { id: "y-test", name: "Y test", accountType: "openai-subscription", oauthEmail: "y@example.test", testAliasOf: "y" };
  const members = [...members3, { accountId: "y-test", enabled: true, automatic: true }];
  const html = new SubscriptionPoolCards({ accounts: [...trio, alias, poolOf(members)], summary: () => ({ resets: 2 }) }).controls(poolOf(members));
  assert.equal(T(html, /data-pool-resets="y"/g), 2, "a test member opens its original's resets: they are one credential's");
  assert.equal(T(html, /data-pool-resets="x"/g), 1);
  const opened = [];
  const door = new SubscriptionPoolCards({ accounts: [...trio, poolOf(members3)], chooseReset: (id) => opened.push(id) });
  let stopped = 0;
  const button = { dataset: { poolResets: "y" }, disabled: false, matches: () => false, hasAttribute: (a) => a === "data-pool-resets", closest: (selector) => (selector.includes("[data-pool-resets]") ? button : null) };
  const writes = calls.length;
  assert.equal(await door.handle({ type: "click", target: button, stopPropagation() { stopped++; } }), true);
  assert.deepEqual(opened, ["y"], "the window is opened for the owner of the resets");
  assert.equal(calls.length, writes, "opening the window saves nothing");
  assert.equal(stopped, 1);
  assert.equal(button.disabled, false, "the button is not left disabled");
  const quiet = new SubscriptionPoolCards({ accounts: [...trio, poolOf(members3)] });
  assert.equal(await quiet.handle({ type: "click", target: button, stopPropagation() {} }), true, "no window to open: the press is still taken, and harmless");
}
// under the ladder: the one policy, the way to add a rung, the history — together
{
  const events = [{ poolId: "p", at: 1000, from: "x", to: "y", mode: "auto", reasons: [{ accountId: "x", reason: "quota" }] }];
  const foot = (html) => html.slice(html.indexOf('<div class="pool-foot">'));
  // "inside": between the container's opening tag and the child, more <div>s were opened than closed — the container is still open.
  const inside = (html, container, child) => {
    const from = html.indexOf(container), to = html.indexOf(child, from);
    const seg = from < 0 || to < 0 ? "" : html.slice(from, to);
    return (seg.match(/<div\b/g) || []).length - (seg.match(/<\/div>/g) || []).length >= 1;
  };
  const bare = ladder({}, poolOf(members3));
  assert.ok(bare.indexOf("</ol>") < bare.indexOf('<div class="pool-foot">'), "the foot is under the ladder");
  const f = foot(bare);
  assert.ok(f.indexOf('data-pool-field="returnToPrimary"') > 0 && f.indexOf('data-pool-field="returnToPrimary"') < f.indexOf('class="pool-add"'), "the policy, then the way to add");
  assert.equal(T(bare, /data-pool-add/g), 0, "every subscription is a rung already: nothing to add from the list");
  assert.equal(T(bare, /<details class="pool-history">/g), 0, "no switches yet: no history");
  assert.ok(inside(bare, '<div class="pool-add">', 'data-pool-connect="p"'), "the connect button stands in the add row, not after it");
  const spare = acct("spare");
  const more = new SubscriptionPoolCards({ accounts: [...trio, spare, poolOf(members3)], runtime: { available: true, pools: {}, events } }).controls(poolOf(members3));
  const g = foot(more);
  const add = g.slice(g.indexOf('class="pool-add"'));
  assert.ok(add.indexOf("data-pool-add") > 0 && add.indexOf("data-pool-add") < add.indexOf("data-pool-connect"), "the list of what can be added, then the button for what cannot");
  assert.ok(g.indexOf('class="pool-add"') < g.indexOf('<details class="pool-history">') && g.includes("poolHistory"), "the history comes after the add row");
  assert.ok(inside(more, '<div class="pool-foot">', '<details class="pool-history">'), "and inside the foot: the foot is what closes the card");
  assert.ok(inside(more, '<div class="pool-foot">', 'data-pool-field="returnToPrimary"') && inside(more, '<div class="pool-foot">', 'data-pool-add'), "the policy and the add list are in the foot too");
  assert.ok(more.includes('aria-label="poolAdd"'), "the list has a name for a screen reader");
}
// the order, as a pure move
{
  const R = (...ids) => ids.map((accountId) => ({ accountId }));
  const names = (r) => r && r.map((m) => m.accountId).join("");
  const base = R("a", "b", "c"), move = SubscriptionPoolCards.reordered;
  assert.equal(names(move(base, "c", "a", false)), "cab");
  assert.equal(names(move(base, "a", "c", true)), "bca");
  assert.equal(names(move(base, "a", "b", true)), "bac");
  assert.equal(names(move(base, "c", "b", false)), "acb");
  assert.equal(move(base, "c", "b", true), null);     // already there
  assert.equal(move(base, "a", "b", false), null);
  assert.equal(move(base, "b", "b", true), null);
  assert.equal(move(base, "q", "a", true), null);
  assert.equal(move(base, "a", "q", true), null);
  assert.equal(move(base, "a", "q", false), null, "an unknown target is refused on either side of it");
  assert.equal(move(base, "c", "q", true), null);
  assert.equal(names(base), "abc", "the input is not changed");
  const moved = move(base, "c", "a", false);
  assert.ok(moved[0] === base[2] && moved[1] === base[0], "the same members, only their order");
}
// the fold is in place and remembered; the mode switch saves only a change
const stepOf = (id) => { const attrs = {}, cls = new Set(); const button = { setAttribute: (k, v) => { attrs[k] = v; } }; return { dataset: { poolMember: id }, attrs, cls, classList: { toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)) }, querySelector: (sel) => (sel === "[data-pool-fold]" ? button : null) }; };
{
  const cards2 = new SubscriptionPoolCards({ accounts: [] }), step = stepOf("y");
  cards2.fold(step);
  assert.ok(cards2.open.has("y") && step.cls.has("open") && step.attrs["aria-expanded"] === "true" && step.attrs.title === "collapse");
  cards2.fold(step);
  assert.ok(!cards2.open.has("y") && !step.cls.has("open") && step.attrs["aria-expanded"] === "false" && step.attrs.title === "expand");
  const writes = calls.length, step2 = stepOf("a-test");
  const click = { type: "click", stopPropagation() {}, target: { matches: () => false, hasAttribute: (a) => a === "data-pool-fold", closest: (sel) => (sel === "[data-pool-member]" ? step2 : click.target) } };
  assert.equal(await cards.handle(click), true);
  assert.equal(calls.length, writes, "folding asks nothing of the server");
  assert.ok(cards.open.has("a-test"));
  await cards.handle(event({ poolMode: "manual" }));
  assert.equal(calls.at(-1)[1].pool.mode, "manual");
  assert.equal(calls.at(-1)[1].pool.manualAccountId, "a", "the first enabled member is picked for a switch to manual");
  const before = calls.length, same = event({ poolMode: "auto" });
  await cards.handle(same);
  assert.equal(calls.length, before, "the mode already on is not a change");
  assert.equal(same.target.disabled, false);
}
// the name is the title: a change in its field renames the pool and nothing else; the card's other fields write the same way
{
  const fieldEvent = (field, value, { checked = false, type = "text" } = {}) => {
    const e = { dataset: { poolField: field }, disabled: false, value, checked, type, matches: () => false, hasAttribute: () => false,
      closest: (selector) => selector === "[data-pool-id]" ? { dataset: { poolId: "p" } } : selector === "[data-pool-member]" ? null : e };
    return { type: "change", target: e, stopPropagation() {} };
  };
  const before = calls.length;
  await cards.handle(fieldEvent("name", "New <name>"));
  assert.equal(calls.length, before + 1, "a rename is one save");
  const renamed = calls.at(-1)[1].pool;
  assert.equal(renamed.name, "New <name>", "the text of the field, not its checkbox state");
  assert.deepEqual(renamed.members.map((m) => m.accountId), ["a", "a-test"], "nothing else about the pool changed");
  assert.equal(renamed.mode, "auto");
  assert.equal(source.pool.name, "Work", "the stored pool is not edited in place");
  await cards.handle(fieldEvent("returnToPrimary", "on", { checked: true, type: "checkbox" }));
  assert.equal(calls.at(-1)[1].pool.returnToPrimary, true, "the policy switch writes its state");
  await cards.handle(fieldEvent("manualDuration", "3600", { type: "select-one" }));
  assert.ok(Math.abs(calls.at(-1)[1].pool.manualUntil - (Math.floor(Date.now() / 1000) + 3600)) <= 2, "'until' is an hour from now");
  source.pool.manualUntil = 4102444800;   // a pool that is held by hand until some far day
  await cards.handle(fieldEvent("manualDuration", "0", { type: "select-one" }));
  assert.equal(calls.at(-1)[1].pool.manualUntil, 0, "'until cancelled' ends the time, it does not keep the old one");
  delete source.pool.manualUntil;
}
// dragging a rung by its grip
{
  const rung = (id, top) => { const cls = new Set(); return { dataset: { poolMember: id }, cls, classList: { add: (...c) => c.forEach((x) => cls.add(x)), remove: (...c) => c.forEach((x) => cls.delete(x)) }, getBoundingClientRect: () => ({ top, height: 40 }) }; };
  const rungs = { x: rung("x", 0), y: rung("y", 100), z: rung("z", 200) };
  const section = (poolId) => ({ dataset: { poolId }, querySelectorAll: () => ({ forEach: (fn) => Object.values(rungs).forEach(fn) }) });
  const p1 = section("p"), p2 = section("q");
  const grip = (id) => ({ closest: (sel) => (sel === "[data-pool-grip]" ? grip(id) : sel === "[data-pool-member]" ? rungs[id] : sel === "[data-pool-id]" ? p1 : null) });
  const over = (id, poolSection = p1) => ({ closest: (sel) => (sel === "[data-pool-member]" ? rungs[id] : sel === "[data-pool-id]" ? poolSection : null) });
  const dt = () => { const data = {}; return { data, effectAllowed: "", dropEffect: "", dragImage: null, setData: (k, v) => { data[k] = v; }, setDragImage(el) { this.dragImage = el; } }; };
  const ev = (type, target, extra = {}) => ({ type, target, clientY: 0, prevented: false, preventDefault() { this.prevented = true; }, ...extra });
  const dragCards = new SubscriptionPoolCards({ accounts: [...trio, poolOf(members3)], apply: (top) => applied.push(top) });
  const marks = () => Object.fromEntries(Object.entries(rungs).map(([id, r]) => [id, [...r.cls].sort().join(" ")]));
  const none = { x: "", y: "", z: "" };
  assert.equal(await dragCards.gesture(ev("dragstart", { closest: () => null })), false, "only the grip starts a drag");
  assert.equal(dragCards.dragging, null);
  const d = dt();
  assert.equal(await dragCards.gesture(ev("dragstart", grip("z"), { dataTransfer: d })), true);
  assert.deepEqual(dragCards.dragging, { pool: "p", id: "z" });
  assert.equal(d.data["text/plain"], "z");
  assert.equal(d.effectAllowed, "move");
  assert.equal(d.dragImage, rungs.z, "the whole rung follows the pointer, not the grip's one glyph");
  assert.deepEqual(marks(), { ...none, z: "dragging" });
  const top = ev("dragover", over("x"), { dataTransfer: d, clientY: 5 });
  assert.equal(await dragCards.gesture(top), true);
  assert.ok(top.prevented && d.dropEffect === "move");
  assert.deepEqual(marks(), { ...none, x: "drop-before", z: "dragging" });
  await dragCards.gesture(ev("dragover", over("x"), { dataTransfer: d, clientY: 35 }));
  assert.deepEqual(marks(), { ...none, x: "drop-after", z: "dragging" }, "the lower half of a rung drops after it, and the old mark goes");
  await dragCards.gesture(ev("dragover", over("z"), { dataTransfer: d, clientY: 205 }));
  assert.deepEqual(marks(), { ...none, z: "dragging" }, "over itself: no mark");
  const foreign = ev("dragover", over("y", p2), { dataTransfer: d, clientY: 105 });
  assert.equal(await dragCards.gesture(foreign), false);
  assert.ok(!foreign.prevented, "another pool's rung is no drop target");
  const writes = calls.length;
  await dragCards.gesture(ev("drop", over("z"), { dataTransfer: d, clientY: 205 }));
  assert.equal(calls.length, writes, "dropped where it was: nothing to save");
  assert.equal(dragCards.dragging, null);
  assert.deepEqual(marks(), none);
  await dragCards.gesture(ev("dragstart", grip("z"), { dataTransfer: d }));
  const drop = ev("drop", over("x"), { dataTransfer: d, clientY: 5 });
  assert.equal(await dragCards.gesture(drop), true);
  assert.ok(drop.prevented);
  assert.deepEqual(calls.at(-1)[1].pool.members.map((m) => m.accountId), ["z", "x", "y"]);
  assert.equal(calls.at(-1)[0], "/api/cloud-pools/save");
  assert.deepEqual(marks(), none);
  assert.equal(dragCards.dragging, null);
  assert.deepEqual(dragCards.accounts[3].pool.members.map((m) => m.accountId), ["x", "y", "z"], "the stored pool is not changed before the server answers");
  await dragCards.gesture(ev("dragstart", grip("y"), { dataTransfer: d }));
  await dragCards.gesture(ev("dragend", grip("y")));
  assert.equal(dragCards.dragging, null);
  assert.deepEqual(marks(), none, "a drag that ends anywhere leaves nothing marked");
  const okApi = globalThis.__stubReturns["utils.api"];
  globalThis.__stubReturns["utils.api"] = async () => { throw new Error("order not saved"); };
  await dragCards.gesture(ev("dragstart", grip("x"), { dataTransfer: d }));
  await dragCards.gesture(ev("drop", over("z"), { dataTransfer: d, clientY: 235 }));
  assert.equal(notices.at(-1), "order not saved");
  globalThis.__stubReturns["utils.api"] = okApi;
  // a rung in the air holds the lane's redraw — and only while it is there
  dragCards.dragging = { pool: "p", id: "z" };
  const hadDocument = globalThis.document;
  assert.equal(dragCards.inFlight(), false, "no page, no rung: the flag goes");
  assert.equal(dragCards.dragging, null);
  dragCards.dragging = { pool: "p", id: "z" };
  globalThis.document = { querySelector: (s) => (s === ".pool-step.dragging" ? {} : null) };
  assert.equal(dragCards.inFlight(), true);
  assert.deepEqual(dragCards.dragging, { pool: "p", id: "z" });
  globalThis.document = { querySelector: () => null };
  assert.equal(dragCards.inFlight(), false, "the rung is gone (drawn over, or dragend never came): the flag must not outlive it");
  assert.equal(dragCards.dragging, null);
  if (hadDocument === undefined) delete globalThis.document; else globalThis.document = hadDocument;
}
// the card an account is drawn on under Model servers: its pool's, or its own (the lane and the kanban both place by it)
{
  const accounts = [
    { id: "solo", name: "Solo" },
    { id: "p1", isPool: true, pool: { id: "p1", members: [{ accountId: "m1" }, { accountId: "m2" }] } },
    { id: "m1" }, { id: "m2" },
    { id: "p2", isPool: true, pool: { id: "p2", members: [{ accountId: "m3" }] } },
    { id: "m3" },
    { id: "broken", isPool: true },
  ];
  assert.deepEqual(["solo", "p1", "m1", "m2", "p2", "m3", "broken", "unknown"].map((id) => SubscriptionPoolCards.cardOf(accounts, id)),
    ["solo", "p1", "p1", "p1", "p2", "p2", "broken", "unknown"], "a member is drawn on its pool's card; a pool, an account outside pools and one not listed — on their own");
  assert.equal(SubscriptionPoolCards.cardOf([{ id: "plain", pool: { members: [{ accountId: "x" }] } }, { id: "x" }], "x"), "x",
    "negative: only a pool takes members — an account that merely carries a pool field is not one");
  assert.equal(SubscriptionPoolCards.cardOf([], "x"), "x");
}
// the kanban's groups: a member stands only while it holds models of its own
{
  const accounts = [
    { id: "solo" },
    { id: "p1", isPool: true, pool: { id: "p1", members: [{ accountId: "m1" }, { accountId: "m2" }] } },
    { id: "m1" }, { id: "m2" },
  ];
  const ids = (blocks) => SubscriptionPoolCards.kanbanGroups(accounts, blocks).map((a) => a.id);
  assert.deepEqual(ids([{ id: "b1", accountId: "p1" }]), ["solo", "p1"],
    "a member without models of its own has no group: its models are reached through the pool");
  assert.deepEqual(ids([{ id: "b1", accountId: "p1" }, { id: "b2", accountId: "m2" }]), ["solo", "p1", "m2"],
    "negative: a member that still holds a model keeps its group — hiding it would hide that output");
  assert.deepEqual(ids([]), ["solo", "p1"], "an account outside pools and a pool keep their groups without models");
  assert.deepEqual(ids(undefined), ["solo", "p1"], "no block list reads as no models, not as an error");
}
console.log("subscription pool UI OK: identities, shared quota, manual/auto, priority ladder, status pills, fold, drag order, adoption, error recovery, the card a member is drawn on, the kanban's groups");
'''
node = find_node()
if not node:
    raise SystemExit('node required')
probe = ROOT / 'scripts' / '.probe_pool.tmp.mjs'
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
