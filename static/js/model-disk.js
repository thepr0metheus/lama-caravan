// The model disk on a machine's own page (machine-head.js MachineSide, its part "Model disk"). The owner, 2026-11-03, looking at the old line there: "make it prettier";
// and a folder for Strata's files of its own, always there and red until one is chosen — the controller starts no Strata cell until then and says where to choose it —
// each folder moved with its files, moved with them deleted, or removed. Later that day: Strata's models stay there up to a limit he changes in the row, and the row says
// what to choose — a fast disk, as Strata reads its model at random while it answers — and what Strata writes to it, so that he knows what it costs an SSD.
// The facts and the actions are the cache line's (model-cache.js, ModelCacheLine): the board's card keeps its short line, this is the same meaning drawn for the page,
// with the same hooks, so one binding serves both.
//
// Each row says its name with its buttons on one line and what it holds under them, so that a path is read whole in the page's narrow column: the old line cut it with "…".
import { t } from "./i18n.js";
import { ModelCacheLine } from "./model-cache.js";
import { Badge, Button, Meter } from "./ui-parts.js";
import { escapeHtml, fmtGb } from "./utils.js";

export class ModelDisk {
  constructor(node) {
    this.line = ModelCacheLine.of(node);
    this.id = escapeHtml(this.line.id);
  }

  static of(node) {
    return new ModelDisk(node);
  }

  /** A quiet button with its hook: `hook` names the attribute the binding finds it by (model-cache.js bind), `t` its test name. */
  button(text, testName, hook, title = "") {
    return new Button({ kind: "quiet", text, title, attrs: `data-t="${testName}" data-t-id="${this.id}" data-${hook}="${this.id}"` }).html();
  }

  /** The ✕ that removes a folder: an icon with its words for the screen reader and the tip. */
  removeButton(testName, hook, title) {
    return new Button({ kind: "icon", icon: "close", label: t("modelDiskRemove"), title, attrs: `data-t="${testName}" data-t-id="${this.id}" data-${hook}="${this.id}"` }).html();
  }

  /** One row: its name and its buttons, then what it holds. `tone` "bad" for what stops a start. */
  row({ testName, state = "", label, help = "", value, buttons = "", tone = "" }) {
    return `<div class="mdisk-row${tone ? ` mdisk-row--${tone}` : ""}" data-t="${testName}" data-t-id="${this.id}"${state ? ` data-t-state="${state}"` : ""}>`
      + `<div class="mdisk-row-head"><span class="mdisk-label"${help ? ` title="${escapeHtml(help)}"` : ""}>${escapeHtml(label)}</span>`
      + `${buttons ? `<span class="mdisk-actions">${buttons}</span>` : ""}</div>${value}</div>`;
  }

  /** A path, read left to right in every language. */
  static path(dir) {
    return `<code class="mdisk-path" dir="ltr">${escapeHtml(dir)}</code>`;
  }

  /** The figures of the disk the cache lies on, for its bar: its size, the other files, and the cache while it was measured; null while the disk was not — an empty bar would read as a
   *  free disk. */
  meterParts() {
    const disk = this.line.disk;
    if (!disk) return null;
    const used = disk.totalBytes - disk.freeBytes;
    const held = this.line.heldBytes;
    const parts = held === null ? [{ value: used, kind: "other", title: t("modelDiskOthers") }]
      : [{ value: Math.max(0, used - held), kind: "other", title: t("modelDiskOthers") }, { value: held, series: 1, title: t("modelDiskCacheShare") }];
    return { total: disk.totalBytes, parts };
  }

  /** The disk as a bar: the other files hatched, the cache in its colour. */
  meterHtml() {
    const figures = this.meterParts();
    if (!figures) return "";
    return `<div class="mdisk-bar" data-live-diskbar>${new Meter({ label: t("modelDiskDisk"), parts: figures.parts, total: figures.total, tile: false }).html()}</div>`;
  }

  /** The cache's rule: the budget in GB where the scout keeps one (2.38), the last N models where it does not. The same boxes, with the same hooks, as on the card. */
  settingRow() {
    const line = this.line;
    const keep = line.facts.keep;
    const box = line.budgets
      ? `<span class="mdisk-budget"><input type="number" class="cache-budget" min="1" step="1" inputmode="numeric" value="${line.budgetGb ?? ""}"`
        + ` placeholder="${escapeHtml(t("modelCacheBudgetUnset"))}" data-t="node-cache-budget" data-t-id="${this.id}" data-cache-budget="${this.id}">`
        + `<span>${escapeHtml(t("modelCacheGb"))}</span></span>`
      : `<select class="cache-keep" data-t="node-cache-keep" data-t-id="${this.id}" data-cache-keep="${this.id}">`
        + line.choices.map((n) => `<option value="${n}"${n === keep ? " selected" : ""}>${n}</option>`).join("") + `</select>`;
    const label = line.budgets ? "modelCacheBudgetLabel" : "modelCacheKeepLabel";
    const help = line.budgets ? t("modelCacheBudgetHelp", { n: keep }) : t("modelCacheKeepHelp");
    return `<div class="mdisk-setting"><span class="mdisk-label" title="${escapeHtml(help)}">${escapeHtml(t(label))}</span>${box}</div>`;
  }

