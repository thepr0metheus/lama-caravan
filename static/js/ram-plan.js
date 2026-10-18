// What a cell keeps in the machine's memory, said on the cell form's RAM scale (the owner, 2026-10-18, looking at the form of a Strata
// cell: "I do not see the planned amount of RAM on the scale on the right" — the VRAM scale said "≈ 31.4 GB", the RAM scale only what
// was in use). The figure is not the form's to work out: it is the runner's own promise (runner.py, ram_reservation), the one a start
// sends the scout, and the scout refuses a start by it (caravan-scout, MemoryLedger). The form asks the controller for it, so the rule
// has one copy; this file is the asking and the arithmetic the scale needs.
import { api } from "./utils.js";

export class RamPlan {
  constructor(reserveMiB, headroomMiB, who = "") {
    this.reserveMiB = reserveMiB;
    this.headroomMiB = headroomMiB;
    this.who = who;
  }

  /** The plan an answer of /api/cell-ram-plan holds; null when the runner keeps nothing it can name in memory, or the answer says nothing
   *  usable — no plan is drawn, never a plan of zero. */
  static from(answer) {
    const mib = Number(answer?.ram?.reserveMiB);
    if (!Number.isFinite(mib) || mib <= 0) return null;
    return new RamPlan(mib, Math.max(0, Number(answer?.headroomMiB) || 0), String(answer?.ram?.who || ""));
  }

  get addGb() { return this.reserveMiB / 1024; }
  get headroomGb() { return this.headroomMiB / 1024; }

  /** The scout's rule (MemoryLedger.short): the promise may be no more than what the kernel says is available, less the room the scout
   *  leaves the system. Beyond it the scout refuses the start, whatever the estimate's grace. */
  fits(freeGb) { return this.addGb <= freeGb - this.headroomGb; }
}

// The asking, one per form (its prefix). A form changes often and the answer is a few hundred bytes from a rule that costs nothing,
// but a request per keystroke is still noise: it waits a moment (`delay`) after the last change, and an answer that arrives for a
// config the form no longer holds is dropped. The plan of the config the form holds is kept, so a redraw does not ask again.
export class RamPlanAsk {
  static forms = new Map();

  /** The asking of the form with this prefix. */
  static of(pfx) {
    if (!RamPlanAsk.forms.has(pfx)) RamPlanAsk.forms.set(pfx, new RamPlanAsk());
    return RamPlanAsk.forms.get(pfx);
  }

  constructor({ call = api, delay = 160, timers = globalThis } = {}) {
    this.call = call;
    this.delay = delay;
    this.timers = timers;
    this.key = "";        // the config the form holds, as text: what the plan below is of
    this.plan = null;     // its plan once known; null while asked, and for a runner that promises nothing
    this.timer = 0;
  }

  /** The plan of `config` if it is known now; otherwise null, and the controller is asked and `again()` is called when it has answered —
   *  the form draws once with no plan and once with it. A config that is the one already held (a redraw) is neither asked again nor
   *  forgotten. A refusal or a network error leaves no plan and is not retried until the config changes: a plan that is not there is
   *  not drawn, and it is not the form's to guess one. */
  planFor(config, again = () => {}) {
    const key = JSON.stringify(config ?? {});
    if (key === this.key) return this.plan;
    this.key = key;
    this.plan = null;
    this.timers.clearTimeout(this.timer);
    this.timer = this.timers.setTimeout(() => this.ask(key, config, again), this.delay);
    return null;
  }

  async ask(key, config, again) {
    let answer = null;
    try {
      answer = await this.call("/api/cell-ram-plan", { method: "POST", body: JSON.stringify({ config }) });
    } catch (err) {
      return;
    }
    if (key !== this.key) return;     // the form moved on while this was on its way
    this.plan = RamPlan.from(answer);
    if (this.plan) again();
  }
}
