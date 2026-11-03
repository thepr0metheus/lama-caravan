// The caravan's parts (static/css/ui.css), step 0 of the screens' redesign: the button, the switch, the segmented choice,
// the filter pill, the badge, the status band, the row, the meter, the lane of a memory map, the tabs, the address, the "⋯"
// menu and the window frame (a window's, or a page's own head). Every screen
// draws them through these classes, so a part looks, reads and behaves the same wherever it stands — its markup and its
// accessibility live in one place. A part decides nothing about what it shows: the caller hands it its words, already
// translated, and the attributes its handlers bind by; the part decides only how it is drawn. A kind it does not know is
// refused, not guessed: the kinds are the code's, never the data's, and a guessed look would hide the mistake.
import { escapeHtml } from "./utils.js";

/** What every part shares: an attribute written only when it has a value, and the refusal of an unknown kind. */
class Part {
  static attr(name, value) {
    return value === "" || value === null || value === undefined ? "" : ` ${name}="${escapeHtml(value)}"`;
  }

  static kind(kinds, kind, part) {
    if (!kinds.includes(kind)) throw new Error(`${part}: no kind "${kind}" (${kinds.join(", ")})`);
    return kind;
  }

  /** The caller's own attributes (its data-* for binding, its data-t for tests), as it wrote them. */
  static extra(attrs) {
    const a = String(attrs || "").trim();
    return a ? ` ${a}` : "";
  }
}

/** The icons the parts draw: one stroke set, so the same action wears the same mark on every screen. */
export class Icon {
  static PATHS = {
    more: '<path d="M3 8h.01M8 8h.01M13 8h.01"></path>',
    close: '<path d="M3.5 3.5l9 9M12.5 3.5l-9 9"></path>',
    plus: '<path d="M8 3v10M3 8h10"></path>',
    back: '<path d="M10 3L5 8l5 5"></path>',
    warn: '<path d="M8 2l6.5 11.5h-13z"></path><path d="M8 6.5v3.2M8 11.6v.1"></path>',
    copy: '<rect x="5" y="5" width="8" height="8" rx="1.5"></rect><path d="M3 10.5V4a1 1 0 0 1 1-1h6.5"></path>',
  };

  static svg(name, size = 16) {
    Part.kind(Object.keys(Icon.PATHS), name, "Icon");
    const width = name === "more" ? 2.4 : 1.8;
    return `<svg width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="${width}"`
      + ` stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${Icon.PATHS[name]}</svg>`;
  }
}

/**
 * A button. Kinds: plain; main — one to an area; quiet — a word with no frame; danger — in a "⋯" menu, asking first; halt —
 * the main button that stops (main and danger at once); icon — an icon alone, which then needs a label. The words say what
 * happens; an icon helps them, except on "⋯" and "✕".
 */
export class Button extends Part {
  static KINDS = ["plain", "main", "quiet", "danger", "halt", "icon"];
  static CLASSES = {
    plain: "ui-btn", main: "ui-btn ui-btn--main", quiet: "ui-btn ui-btn--quiet", danger: "ui-btn ui-btn--danger",
    halt: "ui-btn ui-btn--main ui-btn--danger", icon: "ui-btn ui-btn--icon",
  };

  constructor({ kind = "plain", text = "", icon = "", label = "", title = "", attrs = "", disabled = false } = {}) {
    super();
    this.kind = Part.kind(Button.KINDS, kind, "Button");
    this.text = String(text ?? "");
    this.icon = icon ? Icon.svg(icon, kind === "icon" ? 16 : 14) : "";
    this.label = String(label || "");
    if (kind === "icon" && !this.label) throw new Error("Button: an icon alone needs a label");
    if (kind !== "icon" && !this.text) throw new Error("Button: needs its words");
    this.title = String(title || "");
    this.attrs = attrs;
    this.disabled = !!disabled;
  }

