// How far the copy of a cell's model onto its machine has got — said for the WHOLE model, in the units the rest of these pages use.
//
// The scout reports the file it is on. A model of two parts read "28.5/29.6 GB · 96%" for its first part and began again at 0 for the
// second, and the owner (2026-10-17) asked whether the other part was as big or there was only one. The figures were also decimal
// gigabytes (1e9) where the model list, the memory estimate and /hf count binary ones (2 ** 30) and call them "GB" too: the same pack
// read 54.4 on the list and 58.4 on the card. Both the card as it is drawn and as it is patched live (topology-nodes.js,
// topology-render.js) ask this class, so the two cannot say it differently.
import { state } from "./state.js";

const PART = /^(.*)-(\d{5})-of-(\d{5})\.gguf$/i;
const PART_IN_NAME = /-(\d{5})-of-(\d{5})\.gguf/i;

export class ModelCopy {
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

  // {done, total, pct} of the copy: of the whole model when the file the scout is on is a part of a split one whose parts the
  // list knows, of that one file otherwise. The list must agree with the scout on the size of the file it is on: one that does
  // not is older than the files, and says nothing.
  static of(slot, rows) {
    const here = Number(slot.downloadedBytes || 0);
    const own = Number(slot.totalBytes || 0);
    const file = PART_IN_NAME.exec(String(slot.downloadingFile || ""));
    const sizes = file ? ModelCopy.sizes(slot, rows) : null;
    if (sizes && sizes.length === Number(file[2]) && sizes[Number(file[1]) - 1] === own) {
      const before = sizes.slice(0, Number(file[1]) - 1).reduce((sum, size) => sum + size, 0);
      return ModelCopy.said(before + here, sizes.reduce((sum, size) => sum + size, 0));
    }
    return ModelCopy.said(here, own);
  }

  static said(done, total) {
    return { done, total, pct: total > 0 ? Math.round((done / total) * 100) : null };
  }

  // The line under the card's bar: the file the scout is on (or `label` when it names none), the figures of `copy`.
  static line(copy, label) {
    return `${label} · ${ModelCopy.gb(copy.done)}/${ModelCopy.gb(copy.total)} GB${copy.pct != null ? ` · ${copy.pct}%` : ""}`;
  }
}
