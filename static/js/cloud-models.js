// A provider's models on its card: what each one is to the fleet right now,
// drawn from one place (2026-09-27, the operator's variant A).
//
// The list keeps itself (caravan/admin/cloud_sync.py): new models arrive
// hidden and marked new, a model the provider dropped is marked gone and —
// with nothing pointing at it — removed, and the removal can be undone for a
// day. So the card no longer has "Fetch models" or a bridge section: a row
// says what the model is (new, gone, on the kanban or hidden, the default),
// how many cables reach it, its price, and its own port for an app — opened
// by a button on the row, open in the LAN, no key (the operator's call).
import { t } from "./i18n.js";
import { formatPricePer1M, modelPricing } from "./model-meta.js";
import { escapeHtml } from "./utils.js";

// How long a model stays "new" after the list brought it.
export const NEW_FOR_MS = 7 * 24 * 3600 * 1000;

export class ProviderModels {
  constructor({ account, blocks = [], routers = [], proxies = [], removed = [], now = Date.now(), open = false,
    nextPort = null, hostname = "" } = {}) {
    this.account = account || {};
    this.blocks = blocks.filter((b) => b.accountId === this.account.id);
    this.routers = routers;
    this.proxies = proxies;
    this.removed = removed.filter((r) => r.accountId === this.account.id);
    this.now = now;
    this.open = open;
    this.nextPort = nextPort;
    this.hostname = hostname;
  }

  // Cables into a model: kanban edges that land on its output, in every router.
  cables(blockId) {
    const ref = `out:cb:${blockId}`;
    return this.routers.reduce((n, r) => n + ((r.graph?.edges || []).filter((e) => e && e.to === ref).length), 0);
  }

  isDefault(blockId) {
    return this.routers.some((r) => (r.rules || {}).default === `cb:${blockId}`);
  }

  // A model's own ports for apps (bridges, route kind "service").
  ports(blockId) {
    return this.proxies.filter((p) => p.kind === "service" && p.providerId === blockId)
      .sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  }

  price(model) {
    if (String(model || "").endsWith(":free")) return "FREE";
    const p = modelPricing[model || ""];
    return p && (p.inputPer1M || p.outputPer1M)
      ? `${formatPricePer1M(p.inputPer1M)} / ${formatPricePer1M(p.outputPer1M)} /1M` : "";
  }

  // What each model is, attention first: gone, then new, then on the
  // kanban, then hidden; within a group the dearer first, then by name.
  rows() {
    const rank = (m) => {
      const p = modelPricing[m || ""];
      return p ? (Number(p.inputPer1M) || 0) * 1000 + (Number(p.outputPer1M) || 0) : -1;
    };
    return this.blocks.map((b) => {
      const gone = !!b.unlisted;
      const fresh = !gone && Number(b.newSince) > 0 && this.now - Number(b.newSince) * 1000 < NEW_FOR_MS;
      return { block: b, gone, fresh, shown: !!b.exposed, cables: this.cables(b.id), isDefault: this.isDefault(b.id),
        ports: this.ports(b.id), price: this.price(b.model) };
    }).sort((a, b) => {
      const group = (r) => (r.gone ? 0 : r.fresh ? 1 : r.shown ? 2 : 3);
      return (group(a) - group(b)) || (rank(b.block.model) - rank(a.block.model))
        || String(a.block.model || a.block.id).localeCompare(String(b.block.model || b.block.id), undefined,
          { numeric: true, sensitivity: "base" });
    });
  }

  summary() {
    const rows = this.rows();
    return { total: rows.length, shown: rows.filter((r) => r.shown).length,
      fresh: rows.filter((r) => r.fresh).length, gone: rows.filter((r) => r.gone).length };
  }

  checkedAt() {
    const at = Number(this.account.modelsCheckedAt) || 0;
    if (!at) return t("cloudModelsNotChecked");
    const d = new Date(at * 1000);
    const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    return t("cloudModelsCheckedAt", { time: hhmm });
  }

