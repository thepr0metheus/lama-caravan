// A text chat with a cell from its window's Talk tab (1.3.624): a typed question, the model's words back, and what the server said
// of them — the tokens it wrote and how fast it read and wrote. The page asks the controller (POST /api/cell-talk {cellId}, mode
// text-chat), and the controller asks the cell on the port its run leased: the board is https and the cell plain http, and the
// controller asks only the mode's one path (/v1/chat/completions) — the window is no door into the cell
// (rust/crates/admin/src/fleet/cell_talk.rs).
//
// The talk is kept here, by cell id, and not in the window: the board repaints the lane wholesale, and a talk drawn only into the
// window would go with the next repaint, the typed draft with it. The window draws it from here (html).
import { t } from "./i18n.js";
import { api, escapeHtml } from "./utils.js";

export class CellChat {
  /** The chat's data-t names (docs/testability.md), data-t-id = the cell's id. The section's data-t-state says idle, busy (an
   *  answer is awaited) or off (the cell does not run); a message's says user, answer or error. */
  static HOOKS = { view: "cell-chat", draft: "cell-chat-draft", send: "cell-chat-send", clear: "cell-chat-clear", turn: "cell-chat-turn" };
  /** The controller's mode (cell_talk.TextChat). */
  static MODE = "text-chat";

  constructor({ call = api } = {}) {
    this.call = call;
    // cellId → {turns: [{role, text, error, ms, tokens, speed}], draft, busy, model}
    this.cells = new Map();
    this.bound = false;
  }

  /** True when the window offers a text chat: the runner answers it (its talk modes) and the cell is a chat — an embedding server
   *  of the same runner is not (its job). */
  static offered(spec, jobs) {
    return !!spec && Array.isArray(spec.modes) && spec.modes.includes(CellChat.MODE) && Array.isArray(jobs) && jobs.includes("llm");
  }

  of(cellId) {
    return { turns: [], draft: "", busy: false, ...(this.cells.get(String(cellId)) || {}) };
  }

  /** The talk of `cellId` is held with `model`: a talk is the model's it was had with. Kept by the cell's port, a cell made anew
   *  on the port of a deleted one showed the deleted cell's questions and answers, a gemma's speeds under a Hermes, as its own
   *  (2026-10-26); a new cell has an id of its own now, and the model still parts the talks of one cell given another model. A
   *  model not said keeps the talk as it is, and so does an answer still awaited. */
  heldWith(cellId, model) {
    const k = String(cellId);
    const m = String(model || "");
    if (!m) return;
    const s = this.of(k);
    if (s.model && s.model !== m && !s.busy) this.cells.set(k, { turns: [], draft: "", busy: false, model: m });
    else if (s.model !== m && !s.busy) this.cells.set(k, { ...s, model: m });
  }

  /** What goes with a new message: as many of the last question-and-answer pairs as fit in `carried - 1` messages. Whole pairs:
   *  an answer without its question reads as the model's own words out of nowhere. A question whose answer failed was never
   *  answered, and goes with its failure (two questions in a row are a conversation some models refuse). */
  history(cellId, carried) {
    const turns = this.of(cellId).turns;
    const said = [];
    for (let i = 0; i < turns.length; i += 1) {
      const turn = turns[i];
      const reply = turns[i + 1];
      if (turn.role === "user" && reply?.role === "assistant" && !reply.error) {
        said.push({ role: "user", text: turn.text }, { role: "assistant", text: reply.text });
        i += 1;
      }
    }
    const pairs = Math.floor(Math.max(0, (Number(carried) || 1) - 1) / 2);
    return pairs ? said.slice(-2 * pairs) : [];
  }

  /** The words under an answer: how many tokens it wrote, how fast it wrote and read, how long it took — what the server and the
   *  controller said; a part nobody said is left out. `format` is the board's writing of a speed (polling.js formatTps). */
  static meta(turn, format = (n) => String(n)) {
    const parts = [];
    if (turn.tokens?.written > 0) parts.push(t("cwChatTokens", { n: String(turn.tokens.written) }));
    if (turn.speed?.written > 0) parts.push(t("cwChatWriting", { tps: format(turn.speed.written) }));
    if (turn.speed?.read > 0) parts.push(t("cwChatReading", { tps: format(turn.speed.read) }));
    if (turn.ms?.total > 0) parts.push(t("cwChatSeconds", { s: (turn.ms.total / 1000).toFixed(1) }));
    return parts.join(" · ");
  }

