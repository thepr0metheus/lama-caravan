// When a model is open: the ⏱ on each model of the kanban's right column and the window it opens
// (the owner, 2026-10-12, visumap scheme caravan-model-schedule). A schedule is the model's, the
// same in every pool whose row names it; a pool passes over the row of a model closed now.
//
// The window paints a week of hours on a grid, as the old kanban's schedule node did, and lists the
// same hours as windows with exact times (static/js/week-windows.js keeps the two one week). Its
// hours are the caravan's own — the zone the controller runs in, which the controller names
// (`modelSchedules.zone`) — not this browser's: a browser in another zone draws the hours the proxy
// keeps to. What a model is now (open until…, closed until…) is the controller's word, read where
// it was saved; the page says it, and never works it out of its own.
import { lang, t } from "./i18n.js";
import { WeekWindows } from "./week-windows.js";
import { escapeHtml } from "./utils.js";

// Times in the caravan's zone, in the board's language.
export class ScheduleClock {
  constructor(zone = null, language = "en") {
    this.zone = zone || { name: "UTC", known: false, offsetMinutes: 0 };
    this.language = language || "en";
  }

  // The zone Intl reads the time in, and how far an epoch is moved first: by name when the
  // controller knows its zone, else by the offset it stated.
  frame() {
    if (this.zone.known && this.zone.name) {
      try {
        new Intl.DateTimeFormat("en-US", { timeZone: this.zone.name });
        return { timeZone: this.zone.name, shift: 0 };
      } catch {
        // a zone this browser does not know: the stated offset
      }
    }
    return { timeZone: "UTC", shift: Number(this.zone.offsetMinutes || 0) * 60 };
  }

