//! The board's picture of the fleet.

pub mod assignments;
pub mod board_proxy;
pub mod nodes;
pub mod server;
pub mod windows;

use crate::app::App;
use crate::board_layout::{ClientOrder, ServerOrder};
use crate::cloud::api::CloudApi;
use crate::cloud::board_providers::ProviderDesk;
use crate::cloud::data::CloudData;
use crate::cloud::entry_move::EntryMove;
use crate::cloud::pools::PoolDesk;
use crate::cloud::schedules::ModelScheduleDesk;
use crate::common::cloud_file::AccountModelJobs;
use crate::domain::runner::Config;
use crate::fleet::engine_outputs::EngineOutputs;
use crate::fleet::machine_models::MachineOutputs;
use crate::fleet::reports::FleetReads;
use crate::models::model_list::ModelList;
use crate::models::notes::{ModelNotes, ModelRatings};
use crate::proxies::as_consumer::AsConsumer;
use crate::proxies::config::{ProxiesConfig, ProxyRevisions};
use crate::proxies::dsl::RouterDsl;
use crate::proxies::entry_settings::{ConsumerAddress, PortDoor};
use crate::proxies::stats::ProxyStats;
use crate::store::topology::Topology;
use assignments::Assignments;
use board_proxy::BoardProxies;
use nodes::TopologyNodes;
use rules::{AppError, Coerce, EntryModels, ModelKind, Pool};
use serde_json::{Map, Value, json};
use server::TopologyServer;
use windows::PoolWindows;

/// The routers' outputs, rewritten from what the board knows now.
pub struct RouterOutputs;

impl RouterOutputs {
    /// `proxy_config`'s routers' outputs rewritten, and written when they changed; whether they did.
    pub fn sync(
        app: &App,
        proxy_config: &mut Value,
        server_obj: &Value,
        hosts: &[Value],
        pools: &Value,
    ) -> Result<bool, AppError> {
        let config = ProxiesConfig::of(app);
        let mut routers = Coerce::list(proxy_config.get("routers"));
        let engines = EngineOutputs::of(app).outputs(hosts);
        let machines = MachineOutputs::outputs(hosts, server_obj);
        let pools: &[Value] = pools.as_array().map_or(&[], Vec::as_slice);
        if !ProxiesConfig::sync_router_outputs(&mut routers, pools, &engines, &machines)? {
            return Ok(false);
        }
        let mut fresh = config.read_payload();
        Coerce::put(&mut fresh, "routers", Value::Array(routers.clone()));
        config.write_payload(fresh)?;
        Coerce::put(proxy_config, "routers", Value::Array(routers));
        Ok(true)
    }

    /// The rewrite from the stores alone: the background's, off any board read.
    pub fn follow(app: &App) {
        let config = ProxiesConfig::of(app);
        let Ok(mut proxy_config) = config.load() else {
            return;
        };
        let server = TopologyServer::of(app).state();
        let hosts = FleetReads::of(app).hosts();
        if let Ok(pools) = PoolDesk::of(app).state() {
            // A rewrite that fails is tried again on the next report, and the next board.
            drop(Self::sync(app, &mut proxy_config, &server, &hosts, &pools));
        }
    }
}

/// What the operator wrote on the board.
struct BoardWords {
    assignments: Map<String, Value>,
    aliases: Map<String, Value>,
    layout: Map<String, Value>,
    ratings: Map<String, Value>,
    cell_notes: Map<String, Value>,
    cell_model_notes: Map<String, Value>,
}

/// What the board reads in one call.
pub struct TopologyState<'app> {
    app: &'app App,
}

impl<'app> TopologyState<'app> {
    /// The reading of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The window a pool states to its clients, and what its rows do together, on every pool.
    fn annotate_pools(&self, pools: &mut Value, proxy_config: &Value, data: &Value) {
        let windows = PoolWindows::of(self.app, proxy_config);
        for pool in pools.as_array_mut().into_iter().flatten().filter(|pool| pool.is_object()) {
            let window = windows.window(pool);
            Coerce::put(pool, "window", json!(window));
        }
        let jobs = AccountModelJobs::new(data);
        let reading = rules::CloudAccounts::read(data.get("accounts"));
        let outputs = rules::RouterOutputs::read(proxy_config.get("routers"));
        let said = rules::AccountModelJobs::read(Some(&jobs.stored()));
        for pool in pools.as_array_mut().into_iter().flatten().filter(|pool| pool.is_object()) {
            let kind = Pool::read_one(pool).and_then(|read| ModelKind::of_pool(&read, &reading, &outputs, &said));
            Coerce::put(pool, "kind", kind.map_or(Value::Null, |kind| kind.state()));
        }
    }

    fn entry_reading(models: Option<&EntryModels>) -> (Value, Value, Value) {
        match models {
            Some(models) => {
                (json!(models.names(&rules::ClientDeny::default())), models.choices(), Value::Array(models.catalog()))
            }
            None => (Value::Null, Value::Null, Value::Null),
        }
    }