  turnHtml(cellId, turn, format) {
    const k = escapeHtml(String(cellId));
    const hook = `data-t="${CellChat.HOOKS.turn}" data-t-id="${k}"`;
    if (turn.role === "user") return `<div class="cw-turn me" ${hook} data-t-state="user">${escapeHtml(turn.text)}</div>`;
    const meta = CellChat.meta(turn, format);
    const tail = meta ? `<div class="cw-turn-meta">${escapeHtml(meta)}</div>` : "";
    if (turn.error) {
      return `<div class="cw-turn it bad" ${hook} data-t-state="error" role="alert"><div class="cw-turn-text">${escapeHtml(turn.error)}</div>${tail}</div>`;
    }
    const words = turn.text ? escapeHtml(turn.text) : `<em>${escapeHtml(t("cwChatNoWords"))}</em>`;
    return `<div class="cw-turn it" ${hook} data-t-state="answer"><div class="cw-turn-text">${words}</div>${tail}</div>`;
  }

  /** The Talk tab's chat of cell `cellId`. `running`: it can be asked; `carried` how many messages one request carries (the
   *  runner's talk.turns); `model` the cell's model, which the talk is held with (heldWith). No link to the server's own page:
   *  a cell listens on its machine's loopback since 2026-11-08, out of a browser's reach. */
  html(cellId, { running = false, carried = 8, format, model = "" } = {}) {
    this.heldWith(cellId, model);
    const s = this.of(cellId);
    const k = escapeHtml(String(cellId));
    const H = CellChat.HOOKS;
    const state = !running ? "off" : s.busy ? "busy" : "idle";
    const turns = s.turns.map((turn) => this.turnHtml(cellId, turn, format)).join("");
    const waiting = s.busy
      ? `<div class="cw-turn it wait"><span class="topology-spinner" aria-hidden="true"></span> ${escapeHtml(t("cwChatWaiting"))}</div>` : "";
    const log = turns || waiting ? `<div class="cw-chat-turns" aria-live="polite">${turns}${waiting}</div>` : "";
    const clear = s.turns.length
      ? `<button type="button" class="cw-btn" data-cell-chat-clear="${k}" data-t="${H.clear}" data-t-id="${k}"${s.busy ? " disabled" : ""}>`
        + `${escapeHtml(t("cwChatClear"))}</button>` : "";
    const ask = running
      ? `<textarea class="cw-chat-draft" rows="3" data-cell-chat-draft="${k}" data-t="${H.draft}" data-t-id="${k}"`
        + ` placeholder="${escapeHtml(t("cwChatPlaceholder"))}" aria-label="${escapeHtml(t("cwChatDraftLabel"))}"${s.busy ? " disabled" : ""}>`
        + `${escapeHtml(s.draft)}</textarea>`
        + `<div class="cw-chat-foot"><span class="cw-chat-memory">${escapeHtml(t("cwChatMemory", { n: String(Math.max(1, Number(carried) || 1)) }))}</span>`
        + `<span class="cw-chat-gap"></span>${clear}<button type="button" class="cw-btn primary" data-cell-chat-send="${k}" data-t="${H.send}"`
        + ` data-t-id="${k}"${s.busy ? " disabled" : ""}>${escapeHtml(t("cwChatSend"))}</button></div>`
      : `<p class="cw-empty">${escapeHtml(t("cwChatOff"))}</p>${clear ? `<div class="cw-buttons">${clear}</div>` : ""}`;
    return `<section class="cw-sec cw-chat" data-cell-chat-view="${k}" data-cell-chat-carried="${escapeHtml(String(carried))}"`
      + ` data-t="${H.view}" data-t-id="${k}" data-t-state="${state}" data-cell-chat-model="${escapeHtml(s.model || "")}">`
      + `<p class="cw-lead">${escapeHtml(t("cwChatLead"))}</p>${log}${ask}</section>`;
  }

  /** Keeps what is typed, so a repaint of the lane gives it back. */
  draft(cellId, text) {
    this.cells.set(String(cellId), { ...this.of(cellId), draft: String(text ?? "") });
  }