  // An epoch (seconds) on the caravan's wall clock: {day (Monday 0), hour, minute, date}.
  parts(epoch) {
    const { timeZone, shift } = this.frame();
    const at = new Date((Number(epoch) + shift) * 1000);
    const got = {};
    for (const p of new Intl.DateTimeFormat("en-US", { timeZone, hourCycle: "h23", weekday: "short",
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(at)) got[p.type] = p.value;
    const day = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(got.weekday);
    return { day, hour: Number(got.hour) % 24, minute: Number(got.minute), date: `${got.year}-${got.month}-${got.day}` };
  }

  // A weekday by its Monday-based number, short, in the board's language.
  dayName(day) {
    try {
      return new Intl.DateTimeFormat(this.language, { weekday: "short", timeZone: "UTC" }).format(new Date(Date.UTC(2024, 0, 1 + day)));
    } catch {
      return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day] || "";
    }
  }

  // When something happens, as a person reads it beside now: "19:00" today, "Mon 09:00" later.
  when(epoch, now) {
    const at = this.parts(epoch);
    const time = `${String(at.hour).padStart(2, "0")}:${String(at.minute).padStart(2, "0")}`;
    return at.date === this.parts(now).date ? time : `${this.dayName(at.day)} ${time}`;
  }

  offsetText() {
    const minutes = Number(this.zone.offsetMinutes || 0);
    const sign = minutes < 0 ? "-" : "+";
    const abs = Math.abs(minutes);
    return `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
  }
}

export class ModelScheduleEditor {
  constructor({ call, notify, apply = () => {}, redraw = () => {}, now = () => Date.now() / 1000 } = {}) {
    this.call = call;
    this.notify = notify;
    this.apply = apply;      // the controller's answer → the board
    this.redraw = redraw;    // the board drawn anew, this window with it
    this.now = now;          // seconds; the grid marks the caravan's hour now
    this.top = null;
    this.form = null;        // {key, title, cell, enabled, windows, busy}
    this.painting = null;    // the pointer held on the grid: {open, mask}
  }

  // ── what the board reads ────────────────────────────────────────────

  set(top) {
    this.top = top || {};
    return this;
  }

  schedules() {
    return this.top?.modelSchedules || { zone: null, models: {} };
  }

  clock() {
    return new ScheduleClock(this.schedules().zone, lang);
  }

  // A model's schedule as the controller keeps it, with what it says now — or null: none.
  entry(key) {
    return this.schedules().models?.[key] || null;
  }

  // The ⏱ of a model: faint while it has no schedule or one switched off — open at any time —
  // and, while one is on, when it closes or opens next.
  chipHtml(key, title) {
    const entry = this.entry(key);
    const clock = this.clock();
    const now = Number(this.schedules().now || this.now());
    let look = "none";
    let text = "⏱";
    let hint = t("pbSchedChip");
    if (entry && !entry.enabled) {
      look = "off";
      hint = t("pbSchedOff");
    } else if (entry?.open) {
      look = "open";
      text = `⏱ ${entry.until ? t("pbSchedOpenUntil", { time: clock.when(entry.until, now) }) : t("pbSchedAlways")}`;
    } else if (entry) {
      look = "closed";
      text = `⏱ ${entry.opensAt ? t("pbSchedClosedUntil", { time: clock.when(entry.opensAt, now) }) : t("pbSchedClosed")}`;
    }
    return `<button class="pb-sched ${look}" type="button" data-ms-open="${escapeHtml(key)}" data-ms-title="${escapeHtml(title)}"`
      + ` data-t="pb-model-schedule" data-t-id="${escapeHtml(key)}" data-t-state="${look}" title="${escapeHtml(hint)}">${escapeHtml(text)}</button>`;
  }

  // A pool's row of a model closed now: what its pill says, or null while the model may serve.
  closedWord(key) {
    const entry = this.entry(key);
    if (!entry?.enabled || entry.open !== false) return null;
    const now = Number(this.schedules().now || this.now());
    return entry.opensAt ? t("pbSchedClosedUntil", { time: this.clock().when(entry.opensAt, now) }) : t("pbSchedClosed");
  }

  // ── the window ──────────────────────────────────────────────────────

  open(key, title) {
    const entry = this.entry(key);
    // A model with no schedule yet opens with the switch on: one opens this window to make one.
    this.form = { key, title: String(title || key), cell: String(key).startsWith("out:"),
      enabled: entry ? !!entry.enabled : true, windows: (entry?.windows || []).map((w) => ({ ...w, days: [...(w.days || [])] })), busy: false };
    this.redraw();
    return this.form;
  }

  close() {
    if (!this.form) return null;
    this.form = null;
    this.painting = null;
    this.redraw();
    return true;
  }

  html() {
    const f = this.form;
    if (!f) return "";
    const clock = this.clock();
    const zone = this.schedules().zone;
    const now = this.now();
    const here = clock.parts(now);
    const close = `<button class="pb-tool" type="button" data-ms-close data-t="pb-schedule-close" title="${escapeHtml(t("topologyClose"))}" aria-label="${escapeHtml(t("topologyClose"))}">✕</button>`;
    const nowText = `${clock.dayName(here.day)} ${String(here.hour).padStart(2, "0")}:${String(here.minute).padStart(2, "0")}`;
    const zoneLine = zone?.known
      ? t("pbSchedZone", { zone: String(zone.name), offset: clock.offsetText(), now: nowText })
      : t("pbSchedZoneUnknown");
    const ready = !f.enabled || f.windows.length > 0;
    return `<div class="pb-probe ms" role="dialog" aria-modal="true" data-ms data-t="pb-schedule" data-t-id="${escapeHtml(f.key)}" data-t-state="${f.enabled ? "on" : "off"}">
      <div class="pb-probe-box ms-box">
        <header class="pb-probe-head"><b>⏱ ${escapeHtml(t("pbSchedTitle", { model: f.title }))}</b>${close}</header>
        <label class="ms-switch"><input type="checkbox" data-ms-enabled data-t="pb-schedule-enabled"${f.enabled ? " checked" : ""}> ${escapeHtml(t("pbSchedEnabled"))}</label>
        <p class="ms-zone${zone?.known ? "" : " bad"}" data-t="pb-schedule-zone">${escapeHtml(zoneLine)}</p>
        ${this.savedHtml()}
        ${this.gridHtml(clock, here)}
        <p class="ms-hint">${escapeHtml(t("pbSchedHint"))}</p>
        <h4>${escapeHtml(t("pbSchedWindows"))}</h4>
        ${this.windowsHtml(clock)}
        <button class="pb-add ms-add" type="button" data-ms-add data-t="pb-schedule-add">＋ ${escapeHtml(t("pbSchedAddWindow"))}</button>
        ${f.cell ? `<p class="ms-note" data-t="pb-schedule-cell-note">${escapeHtml(t("pbSchedCellNote"))}</p>` : ""}
        ${ready ? "" : `<p class="ms-note bad" data-t="pb-schedule-needs-window">${escapeHtml(t("pbSchedNeedsWindow"))}</p>`}
        <footer class="ms-foot">
          <button class="pb-tool" type="button" data-ms-close>${escapeHtml(t("cancel"))}</button>
          <button class="pb-add ms-save" type="button" data-ms-save data-t="pb-schedule-save"${ready && !f.busy ? "" : " disabled"}>${escapeHtml(t("save"))}</button>
        </footer>
      </div>
    </div>`;
  }

  // What the saved schedule says now, in the controller's words: nothing for a model with none.
  savedHtml() {
    const entry = this.entry(this.form.key);
    if (!entry) return "";
    const now = Number(this.schedules().now || this.now());
    const clock = this.clock();
    let word;
    if (!entry.enabled) word = t("pbSchedOff");
    else if (entry.open) word = entry.until ? t("pbSchedNowOpen", { time: clock.when(entry.until, now) }) : t("pbSchedNowAlways");
    else word = entry.opensAt ? t("pbSchedNowClosed", { time: clock.when(entry.opensAt, now) }) : t("pbSchedClosed");
    return `<p class="ms-now" data-t="pb-schedule-now" data-t-state="${!entry.enabled ? "off" : entry.open ? "open" : "closed"}">${escapeHtml(word)}</p>`;
  }

  // The week as hours: a row a day, Monday first, an hour a cell — full, part or empty — and the
  // caravan's hour now marked.
  gridHtml(clock, here) {
    const mask = this.painting?.mask || WeekWindows.mask(this.form.windows);
    const hours = Array.from({ length: 24 }, (_, h) => `<span class="ms-hour">${h}</span>`).join("");
    const rows = Array.from({ length: 7 }, (_, d) => {
      const cells = Array.from({ length: 24 }, (_, h) => {
        const open = WeekWindows.share(mask, d, h);
        const look = open === 60 ? " full" : open ? " part" : "";
        const nowMark = d === here.day && h === here.hour ? " now" : "";
        const title = `${clock.dayName(d)} ${String(h).padStart(2, "0")}:00–${String((h + 1) % 24).padStart(2, "0")}:00`;
        return `<span class="ms-cell${look}${nowMark}" data-ms-cell="${d}:${h}" title="${escapeHtml(title)}"></span>`;
      }).join("");
      return `<span class="ms-day">${escapeHtml(clock.dayName(d))}</span>${cells}`;
    }).join("");
    return `<div class="ms-grid${this.form.enabled ? "" : " off"}" data-t="pb-schedule-grid"><span class="ms-corner"></span>${hours}${rows}</div>`;
  }

  windowsHtml(clock) {
    const f = this.form;
    if (!f.windows.length) return `<p class="ms-empty" data-t="pb-schedule-no-windows">${escapeHtml(t("pbSchedNoWindows"))}</p>`;
    const rows = f.windows.map((w, i) => {
      const every = !w.days?.length;
      const days = Array.from({ length: 7 }, (_, d) => {
        const on = every || w.days.includes(d);
        return `<button class="ms-daybtn${on ? " on" : ""}" type="button" data-ms-day="${i}:${d}" aria-pressed="${on}">${escapeHtml(clock.dayName(d))}</button>`;
      }).join("");
      return `<li class="ms-window" data-ms-window="${i}" data-t="pb-schedule-window">
        <span class="ms-days">${days}</span>
        <input class="ms-time" type="time" step="60" data-ms-from="${i}" value="${escapeHtml(String(w.from))}" aria-label="${escapeHtml(t("pbSchedFrom"))}">
        <span aria-hidden="true">–</span>
        <input class="ms-time" type="time" step="60" data-ms-to="${i}" value="${escapeHtml(String(w.to))}" aria-label="${escapeHtml(t("pbSchedTo"))}">
        <button class="pb-tool del" type="button" data-ms-remove="${i}" title="${escapeHtml(t("pbSchedRemoveWindow"))}" aria-label="${escapeHtml(t("pbSchedRemoveWindow"))}">✕</button>
      </li>`;
    }).join("");
    return `<ul class="ms-windows">${rows}</ul>`;
  }

  // ── what the operator does ──────────────────────────────────────────

  // A click the window owns: true when it was one of its buttons (the board asks first).
  click(el) {
    if (el.hasAttribute("data-ms-open")) {
      this.open(el.dataset.msOpen, el.dataset.msTitle);
      return true;
    }
    if (!this.form) return false;
    if (el.hasAttribute("data-ms-close")) return this.close();
    if (el.hasAttribute("data-ms-save")) { this.save(); return true; }
    if (el.hasAttribute("data-ms-add")) {
      this.form.windows.push({ days: [], from: "09:00", to: "18:00" });
      this.redraw();
      return true;
    }
    if (el.hasAttribute("data-ms-remove")) {
      this.form.windows.splice(Number(el.dataset.msRemove), 1);
      this.redraw();
      return true;
    }
    if (el.hasAttribute("data-ms-day")) {
      const [i, d] = el.dataset.msDay.split(":").map(Number);
      const w = this.form.windows[i];
      if (!w) return true;
      // No days is every day: the first day taken away leaves the other six.
      const days = w.days?.length ? [...w.days] : [0, 1, 2, 3, 4, 5, 6];
      w.days = days.includes(d) ? days.filter((x) => x !== d) : [...days, d].sort((a, b) => a - b);
      // A window of no day opens nothing: it goes, rather than reading as every day.
      if (!w.days.length) this.form.windows.splice(i, 1);
      else if (w.days.length === 7) w.days = [];
      this.redraw();
      return true;
    }
    return false;
  }

  // The switch, and a window's exact times.
  change(el) {
    if (!this.form) return false;
    if (el.hasAttribute("data-ms-enabled")) {
      this.form.enabled = !!el.checked;
      this.redraw();
      return true;
    }
    const at = el.hasAttribute("data-ms-from") ? ["from", el.dataset.msFrom] : el.hasAttribute("data-ms-to") ? ["to", el.dataset.msTo] : null;
    if (!at) return false;
    const w = this.form.windows[Number(at[1])];
    // A time the field could not give (a half-typed one) leaves the window as it was.
    if (w && WeekWindows.minutes(el.value) !== null) w[at[0]] = WeekWindows.hhmm(WeekWindows.minutes(el.value));
    this.redraw();
    return true;
  }

  // The pointer pressed on an hour: it opens a closed or part-open hour and closes an open one,
  // and so does every hour it passes over until let go (`over`, `release`).
  press(event) {
    const cell = event.target?.closest?.("[data-ms-cell]");
    if (!cell || !this.form) return false;
    event.preventDefault?.();
    const [d, h] = cell.dataset.msCell.split(":").map(Number);
    const mask = WeekWindows.mask(this.form.windows);
    this.painting = { open: WeekWindows.share(mask, d, h) < 60, mask };
    this.paint(cell, d, h);
    return true;
  }

  over(event) {
    if (!this.painting) return false;
    const cell = event.target?.closest?.("[data-ms-cell]");
    if (!cell) return false;
    const [d, h] = cell.dataset.msCell.split(":").map(Number);
    this.paint(cell, d, h);
    return true;
  }

  // One hour painted: in the week, and on the cell itself at once — the window is drawn anew only
  // when the pointer lets go, so a long stroke does not redraw at every hour.
  paint(cell, d, h) {
    WeekWindows.paint(this.painting.mask, d, h, this.painting.open);
    cell.classList?.remove("part");
    cell.classList?.toggle("full", this.painting.open);
  }

  release() {
    if (!this.painting) return false;
    this.form.windows = WeekWindows.fromMask(this.painting.mask);
    this.painting = null;
    this.redraw();
    return true;
  }

  async save() {
    const f = this.form;
    if (!f || f.busy || (f.enabled && !f.windows.length)) return null;
    f.busy = true;
    this.redraw();
    let res;
    try {
      res = await this.call("/api/models/schedule", { method: "POST",
        body: JSON.stringify({ model: f.key, schedule: { enabled: f.enabled, windows: f.windows } }) });
    } catch (err) {
      f.busy = false;
      this.redraw();
      this.notify(err.message);
      return null;
    }
    this.form = null;
    this.apply(res?.topology);
    this.notify(t("pbSchedSaved", { model: f.title }));
    return res;
  }
}