  /** Where the cache is: its path, Change…, and ✕ when the operator chose it. */
  folderRow() {
    const line = this.line;
    if (!line.folder) return "";
    const remove = line.cacheChosen ? this.removeButton("node-cache-dir-remove", "cache-dir-remove", t("modelDiskCacheRemoveHelp", { dir: line.ownFolder || "?" })) : "";
    return this.row({ testName: "node-cache-dir", label: t("modelCacheDirLabel"), value: ModelDisk.path(line.folder),
                      buttons: this.button(t("modelCacheDirChange"), "node-cache-dir-change", "cache-dir", t("modelCacheDirHelp")) + remove });
  }

  /** Where Strata's files go: the folder, what lies there and the limit over its models, with what the operator should know when he chooses it — Strata needs a fast disk, and what it
   *  writes to it — or, red, that none is chosen and Strata does not start. A scout that keeps no such folder apart gets no row. */
  workRow() {
    const line = this.line;
    const work = line.work;
    if (!work) return "";
    const help = t("modelDiskWorkHelp");
    const fast = `<span class="mdisk-hint" data-t="node-cache-work-fast" data-t-id="${this.id}">${escapeHtml(t("modelDiskWorkFast"))}</span>`;
    if (!work.chosen) {
      return this.row({ testName: "node-cache-work", state: "unset", tone: "bad", label: t("modelDiskWorkLabel"), help,
                        value: `<span class="mdisk-note">${escapeHtml(t("modelDiskWorkUnset"))}</span>${fast}`,
                        buttons: this.button(t("modelDiskWorkChoose"), "node-cache-work-set", "cache-work", help) });
    }
    const bytes = line.workBytes;
    const size = bytes ? ` · <span data-live-workbytes>${escapeHtml(fmtGb(bytes))}</span>` : "";
    // The disk's kind, as the system says it: a spinning one is said in red, as what stalls Strata; no word, the hint of what Strata needs.
    const disk = line.workSpins === true
      ? `<span class="mdisk-warn" data-t="node-cache-work-hdd" data-t-id="${this.id}">${escapeHtml(t("modelDiskWorkHdd"))}</span>`
      : line.workSpins === false ? "" : fast;
    const short = line.workShortBytes === null ? ""
      : `<span class="mdisk-warn" data-t="node-cache-work-short" data-t-id="${this.id}">${escapeHtml(t("modelDiskWorkShort", { free: fmtGb(line.workDisk.freeBytes), room: fmtGb(line.workShortBytes) }))}</span>`;
    const wear = `<span class="mdisk-hint" data-t="node-cache-work-wear" data-t-id="${this.id}">${escapeHtml(t("modelDiskWorkWear"))}</span>`;
    // Said in words as well as by the card: the cache's switch above looked as if it turned Strata off too (the owner, 2026-11-03: "it scares").
    const apart = `<span class="mdisk-hint" data-t="node-cache-work-apart" data-t-id="${this.id}">${escapeHtml(t("modelDiskWorkApart"))}</span>`;
    return `<div class="mdisk-row" data-t="node-cache-work" data-t-id="${this.id}" data-t-state="chosen">`
      + `<div class="mdisk-row-head"><span class="mdisk-label" title="${escapeHtml(help)}">${escapeHtml(t("modelDiskWorkLabel"))}${size}</span>`
      + `<span class="mdisk-actions">${this.button(t("modelCacheDirChange"), "node-cache-work-set", "cache-work", help)}`
      + `${this.removeButton("node-cache-work-remove", "cache-work-remove", t("modelDiskWorkRemoveHelp"))}</span></div>`
      + `${ModelDisk.path(work.dir)}${this.workLimitHtml()}${disk}${short}${apart}${wear}</div>`;
  }

