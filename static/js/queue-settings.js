// One editor and one persisted policy for every admission queue. It is a line at
// the head of the Servers block — "overflow at 5% · reserve 20 s · Loading wait
// 60 s" — and its pencil opens the three fields in place.
import { drawCanvasConnectors } from "./canvas.js";
import { helpTip, t } from "./i18n.js";
import { setTopology, topology } from "./state.js";
import { refreshTopology } from "./topology-render.js";
import { api, escapeHtml, toast } from "./utils.js";

export class QueueSettings {
  static FIELDS = [
    { key: "cloudFallbackPct", spec: "spillPct", label: "cvLabelOverflowAt", tip: "cvTipOverflowAt", max: 100, unit: "%", fallback: 20 },
    { key: "stickySlotSec", spec: "stickySlotSec", label: "cvLabelReserve", tip: "cvTipReserve", max: 120, unit: "s", fallback: 0 },
    { key: "loadingModelWaitSec", spec: "loadingModelWaitSec", label: "cvLabelLoadWait", tip: "cvTipLoadWait", max: 900, unit: "s", fallback: 60 },
  ];
  constructor() { this.saving = false; this.editing = false; }
  values() {
    const policy = topology?.proxyPolicy || {};
    return Object.fromEntries(QueueSettings.FIELDS.map((f) => [f.spec, policy[f.key] ?? f.fallback]));
  }
  // The policy as one line of words: each field's own label, its value and unit.
  summary() {
    const values = this.values();
    return QueueSettings.FIELDS.map((f) => `${t(f.label)} ${values[f.spec]}${f.unit}`).join(" · ");
  }
  html() {
    const values = this.values();
    return `<section class="cv-queue-settings${this.editing ? " open" : ""}" data-t="kanban-queue-settings" data-cv-queue-settings>`
      + `<button class="cv-qs-line" type="button" data-t="kanban-queue-settings-toggle" data-cv-qs-toggle`
      + ` aria-expanded="${this.editing}" title="${escapeHtml(t("cvSharedQueueSettings"))}">`
      + `<span class="cv-qs-glyph" aria-hidden="true">⏳</span>`
      + `<span class="cv-qs-text" data-cv-qs-text>${escapeHtml(this.summary())}</span>`
      + `<span class="cv-qs-pen" aria-hidden="true">✎</span></button>`
      + `<div class="cv-qs-fields">`
      + QueueSettings.FIELDS.map((f) => `<label class="cv-shared-q-field"><span>${escapeHtml(t(f.label))} ${helpTip(f.tip)}</span>`
        + `<input type="number" min="0" max="${f.max}" value="${values[f.spec]}" data-t="kanban-queue-setting"`
        + ` data-t-id="${f.key}" data-cv-queue-policy="${f.key}"><span>${f.unit}</span></label>`).join("")
      + `</div></section>`;
  }
  // Runs from bind(), and bind() runs from the board's MutationObserver on EVERY change
  // of the page: a line rewritten with the text it already has is still a change (a new
  // text node), which wakes the observer, which binds again — a loop that froze the
  // page. So the line is touched only when its words changed.
  sync(root = document) {
    const values = this.values();
    const summary = this.summary();
    root.querySelectorAll("[data-cv-qs-text]").forEach((el) => { if (el.textContent !== summary) el.textContent = summary; });
    root.querySelectorAll("[data-cv-queue-policy]").forEach((input) => {
      input.disabled = this.saving;
      const field = QueueSettings.FIELDS.find((f) => f.key === input.dataset.cvQueuePolicy);
      if (field && !this.saving && input !== document.activeElement) input.value = String(values[field.spec]);
    });
  }
  async save(key, raw) {
    const field = QueueSettings.FIELDS.find((f) => f.key === key);
    if (!field || this.saving) return;
    const value = Number(raw);
    if (!String(raw).trim() || !Number.isInteger(value) || value < 0 || value > field.max)
      throw new Error(t("cvQueueSettingInvalid", { max: field.max }));
    this.saving = true;
    this.sync();
    try {
      const reply = await api("/api/agent-proxies/policy", { method: "POST", body: { policy: { [key]: value } } });
      setTopology({ ...topology, proxyPolicy: reply.config.policy });
      await refreshTopology();
    } finally {
      this.saving = false;
      this.sync();
    }
  }
  bind(root = document) {
    root.querySelectorAll("[data-cv-queue-settings]").forEach((panel) => {
      if (panel.dataset.cvQueueSettingsBound) return;
      panel.dataset.cvQueueSettingsBound = "1";
      const toggle = panel.querySelector("[data-cv-qs-toggle]");
      toggle?.addEventListener("pointerdown", (event) => event.stopPropagation());
      toggle?.addEventListener("click", () => {
        this.editing = !this.editing;
        panel.classList.toggle("open", this.editing);
        toggle.setAttribute("aria-expanded", String(this.editing));
        drawCanvasConnectors();   // the Servers block changed height: its port dots and cables move
        if (this.editing) panel.querySelector("[data-cv-queue-policy]")?.focus();
      });
      panel.querySelectorAll("[data-cv-queue-policy]").forEach((input) => {
        input.addEventListener("pointerdown", (event) => event.stopPropagation());
        input.addEventListener("change", () => {
          this.save(input.dataset.cvQueuePolicy, input.value).catch((error) => {
            input.value = String(this.values()[QueueSettings.FIELDS.find((f) => f.key === input.dataset.cvQueuePolicy).spec]);
            toast(error.message);
          });
        });
      });
    });
    this.sync(root);
  }
}

export const QUEUE_SETTINGS = new QueueSettings();
