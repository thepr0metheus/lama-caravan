//! What a scout of before kept by a cell's port, kept by the cell's name (Papyrus `caravan-scout-port-lease`, step 2). Until 2026-11-07 a cell was its
//! port: its record in `state.json` (`cells`), its kept start request (`autostart`), the files its start asked the cache for (`modelUse`, `workModelUse`)
//! and its logs were keyed by it. Each is moved once by content, when the scout starts, before any cell is found again: a key that is a port becomes
//! `rules::CellId::of_port` of it, the name the controller comes to on its own for the same cell. The list of cells the controller keeps (`knownCells`)
//! is the controller's to say again: a list of before is let go, and its next answer brings the cells by name. A key that is a name already is left as
//! it is, so a second start moves nothing.

use super::logs::CellLogs;
use crate::log::Log;
use crate::state::ScoutState;
use rules::CellId;
use serde_json::{Map, Value, json};

/// The move of one `state.json`, by content.
pub struct StateByCell;

impl StateByCell {
    /// The state's keys this move reads.
    const RECORDS: &'static str = "cells";
    const AUTOSTART: &'static str = "autostart";
    const USES: [&'static str; 2] = ["modelUse", "workModelUse"];
    const KNOWN: &'static str = "knownCells";
    /// What the copy of the state before the move is called after the file's own name: a scout before 2.46 reads none of it after the
    /// move, and the way back past it is this copy (deploy/nas/README.md).
    const COPY_SUFFIX: &'static str = "bak-before-cell-ids";

    /// The name of a key that bore a port; `None` for a key that is a name already, or no cell's.
    fn id_of_port_key(key: &str) -> Option<String> {
        (!CellId::is_name(key)).then(|| CellId::read(&json!(key))).flatten()
    }

    /// A map keyed by ports, keyed by names in the order it was kept; how many keys moved. `fill` writes the name into what moved.
    fn rekeyed(map: &mut Map<String, Value>, fill: impl Fn(&mut Value, &str)) -> usize {
        if !map.keys().any(|key| Self::id_of_port_key(key).is_some()) {
            return 0;
        }
        let mut moved = 0;
        let mut kept = Map::new();
        for (key, mut value) in std::mem::take(map) {
            match Self::id_of_port_key(&key) {
                Some(id) if !kept.contains_key(&id) => {
                    fill(&mut value, &id);
                    kept.insert(id, value);
                    moved += 1;
                }
                _ => {
                    kept.insert(key, value);
                }
            }
        }
        *map = kept;
        moved
    }

    /// A record names its cell; its port is the port its run holds, as before.
    fn record(record: &mut Value, id: &str) {
        if let Some(fields) = record.as_object_mut() {
            fields.insert("id".to_string(), json!(id));
        }
    }

    /// A kept request names its cell, and no port: a start leases one.
    fn request(entry: &mut Value, id: &str) {
        let Some(payload) = entry.get_mut("payload").and_then(Value::as_object_mut) else {
            return;
        };
        payload.insert("cellId".to_string(), json!(id));
        payload.shift_remove("port");
        if let Some(Value::Object(config)) = payload.get_mut("config") {
            config.shift_remove("PORT");
        }
    }

    /// The entries of the files a start asked for, each by its cell's name; how many moved.
    fn uses(list: &mut [Value]) -> usize {
        let mut moved = 0;
        for entry in list.iter_mut().filter_map(Value::as_object_mut) {
            let Some(id) = entry.get("port").and_then(CellId::read).filter(|_| !entry.contains_key("cell")) else {
                continue;
            };
            entry.insert("cell".to_string(), json!(id));
            entry.shift_remove("port");
            moved += 1;
        }
        moved
    }

    /// The move of `doc`; the words of what moved, one per kind, empty when nothing did.
    pub fn migrate(doc: &mut Map<String, Value>) -> Vec<String> {
        let mut said = Vec::new();
        let mut count = |what: &str, moved: usize| {
            if moved > 0 {
                said.push(format!("{moved} {what}"));
            }
        };
        if let Some(records) = doc.get_mut(Self::RECORDS).and_then(Value::as_object_mut) {
            count("records", Self::rekeyed(records, Self::record));
        }
        if let Some(entries) = doc.get_mut(Self::AUTOSTART).and_then(Value::as_object_mut) {
            count("autostart requests", Self::rekeyed(entries, Self::request));
        }
        for key in Self::USES {
            if let Some(list) = doc.get_mut(key).and_then(Value::as_array_mut) {
                count(&format!("{key} entries"), Self::uses(list));
            }
        }
        let known_of_before = doc
            .get(Self::KNOWN)
            .and_then(Value::as_array)
            .is_some_and(|list| list.iter().any(|item| item.get("id").is_none() && item.get("port").is_some()));
        if known_of_before {
            doc.shift_remove(Self::KNOWN);
            count("list of the controller's cells let go (it comes again by name)", 1);
        }
        said
    }
}

impl StateByCell {
    /// Whether the state keeps anything by a cell's port: the move tried on a copy of it.
    fn pending(doc: &Map<String, Value>) -> bool {
        !Self::migrate(&mut doc.clone()).is_empty()
    }

