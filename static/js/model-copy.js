// How far the copy of a cell's model onto its machine has got — said for the WHOLE model, in the units the rest of these pages use.
//
// The scout reports the file it is on. A model of two parts read "28.5/29.6 GB · 96%" for its first part and began again at 0 for the
// second, and the owner (2026-10-17) asked whether the other part was as big or there was only one. The figures were also decimal
// gigabytes (1e9) where the model list, the memory estimate and /hf count binary ones (2 ** 30) and call them "GB" too: the same pack
// read 54.4 on the list and 58.4 on the card. Both the card as it is drawn and as it is patched live (topology-nodes.js,
// topology-render.js) ask this class, so the two cannot say it differently.
import { t } from "./i18n.js";
import { Pace } from "./pace.js";
import { state } from "./state.js";

const PART = /^(.*)-(\d{5})-of-(\d{5})\.gguf$/i;
const PART_IN_NAME = /-(\d{5})-of-(\d{5})\.gguf/i;

export class ModelCopy {
  // A part of a split GGUF by its name: its number, how many parts the name says, and the first part's path — the one an engine is
  // given for the whole model — or null for a whole file. The picker offers first parts only by it (form.js ModelChoices), and
  // /models gives a later part what its first part says (model-facts.js): a later part's header names nothing of its own.
  static part(path) {
    const named = PART.exec(String(path || ""));
    return named ? { index: Number(named[2]), count: Number(named[3]), first: `${named[1]}-00001-of-${named[3]}.gguf` } : null;
  }

  // "GB" of these pages: 2 ** 30 bytes.
  static gb(bytes) {
    return (Number(bytes || 0) / 2 ** 30).toFixed(1);
  }

  // The sizes, in order, of the parts of the split model the cell is set to run — from the model list — or null when the list
  // cannot give every one of them. The row of the FIRST part carries the size of all the parts the list found (`size`) and how
  // many it found (`partsFound`); the other parts are rows of their own, with their own sizes.
  static sizes(slot, rows) {
    const path = String((slot.slotConfig && slot.slotConfig.MODEL_FILE) || "");
    const named = PART.exec(path);
    const first = (rows || []).find((row) => row.path === path);
    if (!first || !named) return null;
    const count = Number(named[3]);
    // Only the first part's row has `parts` and `partsFound`: a cell set to run any other part gets nothing here.
    if (first.parts !== count || first.partsFound !== count) return null;
    const rest = [];
    for (let index = 2; index <= count; index++) {
      const row = (rows || []).find((r) => r.path === `${named[1]}-${String(index).padStart(5, "0")}-of-${named[3]}.gguf`);
      if (!row) return null;
      rest.push(Number(row.size));
    }
    const head = Number(first.size) - rest.reduce((sum, size) => sum + size, 0);
    return head > 0 ? [head, ...rest] : null;
  }

  // The copy of a cell's server record, against the model list the page holds now. The two places that draw the line (the card as
  // it is built, the card as it is patched live) ask THIS, with the record and nothing else, so neither can pass another list.
  static now(slot) {
    return ModelCopy.of(slot, state.models);
  }

  // {done, total, pct, rate} of the copy: of the whole model when the file the scout is on is a part of a split one whose parts
  // the list knows, of that one file otherwise. The list must agree with the scout on the size of the file it is on: one that
  // does not is older than the files, and says nothing. `rate` is how fast the scout copies, bytes a second over its last seconds
  // (scout 2.42, `downloadBytesPerSec`), null while it is not measured.
  static of(slot, rows) {
    const here = Number(slot.downloadedBytes || 0);
    const own = Number(slot.totalBytes || 0);
    const rate = Number(slot.downloadBytesPerSec);
    const file = PART_IN_NAME.exec(String(slot.downloadingFile || ""));
    const sizes = file ? ModelCopy.sizes(slot, rows) : null;
    if (sizes && sizes.length === Number(file[2]) && sizes[Number(file[1]) - 1] === own) {
      const before = sizes.slice(0, Number(file[1]) - 1).reduce((sum, size) => sum + size, 0);
      return ModelCopy.said(before + here, sizes.reduce((sum, size) => sum + size, 0), rate);
    }
    return ModelCopy.said(here, own, rate);
  }