    /// The whole picture.
    pub fn state(&self, refresh_hosts: bool) -> Result<Value, AppError> {
        if refresh_hosts && let Some(app) = self.app.shared() {
            FleetReads::kick_poll(&app);
        }
        let config = self.app.parse_config()?;
        let proxies_config = ProxiesConfig::of(self.app);
        let reading = proxies_config.read_payload();
        let mut revisions = ProxyRevisions::of(&reading);
        let mut proxy_config = proxies_config.load_from(&reading)?;
        let policy = proxy_config
            .get("policy")
            .filter(|said| Coerce::truthy(Some(*said)))
            .cloned()
            .unwrap_or_else(|| RouterDsl::policy(None));
        let door = PortDoor::open(self.app);
        let address = ConsumerAddress::new(&proxy_config, &self.app.paths.topology_server_ip, door);
        let board = BoardProxies::of(self.app);
        let mut proxies = board.rows(&proxy_config, &address);
        let server_obj = TopologyServer::of(self.app).state();
        let reads = FleetReads::of(self.app);
        let hosts = reads.hosts();
        if let Ok(pools) = PoolDesk::of(self.app).state()
            && let Ok(true) = RouterOutputs::sync(self.app, &mut proxy_config, &server_obj, &hosts, &pools)
        {
            revisions = ProxyRevisions::of(&proxies_config.read_payload());
        }
        let live = CloudData::of(self.app).live_models(proxy_config.get("routers"));
        board.annotate_consumers(&mut proxies, Some(&live));
        let cloud_part = self.cloud_part(&proxy_config, &live)?;
        board.annotate_tallies(&mut proxies);
        board.annotate_route_windows(&mut proxies, &proxy_config, &server_obj);
        let words = self.board_words(&config);
        let mut out = json!({
            "server": server_obj,
            "hostSuspects": TopologyNodes::host_suspects(&hosts),
            "nodes": TopologyNodes::of(self.app).rows(&server_obj, &hosts),
            "proxies": proxies,
            "cellPortRange": {"from": self.app.paths.cell_ports.base, "to": self.app.paths.cell_ports.upper, "proxyBase": self.app.paths.proxy_ports.base},
            "modelsStamp": ModelList::of(self.app).current().1,
            "routers": BoardProxies::slot_groups(proxy_config.get("routers")),
            "proxyRevisions": revisions,
            "proxyPolicy": policy,
            "effectiveSlots": policy.get("maxSlots").filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int).unwrap_or(1),
            "hosts": hosts,
            "clients": reads.clients(),
            "assignments": Assignments::at_current_address(&words.assignments, &address, &self.app.paths.topology_server_ip),
            "entry": address.entry(),
            "clientProbes": AsConsumer::probes(),
            "portsReachable": door,
            "embeddingsCalledAt": ProxyStats::of(self.app).embeddings_last_called(7),
            "cellNotes": words.cell_notes,
            "modelRatings": words.ratings,
            "cellModelNotes": words.cell_model_notes,
            "clientAliases": words.aliases,
            "layout": words.layout,
        });
        Coerce::extend(&mut out, &cloud_part);
        Coerce::put(&mut out, "time", json!(self.app.now_whole()));
        Ok(out)
    }

    /// The accounts, the pools and what a client may be offered of them, for the board's answer.
    fn cloud_part(&self, proxy_config: &Value, live: &EntryModels) -> Result<Value, AppError> {
        let cloud = CloudData::of(self.app);
        let desk = PoolDesk::of(self.app);
        let mut cloud_accounts = cloud.accounts_state();
        let mut pools = desk.state()?;
        let entry_move = EntryMove::of(self.app).state(live);
        let data = cloud.load();
        self.annotate_pools(&mut pools, proxy_config, &data);
        let health = CloudApi::of(self.app).annotate_topology(
            cloud_accounts.as_array_mut().map_or(&mut [], Vec::as_mut_slice),
            pools.as_array_mut().map_or(&mut [], Vec::as_mut_slice),
        );
        let (entry_names, deny_choices, live_catalog) = Self::entry_reading(Some(live));
        Ok(json!({
            "cloudAccounts": cloud_accounts,
            "pools": pools,
            "entryModels": entry_names,
            "denyChoices": deny_choices,
            "liveCatalog": live_catalog,
            "entryMove": entry_move,
            "poolsRuntime": desk.runtime(),
            // The reader block's row (`top.reader`, static/js/reader-block.js), from the reading the rest of this answer reads.
            "reader": PoolDesk::reader(live),
            "modelLevels": desk.model_levels(),
            "addedModels": desk.added_models(),
            "modelJobs": desk.model_jobs(),
            "modelSchedules": ModelScheduleDesk::of(self.app).state(),
            "boardProviders": ProviderDesk::of(self.app).state(),
            "cloudApiHealth": health,
            "cloudProviderPresets": self.app.presets.public(),
        }))
    }

    /// What the operator wrote on the board: who is bound to what, the names, the notes, the order of the cards.
    fn board_words(&self, config: &Config) -> BoardWords {
        let (slots, assignments, aliases, layout_doc, ratings, mut notes) = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let slots = topology.slots().clone();
            let assignments = topology.assignments().clone();
            let aliases = topology.aliases().clone();
            let layout = topology.raw().get("layout").cloned();
            let ratings = ModelRatings::new(topology.model_ratings()).all();
            let notes = topology.model_notes().clone();
            (slots, assignments, aliases, layout, ratings, notes)
        });
        let cell_notes: Map<String, Value> = slots
            .iter()
            .filter(|(_, slot)| slot.is_object() && !Coerce::stripped(slot.get("note")).is_empty())
            .map(|(key, slot)| (key.clone(), json!(Coerce::text(slot.get("note")))))
            .collect();
        let cell_models: Vec<(String, String)> = slots
            .iter()
            .filter(|(_, slot)| slot.is_object())
            .map(|(key, slot)| (key.clone(), crate::fleet::machine_cells::SlotModel::path(self.app, slot)))
            .collect();
        let models_dir = self.app.models_dir_of(config);
        let cell_model_notes = ModelNotes::new(&mut notes, 0).for_cells(&cell_models, &models_dir.to_string_lossy());
        let mut layout = ServerOrder::layout_of(layout_doc.as_ref());
        for (key, said) in ClientOrder::layout_of(layout_doc.as_ref()) {
            layout.insert(key, said);
        }
        BoardWords { assignments, aliases, layout, ratings, cell_notes, cell_model_notes }
    }
}
