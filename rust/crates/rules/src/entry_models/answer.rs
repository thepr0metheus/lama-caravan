//! The shapes the entry answers with: OpenAI's model object and its list, and Ollama's `/api/show`. These change when a
//! protocol's shape changes, not when the files are read, so they stand apart from the reading that answers from them.
//!
//! The reading is `EntryModels` (rust/crates/rules/src/entry_models.rs): nothing is decided here about what a name means —
//! the window and the kind are read from it, and an absence is answered as an absence.

use super::EntryModels;
use crate::cloud_pools::{ContextWindow, Pool};
use crate::route::Route;
use serde_json::{Value, json};

impl EntryModels {
    /// One model of the list in OpenAI's shape, answered at `created`. The window is the pool's against this client's own limit, absent
    /// when neither is known: a guessed window is worse than none.
    pub fn model_object(&self, route: &Route, pool: &Pool, created: i64) -> Value {
        let mut entry = serde_json::Map::new();
        entry.insert("id".to_string(), json!(pool.name));
        entry.insert("object".to_string(), json!("model"));
        entry.insert("created".to_string(), json!(created));
        entry.insert("owned_by".to_string(), json!("caravan"));
        if let Some(window) = ContextWindow::effective(route.context_limit, self.window(pool), route.context_auto) {
            entry.insert("context_length".to_string(), json!(window));
            entry.insert("max_model_len".to_string(), json!(window));
        }
        if let Some(kind) = self.kind(pool) {
            entry.extend(kind.models_entry());
        }
        Value::Object(entry)
    }

    /// `GET /v1/models`: what a client's key calls now, at `created`.
    pub fn list(&self, route: &Route, created: i64) -> Value {
        let data: Vec<Value> = self.models(&route.deny).into_iter().map(|pool| self.model_object(route, pool, created)).collect();
        json!({"object": "list", "data": data})
    }

    /// Ollama's `/api/show` for a pool, in Ollama's shape: the window under `model_info` and as `num_ctx` in its `parameters`, the figure
    /// `/v1/models` states. A pool that states no window answers without one.
    pub fn show(&self, route: &Route, pool: &Pool) -> Value {
        let window = ContextWindow::effective(route.context_limit, self.window(pool), route.context_auto);
        let mut model_info = serde_json::Map::new();
        model_info.insert("general.architecture".to_string(), json!("caravan"));
        if let Some(window) = window {
            model_info.insert("caravan.context_length".to_string(), json!(window));
        }
        json!({
            "modelfile": "",
            "parameters": window.map_or(String::new(), |window| format!("num_ctx {window}")),
            "template": "",
            "details": {
                "parent_model": "", "format": "", "family": "caravan", "families": ["caravan"],
                "parameter_size": "", "quantization_level": "",
            },
            "model_info": model_info,
        })
    }
}