  html() {
    return `<button type="button" class="${Button.CLASSES[this.kind]}"${Part.attr("aria-label", this.label)}`
      + `${Part.attr("title", this.title)}${Part.extra(this.attrs)}${this.disabled ? " disabled" : ""}>`
      + `${this.icon}${this.kind === "icon" ? "" : escapeHtml(this.text)}</button>`;
  }
}

/** The on/off of a cell or an engine: it says its state (role="switch"); busy while the change is on its way. */
export class Switch extends Part {
  constructor({ on = false, busy = false, label = "", title = "", attrs = "", disabled = false } = {}) {
    super();
    if (!label) throw new Error("Switch: needs a label");
    Object.assign(this, { on: !!on, busy: !!busy, label: String(label), title: String(title || ""), attrs, disabled: !!disabled });
  }

  html() {
    return `<button type="button" class="ui-switch${this.busy ? " is-busy" : ""}" role="switch" aria-checked="${this.on}"`
      + `${Part.attr("aria-label", this.label)}${Part.attr("title", this.title)}${Part.extra(this.attrs)}`
      + `${this.disabled ? " disabled" : ""}></button>`;
  }
}

/** One of a few, side by side: each option says whether it is the chosen one (aria-pressed). */
export class Seg extends Part {
  constructor({ label = "", options = [] } = {}) {
    super();
    if (!label) throw new Error("Seg: needs a label");
    this.label = String(label);
    this.options = Array.isArray(options) ? options : [];
  }

  html() {
    const opts = this.options.map((o) => `<button type="button" class="ui-seg-opt" aria-pressed="${!!o.on}"${Part.extra(o.attrs)}>`
      + `${escapeHtml(o.text ?? "")}${Seg.count(o.count)}</button>`).join("");
    return `<div class="ui-seg" role="group"${Part.attr("aria-label", this.label)}>${opts}</div>`;
  }

  static count(n) {
    return n === "" || n === null || n === undefined ? "" : ` <span class="ui-count">${escapeHtml(n)}</span>`;
  }
}

/** A filter that is on or off. */
export class Pill extends Part {
  constructor({ text = "", count = "", on = false, attrs = "" } = {}) {
    super();
    if (!text) throw new Error("Pill: needs its words");
    Object.assign(this, { text: String(text), count, on: !!on, attrs });
  }

  html() {
    return `<button type="button" class="ui-pill" aria-pressed="${this.on}"${Part.extra(this.attrs)}>${escapeHtml(this.text)}`
      + `${Seg.count(this.count)}</button>`;
  }
}

/** An exception worth a word — autostart, an old server, a start that will not fit. The normal gets none. */
export class Badge extends Part {
  static TONES = ["idle", "good", "busy", "bad", "act"];

  constructor({ tone = "idle", text = "", title = "" } = {}) {
    super();
    this.tone = Part.kind(Badge.TONES, tone, "Badge");
    if (!text) throw new Error("Badge: needs its words");
    this.text = String(text);
    this.title = String(title || "");
  }

  html() {
    const tone = this.tone === "idle" ? "" : ` ui-badge--${this.tone}`;
    return `<span class="ui-badge${tone}"${Part.attr("title", this.title)}>${escapeHtml(this.text)}</span>`;
  }
}

/**
 * What an object does now, in one line under its name: the tone (good — it works; busy — on its way; idle — it holds nothing;
 * bad — it failed), the title, a second line (HTML: it may carry a live figure) and the one main button (HTML). `inline`: the
 * same said in the line of a head beside the object's name (variant В of a machine's page), with no frame of its own.
 */
export class Band extends Part {
  static TONES = ["good", "busy", "idle", "bad"];

  constructor({ tone = "idle", title = "", sub = "", action = "", attrs = "", inline = false } = {}) {
    super();
    this.tone = Part.kind(Band.TONES, tone, "Band");
    if (!title) throw new Error("Band: needs a title");
    Object.assign(this, { title: String(title), sub: String(sub || ""), action: String(action || ""), attrs, inline: !!inline });
  }

