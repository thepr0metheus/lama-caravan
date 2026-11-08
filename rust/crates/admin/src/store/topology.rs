//! The topology section: which cells exist, on which host, under which name. A slot is stored under its cell's own id (`rules::CellId`:
//! `c<port>` for a cell from before 2026-11-07, `c` and eight hex digits for a newer one); the machine is a field of the slot, and the
//! port is no fact of a slot at all — the scout leases one when the cell starts (Papyrus `caravan-scout-port-lease`, step 2).

use super::admin::AdminStore;
use super::base::{Document, Store};
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

    /// The raw section.
    pub fn raw(&mut self) -> &mut Document {
        self.section
    }

    /// A map under `name`, guaranteed to BE a map: a document where the value is null hands the caller a None that fails three frames away from the cause; this repairs it once.
    pub fn named(&mut self, name: &str) -> &mut Document {
        Store::section(self.section, name, &[])
    }

    /// The slots, by cell id.
    pub fn slots(&mut self) -> &mut Document {
        self.named("serverSlots")
    }

    /// The slot of cell `id`, or empty: what a caller that renders a cell wants.
    pub fn slot(&mut self, id: &str) -> Value {
        self.slots()
            .get(id)
            .filter(|slot| rules::Coerce::truthy(Some(*slot)))
            .cloned()
            .unwrap_or_else(|| Value::Object(Map::new()))
    }

    /// The slot, or none: what a caller about to change something wants, to refuse.
    pub fn find_slot(&mut self, id: &str) -> Option<&mut Value> {
        self.slots().get_mut(id)
    }

    /// Whether there is one.
    pub fn has_slot(&mut self, id: &str) -> bool {
        self.slots().contains_key(id)
    }

    /// Stores a slot under its cell's id.
    pub fn put_slot(&mut self, id: &str, slot: Value) {
        self.slots().insert(id.to_string(), slot);
    }

    /// Removes a slot; answers with what was there.
    pub fn drop_slot(&mut self, id: &str) -> Option<Value> {
        self.slots().shift_remove(id)
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
