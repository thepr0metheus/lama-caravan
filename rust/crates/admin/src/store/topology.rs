//! The topology section: which cells exist, on which host, under which key. A slot is stored under `"<hostId>:<port>"`, and that string is the whole invariant: a lookup that builds the key differently from the write addresses a slot that is not there. So the key is built in ONE place.

use super::admin::AdminStore;
use super::base::{Document, Store};
use crate::paths::HostIds;
use serde_json::{Map, Value};

/// A view onto the admin document's `topology` section. Holds no data of its own; saving is still the document's job.
pub struct Topology<'doc> {
    section: &'doc mut Document,
}

impl<'doc> Topology<'doc> {
    /// The view of a document.
    pub fn of(doc: &'doc mut Document) -> Self {
        Self { section: AdminStore::topology(doc) }
    }

    /// The one spelling of a slot's key.
    pub fn slot_key(host_id: &str, port: i64) -> String {
        format!("{}:{port}", HostIds::canonical(host_id))
    }

    /// The raw section.
    pub fn raw(&mut self) -> &mut Document {
        self.section
    }

    /// A map under `name`, guaranteed to BE a map: a document where the value is null hands the caller a None that fails three frames away from the cause; this repairs it once.
    pub fn named(&mut self, name: &str) -> &mut Document {
        Store::section(self.section, name, &[])
    }

    /// The slots.
    pub fn slots(&mut self) -> &mut Document {
        self.named("serverSlots")
    }

    /// The slot for this host and port, or empty: what a caller that renders a cell wants.
    pub fn slot(&mut self, host_id: &str, port: i64) -> Value {
        let key = Self::slot_key(host_id, port);
        self.slots()
            .get(&key)
            .filter(|slot| rules::Coerce::truthy(Some(*slot)))
            .cloned()
            .unwrap_or_else(|| Value::Object(Map::new()))
    }

    /// The slot, or none: what a caller about to change something wants, to refuse.
    pub fn find_slot(&mut self, host_id: &str, port: i64) -> Option<&mut Value> {
        let key = Self::slot_key(host_id, port);
        self.slots().get_mut(&key)
    }

    /// Whether there is one.
    pub fn has_slot(&mut self, host_id: &str, port: i64) -> bool {
        let key = Self::slot_key(host_id, port);
        self.slots().contains_key(&key)
    }

    /// Stores a slot under its canonical key, and answers with that key.
    pub fn put_slot(&mut self, host_id: &str, port: i64, slot: Value) -> String {
        let key = Self::slot_key(host_id, port);
        self.slots().insert(key.clone(), slot);
        key
    }

    /// Removes a slot; answers with what was there.
    pub fn drop_slot(&mut self, host_id: &str, port: i64) -> Option<Value> {
        let key = Self::slot_key(host_id, port);
        self.slots().shift_remove(&key)
    }

    /// The clients.
    pub fn clients(&mut self) -> &mut Document {
        self.named("clients")
    }

    /// Machines with a scout: what their reports say.
    pub fn hosts(&mut self) -> &mut Document {
        self.named("hosts")
    }

    /// The assignments.
    pub fn assignments(&mut self) -> &mut Document {
        self.named("assignments")
    }

    /// The clients' aliases.
    pub fn aliases(&mut self) -> &mut Document {
        self.named("clientAliases")
    }

    /// The machines' power schedules.
    pub fn power_schedules(&mut self) -> &mut Document {
        self.named("hostPowerSchedules")
    }

    /// The descriptions of the models, by the model's folder.
    pub fn model_notes(&mut self) -> &mut Document {
        self.named("modelNotes")
    }

    /// What each model's developer recommends to start it with.
    pub fn model_params(&mut self) -> &mut Document {
        self.named("modelParams")
    }

    /// The owner's own comment on each model.
    pub fn model_comments(&mut self) -> &mut Document {
        self.named("modelComments")
    }

    /// The owner's like or dislike of each model.
    pub fn model_ratings(&mut self) -> &mut Document {
        self.named("modelRatings")
    }
}