  /** What Strata's models take, with their names in the tip, and the box of the limit over them, in GB as the cache's budget is. */
  workLimitHtml() {
    const line = this.line;
    if (line.workBudgetGb === null) return "";
    const help = t("modelDiskWorkLimitHelp");
    const names = line.workModels.map((row) => `${row.name} · ${fmtGb(row.bytes)}`).join("\n");
    const models = line.workModelsBytes === null ? ""
      : `<span class="mdisk-note" title="${escapeHtml(names || t("modelDiskWorkNoModels"))}" data-live-workmodels>${escapeHtml(t("modelDiskWorkModels", { size: fmtGb(line.workModelsBytes) }))}</span>`;
    return `<div class="mdisk-setting">${models}<span class="mdisk-budget" title="${escapeHtml(help)}"><span>${escapeHtml(t("modelDiskWorkLimit"))}</span>`
      + `<input type="number" class="cache-budget" min="1" step="1" inputmode="numeric" value="${line.workBudgetGb}" aria-label="${escapeHtml(help)}"`
      + ` data-t="node-cache-work-budget" data-t-id="${this.id}" data-cache-work-budget="${this.id}"><span>${escapeHtml(t("modelCacheGb"))}</span></span></div>`;
  }

  /** Where a machine whose cache is off reads its models: through the controller, or a folder where the library is mounted (the card's row, model-cache.js readsHtml, drawn as a row). */
  readsRow() {
    const line = this.line;
    if (!line.switches) return "";
    const help = t("modelCacheLibraryHelp");
    if (line.through) {
      return this.row({ testName: "node-cache-library", state: "through", label: t("modelCacheLibraryLabel"),
                        value: `<span class="mdisk-note">${escapeHtml(t("modelCacheThroughWord"))}</span>`,
                        buttons: this.button(t("modelCacheUseFolder"), "node-cache-library-set", "cache-library", help) });
    }
    const back = line.canThrough ? this.button(t("modelCacheUseThrough"), "node-cache-through", "cache-through", t("modelCacheThroughHelp")) : "";
    const value = line.library ? ModelDisk.path(line.library) : `<span class="mdisk-note">${escapeHtml(t("modelCacheLibraryNotSet"))}</span>`;
    return this.row({ testName: "node-cache-library", state: "folder", label: t("modelCacheLibraryLabel"), value,
                      buttons: this.button(t("modelCacheDirChange"), "node-cache-library-set", "cache-library", help) + back });
  }

  /** How far a move is, in words. */
  movingWords() {
    const moving = this.line.moving;
    if (!moving) return "";
    const what = t(moving.what === "cache" ? "modelDiskWhatCache" : "modelDiskWhatWork");
    return t("modelDiskMoving", { what, to: moving.to, done: fmtGb(moving.doneBytes), total: fmtGb(moving.totalBytes) });
  }

  /** The share of a move done, in percent; 0 before the first byte. */
  static share(moving) {
    return moving && moving.totalBytes > 0 ? Math.min(100, Math.round((moving.doneBytes / moving.totalBytes) * 10000) / 100) : 0;
  }

  /** A folder's files on their way: what moves where, how far, and a bar of it — one segment always drawn, so that the patch has it to widen from 0. */
  movingRow() {
    const moving = this.line.moving;
    if (!moving) return "";
    return `<div class="mdisk-moving" data-t="node-cache-moving" data-t-id="${this.id}" data-t-state="${escapeHtml(moving.what)}">`
      + `<span class="mdisk-note" data-live-movewords>${escapeHtml(this.movingWords())}</span>`
      + `<div class="ui-meter-bar" role="img" aria-label="${escapeHtml(this.movingWords())}"><span class="ui-meter-seg" data-live-moveshare style="width: ${ModelDisk.share(moving)}%"></span></div></div>`;
  }

  /** Why the last move did not happen, until the next one. */
  errorRow() {
    const words = this.line.moveError;
    return words ? `<div class="mdisk-error" data-t="node-cache-move-error" data-t-id="${this.id}">${escapeHtml(t("modelDiskMoveFailed", { words }))}</div>` : "";
  }

  /** The files the scout did not download, with the button that deletes them after a question (the same hooks as the card's line). */
  foreignRow() {
    const foreign = this.line.foreign;
    if (!foreign) return "";
    return `<div class="mdisk-foreign" data-t="node-cache-foreign" data-t-id="${this.id}" title="${escapeHtml(`${t("modelCacheForeignHelp")}\n${this.line.folders()}`.trim())}">`
      + `<span class="mdisk-note">${escapeHtml(t("modelCacheForeign", { n: foreign.files, size: fmtGb(foreign.bytes) }))}</span>`
      + this.button(t("modelCacheDeleteBtn"), "node-cache-delete", "cache-delete-foreign") + `</div>`;
  }

