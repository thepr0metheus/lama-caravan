// How a time left is rounded and which of three phrases it takes — apart from the words. The board's pages speak through the
// shared dictionary (pace.js), /hf has a table of its own and loads no other (hf-text.js, HfFormat.eta): each hands in its own
// `say`, and the rule stays one. Two copies of a rule drift apart, and then the same wait reads differently on two screens.
// scripts/pace_cases.py is the table both are run against.
export class PaceRule {
  // `say(key, vars)` words a phrase: moveEtaSeconds {n}, moveEtaMinutes {n}, moveEtaHours {h, m}. Nothing ("") while the time is
  // not known: a guess from a single answer would jump around.
  static eta(seconds, say) {
    if (!Number.isFinite(seconds) || seconds <= 0) return "";
    const five = Math.ceil(seconds / 5) * 5;
    if (five < 60) return say("moveEtaSeconds", { n: String(five) });
    const minutes = Math.ceil(seconds / 60);
    if (minutes < 60) return say("moveEtaMinutes", { n: String(minutes) });
    return say("moveEtaHours", { h: String(Math.floor(minutes / 60)), m: String(minutes % 60) });
  }
}
