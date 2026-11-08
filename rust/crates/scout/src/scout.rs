//! The scout of one machine, put together from its parts: who owns what, and nothing else. The scout knows its machine only: cards, cells, builds. Each part does one job and gets only the parts it needs; none of them reaches the others through the scout.

use crate::api::answering::Answering;
use crate::cells::autostart::Autostart;
use crate::cells::logs::CellLogs;
use crate::cells::migration::StateByCell;
use crate::cells::reconcile::Reconcile;
use crate::cells::suspect::CrashSuspect;
use crate::cells::watchdog::Watchdog;
use crate::cells::{Cells, CellsParts};
use crate::commands::{Commands, SystemCommands};
use crate::config::ScoutConfig;
use crate::driver::DriverFacts;
use crate::driver_packages::DriverPackages;
use crate::engines::ForeignEngines;
use crate::engines::kind::EngineKind;
use crate::engines::lmstudio::LmStudio;
use crate::engines::ollama::Ollama;
use crate::engines::procs::EngineProcs;
use crate::engines::servers::EngineServers;
use crate::entry::known::KnownCells;
use crate::entry::machine_entry::MachineEntry;
use crate::entry::machine_models::MachineModels;
use crate::errors::AppError;
use crate::heartbeat::Heartbeat;
use crate::http_client::HttpClient;
use crate::identity::HostIdentity;
use crate::machine::Machine;
use crate::models::SystemDisks;
use crate::models::files::SplitGguf;
use crate::own_release::{OwnUpdate, Running};
use crate::paths::ScoutPaths;
use crate::process::LogPatterns;
use crate::report::Report;
use crate::runtimes::BackgroundJob;
use crate::runtimes::builds::LlamaBuilds;
use crate::runtimes::vllm::VllmVenv;
use crate::saved_configs::SavedConfigs;
use crate::state::ScoutState;
use crate::telemetry::Telemetry;
use crate::ticking::Ticking;
use os::LocalTime;
use os::clock::{Clock, SystemClock};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

/// The parts.
pub struct Scout {
    /// The settings.
    pub config: Arc<ScoutConfig>,
    /// The machine.
    pub machine: Arc<Machine>,
    /// The cells.
    pub cells: Arc<Cells>,
    /// The `llama.cpp` builds.
    pub builds: Arc<LlamaBuilds>,
    /// The vLLM venv.
    pub vllm: VllmVenv,
    /// The saved launches.
    pub configs: SavedConfigs,
    /// What starts with the machine.
    pub autostart: Arc<Autostart>,
    /// A fresh build and crashing cells.
    pub suspect: Arc<CrashSuspect>,
    /// The machine second by second.
    pub telemetry: Arc<Telemetry>,
    /// Ollama and LM Studio.
    pub engines: Arc<ForeignEngines>,
    /// The driver's packages.
    pub driver_packages: DriverPackages,
    /// Their install.
    pub driver_install: BackgroundJob,
    /// What this scout says of its machine.
    pub report: Arc<Report>,
    /// Its word to the controller.
    pub heartbeat: Arc<Heartbeat>,
    /// The machine's entry.
    pub entry: MachineEntry,
    /// The door a new release comes in by.
    pub own_update: OwnUpdate,
    /// What it is answering now: what a release in place waits for.
    pub answering: Answering,
    /// The clocks.
    pub clock: Arc<dyn Clock>,
    watchdog: Arc<Watchdog>,
}

/// What the other parts rest on.
struct Foundations {
    clock: Arc<dyn Clock>,
    commands: Arc<dyn Commands>,
    paths: Arc<ScoutPaths>,
    http: Arc<HttpClient>,
    config: Arc<ScoutConfig>,
    state: Arc<ScoutState>,
    machine: Arc<Machine>,
    identity: Arc<HostIdentity>,
}

impl Foundations {
    fn new(config_path: &Path, state_path: &Path) -> Result<Self, AppError> {
        let clock: Arc<dyn Clock> = Arc::new(SystemClock::new());
        let commands: Arc<dyn Commands> = Arc::new(SystemCommands);
        let config = Arc::new(ScoutConfig::load(config_path)?);
        let state = Arc::new(ScoutState::load(state_path, clock.epoch() as i64));
        // Before anything reads `hostId`: the id that stays across renames.
        let identity = Arc::new(HostIdentity::new(Arc::clone(&config), Arc::clone(&state)));
        identity.settle();
        // Before anything reads a cell: what a scout of before kept by a cell's port, kept by the cell's name.
        // absent-ok: a system that cannot place the moment still names the copy by its seconds.
        let stamp = LocalTime::of(clock.epoch() as i64).map_or_else(|| (clock.epoch() as i64).to_string(), |at| at.compact());
        StateByCell::settle(&state, &CellLogs::of_state(&state, Arc::clone(&clock)), &stamp);
        let machine = Arc::new(Machine::new(Arc::clone(&config), Arc::clone(&commands), Arc::clone(&clock)));
        Ok(Self {
            clock,
            commands,
            paths: Arc::new(ScoutPaths::from_environment()),
            http: Arc::new(HttpClient::new()),
            config,
            state,
            machine,
            identity,
        })
    }