  html() {
    const tone = `${this.tone === "idle" ? "" : ` ui-band--${this.tone}`}${this.inline ? " ui-band--inline" : ""}`;
    return `<div class="ui-band${tone}" role="status"${Part.extra(this.attrs)}><span class="ui-band-dot" aria-hidden="true"></span>`
      + `<div class="ui-band-text"><strong class="ui-band-title">${escapeHtml(this.title)}</strong>`
      + `${this.sub ? `<span class="ui-band-sub">${this.sub}</span>` : ""}</div>${this.action}</div>`;
  }
}

/**
 * A row of any list: its state (HTML — a switch, a dot), its name over one line of facts, its figure on the right with an
 * exception under it, and a tail (HTML — a badge, a button). `open`: the attributes of the name when the name opens the
 * object (it is a button then, labelled by `label`); `live` tints a row whose object works now. `cols` sets the columns
 * for a list whose rows carry other parts.
 */
export class Row extends Part {
  static NOTES = ["", "busy", "bad"];

  constructor({ state = "", title = "", facts = "", value = "", note = "", noteTone = "", tail = "", live = false, open = "",
                label = "", attrs = "", cols = "" } = {}) {
    super();
    if (!title) throw new Error("Row: needs a title");
    this.noteTone = Part.kind(Row.NOTES, noteTone, "Row note");
    if (open && !label) throw new Error("Row: a name that opens needs a label");
    Object.assign(this, { state: String(state || ""), title: String(title), facts: String(facts || ""), value: String(value ?? ""),
                          note: String(note || ""), tail: String(tail || ""), live: !!live, open: String(open || ""),
                          label: String(label || ""), attrs, cols: String(cols || "") });
  }

  html() {
    const inner = `<span class="ui-row-title">${escapeHtml(this.title)}</span>`
      + `${this.facts ? `<span class="ui-row-facts">${escapeHtml(this.facts)}</span>` : ""}`;
    const name = this.open
      ? `<button type="button" class="ui-row-name"${Part.attr("aria-label", this.label)} ${this.open}>${inner}</button>`
      : `<div class="ui-row-name">${inner}</div>`;
    const note = this.note ? `<span class="ui-row-note${this.noteTone ? ` ui-row-note--${this.noteTone}` : ""}">${escapeHtml(this.note)}</span>` : "";
    const value = this.value ? `<span class="ui-row-value">${escapeHtml(this.value)}</span>` : "";
    return `<div class="ui-row${this.live ? " ui-row--live" : ""}"${this.cols ? Part.attr("style", `--ui-row-cols: ${this.cols}`) : ""}`
      + `${Part.extra(this.attrs)}><div class="ui-row-state">${this.state}</div>${name}`
      + `<div class="ui-row-figure">${value}${note}</div><div class="ui-row-tail">${this.tail}</div></div>`;
  }
}

/**
 * How full a card, the RAM or a disk is, and who holds it. `parts`: [{value, series 1–6 | kind "other" | "estimate" |
 * "estimate-cache", title}] in the meter's own unit — a colour per cell, hatching for the other processes, dashes for an
 * estimate ("this is where it would go"), paler dashes for the cache and buffers of one (1.3.635: the owner asked to see where
 * the model is and where its cache). The segments never add up past the whole. While the total is not known there is no bar: an empty bar would
 * read as a free card; the caller says why in the foot.
 */
export class Meter extends Part {
  static KINDS = ["other", "estimate", "estimate-cache"];

  constructor({ label = "", side = "", value = "", unit = "", total = null, parts = [], foot = "", tile = true, attrs = "" } = {}) {
    super();
    if (!label) throw new Error("Meter: needs a label");
    Object.assign(this, { label: String(label), side: String(side || ""), value: String(value ?? ""), unit: String(unit || ""),
                          total: Number(total), parts: Array.isArray(parts) ? parts : [], foot: String(foot || ""), tile: !!tile, attrs });
  }

