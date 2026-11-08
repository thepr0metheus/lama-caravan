// A machine's scout takes the release this controller carries, from the machine's ⋯ menu
// (the owner, 2026-11-02: an update by a button on the board, and the cells outlive it).
import { appConfirm } from "./dialogs.js";
import { t } from "./i18n.js";
import { api, toast } from "./utils.js";

/**
 * One press of the item. What it leads to is decided from the controller's answer
 * (GET /api/fleet/scout-release), by `offer`: a value, so that each of the five outcomes can be
 * pinned without a dialog. Either side may be absent, and each absence is its own outcome: a
 * controller that carries no scout, a scout that does not say its release and cannot replace itself.
 *
 * After the scout has taken the release it restarts, and only its next report says it came back:
 * the words that it took the release are not the words that it runs it. A scout that took it while
 * requests pass through it restarts once they are done (`waitsFor` in its answer, with the most it
 * waits for them), and the watch for its report lasts that much longer.
 */
export class ScoutRelease {
  /** How long a restarted scout has to report its new release: it beats at start, the rest is margin. */
  static WATCH_TRIES = 30;
  static WATCH_PAUSE_MS = 2000;

  constructor(hostId, { call = api, confirm = appConfirm, notify = toast,
                        pause = (ms) => new Promise((done) => setTimeout(done, ms)) } = {}) {
    this.hostId = String(hostId || "");
    this.call = call;
    this.confirm = confirm;
    this.notify = notify;
    this.pause = pause;
  }

  /** The outcome of an answer: no-release | cannot | current | same | new. "same" is another commit of one program: the controller
   *  compares what the two releases carry (`sameScout`, null when it cannot tell), the rule it follows by itself after a delivery. */
  static offer(said) {
    const commit = String(said?.release?.commit || "");
    const running = String(said?.running || "");
    if (!commit) return { kind: "no-release" };
    if (!running) return { kind: "cannot", commit };
    if (running === commit) return { kind: "current", commit, running };
    return { kind: said?.sameScout === true ? "same" : "new", commit, running };
  }

  /** The words of an outcome that asks nothing of the operator. */
  words(offer) {
    if (offer.kind === "no-release") return t("scoutUpdateNoRelease");
    if (offer.kind === "cannot") return t("scoutUpdateCannot", { host: this.hostId });
    if (offer.kind === "same") return t("scoutUpdateSame", { host: this.hostId, running: offer.running, commit: offer.commit });
    return t("scoutUpdateCurrent", { host: this.hostId, commit: offer.commit });
  }

  /** Seconds as whole minutes; a figure not given is a dash, not a guess. */
  static minutes(seconds) {
    return Number.isFinite(Number(seconds)) && seconds !== null ? String(Math.round(Number(seconds) / 60)) : "—";
  }

  /** A scout busy for now: the controller asks it again by itself, every so many minutes for so long (its answer says how), and it takes the
   *  release once it is free. A figure the answer does not give is a dash, not a guess. */
  waitingWords(waiting, commit) {
    const total = Number(waiting?.retrySec) * Number(waiting?.tries);
    return t("scoutUpdateWaiting", { host: this.hostId, commit, why: String(waiting?.words || "—"),
                                     minutes: ScoutRelease.minutes(waiting?.retrySec),
                                     total: ScoutRelease.minutes(Number.isFinite(total) ? total : null) });
  }

  /** A scout that took the release and restarts once what passes through it is done: what, and the most it waits for the requests. */
  waitsWords(waitsFor, commit) {
    const words = Array.isArray(waitsFor?.words) ? waitsFor.words.map(String).join(", ") : "";
    return t("scoutUpdateTakenWaits", { host: this.hostId, commit, why: words || "—", minutes: ScoutRelease.minutes(waitsFor?.mostSec) });
  }

  /** How many looks the watch for the report takes: the usual, and as many more as the scout said it may wait. A wait it does not put
   *  a figure on adds none: the watch then says what it saw, not what it guessed. */
  static watchTries(waitsFor) {
    const most = waitsFor && waitsFor.mostSec !== null ? Number(waitsFor.mostSec) : NaN;
    const more = Number.isFinite(most) && most > 0 ? Math.ceil((most * 1000) / ScoutRelease.WATCH_PAUSE_MS) : 0;
    return ScoutRelease.WATCH_TRIES + more;
  }

  read() {
    return this.call(`/api/fleet/scout-release?hostId=${encodeURIComponent(this.hostId)}`);
  }

  /** Whether the machine's report came to say `commit` within `tries` looks. A controller that does not answer for a moment is no answer yet. */
  async cameBack(commit, tries = ScoutRelease.WATCH_TRIES) {
    for (let tried = 0; tried < tries; tried += 1) {
      await this.pause(ScoutRelease.WATCH_PAUSE_MS);
      const said = await this.read().catch(() => null);
      if (said && String(said.running || "") === commit) return true;
    }
    return false;
  }

  /** Resolves to what happened, the same word the page's check reads: no-release | cannot | current | same | declined | waiting | done | silent | failed. */
  async press() {
    try {
      const offer = ScoutRelease.offer(await this.read());
      if (offer.kind !== "new") {
        this.notify(this.words(offer));
        return offer.kind;
      }
      const ask = t("scoutUpdateAsk", { host: this.hostId, running: offer.running, commit: offer.commit });
      if (!(await this.confirm(ask, { confirmLabel: t("scoutUpdateOk") }))) return "declined";
      const answer = await this.call("/api/fleet/scout-update", { method: "POST", body: { hostId: this.hostId } });
      if (answer?.waiting) {
        this.notify(this.waitingWords(answer.waiting, offer.commit));
        return "waiting";
      }
      const waitsFor = answer?.waitsFor || null;
      this.notify(waitsFor ? this.waitsWords(waitsFor, offer.commit) : t("scoutUpdateTaking", { host: this.hostId, commit: offer.commit }));
      const back = await this.cameBack(offer.commit, ScoutRelease.watchTries(waitsFor));
      this.notify(t(back ? "scoutUpdateDone" : "scoutUpdateSilent", { host: this.hostId, commit: offer.commit }));
      return back ? "done" : "silent";
    } catch (error) {
      this.notify(String(error?.message || error));
      return "failed";
    }
  }

  /** The items of a freshly drawn lane: drawn anew on each repaint, as the machine's other items are. */
  static bind(root) {
    root?.querySelectorAll("[data-scout-update]").forEach((item) => {
      item.addEventListener("click", (event) => {
        event.stopPropagation();
        new ScoutRelease(item.getAttribute("data-scout-update")).press();
      });
    });
  }
}
