//! The controller's parts, made once and handed to every route. A subsystem is a view over this object: `Pools::of(&app)`; what it remembers between calls stands here under its own name.

use crate::benchmarks::quality::BenchMemory;
use crate::cloud::catalog::{CatalogMemory, ChatModels};
use crate::cloud::misses::ClientTallies;
use crate::cloud::oauth::LoginMemory;
use crate::cloud::presets::CloudPresets;
use crate::common::checkout::CheckoutCommit;
use crate::config::text::ConfigText;
use crate::domain::runner::{Config, RunnerDefaults, RunnerRegistry};
use crate::fleet::gpu_driver::DriverMemory;
use crate::fleet::host_telemetry::TelemetryMemory;
use crate::fleet::machine_scout::MachineScoutMemory;
use crate::fleet::remote_cells::RemoteMemory;
use crate::fleet::scout_follow::ScoutFollow;
use crate::fleet::scout_poll::{Rerun, ScoutPoller};
use crate::models::checkpoints::CheckpointConfigs;
use crate::models::downloads::DownloadMemory;
use crate::models::hf::HubMemory;
use crate::models::memory::{HeaderMemory, LibraryMeta};
use crate::models::model_list::ModelListMemory;
use crate::models::moves::runner::MoveMemory;
use crate::models::stores::StoreMemory;
use crate::models::verify::VerifyMemory;
use crate::models::watch::{ModelWatch, WatchMemory};
use crate::monitoring::incidents::IncidentMemory;
use crate::monitoring::sampler::MonitorMemory;
use crate::paths::{AdminPaths, Environment};
use crate::proxies::config::ProxyLock;
use crate::proxies::latency::LatencyMemory;
use crate::proxies::queue_thresholds::ThresholdMemory;
use crate::proxies::service::ServiceChildren;
use crate::proxies::stats::StatsMemory;
use crate::proxies::token_history::TokenHistoryMemory;
use crate::status::UpdateJobMemory;
use crate::store::admin::AdminStore;
use crate::store::auth::{AuthStore, SessionInfo};
use crate::store::base::Unreadable;
use crate::store::cached::CachedJsonStore;
use crate::store::proxies::ProxyStore;
use crate::topology::server::SlotSizeMemory;
use crate::web::Exchange;
use os::clock::Clock;
use plumbing::{Commands, HttpClient};
use rules::AppError;
use std::path::PathBuf;
use std::sync::{Arc, OnceLock, Weak};

/// What a program needs from the world, as parameters: a test says each.
pub struct Outside {
    /// The clock.
    pub clock: Arc<dyn Clock>,
    /// The machine's tools.
    pub commands: Arc<dyn Commands>,
    /// The environment.
    pub env: Environment,
}

/// The controller.
pub struct App {
    /// Its paths and ports.
    pub paths: AdminPaths,
    /// The environment it started in.
    pub env: Environment,
    /// The clock.
    pub clock: Arc<dyn Clock>,
    /// The machine's tools.
    pub commands: Arc<dyn Commands>,
    /// The asking side of HTTP.
    pub http: HttpClient,
    /// The runners.
    pub runners: RunnerRegistry,
    /// `admin.json`.
    pub admin: AdminStore,
    /// `agent-proxies.json`.
    pub proxies: ProxyStore,
    /// `cloud-providers.json`.
    pub cloud_file: CachedJsonStore,
    /// `provider-secrets.json`.
    pub secrets_file: CachedJsonStore,
    /// The accounts.
    pub auth: AuthStore,
    /// How each model store looked.
    pub store_memory: StoreMemory,
    /// What the headers of the models folder said.
    pub header_memory: HeaderMemory,
    /// What the headers of the libraries' files said.
    pub library_meta: LibraryMeta,
    /// What each checkpoint's config.json said.
    pub checkpoint_configs: CheckpointConfigs,
    /// The last walk of the models.
    pub model_list: ModelListMemory,
    /// The watcher's report and pass.
    pub watch_memory: WatchMemory,
    /// What the hub said.
    pub hub_memory: HubMemory,
    /// The downloads.
    pub downloads: DownloadMemory,
    /// The verify jobs.
    pub verify_memory: VerifyMemory,
    /// The model moves.
    pub moves: MoveMemory,
    /// What a check of a list and its write stand under.
    pub proxy_lock: ProxyLock,
    /// The providers the board can add an account of.
    pub presets: CloudPresets,
    /// The catalogue's file and its refreshes.
    pub catalog: CatalogMemory,
    /// Which of a provider's models chat.
    pub chat_models: ChatModels,
    /// The sign-ins in progress.
    pub logins: LoginMemory,
    /// What the proxy's journal said, day by day.
    pub stats: StatsMemory,
    /// The timings the journal holds.
    pub latency: LatencyMemory,
    /// The token-rate history.
    pub token_history: TokenHistoryMemory,
    /// The last queue thresholds.
    pub thresholds: ThresholdMemory,
    /// What each client asked.
    pub tallies: ClientTallies,
    /// The children this controller keeps.
    pub services: ServiceChildren,
    /// The pass that follows the fleet's cells onto the routers' outputs.
    pub cells_follow: Rerun,
    /// The background reads of the scouts.
    pub scout_poller: ScoutPoller,
    /// The machines' scouts as they follow this controller's release.
    pub scout_follow: ScoutFollow,
    /// The answers of the scout of the controller's machine.
    pub machine_scout: MachineScoutMemory,
    /// What the cells said of themselves.
    pub remote: RemoteMemory,
    /// The machines' load, read from their scouts.
    pub telemetry: TelemetryMemory,
    /// The driver's last look and its watcher.
    pub driver: DriverMemory,
    /// The size of each slot's model as last read.
    pub slot_sizes: SlotSizeMemory,
    /// The monitor's samples.
    pub monitor: MonitorMemory,
    /// The incident log's lock and its trim.
    pub incidents: IncidentMemory,
    /// The build job on the controller's machine.
    pub update_job: UpdateJobMemory,
    /// The quality tables.
    pub bench: BenchMemory,
    commit: OnceLock<String>,
    own: Weak<App>,
}

