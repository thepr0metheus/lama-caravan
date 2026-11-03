// Where a model of the caravan's library is shown in the caravan's own pages. The library lays a download out as
// <model>/<author>/<quant>/<file> — /hf names the folders so — and the models page (/models) and our Hugging Face page (/hf) are
// asked by those folders. One rule for the 🤗 on the models page's branches and the cell window's two links (1.3.660; the owner,
// 2026-10-26: "a link to the model in our storage, and to our page on HF").

/**
 * A model's path in the library, and what the caravan's pages are asked for it.
 *
 * A path of the machine's own disk ("/home/…") is not the library's: it says nothing of the folders the pages know, and gives no
 * link. Nor does a path that climbs out ("..").
 */
export class LibraryPath {
  /** A folder's name as Hugging Face spells a part of a repository's id: what /hf can be asked by. */
  static HF_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

  /** What /hf is asked for a branch of the library: an author's branch (`model`, `author`) is a repository, `<author>/<model>`,
   *  and /hf opens it; a model's branch (no author), its name, which finds every author's build. "" for a folder not laid out
   *  that way: "(root)", "·", a cache folder (`models--…`), the author "default". */
  static hfQuery(model, author = null) {
    const name = String(model ?? "");
    if (!LibraryPath.HF_ID.test(name) || name.startsWith("models--")) return "";
    if (author === null) return name;
    const who = String(author ?? "");
    return LibraryPath.HF_ID.test(who) && who !== "default" ? `${who}/${name}` : "";
  }

  /** @param ref the model's path as a cell's config names it (MODEL_FILE): relative to the library, "/"-separated. */
  constructor(ref) {
    const text = String(ref ?? "").trim();
    const parts = text.split("/").filter(Boolean);
    this.parts = text.startsWith("/") || parts.includes("..") ? [] : parts;
  }

  /** The model a path lies in: its top folder, what /models draws on the first level of its tree — "" for a file straight in the
   *  library, which names no model. The browser's copy of ModelNotes.model_of (rust/crates/admin/src/models/notes.rs), held by one table of cases. */
  model() {
    return this.parts.length > 1 ? this.parts[0] : "";
  }

  /** What a list of models calls a path: its model's folder, or the file itself when it lies straight in the library; "" for a path that
   *  is not the library's. */
  listed() {
    return this.model() || this.parts[0] || "";
  }

  /** The build a path lies in: its quant's folder, of a path laid out as /hf lays it; "" for another. */
  quant() {
    return this.parts.length >= 4 ? this.parts[2] : "";
  }

  /** What the models page is asked for: the quant's folder of a path laid out as /hf lays it — every file of it, a GGUF of
   *  several parts and a model that is a folder alike — and the path itself when it is not; "" for none. */
  modelsQuery() {
    if (!this.parts.length) return "";
    return this.parts.length >= 3 ? `${this.parts.slice(0, 3).join("/")}/` : this.parts.join("/");
  }

  /** The repository on Hugging Face its folders name, or "". */
  hfRepo() {
    return this.parts.length >= 3 ? LibraryPath.hfQuery(this.parts[0], this.parts[1]) : "";
  }

  /** The two pages' addresses: {models, hf}, each "" when the path gives none. */
  links() {
    const models = this.modelsQuery();
    const hf = this.hfRepo();
    return { models: models ? `/models?q=${encodeURIComponent(models)}` : "", hf: hf ? `/hf?q=${encodeURIComponent(hf)}` : "" };
  }
}
