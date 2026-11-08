//! The slots keyed by their cell's own id. Until 2026-11-07 a slot was kept under `<host>:<port>`, with the port in it and in its
//! config: the port was held for the cell whether it ran or not. From then on the scout leases a port when a cell starts
//! (Papyrus `caravan-scout-port-lease`, step 2), so a slot is kept under its cell's id and holds no port at all.
//!
//! The move is done once by content, when the document is opened: a slot kept under a machine and a port goes under
//! `rules::CellId::of_port`, the name the scout comes to on its own for the same cell, and so does what the machines' records said
//! by port (the cells a scout keeps on autostart). A slot already under an id is left as it is.

use super::base::Document;
use rules::CellId;
use serde_json::{Map, Value, json};

/// The move of the slots to their cells' ids.
pub struct SlotsByCell;

impl SlotsByCell {
    /// The cell id of a slot kept as `<host>:<port>`; `None` for a key that is an id already, or no such key.
    fn id_of_key(key: &str) -> Option<String> {
        if CellId::is_name(key) {
            return None;
        }
        let (_, port) = key.rsplit_once(':')?;
        CellId::read(&json!(port))
    }

    /// The slot as it is kept under its id: the id is its own, and the port is no fact of it.
    fn moved(mut slot: Value, id: &str) -> Value {
        if let Some(fields) = slot.as_object_mut() {
            fields.insert("id".to_string(), json!(id));
            fields.shift_remove("port");
            if let Some(config) = fields.get_mut("config").and_then(Value::as_object_mut) {
                config.shift_remove("PORT");
            }
        }
        slot
    }

    /// The slots keyed by their ids, in the order they were kept; the moves made, `(old key, id)`.
    fn slots(slots: &mut Map<String, Value>) -> Vec<(String, String)> {
        if !slots.keys().any(|key| Self::id_of_key(key).is_some()) {
            return Vec::new();
        }
        let mut moves = Vec::new();
        let mut kept = Map::new();
        for (key, slot) in std::mem::take(slots) {
            let Some(id) = Self::id_of_key(&key) else {
                kept.insert(key, slot);
                continue;
            };
            // Ports were one per fleet, so two slots never come to one id; were it so, the second is not lost but kept apart.
            let id = if kept.contains_key(&id) { format!("{id}d") } else { id };
            kept.insert(id.clone(), Self::moved(slot, &id));
            moves.push((key, id));
        }
        *slots = kept;
        moves
    }

    /// What a machine's record said by port, said by id: the cells its scout keeps on autostart.
    fn host(host: &mut Value) {
        if let Some(list) = host.get_mut("autostart").and_then(Value::as_array_mut) {
            let ids: Vec<Value> = list.iter().filter_map(CellId::read).map(Value::String).collect();
            *list = ids;
        }
        if let Some(requests) = host.get_mut("autostartRequests").and_then(Value::as_object_mut) {
            let moved: Map<String, Value> = std::mem::take(requests)
                .into_iter()
                .map(|(key, request)| (CellId::read(&json!(key)).unwrap_or(key), request))
                .collect();
            *requests = moved;
        }
    }

    /// Whether the document holds a slot to move: what the copy of the file before the move is kept for.
    pub fn pending(doc: &Document) -> bool {
        let slots = doc.get("topology").and_then(|topology| topology.get("serverSlots")).and_then(Value::as_object);
        slots.is_some_and(|slots| slots.keys().any(|key| Self::id_of_key(key).is_some()))
    }

    /// The move, once by content; the moves made, empty when nothing was left to move.
    pub fn migrate(doc: &mut Document) -> Vec<(String, String)> {
        let Some(topology) = doc.get_mut("topology").and_then(Value::as_object_mut) else {
            return Vec::new();
        };
        let moves = match topology.get_mut("serverSlots").and_then(Value::as_object_mut) {
            Some(slots) => Self::slots(slots),
            None => Vec::new(),
        };
        if !moves.is_empty()
            && let Some(hosts) = topology.get_mut("hosts").and_then(Value::as_object_mut)
        {
            hosts.values_mut().for_each(Self::host);
        }
        moves
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_slot_of_before_goes_under_its_cell_s_id_with_no_port() {
        let mut doc: Document = serde_json::from_value(json!({"topology": {
            "serverSlots": {
                "box:22001": {"id": "box:22001", "hostId": "box", "port": 22001, "note": "mine", "config": {"PORT": "22001", "MODEL_FILE": "m.gguf"}},
                "c3f9a02b1": {"id": "c3f9a02b1", "hostId": "box", "config": {"MODEL_FILE": "n.gguf"}},
                "box:22002": {"id": "box:22002", "hostId": "box", "port": 22002},
            },
            "hosts": {"box": {"autostart": [22001, "c3f9a02b1"], "autostartRequests": {"22001": {"config": {}}}}},
        }}))
        .unwrap();
        let moves = SlotsByCell::migrate(&mut doc);
        assert_eq!(moves, [("box:22001".to_string(), "c22001".to_string()), ("box:22002".to_string(), "c22002".to_string())]);
        let topology = &doc["topology"];
        let keys: Vec<&String> = topology["serverSlots"].as_object().unwrap().keys().collect();
        assert_eq!(keys, ["c22001", "c3f9a02b1", "c22002"], "in the order they were kept");
        assert_eq!(
            topology["serverSlots"]["c22001"],
            json!({"id": "c22001", "hostId": "box", "note": "mine", "config": {"MODEL_FILE": "m.gguf"}}),
            "the note stays, the port goes from the slot and from its config"
        );
        assert_eq!(topology["hosts"]["box"]["autostart"], json!(["c22001", "c3f9a02b1"]));
        assert_eq!(topology["hosts"]["box"]["autostartRequests"], json!({"c22001": {"config": {}}}));
        // Negative: done once by content — a document already moved is left as it is.
        let before = doc.clone();
        assert!(SlotsByCell::migrate(&mut doc).is_empty());
        assert_eq!(doc, before);
    }
}
