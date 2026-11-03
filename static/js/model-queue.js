// A local model's queue, as Routing draws it (the owner, 2026-10-26: "several pools may go to one local model, so the queue is
// to be made on the model, not in the pool"; of the mockups — canvas Wo63Az2b3Vc7C6sv6h3vyj — "I like the new mockups, do it").
// Read from the monitor's rows of requests, the rows the cables' drops are read from (pool-flow.js), and from what the proxy
// says on each request in a model's queue: since when it waits, when it leaves and where to (`queue.since`, `leaveAt`,
// `leaveTo`; rust/crates/rules/src/model_queue.rs, QueueLeave), since when a served one holds its slot (`slotAt`) and when its client
// gives up on it (`clientDeadline`). Nothing the proxy decides is worked out here: a request that says no leave is drawn as one
// that does not leave by itself, never with an end guessed for it, a served one with no deadline said has a bar with no end, and
// a slot count nobody said is "?". The board says which model a request is on (`keyOf`), the clock is a parameter: the rule is
// read by value (scripts/test_js_model_queue.py).
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

// Time as the queue says it: a clock for how long ("1:05", "23:20", "1:02:03"), seconds under a minute where it is short ("25 s").
export class QueueTime {
  static clock(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const two = (n) => String(n).padStart(2, "0");
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h ? `${h}:${two(m)}:${two(s % 60)}` : `${m}:${two(s % 60)}`;
  }

  // How long is left, rounded up: a request is not "0 s" from leaving while it still waits.
  static left(seconds) {
    const s = Math.max(0, Math.ceil(Number(seconds) || 0));
    return s < 60 ? t("pbQueueSec", { n: String(s) }) : QueueTime.clock(s);
  }
}

// The scale under a waiting request's bar: at most five steps of a round size, in minutes when the steps and the end are whole
// minutes, in seconds under a minute, as a clock otherwise. A tick at each step inside the bar; a label at each, but none too
// near the end, which is always labelled — with its unit.
export class QueueScale {
  static STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];

  static of(total) {
    const end = Number(total);
    if (!(end > 0)) return { ticks: [], labels: [] };
    const step = QueueScale.STEPS.find((s) => end / s <= 5) || 3600;
    const minutes = step % 60 === 0 && end % 60 === 0;
    const word = (v, last) => (minutes ? (last ? t("pbQueueMin", { n: String(v / 60) }) : String(v / 60))
      : end < 60 ? (last ? t("pbQueueSec", { n: String(v) }) : String(v)) : QueueTime.clock(v));
    const at = (v) => `${Number((v / end * 100).toFixed(2))}%`;
    const ticks = [];
    const labels = [{ at: "0%", text: "0", edge: "start" }];
    for (let v = step; v < end; v += step) {
      ticks.push(at(v));
      if ((end - v) / end >= 0.12) labels.push({ at: at(v), text: word(v, false), edge: "" });
    }
    labels.push({ at: "100%", text: word(end, true), edge: "end" });
    return { ticks, labels };
  }
}

export class ModelQueue {
  // The monitor's `agents` ({port: {active: [request]}}) → a queue for each model a request is on now, by the model's key on the
  // board. `keyOf(request)` names the model ("" — none the board draws); `slots(group)` the slots the proxy counted for the
  // request's upstream (`slotTotals`), or nothing; `now` is epoch milliseconds. A request still being routed — queued, with no
  // model's queue said yet — is in none.
  static of(agents, keyOf, slots, now) {
    const queues = new Map();
    for (const row of Object.values(agents || {})) {
      for (const item of row?.active || []) {
        const key = item ? keyOf(item) : "";
        if (!key) continue;
        const waiting = item.phase === "queued" && !item.slotAt;
        if (waiting && !(Number(item.queue?.since) > 0)) continue;
        if (!queues.has(key)) queues.set(key, new ModelQueue(key, now));
        queues.get(key).add(item, waiting, slots);
      }
    }
    for (const queue of queues.values()) queue.order();
    return queues;
  }

  constructor(key, now) {
    this.key = key;
    this.now = Number(now) / 1000;   // seconds, as the proxy says its times
    this.running = [];
    this.waiting = [];
    this.slots = null;               // the model's slots as the proxy counted them; null — nobody said
  }

