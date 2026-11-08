//! What the controller does before it listens. A step that fails says so and the rest go on: the board that opens says what it found, and a controller that does not start says nothing.

use crate::app::App;
use crate::cloud::board_providers::ProviderDesk;
use crate::cloud::consumers::ConsumerDesk;
use crate::cloud::data::CloudData;
use crate::cloud::entry_move::EntryMove;
use crate::cloud::pool_ports::PoolPortsRetired;
use crate::cloud::pools::PoolDesk;
use crate::common::entry::{BuiltinClient, EntryDoor};
use crate::data_tree::DataTree;
use crate::fleet::cell_schedule::CellSchedule;
use crate::fleet::default_cells_retired::DefaultCellsRetired;
use crate::fleet::gpu_driver::GpuDriver;
use crate::fleet::listen_address_retired::ListenAddressRetired;
use crate::fleet::machine_rows::MachineRows;
use crate::fleet::reports::FleetReads;
use crate::models::model_list::ModelList;
use crate::models::moves::runner::MoveRunner;
use crate::monitoring::MonitorSampler;
use crate::proxies::client_ids::ClientIdsGiven;
use crate::proxies::config::ProxiesConfig;
use crate::proxies::dsl::RouterDsl;
use crate::proxies::entry_settings::EntrySettings;
use crate::proxies::queue_thresholds::QueueThresholds;
use crate::proxies::service::Services;
use crate::proxies::stats::ProxyStats;
use crate::topology::TopologyState;
use plumbing::{Log, Ticking};
use rules::{AppError, Coerce, ReleasePatience};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

/// The start.
pub struct Startup {
    app: Arc<App>,
}

impl Startup {
    /// A start of this controller.
    pub fn of(app: &Arc<App>) -> Self {
        Self { app: Arc::clone(app) }
    }

    /// Everything before the listener opens. `Err` is a controller that must not start.
    pub fn run(&self) -> Result<(), String> {
        let app = &self.app;
        if let Some(data_dir) = &app.paths.data_dir {
            let found = DataTree::new(data_dir).problem();
            if !found.is_empty() {
                return Err(format!("lama-caravan: will not start: {found}"));
            }
        }
        // Before the proxy starts: a proxy that read the records with their numbers and no ids would know no client.
        self.client_ids();
        Services::of(app).start_proxy();
        self.migrations();
        self.builtin_clients();
        self.machine_rows();
        self.background();
        MoveRunner::of(app).resume();
        Ok(())
    }

    /// One migration: what it did goes to the log, and so does why it was skipped.
    fn step(what: &str, work: impl FnOnce() -> Result<Option<Value>, AppError>, said: impl FnOnce(&Value) -> String) {
        match work() {
            Ok(Some(done)) => Log::line(&said(&done)),
            Ok(None) => {}
            Err(error) => Log::line(&format!("{what} skipped ({})", error.message)),
        }
    }

    /// `", ".join(names)`, "none" for no name.
    fn joined(names: Option<&Value>) -> String {
        let listed: Vec<String> =
            names.and_then(Value::as_array).into_iter().flatten().map(|name| Coerce::str_of(Some(name))).collect();
        if listed.is_empty() { "none".to_string() } else { listed.join(", ") }
    }

    fn count(value: Option<&Value>) -> usize {
        // absent-ok: no list is no rows.
        value.and_then(Value::as_array).map_or(0, Vec::len)
    }

    /// Every client known by its record's id, its number gone (the owner, 2026-11-07): once, and said in the log with what each
    /// number became, so that a row of the old journal can be read by it.
    fn client_ids(&self) {
        let app = &*self.app;
        Self::step(
            "entry: giving the clients their ids",
            || ClientIdsGiven::migrate(app),
            |done| {
                let rows = |key: &str, shown: &dyn Fn(&Value) -> String| -> String {
                    let listed: Vec<String> = done.get(key).and_then(Value::as_array).into_iter().flatten().map(shown).collect();
                    if listed.is_empty() { "none".to_string() } else { listed.join(", ") }
                };
                let given = rows("given", &|row| {
                    format!(
                        "{} :{} → {}",
                        Coerce::text(row.get("label")),
                        Coerce::str_of(row.get("port")),
                        Coerce::text(row.get("id"))
                    )
                });
                let retired =
                    rows("retired", &|row| format!("{} :{}", Coerce::text(row.get("label")), Coerce::str_of(row.get("port"))));
                format!(
                    "entry: every client is known by its id, its number gone: {given}; routes of the old kind retired: {retired}"
                )
            },
        );
    }

