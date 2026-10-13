// Adding a machine's scout from the board: the one way a machine that lends
// its GPU or CPU joins the fleet.
import { t } from "./i18n.js";
import { refreshTopology } from "./topology-render.js";
import { $, api, escapeHtml } from "./utils.js";

/**
 * The address box under the Machines head. The machine only installs its scout
 * (caravan-scout ./install.sh, which prints its address and port); the
 * operator enters that address here, and the controller pairs the scout:
 * reads it, hands it the controller's address and fleet token, and waits for
 * its first heartbeat (POST /api/topology/scout/connect). Connecting a scout
 * that is already here again is the connection test.
 *
 * The block is static markup next to the lane, not part of it: the lane is
 * repainted every few seconds, and an address typed into it would be wiped
 * mid-word. It says so (data-survives-render), so its focused field does not
 * hold the board's repaint back the way a field inside the board does.
 *
 * Its state is written on the block (data-t-state: idle | working | ok |
 * error) so a check reads the outcome without parsing the text.
 *
 * The box opens by two buttons in the Machines head, where "+ New pool" stands
 * for the pools (the owner, 2026-10-11): ＋ Add scout, and 🔍 Find, the scan.
 * Closed, it takes none of the lane's room. A page without them keeps the box
 * open, as it always was.
 */
export class ScoutAddForm {
  constructor(root, { opener = null, finderButton = null } = {}) {
    this.root = root;
    this.opener = opener;
    this.address = root.querySelector("[data-scout-add-address]");
    this.port = root.querySelector("[data-scout-add-port]");
    this.button = root.querySelector("[data-scout-add-connect]");
    this.status = root.querySelector("[data-scout-add-status]");
    // 🔍, where the page has it: a scan of the home network.
    this.finder = root.querySelector("[data-scout-find]") ? new ScoutFinder(this, root, { toggleButton: finderButton }) : null;
  }

  static mount(doc = document) {
    const root = doc.getElementById("scoutAdd");
    if (!root || root.dataset.bound) return null;
    root.dataset.bound = "1";
    const head = (sel) => doc.querySelector?.(sel) || null;
    const form = new ScoutAddForm(root, { opener: head("[data-scout-add-open]"), finderButton: head("[data-scout-add-find]") });
    form.bind();
    return form;
  }

  bind() {
    this.opener?.addEventListener("click", () => this.open());
    this.button.addEventListener("click", () => this.connect());
    for (const field of [this.address, this.port]) {
      field.addEventListener("keydown", (e) => { if (e.key === "Enter") this.connect(); });
    }
    this.finder?.bind();
  }

  say(state, text) {
    this.root.dataset.tState = state;
    this.status.textContent = text;
  }

  // ＋ Add scout opens the box and puts the caret in the address; pressed again, it closes the box,
  // and the scan with it.
  open(on = !!this.root.hidden) {
    this.root.hidden = !on;
    this.opener?.setAttribute("aria-expanded", String(on));
    if (on) this.address.focus?.();
    else if (this.finder && !this.finder.panel.hidden) this.finder.toggle();
    return on;
  }

  async connect() {
    const address = this.address.value.trim();
    const port = this.port.value.trim();
    if (!address) {
      this.say("error", t("scoutAddEmpty"));
      this.address.focus();
      return;
    }
    this.button.disabled = true;
    this.say("working", t("scoutAddWorking", { url: `${address}:${port || "8092"}` }));
    try {
      const res = await api("/api/topology/scout/connect", { method: "POST", body: { address, port } });
      this.say("ok", t("scoutAddDone", { name: res.name || res.hostId || address, version: res.scoutVersion || "?" }));
      this.address.value = "";
      refreshTopology().catch(() => {});
    } catch (e) {
      this.say("error", String(e?.message || e));
    } finally {
      this.button.disabled = false;
    }
  }
}

/**
 * 🔍 Find: which machines of the home network answer as a
 * caravan-scout (the owner, 2026-10-11: "add scanning the local network").
 * The controller knocks on every address of the networks asked — its own /24s
 * when none is typed — and asks those that answer the scout's open
 * /api/pairing (POST /api/topology/scout/scan). A found scout is free, already
 * on the board, or held by another caravan; a free one's Connect fills the
 * fields and pairs it as if typed. The networks typed last are remembered in
 * this browser, a convenience only: the field works without them.
 *
 * The panel's state is on it (data-t-state: idle | working | found | none |
 * error), as the form's is on the form.
 */
export class ScoutFinder {
  static MEMORY = "caravan.scoutFindNetworks";

