// Available resets are a provider fact. Consumption is an explicit confirmed
// action, never part of pool selection; retries keep the same durable request id.
// One door leads to the spend (run): the counter in a pool rung's head opens a window that lists the
// resets that can be spent and asks which, its own button being the confirmation. Opening it, or
// choosing in it, spends nothing. Until 1.3.464 a second door — the same list as rows under a rung's
// fold — drew what the window already shows (the operator, 2026-10-11: "лишнее").
import { t } from "./i18n.js";
import { api, escapeHtml, toast } from "./utils.js";
import { appConfirmChoice } from "./dialogs.js";

export class SubscriptionResetCards {
  constructor({ redraw = () => {}, refreshed = () => {}, now = () => Date.now(), choice = appConfirmChoice } = {}) {
    this.redraw = redraw;
    this.refreshed = refreshed;
    this.now = now;
    this.choice = choice;   // the window of choice: (message, opts) → the chosen reset's id, or null
    this.cache = new Map();
    this.busy = new Set();
    this.attempts = new Map();
  }

  async fetch(id, force = false, settledAttempt = false) {
    const old = this.cache.get(id);
    if (old?.loading || (!force && old && this.now() - old.at < 60000)) return;
    this.cache.set(id, { ...old, loading: true, at: this.now() });
    try {
      const data = await api(`/api/cloud-accounts/subscription-resets?id=${encodeURIComponent(id)}`);
      this.cache.set(id, { data, at: this.now() });
      const pending = data.pending?.[0];
      if (pending) this.attempts.set(id, pending);
      // Only a read after the consume request settles can prove that the
      // server never recorded a spend (for example, an expired selection).
      else if (settledAttempt) this.attempts.delete(id);
    } catch (err) { this.cache.set(id, { data: old?.data, at: this.now(), error: err.message }); }
    this.redraw();
  }

  // The counter reads the account's resets itself — no list under the fold asks for them any more:
  // at most once a minute (fetch keeps its own clock), and never for an account without a sign-in.
  read(account) {
    if (account?.hasCredential) this.fetch(account.testAliasOf || account.id);
  }

  // What the head of a rung says about this account's resets. Null while the balance is unread or
  // the read failed: an unknown count is not "0 resets".
  count(account) {
    const n = this.cache.get(account.testAliasOf || account.id)?.data?.availableCount;
    return Number.isFinite(n) ? n : null;
  }
  // A reset whose outcome is uncertain waits for a retry; nothing may hide it.
  pending(account) {
    return this.attempts.has(account.testAliasOf || account.id);
  }

  // The last read failed and nothing was read before it: the counter says "?" rather than vanish.
  failed(account) {
    const entry = this.cache.get(account.testAliasOf || account.id);
    return !!entry?.error && !entry.data;
  }

  // The small door to the saved resets on a subscription's row of the main board (the owner,
  // 2026-10-12: "the small button that enters the reset of limits — on the board's card"): ↺ and the
  // count, a button while one can be spent; the count alone when none can; "↺ ?" when the read failed
  // with nothing read before; ⚠ ahead of it while a spend is unresolved. Nothing while the first read
  // is under way: a count not read yet is not "0".
  chipHtml(account) {
    const id = escapeHtml(String(account.testAliasOf || account.id));
    const n = this.count(account);
    const warn = this.pending(account) ? `<span class="pool-warn" title="${escapeHtml(t("resetPending"))}">⚠</span>` : "";
    if (n == null) {
      return warn + (this.failed(account) ? `<span class="pool-resets none" data-t="provider-resets" data-t-state="unknown" title="${escapeHtml(t("resetUnavailable"))}">↺ ?</span>` : "");
    }
    const title = escapeHtml(t(n > 0 ? "resetChoose" : "resetAvailable", { count: String(n) }));
    return warn + (n > 0
      ? `<button class="pool-resets" type="button" data-pool-resets="${id}" data-t="provider-resets" data-t-state="some" title="${title}" aria-label="${title}">↺ ${n}</button>`
      : `<span class="pool-resets none" data-t="provider-resets" data-t-state="none" title="${title}">↺ 0</span>`);
  }

