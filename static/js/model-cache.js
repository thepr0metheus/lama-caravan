// A machine's model cache, said on its card (1.3.576). The owner, 2026-10-18, when the disk of a machine was 94 % full of model copies and a
// start died with "No space left on device": keep in the cache only the last models, from 1 to 5, 1 by default; show the setting somewhere
// noticeable; delete everything older by itself. The scout does it (caravan-scout 2.34, cache_keeper.py) and reports `modelCache` with the
// setting and the figures; this is the line on the caravan's group of the machine's card — the setting as a box to choose from, what the cache
// holds, what the disk has left — and, when the folder holds files the scout did not download (it never deletes those by itself), a line that
// says so with a button to delete them after a question that names the size.
//
// A scout older than 2.34 reports nothing about its cache: no line is drawn for it — never a line with a setting made up.
//
// The owner, 2026-10-26: say the setting in GB, not in models, and let the cache be in a folder of his choosing — an HDD, not the SSD's
// writes. A scout of 2.38 keeps both (budgetBytes, dir): the box is the budget in GB then, empty while none is chosen (the last N models
// rule), and the folder stands under it with a button that moves it after a question that names what goes.
//
// The owner, 2026-11-02: be able to clear this cache, and to turn caching off on the machine altogether. A scout that can says `off`: the line then
// offers "Clear" while the cache holds something and "Turn off…"; off, the machine reads its models from the library over the network, and the
// line says from where and offers "Turn on". Each of the two that delete copies asks first, naming how much.
//
// The owner, 2026-11-03: a folder for Strata's files of its own (`work`: it starts no Strata cell until one is chosen), and a folder that changes either takes its
// files with it or deletes them, as he chooses; a folder removed takes its files with it. The machine's own page draws all of it (model-disk.js); the board's card
// keeps its short line, and its Change… asks the same question. Later that day: Strata's models stay in that folder after a stop, up to a limit he can change (300 GB
// unless he says), and the folder says whether its disk spins — Strata stalls on an HDD.
//
// The same figures give the sign on the machine's head, on the main board's glance too (the owner, 2026-10-18, asked for it after the disk of
// a machine filled up): "⚠ disk 94% full" when the cache folder's disk is used DISK_LOW_USED_PCT % or more.
import { appConfirm, appConfirmChoice, appConfirmFields, appPrompt } from "./dialogs.js";
import { t } from "./i18n.js";
import { topology } from "./state.js";
import { api, escapeHtml, fmtGb, fmtSpace, toast } from "./utils.js";

export class ModelCacheLine {
  /** What the box offers. The scout's own range (cache_keeper.CacheKeep: 1 to 5) — it refuses any other, in its own words. */
  static KEEPS = [1, 2, 3, 4, 5];

  /** From this share of the disk used (whole percent) the disk is "almost full" and the machine's head says so. The owner asked for the sign, not for
   *  a number: 90 is a choice — a disk at 94 % is where a start died with "No space left on device", and 10 % of a 900 GB disk is 90 GB, about what one
   *  big model copy takes. One place for it; the words of the tip read it from here. */
  static DISK_LOW_USED_PCT = 90;

  /** The facts of a machine's node (`node.modelCache`, as the controller cleaned them: model_cache.py) or null when the scout cannot say. */
  constructor(node) {
    this.id = String(node?.id ?? "");
    this.name = String(node?.name || node?.id || "");
    const facts = node?.modelCache;
    this.facts = facts && typeof facts === "object" && Number.isInteger(facts.keep) && facts.keep > 0 ? facts : null;
  }

  static of(node) {
    return new ModelCacheLine(node);
  }

  /** Whether this machine's scout reports a cache at all. */
  get drawn() {
    return this.facts !== null;
  }

  /** The foreign files the scout counted, or null when it did not say or none lie there — the line below the setting exists only for these. */
  get foreign() {
    const f = this.facts?.foreign;
    return f && Number.isFinite(f.files) && f.files > 0 && Number.isFinite(f.bytes) ? f : null;
  }

  /** Whether the scout keeps a budget in bytes (2.38: the owner, 2026-10-26, "in GB, not in models"): its report says `budgetBytes`,
   *  null while none is chosen. An older scout says nothing of it, and the box of the last N models stays — never a field it cannot set. */
  get budgets() {
    return !!this.facts && "budgetBytes" in this.facts;
  }

  /** Whether the scout can turn its cache off: it says `off`. An older scout says nothing of it, and no switch is drawn: never a button it cannot do. */
  get switches() {
    return !!this.facts && typeof this.facts.off === "boolean";
  }

  /** Whether this machine keeps no copies. */
  get off() {
    return this.facts?.off === true;
  }

  /** Where the library lies on this machine, as its scout was told; "" while it was not. */
  get library() {
    return String(this.facts?.library || "");
  }