  headHtml() {
    const s = this.summary();
    const acc = escapeHtml(this.account.id);
    const parts = [t("cloudModelsOnKanban", { n: String(s.shown) })];
    if (s.fresh) parts.push(`<span class="cloud-models-fresh">${escapeHtml(t("cloudModelsNewCount", { n: String(s.fresh) }))}</span>`);
    if (s.gone) parts.push(`<span class="cloud-models-gone">${escapeHtml(t("cloudModelsGoneCount", { n: String(s.gone) }))}</span>`);
    const said = parts.map((p) => (p.startsWith("<") ? p : escapeHtml(p))).join(" · ");
    return `<div class="cloud-models-head">
      <button class="cloud-models-toggle" type="button" data-cloud-models-toggle="${acc}" aria-expanded="${this.open}">
        <span class="cloud-models-title">${escapeHtml(t("cloudModelsTitle"))}</span><span class="cloud-models-n">${s.total}</span>
        <span class="cloud-models-sum">${said}</span><span class="cloud-models-caret" aria-hidden="true">${this.open ? "⌃" : "⌄"}</span>
      </button>
      <span class="cloud-models-checked">${escapeHtml(this.checkedAt())}</span>
      <button class="icon-action compact" type="button" data-cloud-fetch-models="${acc}" title="${escapeHtml(t("cloudModelsCheckNow"))}"
        aria-label="${escapeHtml(t("cloudModelsCheckNow"))}">↻</button>
    </div>`;
  }

  chip(text, kind) {
    return `<span class="cloud-chip ${kind}">${escapeHtml(text)}</span>`;
  }

  rowHtml(r) {
    const b = r.block;
    const chips = [
      r.gone ? this.chip(t("cloudChipGone"), "gone") : "",
      r.fresh ? this.chip(t("cloudChipNew"), "fresh") : "",
      this.chip(r.shown ? t("cloudChipKanban") : t("cloudChipHidden"), r.shown ? "shown" : "hidden"),
      r.isDefault ? this.chip(t("cloudChipDefault"), "default") : "",
    ].join("");
    const cables = r.cables ? `<span class="cloud-block-cables">${escapeHtml(t("cloudModelCables", { n: String(r.cables) }))}</span>` : "";
    const price = r.price ? `<span class="cloud-block-pricing${r.price === "FREE" ? " free" : ""}">${escapeHtml(r.price)}</span>` : "";
    const ports = r.ports.length
      ? r.ports.map((p) => {
        const url = `http://${this.hostname}:${p.port}`;
        return `<span class="cloud-model-port"><code class="cloud-bridge-port">:${escapeHtml(String(p.port))}</code>`
          + `<button class="icon-action compact" type="button" data-bridge-copy="${escapeHtml(url)}" title="${escapeHtml(t("cloudBridgeCopy"))}">⧉</button>`
          + `<button class="icon-action compact" type="button" data-bridge-delete="${escapeHtml(String(p.port))}" title="${escapeHtml(t("cloudBridgeDelete"))}">✕</button></span>`;
      }).join("")
      : (this.account.hasCredential
        ? `<button class="cloud-port-add" type="button" data-bridge-mint="${escapeHtml(b.id)}" title="${escapeHtml(
          t("cloudPortAddTitle", { port: this.nextPort ? String(this.nextPort) : "…" }))}">${escapeHtml(t("cloudPortAdd"))}</button>`
        : "");
    const title = r.gone ? t("cloudModelGoneTitle") : (b.model || b.id);
    return `<div class="cloud-block-row${r.gone ? " stale" : ""}${r.fresh ? " fresh" : ""}" data-cloud-block="${escapeHtml(b.id)}"`
      + ` role="button" tabindex="0" title="${escapeHtml(title)}">`
      + `<span class="cloud-block-model">${escapeHtml(b.model || "—")}</span>${chips}${cables}${price}${ports}</div>`;
  }

  removedHtml() {
    if (!this.removed.length) return "";
    const acc = escapeHtml(this.account.id);
    const items = this.removed.map((r) => `<span class="cloud-removed-item"><code>${escapeHtml(r.model || r.id)}</code>`
      + `<button class="icon-action compact" type="button" data-cloud-restore="${acc}|${escapeHtml(r.id)}"`
      + ` title="${escapeHtml(t("cloudRestore"))}" aria-label="${escapeHtml(t("cloudRestore"))}">↶</button></span>`).join("");
    return `<div class="cloud-removed"><span class="cloud-removed-title">${escapeHtml(t("cloudRemovedTitle"))}</span>${items}</div>`;
  }

  html() {
    const rows = this.rows();
    const list = rows.length
      ? `<div class="cloud-account-blocks">${rows.map((r) => this.rowHtml(r)).join("")}</div>`
      : `<div class="topology-muted cloud-models-empty">${escapeHtml(t("clNoModelsYet"))}</div>`;
    return `${this.headHtml()}${this.removedHtml()}
      <div class="cloud-models-flyout">${list}
        <button class="cloud-add-model-btn" type="button" data-cloud-add-block="${escapeHtml(this.account.id)}">${escapeHtml(t("cloudAddById"))}</button>
      </div>`;
  }
}
