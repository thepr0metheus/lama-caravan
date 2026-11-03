// The settings of the models' queue, one for every model (the owner, 2026-10-26: "let us first make one for all"), in minutes (the
// owner, 2026-10-29: the wait with somewhere to go "not in seconds but minutes, and no more than the value in 'wait up to'"): how long
// a request waits for a busy model while its pool has a ready row further on, how long it waits with nowhere to go before its client
// is answered 503, and how long the clients wait for an answer — the timeout the agents are to be given ("I plan to give all agents
// this waiting period"). The rule is the proxy's
// (rust/crates/rules/src/model_queue.rs, ModelQueuePolicy); FIELDS is its copy — names, defaults and bounds — held to it by
// contract/controller.json. A button in the head of the Models column says the queue's two and opens the fields under it;
// the strip of a model says them in words. Saved as the old queue line saved its fields (queue-settings.js): the proxy's policy.
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";
import { QueueTime } from "./model-queue.js";

export class ModelQueueSettings {
  // key — the policy's, kept in seconds; `per` — the seconds of the unit the field is typed in; `step` — what may be typed in it.
  // The patience goes by half a minute: the 90 s it has been set to since August is a minute and a half, and no more words than that.
  static FIELDS = [
    { key: "queueYieldSec", fallback: 0, min: 0, max: 3600, per: 60, step: 0.5, unit: "pbQueueUnitMin", label: "pbQueueYield", hint: "pbQueueYieldHint",
      invalid: "pbQueueYieldInvalid" },
    { key: "queueLimitSec", fallback: 0, min: 0, max: 3600, per: 60, step: 1, unit: "pbQueueUnitMin", label: "pbQueueLimit", hint: "pbQueueLimitHint",
      invalid: "pbQueueInvalid" },
    { key: "clientTimeoutSec", fallback: 3600, min: 60, max: 86400, per: 60, step: 1, unit: "pbQueueUnitMin", label: "pbQueueClientWait",
      hint: "pbQueueClientWaitHint", invalid: "pbQueueInvalid" },
  ];

  constructor({ call, notify }) {
    this.call = call;          // the controller (utils.api); its answer is the board's to apply
    this.notify = notify;      // a toast
    this.open = false;         // the fields under the button in the head of the Models column
    this.saving = false;
  }

  // The policy as the controller keeps it (`topology.proxyPolicy`) → each field's value in seconds, within its bounds as the
  // proxy reads it; a value nobody said (or no number) is its default — the behaviour the proxy has without it.
  static values(policy) {
    const out = Object.fromEntries(ModelQueueSettings.FIELDS.map((f) => {
      const raw = (policy || {})[f.key];
      const said = raw === null || raw === undefined || raw === "" ? NaN : Number(raw);
      return [f.key, Number.isInteger(said) ? Math.max(f.min, Math.min(said, f.max)) : f.fallback];
    }));
    if (out.queueLimitSec) out.queueYieldSec = Math.min(out.queueYieldSec, out.queueLimitSec);
    return out;
  }

  // The most a field takes, in seconds, by the values it stands with: the patience is no longer than a limit that is set.
  static ceiling(f, values) {
    return f.key === "queueYieldSec" && values.queueLimitSec ? Math.min(f.max, values.queueLimitSec) : f.max;
  }

  // Seconds in the field's unit: as typed, and at most two decimals for a value saved in seconds that is no step of it.
  static inUnit(f, seconds) {
    return Number((seconds / f.per).toFixed(2));
  }

  // "1.5 min": the patience in words, in the unit it is typed in.
  static waitWords(seconds) {
    return t("pbQueueMin", { n: String(ModelQueueSettings.inUnit(ModelQueueSettings.FIELDS[0], seconds)) });
  }

  // "Queue: 90 s · 25 min" — what the button says; "at once" and "no limit" for the zeros.
  static pill(policy) {
    const v = ModelQueueSettings.values(policy);
    return t("pbQueuePill", { wait: v.queueYieldSec ? ModelQueueSettings.waitWords(v.queueYieldSec) : t("pbQueueAtOnce"),
      limit: v.queueLimitSec ? ModelQueueSettings.limitWords(v.queueLimitSec) : t("pbQueueNoLimit") });
  }

  static limitWords(seconds) {
    return seconds % 60 === 0 ? t("pbQueueMin", { n: String(seconds / 60) }) : QueueTime.clock(seconds);
  }