  /** Whether a model comes through the controller with the cache off, and no folder of the library is read. */
  get through() {
    return this.facts?.through === true;
  }

  /** Whether this machine can read a model that way. A scout that does not say cannot: the way is offered to none that may refuse it. */
  get canThrough() {
    return this.facts?.canThrough === true;
  }

  /** The budget the scout keeps, in whole GB as the box shows it, or null while none is chosen. */
  get budgetGb() {
    const bytes = this.facts?.budgetBytes;
    return Number.isFinite(bytes) && bytes > 0 ? Math.round(bytes / ModelCacheLine.GIB) : null;
  }

  /** The folder the cache is in (2.38), or "" when the scout does not say — and then nothing offers to move it. */
  get folder() {
    const dir = this.facts?.dir;
    return typeof dir === "string" && dir.startsWith("/") ? dir : "";
  }

  /** Whether the cache lies in a folder the operator chose, not where it lies by itself: only such a folder can be removed. */
  get cacheChosen() {
    return this.facts?.dirChosen === true;
  }

  /** Where the cache goes back to when the chosen folder is removed, as the scout says it; "" when it does not say. */
  get ownFolder() {
    const dir = this.facts?.dirOwn;
    return typeof dir === "string" && dir.startsWith("/") ? dir : "";
  }

  /** The folder the cells keep what they make from their models in (2026-11-03): {dir, chosen, bytes}, or null for a scout that keeps none apart. */
  get work() {
    const w = this.facts?.work;
    return w && typeof w.dir === "string" && w.dir.startsWith("/") && typeof w.chosen === "boolean" ? w : null;
  }

  /** What the folder holds — Strata's models and what its cells made from them — in bytes, or null when the scout did not measure it. */
  get workBytes() {
    const bytes = this.work?.bytes;
    return Number.isFinite(bytes) && bytes >= 0 ? bytes : null;
  }

  /** What Strata's models there take, in bytes, or null when the scout did not say (an older one keeps no models there). */
  get workModelsBytes() {
    const bytes = this.work?.modelsBytes;
    return Number.isFinite(bytes) && bytes >= 0 ? bytes : null;
  }

  /** The folder's limit over its models, in whole GB as the box shows it, or null for a scout that keeps none. */
  get workBudgetGb() {
    const bytes = this.work?.budgetBytes;
    return Number.isFinite(bytes) && bytes > 0 ? Math.round(bytes / ModelCacheLine.GIB) : null;
  }

  /** {free, total} of the folder's disk, or null when the scout did not measure it. */
  get workDisk() {
    const d = this.work?.disk;
    return d && Number.isFinite(d.freeBytes) && Number.isFinite(d.totalBytes) && d.totalBytes > 0 && d.freeBytes <= d.totalBytes ? d : null;
  }

  /** Whether the folder's disk spins — an HDD — as the system says it: true, false, or null where it does not say (a share, an older scout). */
  get workSpins() {
    const said = this.work?.rotational;
    return typeof said === "boolean" ? said : null;
  }

  /** Strata's models in the folder, biggest first, as the scout lists them: [{name, bytes}]. */
  get workModels() {
    const rows = this.work?.models;
    return Array.isArray(rows) ? rows.filter((row) => typeof row?.name === "string" && Number.isFinite(row.bytes)) : [];
  }

  /** The room the limit still leaves for new models, in bytes, when the disk has less free than that: null otherwise, and null for what was not measured. A
   *  disk that fills before the limit does refuses a start the limit allows, and the operator should see it before he starts one. */
  get workShortBytes() {
    const disk = this.workDisk;
    const models = this.workModelsBytes;
    const budget = this.workBudgetGb;
    if (!disk || models === null || budget === null) return null;
    const room = Math.max(0, budget * ModelCacheLine.GIB - models);
    return disk.freeBytes < room ? room : null;
  }

  /** A folder's files on their way: {what, to, doneBytes, totalBytes}, or null when none moves. */
  get moving() {
    const m = this.facts?.moving;
    return m && (m.what === "cache" || m.what === "work") && typeof m.to === "string" && Number.isFinite(m.doneBytes) && Number.isFinite(m.totalBytes) ? m : null;
  }

  /** The words of the last move that failed, or "". */
  get moveError() {
    return typeof this.facts?.moveError === "string" ? this.facts.moveError : "";
  }

  /** The box's choices: the scout's range, and the setting it reports if that is not in it (so the box never shows a setting it does not hold). */
  get choices() {
    const keep = this.facts?.keep;
    return ModelCacheLine.KEEPS.includes(keep) ? ModelCacheLine.KEEPS : [...ModelCacheLine.KEEPS, keep].sort((a, b) => a - b);
  }

  /** Bytes the scout says it holds in the cache, or null when it did not measure them. */
  get heldBytes() {
    const bytes = this.facts?.managedBytes;
    return Number.isFinite(bytes) ? bytes : null;
  }

