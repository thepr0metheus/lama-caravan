// A machine's scout takes the release this controller carries, from the machine's ⋯ menu
// (the owner, 2026-11-02: an update by a button on the board, and the cells outlive it).
import { appConfirm } from "./dialogs.js";
import { t } from "./i18n.js";
import { api, toast } from "./utils.js";

/**
 * One press of the item. What it leads to is decided from the controller's answer
 * (GET /api/fleet/scout-release), by `offer`: a value, so that each of the four outcomes can be
 * pinned without a dialog. Either side may be absent, and each absence is its own outcome: a
 * controller that carries no scout, a scout that does not say its release and cannot replace itself.
 *
 * After the scout has taken the release it restarts, and only its next report says it came back:
 * the words that it took the release are not the words that it runs it.
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

  /** The outcome of an answer: no-release | cannot | current | new. */
  static offer(said) {
    const commit = String(said?.release?.commit || "");
    const running = String(said?.running || "");
    if (!commit) return { kind: "no-release" };
    if (!running) return { kind: "cannot", commit };
    return { kind: running === commit ? "current" : "new", commit, running };
  }

  /** The words of an outcome that asks nothing of the operator. */
  words(offer) {
    if (offer.kind === "no-release") return t("scoutUpdateNoRelease");
    if (offer.kind === "cannot") return t("scoutUpdateCannot", { host: this.hostId });
    return t("scoutUpdateCurrent", { host: this.hostId, commit: offer.commit });
  }

  read() {
    return this.call(`/api/fleet/scout-release?hostId=${encodeURIComponent(this.hostId)}`);
  }

  /** Whether the machine's report came to say `commit`. A controller that does not answer for a moment is no answer yet. */
  async cameBack(commit) {
    for (let tries = 0; tries < ScoutRelease.WATCH_TRIES; tries += 1) {
      await this.pause(ScoutRelease.WATCH_PAUSE_MS);
      const said = await this.read().catch(() => null);
      if (said && String(said.running || "") === commit) return true;
    }
    return false;
  }

  /** Resolves to what happened, the same word the page's check reads: no-release | cannot | current | declined | done | silent | failed. */
  async press() {
    try {
      const offer = ScoutRelease.offer(await this.read());
      if (offer.kind !== "new") {
        this.notify(this.words(offer));
        return offer.kind;
      }
      const ask = t("scoutUpdateAsk", { host: this.hostId, running: offer.running, commit: offer.commit });
      if (!(await this.confirm(ask, { confirmLabel: t("scoutUpdateOk") }))) return "declined";
      await this.call("/api/fleet/scout-update", { method: "POST", body: { hostId: this.hostId } });
      this.notify(t("scoutUpdateTaking", { host: this.hostId, commit: offer.commit }));
      const back = await this.cameBack(offer.commit);
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
