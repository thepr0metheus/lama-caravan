// The start of a cell, said in its folded line (the owner, 2026-10-18: "when I start a cell, do not widen it by itself — only in the
// same thin line, the same as the card says it, without the name of the model, so it comes out shorter").
//
// A cell that was downloading, loading or warming up used to open its full card by itself (card-fold.js: "download/load progress needs
// the full card"), and the line the operator had folded it into was gone for the whole start. The line keeps the cell now, and under
// its name a thin strip says what the card's status line says — the bar and the words — in one place: the card asks this class for
// the downloading words too, so the two say the same, and the strip leaves out what the line already says, the model's name.
import { ModelCopy } from "./model-copy.js";
import { escapeHtml } from "./utils.js";

export class StartStrip {
  // The scout's label of the file it is copying, "<file> (1/2)", without the name of the model the line carries: the files of a
  // model are named after it ("Swift-Qwen3.8-GSQ-IQ3_S-00001-of-00002.gguf"), and the name said again is what made the line long.
  // A file that is not named after the model (a projector, a draft layer) is said as it is; so is a file that is nothing but the name.
  static label(file, name) {
    const text = String(file ?? "");
    const model = String(name ?? "").trim();
    if (!model || !text.toLowerCase().startsWith(model.toLowerCase())) return text;
    const rest = text.slice(model.length);
    // The name ends where a separator stands: "Qwen3" is not the name part of "Qwen3.8-…" — a dot is part of a version, not a break.
    if (!/^[\s_-]/.test(rest)) return text;
    const kept = rest.replace(/^[\s_-]+/, "");
    return kept || text;
  }

  // The words of the copy: the file, the whole model's gigabytes and the share of it (ModelCopy.line) — the file without the name.
  static words(copy, file, name) {
    return ModelCopy.line(copy, StartStrip.label(file, name));
  }

  // The strip under the line's name: the bar, and the words of the copy. `data-live-rowdl` is what the live patch rewrites between
  // two paints; `data-strip-name` is the name it leaves out.
  static download(copy, file, name) {
    const pct = copy.pct ?? 0;
    return StartStrip.wrap(`<span class="msl-bar"><span style="width:${pct}%"></span></span>`
      + `<span class="msl-text" data-live-rowdl data-strip-name="${escapeHtml(String(name ?? ""))}">${escapeHtml(StartStrip.words(copy, file, name))}</span>`);
  }

  // The strip of a start that has no bytes to count — loading, warming up, starting: the card's own status line, as it says it.
  static status(inner) {
    return inner ? StartStrip.wrap(inner) : "";
  }

  static wrap(inner) {
    return `<div class="fr-strip model-status-line" data-t="cell-row-strip">${inner}</div>`;
  }
}
