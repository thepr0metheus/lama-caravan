// Model stores on the /models page: the places models live — this controller's
// own directory and the libraries — whether each place is really there, and
// which of them the list below is showing.
// Data: /api/model-stores; adding and removing a library:
// /api/model-stores/add and /api/model-stores/remove.
//
// The panel draws two things: the list of places in the side column (every
// place with what it holds and how much room it has, and "All models" above
// them), and the summary over the model list (the chosen place's path, state
// and room; under "All models", every place side by side). Choosing a place is
// the panel's business, what the list then shows is the page's — the page
// hears of it through onScope and reads `scope`.
//
// The page never looks inside a store itself. The server does, from a child
// process with a deadline (caravan/admin/model_stores.py), so a dead NAS
// arrives here as the state "unknown" and is drawn as "not answering" — never
// as a spinner that does not end.
import { appConfirm } from "./dialogs.js";
import { t } from "./i18n.js";
import { api, escapeHtml, fmtGb, fmtSpace, toast } from "./utils.js";

// State → the tone of its chip, and → the key of its word. A state the server
// adds tomorrow falls through to "unknown", never to "ok".
const TONES = { ok: "good", "low-space": "warn", "read-only": "warn", foreign: "bad", "not-mounted": "bad", missing: "bad", unknown: "bad" };
const WORDS = { ok: "storeStateOk", "low-space": "storeStateLowSpace", "read-only": "storeStateReadOnly", foreign: "storeStateForeign", "not-mounted": "storeStateNotMounted", missing: "storeStateMissing", unknown: "storeStateUnknown" };
// Only these states come with numbers. A library that is not mounted would
// report the free space of the LOCAL disk its bare mount point sits on — the
// server does not send those numbers, and the page does not draw them either.
const MEASURED = new Set(["ok", "low-space", "read-only"]);
//: The scope that shows every place at once.
const ALL = "all";
// Library segments of the bar take these in turn; this disk is always the
// accent. Three are enough to tell neighbours apart, and they repeat past it.
const LIB_SEGMENTS = 3;

export class StoresPanel {
  static mount(root, opts = {}) {
    if (!root) return null;
    const panel = new StoresPanel(root, opts);
    panel.bind();
    panel.refresh();
    return panel;
  }

  constructor(root, opts = {}) {
    this.root = root;
    // The summary over the list; a page without one gets the places alone.
    this.summary = opts.summary || null;
    // null = not loaded yet, [] = loaded and empty: "…" and an empty list are
    // two different things on screen.
    this.stores = null;
    this.error = "";
    // Told after every answer: the move button on the same page needs the
    // libraries this panel measured.
    this.onChange = opts.onChange || null;
    // Told when another place is chosen: the list below shows that place.
    this.onScope = opts.onScope || null;
    // What the controller's own directory holds — counted by the tree on this
    // page, not measured again here. A library is walked by the server; this
    // disk is already listed file by file right below, and asking for it twice
    // would be a second number that can disagree with the first. The page
    // also counts the model families each place holds: they are folders of
    // the list it draws.
    this.local = null;
    // Changing where the models directory IS: the panel owns the pencil on
    // that place's summary, and the page owns what saving means.
    this.onSavePath = opts.onSavePath || null;
    this.editing = false;
    this.adding = false;
    // "all", or the id of the place the list shows.
    this.scope = ALL;
    // The markup last put on screen, to leave alone what did not change.
    this.drawn = { places: null, summary: null };
  }

  // The page hands over its own count after every drawing of the list — on
  // every letter typed into its name box too; render() leaves the markup alone
  // when the count did not change it.
  holds(local) {
    this.local = local && Number.isFinite(local.files)
      ? { files: local.files, size: local.size || 0, families: local.families || null } : null;
    this.render();
  }