  /** The parts as shares of the total, in percent, cut where they would pass it — the rule a meter and a lane draw by; null
   *  while the total is not known. */
  static cut(total, parts) {
    if (!(Number(total) > 0)) return null;
    let left = 100;
    const out = [];
    for (const part of Array.isArray(parts) ? parts : []) {
      const v = Number(part?.value);
      if (!(v > 0) || left <= 0) continue;
      const width = Math.min(left, (v / Number(total)) * 100);
      left -= width;
      out.push({ part, width: Math.round(width * 100) / 100 });
    }
    return out;
  }

  /** A part's look, as the suffix of its class: hatched or dashed by its kind, else its series' colour (1–6, the first plain). */
  static look(p, part) {
    if (p.kind) return `--${Part.kind(Meter.KINDS, p.kind, `${part} part`)}`;
    const s = Number(p.series || 1);
    if (!(Number.isInteger(s) && s >= 1 && s <= 6)) throw new Error(`${part} part: no series "${p.series}" (1–6)`);
    return s > 1 ? `--s${s}` : "";
  }

  /** The segments, in percent of the total, cut where they would pass it; null while the total is not known. */
  segments() {
    const cut = Meter.cut(this.total, this.parts);
    if (cut === null) return null;
    return cut.map(({ part, width }) => {
      const look = Meter.look(part, "Meter");
      return { cls: `ui-meter-seg${look ? ` ui-meter-seg${look}` : ""}`, width, title: String(part.title || "") };
    });
  }

  html() {
    const segs = this.segments();
    const figure = this.value
      ? `<div class="ui-meter-figure"><span class="ui-meter-value">${escapeHtml(this.value)}</span>`
        + `${this.unit ? `<span class="ui-meter-unit">${escapeHtml(this.unit)}</span>` : ""}</div>` : "";
    const bar = segs === null ? ""
      : `<div class="ui-meter-bar" role="img"${Part.attr("aria-label", [this.label, this.value, this.unit].filter(Boolean).join(" "))}>`
        + `${segs.map((s) => `<span class="${s.cls}" style="width: ${s.width}%"${Part.attr("title", s.title)}></span>`).join("")}</div>`;
    return `<div class="ui-meter${this.tile ? " ui-tile" : ""}"${Part.extra(this.attrs)}><div class="ui-meter-head">`
      + `<span class="ui-meter-label">${escapeHtml(this.label)}</span>${this.side ? `<span class="ui-meter-side">${escapeHtml(this.side)}</span>` : ""}`
      + `</div>${figure}${bar}${this.foot ? `<span class="ui-meter-foot">${escapeHtml(this.foot)}</span>` : ""}</div>`;
  }
}

/**
 * A lane of a memory map (variant В of a machine's page, the owner's choice of 2026-10-25): a card or the RAM as one wide bar,
 * each holder a block of its share — a cell in its colour, its name and figure inside while the block is wide enough to carry
 * them, a button when choosing it means something (`pick`: the attributes it is bound by; `on`: the chosen one); the other
 * processes hatched; an estimate dashed ("this is where it would go"), its cache in paler dashes — and, at the right of its
 * head, how much is free. The
 * shares and looks are the meter's (Meter.cut, Meter.look). While the total is not known there is no bar: an empty one would read
 * as a free card; the foot says why.
 */
export class Lane extends Part {
  static KINDS = Meter.KINDS;
  /** The share of the lane, in percent, a block needs to carry its words: a narrower one says them in its hover only. */
  static WIDE = 12;
  /** On a rack: the share of the row, in percent, a block needs for its figure, for the figure's number alone, and for the word of other
   *  processes. Below that it says them in its hover only: on the owner's machine "system" read "sy…", and the handle covered a figure's end. */
  static ROOM = { figure: 22, short: 12, word: 16 };

