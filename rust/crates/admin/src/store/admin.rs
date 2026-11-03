//! `admin.json`: the panel's own document: topology, pricing, favourites, tokens.

use super::base::{Document, Store};
use crate::domain::host::HostRecord;
use crate::domain::runner::RunnerRegistry;
use crate::paths::{CONTROLLER_HOST_ID, HostIds};
use plumbing::Log;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::path::PathBuf;

/// The admin document, with its defaults and its migrations.
pub struct AdminStore {
    store: Store,
    monitor_retention: i64,
}

impl AdminStore {
    /// The one-off below cannot tell a record it repaired from one written after it by its content, so it runs once, and its name stays in the document's `migrations`.
    const METRICS_UNSAID: &'static str = "metrics-unsaid-2026-10";

    /// What scouts' reports and adoption left in the document, and what no code reads since 2026-09-24.
    const SCOUT_WORDS_CLIENT: [&'static str; 6] = ["manual", "candidates", "assignments", "applyStatus", "state", "ageSeconds"];
    const SCOUT_WORDS_AGENT: [&'static str; 2] = ["manual", "runtimeDetected"];
    const SCOUT_WORDS_ENTRY: [&'static str; 3] = ["agentUrl", "applyStatus", "desiredAt"];
    const SCOUT_WORDS_ROW: [&'static str; 1] = ["manual"];

    /// Opens the document, seeds it and brings it forward.
    pub fn open(path: PathBuf, monitor_retention: i64, runners: &RunnerRegistry) -> Self {
        let this = Self { store: Store::open(path), monitor_retention };
        this.seed();
        this.migrate(runners);
        this
    }

    /// The store itself.
    pub fn store(&self) -> &Store {
        &self.store
    }

    /// A look at the document.
    pub fn read<R>(&self, look: impl FnOnce(&Document) -> R) -> R {
        self.store.read(look)
    }

    /// A change in memory.
    pub fn change<R>(&self, edit: impl FnOnce(&mut Document) -> R) -> R {
        self.store.change(edit)
    }

    /// A save of what was changed.
    pub fn save(&self) -> std::io::Result<()> {
        self.store.save()
    }

    /// A change, and a save right after it. A save that fails is said: the change holds in memory, and the next save takes it.
    pub fn saving<R>(&self, edit: impl FnOnce(&mut Document) -> R) -> R {
        let out = self.store.change(edit);
        if let Err(error) = self.store.save() {
            Log::line(&format!("admin state not saved: {error}"));
        }
        out
    }

    /// Re-reads the file, as a settings import does.
    pub fn reload(&self) {
        self.store.refill(Store::read_file(self.store.path()));
        self.seed();
    }

    /// Fills in whatever the document does not have yet.
    pub fn seed(&self) {
        let retention = self.monitor_retention;
        self.store.change(|doc| {
            Store::section(doc, "monitor", &[]).entry("retentionSeconds").or_insert_with(|| json!(retention));
            Store::section(doc, "topology", &["clients", "hosts", "assignments", "layout"]);
            // A manual price for LOCAL tokens, $ per 1M: the usage panel's "what this would have cost in the cloud".
            let local = Store::section(doc, "localPricing", &[]);
            local.entry("inputPer1M").or_insert_with(|| json!(0.0));
            local.entry("outputPer1M").or_insert_with(|| json!(0.0));
            // Manual per-model API price overrides, for a model LiteLLM has no entry for.
            Store::section(doc, "apiPricing", &[]);
            doc.entry("hfToken").or_insert_with(|| json!(""));
            doc.entry("hfFavorites").or_insert_with(|| json!([]));
            // Field keys starred to mirror into the launch form's "Favorites" tab.
            doc.entry("favFields").or_insert_with(|| json!([]));
        });
    }

    /// The topology section with every subsection this caravan expects: a document written by an older version has sections this one needs, and the first caller should find them.
    pub fn topology(doc: &mut Document) -> &mut Document {
        let topology = Store::section(doc, "topology", &["clients", "hosts", "assignments", "clientAliases", "layout"]);
        // Persistent server slots so a proxy cable stays attached even when the server is stopped.
        topology.entry("serverSlots").or_insert_with(|| Value::Object(Map::new()));
        topology
    }

    fn migrate(&self, runners: &RunnerRegistry) {
        let (rekeyed, dropped, split, unsaid) = self.store.change(|doc| {
            (
                Self::rekey_legacy_controller_slots(doc),
                Self::forget_what_reports_said(doc),
                Self::split_hosts_from_clients(doc),
                Self::metrics_unsaid(doc, runners),
            )
        });
        if (rekeyed || !dropped.is_empty() || !split.is_empty() || unsaid.is_some())
            && let Err(error) = self.store.save()
        {
            Log::line(&format!("store: migrated, not saved: {error}"));
        }
        if let Some(keys) = unsaid.filter(|keys| !keys.is_empty()) {
            Log::line(&format!(
                "store: llama.cpp cells start with their metrics again, the form had said off for them: {}",
                keys.join(", ")
            ));
        }
        if !dropped.is_empty() {
            let words: Vec<String> = dropped.iter().map(|(what, count)| format!("{count} {what}")).collect();
            Log::line(&format!("store: dropped what scout reports and adoption left: {}", words.join(", ")));
        }
        if !split.is_empty() {
            let words: Vec<String> = split.iter().map(|(id, what)| format!("{id} ({what})")).collect();
            Log::line(&format!("store: machines split into host and client records: {}", words.join(", ")));
        }
    }

    /// The controller's stored host id used to be the literal machine name; slots move to the role-based sentinel. Never over a canonical key: if both spellings of one port exist, the canonical record wins.
    fn rekey_legacy_controller_slots(doc: &mut Document) -> bool {
        let Some(slots) =
            doc.get_mut("topology").and_then(|topology| topology.get_mut("serverSlots")).and_then(Value::as_object_mut)
        else {
            return false;
        };
        let mut changed = false;
        let keys: Vec<String> = slots.keys().cloned().collect();
        for key in keys {
            let Some((head, port)) = key.split_once(':') else {
                continue;
            };
            if !HostIds::LEGACY.contains(&head) {
                continue;
            }
            let new_key = format!("{CONTROLLER_HOST_ID}:{port}");
            let Some(mut slot) = slots.shift_remove(&key) else {
                continue;
            };
            if let Some(fields) = slot.as_object_mut() {
                fields.insert("hostId".to_string(), json!(CONTROLLER_HOST_ID));
                fields.insert("id".to_string(), json!(new_key));
            }
            slots.entry(new_key).or_insert(slot);
            changed = true;
        }
        changed
    }

    /// A llama.cpp cell's metrics box says "0" because the form took it from the controller's own config: nobody turned it off. The box is unsaid again. Once: a "0" set after this is the operator's. The keys of the slots changed; `None` when it was done before.
    fn metrics_unsaid(doc: &mut Document, runners: &RunnerRegistry) -> Option<Vec<String>> {
        let done = doc.get("migrations").cloned();
        let list = done.as_ref().and_then(Value::as_array);
        if list.is_some_and(|marks| marks.iter().any(|mark| mark.as_str() == Some(Self::METRICS_UNSAID))) {
            return None;
        }
        let mut changed = Vec::new();
        if let Some(slots) =
            doc.get_mut("topology").and_then(|topology| topology.get_mut("serverSlots")).and_then(Value::as_object_mut)
        {
            for (key, slot) in slots.iter_mut() {
                let Some(config) = slot.get_mut("config").and_then(Value::as_object_mut) else {
                    continue;
                };
                let box_says = config.get("ENABLE_METRICS").map_or_else(String::new, |said| Coerce::stripped(Some(said)));
                if box_says == "0" && runners.for_config(config).row().llama_config {
                    config.insert("ENABLE_METRICS".to_string(), json!(""));
                    changed.push(key.clone());
                }
            }
        }
        let mut kept: Vec<String> = list.into_iter().flatten().filter_map(Value::as_str).map(str::to_string).collect();
        kept.push(Self::METRICS_UNSAID.to_string());
        kept.sort();
        kept.dedup();
        doc.insert("migrations".to_string(), json!(kept));
        Some(changed)
    }

    /// One combined record per machine becomes a host record and a client record, by `HostRecord::split`. A host already in `hosts` is left as it is.
    fn split_hosts_from_clients(doc: &mut Document) -> Vec<(String, &'static str)> {
        let Some(topology) = doc.get_mut("topology").and_then(Value::as_object_mut) else {
            return Vec::new();
        };
        let Some(clients) = topology.get("clients").and_then(Value::as_object).cloned() else {
            return Vec::new();
        };
        let mut split = Vec::new();
        let mut left = clients.clone();
        // absent-ok: `setdefault("hosts", {})`: a document with no hosts has none yet.
        let mut hosts = topology.get("hosts").and_then(Value::as_object).cloned().unwrap_or_default();
        for (id, row) in &clients {
            let (host, client) = HostRecord::split(row);
            let Some(host) = host else {
                continue;
            };
            hosts.entry(id.clone()).or_insert(host);
            match client {
                None => {
                    left.shift_remove(id);
                    split.push((id.clone(), "host only"));
                }
                Some(client) => {
                    left.insert(id.clone(), client);
                    split.push((id.clone(), "host+client"));
                }
            }
        }
        topology.insert("hosts".to_string(), Value::Object(hosts));
        topology.insert("clients".to_string(), Value::Object(left));
        split
    }

    fn drop_words(row: &mut Value, what: &str, words: &[&str], dropped: &mut BTreeMap<String, i64>) {
        if let Some(fields) = row.as_object_mut() {
            for key in words {
                if fields.shift_remove(*key).is_some() {
                    *dropped.entry(format!("{what} {key}")).or_default() += 1;
                }
            }
        }
    }

    /// Drops the scout's words and the tombstones of deleted agents. What went, by what it was.
    fn forget_what_reports_said(doc: &mut Document) -> BTreeMap<String, i64> {
        let mut dropped = BTreeMap::new();
        let Some(topology) = doc.get_mut("topology").and_then(Value::as_object_mut) else {
            return dropped;
        };
        for client in
            topology.get_mut("clients").and_then(Value::as_object_mut).into_iter().flat_map(|clients| clients.values_mut())
        {
            Self::drop_words(client, "client", &Self::SCOUT_WORDS_CLIENT, &mut dropped);
            for agent in client.get_mut("agents").and_then(Value::as_array_mut).into_iter().flatten() {
                Self::drop_words(agent, "agent", &Self::SCOUT_WORDS_AGENT, &mut dropped);
            }
        }
        for entry in
            topology.get_mut("assignments").and_then(Value::as_object_mut).into_iter().flat_map(|entries| entries.values_mut())
        {
            Self::drop_words(entry, "assignment entry", &Self::SCOUT_WORDS_ENTRY, &mut dropped);
            for row in entry.get_mut("assignments").and_then(Value::as_array_mut).into_iter().flatten() {
                Self::drop_words(row, "assignment row", &Self::SCOUT_WORDS_ROW, &mut dropped);
            }
        }
        if let Some(tombstones) = topology.shift_remove("deletedAgents") {
            let lists = tombstones.as_object().into_iter().flat_map(|lists| lists.values()).filter_map(Value::as_array);
            dropped.insert("tombstones".to_string(), lists.map(|list| list.len() as i64).sum());
        }
        dropped
    }
}