  /** {free, total} of the cache folder's disk, or null when the scout could not measure it — or said what cannot be (more free than the disk holds). */
  get disk() {
    const d = this.facts?.disk;
    return d && Number.isFinite(d.freeBytes) && Number.isFinite(d.totalBytes) && d.totalBytes > 0 && d.freeBytes <= d.totalBytes ? d : null;
  }

  /** The share of the cache folder's disk that is used, in whole percent and ROUNDED DOWN, or null when the scout could not measure the disk. Rounded down
   *  so that a number the sign shows is one the rule holds for: "90%" on the sign means 90 % or more is used, never 89.6. */
  get diskUsedPct() {
    const d = this.disk;
    return d ? Math.floor(((d.totalBytes - d.freeBytes) / d.totalBytes) * 100) : null;
  }

  /** Whether the disk is almost full. False for a disk nobody measured: the sign says only what the scout measured, and says nothing otherwise. */
  get diskLow() {
    const pct = this.diskUsedPct;
    return pct !== null && pct >= ModelCacheLine.DISK_LOW_USED_PCT;
  }

  /** The sign's words: "disk 94% full". */
  diskWords() {
    const pct = this.diskUsedPct;
    return pct === null ? "" : t("diskLowChip", { pct });
  }

  /** The sign for a machine's head: ⚠ and the words, with the rule in its tip — not the figures, which move with every download while a tip is written once. */
  diskChipHtml() {
    if (!this.diskLow) return "";
    const id = escapeHtml(this.id);
    return `<span class="node-disk-low" data-t="node-disk-low" data-t-id="${id}" title="${escapeHtml(t("diskLowTitle", { limit: ModelCacheLine.DISK_LOW_USED_PCT }))}">`
      + `⚠ <span data-live-diskpct>${escapeHtml(this.diskWords())}</span></span>`;
  }

  /** What the cache holds and what the disk has left, as words — only the parts the scout measured: a part it did not is left out, not zero. */
  figures() {
    const held = this.heldBytes === null ? "" : t("modelCacheHeld", { size: fmtGb(this.heldBytes) });
    const disk = this.disk ? t("modelCacheFree", { free: fmtSpace(this.disk.freeBytes), total: fmtSpace(this.disk.totalBytes) }) : "";
    return [held, disk].filter(Boolean).join(" · ");
  }

  /** The folders of the foreign files, one to a line, biggest first as the scout lists them. */
  folders() {
    return (this.foreign?.folders || []).map((row) => `${row.folder} · ${fmtGb(row.bytes)}`).join("\n");
  }

  /** A gibibyte: the board's GB everywhere (fmtGb), so a budget of "100" is the 100 the figures beside it say. */
  static GIB = 2 ** 30;

  /** What makes the card be drawn again when it moves: the setting, whether (and how much) foreign files lie there, and whether the disk is almost full
   *  (the sign comes and goes). The figures that move with every download — what the cache holds, what the disk has left, how full it is — are patched
   *  in place (`figures()`, `diskWords()`), not drawn again. */
  fingerprint() {
    if (!this.drawn) return "-";
    const foreign = this.foreign ? `${this.foreign.files}/${this.foreign.bytes}` : "none";
    const budget = this.budgets ? `b${this.budgetGb ?? "-"}` : "";
    const held = this.switches && this.heldBytes ? "h" : "";
    // What the folder holds moves with every chunk of a copy, as the cache's figures do: patched in place (model-disk.js ModelDisk.patch). Its limit, its disk's kind, the names of its models
    // and whether the disk is short of the limit are drawn again.
    const work = this.work
      ? `${this.work.chosen ? "w" : "c"}${this.work.dir}:${this.workBudgetGb ?? "-"}:${this.workSpins ?? "?"}:${this.workModels.map((row) => row.name).join("|")}:${this.workShortBytes === null ? "" : "short"}`
      : "";
    // How far a move is moves with every chunk, as the figures do: patched in place (model-disk.js ModelDisk.patch), not drawn again.
    const moving = this.moving ? `${this.moving.what}>${this.moving.to}` : "";
    return `${this.facts.keep}${budget}:${foreign}:${this.heldBytes === null ? 0 : 1}${this.disk ? 1 : 0}${this.diskLow ? "!" : ""}:${this.folder}${this.cacheChosen ? "*" : ""}:${this.off ? `off:${this.library}` : held}${this.through ? ":through" : ""}${this.canThrough ? ":can" : ""}`
      + `:${work}:${moving}:${this.moveError ? "e" : ""}`;
  }