  /**
   * On a rack (the memory map of a machine: `rack` given, machine-head.js MachineRack) the lane is one thin row of a column of lanes on
   * one scale: its name, how much is free, its bar, and the lines that sew one cell's pieces together. What lies on it is said once for
   * the whole rack, by the list beside it (RackLegend), and block by block in the hover.
   * @param rack {bar, slots}: the share of the row this bar takes, in percent; how many lines run down between the lanes
   * @param links [{slot, up, down, here, from, owner, shown, series|kind}]: the line of a cell whose pieces lie on several lanes: it comes from
   *   above and goes on below, and where it has a piece here it leaves the bar at `from` percent of it, where the bar's free part starts.
   *   Only the lines of what is planned, chosen (`shown`) or under the pointer are drawn: all of them at once were a thicket
   * @param grips [{at, on, title, attrs}]: a handle at `at` percent of the bar: `on` it holds a piece, else it can be given one
   * @param metrics [{word, cls, attrs, valAttrs, sparkAttrs}]: the device's own figures at the end of the row, a cell per column of the
   *   rack; no `word` and no `valAttrs` leaves that cell empty (the RAM has no power)
   * @param pic HTML: what stands before its label, a picture of the device
   */
  constructor({ label = "", side = "", free = "", total = null, blocks = [], foot = "", attrs = "", rack = null, links = [], grips = [], metrics = [], pic = "" } = {}) {
    super();
    if (!label) throw new Error("Lane: needs a label");
    Object.assign(this, { label: String(label), side: String(side || ""), free: String(free || ""), total: Number(total), pic: String(pic || ""),
                          blocks: Array.isArray(blocks) ? blocks : [], foot: String(foot || ""), attrs, rack,
                          links: Array.isArray(links) ? links : [], grips: Array.isArray(grips) ? grips : [], metrics: Array.isArray(metrics) ? metrics : [] });
  }

  /** What a block carries inside: its name and figure while it is wide enough, else nothing — its hover says them. On a rack, whose list
   *  names what lies on it, a block carries only its figure, by its share of the row (`bar`: the share the whole bar takes); other
   *  processes have no row in that list when they are small, and carry a word. */
  static inner(part, width, bar = null) {
    if (bar === null) {
      return width >= Lane.WIDE && (part.name || part.figure)
        ? `${part.name ? `<strong>${escapeHtml(part.name)}</strong>` : ""}${part.figure ? `<span>${escapeHtml(part.figure)}</span>` : ""}` : "";
    }
    const room = (width * Number(bar)) / 100;
    if (part.kind === "other") return room >= Lane.ROOM.word && part.short ? `<strong>${escapeHtml(part.short)}</strong>` : "";
    const said = room >= Lane.ROOM.figure ? part.figure : room >= Lane.ROOM.short ? part.short : "";
    return said ? `<span>${escapeHtml(said)}</span>` : "";
  }

  static block({ part, width }, bar = null) {
    const look = Meter.look(part, "Lane");
    const cls = `ui-lane-blk${look ? ` ui-lane-blk${look}` : ""}${part.on ? " is-on" : ""}`;
    const words = Lane.inner(part, width, bar);
    const style = ` style="width: ${width}%"`;
    const title = String(part.title || "");
    const owner = part.owner ? Part.attr("data-lane-owner", part.owner) : "";
    if (part.pick) {
      return `<button type="button" class="${cls}"${style} aria-pressed="${!!part.on}"${Part.attr("aria-label", title)}`
        + `${Part.attr("title", title)}${owner}${Part.extra(part.pick)}>${words}</button>`;
    }
    return `<span class="${cls}"${style}${Part.attr("title", title)}${owner}>${words}</span>`;
  }

  /** A line's own classes and owner: one for its piece between the lanes and for where it leaves the bar. */
  static lineAttrs(link, cls, states = "") {
    const look = Meter.look(link, "Lane link");
    return `class="${cls} ui-lane-c${look ? ` ui-lane-c${look}` : ""}${link.shown ? " is-shown" : ""}${states}"${link.owner ? Part.attr("data-lane-owner", link.owner) : ""}`;
  }

