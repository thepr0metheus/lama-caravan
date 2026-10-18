// A machine's model cache, said on its card (1.3.576). The owner, 2026-10-18, when the disk of a machine was 94 % full of model copies and a
// start died with "No space left on device": keep in the cache only the last models, from 1 to 5, 1 by default; show the setting somewhere
// noticeable; delete everything older by itself. The scout does it (caravan-scout 2.34, cache_keeper.py) and reports `modelCache` with the
// setting and the figures; this is the line on the caravan's group of the machine's card — the setting as a box to choose from, what the cache
// holds, what the disk has left — and, when the folder holds files the scout did not download (it never deletes those by itself), a line that
// says so with a button to delete them after a question that names the size.
//
// A scout older than 2.34 reports nothing about its cache: no line is drawn for it — never a line with a setting made up.
//
// The same figures give the sign on the machine's head, on the main board's glance too (the owner, 2026-10-18, asked for it after the disk of
// a machine filled up): "⚠ disk 94% full" when the cache folder's disk is used DISK_LOW_USED_PCT % or more.
import { appConfirm } from "./dialogs.js";
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

  /** What makes the card be drawn again when it moves: the setting, whether (and how much) foreign files lie there, and whether the disk is almost full
   *  (the sign comes and goes). The figures that move with every download — what the cache holds, what the disk has left, how full it is — are patched
   *  in place (`figures()`, `diskWords()`), not drawn again. */
  fingerprint() {
    if (!this.drawn) return "-";
    const foreign = this.foreign ? `${this.foreign.files}/${this.foreign.bytes}` : "none";
    return `${this.facts.keep}:${foreign}:${this.heldBytes === null ? 0 : 1}${this.disk ? 1 : 0}${this.diskLow ? "!" : ""}`;
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
    return `<div class="cache-line" data-t="node-cache" data-t-id="${id}">`
      + `<span class="cache-title" title="${help}">${escapeHtml(t("modelCacheHead"))}</span>`
      + `<label class="cache-keep-label" title="${help}"><span>${escapeHtml(t("modelCacheKeepLabel"))}</span>`
      + `<select class="cache-keep" data-t="node-cache-keep" data-t-id="${id}" data-cache-keep="${id}">${options}</select></label>`
      + `<span class="cache-figures" data-t="node-cache-figures" data-t-id="${id}" data-live-cachefigures>${escapeHtml(this.figures())}</span>`
      + `${line}</div>`;
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
    root?.querySelectorAll("[data-cache-delete-foreign]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        ModelCacheLine.deleteForeign(btn.dataset.cacheDeleteForeign || "", refresh);
      });
    });
  }
}