  // The settings in words: what a request does when its model is busy, and how long its client waits — the timeout to give the
  // agents (the owner, 2026-10-26: "write 'set this for your agent' so they match"). The board shows a running request's end by it.
  static said(policy) {
    const v = ModelQueueSettings.values(policy);
    return [
      v.queueYieldSec ? t("pbQueueYieldSaid", { time: ModelQueueSettings.waitWords(v.queueYieldSec) }) : t("pbQueueYieldSaidZero"),
      v.queueLimitSec ? t("pbQueueLimitSaid", { time: ModelQueueSettings.limitWords(v.queueLimitSec) }) : t("pbQueueLimitSaidNone"),
      t("pbQueueClientWaitSaid", { time: ModelQueueSettings.limitWords(v.clientTimeoutSec) }),
    ];
  }

  buttonHtml(policy) {
    return `<button class="pb-queue-pill${this.open ? " open" : ""}" type="button" data-pb-queue-open aria-expanded="${this.open}"`
      + ` data-t="pb-queue-settings" title="${escapeHtml(t("pbQueuePillTitle"))}">${escapeHtml(ModelQueueSettings.pill(policy))}</button>`;
  }

  // The fields under the button, while it is open: each in its unit, with what it means; under them the two in words.
  panelHtml(policy) {
    if (!this.open) return "";
    const v = ModelQueueSettings.values(policy);
    const fields = ModelQueueSettings.FIELDS.map((f) => `<label class="pb-queue-field" title="${escapeHtml(t(f.hint))}">`
      + `<span>${escapeHtml(t(f.label))}</span>`
      + `<input type="number" min="${f.min / f.per}" max="${ModelQueueSettings.ceiling(f, v) / f.per}" step="${f.step}"`
      + ` inputmode="${f.step === 1 ? "numeric" : "decimal"}" value="${ModelQueueSettings.inUnit(f, v[f.key])}"`
      + ` data-pb-queue-field="${f.key}" data-t="pb-queue-field" data-t-id="${f.key}"${this.saving ? " disabled" : ""}>`
      + `<em>${escapeHtml(t(f.unit))}</em><small>${escapeHtml(t(f.hint))}</small></label>`).join("");
    return `<section class="pb-queue-panel" data-t="pb-queue-panel"><b>${escapeHtml(t("pbQueueSettingsTitle"))}</b>${fields}`
      + `<p class="pb-stated">${ModelQueueSettings.said(policy).map((x) => escapeHtml(x)).join(" ")}</p></section>`;
  }

  // The strip of a model: the door to the fields beside its title, the two in words, and the legend of its scales.
  sideHtml(policy) {
    const legend = [["waited", "pbQueueLegendWaited"], ["left", "pbQueueLegendLeft"], ["run", "pbQueueLegendRunning"],
      ["refuse", "pbQueueLegend503"], ["next", "pbQueueLegendNext"]]
      .map(([look, key]) => `<span class="pb-queue-key ${look}"><i aria-hidden="true"></i>${escapeHtml(t(key))}</span>`).join("");
    return `<div class="pb-queue-side" data-t="pb-queue-side"><div class="pb-queue-side-head"><b>${escapeHtml(t("pbQueueSettingsTitle"))}</b>`
      + `<button class="pb-queue-edit" type="button" data-pb-queue-open data-t="pb-queue-edit">${escapeHtml(t("pbQueueEdit"))}</button></div>`
      + ModelQueueSettings.said(policy).map((x) => `<p>${escapeHtml(x)}</p>`).join("")
      + `<div class="pb-queue-legend">${legend}</div></div>`;
  }

  // A field let go: its value in its unit → seconds, saved as the proxy's policy. A value that is no step of the field or out of its
  // bounds — the patience over a limit that is set, too — is refused before it is sent, with the bounds in the words; the field then
  // shows what the controller keeps. A limit lowered under the patience takes the patience with it, on the controller's side.
  async save(field, policy) {
    const f = ModelQueueSettings.FIELDS.find((x) => x.key === field?.dataset?.pbQueueField);
    if (!f || this.saving) return null;
    const typed = String(field.value ?? "").trim();
    const value = Number(typed);
    const kept = ModelQueueSettings.values(policy);
    const top = ModelQueueSettings.ceiling(f, kept);
    if (!typed || !Number.isInteger(value / f.step) || value * f.per < f.min || value * f.per > top) {
      field.value = String(ModelQueueSettings.inUnit(f, kept[f.key]));
      this.notify(t(f.invalid, { min: String(f.min / f.per), max: String(top / f.per) }));
      return null;
    }
    this.saving = true;
    try {
      const reply = await this.call("/api/agent-proxies/policy", { method: "POST", body: JSON.stringify({ policy: { [f.key]: value * f.per } }) });
      this.notify(t("pbQueueSaved"));
      return reply;
    } catch (err) {
      field.value = String(ModelQueueSettings.inUnit(f, kept[f.key]));
      this.notify(err.message);
      return null;
    } finally {
      this.saving = false;
    }
  }
}