  /** Sends what is typed, with the talk so far, and keeps the answer — the model's words and counts, or the refusal's own words.
   *  Nothing is sent while an answer is awaited, nor an empty message. The controller is asked by the cell's id alone: it knows
   *  the port the cell's run leased, and a cell that does not run has none. */
  async send(cellId, { carried = 8, doc = globalThis.document, format } = {}) {
    const k = String(cellId);
    const s = this.of(k);
    const text = s.draft.trim();
    if (!text || s.busy) return s;
    const history = this.history(k, carried);
    this.cells.set(k, { ...s, turns: [...s.turns, { role: "user", text }], draft: "", busy: true });
    this.paint(doc, k, { format });
    let answer;
    try {
      const got = await this.call("/api/cell-talk", {
        method: "POST", body: JSON.stringify({ cellId: k, mode: CellChat.MODE, text, history }) });
      answer = got?.error
        ? { role: "assistant", error: String(got.error), ms: got.ms || null }
        : { role: "assistant", text: String(got?.text || ""), ms: got?.ms || null, tokens: got?.tokens || null, speed: got?.speed || null };
    } catch (e) {
      answer = { role: "assistant", error: String(e?.message || e) };
    }
    const now = this.of(k);
    this.cells.set(k, { ...now, turns: [...now.turns, answer], busy: false });
    this.paint(doc, k, { format, focus: true });
    return this.of(k);
  }

  /** Forgets the talk of `cellId` (not while an answer is awaited: it would come into an empty talk). */
  clear(cellId, doc = globalThis.document) {
    const s = this.of(cellId);
    if (s.busy) return s;
    this.cells.set(String(cellId), { ...s, turns: [] });
    this.paint(doc, String(cellId));
    return this.of(cellId);
  }

  /** Draws the chat of `cellId` again where it stands in `doc`, at its newest message; `focus` gives the typing back. */
  paint(doc, cellId, { format, focus = false } = {}) {
    const esc = globalThis.CSS?.escape ? globalThis.CSS.escape(cellId) : String(cellId).replace(/["\\]/g, "\\$&");
    const view = doc?.querySelector?.(`[data-cell-chat-view="${esc}"]`);
    if (!view) return;
    const running = view.dataset?.tState !== "off";
    view.outerHTML = this.html(cellId, { running, carried: view.dataset?.cellChatCarried, format,
                                         model: view.dataset?.cellChatModel || "" });
    const turns = doc.querySelector?.(`[data-cell-chat-view="${esc}"] .cw-chat-turns`);
    if (turns) turns.scrollTop = turns.scrollHeight;
    if (focus) doc.querySelector?.(`[data-cell-chat-view="${esc}"] .cw-chat-draft`)?.focus?.();
  }

  /** Once, on the document (the lanes are repainted wholesale): Send and Clear, Enter in the message (Shift+Enter is a new line,
   *  and a word still being composed by an input method is not sent), and what is typed. */
  bind(doc = globalThis.document, { format } = {}) {
    if (this.bound || !doc) return;
    this.bound = true;
    this.format = format;
    doc.addEventListener("click", (e) => this.onClick(e, doc));
    doc.addEventListener("keydown", (e) => this.onKey(e, doc));
    doc.addEventListener("input", (e) => this.onInput(e));
  }

  carriedOf(el) {
    return Number(el?.closest?.("[data-cell-chat-view]")?.dataset?.cellChatCarried) || 8;
  }

  onClick(e, doc = globalThis.document) {
    const send = e.target?.closest?.("[data-cell-chat-send]");
    if (send) return this.send(send.dataset.cellChatSend, { carried: this.carriedOf(send), doc, format: this.format });
    const clear = e.target?.closest?.("[data-cell-chat-clear]");
    if (clear) return this.clear(clear.dataset.cellChatClear, doc);
    return null;
  }

  onKey(e, doc = globalThis.document) {
    const box = e.target?.closest?.("[data-cell-chat-draft]");
    if (!box || e.key !== "Enter" || e.shiftKey || e.isComposing) return null;
    e.preventDefault?.();
    this.draft(box.dataset.cellChatDraft, box.value);
    return this.send(box.dataset.cellChatDraft, { carried: this.carriedOf(box), doc, format: this.format });
  }

  onInput(e) {
    const box = e.target?.closest?.("[data-cell-chat-draft]");
    if (!box) return null;
    this.draft(box.dataset.cellChatDraft, box.value);
    return this.of(box.dataset.cellChatDraft).draft;
  }
}

export const CELL_CHAT = new CellChat();
