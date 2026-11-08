//! The way from this controller to one cell: through its machine's scout (`rules::CellDoor`).
//!
//! Since step 7 of the owner's plan (Papyrus `caravan-scout-port-lease`, 2026-11-08) a cell listens on its machine's loopback alone,
//! and the machine shows the network one port of the caravan, its scout's. So the cell's health and `/props` that the board reads, a
//! question of the Talk tab and a live talk all go to the scout's door, with the fleet token, as every call of the scout does. Before,
//! each asked `<machine>:<the cell's port>` straight over the network, and only the firewall kept anyone else out.

use super::machine_models::MachineOutputs;
use super::scout::ScoutAuth;
use crate::app::App;
use rules::{CellDoor, Coerce};
use serde_json::Value;

/// One cell as this controller reaches it.
#[derive(Debug, Clone)]
pub struct CellDoorway {
    /// The scout's address as its machine reported it, `http://<address>:<port>`.
    agent: String,
    /// The scout's address and port, for a connection of its own: a WebSocket.
    address: (String, u16),
    /// The cell's name.
    cell: String,
    /// The fleet token's field: none while accounts are off.
    fields: Vec<(&'static str, String)>,
}

impl CellDoorway {
    /// The way to the cell named `cell` of the machine whose record is `host`; `None` for a machine that reported no scout address
    /// with its port: then nothing reaches its cells, and the board says it does not know.
    pub fn of(app: &App, host: &Value, cell: &str) -> Option<Self> {
        let address = MachineOutputs::entry_address(host)?;
        let agent = Coerce::text(host.get("agentUrl")).trim_end_matches('/').to_string();
        Some(Self { agent, address, cell: cell.to_string(), fields: ScoutAuth::fields(app) })
    }

    /// The URL of the cell's own `path`.
    pub fn url(&self, path: &str) -> String {
        format!("{}{}", self.agent, self.target(path))
    }

    /// The request line's target for the cell's own `path`, for a connection of its own.
    pub fn target(&self, path: &str) -> String {
        CellDoor::path(&self.cell, path)
    }

    /// The scout's `address:port`.
    pub fn address(&self) -> String {
        format!("{}:{}", self.address.0, self.address.1)
    }

    /// The fields every request through the door carries: the fleet token's.
    pub fn fields(&self) -> &[(&'static str, String)] {
        &self.fields
    }

    /// What a memory of the cell's answers is kept under: the cell, behind its machine's scout.
    pub fn key(&self) -> String {
        format!("{} {}", self.agent, self.cell)
    }

    /// Where the words to the operator say the cell is.
    pub fn named(&self) -> String {
        format!("cell {} behind {}", self.cell, self.address())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::{TestApp, TestFolder};
    use serde_json::json;

    #[test]
    fn a_cell_is_reached_through_its_machine_s_scout() {
        let folder = TestFolder::new("cell-way");
        let app = TestApp::over(&folder.path, &[]);
        let way = CellDoorway::of(&app, &json!({"id": "box", "agentUrl": "http://10.0.0.5:8092/"}), "c22035").unwrap();
        assert_eq!(way.url("/health"), "http://10.0.0.5:8092/api/cell/c22035/health");
        assert_eq!(way.target("/backend"), "/api/cell/c22035/backend");
        assert_eq!(way.address(), "10.0.0.5:8092");
        assert!(!way.url("/props").contains(":22035/"), "negative: the cell's own port is no address from here");
    }

    #[test]
    fn a_machine_with_no_scout_address_has_no_way_to_its_cells() {
        let folder = TestFolder::new("cell-way-none");
        let app = TestApp::over(&folder.path, &[]);
        assert!(CellDoorway::of(&app, &json!({"id": "box"}), "c1").is_none());
        assert!(
            CellDoorway::of(&app, &json!({"id": "box", "agentUrl": "http://10.0.0.5"}), "c1").is_none(),
            "an address with no port"
        );
    }
}