    fn closed_ports(done: &Value) -> String {
        let rows = done.as_array().into_iter().flatten().map(|row| {
            let pool = Coerce::text(row.get("pool"));
            format!(":{} ({})", Coerce::str_of(row.get("port")), if pool.is_empty() { "no pool" } else { &pool })
        });
        rows.collect::<Vec<String>>().join(", ")
    }

    fn moved_clients(done: &Value) -> String {
        let clients: Vec<String> = done
            .get("clients")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|client| {
                let had = Coerce::text(client.get("had"));
                format!("{} had {}", Coerce::str_of(client.get("name")), if had.is_empty() { "nothing" } else { &had })
            })
            .collect();
        let sets: Vec<String> = done
            .get("sets")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|set| {
                let pools: Vec<String> = set
                    .get("pools")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .map(|pool| Coerce::str_of(Some(pool)))
                    .collect();
                format!("{} [{}]", Coerce::str_of(set.get("name")), pools.join(", "))
            })
            .collect();
        format!(
            "entry: every client sees every model now, the sets are gone — {}; sets: {}",
            if clients.is_empty() { "no clients".to_string() } else { clients.join(", ") },
            if sets.is_empty() { "none".to_string() } else { sets.join("; ") },
        )
    }

    fn migrations(&self) {
        let app = &*self.app;
        Self::step(
            "entry: closing the pools' own ports",
            || PoolPortsRetired::migrate(app),
            |done| {
                format!(
                    "entry: pools' own ports closed, a client comes in through the entry with its key: {}",
                    Self::closed_ports(done)
                )
            },
        );
        match CloudData::of(app).migrate_context_auto() {
            Ok(0) => {}
            Ok(stamped) => {
                Log::line(&format!("cloud: contextAuto stamped on {stamped} blocks that relied on the provider's figure"))
            }
            Err(error) => Log::line(&format!("cloud: contextAuto migration skipped ({})", error.message)),
        }
        self.pool_migrations();
        Self::step(
            "cells: the models' default cells becoming presets",
            || DefaultCellsRetired::migrate(app),
            |done| {
                format!(
                    "cells: the models' default cells are presets of the launch builder now — gone, kept in defaultCellsRetired: {}; \
                     kept as the operator's cells: {}; pools that lost a cable: {}",
                    Self::joined(done.get("gone")),
                    Self::joined(done.get("kept")),
                    Self::joined(done.get("pools"))
                )
            },
        );
        Self::step(
            "cells: the cells' own listen address retired",
            || ListenAddressRetired::migrate(app),
            |done| {
                format!(
                    "cells: every cell listens on its machine's loopback now, behind its scout — HOST gone from: {}",
                    Self::joined(done.get("cells"))
                )
            },
        );
    }

    fn pool_migrations(&self) {
        let app = &*self.app;
        let pools = PoolDesk::of(app);
        Self::step(
            "cloud: rewriting the model blocks as pools",
            || pools.migrate(),
            |done| {
                format!(
                    "cloud: model blocks became pools: {}; dropped, unused: {}",
                    Self::joined(done.get("pools")),
                    Self::count(done.get("dropped"))
                )
            },
        );
        Self::step(
            "cloud: moving the steps' levels onto their models",
            || pools.migrate_rows(),
            |done| {
                format!(
                    "cloud: levels of {} step(s) moved onto {} model(s)",
                    Coerce::str_of(done.get("steps")),
                    Coerce::str_of(done.get("models"))
                )
            },
        );
        Self::step(
            "cloud: adding the rows' models to Routing",
            || pools.migrate_added(),
            |done| format!("cloud: {} model(s) the pools' rows name added to Routing", Coerce::str_of(done.get("models"))),
        );
        Self::step(
            "cloud: putting the providers on the main board",
            || ProviderDesk::of(app).migrate(),
            |done| format!("cloud: providers put on the main board: {}", Self::joined(done.get("providers"))),
        );
        Self::step(
            "entry: the move to clients without sets",
            || {
                let moved = ConsumerDesk::of(app).migrate()?;
                if moved.is_some() {
                    EntryMove::of(app).record(moved.as_ref());
                }
                Ok(moved)
            },
            Self::moved_clients,
        );
    }

    fn builtin_clients(&self) {
        let app = &*self.app;
        for (kind, ..) in BuiltinClient::KINDS {
            let open_entry = || EntrySettings::of(app).write(&json!({"port": EntryDoor::DEFAULT_PORT}));
            let what = format!("entry: making the built-in client {}", BuiltinClient::name(kind));
            Self::step(
                &what,
                || ConsumerDesk::of(app).ensure_builtin(Some(&open_entry), kind),
                |made| {
                    let entry = Coerce::str_of(made.get("entry"));
                    let refused = Coerce::text(made.get("entryRefused"));
                    let door = if Coerce::truthy(made.get("entry")) {
                        format!("; the entry opened on :{entry}")
                    } else if refused.is_empty() {
                        String::new()
                    } else {
                        format!("; the entry could not be opened ({refused})")
                    };
                    format!(
                        "entry: the built-in client {} made, id {}{door}",
                        Coerce::str_of(made.get("name")),
                        Coerce::str_of(made.get("routeId"))
                    )
                },
            );
        }
    }

    fn machine_rows(&self) {
        let app = &*self.app;
        let hosts = FleetReads::of(app).hosts();
        if let Err(error) = MachineRows::of(app).run(&hosts, &BTreeMap::new(), "at start") {
            Log::line(&format!("cloud: moving the pools' rows to the machines' models skipped ({})", error.message));
        }
    }

    /// The routes' fallback marks as the routes say them: written only when they moved.
    fn cloud_fallback(app: &App) {
        let config = ProxiesConfig::of(app);
        let mut payload = config.read_payload();
        let marks = |routes: &[Value]| -> Vec<(Value, Value)> {
            routes
                .iter()
                .filter(|route| route.is_object())
                .map(|route| {
                    let said = |key: &str| route.get(key).cloned().unwrap_or(Value::Null);
                    (said("cloudFallbackEligible"), said("cloudFallbackProviderId"))
                })
                .collect()
        };
        let Some(routes) = payload.get_mut("routes").and_then(Value::as_array_mut) else {
            return;
        };
        let before = marks(routes);
        RouterDsl::recompute_cloud_fallback(routes);
        if before != marks(routes)
            && let Err(error) = config.write_payload(payload)
        {
            Log::line(&format!("cloud: the fallback marks not saved ({})", error.message));
        }
    }

    fn thread(name: &str, work: impl FnOnce() + Send + 'static) {
        if let Err(error) = std::thread::Builder::new().name(name.to_string()).spawn(work) {
            Log::line(&format!("[{name}] not started: {error}"));
        }
    }

    fn background(&self) {
        let shared = |work: fn(&App)| {
            let app = Arc::clone(&self.app);
            move || work(&app)
        };
        Self::thread("models-folder", shared(|app| drop(ModelList::of(app).rows())));
        // The board's first read counts the clients' calls over the whole journal: seconds over a month of it. Here, not under the operator's first look after a new version.
        Self::thread("board-warm", shared(|app| drop(TopologyState::of(app).state(false))));
        Self::said_if_refused("monitor-sampler", MonitorSampler::start_thread(&self.app));
        Self::thread("cloud-fallback", shared(Self::cloud_fallback));
        let app = Arc::clone(&self.app);
        Ticking::in_background("queue-thresholds", Duration::from_secs(QueueThresholds::REFRESH_SECONDS), move || {
            QueueThresholds::of(&app).compute();
        });
        Ticking::in_background("memory-back", Duration::from_secs(60), os::Allocator::give_back);
        // What waits for the file (a scout's report) gets there when no heartbeat comes to take it: a machine gone quiet.
        let app = Arc::clone(&self.app);
        Ticking::in_background("admin-save-later", Duration::from_secs(60), move || {
            app.admin.save_if_waited(app.now(), FleetReads::REPORT_SAVE_WITHIN);
        });
        self.release_watch();
        Self::said_if_refused("gpu-driver-watch", GpuDriver::start_thread(&self.app));
        Self::said_if_refused("cell-schedule", CellSchedule::start_thread(&self.app));
    }

    /// `CARAVAN_ROOT` is a link to one release: when it comes to name another, this process ends once no request runs, or after
    /// `ReleasePatience` at the most (a machine's scout waits as long), and the container's restart starts the new one. A new version so
    /// needs no password.
    fn release_watch(&self) {
        let Some(link) = self.app.env.get("CARAVAN_ROOT").map(std::path::PathBuf::from).filter(|link| link.is_symlink()) else {
            return;
        };
        let Ok(running) = std::fs::canonicalize(&link) else {
            return;
        };
        let app = Arc::clone(&self.app);
        let mut waited_since = None;
        Ticking::in_background("release-watch", Duration::from_secs(5), move || {
            if std::fs::canonicalize(&link).is_ok_and(|now| now == running) {
                return;
            }
            let now = app.now();
            let since = *waited_since.get_or_insert(now);
            if Self::requests_running(&app) && now - since < ReleasePatience::SECONDS {
                return;
            }
            Log::line(&format!(
                "a new release is in place ({}): this process ends and the container's restart starts it",
                link.display()
            ));
            Self::before_exit(&app);
            std::process::exit(0);
        });
    }

    /// What waits for the files goes there before the process ends: the new one starts from them. The admin document is saved whether a
    /// report waits or not: one write a release.
    fn before_exit(app: &App) {
        app.save_admin();
        MonitorSampler::of(app).persist_now();
    }

    /// Whether a request still runs. The proxy a new file replaced counts by itself: it answers what it holds, and the state file is the new one's
    /// by then, and says nothing of those. Ending here would cut them: the container's restart takes every process in it.
    fn requests_running(app: &App) -> bool {
        if Services::of(app).proxy_finishing() {
            return true;
        }
        let state = ProxyStats::of(app).sample();
        let agents = state.get("agents").and_then(Value::as_object).into_iter().flatten();
        agents.into_iter().any(|(_, row)| Coerce::truthy(row.get("active")))
    }

    fn said_if_refused(name: &str, started: std::io::Result<()>) {
        if let Err(error) = started {
            Log::line(&format!("[{name}] not started: {error}"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_process_that_ends_leaves_what_waited_in_its_files() {
        let folder = crate::tests::TestFolder::new("startup-before-exit");
        let clock = crate::tests::HandClock::at(1_000);
        let app = crate::tests::TestApp::with_clock(&folder.path, &[], clock.clone());
        let reads = FleetReads::of(&app);
        let report = json!({"host": {"id": "box", "name": "Box"}});
        reads.record(&report, false).unwrap();
        clock.pass(10);
        reads.record(&report, false).unwrap();
        let seen = || {
            let doc: Value = serde_json::from_slice(&std::fs::read(app.admin.store().path()).unwrap()).unwrap();
            doc["topology"]["hosts"]["box"]["lastSeen"].clone()
        };
        assert_eq!((seen(), app.paths.monitor_history_file.exists()), (json!(1_000), false));
        Startup::before_exit(&app);
        assert_eq!((seen(), app.admin.waiting()), (json!(1_010), false), "the report that waited");
        assert!(app.paths.monitor_history_file.exists(), "and the monitor's history");
    }
}