  async refresh(force = false) {
    try {
      const res = await api(force ? "/api/model-stores?force=1" : "/api/model-stores");
      this.stores = (res && res.stores) || [];
      this.error = "";
    } catch (err) {
      this.error = String((err && err.message) || err);
    }
    // A chosen place that is gone — removed here or in another tab — hands
    // the list back to every place, instead of a summary of nothing.
    if (this.scope !== ALL && this.stores && !this.stores.some((s) => s.id === this.scope)) this.choose(ALL);
    this.render();
    if (this.onChange) this.onChange(this.stores);
  }

  choose(scope) {
    const next = scope === ALL || (this.stores || []).some((s) => s.id === scope) ? scope : ALL;
    if (next === this.scope) return;
    this.scope = next;
    this.editing = false;
    this.render();
    if (this.onScope) this.onScope(next);
  }

  render() {
    // Only what changed is replaced. A move redraws the page on every file
    // that arrives, and markup replaced under a pressed mouse button swallows
    // the click: the press lands on one element, the release on its copy.
    const places = this.places();
    const summary = this.summary ? this.summaryHtml() : "";
    // What is typed survives the redraw, for the same reason.
    const kept = this.typed();
    if (places !== this.drawn.places) this.root.innerHTML = places;
    if (this.summary && summary !== this.drawn.summary) this.summary.innerHTML = summary;
    if (this.summary && this.summary.dataset) this.summary.dataset.tId = this.scope;
    this.drawn = { places, summary };
    this.retype(kept);
  }

  nameOf(s) {
    return s.builtin ? t("storeLocalName") : (s.name || s.id);
  }

  static state(s) {
    return WORDS[s.state] ? s.state : "unknown";
  }

  // What a place holds: its own count for a library, the page's count for this
  // disk. An unmeasured place says nothing rather than zero — "0 models" and "I
  // could not look" are not the same sentence.
  held(s) {
    if (!MEASURED.has(StoresPanel.state(s))) return null;
    if (s.builtin) return this.local ? { files: this.local.files, size: this.local.size } : null;
    return Number.isFinite(s.files) ? { files: s.files, size: s.size || 0 } : null;
  }

  familiesOf(scope) {
    const n = this.local && this.local.families ? this.local.families[scope] : undefined;
    return Number.isFinite(n) ? n : null;
  }

  // How full a place is, in percent; null when it was not measured.
  static used(s) {
    if (!MEASURED.has(StoresPanel.state(s)) || !Number.isFinite(s.total) || s.total <= 0) return null;
    return Math.max(0, Math.min(100, Math.round(100 - (100 * (s.free || 0)) / s.total)));
  }

  // The state's word in its tone, with the reason in the tooltip. The one in
  // the list of places carries the hook; the summary's repeats it for the eye.
  chip(s, hooked = false) {
    const state = StoresPanel.state(s);
    const tip = s.detail ? ` title="${escapeHtml(s.detail)}"` : "";
    return `<span class="mdl-store-state ${TONES[state]}"${hooked ? ` data-t="models-store-state"` : ""}${tip}>${escapeHtml(t(WORDS[state]))}</span>`;
  }

  // ── The places, in the side column ──────────────────────────────────────

  places() {
    let body = `<p class="muted">…</p>`;
    if (this.error) body = `<p class="muted" data-t="models-stores-error">${escapeHtml(this.error)}</p>`;
    else if (this.stores) body = this.allEntry() + this.stores.map((s) => this.entry(s)).join("");
    return body + this.addEntry();
  }

  // Every place's bytes together: this disk as the page counted it, each
  // library as it was measured. Nothing until this disk is counted — a total
  // without its largest part would read as the whole.
  total() {
    if (!this.local) return null;
    return (this.stores || []).reduce((a, s) => a + (s.builtin ? 0 : ((this.held(s) || {}).size || 0)), this.local.size);
  }

  current(scope) {
    return this.scope === scope ? ` aria-current="true"` : "";
  }

