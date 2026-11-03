// The owner's like or dislike of a model (rust/crates/admin/src/models/notes.rs, ModelRatings; the owner, 2026-10-31: "likes or dislikes on the
// models at /machine, so that later, where we choose them and in the store of saved models, these marks are seen"). One mark for all its
// quants, kept by the model's folder as its description is. One rule for what a mark is called and drawn, on every page that shows one:
// /hf does not load the shared dictionary, so a page hands in its own words. A model with no mark draws nothing: no mark is no opinion.
import { LibraryPath } from "./library-path.js";
import { escapeHtml } from "./utils.js";

export class ModelRating {
  static GLYPHS = { like: "👍", dislike: "👎" };
  static WORDS = { like: "ratingLike", dislike: "ratingDislike" };

  /** Whether a word is a mark: not whatever an object happens to answer to ("constructor"). */
  static isMark(word) {
    return Object.prototype.hasOwnProperty.call(ModelRating.GLYPHS, word);
  }

  /** The mark on a model's folder in the controller's map, or "": anything else there is no mark. */
  static of(ratings, model) {
    const said = model && Object.prototype.hasOwnProperty.call(ratings || {}, model) ? ratings[model] : "";
    return ModelRating.isMark(said) ? said : "";
  }

  /** The mark of the model a path of the library lies in. */
  static ofPath(ratings, path) {
    return ModelRating.of(ratings, new LibraryPath(path).model());
  }

  /** What a press leaves: the mark pressed, or none when it was that one already. */
  static pressed(current, kind) {
    return current === kind ? "" : kind;
  }

  /** The mark as a list shows it. */
  static markHtml(rating, words) {
    if (!ModelRating.isMark(rating)) return "";
    const said = escapeHtml(words(ModelRating.WORDS[rating]));
    return `<span class="model-rating" data-t="model-rating" data-t-state="${rating}" title="${said}" aria-label="${said}">${ModelRating.GLYPHS[rating]}</span>`;
  }

  /** The two buttons that set it: `hook` the attribute a test finds them by, spelled whole where it is given (scripts/testability_names.py
   *  reads it there), `cls` the box's class where a page places it. */
  static buttonsHtml(model, rating, words, { cls = "", hook = "" } = {}) {
    const name = escapeHtml(String(model));
    const one = (kind) => {
      const said = escapeHtml(words(ModelRating.WORDS[kind]));
      const on = rating === kind;
      return `<button type="button" class="model-rate-btn${on ? " is-on" : ""}" aria-pressed="${on}" data-model-rate="${kind}" data-model-rate-for="${name}"`
        + ` ${hook} data-t-id="${name}:${kind}" title="${said}" aria-label="${said}">${ModelRating.GLYPHS[kind]}</button>`;
    };
    return `<span class="${escapeHtml(cls)}">${one("like")}${one("dislike")}</span>`;
  }

  /** A button's look when the model's mark is `rating`, written in place by the rule its drawing uses. */
  static mark(button, rating) {
    const on = button.dataset.modelRate === rating;
    button.classList?.toggle?.("is-on", on);
    button.setAttribute?.("aria-pressed", String(on));
  }
}
