//! The machine a scout runs on, as its OS tells it: the cards and the processes on them, CPU and memory, who the firewall lets in, what listens, and
//! which address faces the controller.

mod gpus;
mod listeners;
mod resources;
mod ufw;

pub use gpus::GpuProbe;
pub use listeners::Listeners;
pub use resources::{Resources, Rounded};
pub use ufw::UfwRules;

use crate::commands::Commands;
use crate::config::ScoutConfig;
use os::clock::Clock;
use rules::{BaseUrl, Coerce};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::net::{IpAddr, UdpSocket};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

/// An answer kept for a while, and when it was asked: 0 for never.
#[derive(Debug, Default)]
struct Kept<T> {
    answer: T,
    at: f64,
}

impl<T: Clone> Kept<T> {
    fn fresh(&self, now: f64, lasts: f64) -> Option<T> {
        (self.at != 0.0 && now - self.at < lasts).then(|| self.answer.clone())
    }
}

/// What the probes last answered.
#[derive(Debug, Default)]
struct Answers {
    cards: Kept<(Vec<Value>, String)>,
    apps: Kept<Vec<Value>>,
    listening: Kept<Option<BTreeSet<i64>>>,
    firewall: BTreeMap<String, Kept<Value>>,
}

/// This machine's probes, with the caches that keep a polling board from spawning `nvidia-smi` and `sudo` on every request. A probe that cannot ask
/// answers with nothing, and the caches keep an empty answer too, so a host without cards does not run `nvidia-smi` and `lspci` on every request either.
pub struct Machine {
    config: Arc<ScoutConfig>,
    commands: Arc<dyn Commands>,
    clock: Arc<dyn Clock>,
    answers: Mutex<Answers>,
    /// Whether this is Linux: `lspci` and `/proc` are asked only there.
    linux: bool,
}

impl Machine {
    const CARDS_LAST: f64 = 10.0;
    const APPS_LAST: f64 = 5.0;
    const FIREWALL_LASTS: f64 = 30.0;
    const LISTENING_LASTS: f64 = 2.0;
    const SHORT: Duration = Duration::from_secs(4);
    const SMI_TIMEOUT: Duration = Duration::from_secs(5);
    const TOP_LINES: usize = 7;

    /// The machine of this config, asked through `commands`.
    pub fn new(config: Arc<ScoutConfig>, commands: Arc<dyn Commands>, clock: Arc<dyn Clock>) -> Self {
        Self::on_system(config, commands, clock, cfg!(target_os = "linux"))
    }

    /// The same, saying which system it is: the tables hold what a Linux says, also where they are run on another.
    pub fn on_system(config: Arc<ScoutConfig>, commands: Arc<dyn Commands>, clock: Arc<dyn Clock>, linux: bool) -> Self {
        Self { config, commands, clock, answers: Mutex::new(Answers::default()), linux }
    }

    fn answers(&self) -> MutexGuard<'_, Answers> {
        self.answers.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn cards(&self) -> (Vec<Value>, String) {
        let now = self.clock.epoch();
        if let Some(kept) = self.answers().cards.fresh(now, Self::CARDS_LAST) {
            return kept;
        }
        let read = GpuProbe::reading(self.commands.as_ref(), self.linux);
        self.answers().cards = Kept { answer: read.clone(), at: now };
        read
    }

    /// The cards, refreshed at most every 10 s, so polling `/api/state` does not spawn `nvidia-smi` on every request.
    pub fn gpus(&self) -> Vec<Value> {
        self.cards().0
    }

    /// Why `nvidia-smi` named no card at the last look, in its own words; "" when it named them, or is not installed here.
    pub fn gpu_error(&self) -> String {
        self.cards().1
    }

    /// Per-process memory on the cards, refreshed at most every 5 s.
    pub fn compute_apps(&self) -> Vec<Value> {
        let now = self.clock.epoch();
        if let Some(kept) = self.answers().apps.fresh(now, Self::APPS_LAST) {
            return kept;
        }
        let apps = GpuProbe::apps(self.commands.as_ref());
        self.answers().apps = Kept { answer: apps.clone(), at: now };
        apps
    }