  allEntry() {
    const size = this.total();
    return `<button class="mdl-place" type="button" data-scope="${ALL}" data-t="models-place-all"${this.current(ALL)}>`
      + `<span aria-hidden="true">🗂</span><span class="nm"><span>${escapeHtml(t("mdlAllModels"))}</span></span>`
      + `<span class="c">${size === null ? "" : escapeHtml(fmtGb(size))}</span></button>`;
  }

  // A place: name and state, what it holds, and how much room is left. A
  // healthy state is a dot (styled); any other says its word right there.
  entry(s) {
    const held = this.held(s);
    const used = StoresPanel.used(s);
    return `<button class="mdl-place" type="button" data-scope="${escapeHtml(s.id)}" data-t="models-store" data-t-id="${escapeHtml(s.id)}"`
      + ` data-state="${escapeHtml(StoresPanel.state(s))}"${this.current(s.id)}>`
      + `<span aria-hidden="true">${s.builtin ? "🏠" : "📚"}</span>`
      + `<span class="nm"><span>${escapeHtml(this.nameOf(s))}</span>${this.chip(s, true)}</span>`
      + `<span class="c" data-t="models-store-meta">${held && held.files ? escapeHtml(fmtGb(held.size)) : ""}</span>`
      + (used === null ? "" : this.bar(s, used)
        + `<span class="sub">${escapeHtml(t("storeFree", { free: fmtSpace(s.free || 0), total: fmtSpace(s.total) }))}</span>`)
      + `</button>`;
  }

  // The bar is how FULL the place is, so a glance answers "is there room"
  // without reading two numbers and dividing. It is a shape, not a verdict: a
  // disk 93% full with room to spare is still available, and painting it green
  // fought the word next to it while red would have argued with the same word
  // the other way. Only the state the server judged turns it amber.
  bar(s, used) {
    return `<span class="mdl-store-bar${s.state === "low-space" ? " low" : ""}" aria-hidden="true"><i style="width:${used}%"></i></span>`;
  }

  addEntry() {
    if (!this.adding) {
      return `<button class="mdl-place add" type="button" data-store-add-open data-t="models-store-add-open">`
        + `<span aria-hidden="true">＋</span><span>${escapeHtml(t("storeAdd"))}</span></button>`;
    }
    const hint = escapeHtml(t("storeAddPlaceholder"));
    return `<div class="mdl-path-edit mdl-store-add" data-t="models-store-add-row">`
      + `<input data-store-path placeholder="${hint}" aria-label="${hint}" autocomplete="off" spellcheck="false" data-t="models-store-add-path">`
      + `<button class="mini-link" type="button" data-store-add data-t="models-store-add">${escapeHtml(t("storeAdd"))}</button>`
      + `<button class="mini-link" type="button" data-store-add-cancel data-t="models-store-add-cancel">${escapeHtml(t("cancel"))}</button></div>`;
  }

  // ── The summary over the list ───────────────────────────────────────────

  summaryHtml() {
    if (!this.stores && !this.error) return `<p class="muted">…</p>`;
    const store = (this.stores || []).find((s) => s.id === this.scope);
    return store ? this.placeSummary(store) : this.allSummary();
  }

  // Every place at once: how many models, where their bytes lie — one bar, a
  // segment per place — and each place's room, with the way into it. The
  // counts and the bar wait for this disk's count, as the total in the list
  // does: a library alone would fill the whole bar and pass for everything.
  allSummary() {
    const parts = !this.local ? [] : (this.stores || []).map((s) => ({ s, held: this.held(s) })).filter((p) => p.held);
    const families = this.familiesOf(ALL);
    const facts = [
      families === null ? "" : t("mdlFamilies", { n: String(families) }),
      parts.length ? t("mdlFiles", { n: String(parts.reduce((a, p) => a + p.held.files, 0)) }) : "",
      parts.length ? fmtGb(parts.reduce((a, p) => a + p.held.size, 0)) : "",
    ].filter(Boolean).join(" · ");
    return `<div class="mdl-sum-main"><h2 class="mdl-sum-title"><span aria-hidden="true">🗂</span> ${escapeHtml(t("mdlAllModels"))}`
      + `${facts ? ` <span class="facts" data-t="models-summary-facts">${escapeHtml(facts)}</span>` : ""}</h2>`
      + `${this.stack(parts)}</div>`
      + `<div class="mdl-cards">${(this.stores || []).map((s) => this.card(s)).join("")}</div>`;
  }

