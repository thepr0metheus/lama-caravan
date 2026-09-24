// Adding a machine's scout from the board: the one way a machine that lends
// its GPU or CPU joins the fleet.
import { t } from "./i18n.js";
import { refreshTopology } from "./topology-render.js";
import { $, api } from "./utils.js";

/**
 * The address field under Model servers. The machine only installs its scout
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
 */
export class ScoutAddForm {
  constructor(root) {
    this.root = root;
    this.address = root.querySelector("[data-scout-add-address]");
    this.port = root.querySelector("[data-scout-add-port]");
    this.button = root.querySelector("[data-scout-add-connect]");
    this.status = root.querySelector("[data-scout-add-status]");
  }

  static mount(doc = document) {
    const root = doc.getElementById("scoutAdd");
    if (!root || root.dataset.bound) return null;
    root.dataset.bound = "1";
    const form = new ScoutAddForm(root);
    form.bind();
    return form;
  }

  bind() {
    this.button.addEventListener("click", () => this.connect());
    for (const field of [this.address, this.port]) {
      field.addEventListener("keydown", (e) => { if (e.key === "Enter") this.connect(); });
    }
  }

  say(state, text) {
    this.root.dataset.tState = state;
    this.status.textContent = text;
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

export const mountScoutAdd = (doc) => ScoutAddForm.mount(doc);