    /// The TCP ports something listens on here, asked at most every 2 s for all the cells at once; `None` when the OS will not say.
    pub fn listening_ports(&self) -> Option<BTreeSet<i64>> {
        let now = self.clock.epoch();
        if let Some(kept) = self.answers().listening.fresh(now, Self::LISTENING_LASTS) {
            return kept;
        }
        let ports = Listeners::ports(self.commands.as_ref());
        self.answers().listening = Kept { answer: ports.clone(), at: now };
        ports
    }

    /// Who `ufw` lets reach `port`, kept 30 s per port: a single slot for all of them cost a host of three cells 232 `sudo` forks a minute.
    pub fn firewall(&self, port: &Value) -> Value {
        let now = self.clock.epoch();
        let key = port.to_string();
        if let Some(kept) = self.answers().firewall.get(&key).and_then(|kept| kept.fresh(now, Self::FIREWALL_LASTS)) {
            return kept;
        }
        let access = UfwRules::access(&self.run_text(&["sudo", "-n", "ufw", "status"]), port);
        self.answers().firewall.insert(key, Kept { answer: access.clone(), at: now });
        access
    }

    /// Standard output of a tool that succeeded; "" on any failure.
    pub fn run_text(&self, argv: &[&str]) -> String {
        self.commands.run(argv, Self::SHORT).ok().filter(|ran| ran.ok()).map_or_else(String::new, |ran| ran.stdout)
    }

    /// The address others can reach this machine at: the interface the kernel picks towards the controller, no packet sent; towards the default route
    /// when the controller is on this very machine, for 127.0.0.1 reaches nobody else. A stand's config says it: a real machine's says nothing.
    pub fn address(&self) -> String {
        let stand = self.config.text("standAddress");
        if !stand.is_empty() {
            return stand;
        }
        let controller = BaseUrl::read(&self.config.text("controllerUrl")).filter(|place| !Self::is_loopback(&place.host));
        let target = controller.map_or_else(|| ("8.8.8.8".to_string(), 80), |place| (place.host, place.port));
        let asked = UdpSocket::bind(("0.0.0.0", 0)).and_then(|socket| {
            socket.connect((target.0.as_str(), target.1))?;
            socket.local_addr()
        });
        asked.map_or_else(|_| "127.0.0.1".to_string(), |address| address.ip().to_string())
    }

    /// localhost, 127.0.0.0/8 or `::1`: a controller on this very machine.
    pub fn is_loopback(host: &str) -> bool {
        host.eq_ignore_ascii_case("localhost") || host.parse::<IpAddr>().is_ok_and(|address| address.is_loopback())
    }

    /// What this machine is called where one word is wanted.
    pub fn name(&self) -> String {
        [self.config.text("hostId"), self.config.text("displayName")]
            .into_iter()
            .find(|name| !name.is_empty())
            .unwrap_or_else(|| "remote".to_string())
    }

    /// Each port listening here, for the controller's port picker.
    pub fn listeners(&self) -> Value {
        Listeners::listing(self.commands.as_ref())
    }

    /// `nvidia-smi` as its own table, for the controller's monitor panel.
    pub fn nvidia_smi(&self) -> Value {
        let (ok, output) = match self.commands.run(&["nvidia-smi"], Self::SMI_TIMEOUT) {
            Ok(ran) if ran.ok() => (true, ran.stdout.trim().to_string()),
            Ok(ran) => (false, if ran.stderr.is_empty() { ran.stdout.trim().to_string() } else { ran.stderr.trim().to_string() }),
            Err(crate::commands::NoAnswer::NotFound) => (false, "nvidia-smi not found".to_string()),
            Err(why) => (false, format!("{why:?}")),
        };
        json!({"kind": "nvidia-smi", "ok": ok, "output": output, "source": self.name(), "time": self.clock.epoch() as i64})
    }

    /// The busiest processes by CPU. `processes` is `None` when `ps` will not say: not "no processes".
    pub fn top_processes(&self) -> Value {
        let mut rows = None;
        // Linux first; macOS's `ps` has no `--sort`.
        for sort in ["--sort=-%cpu", "-r"] {
            let asked = self.commands.run(&["ps", "-eo", "pid,comm,user,%cpu,%mem,rss", sort], Duration::from_secs(3));
            if let Some(ran) = asked.ok().filter(|ran| ran.ok()) {
                rows = Some(ran.stdout.lines().skip(1).take(Self::TOP_LINES).filter_map(Self::top_row).collect::<Vec<_>>());
                break;
            }
        }
        json!({"ok": rows.is_some(), "processes": rows, "time": self.clock.epoch() as i64})
    }