    fn failed(error: regex::Error) -> AppError {
        AppError::with_status(error.to_string(), 500)
    }

    fn cells(&self) -> Result<Arc<Cells>, AppError> {
        Ok(Arc::new(Cells::new(CellsParts {
            machine: Arc::clone(&self.machine),
            config: Arc::clone(&self.config),
            state: Arc::clone(&self.state),
            commands: Arc::clone(&self.commands),
            http: Arc::clone(&self.http),
            clock: Arc::clone(&self.clock),
            paths: Arc::clone(&self.paths),
            patterns: Arc::new(LogPatterns::new().map_err(Self::failed)?),
            splits: Arc::new(SplitGguf::new().map_err(Self::failed)?),
            disks: Arc::new(SystemDisks),
        })))
    }

    /// Ollama, LM Studio: model engines on this machine that are not its cells; their servers' output next to the state.
    fn engines(&self, cells: &Arc<Cells>) -> Arc<ForeignEngines> {
        let procs = EngineProcs::new(
            self.state.folder().join("engine-logs"),
            self.paths.proc_root.clone(),
            self.paths.home.clone(),
            Arc::clone(&self.commands),
            Arc::clone(&self.clock),
        );
        let servers = EngineServers::new(Arc::clone(&self.state), procs, self.paths.home.clone());
        let kinds: Vec<Arc<dyn EngineKind>> =
            vec![Arc::new(Ollama), Arc::new(LmStudio::new(self.paths.home.clone(), Arc::clone(&self.commands)))];
        Arc::new(ForeignEngines::new(Arc::clone(&self.machine), Arc::clone(cells), servers, kinds, Arc::clone(&self.clock)))
    }
}

impl Scout {
    /// Puts it together. What cannot be read of its settings ends the start with the words why.
    pub fn new(config_path: &Path, state_path: &Path) -> Result<Self, AppError> {
        let base = Foundations::new(config_path, state_path)?;
        let cells = base.cells()?;
        let engines = base.engines(&cells);
        let builds = Arc::new(LlamaBuilds::new(
            Arc::clone(&base.config),
            Arc::clone(&base.commands),
            Arc::clone(&base.paths),
            Arc::clone(&base.clock),
        ));
        let autostart = Arc::new(Autostart::new(Arc::clone(&base.state), Arc::clone(&cells), Arc::clone(&base.clock)));
        let suspect = Arc::new(CrashSuspect::new(Arc::clone(&base.state), Arc::clone(&builds), Arc::clone(&base.clock)));
        let telemetry =
            Arc::new(Telemetry::new(Arc::clone(&base.machine), Arc::clone(&base.clock), base.paths.proc_root.join("stat")));
        // What decides whether the NVIDIA card comes back after a reboot: the controller warns before the reboot, not after it.
        let driver = Arc::new(DriverFacts::new(Arc::clone(&base.machine), Arc::clone(&base.clock)).map_err(Foundations::failed)?);
        // The cells the controller keeps for this machine: its answer to a heartbeat says them, so that a stopped cell this scout has not started is a model of the machine too.
        let known = Arc::new(KnownCells::new(Arc::clone(&base.state)));
        let entry_models = Arc::new(MachineModels::new(
            Arc::clone(&cells),
            Arc::clone(&autostart),
            Arc::clone(&base.config),
            Arc::clone(&known),
        ));
        let report = Arc::new(Report {
            config: Arc::clone(&base.config),
            state: Arc::clone(&base.state),
            machine: Arc::clone(&base.machine),
            cells: Arc::clone(&cells),
            builds: Arc::clone(&builds),
            autostart: Arc::clone(&autostart),
            suspect: Arc::clone(&suspect),
            telemetry: Arc::clone(&telemetry),
            identity: Arc::clone(&base.identity),
            engines: Arc::clone(&engines),
            driver: Arc::clone(&driver),
            entry_models: Arc::clone(&entry_models),
            clock: Arc::clone(&base.clock),
        });
        Ok(Self {
            // The venv the controller's vLLM start line uses; the versions it had are kept next to the state, like the configs.
            vllm: VllmVenv::new(
                base.paths.home.join("vllm-venv"),
                base.state.folder().join("vllm-versions.json"),
                Arc::clone(&base.clock),
            ),
            configs: SavedConfigs::new(base.state.folder().join("llama-node-configs")),
            watchdog: Arc::new(Watchdog::new(Arc::clone(&cells), Arc::clone(&suspect), Arc::clone(&base.clock))),
            driver_packages: DriverPackages::new(driver, Arc::clone(&base.commands), Arc::clone(&base.clock))
                .map_err(Foundations::failed)?,
            driver_install: BackgroundJob::new("driver-install", "a driver install is already running", Arc::clone(&base.clock)),
            heartbeat: Arc::new(Heartbeat::new(
                Arc::clone(&base.config),
                Arc::clone(&base.state),
                Arc::clone(&report),
                Arc::clone(&cells),
                known,
                Arc::clone(&base.http),
                Arc::clone(&base.clock),
            )),
            entry: MachineEntry::new(entry_models, Arc::clone(&cells), Arc::clone(&base.http)),
            own_update: OwnUpdate::new(
                Arc::clone(&base.http),
                Arc::clone(&base.commands),
                Arc::clone(&base.config),
                Arc::clone(&base.clock),
            ),
            answering: Answering::default(),
            config: base.config,
            machine: base.machine,
            clock: base.clock,
            cells,
            builds,
            autostart,
            suspect,
            telemetry,
            engines,
            report,
        })
    }

