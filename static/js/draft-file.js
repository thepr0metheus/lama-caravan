// Which speculative type a draft file is for, read from its path — the twin of
// caravan/common/draft_file.py; scripts/test_draft_file.py runs both against
// ONE table of cases. The cell editor names a draft's type here when a model is
// picked or speculation is switched on, and the board's command preview names
// it for a cell whose type is left empty. The server's builder, which launches
// the cell, reads the Python copy: two copies that drifted once already (the
// scanner offered a file in a model's mtp/ folder as its draft, and this rule
// named it draft-simple).
export class DraftFile {
  // Sidecar prefix → speculative type: upstream's own convention, matched on
  // the FIRST word of the name only, so "my-dflash-lookalike.gguf" is no sidecar.
  static PREFIXES = [
    ["dflash", "draft-dflash"],
    ["dspark", "draft-dspark"],
    ["eagle3", "draft-eagle3"],
    ["mtp", "draft-mtp"],
  ];
  // The layout before upstream's `mtp-` names: <model>/mtp/<file>. A prefix in
  // the name still outranks it.
  static MTP_FOLDER = "mtp";
  // No sidecar: a plain second model, drafted autoregressively. Not draft-mtp —
  // that aborts outright on a model with no MTP head.
  static PLAIN = "draft-simple";

  constructor(path) {
    this.path = String(path || "");
  }

  // The type the file is a sidecar for, or "" when it is none: said, not guessed.
  get sidecarType() {
    const folders = this.path.split("/");
    const name = folders.pop().toLowerCase();
    const types = new Map(DraftFile.PREFIXES);
    const head = name.split(/[-_.]/)[0];
    if (types.has(head)) return types.get(head);
    return folders.some((folder) => folder.toLowerCase() === DraftFile.MTP_FOLDER)
      ? types.get(DraftFile.MTP_FOLDER) : "";
  }

  // The type a cell with no type of its own launches the file with.
  get launchType() {
    return this.sidecarType || DraftFile.PLAIN;
  }

  // The type the cell editor writes for a cell's draft: the file's own, or —
  // with no file, for a model with an MTP head inside — its family's, else
  // draft-mtp. Picking a model and switching speculation on both write it: the
  // switch wrote the family's type over a DFlash sidecar until 2026-10-11.
  static cellType(draft, familyType) {
    return draft ? new DraftFile(draft).launchType : (familyType || "draft-mtp");
  }
}