  // Where the bytes lie. A place holding nothing gets no segment, and with
  // nothing anywhere there is no bar: an empty track would say "0%" of what?
  stack(parts) {
    const size = parts.reduce((a, p) => a + p.held.size, 0);
    if (!size) return "";
    let libs = 0;
    const segs = parts.filter((p) => p.held.size > 0)
      .map((p) => ({ ...p, cls: p.s.builtin ? "here" : `lib${(libs++) % LIB_SEGMENTS}` }));
    const bars = segs.map((p) => `<i class="${p.cls}" style="width:${((100 * p.held.size) / size).toFixed(2)}%"></i>`).join("");
    const legend = segs.map((p) => `<span><i class="mdl-sw ${p.cls}"></i>${p.s.builtin ? "🏠" : "📚"} ${escapeHtml(this.nameOf(p.s))}`
      + ` <b>${escapeHtml(fmtGb(p.held.size))}</b> · ${escapeHtml(t("mdlFiles", { n: String(p.held.files) }))}</span>`).join("");
    return `<div class="mdl-stack" data-t="models-summary-bar"><div class="mdl-stack-bars" aria-hidden="true">${bars}</div>`
      + `<div class="mdl-stack-legend">${legend}</div></div>`;
  }

  // One place's room, beside the others. What it holds is in the bar's
  // legend already; the card says what the legend cannot — how much is free.
  card(s) {
    const used = StoresPanel.used(s);
    const open = `<button class="mdl-open" type="button" data-scope="${escapeHtml(s.id)}" data-t="models-place-open" data-t-id="${escapeHtml(s.id)}">`
      + `${escapeHtml(t("mdlOpenPlace"))} ›</button>`;
    const head = `<div class="mdl-card-h"><span aria-hidden="true">${s.builtin ? "🏠" : "📚"}</span><span class="nm">${escapeHtml(this.nameOf(s))}</span>`
      + `${s.state === "ok" ? "" : this.chip(s)}${open}</div>`;
    return `<div class="mdl-card" data-t="models-place-card" data-t-id="${escapeHtml(s.id)}">${head}${used === null ? "" : this.room(s, used)}</div>`;
  }

  room(s, used) {
    return `<div class="mdl-free"><b>${escapeHtml(fmtSpace(s.free || 0))}</b><span>${escapeHtml(t("mdlFreeOf", { total: fmtSpace(s.total) }))}</span></div>`
      + `${this.bar(s, used)}<div class="mdl-full">${escapeHtml(t("mdlPercentFull", { pct: String(used) }))}</div>`;
  }

  // One place: its name and state, where it is and what may be done with that,
  // what it holds, and its room.
  placeSummary(s) {
    const held = this.held(s);
    const used = StoresPanel.used(s);
    const families = this.familiesOf(s.id);
    let facts = "";
    if (held) {
      facts = held.files
        ? [t("mdlFiles", { n: String(held.files) }), fmtGb(held.size), families === null ? "" : t("mdlFamilies", { n: String(families) })].filter(Boolean).join(" · ")
        : t("storeEmpty");
    }
    return `<div class="mdl-sum-main"><h2 class="mdl-sum-title"><span aria-hidden="true">${s.builtin ? "🏠" : "📚"}</span> ${escapeHtml(this.nameOf(s))} ${this.chip(s)}</h2>`
      + `<div class="mdl-sum-line">${this.pathCell(s)}</div>`
      + (facts ? `<div class="mdl-sum-line" data-t="models-summary-facts">${escapeHtml(facts)}</div>` : "")
      + (held && !s.builtin ? this.folders(s) : "")
      + `</div>`
      + (used === null ? "" : `<div class="mdl-sum-space">${this.room(s, used)}</div>`);
  }