  /** A piece of a cell's line between the lanes, and where it leaves the bar. */
  static link(link) {
    return `<i ${Lane.lineAttrs(link, "ui-lane-link", `${link.up ? " is-up" : ""}${link.down ? " is-down" : ""}${link.here ? " is-here" : ""}`)} style="--lane-slot: ${Number(link.slot) || 0}"></i>`;
  }

  static lead(link) {
    return `<i ${Lane.lineAttrs(link, "ui-lane-lead")} style="--lane-slot: ${Number(link.slot) || 0}; --lane-from: ${Number(link.from) || 0}"></i>`;
  }

  /** A handle on the bar: a button of its own, moved by the pointer or the arrow keys (its caller binds it by `attrs`). */
  static grip(grip) {
    return `<button type="button" class="ui-lane-grip${grip.on ? " is-on" : ""}" style="--lane-grip: ${Number(grip.at) || 0}"`
      + `${Part.attr("title", grip.title)}${Part.attr("aria-label", grip.title)}${Part.extra(grip.attrs)}></button>`;
  }

  /** A figure of the row: its value and its little chart, which the monitor's tick fills (charts.js). */
  static metric(metric) {
    if (!metric.valAttrs) return '<span class="ui-lane-metric"></span>';
    return `<span class="ui-lane-metric${metric.cls ? ` ${metric.cls}` : ""}"${Part.extra(metric.attrs)}><span class="ui-lane-metric-val"${Part.extra(metric.valAttrs)}>${escapeHtml(metric.word ?? "")}</span>`
      + `<span class="ui-lane-metric-spark"${Part.extra(metric.sparkAttrs)}></span></span>`;
  }

  /** The heads of the rack's columns: the same grid as a lane's row, so that they stand over the figures. */
  static heads(words, slots) {
    return `<div class="ui-lane-heads" style="--lane-slots: ${Number(slots) || 0}"><div class="ui-lane-metrics">${words.map((word) => `<span class="ui-lane-metric">${escapeHtml(word)}</span>`).join("")}</div></div>`;
  }

  html() {
    const cut = Meter.cut(this.total, this.blocks);
    const share = this.rack ? Number(this.rack.bar ?? 100) : null;
    const bar = cut === null ? "" : `<div class="ui-lane-bar">${cut.map((b) => Lane.block(b, share)).join("")}</div>`;
    const name = `${this.pic}<span class="ui-lane-label">${escapeHtml(this.label)}</span>`
      + `${this.side ? `<span class="ui-lane-side"${this.rack ? Part.attr("title", this.side) : ""}>${escapeHtml(this.side)}</span>` : ""}`;
    const free = this.free ? `<span class="ui-lane-free">${escapeHtml(this.free)}</span>` : "";
    const foot = this.foot ? `<span class="ui-lane-foot">${escapeHtml(this.foot)}</span>` : "";
    if (!this.rack) return `<div class="ui-lane"${Part.extra(this.attrs)}><div class="ui-lane-head">${name}${free}</div>${bar}${foot}</div>`;
    const leads = cut === null ? "" : this.links.filter((l) => l.here).map((l) => Lane.lead(l)).join("");
    const style = `--lane-bar: ${share}%; --lane-slots: ${Number(this.rack.slots) || 0}`;
    return `<div class="ui-lane ui-lane--rack" style="${style}"${Part.extra(this.attrs)}><div class="ui-lane-head">${name}</div>${free}`
      + `<div class="ui-lane-line">${bar}${leads}${cut === null ? "" : this.grips.map((g) => Lane.grip(g)).join("")}</div>${foot}`
      + `<div class="ui-lane-spine">${this.links.map((l) => Lane.link(l)).join("")}</div>`
      + `${this.metrics.length ? `<div class="ui-lane-metrics">${this.metrics.map((m) => Lane.metric(m)).join("")}</div>` : ""}</div>`;
  }
}

/**
 * The list beside a rack of lanes (the owner's choice П3, 2026-11-02: the names beside each lane read as a heap, and one model on four
 * cards was said four times): each holder once, what it holds in all and where. A row of a cell is a button that chooses it; `owner` ties
 * a row to its blocks and its line, so that a pointer on either lights the other (machine-head.js MachinePick.light).
 */