  /** Where a machine whose cache is off reads its models. By default through the controller; a folder where the library is mounted is the operator's word (the owner, 2026-11-02). With the cache on a model
   *  comes through the controller anyway and no such folder matters: this row made the owner ask what it was for. */
  readsHtml(id) {
    const label = `<span class="cache-dir-label">${escapeHtml(t("modelCacheLibraryLabel"))}</span>`;
    const row = (place, button) => `<div class="cache-dir" data-t="node-cache-library" data-t-id="${id}" data-t-state="${this.through ? "through" : "folder"}">${label}${place}${button}</div>`;
    const folderButton = (word) => `<button type="button" class="cache-dir-change" data-t="node-cache-library-set" data-t-id="${id}" data-cache-library="${id}" title="${escapeHtml(t("modelCacheLibraryHelp"))}">${escapeHtml(t(word))}</button>`;
    if (this.through) return row(`<code class="cache-dir-path">${escapeHtml(t("modelCacheThroughWord"))}</code>`, folderButton("modelCacheUseFolder"));
    const back = this.canThrough
      ? `<button type="button" class="cache-dir-change" data-t="node-cache-through" data-t-id="${id}" data-cache-through="${id}" title="${escapeHtml(t("modelCacheThroughHelp"))}">${escapeHtml(t("modelCacheUseThrough"))}</button>`
      : "";
    return row(`<code class="cache-dir-path" dir="ltr" title="${escapeHtml(this.library)}">${escapeHtml(this.library || t("modelCacheLibraryNotSet"))}</code>`, folderButton("modelCacheDirChange") + back);
  }

  html() {
    if (!this.drawn) return "";
    const id = escapeHtml(this.id);
    const keep = this.facts.keep;
    const options = this.choices.map((n) => `<option value="${n}"${n === keep ? " selected" : ""}>${n}</option>`).join("");
    const help = escapeHtml(t("modelCacheKeepHelp"));
    const foreign = this.foreign;
    const line = foreign
      ? `<div class="cache-foreign" data-t="node-cache-foreign" data-t-id="${id}" title="${escapeHtml(`${t("modelCacheForeignHelp")}\n${this.folders()}`.trim())}">`
        + `<span class="cache-foreign-text">${escapeHtml(t("modelCacheForeign", { n: foreign.files, size: fmtGb(foreign.bytes) }))}</span>`
        + `<button type="button" class="cache-foreign-delete" data-t="node-cache-delete" data-t-id="${id}" data-cache-delete-foreign="${id}">`
        + `${escapeHtml(t("modelCacheDeleteBtn"))}</button></div>`
      : "";
    // The setting: the budget in GB where the scout keeps one (2.38), the last N models where it does not.
    const budgetHelp = escapeHtml(t("modelCacheBudgetHelp", { n: keep }));
    const setting = this.budgets
      ? `<label class="cache-budget-label" title="${budgetHelp}"><span>${escapeHtml(t("modelCacheBudgetLabel"))}</span>`
        + `<input type="number" class="cache-budget" min="1" step="1" inputmode="numeric" value="${this.budgetGb ?? ""}"`
        + ` placeholder="${escapeHtml(t("modelCacheBudgetUnset", { n: keep }))}" data-t="node-cache-budget" data-t-id="${id}" data-cache-budget="${id}">`
        + `<span>${escapeHtml(t("modelCacheGb"))}</span></label>`
      : `<label class="cache-keep-label" title="${help}"><span>${escapeHtml(t("modelCacheKeepLabel"))}</span>`
        + `<select class="cache-keep" data-t="node-cache-keep" data-t-id="${id}" data-cache-keep="${id}">${options}</select></label>`;
    // Where the cache is, and the button that moves it (2.38: the owner wants it on an HDD, not on the SSD's writes).
    const folder = this.folder
      ? `<div class="cache-dir" data-t="node-cache-dir" data-t-id="${id}"><span class="cache-dir-label">${escapeHtml(t("modelCacheDirLabel"))}</span>`
        // A path reads left to right in every language: in Arabic and Urdu its first "/" went to the end.
        + `<code class="cache-dir-path" dir="ltr" title="${escapeHtml(this.folder)}">${escapeHtml(this.folder)}</code>`
        + `<button type="button" class="cache-dir-change" data-t="node-cache-dir-change" data-t-id="${id}" data-cache-dir="${id}"`
        + ` title="${escapeHtml(t("modelCacheDirHelp"))}">${escapeHtml(t("modelCacheDirChange"))}</button></div>`
      : "";
    const title = `<span class="cache-title" title="${help}">${escapeHtml(t("modelCacheHead"))}</span>`;
    const figures = `<span class="cache-figures" data-t="node-cache-figures" data-t-id="${id}" data-live-cachefigures>${escapeHtml(this.figures())}</span>`;
    const library = this.switches && this.off ? this.readsHtml(id) : "";
    if (this.off) {
      return `<div class="cache-line is-off" data-t="node-cache" data-t-id="${id}" data-t-state="off">${title}`
        + `<span class="cache-off-word">${escapeHtml(t("modelCacheOffWord"))}</span>${figures}`
        + `<button type="button" class="cache-dir-change" data-t="node-cache-on" data-t-id="${id}" data-cache-on="${id}" title="${escapeHtml(t("modelCacheOnHelp"))}">${escapeHtml(t("modelCacheTurnOn"))}</button>`
        + `${library}${line}</div>`;
    }
    // Clear and the switch: only for a scout that can, and Clear only while there is something to clear.
    const clear = this.switches && this.heldBytes
      ? `<button type="button" class="cache-dir-change" data-t="node-cache-clear" data-t-id="${id}" data-cache-clear="${id}" title="${escapeHtml(t("modelCacheClearHelp"))}">${escapeHtml(t("modelCacheClear"))}</button>`
      : "";
    const turnOff = this.switches
      ? `<button type="button" class="cache-dir-change" data-t="node-cache-off" data-t-id="${id}" data-cache-off="${id}" title="${escapeHtml(t("modelCacheOffHelp"))}">${escapeHtml(t("modelCacheTurnOff"))}</button>`
      : "";
    return `<div class="cache-line" data-t="node-cache" data-t-id="${id}">${title}${setting}${figures}${clear}${turnOff}${folder}${line}</div>`;
  }