  add(item, waiting, slots) {
    const said = Number(item.upstream && slots ? slots(String(item.upstream)) : 0);
    if (said > 0) this.slots = said;
    const request = { id: String(item.id || ""), client: String(item.route || ""), pool: String(item.cloudPoolId || ""),
      row: String(item.poolStepId ?? "") };
    if (!waiting) {
      // When its client gives up on it: the proxy says it (`clientDeadline`); the model never says how long its answer is.
      const deadline = Number(item.clientDeadline) > 0 ? Number(item.clientDeadline) : null;
      this.running.push({ ...request, since: Number(item.slotAt) || Number(item.startedAt) || null,
        started: Number(item.startedAt) || null, deadline });
      return;
    }
    const q = item.queue || {};
    const leaveAt = Number(q.leaveAt) > 0 ? Number(q.leaveAt) : null;
    const position = Number(q.position);
    this.waiting.push({ ...request, since: Number(q.since), position: Number.isFinite(position) ? position : Infinity,
      leaveAt, leaveTo: leaveAt && ["next", "refuse"].includes(q.leaveTo) ? q.leaveTo : null });
  }

  order() {
    this.waiting.sort((a, b) => a.position - b.position || a.since - b.since);
    this.running.sort((a, b) => (a.since ?? 0) - (b.since ?? 0));
  }

  // A waiting request as it is drawn: how long it waited, how long its bar is and how much is left — none of the two when it
  // says no leave.
  span(request) {
    const waited = Math.max(0, this.now - request.since);
    if (!request.leaveAt) return { waited, total: null, left: null, fill: null };
    const total = Math.max(0, request.leaveAt - request.since);
    const left = Math.max(0, request.leaveAt - this.now);
    return { waited, total, left, fill: total > 0 ? Math.min(100, waited / total * 100) : 100 };
  }

  // A served request on its client's scale (1.3.670; the owner, 2026-10-27: "why is the end unknown? we know when the request
  // came and where it is cut off"): from the moment the proxy received it to the moment its client gives up (`clientDeadline`),
  // the shares it waited in the queue and has run since; the rest is what its client still waits. The model never says how long
  // its answer is, so the bar ends where the client stops waiting, not where the answer will. No deadline said — null: no scale.
  runSpan(r) {
    const start = r.started ?? r.since;
    if (!r.deadline || !start || !(r.deadline > start)) return null;
    const total = r.deadline - start;
    const share = (at) => Math.min(100, Math.max(0, (at - start) / total * 100));
    const queued = share(r.since ?? start);
    return { total, queued, ran: Math.max(0, share(this.now) - queued) };
  }

  get slotsText() {
    return this.slots ? String(this.slots) : "?";
  }

  // The model's line on its card: "1 of 1", and with a queue "1 of 1 · 2 wait" — nothing while it serves none and none waits.
  chip() {
    const n = this.waiting.length;
    if (!this.running.length && !n) return null;
    const vars = { busy: String(this.running.length), slots: this.slotsText, n: String(n) };
    return { text: t(n ? "pbQueueChipWaiting" : "pbQueueChip", vars), title: t("pbQueueChipTitle", vars), waiting: n > 0 };
  }

  // A pool's row whose requests wait in this queue: how many, and how long until the first of them leaves. A row is always a
  // pool's: a request routed straight to the model is no row's.
  rowWait(pool, row) {
    if (!pool) return null;
    const mine = this.waiting.filter((w) => w.pool === String(pool) && w.row === String(row));
    if (!mine.length) return null;
    const lefts = mine.map((w) => this.span(w).left).filter((x) => x !== null);
    const time = lefts.length ? QueueTime.left(Math.min(...lefts)) : null;
    if (mine.length > 1) return t(time ? "pbQueueRowWaitMany" : "pbQueueRowWaitManyStay", { n: String(mine.length), time: time || "" });
    return time ? t("pbQueueRowWait", { time }) : t("pbQueueRowWaitStays");
  }

  // The queue in the strip of its model: who holds the slots and for how long, and each waiting request on a scale — how long
  // it waited, how long is left, and what comes at the end of it. `rowOf(request)` is the number of the row a request that goes
  // on would go to, or null when the board cannot say which (the proxy picks the next ready row at that moment). `poolName(id)` is
  // the name the board shows a pool by: a request carries its pool's id, and an id like `gpt-6-1-sol` beside another model's queue
  // read as the model the request was for (the owner's strip, 2026-10-26).
  html(rowOf = () => null, poolName = (id) => id) {
    const busy = { busy: String(this.running.length), slots: this.slotsText };
    const running = this.running.map((r) => `<div class="pb-queue-slot" data-t="pb-queue-slot">`
      + `<span class="pb-queue-who"><b>${escapeHtml(r.client)}</b>${r.pool ? ` · ${escapeHtml(poolName(r.pool))}` : ""}</span>`
      + `<span class="pb-queue-time run">${escapeHtml(this.runningWords(r))}</span>${this.runHtml(r)}</div>`).join("");
    const waits = this.waiting.map((w, i) => this.waitHtml(w, i, rowOf, poolName)).join("");
    const state = this.waiting.length ? "waiting" : this.running.length ? "busy" : "idle";
    return `<div class="pb-queue" data-t="pb-queue" data-t-state="${state}">`
      + `<div class="pb-queue-head">${escapeHtml(t("pbQueueBusy", busy))}</div>${running}`
      + `<div class="pb-queue-head${this.waiting.length ? " waiting" : ""}">${escapeHtml(this.waitingHead())}</div>${waits}</div>`;
  }