export class RackLegend extends Part {
  /**
   * @param rows [{name, figure, where, speed, owner, title, series|kind, on, pick, attrs}]
   * @param empty what it says when nothing holds anything
   * @param heads the words over the columns: [figure's, speed's]
   */
  constructor({ rows = [], empty = "", heads = [] } = {}) {
    super();
    Object.assign(this, { rows: Array.isArray(rows) ? rows : [], empty: String(empty || ""), heads: Array.isArray(heads) ? heads : [] });
  }

  static row(row) {
    const look = Meter.look(row, "Legend row");
    const cls = `ui-legend-row ui-lane-c${look ? ` ui-lane-c${look}` : ""}${row.on ? " is-on" : ""}`;
    const words = `<span class="ui-lane-dot" aria-hidden="true"></span><strong class="ui-legend-name">${escapeHtml(row.name || "")}</strong>`
      + `<span class="ui-legend-figure">${escapeHtml(row.figure || "")}</span><span class="ui-legend-where">${escapeHtml(row.where || "")}</span>`
      + `<span class="ui-legend-speed">${escapeHtml(row.speed || "")}</span>`;
    const owner = row.owner ? Part.attr("data-lane-owner", row.owner) : "";
    return row.pick
      ? `<button type="button" class="${cls}" aria-pressed="${!!row.on}"${Part.attr("title", row.title)}${owner}${Part.extra(row.pick)}>${words}</button>`
      : `<div class="${cls}"${Part.attr("title", row.title)}${owner}${Part.extra(row.attrs)}>${words}</div>`;
  }

  html() {
    const body = this.rows.length ? this.rows.map((row) => RackLegend.row(row)).join("")
      : `<p class="ui-legend-empty">${escapeHtml(this.empty)}</p>`;
    const heads = this.heads.length && this.rows.length ? `<div class="ui-legend-row ui-legend-heads"><span></span><span></span><span class="ui-legend-figure">${escapeHtml(this.heads[0] ?? "")}</span><span></span>`
      + `<span class="ui-legend-speed">${escapeHtml(this.heads[1] ?? "")}</span></div>` : "";
    return `<div class="ui-legend">${heads}${body}</div>`;
  }
}

/** The tabs of a window or a page section; the chosen one says so (aria-selected). `cls`: the frame's own place for them. */
export class Tabs extends Part {
  constructor({ label = "", tabs = [], cls = "" } = {}) {
    super();
    if (!label) throw new Error("Tabs: needs a label");
    Object.assign(this, { label: String(label), tabs: Array.isArray(tabs) ? tabs : [], cls: String(cls || "") });
  }

  html() {
    const tabs = this.tabs.map((t) => `<button type="button" role="tab" class="ui-tab" aria-selected="${!!t.on}"${Part.extra(t.attrs)}>`
      + `${escapeHtml(t.text ?? "")}${t.count === "" || t.count === null || t.count === undefined ? "" : `<span class="ui-tab-count">${escapeHtml(t.count)}</span>`}`
      + `</button>`).join("");
    return `<div class="ui-tabs${this.cls ? ` ${this.cls}` : ""}" role="tablist"${Part.attr("aria-label", this.label)}>${tabs}</div>`;
  }
}

/** An object's address that copies itself: the caller binds the copy by `attrs`. */
export class Addr extends Part {
  constructor({ text = "", label = "", attrs = "" } = {}) {
    super();
    if (!text) throw new Error("Addr: needs the address");
    Object.assign(this, { text: String(text), label: String(label || ""), attrs });
  }

  html() {
    return `<button type="button" class="ui-addr"${Part.attr("title", this.label)}${Part.extra(this.attrs)}>`
      + `<span>${escapeHtml(this.text)}</span>${Icon.svg("copy", 12)}</button>`;
  }
}

