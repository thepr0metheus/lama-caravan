// Shared mutable frontend state.
//
// `state` and `topology` are live bindings: importers see updates, but only
// this module may rebind them — writers go through setState()/setTopology().
// `ui` holds the flags historically rebound from several features (mostly the
// big delegated click router); property writes need no setters.

export let state = null;
export let topology = null;

export function setState(value) { state = value; }
export function setTopology(value) { topology = value; }

export const ui = {
  topologyRouterDetailId: "",
  topologyCanvasRouterId: "",
  topologyRouterNodeCfgId: "",
  topologyRouterInputsExpanded: false,
  topologyRouterInputSearch: "",
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
  topologyAgentConfigMode: "",
  pendingConfirm: null,
  latestSystemMonitor: null,
  routeErrHour: null,
  _lastActivityFingerprint: "",
  _lastCloudProvidersKey: "",
};
