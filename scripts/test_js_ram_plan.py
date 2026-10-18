#!/usr/bin/env python3
"""Actual ram-plan.js: what a cell keeps in the machine's memory, for the cell form's RAM scale (1.3.574).

The owner, 2026-10-18, looking at the form of a Strata cell: "I do not see the planned amount of RAM on the scale on the right" — the VRAM
scale said "≈ 31.4 GB", the RAM scale only what was in use. The figure is the runner's own promise (runner.py, ram_reservation), the one a
start sends the scout and the scout refuses a start by; the form asks the controller for it (POST /api/cell-ram-plan), so the rule has one
copy. RamPlan is the answer and the arithmetic the scale needs; RamPlanAsk is the asking: one per form, a moment after the last change,
an answer for a config the form no longer holds dropped.

The module is loaded FOR REAL (utils.js with it); the controller and the clock are stand-ins passed to the class.

Run: python3 scripts/test_js_ram_plan.py
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { RamPlan, RamPlanAsk } = await import(pathToFileURL(process.env.JS_ROOT + "/ram-plan.js").href);
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };
const eq = (got, want, why) => { assert.deepEqual(got, want, why + ` (got ${JSON.stringify(got)})`); pass.push(why); };

// ── the plan ──
{
  const strata = { ok: true, runner: "strata", ram: { reserveMiB: 52531, who: "Strata", why: "its experts stay in memory" }, headroomMiB: 2048 };
  const plan = RamPlan.from(strata);
  eq([plan.reserveMiB, plan.headroomMiB, plan.who, plan.addGb, plan.headroomGb], [52531, 2048, "Strata", 52531 / 1024, 2],
     "the plan is the controller's promise and the room the scout leaves the system, in MiB and in GB (the scale's own unit)");
  pin(RamPlan.from({ ok: true, runner: "llama-server", ram: null, headroomMiB: 2048 }) === null,
      "negative: a runner that keeps nothing it can name in memory has no plan — never a plan of zero");
  pin(RamPlan.from({ ram: { reserveMiB: 0 } }) === null && RamPlan.from({ ram: { reserveMiB: -5 } }) === null && RamPlan.from({ ram: { reserveMiB: "many" } }) === null
      && RamPlan.from({ ram: {} }) === null && RamPlan.from({}) === null && RamPlan.from(null) === null && RamPlan.from(undefined) === null,
      "negative: an answer that says nothing usable (zero, negative, not a number, empty, none) is no plan");
  eq(RamPlan.from({ ram: { reserveMiB: 1024 } }).headroomMiB, 0, "an answer with no room for the system counts none: the plan is still drawn, by what it says");
  eq(RamPlan.from({ ram: { reserveMiB: 1024 }, headroomMiB: -7 }).headroomMiB, 0, "negative: a room that is not a size is none, not a negative size that would make everything fit");
  eq(RamPlan.from({ ram: { reserveMiB: 1024 } }).who, "", "boundary: no name for the runner is an empty name");
}

// ── the scout's rule: no more than free, less the room it leaves the system ──
{
  const at = (mib) => new RamPlan(mib, 2048, "Strata");
  pin(at(51200).fits(52) && !at(51201).fits(52),
      "boundary: with 52 GB free and 2 GB left to the system a promise of 50 GB (51200 MiB) fits and one MiB more does not — the scout's own cut (MemoryLedger.short)");
  pin(!at(52531).fits(52.1) && at(40 * 1024).fits(52.1),
      "the Swift IQ3_S promise (51.3 GB) does not fit 52.1 GB free, a 40 GB one does");
  pin(new RamPlan(1024, 0, "").fits(1) && !new RamPlan(1025, 0, "").fits(1),
      "no room left to the system: the promise fits what is free, to the MiB");
  pin(!at(1).fits(0) && !at(1).fits(2), "negative: nothing free (or only the system's room) fits nothing");
}

// ── the asking ──
const sleep = () => new Promise((resolve) => setImmediate(resolve));
const rig = (answers = {}) => {
  // a clock that keeps what is waiting, by id, and drops what is cleared
  const timers = { queue: [], last: 0, setTimeout(fn, ms) { this.queue.push({ fn, ms, id: ++this.last }); return this.last; },
                   clearTimeout(id) { this.queue = this.queue.filter((job) => job.id !== id); } };
  const calls = [], drawn = [];
  const call = async (path, opts) => {
    calls.push([path, JSON.parse(opts.body).config]);
    const key = JSON.parse(opts.body).config.MODEL_FILE;
    if (answers[key] instanceof Error) throw answers[key];
    return answers[key];
  };
  const ask = new RamPlanAsk({ call, delay: 160, timers });
  const fire = async () => { const job = timers.queue.shift(); if (job) job.fn(); await sleep(); await sleep(); };
  return { ask, timers, calls, drawn, again: () => drawn.push(1), fire };
};
const STRATA = { ok: true, runner: "strata", ram: { reserveMiB: 52531, who: "Strata" }, headroomMiB: 2048 };
{
  const r = rig({ a: STRATA });
  const A = { RUNNER: "strata", MODEL_FILE: "a" };
  pin(r.ask.planFor(A, r.again) === null && r.timers.queue.length === 1 && r.timers.queue[0].ms === 160 && r.calls.length === 0,
      "the first draw has no plan and asks nothing yet: the controller is asked a moment (160 ms) after the last change, not at once");
  await r.fire();
  eq(r.calls, [["/api/cell-ram-plan", A]], "the controller is asked with the config the form holds, at /api/cell-ram-plan");
  pin(r.drawn.length === 1, "the answer redraws the scale once");
  const plan = r.ask.planFor(A, r.again);
  pin(plan instanceof RamPlan && plan.reserveMiB === 52531 && r.timers.queue.length === 0 && r.calls.length === 1,
      "a redraw of the same config gets the plan that is held — no new request, no new timer");
  pin(r.ask.planFor({ ...A }, r.again) === plan && r.calls.length === 1,
      "the config is compared by what it says, not by identity: the form reads a new object at every draw");
}
{
  const r = rig({ a: STRATA, b: { ok: true, runner: "strata", ram: { reserveMiB: 36352 + 1024, who: "Strata" }, headroomMiB: 2048 } });
  r.ask.planFor({ MODEL_FILE: "a" }, r.again);
  await r.fire();
  pin(r.ask.planFor({ MODEL_FILE: "b" }, r.again) === null && r.ask.plan === null,
      "a config that changed has no plan until it is answered: the plan of the model before is not drawn for the model now");
  await r.fire();
  eq(r.ask.planFor({ MODEL_FILE: "b" }, r.again).reserveMiB, 37376, "and then it has its own");
  eq(r.drawn.length, 2, "each answer redrew once");
}
{
  const r = rig({ a: STRATA, b: STRATA });
  r.ask.planFor({ MODEL_FILE: "a" }, r.again);
  r.ask.planFor({ MODEL_FILE: "b" }, r.again);
  eq(r.timers.queue.length, 1, "debounce: a change made while the controller is still to be asked clears the wait of the change before it — one wait stands");
  await r.fire();
  eq(r.calls.map((c) => c[1].MODEL_FILE), ["b"], "and the controller is asked of the last config only: the one before was never asked");
}
{
  // the answer to a config the form has left
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  const timers = { queue: [], setTimeout(fn) { this.queue.push(fn); return 1; }, clearTimeout() {} };
  const drawn = [];
  const ask = new RamPlanAsk({ call: async (path, opts) => (JSON.parse(opts.body).config.MODEL_FILE === "a" ? slow : STRATA), delay: 1, timers });
  ask.planFor({ MODEL_FILE: "a" }, () => drawn.push("a"));
  timers.queue.shift()();
  await sleep();
  ask.planFor({ MODEL_FILE: "b" }, () => drawn.push("b"));
  release(STRATA);
  await sleep(); await sleep();
  pin(ask.plan === null && drawn.length === 0,
      "negative: an answer that arrives for a config the form has moved on from is dropped — it is neither kept as the plan of the config now nor drawn");
}
{
  const r = rig({ a: new Error("controller is down") });
  r.ask.planFor({ MODEL_FILE: "a" }, r.again);
  await r.fire();
  pin(r.ask.plan === null && r.drawn.length === 0 && r.ask.planFor({ MODEL_FILE: "a" }, r.again) === null && r.timers.queue.length === 0 && r.calls.length === 1,
      "negative: a failed request leaves no plan, draws nothing and is not asked again for the same config — a plan that is not there is not made up, and a down controller is not hammered");
  const none = rig({ a: { ok: true, runner: "llama-server", ram: null, headroomMiB: 2048 } });
  none.ask.planFor({ MODEL_FILE: "a" }, none.again);
  await none.fire();
  pin(none.ask.plan === null && none.drawn.length === 0, "negative: an answer of no promise draws nothing — there is nothing to redraw");
}
{
  const a = RamPlanAsk.of("tr-"), b = RamPlanAsk.of("");
  pin(a === RamPlanAsk.of("tr-") && a !== b && a instanceof RamPlanAsk, "one asking per form: the cell form (tr-) and the main form () do not share a plan");
}

for (const why of pass) console.log("  ok  " + why);
console.log(`js ram-plan OK: ${pass.length} pins — the plan, the scout's cut, the asking`);
'''


def main():
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_ram_plan.tmp.mjs"
    probe.write_text(PROBE)
    try:
        result = subprocess.run([node, str(probe)], cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=60)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
