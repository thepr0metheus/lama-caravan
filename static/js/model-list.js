// The models the cell editor offers (state.models), kept current on an open
// board.
//
// /api/state brings them once, when the page opens, and the board's beat reads
// only the topology: the caravan's shelf (topology-nodes.js), which lists the
// same rows, never showed a model downloaded after the page opened
// (2026-09-26). The topology now carries the list's stamp (ModelList in
// caravan/admin/models.py); when it differs from the stamp the page holds, the
// rows are fetched again — once, however many beats ask meanwhile.
import { state } from "./state.js";
import { api } from "./utils.js";

export class ModelListFollower {
  constructor({ fetchRows = () => api("/api/models/rows"), page = () => state } = {}) {
    this.fetchRows = fetchRows;
    this.page = page;
    this.inflight = null;
  }

  // Whether the page's list is older than `stamp`. Not while the page has no
  // state yet — /api/state is on its way and brings a list of its own — nor
  // when the topology carries no stamp (a controller older than the stamp).
  behind(stamp) {
    const page = this.page();
    return !!(page && stamp && stamp !== page.modelsStamp);
  }

  // Fetches the rows when the page is behind; true once they are in. A failed
  // fetch leaves the page's list as it was, and the next beat asks again.
  async follow(stamp) {
    if (!this.behind(stamp)) return false;
    this.inflight ||= Promise.resolve().then(this.fetchRows).finally(() => { this.inflight = null; });
    let reply;
    try {
      reply = await this.inflight;
    } catch {
      return false;
    }
    const page = this.page();
    if (!page || !Array.isArray(reply?.models)) return false;
    page.models = reply.models;
    // The reply names the list it is; one without a name was still read after
    // the topology's stamp, so that stamp is what the page now holds.
    page.modelsStamp = String(reply.stamp || stamp);
    return true;
  }
}

export const MODEL_LIST = new ModelListFollower();
