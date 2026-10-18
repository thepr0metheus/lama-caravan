// How fast and how long, in one wording for every progress on these pages: a
// move on /models and a cell reading its model on the board. Two copies of a
// format drift apart, and then one speed reads differently on two screens.
import { t } from "./i18n.js";
import { PaceRule } from "./pace-rule.js";

export class Pace {
  static speed(bps) {
    if (!(bps > 0)) return "";
    return bps >= 2 ** 30 ? `${(bps / 2 ** 30).toFixed(1)} GB/s` : `${Math.max(1, Math.round(bps / 2 ** 20))} MB/s`;
  }

  // Time left in words read at a glance; nothing while it is not known — a
  // guess from a single answer would jump around. The rule is pace-rule.js's:
  // /hf words the same rule from its own table.
  static eta(seconds) {
    return PaceRule.eta(seconds, t);
  }
}
