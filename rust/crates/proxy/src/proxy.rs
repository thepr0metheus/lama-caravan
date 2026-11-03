//! The proxy's parts together: what every request shares.

use crate::admission::Admission;
use crate::board::Board;
use crate::clock::SystemZone;
use crate::clock::{Clock, SystemClock};
use crate::config::ProxyConfig;
use crate::drain::Drain;
use crate::log::Log;
use crate::places::MachinePlaces;
use crate::pool_steps::{PoolQuestion, PoolSteps, RowChoice};
use crate::provider_access::{ProviderAccess, SharedAccess};
use crate::queue::ModelQueue;
use crate::recorder::Recorder;
use files::{AtomicFile, Journal, Settings, SettingsFiles, SettingsPaths};
use net::KeptConnections;
use rules::{EffortFit, MachineOutput, Pool};
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

/// The objects of one running proxy. Everything a request changes is a field of one of these: nothing lives in a global.
pub struct Proxy {
    /// Where it listens, where its files are.
    pub config: ProxyConfig,
    /// The settings files.
    pub settings: SettingsFiles,
    /// The running and the recent requests.
    pub board: Arc<Board>,
    /// The journal.
    pub recorder: Recorder,
    /// The queue of each model.
    pub queue: ModelQueue,
    /// How many places each model says it has.
    pub places: MachinePlaces,
    /// The pools' rows: their state, each account's windows and each output's health.
    pub pools: PoolSteps,
    /// What it takes to reach a provider.
    pub access: Arc<ProviderAccess>,
    /// The connections to providers kept open between requests.
    pub kept: Arc<KeptConnections>,
    /// The efforts each provider's models take, as their refusals listed them.
    pub efforts: EffortFit,
    /// The way out when a new version comes.
    pub drain: Arc<Drain>,
    /// The clocks.
    pub clock: Arc<dyn Clock>,
    started_at: f64,
    requests_seen: AtomicU64,
}

impl Proxy {
    /// How often the state file may be written; a request's changes wait this long for it at most.
    const STATE_TURN: Duration = Duration::from_millis(250);
    /// Turns between two writes when nothing changed: the file's `time` is its heartbeat, and the board tells a dead process
    /// by it.
    const BEAT_TURNS: u32 = 20;

    /// A proxy on the machine's clocks.
    pub fn new(config: ProxyConfig) -> Self {
        Self::with_clock(config, Arc::new(SystemClock::new()))
    }

    /// A proxy on the given clocks.
    pub fn with_clock(config: ProxyConfig, clock: Arc<dyn Clock>) -> Self {
        let board = Arc::new(Board::default());
        let access = Arc::new(ProviderAccess::new(config.secrets_file.clone(), config.cert_file.clone(), Arc::clone(&clock)));
        Self {
            settings: SettingsFiles::new(SettingsPaths {
                proxies: config.proxies_file.clone(),
                cloud: config.cloud_file.clone(),
                secrets: config.secrets_file.clone(),
                catalogue: config.catalogue_file.clone(),
                resets: config.resets_file.clone(),
            }),
            recorder: Recorder::new(
                Journal::new(config.journal_folder.clone(), config.journal_keep_days),
                Arc::clone(&board),
                Arc::clone(&clock),
            ),
            queue: ModelQueue::default(),
            places: MachinePlaces::new(Arc::clone(&clock)),
            pools: PoolSteps::new(Arc::clone(&clock), Arc::new(SystemZone), Box::new(SharedAccess(Arc::clone(&access)))),
            access,
            kept: Arc::new(KeptConnections::default()),
            efforts: EffortFit::default(),
            drain: Arc::new(Drain::of_program(config.program.clone()).kept_by(config.keeper)),
            started_at: clock.epoch(),
            requests_seen: AtomicU64::new(0),
            board,
            clock,
            config,
        }
    }

    /// A new request's id: the time and a number of this process.
    pub fn new_request_id(&self) -> String {
        let number = self.requests_seen.fetch_add(1, Ordering::Relaxed);
        format!("{}-{number}", (self.clock.epoch() * 1e9) as u128)
    }

    /// The row of `pool` that serves now, the journal told when the pool's choice has moved. `excluded` is what the request has tried.
    pub fn choose_row(
        &self,
        settings: &Settings,
        pool: &Pool,
        body: &[u8],
        path: &str,
        excluded: &BTreeSet<String>,
    ) -> RowChoice {
        let free = |output: &MachineOutput| Admission::has_room(self, output, &settings.policy);
        let (choice, event) = self.pools.resolve(&PoolQuestion { settings, pool, body, path, excluded, free: &free });
        if let Some(event) = event {
            self.recorder.event("pool_switch", "", "", None, event);
        }
        choice
    }

    /// Writes the state file now.
    pub fn write_state(&self) {
        let now = self.clock.epoch();
        let mut state = self.board.state_json(now, self.started_at, std::process::id(), &self.config.commit);
        if let Some(fields) = state.as_object_mut() {
            fields.insert("subscriptionUsage".to_string(), self.pools.usage.snapshot());
            fields.insert("outputHealth".to_string(), self.pools.health.snapshot(now));
            fields.insert("pools".to_string(), self.pools.snapshot());
            // The file the board reads the proxy's door from: where the ports listen.
            fields.insert("listenHost".to_string(), serde_json::json!(self.config.host));
            fields.insert("slotTotals".to_string(), self.places.totals());
        }
        if AtomicFile::write(&self.config.state_file, state.to_string().as_bytes()).is_err() {
            self.board.count_state_failure();
        }
    }

    /// Starts the thread that writes the state file. It is the file's one writer in this process.
    pub fn start_state_writer(self: &Arc<Self>) {
        let proxy = Arc::clone(self);
        let writer = std::thread::Builder::new().name("state-writer".into()).spawn(move || proxy.state_writer_loop());
        if let Err(error) = writer {
            Log::line(&format!("caravan-proxy: no thread for the state file: {error}"));
        }
    }

    /// Ends when a new version comes: the state file is the new one's from then, and a file has one writer. What this one still finishes
    /// goes to the journal.
    fn state_writer_loop(&self) {
        let mut turns_quiet = Self::BEAT_TURNS;
        while !self.drain.is_on() {
            if self.board.take_dirty() || turns_quiet >= Self::BEAT_TURNS {
                self.write_state();
                turns_quiet = 0;
            }
            turns_quiet += 1;
            std::thread::sleep(Self::STATE_TURN);
        }
    }
}
