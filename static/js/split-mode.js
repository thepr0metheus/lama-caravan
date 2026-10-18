// How a model is divided between several cards, as the operator meets it.
import { fieldChoices } from "./constants.js";
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

/**
 * One value of llama-server's -sm/--split-mode, and what it means to say it.
 *
 * Four values decide something the operator cares about and cannot see:
 * whether two cards take turns on a request or work on it at once. Until now
 * they were reachable only as free text in a tab eleven tabs deep, spelled by
 * hand — a typo ("raw") reached the command line unchallenged and the cell
 * simply failed to start, with the reason in a log nobody was watching.
 *
 * The four values themselves stay in constants.js with every other field's
 * value set. This class owns what they MEAN — the labels, the hint, the one a
 * fresh multi-card selection gets — so a fifth mode is named in one place.
 * llama.cpp added "tensor" after this field was written, and the field's own
 * help text still said "none, layer, or row" the day it shipped.
 */
export class SplitMode {
  /** Offered on the tile, in the order shown. "none" ("use one GPU only") is
   *  left out on purpose: the tile appears only once two cards or more are
   *  picked, and that value contradicts the choice just made. It stays
   *  typeable in the Devices field, whose list carries all four. */
  static SHOWN = ["layer", "row", "tensor"];
  /** The modes that divide every weight between the cards instead of handing
   *  each card whole layers — the ones that make the cards work at once. */
  static PARALLEL = ["row", "tensor"];
  /** What a fresh multi-card selection gets: "layer", llama.cpp's own default and
   *  the one mode that starts on every build. It was "row" (asked for 2026-09-21:
   *  tensor by default; the newer "tensor" is marked EXPERIMENTAL by llama.cpp,
   *  so a default is not that either) until the campaign of 2026-10-17. On the
   *  machine with a 3090 and a 5090 (llama.cpp b1141) every start with "row"
   *  died on "device CUDA0 does not support split buffers" — llama.cpp removed
   *  row split from its CUDA backend on 2026-07-06 (#24216), the flag stayed —
   *  so the first
   *  multi-card choice an operator makes — a click on the cards — was the one
   *  that could not start, with a card that said only "Model loading failed".
   *  Llama 3.3 70B there, 300 tokens: layer 25.8 t/s, tensor 32.0, tensor with a
   *  split by the cards' sizes 36.0. The faster modes are one click away, and a
   *  start that fails on "row" now says why, by name (classifyLlamaError). */
  static DEFAULT = "layer";

  constructor(value) {
    this.value = String(value ?? "").trim().toLowerCase();
  }

  /** The legal values, from the one table that already holds them. */
  static get VALUES() { return fieldChoices.SPLIT_MODE; }

  /** Whether llama-server knows this value. An empty field is NOT unknown —
   *  it means llama.cpp picks, which is a different statement and a legal one,
   *  so it answers false here and gets no warning. */
  get known() { return SplitMode.VALUES.includes(this.value); }
  get parallel() { return SplitMode.PARALLEL.includes(this.value); }

  /** Whether, with no --tensor-split given, this mode cuts every weight into EQUAL parts whatever the cards hold. "layer" and
   *  "row" follow the cards' FREE memory (llama.cpp reads it at load); "tensor" does not: 21.1 + 21.4 GB of a 39.6 GB model on a
   *  24 GB and a 32 GB card (2026-10-17). A model over twice the smaller card then overflows it with room left on the other. */
  get evenByDefault() { return this.value === "tensor"; }

  /** The --tensor-split to write for these cards (the picked ones, in the order llama.cpp sees them): their sizes in GB, as
   *  proportions — "24,32" for a 3090 and a 5090, which took the 70B from 32.0 to 36.0 t/s. Empty for a mode that divides by
   *  free memory on its own, and for cards of one size (within a tenth): "1,1" would be noise in the command. */
  suggestedSplit(cards) {
    if (!this.evenByDefault) return "";
    const sizes = (cards || []).map((c) => Math.round(Number(c?.memoryTotalMiB || 0) / 1024));
    if (sizes.length < 2 || sizes.some((gb) => !(gb > 0))) return "";
    return Math.max(...sizes) - Math.min(...sizes) > Math.max(...sizes) * 0.1 ? sizes.join(",") : "";
  }

  label() {
    return { layer: t("splitLayer"), row: t("splitRow"), tensor: t("splitTensor") }[this.value]
      || this.value;
  }

  /** One line on what the chosen mode does. Empty for a mode with nothing to
   *  say about it — an empty hint is left out rather than drawn as a blank
   *  line that reads like a missing translation. */
  hint() {
    if (!SplitMode.SHOWN.includes(this.value)) return "";
    // "row" has a hint of its own: llama.cpp took it out of the CUDA backend on 2026-07-06 ("CUDA: remove -sm row", #24216),
    // so on an NVIDIA build from then on it cannot start — said where the tile is, with the names of the two that can.
    if (this.value === "row") return t("splitHintRow", { layer: t("splitLayer"), tensor: t("splitTensor") });
    return this.parallel ? t("splitHintParallel") : t("splitHintLayer");
  }

  /** The value to write when `cards` cards are selected. One card has nothing
   *  to divide, so the flag is not printed at all; more than one keeps a
   *  choice the operator has already made and fills a blank with the default —
   *  re-picking a card must not quietly undo the mode they chose. */
  forCards(cards) {
    if (Number(cards) <= 1) return "";
    return SplitMode.SHOWN.includes(this.value) ? this.value : SplitMode.DEFAULT;
  }

  /** The segmented control, with `hook` the data-t name of one button. */
  html(hook) {
    const seg = SplitMode.SHOWN.map((v) => {
      const mode = new SplitMode(v);
      const exp = v === "tensor"
        ? `<span class="compute-split-exp">${escapeHtml(t("splitExperimental"))}</span>` : "";
      return `<button type="button" class="compute-split-btn${v === this.value ? " on" : ""}"`
        + ` data-split="${v}" data-t="${hook}" data-t-id="${v}"`
        + ` title="${escapeHtml([mode.label(), mode.hint()].filter(Boolean).join(" · "))}">`
        + `${escapeHtml(mode.label())}${exp}</button>`;
    }).join("");
    // A value llama-server does not know is said out loud, here, where it was
    // typed — not left to look like one more mode with no button lit.
    const warn = this.value && !this.known
      ? `<p class="compute-split-warn">⚠ ${escapeHtml(t("splitUnknown", { value: this.value }))}</p>`
      : "";
    const hint = this.hint()
      ? `<p class="compute-split-hint">${escapeHtml(this.hint())}</p>` : "";
    return `<div class="compute-split">`
      + `<div class="compute-split-label">${escapeHtml(t("splitMode"))}</div>`
      + `<div class="compute-split-seg">${seg}</div>${warn}${hint}</div>`;
  }
}