  // The path, and what may be done with it: the controller's own directory can
  // be pointed somewhere else (the pencil opens the box in place), a library
  // can be taken off the list.
  pathCell(s) {
    if (s.builtin && this.editing) {
      return `<span class="mdl-path-edit" data-t="models-path-edit-row">`
        + `<input data-store-dir value="${escapeHtml(s.path || "")}" autocomplete="off" spellcheck="false"`
        + ` data-i18n-aria="a11yModelsDirectory" aria-label="Models directory" data-t="models-path-input">`
        + `<button class="mini-link" type="button" data-dir-save data-t="models-path-save">${escapeHtml(t("save"))}</button>`
        + `<button class="mini-link" type="button" data-dir-cancel data-t="models-path-cancel">${escapeHtml(t("cancel"))}</button></span>`;
    }
    const act = s.builtin
      ? `<button class="mdl-mini" type="button" data-dir-edit title="${escapeHtml(t("mdlEditModelsDir"))}"`
        + ` aria-label="${escapeHtml(t("mdlEditModelsDir"))}" data-t="models-path-edit">✎</button>`
      : `<button class="mdl-mini" type="button" data-store-remove="${escapeHtml(s.id)}"`
        + ` data-t="models-store-remove">${escapeHtml(t("storeRemove"))}</button>`;
    return `<code class="mdl-store-path" data-t="models-path-value" title="${escapeHtml(s.path || "")}">`
      + `${escapeHtml(s.path || "")}</code>${act}`;
  }

  folders(s) {
    const list = Array.isArray(s.folders) ? s.folders : [];
    if (!list.length) return "";
    const rows = list.map((f) => `<div class="mdl-inside-row"><code title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</code>`
      + `<span class="meta">${escapeHtml(fmtGb(f.bytes || 0))} · ${escapeHtml(String(f.files || 0))}</span></div>`).join("");
    // What did not fit is named by its count, not dropped: a list cut at the
    // limit would otherwise read as the whole library.
    const more = s.more ? `<p class="muted">${escapeHtml(t("storeMore", { n: String(s.more) }))}</p>` : "";
    return `<details class="mdl-store-files" data-t="models-store-files"><summary><span class="tw"></span>${escapeHtml(t("storeFolders"))}</summary>`
      + `<div class="mdl-inside">${rows}${more}</div></details>`;
  }

  // ── Talking to the operator ─────────────────────────────────────────────

  // The first element matching in the places or in the summary: the path box
  // lives in one, the add box in the other.
  query(sel) {
    for (const el of [this.root, this.summary]) {
      const hit = el && el.querySelector ? el.querySelector(sel) : null;
      if (hit) return hit;
    }
    return null;
  }

  typed() {
    const path = this.query("[data-store-path]");
    const dir = this.query("[data-store-dir]");
    const inside = this.query("details.mdl-store-files");
    const active = globalThis.document ? globalThis.document.activeElement : null;
    return {
      path: path ? path.value : null,
      dir: dir ? dir.value : null,
      inside: !!(inside && inside.open),
      focus: active && active === path ? "[data-store-path]" : active && active === dir ? "[data-store-dir]" : "",
    };
  }

  retype(kept) {
    const path = this.query("[data-store-path]");
    const dir = this.query("[data-store-dir]");
    if (path && kept.path !== null) path.value = kept.path;
    if (dir && kept.dir !== null) dir.value = kept.dir;
    const inside = this.query("details.mdl-store-files");
    if (inside && kept.inside) inside.open = true;
    const focus = kept.focus ? this.query(kept.focus) : null;
    if (focus && focus.focus) focus.focus();
  }

