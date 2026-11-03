//! Who this machine is on the board: an id that stays, a name that follows it.

use crate::config::ScoutConfig;
use crate::log::Log;
use crate::state::ScoutState;
use os::Host;
use rules::Coerce;
use serde_json::json;
use std::sync::Arc;

/// The id in use is pinned in `state.json`, and at the next start the pin wins over the hostname: a rename changes only the name the board
/// shows. The operator can still choose an id: `hostId` in `config.json` wins over the pin, and becomes the pin.
pub struct HostIdentity {
    config: Arc<ScoutConfig>,
    state: Arc<ScoutState>,
}

impl HostIdentity {
    /// The word for a machine that has no name at all.
    const FALLBACK: &'static str = "remote";

    /// The identity of this config and state.
    pub fn new(config: Arc<ScoutConfig>, state: Arc<ScoutState>) -> Self {
        Self { config, state }
    }

    /// The id for this run: the file's `hostId`, else the pin, else the hostname; pinned, and put into the running config.
    pub fn settle(&self) -> String {
        let chosen = Coerce::stripped(self.config.from_file("hostId"));
        let pinned = self.state.read(|doc| Coerce::stripped(doc.get("hostId")));
        let host_id = [chosen, pinned.clone(), Host::short_name()].into_iter().find(|id| !id.is_empty());
        let Some(host_id) = host_id else {
            // A machine with no name yet, an early boot: called something for this run, pinned as nothing.
            self.config.set("hostId", json!(Self::FALLBACK));
            return Self::FALLBACK.to_string();
        };
        if host_id != pinned {
            self.state.change(|doc| doc.insert("hostId".to_string(), json!(host_id)));
        }
        self.config.set("hostId", json!(host_id));
        if pinned.is_empty() {
            Log::line(&format!("[identity] host id {host_id:?} pinned: a rename of this machine keeps it"));
        } else if host_id != pinned {
            Log::line(&format!("[identity] host id {pinned:?} -> {host_id:?}: config.json names it"));
        }
        host_id
    }

    /// The name the board shows: the file's `displayName`, else the hostname right now: a rename shows at the next report.
    pub fn name(&self) -> String {
        let said = Coerce::stripped(self.config.from_file("displayName"));
        [said, Host::short_name(), self.config.text("hostId")]
            .into_iter()
            .find(|name| !name.is_empty())
            .unwrap_or_else(|| Self::FALLBACK.to_string())
    }
}
