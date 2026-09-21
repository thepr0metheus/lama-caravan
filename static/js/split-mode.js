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
  /** What a fresh multi-card selection gets (asked for 2026-09-21: tensor by
   *  default). "row" and not the newer "tensor", which llama.cpp itself marks
   *  EXPERIMENTAL — a default is what an operator gets without asking for it,
   *  and both are tensor-parallel. "tensor" is one click away. */
  static DEFAULT = "row";

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

  label() {
    return { layer: t("splitLayer"), row: t("splitRow"), tensor: t("splitTensor") }[this.value]
      || this.value;
  }

  /** One line on what the chosen mode does. Empty for a mode with nothing to
   *  say about it — an empty hint is left out rather than drawn as a blank
   *  line that reads like a missing translation. */
  hint() {
    if (!SplitMode.SHOWN.includes(this.value)) return "";
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
