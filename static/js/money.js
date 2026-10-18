// Dollars as the board says them (1.3.585) — one rule for every sum of money drawn from the spend reading: the spend line of a provider
// (usage-stats.js `spendCost`) and the credit left of a key account (credit-left.js).
//
// Whole from a hundred up, cents below, none when they are zero. An amount above zero that cents cannot show says so ("<$0.01"), because "$0"
// reads as "nothing was spent": the provider's line used to round every spend to whole dollars and said "≈ $0" for $0.07, while the Console the
// operator held it against (2026-10-18) says cents. The two places that said dollars had two rules; they have this one.
export class Money {
  static dollars(amount) {
    const value = Number(amount) || 0;
    if (value > 0 && value < 0.005) return "<$0.01";
    return `$${value >= 100 ? Math.round(value).toLocaleString("en-US") : value.toFixed(2).replace(/\.00$/, "")}`;
  }
}