  bind() {
    // Delegation: the panel is rebuilt from scratch on every refresh, and a
    // handler bound to a button would leave together with the button.
    const click = (e) => {
      const find = (sel) => (e.target && e.target.closest ? e.target.closest(sel) : null);
      const place = find("[data-scope]");
      if (place) return this.choose(place.dataset.scope);
      if (find("[data-store-add-open]")) { this.adding = true; this.render(); this.focusOn("[data-store-path]"); return undefined; }
      if (find("[data-store-add-cancel]")) { this.adding = false; this.render(); return undefined; }
      const add = find("[data-store-add]");
      if (add) return this.add(add);
      const rm = find("[data-store-remove]");
      if (rm) return this.remove(rm.dataset.storeRemove, rm);
      if (find("[data-dir-edit]")) { this.editing = true; this.render(); this.focusOn("[data-store-dir]"); return undefined; }
      if (find("[data-dir-cancel]")) { this.editing = false; this.render(); return undefined; }
      const save = find("[data-dir-save]");
      if (save) return this.saveDir(save);
      return undefined;
    };
    const key = (e) => {
      const on = (sel) => (e.target && e.target.closest ? e.target.closest(sel) : null);
      if (on("[data-store-dir]")) {
        if (e.key === "Enter") { e.preventDefault(); this.saveDir(this.query("[data-dir-save]")); }
        if (e.key === "Escape") { e.preventDefault(); this.editing = false; this.render(); }
        return;
      }
      if (!on("[data-store-path]")) return;
      if (e.key === "Enter") { e.preventDefault(); this.add(this.query("[data-store-add]")); }
      if (e.key === "Escape") { e.preventDefault(); this.adding = false; this.render(); }
    };
    for (const el of [this.root, this.summary]) {
      if (!el) continue;
      el.addEventListener("click", click);
      el.addEventListener("keydown", key);
    }
  }

  focusOn(sel) {
    const box = this.query(sel);
    if (box && box.focus) { box.focus(); if (box.select) box.select(); }
  }

  async saveDir(btn) {
    const box = this.query("[data-store-dir]");
    const path = String((box && box.value) || "").trim();
    if (!path || !this.onSavePath) return;
    if (btn) { btn.disabled = true; btn.classList.add("btn-busy"); }
    try {
      await this.onSavePath(path);
      this.editing = false;
      this.render();
    } catch (err) {
      toast(String((err && err.message) || err));
      if (btn) { btn.disabled = false; btn.classList.remove("btn-busy"); }
    }
  }

  async add(btn, force = false) {
    const input = this.query("[data-store-path]");
    const path = String((input && input.value) || "").trim();
    if (!path) return;
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/model-stores/add", { method: "POST", body: { path, force } });
      if (res && res.ok === false) {
        // A bare directory is refused ONCE, and the operator decides: an
        // unmounted share leaves exactly such a directory behind, and marking
        // it would make the local disk pose as the library.
        if (res.code === "not-a-mount" && !force) {
          if (await appConfirm(t("storeNotMountConfirm", { path }), { title: t("storesTitle"), confirmLabel: t("storeAdd") })) await this.add(btn, true);
          return;
        }
        throw new Error(res.error || "failed");
      }
      this.adding = false;
      if (input) input.value = "";
      await this.refresh(true);
    } catch (err) {
      toast(String((err && err.message) || err));
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async remove(id, btn) {
    const store = (this.stores || []).find((s) => s.id === id);
    const name = (store && (store.name || store.id)) || id;
    if (!(await appConfirm(t("storeRemoveConfirm", { name }), { title: t("storesTitle"), confirmLabel: t("storeRemove") }))) return;
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/model-stores/remove", { method: "POST", body: { id } });
      if (res && res.ok === false) throw new Error(res.error || "failed");
      await this.refresh(true);
    } catch (err) {
      toast(String((err && err.message) || err));
      if (btn) btn.disabled = false;
    }
  }
}

// The page's one entry point: models-page.js mounts the panel and keeps the
// instance, to redraw it when the language changes, to hand its libraries to
// the move button and to ask which place the list shows.
export const mountStores = (root, opts) => StoresPanel.mount(root, opts);