  // How a saved reset is named and when it ends, in the window.
  static title(credit) { return credit.resetType === "codex_rate_limits" ? t("resetFull") : credit.title || t("poolUnavailable"); }
  static expiry(credit) { return credit.expiresAt ? t("resetExpires", { date: new Date(credit.expiresAt).toLocaleString() }) : ""; }

  // What the window offers: the resets that can be spent, the one that ends first leading — a reset about to
  // lapse is the one to use. While an attempt is unresolved, that reset only: another cannot be spent before
  // it is settled (the server refuses it too). The list the cache holds is not reordered.
  static options(credits, attempt) {
    const named = (credit) => ({ value: String(credit.id), label: [SubscriptionResetCards.title(credit), SubscriptionResetCards.expiry(credit)].filter(Boolean).join(" · ") });
    const list = Array.isArray(credits) ? credits : [];
    if (attempt) {
      const kept = list.find((credit) => credit.id === attempt.creditId);
      return [kept ? named(kept) : { value: String(attempt.creditId), label: t("resetRetry") }];
    }
    const ends = (credit) => { const at = Date.parse(credit.expiresAt); return Number.isFinite(at) ? at : Infinity; };
    return list.filter((credit) => credit.usable)
      .sort((a, b) => (ends(a) === ends(b) ? 0 : ends(a) < ends(b) ? -1 : 1)).map(named);
  }

  // The counter in the head of a pool rung. The window lists the resets that can be spent and asks which;
  // the list is read again first when it is older than a minute (fetch keeps its own clock). Nothing to
  // choose from is said, not shown as an empty window.
  async choose(account) {
    const id = account.testAliasOf || account.id;
    await this.fetch(id);
    await this.run(id, async (pending) => {
      const options = SubscriptionResetCards.options(this.cache.get(id)?.data?.credits, pending);
      if (!options.length) { toast(t("resetNoCredit")); return ""; }
      // Unresolved: the window says why it offers one reset only, and what pressing its button does.
      return this.choice(t("resetConfirm", { account: account.name || id }) + (pending ? ` ${t("resetPending")}` : ""), {
        title: t("resetConfirmTitle"), confirmLabel: t(pending ? "resetRetry" : "resetUse"), danger: true,
        detail: account.oauthEmail || "", choices: options, list: true,
        choiceLabel: pending ? t("resetRetry") : t("resetAvailable", { count: String(options.length) }),
      });
    });
    return true;
  }

  // Another reset is unresolved: only that one may be tried again.
  blocked(id, creditId) {
    const pending = this.attempts.get(id);
    return !!pending && pending.creditId !== creditId;
  }

  // The one spend, whichever door the operator came by. `ask(pending)` gets the operator's word: the id of
  // the reset to spend, or nothing — then nothing is written and nothing is sent. Only after it the attempt
  // is stored (a retry keeps its key) and the server is asked, with the confirmation it insists on.
  async run(id, ask) {
    if (this.busy.has(id)) return;
    this.busy.add(id);
    try {
      const pending = this.attempts.get(id);
      const creditId = await ask(pending);
      if (!creditId || this.blocked(id, creditId)) return;
      const attempt = pending || { creditId, idempotencyKey: SubscriptionResetCards.requestId() };
      this.attempts.set(id, attempt);
      this.redraw();
      const result = await api("/api/cloud-accounts/subscription-reset", { method: "POST", body: JSON.stringify({ id, ...attempt, confirmed: true }) });
      this.attempts.delete(id);
      const key = { reset: "resetDone", already_redeemed: "resetDone", nothing_to_reset: "resetNothing", no_credit: "resetNoCredit" }[result.outcome];
      toast(t(key || "resetPending"));
      if (["reset", "already_redeemed"].includes(result.outcome)) this.refreshed(id);
      await this.fetch(id, true, true);
    } catch (err) { toast(err.message); await this.fetch(id, true, true); }
    finally { this.busy.delete(id); this.redraw(); }
  }

  static requestId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
  }
}