/**
 * The "⋯" of an object: a button that opens what else can be done with it — what is rare, and what cannot be undone and asks
 * first (in red, `danger`). `items`: [{text, attrs, title, danger, disabled}], and "-" for a line between groups; an item
 * carries the attributes the board's listeners already bind by, so it does what the button it replaces did. The list opens
 * and closes by ui-menus.js (UiMenus): its button, Escape, a click outside it, an item chosen.
 */
export class Menu extends Part {
  constructor({ label = "", items = [], attrs = "" } = {}) {
    super();
    if (!label) throw new Error("Menu: needs a label");
    this.items = (Array.isArray(items) ? items : []).map((item) => {
      if (item === "-") return item;
      if (!item || !item.text) throw new Error("Menu item: needs its words");
      return item;
    });
    Object.assign(this, { label: String(label), attrs });
  }

  html() {
    const items = this.items.map((item) => (item === "-" ? '<div class="ui-menu-sep" role="separator"></div>'
      : `<button type="button" role="menuitem" class="ui-menu-item${item.danger ? " ui-menu-item--danger" : ""}"`
        + `${Part.attr("title", item.title)}${Part.extra(item.attrs)}${item.disabled ? " disabled" : ""}>${escapeHtml(item.text)}</button>`)).join("");
    const toggle = new Button({ kind: "icon", icon: "more", label: this.label, attrs: 'data-ui-menu-toggle aria-haspopup="menu" aria-expanded="false"' });
    return `<div class="ui-menu"${Part.extra(this.attrs)}>${toggle.html()}`
      + `<div class="ui-menu-list" role="menu"${Part.attr("aria-label", this.label)} hidden>${items}</div></div>`;
  }
}

/**
 * The window frame: the passport (title, facts, an address, tools), the band, the tabs, the body and the foot that says what
 * is not applied. A machine's page, a cell's window, an engine and the new cell's steps are this frame. `band`, `tabs`,
 * `body`, `foot`, `addr`, `tools`: HTML from the other parts. `foot`: null for a frame with no foot; "" for its slot, empty
 * while nothing is pending. `kind`: a window's frame, or a page's own head — the same passport and band, without a window's
 * edge, the name the page's heading (`<h1>`).
 */
export class Frame extends Part {
  static TAGS = ["section", "div", "article"];
  static KINDS = ["window", "page"];

  constructor({ title = "", facts = "", addr = "", tools = "", band = "", tabs = "", body = "", foot = null, label = "", attrs = "", tag = "section",
                kind = "window" } = {}) {
    super();
    if (!title) throw new Error("Frame: needs a title");
    this.tag = Part.kind(Frame.TAGS, tag, "Frame tag");
    this.kind = Part.kind(Frame.KINDS, kind, "Frame");
    Object.assign(this, { title: String(title), facts: String(facts || ""), addr: String(addr || ""), tools: String(tools || ""),
                          band: String(band || ""), tabs: String(tabs || ""), body: String(body ?? ""), foot: foot === null ? null : String(foot),
                          label: String(label || ""), attrs });
  }

  html() {
    const page = this.kind === "page";
    const name = page ? "h1" : "strong";
    return `<${this.tag} class="ui-win${page ? " ui-win--page" : ""}"${Part.attr("aria-label", this.label)}${Part.extra(this.attrs)}>`
      + `<div class="ui-win-head"><div class="ui-win-id"><div class="ui-win-title-row"><${name} class="ui-win-title">${escapeHtml(this.title)}</${name}>`
      + `${this.facts ? `<span class="ui-win-facts">${escapeHtml(this.facts)}</span>` : ""}</div>${this.addr}</div>${this.tools}</div>`
      + `${this.band ? `<div class="ui-win-band">${this.band}</div>` : ""}${this.tabs}`
      + `${this.body ? `<div class="ui-win-body">${this.body}</div>` : ""}`
      + `${this.foot === null ? "" : `<div class="ui-win-foot">${this.foot}</div>`}</${this.tag}>`;
  }
}
