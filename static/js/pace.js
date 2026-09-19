// How fast and how long, in one wording for every progress on these pages: a
// move on /models and a cell reading its model on the board. Two copies of a
// format drift apart, and then one speed reads differently on two screens.
import { t } from "./i18n.js";

export class Pace {
  static speed(bps) {
    if (!(bps > 0)) return "";
    return bps >= 2 ** 30 ? `${(bps / 2 ** 30).toFixed(1)} GB/s` : `${Math.max(1, Math.round(bps / 2 ** 20))} MB/s`;
  }

  // Time left in words read at a glance; nothing while it is not known — a
  // guess from a single answer would jump around.
  static eta(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return "";
    const five = Math.ceil(seconds / 5) * 5;
    if (five < 60) return t("moveEtaSeconds", { n: String(five) });
    const minutes = Math.ceil(seconds / 60);
    if (minutes < 60) return t("moveEtaMinutes", { n: String(minutes) });
    return t("moveEtaHours", { h: String(Math.floor(minutes / 60)), m: String(minutes % 60) });
  }
}