    fn top_row(line: &str) -> Option<Value> {
        let mut parts = line.split_whitespace();
        let (pid, name, user, cpu, memory, rss) =
            (parts.next()?, parts.next()?, parts.next()?, parts.next()?, parts.next()?, parts.next()?);
        Some(json!({
            "pid": pid.parse::<i64>().ok()?, "name": name, "user": user, "cpuPct": cpu.parse::<f64>().ok()?, "memPct": memory.parse::<f64>().ok()?,
            "rssMiB": Rounded::to(rss.parse::<i64>().ok()? as f64 / 1024.0, 1),
        }))
    }

    /// One `btop` frame as the terminal drew it, and `top`'s table beside it: asked on a hover, not on a schedule.
    pub fn btop_snapshot(&self) -> Value {
        const DRAW: &str = "stty cols 120 rows 40; TERM=xterm-256color btop -p 0 -u 1000 --utf-force";
        let asked =
            self.commands.run(&["timeout", "-k", "1s", "2s", "script", "-q", "-c", DRAW, "/dev/null"], Duration::from_secs(6));
        let frame = asked.map_or_else(|_| String::new(), |ran| format!("{}{}", ran.stdout, ran.stderr));
        let asked = self.commands.run(&["bash", "-lc", "COLUMNS=150 top -b -n 1 -w 150 | head -45"], Self::SMI_TIMEOUT);
        let top = asked.map_or_else(
            |_| String::new(),
            |ran| if ran.ok() || ran.stderr.is_empty() { ran.stdout.trim().to_string() } else { ran.stderr.trim().to_string() },
        );
        json!({"kind": "btop", "ok": !frame.is_empty() || !top.is_empty(), "frame": frame, "top": top, "source": self.name(), "time": self.clock.epoch() as i64})
    }

    /// Every process on this machine: pid to `{ppid, rssKb, name}`, the name being the executable's own. `None` when `ps` will not say. On macOS the name is
    /// the whole path, spaces and all: so it is the last column.
    pub fn processes(&self) -> Option<BTreeMap<i64, Value>> {
        let ran =
            self.commands.run(&["ps", "-A", "-o", "pid=,ppid=,rss=,comm="], Self::SMI_TIMEOUT).ok().filter(|ran| ran.ok())?;
        Some(ran.stdout.lines().filter_map(Self::process_row).collect())
    }

    fn process_row(line: &str) -> Option<(i64, Value)> {
        let line = line.trim_start();
        let (pid, rest) = line.split_once(char::is_whitespace)?;
        let rest = rest.trim_start();
        let (parent, rest) = rest.split_once(char::is_whitespace)?;
        let rest = rest.trim_start();
        let (rss, name) = rest.split_once(char::is_whitespace)?;
        // absent-ok: `rsplit` always has a last part.
        let name = name.trim().rsplit('/').next().unwrap_or_default();
        let row = json!({"ppid": parent.parse::<i64>().ok()?, "rssKb": rss.parse::<i64>().ok()?, "name": name});
        Some((pid.parse().ok()?, row))
    }

    /// Load and memory, best effort. A stand's config says the memory of the machine it stands in for: a real machine's says nothing.
    pub fn cpu_ram(&self) -> Value {
        let mut reading = Resources::new(self.commands.as_ref(), self.linux).reading();
        if let Some(ram) = self.config.get("standRam") {
            Coerce::put(&mut reading, "ram", ram);
        }
        reading
    }

    /// This boot of the machine: changes on every boot and on nothing else. "" when the machine will not say.
    pub fn boot_id(&self) -> String {
        match std::fs::read_to_string("/proc/sys/kernel/random/boot_id") {
            Ok(text) => text.trim().to_string(),
            Err(_) => self.run_text(&["sysctl", "-n", "kern.boottime"]).trim().to_string(),
        }
    }
}
