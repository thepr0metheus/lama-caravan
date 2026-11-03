// Shared mutable frontend state.
//
// `state` and `topology` are live bindings: importers see updates, but only
// this module may rebind them — writers go through setState()/setTopology().
// `ui` holds the flags historically rebound from several features (mostly the
// big delegated click router); property writes need no setters.

export let state = null;
export let topology = null;

// A reading of the topology travels while the page goes on, so it can land after a newer one or after the answer to a write,
// and it then draws what was: on Routing, which reads on a beat since 1.3.691, a row just carried would jump back to where it stood
// until the next beat. Each reading is numbered as it sets out, and one older than what the page holds is dropped.
class TopologyReadings {
  constructor() {
    this.asked = 0;   // the number of the reading that set out last
    this.held = 0;    // the newest reading the page holds, or one a write's answer has outdated
  }

  setOut() {
    this.asked += 1;
    return this.asked;
  }

  // The reading lands, and the page holds it from now on; false when it is older than what the page holds.
  land(number, value) {
    if (number <= this.held) return false;
    this.held = number;
    topology = value;
    return true;
  }

  // A write's answer is the controller's word after that write: the readings on their way may have left before it.
  answered() {
    this.held = this.asked;
  }
}

export const TOPOLOGY_READINGS = new TopologyReadings();

export function setState(value) { state = value; }
export function setTopology(value) {
  topology = value;
  TOPOLOGY_READINGS.answered();
}

export const ui = {
  topologyRouterDetailId: "",
  topologyCanvasRouterId: "",
  topologyRouterNodeCfgId: "",
  topologyProxyFormOpen: false,
  topologyProxyEditingId: "",
  topologyCloudModalOpen: false,
  topologyCloudPickerOpen: false,
  topologyCloudForm: null,
  usageStatsModalOpen: false,
  usageStatsScope: "overview",
  usageStatsExpanded: "",
  usageStatsRateEdit: null,
  usageStatsDays: 30,
  pendingConfirm: null,
  latestSystemMonitor: null,
  routeErrHour: null,
  _lastActivityFingerprint: "",
  _lastCloudProvidersKey: "",
};