  static said(done, total, rate = null) {
    return { done, total, pct: total > 0 ? Math.round((done / total) * 100) : null,
             rate: Number.isFinite(rate) && rate > 0 ? rate : null };
  }

  // The line under the card's bar: the file the scout is on (or `label` when it names none), the figures of `copy`, and — while
  // the scout measures it — how fast it goes and how long the rest of the model takes at that pace (the owner, 2026-10-26: "show
  // at what speed it downloads"). The speed and the time left are worded as every progress of these pages words them (Pace).
  static line(copy, label) {
    const pace = copy.rate > 0 ? [Pace.speed(copy.rate), Pace.eta((copy.total - copy.done) / copy.rate)].filter(Boolean) : [];
    // A whole not known is not said: "1.5 GB", not "1.5/0.0 GB".
    const figures = copy.total > 0 ? `${ModelCopy.gb(copy.done)}/${ModelCopy.gb(copy.total)} GB` : `${ModelCopy.gb(copy.done)} GB`;
    return `${label} · ${figures}${copy.pct != null ? ` · ${copy.pct}%` : ""}` + pace.map((words) => ` · ${words}`).join("");
  }
}

/**
 * How far a loading cell has read its model, as its scout measures it (scout 2.43; the owner, 2026-10-26: "and at what speed it
 * loads into memory — do it, I want it to work"). The scout says what the cell's processes have read (`readBytes`: the kernel's
 * count of what they read by calls or fetched from storage), how fast (`readBytesPerSec`) and what its files weigh (`modelBytes`,
 * measured by its start). Said in the copy's own words (ModelCopy.line): the bytes of the whole, the share, the speed, the time
 * left. The card, its folded line, its window and the machine's page ask this class, as they are drawn and as they are patched.
 */
export class ModelLoad {
  /** Below this share of the model, a reading that does not move is not the model's: a mapped model already in memory costs no
   *  read, and what its libraries took is a sliver — said, it would read as a load stuck at 0 %. */
  static SHOWN = 0.01;
  /** The phases in which a cell's line says its load: starting, loading, warming up — its process reads its model. */
  static ON_ITS_WAY = ["starting", "loading", "warming", "resolving"];

  /** {done, total, pct, rate} of the load, or null while there is nothing to say: no reading told, or too little that does not
   *  move. The read is capped at the whole: the libraries' bytes are not more of the model. */
  static now(server) {
    const done = Number(server?.readBytes);
    const total = Number(server?.modelBytes) > 0 ? Number(server.modelBytes) : 0;
    const rate = Number(server?.readBytesPerSec);
    if (!(done > 0)) return null;
    if (!(rate > 0) && !(total > 0 && done >= total * ModelLoad.SHOWN)) return null;
    return ModelCopy.said(total > 0 ? Math.min(done, total) : done, total, rate);
  }

  /** What a cell on its way says it does, by its phase: loading its weights into the cards or into RAM (a CPU cell), loading,
   *  or starting — with what its start's log says of where it is. */
  static label(server, phase) {
    if (phase === "warming") {
      const config = server?.slotConfig || {};
      const cpu = String(config.N_GPU_LAYERS ?? "").trim() === "0" || String(config.RUNNER || "").toLowerCase() === "moonshine";
      return t(cpu ? "topologyRemoteWarmingRam" : "topologyRemoteWarming");
    }
    const note = server?.status?.progressNote ? ` · ${server.status.progressNote}` : "";
    return t(phase === "loading" ? "topologyRemoteLoading" : "topologyRemoteStarting") + note;
  }

  /** The words of a cell on its way: its label, and the load's figures while the scout measures them. */
  static words(server, phase) {
    const load = ModelLoad.now(server);
    const label = ModelLoad.label(server, phase);
    return load ? ModelCopy.line(load, label) : label;
  }
}
