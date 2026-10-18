// What is left of a key account's credit, as the board says it (the owner, 2026-10-17, after adding an Anthropic key and a model:
// "why can't I see how much money is left on this API?").
//
// The provider does not tell. Anthropic's Console shows "Organization credits" and its API has no call for it; OpenAI's keys read no
// balance either. So the account holds the figure the operator typed — what the console shows NOW — and the moment it was typed
// (`creditUsd`, `creditAsOf`), and the controller counts what went through the caravan since (`sinceCredit` in the spend reading,
// caravan/admin/cloud_api.py). What stands here is an estimate, and every line of it says so: what the same key spent anywhere else is
// not in it.
//
// "Not read" is its own state. A credit with no spend reading — or one made for another figure than the account's now — draws the
// figure alone and says the spend is not read: never "all of it left", which is what an empty reading would look like.
import { t } from "./i18n.js";
import { Money } from "./money.js";
import { limitTone } from "./usage-stats.js";
import { escapeHtml } from "./utils.js";

export class CreditLeft {
  // The credit the operator typed, or null: the controller says `null` for none, and 0 is a credit used up.
  static typed(account) {
    const value = account?.creditUsd;
    if (typeof value === "boolean" || value === null || value === undefined || value === "") return null;
    return Number.isFinite(Number(value)) ? Number(value) : null;
  }

  // The figures of an account, or null while the reading that says what was spent is not there or counts from another figure.
  // `spend` is the spend reading keyed by account id (usage-stats.js proxySpendData; null before the first one landed).
  static of(account, spend) {
    const credit = CreditLeft.typed(account);
    if (credit === null || !spend) return null;
    const since = (spend[account.id] || {}).sinceCredit;
    if (!since || Number(since.asOf) !== Number(account.creditAsOf)) return null;
    const spent = Number(since.total) || 0;
    const left = Math.max(0, credit - spent);
    return {
      credit,
      spent,
      left,
      pct: credit > 0 ? Math.round(Math.min(100, (left / credit) * 100)) : 0,
      unpriced: Number(since.unpriced) || 0,
      partial: since.partial === true,
      asOf: Number(account.creditAsOf),
    };
  }

  // Dollars as the board says them: the one rule of the spend line beside it (money.js), so the two agree.
  static money(amount) {
    return Money.dollars(amount);
  }

  static day(seconds) {
    return new Date(Number(seconds) * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  // The meter of the credit left — the bar of the subscription limits, its words said in full — and what must be said beside it.
  static html(account, spend) {
    const credit = CreditLeft.typed(account);
    if (credit === null) return "";
    const id = escapeHtml(String(account.id));
    const hint = escapeHtml(t("creditHint"));
    const figures = CreditLeft.of(account, spend);
    if (!figures) {
      return `<div class="credit-left" data-t="credit-left" data-t-id="${id}" data-t-state="unread" title="${hint}">`
        + `<span class="credit-line">${escapeHtml(t("creditUnread", { credit: CreditLeft.money(credit) }))}</span></div>`;
    }
    const left = t("creditLeft", { left: CreditLeft.money(figures.left) });
    const of = t("creditOf", { credit: CreditLeft.money(figures.credit) });
    const warnings = [];
    if (figures.unpriced > 0) warnings.push(t("creditUnpriced", { n: String(figures.unpriced) }));
    if (figures.partial) warnings.push(t("creditPartial"));
    return `<div class="credit-left sub-meters single" data-t="credit-left" data-t-id="${id}" data-t-state="known" title="${hint}">`
      + `<div class="sub-meter credit-meter" role="meter" aria-label="${escapeHtml(`${left} ${of}`)}" aria-valuemin="0" aria-valuemax="${figures.credit}" aria-valuenow="${figures.left}">`
      + `<span class="sub-meter-label">${escapeHtml(left)}</span>`
      + `<span class="sub-meter-bar"><i class="sub-meter-fill" style="width:${figures.pct}%;background:${limitTone(figures.pct)}"></i></span>`
      + `<span class="sub-meter-pct">${escapeHtml(of)}</span></div>`
      + `<div class="credit-note" data-t="credit-since">${escapeHtml(t("creditSince", { date: CreditLeft.day(figures.asOf) }))}</div>`
      + warnings.map((words) => `<div class="credit-note warn" data-t="credit-warn">${escapeHtml(words)}</div>`).join("")
      + `</div>`;
  }
}
