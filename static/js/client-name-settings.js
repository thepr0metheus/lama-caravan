// The one name every client goes to the cloud providers under (the owner, 2026-10-31: "let us present ourselves as one; it is purely for
// the home, and if they ban us, let them"). Empty: each client under its own. A button in the head of the Clients column says which and opens
// the field under it, as the models' queue does in its column. Saved as the proxy's policy, and the rule of what can be a name is the
// server's alone (rust/crates/rules/src/client_name.rs): what it refuses comes back here in its words, and the field shows what it keeps.
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

export class ClientNameSettings {
  constructor({ call, notify } = {}) {
    this.call = call;
    this.notify = notify;
    this.open = false;
    this.saving = false;
  }

  static kept(policy) {
    return String(policy?.clientName || "");
  }

  static pill(policy) {
    const name = ClientNameSettings.kept(policy);
    return name ? t("pbClientNamePill", { name }) : t("pbClientNamePillOwn");
  }

  buttonHtml(policy) {
    return `<button class="pb-queue-pill pb-name-pill${this.open ? " open" : ""}" type="button" data-pb-client-name-open aria-expanded="${this.open}"`
      + ` data-t="pb-client-name-open" title="${escapeHtml(t("pbClientNameLabel"))}">${escapeHtml(ClientNameSettings.pill(policy))}</button>`;
  }

  panelHtml(policy) {
    if (!this.open) return "";
    return `<section class="pb-queue-panel" data-t="pb-client-name-panel"><label class="pb-name-field"><b>${escapeHtml(t("pbClientNameLabel"))}</b>`
      + `<input type="text" autocomplete="off" spellcheck="false" value="${escapeHtml(ClientNameSettings.kept(policy))}"`
      + ` placeholder="${escapeHtml(t("pbClientNameEmpty"))}" data-pb-client-name data-t="pb-client-name"${this.saving ? " disabled" : ""}>`
      + `<small>${escapeHtml(t("pbClientNameHint"))}</small></label></section>`;
  }

  // The field let go: saved as it is typed. A refusal says why, and the field goes back to what the controller keeps.
  async save(field, policy) {
    if (!field || this.saving) return null;
    this.saving = true;
    try {
      const reply = await this.call("/api/agent-proxies/policy", { method: "POST", body: JSON.stringify({ policy: { clientName: String(field.value ?? "") } }) });
      this.notify(t("pbClientNameSaved"));
      return reply;
    } catch (err) {
      field.value = ClientNameSettings.kept(policy);
      this.notify(err.message);
      return null;
    } finally {
      this.saving = false;
    }
  }
}