impl App {
    /// The controller over these paths.
    pub fn new(paths: AdminPaths, outside: Outside) -> Result<Arc<Self>, regex::Error> {
        let Outside { clock, commands, env } = outside;
        let defaults = RunnerDefaults {
            models_dir: paths.default_models_dir.to_string_lossy().into_owned(),
            home: env.home().to_string_lossy().into_owned(),
        };
        let runners = RunnerRegistry::new(&defaults)?;
        let stamp = Unreadable::stamp(clock.epoch() as i64);
        let admin = AdminStore::open(paths.admin_state_file.clone(), paths.monitor_retention_default, &runners, &stamp);
        let hub_memory = HubMemory::new()?;
        let chat_models = ChatModels::new()?;
        let bench = BenchMemory::new()?;
        let stats = StatsMemory::new()?;
        Ok(Arc::new_cyclic(|own| Self {
            auth: AuthStore::open(&paths.auth_db, &stamp),
            proxies: ProxyStore::new(paths.agent_proxy_config_file.clone()),
            cloud_file: CachedJsonStore::new(paths.cloud_providers_file.clone()),
            secrets_file: CachedJsonStore::new(paths.provider_secrets_file.clone()),
            http: HttpClient::new(),
            commit: OnceLock::new(),
            store_memory: StoreMemory::default(),
            header_memory: HeaderMemory::new(paths.gguf_headers_file.clone()),
            library_meta: LibraryMeta::new(paths.library_meta_file.clone()),
            checkpoint_configs: CheckpointConfigs::default(),
            model_list: ModelListMemory::default(),
            watch_memory: WatchMemory::default(),
            hub_memory,
            downloads: DownloadMemory::default(),
            verify_memory: VerifyMemory::default(),
            moves: MoveMemory::default(),
            proxy_lock: ProxyLock::default(),
            presets: CloudPresets::new(),
            catalog: CatalogMemory::default(),
            chat_models,
            logins: LoginMemory::default(),
            stats,
            latency: LatencyMemory::default(),
            token_history: TokenHistoryMemory::default(),
            thresholds: ThresholdMemory::default(),
            tallies: ClientTallies::default(),
            services: ServiceChildren::new(clock.epoch()),
            cells_follow: Rerun::default(),
            scout_poller: ScoutPoller::default(),
            scout_follow: ScoutFollow::default(),
            machine_scout: MachineScoutMemory::default(),
            remote: RemoteMemory::default(),
            telemetry: TelemetryMemory::default(),
            driver: DriverMemory::default(),
            slot_sizes: SlotSizeMemory::default(),
            monitor: MonitorMemory::default(),
            incidents: IncidentMemory::default(),
            update_job: UpdateJobMemory::default(),
            bench,
            own: own.clone(),
            admin,
            runners,
            paths,
            env,
            clock,
            commands,
        }))
    }