  constructor(form, root, { call = api, memory = globalThis.localStorage, toggleButton = null } = {}) {
    this.form = form;
    this.panel = root.querySelector("[data-scout-find]");
    // In the Machines head, where the page has it; beside Connect on a page of before.
    this.toggleButton = toggleButton || root.querySelector("[data-scout-add-find]");
    this.networks = root.querySelector("[data-scout-find-networks]");
    this.runButton = root.querySelector("[data-scout-find-run]");
    this.list = root.querySelector("[data-scout-find-list]");
    this.call = call;
    this.memory = memory;
  }

  bind() {
    this.toggleButton?.addEventListener("click", () => this.toggle());
    this.runButton?.addEventListener("click", () => this.scan());
    this.networks?.addEventListener("keydown", (e) => (e.key === "Enter" ? this.scan() : undefined));
    this.list?.addEventListener("click", (e) => {
      const btn = e.target?.closest?.("[data-scout-find-connect]");
      return btn ? this.pick(btn.dataset.scoutFindConnect, btn.dataset.scoutFindPort) : undefined;
    });
  }

  remembered() {
    try { return String(this.memory?.getItem(ScoutFinder.MEMORY) || ""); } catch { return ""; }
  }

  remember(text) {
    try { this.memory?.setItem(ScoutFinder.MEMORY, text); } catch { /* a convenience only */ }
  }

  toggle() {
    const open = this.panel.hidden;
    // The scan lives in the box: opened, it opens the box too.
    if (open && this.form.root.hidden) this.form.open(true);
    this.panel.hidden = !open;
    this.toggleButton?.setAttribute("aria-expanded", String(open));
    if (open) {
      if (!this.networks.value) this.networks.value = this.remembered();
      this.networks.focus();
    }
    return open;
  }

  say(state, html) {
    this.panel.dataset.tState = state;
    this.list.innerHTML = html;
  }

  // One found scout: its machine, where it answers, its version, and what can be done with it.
  rowHtml(f) {
    const where = `${f.address}:${f.port}`;
    const chip = { free: "scoutFindFree", here: "scoutFindHere", taken: "scoutFindTaken" }[f.state] || "scoutFindTaken";
    const act = f.state === "free"
      ? `<button type="button" class="scout-find-connect" data-scout-find-connect="${escapeHtml(f.address)}"`
        + ` data-scout-find-port="${escapeHtml(String(f.port))}" data-t="scout-find-connect">${escapeHtml(t("scoutFindConnect"))}</button>`
      : "";
    return `<div class="scout-find-row" role="listitem" data-t="scout-find-row" data-t-id="${escapeHtml(where)}" data-t-state="${escapeHtml(f.state)}">`
      + `<strong>${escapeHtml(f.name || f.hostId || f.address)}</strong>`
      + `<span class="scout-find-where">${escapeHtml(where)}</span>`
      + `<span class="scout-find-version">${escapeHtml(f.version ? "scout " + f.version : "")}</span>`
      + `<span class="scout-find-state ${escapeHtml(f.state)}">${escapeHtml(t(chip))}</span>${act}</div>`;
  }

  async scan() {
    const networks = this.networks.value.trim();
    const port = this.form.port.value.trim();
    this.remember(networks);
    this.runButton.disabled = true;
    this.say("working", `<span class="scout-find-note">${escapeHtml(t("scoutFindWorking", { networks: networks || t("scoutFindOwn") }))}</span>`);
    try {
      const res = await this.call("/api/topology/scout/scan", { method: "POST", body: { networks, port } });
      const where = (res?.networks || []).join(", ");
      const found = Array.isArray(res?.found) ? res.found : [];
      if (!found.length) {
        this.say("none", `<span class="scout-find-note">${escapeHtml(t("scoutFindNone", { networks: where, port: String(res?.port || port || 8092) }))}</span>`);
      } else {
        this.say("found", `<span class="scout-find-note">${escapeHtml(t("scoutFindFound", { networks: where, count: String(found.length) }))}</span>`
          + found.map((f) => this.rowHtml(f)).join(""));
      }
      return res;
    } catch (e) {
      this.say("error", `<span class="scout-find-note error">${escapeHtml(String(e?.message || e))}</span>`);
      return null;
    } finally {
      this.runButton.disabled = false;
    }
  }

  // A free scout found: its address goes into the form, and the form pairs it as if typed.
  pick(address, port) {
    this.form.address.value = address;
    if (port) this.form.port.value = port;
    return this.form.connect();
  }
}

export const mountScoutAdd = (doc) => ScoutAddForm.mount(doc);
