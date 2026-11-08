//! The board's reading: the names it has, as the board reads them. The reader rule is asked from this reading, so a name the
//! board can write down is a name the rule has facts about. Held by `scripts/check_media_reader.py` (rule 7), with the case
//! table in `contract/media_reader.json` (`names`); the words are in `docs/vision-describe.md`.

use super::CloudData;
use crate::proxies::config::ProxiesConfig;
use rules::{Credentials, EntryModels, ModelCatalogue};
use serde_json::Value;

impl CloudData<'_> {
    /// The names the board has: its pools and the models it knows, with the routers that say which name is a machine's model
    /// and the keys that say which account is signed in. A reading of the pools alone answered `media_reader_unknown` for
    /// every model name on the live board on 2026-11-06 — a fact about the reading, not about the model.
    pub fn board_names(&self, data: &Value) -> EntryModels {
        let payload = ProxiesConfig::of(self.app).read_payload();
        self.read_names(data, payload.get("routers"))
    }

    /// The models a client calls without a pool, as the board reads them.
    pub fn live_models(&self, routers: Option<&Value>) -> EntryModels {
        self.read_names(&self.load(), routers)
    }

    /// The one place the board's reading is built.
    fn read_names(&self, data: &Value, routers: Option<&Value>) -> EntryModels {
        EntryModels::read(routers, Some(data), &Credentials::read(Some(&self.secrets())), ModelCatalogue::default())
    }
}