  // How long a slot has been held, and how long its client still waits — "end unknown" while the proxy says no deadline.
  runningWords(r) {
    const time = QueueTime.clock(r.since ? this.now - r.since : 0);
    return r.deadline ? t("pbQueueRunningLeft", { time, left: QueueTime.left(Math.max(0, r.deadline - this.now)) })
      : t("pbQueueRunning", { time });
  }

  // A served request's bar: on its client's scale — the amber of its wait in the queue, the stripes of its work, the rest its
  // client still waits — or, with no deadline said, stripes with no end.
  runHtml(r) {
    const span = this.runSpan(r);
    if (!span) return `<span class="pb-queue-run" title="${escapeHtml(t("pbQueueRunningTitle"))}"></span>`;
    const share = (x) => Number(x.toFixed(1));
    const parts = (span.queued > 0 ? `<i style="width: ${share(span.queued)}%"></i>` : "")
      + `<i class="ran" style="left: ${share(span.queued)}%; width: ${share(span.ran)}%"></i>`;
    return ModelQueue.scaleHtml(span.total, "run", parts, this.runningWords(r), t("pbQueueRunScaleTitle"));
  }

  // A bar on its scale of `total` seconds: its parts, the steps ticked inside it and labelled under it.
  static scaleHtml(total, look, parts, label, title = "") {
    const { ticks, labels } = QueueScale.of(total);
    return `<span class="pb-queue-scale"${title ? ` title="${escapeHtml(title)}"` : ""}>`
      + `<span class="pb-queue-bar ${look}" role="img" aria-label="${escapeHtml(label)}">`
      + `${parts}${ticks.map((at) => `<s style="left: ${at}"></s>`).join("")}</span>`
      + `<span class="pb-queue-ticks">${labels.map((l) => `<span class="${l.edge}" style="left: ${l.at}">${escapeHtml(l.text)}</span>`).join("")}</span></span>`;
  }

  waitingHead() {
    if (!this.waiting.length) return t("pbQueueNobody");
    const spans = this.waiting.map((w) => this.span(w));
    const lefts = spans.map((s) => s.left).filter((x) => x !== null);
    const notes = [t("pbQueueLongest", { time: QueueTime.clock(Math.max(...spans.map((s) => s.waited))) })];
    if (lefts.length) notes.push(t("pbQueueSoonest", { time: QueueTime.left(Math.min(...lefts)) }));
    return `${t("pbQueueWaiting", { n: String(this.waiting.length) })} · ${notes.join(" · ")}`;
  }

  waitHtml(w, index, rowOf, poolName = (id) => id) {
    const span = this.span(w);
    const head = index === 0 && this.running.length ? `<em class="pb-queue-next">${escapeHtml(t("pbQueueNext"))}</em>` : "";
    const time = `<b>${escapeHtml(t("pbQueueWaited", { time: QueueTime.clock(span.waited) }))}</b> · `
      + escapeHtml(span.left === null ? t("pbQueueNoLimit") : t("pbQueueLeft", { time: QueueTime.left(span.left) }));
    let scale = `<span class="pb-queue-scale none"></span>`;
    let fate = "";
    if (span.total !== null) {
      scale = ModelQueue.scaleHtml(span.total, w.leaveTo || "unsaid", `<i style="width: ${Number(span.fill.toFixed(1))}%"></i>`,
        time.replace(/<[^>]+>/g, ""));
      // What comes at the end, as the proxy said it; an end it did not say is not drawn as either.
      const row = w.leaveTo === "next" ? rowOf(w) : null;
      const [words, title] = w.leaveTo === "next"
        ? [row ? t("pbQueueToRow", { n: String(row) }) : t("pbQueueToNext"), t("pbQueueToNextTitle")]
        : [t("pbQueueTo503"), t("pbQueueTo503Title")];
      fate = w.leaveTo ? `<span class="pb-queue-fate ${w.leaveTo}" title="${escapeHtml(title)}">${escapeHtml(words)}</span>` : "";
    }
    return `<div class="pb-queue-wait" data-t="pb-queue-wait" data-t-state="${w.leaveTo || "stays"}">`
      + `<span class="pb-queue-pos">${index + 1}</span>`
      + `<span class="pb-queue-who"><b>${escapeHtml(w.client)}</b>${w.pool ? ` · ${escapeHtml(poolName(w.pool))}` : ""}${head}</span>`
      + `${scale}<span class="pb-queue-time">${time}</span>${fate}</div>`;
  }
}