  /** The words for what the scout did when the setting was set: the setting, and the files that went with it — or why none did. */
  static keptWords(host, keep, answer) {
    const result = answer?.result || {};
    const kept = t("modelCacheKept", { host, n: result.keep ?? keep });
    if (result.waiting === true) return `${kept}. ${t("modelCacheNothingYet", { host })}`;
    return result.removed > 0 ? `${kept} · ${ModelCacheLine.freedWords(result)}` : kept;
  }

  static freedWords(result) {
    return t("modelCacheFreed", { size: fmtGb(Number(result?.freedBytes) || 0), n: Number(result?.removed) || 0 });
  }

  /** The box was changed: tell the scout, say what it did, and draw what the controller now holds (`refresh`). A refusal is said in the scout's
   *  words, and the box goes back to the setting the controller holds: the controller's record did not change, so the board's redraw sees no
   *  structure moved and would leave the refused number in the box. */
  static async setKeep(box, refresh) {
    const hostId = box.dataset.cacheKeep || "";
    const keep = Number(box.value);
    const node = ModelCacheLine.nodeOf(hostId);
    box.disabled = true;
    try {
      const answer = await api("/api/topology/client-llama/cache-keep", { method: "POST", body: JSON.stringify({ hostId, keep }) });
      toast(ModelCacheLine.keptWords(node?.name || hostId, keep, answer));
    } catch (err) {
      toast(err.message);
      const held = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId)).facts?.keep;
      if (held !== undefined) box.value = String(held);
    }
    box.disabled = false;
    // A box that has the focus holds the board's redraw back until it lets go: the figures below it would stay as they were.
    box.blur();
    await refresh();
  }

  /** The budget box was changed (2.38): a whole number of GB is the budget, an empty box takes it off — the last N models rule again. A number
   *  that is no budget is said, and the box goes back to what the controller holds; the scout refuses any other in its own words. */
  static async setBudget(box, refresh) {
    const hostId = box.dataset.cacheBudget || "";
    const node = ModelCacheLine.nodeOf(hostId);
    const host = node?.name || hostId;
    const text = String(box.value || "").trim();
    const gb = text === "" ? null : Number(text);
    const held = () => { box.value = String(ModelCacheLine.of(ModelCacheLine.nodeOf(hostId)).budgetGb ?? ""); };
    if (gb !== null && !(Number.isInteger(gb) && gb >= 1)) {
      toast(t("modelCacheBudgetBad"));
      held();
      return;
    }
    box.disabled = true;
    try {
      const budgetBytes = gb === null ? null : gb * ModelCacheLine.GIB;
      const answer = await api("/api/topology/client-llama/cache-budget", { method: "POST", body: JSON.stringify({ hostId, budgetBytes }) });
      const said = gb === null ? t("modelCacheBudgetOff", { host }) : t("modelCacheBudgetSet", { host, size: fmtGb(budgetBytes) });
      const result = answer?.result || {};
      toast(result.waiting === true ? `${said}. ${t("modelCacheNothingYet", { host })}`
        : result.removed > 0 ? `${said} · ${ModelCacheLine.freedWords(result)}` : said);
    } catch (err) {
      toast(err.message);
      held();
    }
    box.disabled = false;
    box.blur();
    await refresh();
  }

  /** The limit box of the folder for Strata's files was changed: a whole number of GB is the limit, an empty box gives the folder its own (300 GB). A number that is no limit is said, and
   *  the box goes back to what the controller holds; the scout refuses any other in its own words. */
  static async setWorkBudget(box, refresh) {
    const hostId = box.dataset.cacheWorkBudget || "";
    const host = ModelCacheLine.nodeOf(hostId)?.name || hostId;
    const text = String(box.value || "").trim();
    const gb = text === "" ? null : Number(text);
    const held = () => { box.value = String(ModelCacheLine.of(ModelCacheLine.nodeOf(hostId)).workBudgetGb ?? ""); };
    if (gb !== null && !(Number.isInteger(gb) && gb >= 1)) {
      toast(t("modelDiskWorkLimitBad"));
      held();
      return;
    }
    box.disabled = true;
    try {
      const answer = await api("/api/topology/client-llama/cache-work-budget", { method: "POST", body: JSON.stringify({ hostId, budgetBytes: gb === null ? null : gb * ModelCacheLine.GIB }) });
      const result = answer?.result || {};
      const said = t("modelDiskWorkLimitSet", { host, size: fmtGb(Number(result.budgetBytes) || 0) });
      toast(Number(result.removed) > 0 ? `${said} · ${ModelCacheLine.freedWords(result)}` : said);
    } catch (err) {
      toast(err.message);
      held();
    }
    box.disabled = false;
    box.blur();
    await refresh();
  }

  /** What the files of the folder a move leaves become: "move" — they go with it — or "delete"; null when the operator stepped back. Asked only when there is something there: an empty
   *  folder has nothing to carry, and is asked nothing. */
  static async carry({ title, detail, size, confirmLabel }) {
    if (!(size > 0)) return "delete";
    return appConfirmChoice(t("modelDiskCarryQuestion", { size: fmtGb(size) }), {
      title, detail, confirmLabel, choice: "move", choiceLabel: t("modelDiskCarryWhat"),
      choices: [{ value: "move", label: t("modelDiskCarryMove") }, { value: "delete", label: t("modelDiskCarryDelete") }],
    });
  }

  /** What the scout said of a folder's change: a move under way, or what went — and nothing of what went when nothing did ("Freed 0.00 GB · files deleted: 0"
   *  read as a deletion on a folder that held nothing, 2026-11-03). */
  static changedWords(result, done) {
    if (result?.moving === true) return t("modelDiskMoveStarted", { dir: result.dir || "", size: fmtGb(Number(result.totalBytes) || 0) });
    return Number(result?.removed) > 0 ? `${done} · ${ModelCacheLine.freedWords(result)}` : done;
  }

  /** "Change…" by the cache's folder (2.38; the choice, 2026-11-03): the new folder asked, then what the files of the old one become — they go with it, or they are deleted. */
  static async moveFolder(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    if (!line.folder) return;
    const typed = await appPrompt(t("modelCacheDirPrompt", { host: line.name }),
      { value: line.folder, placeholder: "/mnt/hdd/llama-model-cache", confirmLabel: t("modelCacheDirNext") });
    const path = String(typed ?? "").trim();
    if (!path || path === line.folder) return;
    const how = await ModelCacheLine.carry({ title: t("modelCacheDirTitle"), detail: `${line.folder} → ${path}`, size: line.heldBytes ?? 0, confirmLabel: t("modelCacheDirMove") });
    if (!how) return;
    await ModelCacheLine.sendFolder(line, "/api/topology/client-llama/cache-dir", { hostId, path, how }, t("modelCacheMoved", { host: line.name, dir: path }), refresh);
  }

  /** ✕ by a folder the operator chose for the cache: it goes back to the folder it lies in by itself, and what Caravan downloaded into the chosen one is deleted, after a question that names both. */
  static async removeFolder(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    if (!line.cacheChosen) return;
    const asked = await appConfirm(t("modelDiskCacheRemoveConfirm", { host: line.name, folder: line.folder, dir: line.ownFolder || "?", size: fmtGb(line.heldBytes ?? 0) }),
      { title: t("modelDiskCacheRemoveTitle"), confirmLabel: t("modelDiskRemove") });
    if (!asked) return;
    await ModelCacheLine.sendFolder(line, "/api/topology/client-llama/cache-dir", { hostId, path: "", how: "delete" }, t("modelCacheMoved", { host: line.name, dir: line.ownFolder || "?" }), refresh);
  }

  /** "Choose…" or "Change…" by the folder for Strata's files: the folder asked, then — when the cells made something where they keep it now — whether it goes with them or is deleted. */
  static async chooseWork(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    const work = line.work;
    if (!work) return;
    const typed = await appPrompt(t("modelDiskWorkPrompt", { host: line.name }),
      { value: work.chosen ? work.dir : "", placeholder: "/mnt/hdd/caravan/strata", confirmLabel: t("modelCacheDirNext") });
    const path = String(typed ?? "").trim();
    if (!path || (work.chosen && path === work.dir)) return;
    const how = await ModelCacheLine.carry({ title: t("modelDiskWorkTitle"), detail: `${work.dir} → ${path}`, size: line.workBytes ?? 0, confirmLabel: t("modelCacheDirMove") });
    if (!how) return;
    await ModelCacheLine.sendFolder(line, "/api/topology/client-llama/cache-work", { hostId, path, how }, t("modelDiskWorkSet", { host: line.name, dir: path }), refresh);
  }

  /** ✕ by the folder for Strata's files: what the cells made there is deleted, and Strata does not start until another is chosen — said before, and done after a yes. */
  static async removeWork(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    if (!line.work?.chosen) return;
    const asked = await appConfirm(t("modelDiskWorkRemoveConfirm", { host: line.name, folder: line.work.dir, size: fmtGb(line.workBytes ?? 0) }),
      { title: t("modelDiskWorkRemoveTitle"), confirmLabel: t("modelDiskRemove") });
    if (!asked) return;
    await ModelCacheLine.sendFolder(line, "/api/topology/client-llama/cache-work", { hostId, path: "", how: "delete" }, t("modelDiskWorkRemoved", { host: line.name }), refresh);
  }

  /** A folder's change sent, what the scout did said, the page drawn again; a refusal said in the scout's words. */
  static async sendFolder(line, path, body, done, refresh) {
    try {
      const answer = await api(path, { method: "POST", body: JSON.stringify(body) });
      toast(ModelCacheLine.changedWords(answer?.result || {}, done));
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** "Clear" was pressed: ask, naming how much goes and that the library keeps the models, and delete only after a yes. */
  static async clear(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    const asked = await appConfirm(t("modelCacheClearConfirm", { host: line.name, size: fmtGb(line.heldBytes ?? 0) }),
      { title: t("modelCacheClearTitle"), confirmLabel: t("modelCacheClear") });
    if (!asked) return;
    try {
      const answer = await api("/api/topology/client-llama/cache-clear", { method: "POST", body: JSON.stringify({ hostId }) });
      toast(ModelCacheLine.freedWords(answer?.result));
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** "Turn off…" was pressed. A machine that can read a model through the controller is asked nothing but the yes: no folder has to be mounted (the owner, 2026-11-02). One that cannot is asked where the
   *  library lies, when its scout did not find it by itself. The question names what a start will cost and what goes, and the cache turns off only after a yes. */
  static async turnOff(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    const typed = line.canThrough ? "" : line.library || await appPrompt(t("modelCacheOffPrompt", { host: line.name }),
      { value: line.library, placeholder: "/mnt/models", confirmLabel: t("modelCacheDirNext") });
    const library = String(typed ?? "").trim();
    if (!library && !line.canThrough) return;
    const asked = await appConfirm(t(library ? "modelCacheOffConfirm" : "modelCacheOffConfirmThrough", { host: line.name, size: fmtGb(line.heldBytes ?? 0) }),
      { title: t("modelCacheOffTitle"), ...(library ? { detail: library } : {}), confirmLabel: t("modelCacheTurnOff") });
    if (!asked) return;
    try {
      const answer = await api("/api/topology/client-llama/cache-off", { method: "POST", body: JSON.stringify({ hostId, off: true, library }) });
      const result = answer?.result || {};
      const said = library ? t("modelCacheIsOff", { host: line.name, library: result.library || library }) : t("modelCacheIsOffThrough", { host: line.name });
      toast(`${said} · ${ModelCacheLine.freedWords(result)}`);
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** "Change…" by the library: nothing goes and nothing stops, so only where it lies is asked. The cache stays as it is. */
  static async nameLibrary(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    const typed = await appPrompt(t("modelCacheOffPrompt", { host: line.name }), { value: line.library, placeholder: "/mnt/models", confirmLabel: t("modelCacheLibrarySave") });
    const library = String(typed ?? "").trim();
    if (!library || library === line.library) return;
    try {
      await api("/api/topology/client-llama/cache-off", { method: "POST", body: JSON.stringify({ hostId, off: line.off, library }) });
      toast(t("modelCacheLibraryIs", { host: line.name, library }));
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** Back from a mounted folder to the controller: nothing goes, so nothing is asked. */
  static async useThrough(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    try {
      await api("/api/topology/client-llama/cache-off", { method: "POST", body: JSON.stringify({ hostId, off: true, library: "" }) });
      toast(t("modelCacheIsOffThrough", { host: line.name }));
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** "Turn on": asked first, as Turn off is, with the cache's folder and its limit in the same window (the owner, 2026-11-03: "it turns on at once — show
   *  such a window, and let the folder and the limits be set in it"). A folder other than the present one takes the cache there first — what the old one
   *  still holds (a running cell's files outlive the turning off) is asked about as "Change…" asks, and an empty one is asked nothing — and a limit that
   *  changed is kept; then the cache turns on. A limit that is no limit is said, and nothing is sent; what the scout refuses is said in its words, and the
   *  cache stays as the scout left it. */
  static async turnOn(hostId, refresh) {
    const line = ModelCacheLine.of(ModelCacheLine.nodeOf(hostId));
    const fields = [{ key: "dir", label: t("modelCacheDirLabel"), value: line.folder, placeholder: "/mnt/ssd/llama-model-cache" }];
    if (line.budgets) {
      fields.push({ key: "budget", label: t("modelCacheBudgetLabel"), value: line.budgetGb ?? "", kind: "number", suffix: t("modelCacheGb"),
                    placeholder: t("modelCacheBudgetUnset", { n: line.facts?.keep }) });
    }
    const answer = await appConfirmFields(t("modelCacheOnConfirm", { host: line.name }),
      { title: t("modelCacheOnTitle"), confirmLabel: t("modelCacheTurnOn"), danger: false, fields });
    if (!answer) return;
    const gb = !line.budgets || answer.budget === "" ? null : Number(answer.budget);
    if (gb !== null && !(Number.isInteger(gb) && gb >= 1)) {
      toast(t("modelCacheBudgetBad"));
      return;
    }
    const moves = !!answer.dir && answer.dir !== line.folder;
    const how = moves
      ? await ModelCacheLine.carry({ title: t("modelCacheDirTitle"), detail: `${line.folder} → ${answer.dir}`, size: line.heldBytes ?? 0, confirmLabel: t("modelCacheDirMove") })
      : null;
    if (moves && !how) return;
    const send = (path, body) => api(path, { method: "POST", body: JSON.stringify({ hostId, ...body }) });
    try {
      const moved = moves ? (await send("/api/topology/client-llama/cache-dir", { path: answer.dir, how }))?.result || {} : null;
      if (line.budgets && gb !== line.budgetGb) await send("/api/topology/client-llama/cache-budget", { budgetBytes: gb === null ? null : gb * ModelCacheLine.GIB });
      await send("/api/topology/client-llama/cache-off", { off: false });
      const on = t("modelCacheIsOn", { host: line.name });
      toast(moved ? ModelCacheLine.changedWords(moved, on) : on);
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** The delete button was pressed: ask, naming the files and the size the operator sees, and delete only if the files are still that size
   *  (the scout refuses otherwise, and nothing is deleted). */
  static async deleteForeign(hostId, refresh) {
    const node = ModelCacheLine.nodeOf(hostId);
    const line = ModelCacheLine.of(node);
    const foreign = line.foreign;
    if (!foreign) return;
    const asked = await appConfirm(t("modelCacheDeleteConfirm", { host: line.name, n: foreign.files, size: fmtGb(foreign.bytes) }),
      { title: t("modelCacheDeleteTitle"), detail: line.folders().replace(/\n/g, " · "), confirmLabel: t("deleteAction") });
    if (!asked) return;
    try {
      const answer = await api("/api/topology/client-llama/cache-delete-foreign",
        { method: "POST", body: JSON.stringify({ hostId, expectBytes: foreign.bytes }) });
      toast(ModelCacheLine.freedWords(answer?.result));
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** The node of the topology the page holds now. */
  static nodeOf(hostId) {
    return (topology?.nodes || []).find((n) => String(n.id) === String(hostId)) || null;
  }

  /** Wires the box and the button of every machine under `root` (the board binds again after each redraw). `refresh` draws what the
   *  controller holds now. */
  static bind(root, refresh) {
    root?.querySelectorAll("[data-cache-keep]").forEach((box) => {
      box.addEventListener("change", () => ModelCacheLine.setKeep(box, refresh));
    });
    root?.querySelectorAll("[data-cache-budget]").forEach((box) => {
      box.addEventListener("change", () => ModelCacheLine.setBudget(box, refresh));
    });
    root?.querySelectorAll("[data-cache-work-budget]").forEach((box) => {
      box.addEventListener("change", () => ModelCacheLine.setWorkBudget(box, refresh));
    });
    root?.querySelectorAll("[data-cache-dir]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        ModelCacheLine.moveFolder(btn.dataset.cacheDir || "", refresh);
      });
    });
    for (const [hook, run] of [["cacheClear", ModelCacheLine.clear], ["cacheOff", ModelCacheLine.turnOff], ["cacheOn", ModelCacheLine.turnOn], ["cacheLibrary", ModelCacheLine.nameLibrary], ["cacheThrough", ModelCacheLine.useThrough],
                               ["cacheDirRemove", ModelCacheLine.removeFolder], ["cacheWork", ModelCacheLine.chooseWork], ["cacheWorkRemove", ModelCacheLine.removeWork]]) {
      root?.querySelectorAll(`[data-${hook.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}]`).forEach((btn) => {
        btn.addEventListener("click", (event) => {
          event.stopPropagation();
          run(btn.dataset[hook] || "", refresh);
        });
      });
    }
    root?.querySelectorAll("[data-cache-delete-foreign]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        ModelCacheLine.deleteForeign(btn.dataset.cacheDeleteForeign || "", refresh);
      });
    });
  }
}
