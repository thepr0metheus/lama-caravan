//! A cell's own listen address, retired: every cell listens on its machine's loopback (`rules::CellDoor::LISTEN`), the caravan's word
//! and not a setting of the cell.
//!
//! Until 2026-11-08 a cell's config held `HOST`, the address its server bound, and the form wrote "0.0.0.0" into every new cell: on
//! that day all 35 cells of the big machine held it. Step 7 of the owner's plan (Papyrus `caravan-scout-port-lease`) puts the cells
//! on the loopback, behind the machine's one port, its scout's; the command builder writes the loopback whatever a config says. A
//! `HOST` left in a config would say an address the cell no longer binds, so each slot is looked at once, at the start, and the field
//! goes. Run at every start, it finds nothing to do after the first: nothing writes the field any more.

use crate::app::App;
use crate::store::topology::Topology;
use rules::AppError;
use serde_json::{Value, json};

/// The retirement of the listen address.
pub struct ListenAddressRetired<'app> {
    app: &'app App,
}

impl<'app> ListenAddressRetired<'app> {
    /// The field that said where a cell's server listened.
    const FIELD: &'static str = "HOST";

    /// The retirement, once a start: `None` when no slot holds the field; else the cells it went from.
    pub fn migrate(app: &'app App) -> Result<Option<Value>, AppError> {
        Self { app }.run()
    }

    fn holding(&self) -> Vec<String> {
        self.app.admin.change(|doc| {
            Topology::of(doc)
                .slots()
                .iter()
                .filter(|(_, slot)| slot.get("config").and_then(|config| config.get(Self::FIELD)).is_some())
                .map(|(key, _)| key.clone())
                .collect()
        })
    }

    fn run(&self) -> Result<Option<Value>, AppError> {
        let holding = self.holding();
        if holding.is_empty() {
            return Ok(None);
        }
        self.app.admin.saving(|doc| {
            let mut view = Topology::of(doc);
            let slots = view.slots();
            for key in &holding {
                if let Some(config) = slots.get_mut(key).and_then(|slot| slot.get_mut("config")).and_then(Value::as_object_mut) {
                    config.shift_remove(Self::FIELD);
                }
            }
        });
        Ok(Some(json!({"cells": holding})))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::{TestApp, TestFolder};

    #[test]
    fn every_cell_loses_its_listen_address_once() {
        let folder = TestFolder::new("listen-address-retired");
        let app = TestApp::over(&folder.path, &[]);
        app.admin.saving(|doc| {
            let mut view = Topology::of(doc);
            let slots = view.slots();
            slots.insert("c22001".to_string(), json!({"hostId": "h", "config": {"HOST": "0.0.0.0", "MODEL_FILE": "m.gguf"}}));
            slots.insert("c22002".to_string(), json!({"hostId": "h", "config": {"MODEL_FILE": "n.gguf"}}));
            slots.insert("c22003".to_string(), json!({"hostId": "h"}));
        });
        let done = ListenAddressRetired::migrate(&app).unwrap().unwrap();
        assert_eq!(
            done,
            json!({"cells": ["c22001"]}),
            "negative: a cell with no such field, and one with no config, are not named"
        );
        let config = app.admin.change(|doc| Topology::of(doc).slots().get("c22001").cloned()).unwrap()["config"].clone();
        assert_eq!(config, json!({"MODEL_FILE": "m.gguf"}), "the rest of the config stays as it was");
        assert_eq!(ListenAddressRetired::migrate(&app).unwrap(), None, "the second start finds nothing to do");
    }
}