    /// The release `commit` from the controller, in place of this one. Refused while a restart would cut work of its own; the requests it answers
    /// are waited for (own_release.rs).
    pub fn take_new_release(&self, commit: &str, sha256: &str) -> Result<serde_json::Value, AppError> {
        self.own_update.take(commit, sha256, &self.running_now())
    }

    /// What runs in this process now that its end would cut: its own work (the two shelves share one move at a time), and what it is answering.
    fn running_now(&self) -> Running {
        let jobs = [
            ("the llama.cpp build", self.builds.status()),
            ("the vLLM update", self.vllm.job_status()),
            ("the driver's install", self.driver_install.status()),
        ];
        Running {
            work: OwnUpdate::mid_work(&self.cells.views(), &jobs, self.cells.models.relocation.under_way()),
            connections: self.answering.connections.now(),
            entry: self.answering.entry.now(),
        }
    }

    /// The cells that start with the machine, and then each shelf trimmed to its setting: the cells have asked for their files by then, so that a trim does not take them. Off the main thread: a slow start does not keep the port closed.
    fn start_cells(&self) {
        self.autostart.start_all();
        self.cells.keeper.trim();
        self.cells.work_keeper.trim();
    }

    /// Its watches, each on a thread of its own.
    pub fn start_watches(self: &Arc<Self>) {
        const WATCH_REST: Duration = Duration::from_secs(2);
        let scout = Arc::clone(self);
        let started = std::thread::Builder::new().name("start-cells".to_string()).spawn(move || scout.start_cells());
        if let Err(error) = started {
            crate::log::Log::line(&format!("[autostart] not started: {error}"));
        }
        // A crashed cell comes back, as systemd brings the controller's.
        let watchdog = Arc::clone(&self.watchdog);
        Ticking::in_background("watchdog", WATCH_REST, move || watchdog.tick());
        // A cell it started and lost track of, the scout was killed while it loaded, is held again, so that the board can stop it.
        let mut reconcile = Reconcile::new(Arc::clone(&self.cells));
        Ticking::in_background("reconcile", Duration::from_secs(Reconcile::INTERVAL_SEC), move || {
            reconcile.tick();
        });
        // The machine second by second while a board watches it.
        let telemetry = Arc::clone(&self.telemetry);
        Ticking::in_background("telemetry", Duration::ZERO, move || {
            telemetry.sample();
            std::thread::sleep(Duration::from_secs_f64(telemetry.rest()));
        });
        // The engines next to the cells, rescanned on their own. After the first scan, when it is known what runs, the servers due at boot start.
        let engines = Arc::clone(&self.engines);
        let mut first = true;
        Ticking::in_background("engines", Duration::from_secs(ForeignEngines::PERIOD_SEC), move || {
            engines.refresh();
            if first {
                first = false;
                ForeignEngines::start_at_boot(&engines);
            }
        });
        // The cells' logs: thirty days, and what still lies in the cache's folder comes over. Each day: a machine runs for months.
        let cells = Arc::clone(&self.cells);
        Ticking::in_background("cell-logs", Duration::from_secs(86_400), move || cells.tidy_logs());
        // The library, while nobody has named it: a share may be mounted long after the scout started.
        let cells = Arc::clone(&self.cells);
        Ticking::in_background("library", Duration::from_secs(300), move || cells.keeper.find_library());
        let heartbeat = Arc::clone(&self.heartbeat);
        Ticking::in_background("heartbeat", Duration::ZERO, move || std::thread::sleep(heartbeat.turn()));
        // A release in place ends this process once its end cuts nothing, and the service starts the new one.
        let scout = Arc::clone(self);
        Ticking::in_background("release-end", OwnUpdate::TURN, move || {
            scout.own_update.look(
                || scout.running_now(),
                |words| {
                    crate::log::Log::line(words);
                    std::process::exit(0);
                },
            );
        });
    }
}