    /// This controller for a thread of its own; none only while the program ends.
    pub fn shared(&self) -> Option<Arc<Self>> {
        self.own.upgrade()
    }

    /// The controller's own config block; empty when its file is not there: it may not be, on a controller that runs no server of its own.
    pub fn parse_config(&self) -> Result<Config, AppError> {
        match std::fs::read_to_string(&self.paths.start_script) {
            Ok(text) => ConfigText::parse(&text, "text", &self.paths.default_models_dir.to_string_lossy()),
            Err(_) => Ok(Config::new()),
        }
    }

    /// The models folder a config says.
    pub fn models_dir_of(&self, config: &Config) -> PathBuf {
        let said = config.get("LLAMA_MODELS_DIR").filter(|said| rules::Coerce::truthy(Some(*said)));
        said.map_or_else(|| self.paths.default_models_dir.clone(), |said| self.env.expand(&rules::Coerce::text(Some(said))))
    }

    /// The models folder of the controller's own config: what a config that does not read leaves is the default.
    pub fn models_dir(&self) -> PathBuf {
        self.parse_config().map_or_else(|_| self.paths.default_models_dir.clone(), |config| self.models_dir_of(&config))
    }

    /// Epoch seconds.
    pub fn now(&self) -> f64 {
        self.clock.epoch()
    }

    /// Epoch seconds, whole.
    pub fn now_whole(&self) -> i64 {
        self.clock.epoch().trunc() as i64
    }

    /// The same, as an HTTP date takes it.
    pub fn now_seconds(&self) -> u64 {
        self.clock.epoch().max(0.0) as u64
    }

    /// `%Y%m%d-%H%M%S` of now.
    pub fn stamp(&self) -> String {
        Unreadable::stamp(self.now_whole())
    }

    /// The hub's address: the real one, unless the environment names one that stands in for it. A test's and a stand's way to it: there is no other reason to set it.
    pub fn hub(&self) -> &str {
        self.env.get("CARAVAN_HUB_URL").unwrap_or("https://huggingface.co").trim_end_matches('/')
    }

    /// Who the request's cookie says it is.
    pub fn session_of(&self, h: &Exchange<'_>) -> Result<Option<SessionInfo>, AppError> {
        self.auth.validate_session(&h.cookie(AuthStore::SESSION_COOKIE), self.now())
    }

    /// The commit this controller runs, in its short form; "" when nothing says it. Read once: it cannot change under a running program.
    pub fn running_commit(&self) -> String {
        self.commit
            .get_or_init(|| {
                CheckoutCommit::of(
                    &self.paths.project_root,
                    true,
                    self.env.get(CheckoutCommit::BAKED_ENV),
                    self.commands.as_ref(),
                )
                .commit
            })
            .clone()
    }

    /// The board was opened: what wakes the day's first check of the models.
    pub fn board_opened(&self) {
        // Its answer is for the routes that ask; a page is not held up by it.
        drop(ModelWatch::of(self).board_opened());
    }

    /// Starts the cell a finished move was bringing a model home for: `{hostId, port}`.
    pub fn start_cell(&self, start: &serde_json::Value) -> Result<(), AppError> {
        let mut asked = start.clone();
        rules::Coerce::put(&mut asked, "action", serde_json::json!("start"));
        crate::fleet::cell_ops::CellOps::of(self).action(&asked).map(drop)
    }

    /// The admin document on disk. A save that fails is said: the change holds in memory, and the next save takes it.
    pub fn save_admin(&self) {
        if let Err(error) = self.admin.save() {
            plumbing::Log::line(&format!("admin state not saved: {error}"));
        }
    }

    /// The ports the fleet's cells hold: only a running cell holds one, the one its scout leased (Papyrus `caravan-scout-port-lease`).
    pub fn used_cell_ports(&self) -> std::collections::BTreeSet<i64> {
        crate::fleet::server_cells::ServerCells::of(self).held_ports()
    }

    /// A client's name, refused when another has it.
    pub fn clean_client_name(&self, name: &str, routes: &[serde_json::Value], own_id: Option<&str>) -> Result<String, AppError> {
        crate::cloud::consumers::ConsumerDesk::clean_name(Some(&serde_json::json!(name)), routes, own_id)
    }

    /// This machine's name.
    pub fn hostname(&self) -> String {
        os::Host::name()
    }

    /// The Hugging Face token; "" when none is saved.
    pub fn hf_token(&self) -> String {
        self.admin.read(|doc| rules::Coerce::text(doc.get("hfToken")))
    }
}