  /** The head: the cache's name, on or off, and what it can be told — Clear while it holds something, the switch. */
  headHtml() {
    const line = this.line;
    const actions = !line.switches ? ""
      : line.off ? this.button(t("modelCacheTurnOn"), "node-cache-on", "cache-on", t("modelCacheOnHelp"))
      : (line.heldBytes ? this.button(t("modelCacheClear"), "node-cache-clear", "cache-clear", t("modelCacheClearHelp")) : "")
        + this.button(t("modelCacheTurnOff"), "node-cache-off", "cache-off", t("modelCacheOffHelp"));
    const state = line.switches ? new Badge({ tone: line.off ? "idle" : "good", text: t(line.off ? "modelCacheOffWord" : "modelDiskOnWord") }).html() : "";
    return `<div class="mdisk-head"><span class="mdisk-name" title="${escapeHtml(t("modelCacheKeepHelp"))}">${escapeHtml(t("modelCacheHead"))}</span>${state}`
      + `${actions ? `<span class="mdisk-actions">${actions}</span>` : ""}</div>`;
  }

  /** What moves with every chunk, written again in place — the disk's bar, a move's words and bar — as the figures are: they never redraw the page (the card's rule, model-cache.js
   *  fingerprint). A bar whose parts came or went is drawn again by the fingerprint instead. */
  static patch(nodeEl, n) {
    const disk = ModelDisk.of(n);
    const figures = disk.meterParts();
    const segs = [...(nodeEl?.querySelector?.("[data-live-diskbar]")?.querySelectorAll(".ui-meter-seg") || [])];
    const cut = figures ? Meter.cut(figures.total, figures.parts) : null;
    if (cut && cut.length === segs.length) cut.forEach(({ width }, i) => ModelDisk.widen(segs[i], width));
    const words = nodeEl?.querySelector?.("[data-live-movewords]");
    const said = disk.movingWords();
    if (words && said && words.textContent !== said) words.textContent = said;
    ModelDisk.widen(nodeEl?.querySelector?.("[data-live-moveshare]"), ModelDisk.share(disk.line.moving));
    // What the folder for Strata's files holds grows with every chunk of a copy into it.
    const line = disk.line;
    ModelDisk.say(nodeEl?.querySelector?.("[data-live-workbytes]"), line.workBytes ? fmtGb(line.workBytes) : "");
    ModelDisk.say(nodeEl?.querySelector?.("[data-live-workmodels]"), line.workModelsBytes === null ? "" : t("modelDiskWorkModels", { size: fmtGb(line.workModelsBytes) }));
  }

  /** Words written again in place, when there are any and they changed. */
  static say(el, words) {
    if (el && words && el.textContent !== words) el.textContent = words;
  }

  static widen(seg, width) {
    const w = `${width}%`;
    if (seg && seg.style.width !== w) seg.style.width = w;
  }

  /** A move under way, in the card of the folder that moves. */
  movingIn(what) {
    return this.line.moving?.what === what ? this.movingRow() : "";
  }

  /** The folder for Strata's files as a card of its own beside the cache's, not a row under its switch: Turn off and Clear are the cache's and never touch it (the owner,
   *  2026-11-03: "the cache of ordinary models and of Strata's must be apart, and the cache's Turn off must not touch Strata"). */
  workCard() {
    const work = this.line.work;
    if (!work) return "";
    return `<div class="mdisk mdisk--work${work.chosen ? "" : " mdisk--bad"}" data-t="node-strata" data-t-id="${this.id}">${this.workRow()}${this.movingIn("work")}</div>`;
  }

  html() {
    const line = this.line;
    if (!line.drawn) return "";
    const figures = `<div class="mdisk-figures" data-t="node-cache-figures" data-t-id="${this.id}" data-live-cachefigures>${escapeHtml(line.figures())}</div>`;
    // Off, the cache keeps no copies: no rule and no folder for them, and where the models are read from instead.
    const cache = line.off ? this.readsRow() : `${this.settingRow()}${this.folderRow()}`;
    const cacheCard = `<div class="mdisk" data-t="node-cache" data-t-id="${this.id}" data-t-state="${line.off ? "off" : "on"}">${this.headHtml()}${this.meterHtml()}${figures}`
      + `<div class="mdisk-rows">${cache}${this.movingIn("cache")}${this.foreignRow()}</div></div>`;
    // The last move's failure says no folder of its own: it stands under both cards.
    return `<div class="mdisk-stack">${cacheCard}${this.workCard()}${this.errorRow()}</div>`;
  }
}