    /// The move of this scout's state and logs, once by content, before anything reads a cell; one line in the log when anything moved.
    /// The state as it was is kept beside it first (`stamp` names the copy): no copy, no move — the next start tries again.
    pub fn settle(state: &ScoutState, logs: &CellLogs, stamp: &str) {
        if state.read(Self::pending)
            && let Err(error) = state.keep_copy(&format!("{}-{stamp}", Self::COPY_SUFFIX))
        {
            Log::line(&format!(
                "[cells] the cells stay under their ports for now: the copy of the state before the move was not kept ({error})"
            ));
            return;
        }
        let mut said = state.change(Self::migrate);
        let renamed = logs.rename_by_port();
        if !renamed.is_empty() {
            said.push(format!("{} logs renamed", renamed.len()));
        }
        if !said.is_empty() {
            Log::line(&format!("[cells] cells are known by their names now, a port is leased at a start: {}", said.join(", ")));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn what_was_kept_by_port_is_kept_by_name() {
        let mut doc: Map<String, Value> = serde_json::from_value(json!({
            "cells": {"22001": {"port": 22001, "pid": 5, "kind": "llama"}, "c3f9a02b1": {"id": "c3f9a02b1", "port": 22002}},
            "autostart": {"22003": {"payload": {"port": 22003, "modelPath": "m", "config": {"PORT": "22003", "CTX_SIZE": "8192"}}}},
            "modelUse": [{"files": ["a"], "port": 22001, "ok": true}, {"files": ["b"], "cell": "c3f9a02b1"}],
            "workModelUse": [],
            "knownCells": [{"port": 22001, "config": {}}],
            "heartbeat": {"state": "ok"},
        }))
        .unwrap();
        let said = StateByCell::migrate(&mut doc);
        assert_eq!(said.len(), 4, "{said:?}");
        assert_eq!(
            doc["cells"]["c22001"],
            json!({"port": 22001, "pid": 5, "kind": "llama", "id": "c22001"}),
            "the port its run holds stays in it"
        );
        assert_eq!(doc["cells"]["c3f9a02b1"]["port"], 22002, "a record of now is left as it is");
        assert_eq!(
            doc["autostart"]["c22003"]["payload"],
            json!({"modelPath": "m", "config": {"CTX_SIZE": "8192"}, "cellId": "c22003"}),
            "a kept request names its cell and no port"
        );
        assert_eq!(
            doc["modelUse"],
            json!([{"files": ["a"], "ok": true, "cell": "c22001"}, {"files": ["b"], "cell": "c3f9a02b1"}])
        );
        assert_eq!(doc.get("knownCells"), None, "a list of before is let go: the controller says its cells again, by name");
        assert_eq!(doc["heartbeat"], json!({"state": "ok"}), "what is no cell's is not touched");
        // Negative: once by content — a second start moves nothing.
        let before = doc.clone();
        assert!(StateByCell::migrate(&mut doc).is_empty());
        assert_eq!(doc, before);
    }

    #[test]
    fn the_state_as_it_was_is_kept_beside_it_before_the_move_and_once() {
        let folder = std::env::temp_dir().join(format!("caravan-scout-state-copy-{}", std::process::id()));
        drop(std::fs::remove_dir_all(&folder));
        std::fs::create_dir_all(folder.join("cell-logs")).unwrap();
        let path = folder.join("state.json");
        let before = json!({"cells": {"22001": {"port": 22001, "pid": 5}}, "autostart": {}});
        std::fs::write(&path, before.to_string()).unwrap();
        let clock: std::sync::Arc<dyn os::clock::Clock> = std::sync::Arc::new(os::clock::SystemClock::new());
        let state = ScoutState::load(&path, 0);
        let logs = CellLogs::of_state(&state, clock);
        StateByCell::settle(&state, &logs, "20261108-120000");
        assert!(state.read(|doc| doc["cells"].get("c22001").is_some()), "the record is under its cell's name");
        let copy = folder.join("state.json.bak-before-cell-ids-20261108-120000");
        let kept: Value = serde_json::from_slice(&std::fs::read(&copy).unwrap()).unwrap();
        assert_eq!(kept, before, "the copy is the file as it was: the way back past the move");
        // Negative: once — a second start finds nothing kept by a port, and keeps no second copy.
        StateByCell::settle(&state, &logs, "20261108-130000");
        assert!(!folder.join("state.json.bak-before-cell-ids-20261108-130000").exists());
        drop(std::fs::remove_dir_all(&folder));
    }
}
