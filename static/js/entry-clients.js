// Which of the entry's clients are the caravan's own, and what a client sees: one rule for the main board's cards
// (consumers.js), its cables (cables.js) and Routing's cards (pool-board.js).
//
// The owner, 2026-10-27: Open WebUI is a client the caravan makes itself — first among the clients; then, of opencode: "let it
// work the same way". The same day, of every client: "every client we make has every model and every pool" — no sets: a client
// sees every pool and every model that runs, but what is blocked for it (rust/crates/rules/src/entry_models.rs, ClientDeny).
export class EntryClients {
  // The built-in clients, in the order they stand first — as the program's BuiltinClient.KINDS says them:
  // the name it is made with, whether it writes its models down (opencode reads no
  // /v1/models: its block gives it opencode.json), and whether there may be many (the owner, 2026-11-01: opencode's clients in one
  // block, created from it; Open WebUI one, without the plus).
  static KINDS = {
    "open-webui": { name: "Open WebUI", config: false, many: false },
    opencode: { name: "opencode", config: true, many: true },
  };

  // The kind of built-in client a client is: its route's `builtin` says it, never its name — the operator may rename it, and
  // another client may be called "openwebui". "" for any other client.
  static kind(p) {
    return p?.kind === "consumer" && Object.prototype.hasOwnProperty.call(EntryClients.KINDS, p?.builtin) ? p.builtin : "";
  }

  static builtin(p) {
    return Boolean(EntryClients.kind(p));
  }

  // Where a built-in client stands among the built-in ones: its kind's place in KINDS; any other client after them.
  static rank(p) {
    const at = Object.keys(EntryClients.KINDS).indexOf(EntryClients.kind(p));
    return at < 0 ? Infinity : at;
  }

  // What a client sees, against what a client blocked for nothing sees (`entryModels`, the controller's list of names): "unknown"
  // while either was not read — not known is never "none" —, "none", "some" when something is blocked for it, or "all".
  static sees(p, all) {
    if (!Array.isArray(p?.models) || !Array.isArray(all)) return "unknown";
    if (!p.models.length) return "none";
    return p.models.length < all.length ? "some" : "all";
  }
}
