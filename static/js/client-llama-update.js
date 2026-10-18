// What a machine's ⇪ installs — and what the words on it say it installs (found 2026-10-17: on the NAS controller the ⇪ promised "the
// controller's build" and installed the latest release).
//
// ⇪ sends the controller's llama.cpp commit (`state.llamaCpp.git.head`) to /api/fleet/llama-update, and the route reads an empty tag as
// "the latest release". A controller that runs in a container (the NAS) has no llama.cpp checkout: its commit is empty, so ⇪ installed the
// latest release while its tooltip and its confirm window said "to the controller's build". The tag came from one reading of the
// controller and the words from none: here the tag, the tooltip and the confirm window come from the same one.
//
// "Not read yet" is a state of its own. Before the controller has said what it runs there is nothing to compare the words with, so ⇪ is
// not drawn — never drawn with the latest release's words, which is what an empty commit would say. A controller that HAS said, and runs
// no llama.cpp, is the other state: ⇪ is there, and says what it does.
import { t } from "./i18n.js";
import { state } from "./state.js";
import { api, toast } from "./utils.js";

export class ClientLlamaUpdate {
  // `info` is the controller's own llama.cpp reading (state.llamaCpp): missing before the first state came, and without `git` when the
  // controller did not say.
  constructor(info) {
    const git = info && typeof info === "object" ? info.git : null;
    this.read = !!git && typeof git === "object";
    this.commit = this.read ? String(git.head ?? "").trim() : "";
  }

  static of(info) {
    return new ClientLlamaUpdate(info);
  }

  // ⇪ is drawn only when the controller has said what it runs (even when it runs nothing).
  get offered() {
    return this.read;
  }

  // True: ⇪ converges the machine onto the controller's commit. False: the controller has none, the machine gets the latest release.
  get followsController() {
    return this.commit !== "";
  }

  // What the route is given: the controller's commit, or "" — the route's word for "the latest release".
  get tag() {
    return this.commit;
  }

  get titleKey() {
    return this.followsController ? "updateClientLlama" : "updateClientLlamaLatest";
  }

  get confirmKey() {
    return this.followsController ? "updateClientLlamaConfirm" : "updateClientLlamaLatestConfirm";
  }

  // The click: ask in words that tell what will be installed, then ask the route for the same thing. The scout runs it as a background
  // job; its heartbeat flips the chip to "building…" on the next topology poll.
  async start(hostId) {
    if (!window.confirm(t(this.confirmKey))) return;
    try {
      await api("/api/fleet/llama-update", { method: "POST", body: JSON.stringify({ hostId, tag: this.tag }) });
      toast(t("clientLlamaBuilding"));
    } catch (err) {
      toast(err.message);
    }
  }

  // Wires every ⇪ under `root`. The reading of the controller is taken at the click, not when the button was drawn: the words in the
  // window and the tag sent after it stay one reading.
  static bind(root) {
    root?.querySelectorAll("[data-update-client-llama]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        ClientLlamaUpdate.of(state.llamaCpp).start(btn.getAttribute("data-update-client-llama") || "");
      });
    });
  }
}
