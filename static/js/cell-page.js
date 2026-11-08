/**
 * The page a running cell serves itself (PersonaPlex's), opened from its card: a link to the https address its config
 * names, through the reverse proxy in front of the cell. A microphone needs a secure page, and the cell answers plain
 * http in the LAN — so the link goes to that name, never to the cell's own address.
 *
 * Which config field holds the address, and the form an address must have, are the runner's to say
 * (state.runners[].page: {field, pattern} — rust/crates/admin/src/domain/runner/mod.rs PageSpec, which checks the same form at the save).
 * The link opens in this tab, as everything of the caravan does (scripts/check_same_tab_links.py).
 */
import { t } from "./i18n.js";
import { runnerRegistry } from "./llama-edit.js";
import { escapeHtml } from "./utils.js";

/** A cell as its card links its page: its id (the link's hooks name the cell by it — a cell holds a port only while it runs),
 *  its runner, its config. */
export class PageCell {
  constructor({ cellId, runner = "", config = {} } = {}) {
    this.cellId = String(cellId || "");
    this.runner = String(runner || "");
    this.config = config || {};
  }

  /** The runner's page (its registry row's `page`: the field and the pattern), or null when it serves none. */
  get spec() {
    const page = runnerRegistry().find((r) => r.id === this.runner)?.page;
    return page?.field ? page : null;
  }

  /** What the config names in the runner's field, trimmed: "" when it names nothing. */
  get named() {
    const spec = this.spec;
    return spec ? String(this.config[spec.field] ?? "").trim() : "";
  }

  /** The page's address: what the config names when it has the runner's form — matched whole, ignoring case, as the
   *  server matches it — else "". No link is drawn to anything else. */
  get address() {
    const named = this.named;
    if (!named) return "";
    let form;
    try {
      form = new RegExp(`^(?:${this.spec.pattern})$`, "i");
    } catch {
      return "";
    }
    return form.test(named) ? named : "";
  }

  /** The card's page link: open on a running cell whose config names its page; shut, saying why, when it names none,
   *  names something that is no page's address, or the cell is stopped; none for a runner that serves no page.
   *  `running` is the card's own word. */
  buttonHtml(running) {
    const spec = this.spec;
    if (!spec) return "";
    const label = `🌐<span class="nab-lbl">${escapeHtml(t("pageOpen"))}</span>`;
    const shut = (why) => `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(why)}">${label}</button>`;
    if (!this.named) return shut(t("pageNeedsUrl", { field: spec.field }));
    const address = this.address;
    if (!address) return shut(t("pageBadUrl", { field: spec.field }));
    if (!running) return shut(t("pageOpenStopped"));
    const id = this.cellId;
    return `<a class="node-action-btn ok page" href="${escapeHtml(address)}" data-t="cell-page" data-t-id="${escapeHtml(id)}"`
      + ` data-cell-page="${escapeHtml(id)}" title="${escapeHtml(t("pageOpenTitle", { address }))}">${label}</a>`;
  }
}
