//! This scout as one release of the caravan: `<home>/releases/<commit>/caravan-scout`, and the next one fetched from its controller by the button on the machine's page.
//!
//! The program is replaced by a link, as the controller's is: `<home>/current` names the running release, and the service starts what it names. Nothing changes until what arrived
//! has been checked against the sum the controller named and has run here: a scout that does not start cannot be reached from the board again.
//!
//! The process ends for the release in place only once its end cuts nothing, as the controller ends for its own only once its proxy runs no request
//! (the owner's plan of 2026-11-07, step 6: the scout is to wait for the requests on an update as the controller does). Every request to a model of
//! this machine passes through this process, and a stream through it would be cut halfway: a client loses its answer, and the cell behind it,
//! which outlives the scout, writes it to nobody.

use crate::cells::table::Cell;
use crate::commands::Commands;
use crate::config::ScoutConfig;
use crate::errors::AppError;
use crate::heartbeat::Heartbeat;
use crate::http_client::HttpClient;
use crate::log::Log;
use net::Sha256;
use os::clock::Clock;
use rules::ReleasePatience;
use serde_json::{Map, Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

/// Where the running program stands.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OwnRelease {
    home: PathBuf,
    commit: String,
}

impl OwnRelease {
    const PROGRAM: &'static str = "caravan-scout";
    /// The file the controller hands out.
    pub const BUNDLE_PATH: &'static str = "/scout/bundle.tar.gz";
    /// Releases left on the disk: the running one and those before it, for a way back by hand.
    const KEEP: usize = 3;
    const BUNDLE_MOST: u64 = 256 << 20;
    const FETCH: Duration = Duration::from_secs(300);
    const QUICK: Duration = Duration::from_secs(30);

    /// The release `program` is; `None` for a program run from anywhere else, a build tree, with nothing here to replace it by.
    pub fn of_program(program: &Path) -> Option<Self> {
        let folder = program.parent()?;
        let releases = folder.parent()?;
        if releases.file_name()? != "releases" {
            return None;
        }
        Some(Self { home: releases.parent()?.to_path_buf(), commit: folder.file_name()?.to_str()?.to_string() })
    }

    /// The release this process runs from, through the link `current` it was started by.
    pub fn running() -> Option<Self> {
        Self::of_program(&fs::canonicalize(std::env::current_exe().ok()?).ok()?)
    }

    /// The commit it was built from: its folder says it.
    pub fn commit(&self) -> &str {
        &self.commit
    }

    /// A commit is a word of hexadecimal digits: it becomes a folder's name here.
    pub fn is_commit(word: &str) -> bool {
        (4..=40).contains(&word.len()) && word.bytes().all(|letter| letter.is_ascii_digit() || (b'a'..=b'f').contains(&letter))
    }

    fn folder(&self, name: &str) -> PathBuf {
        self.home.join("releases").join(name)
    }

    /// Fetches the bundle from `controller`, checks it against `sha256` and that its program runs on this machine, and moves the link to it. A failure on the way leaves the running release named.
    pub fn take_new(
        &self,
        http: &HttpClient,
        commands: &dyn Commands,
        controller: &str,
        commit: &str,
        sha256: &str,
    ) -> Result<(), AppError> {
        let failed = |error: String| AppError::with_status(error, 502);
        let url = format!("{}{}", controller.trim_end_matches('/'), Self::BUNDLE_PATH);
        let answer =
            http.ask("GET", &url, &[], &[], Self::FETCH).map_err(|error| failed(format!("the bundle did not come: {error}")))?;
        let bytes = answer.text(Self::BUNDLE_MOST).map_err(|error| failed(format!("the bundle did not come whole: {error}")))?;
        if Sha256::of(&bytes) != sha256 {
            return Err(failed("what arrived is not what the controller named: nothing was changed".to_string()));
        }
        let new = self.folder(&format!("{commit}.new"));
        self.unpacked(commands, &new, &bytes).inspect_err(|_| drop(fs::remove_dir_all(&new)))?;
        let place = self.folder(commit);
        let moved = (!place.exists() || fs::remove_dir_all(&place).is_ok()).then(|| fs::rename(&new, &place));
        if !matches!(moved, Some(Ok(()))) {
            drop(fs::remove_dir_all(&new));
            return Err(failed(format!("the release could not be put in place: {}", place.display())));
        }
        self.point_at(commit).map_err(|error| failed(format!("the link did not move: {error}")))?;
        self.prune();
        Ok(())
    }

    /// The bundle's files in a folder of their own, and its program asked whether it runs here.
    fn unpacked(&self, commands: &dyn Commands, new: &Path, bytes: &[u8]) -> Result<(), AppError> {
        let failed = |error: String| AppError::with_status(error, 502);
        // absent-ok: a folder left by an update that died on the way, or none: either way it is made anew.
        drop(fs::remove_dir_all(new));
        fs::create_dir_all(new).map_err(|error| failed(format!("no folder for the release: {error}")))?;
        let bundle = new.join("bundle.tar.gz");
        fs::write(&bundle, bytes).map_err(|error| failed(format!("the bundle was not saved: {error}")))?;
        let (file, into) = (bundle.to_string_lossy().into_owned(), new.to_string_lossy().into_owned());
        let unpacked = commands.run(&["tar", "-xzf", &file, "-C", &into], Self::QUICK);
        if !unpacked.is_ok_and(|ran| ran.ok()) {
            return Err(failed("the bundle does not unpack: nothing was changed".to_string()));
        }
        drop(fs::remove_file(&bundle));
        let program = new.join(Self::PROGRAM).to_string_lossy().into_owned();
        if !commands.run(&[&program, "--version"], Self::QUICK).is_ok_and(|ran| ran.ok()) {
            return Err(failed("the new program does not run on this machine: nothing was changed".to_string()));
        }
        Ok(())
    }

    fn point_at(&self, commit: &str) -> std::io::Result<()> {
        let temporary = self.home.join("current.new");
        // absent-ok: no link left by an update that died on the way is the usual case.
        drop(fs::remove_file(&temporary));
        std::os::unix::fs::symlink(Path::new("releases").join(commit), &temporary)?;
        fs::rename(&temporary, self.home.join("current"))
    }

    /// The newest releases stay, and the running one, whose age does not matter: the older go.
    fn prune(&self) {
        let Ok(entries) = fs::read_dir(self.home.join("releases")) else {
            return;
        };
        let mut folders: Vec<(std::time::SystemTime, PathBuf)> = entries
            .flatten()
            .filter_map(|entry| Some((entry.metadata().ok()?.modified().ok()?, entry.path())))
            .filter(|(_, path)| path.is_dir())
            .collect();
        folders.sort_by_key(|(modified, _)| std::cmp::Reverse(*modified));
        let running = self.folder(&self.commit);
        for (_, old) in folders.into_iter().skip(Self::KEEP).filter(|(_, path)| *path != running) {
            if let Err(error) = fs::remove_dir_all(&old) {
                Log::line(&format!("[release] {} was not removed: {error}", old.display()));
            }
        }
    }
}

/// What runs in this process now that its end would cut.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Running {
    /// The scout's own work, in words: `OwnUpdate::mid_work`.
    pub work: Vec<String>,
    /// The connections being answered, the update's own among them while its answer goes.
    pub connections: usize,
    /// Of those, the requests through the machine's entry.
    pub entry: usize,
}

impl Running {
    /// The requests through the entry, in words; none, no words.
    fn requests(&self) -> Option<String> {
        match self.entry {
            0 => None,
            1 => Some("1 request through the machine's entry".to_string()),
            many => Some(format!("{many} requests through the machine's entry")),
        }
    }

    /// The other connections, the controller's calls, in words; none, no words.
    fn calls(&self) -> Option<String> {
        match self.connections.saturating_sub(self.entry) {
            0 => None,
            1 => Some("1 call to this scout".to_string()),
            many => Some(format!("{many} calls to this scout")),
        }
    }
}

/// What a look at the release in place finds.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Ending {
    /// Nothing the end would cut runs: the process ends now.
    Now,
    /// The process waits for these, in words.
    Waits(Vec<String>),
    /// What it answers has had its patience: the process ends now, and cuts these.
    Cutting(Vec<String>),
}

/// A release put in place, which this process ends for.
#[derive(Debug, Clone, PartialEq)]
struct Taken {
    commit: String,
    /// When the first release of this wait was put in place, on the monotonic clock: the patience counts from then.
    at: f64,
}

/// The door a new release comes in by: the part of the scout that fetches it, and ends the process for the service to start it once the end cuts
/// nothing.
///
/// The rule. A cell on its way up, a job of its own or a move of a model folder refuses a release with 409, "not now" (`mid_work`): the
/// controller asks again later, and
/// nothing changes. What the scout is answering does not refuse it, and a request through the entry, a stream among them, does not either: the
/// release is put in place, the answer says what the process waits for (`waitsFor`), and the process ends at the first look, every `TURN`, at which
/// no connection is answered and no work of its own runs. Connections are waited for `ReleasePatience` at the most from the first release of the
/// wait, the controller's own patience with its proxy's requests: past it, what still runs is cut, and the log says what. The scout's own work is
/// waited for as long as it takes: none of it ran when the release came, so it was started since by somebody who meant it, and nothing would
/// finish it after the end. Meanwhile everything is answered as before: a new request is served, not refused, and is waited for too.
pub struct OwnUpdate {
    running: Option<OwnRelease>,
    http: Arc<HttpClient>,
    commands: Arc<dyn Commands>,
    config: Arc<ScoutConfig>,
    clock: Arc<dyn Clock>,
    /// The release in place this process ends for; `None` until one is. Held while a release is put in place, and by the look that ends the
    /// process: it never ends halfway through one.
    taken: Mutex<Option<Taken>>,
}

impl OwnUpdate {
    /// How often the release in place looks whether the process may end.
    pub const TURN: Duration = Duration::from_millis(250);

    /// The door of the running program.
    pub fn new(http: Arc<HttpClient>, commands: Arc<dyn Commands>, config: Arc<ScoutConfig>, clock: Arc<dyn Clock>) -> Self {
        Self { running: OwnRelease::running(), http, commands, config, clock, taken: Mutex::new(None) }
    }

    /// What a restart of this process would cut of its own work, in words: a cell on its way up, whose copy runs inside it, a job of its own,
    /// and the move of a model folder (`moving`, its words), whose copies run inside it too: a cut move leaves its half-copied files behind.
    /// Cells that run outlive it.
    pub fn mid_work(cells: &[Value], jobs: &[(&str, Value)], moving: Option<String>) -> Vec<String> {
        let starting = cells.iter().filter_map(|cell| {
            let phase = cell.get("phase").and_then(Value::as_str).filter(|phase| Heartbeat::STARTING_PHASES.contains(phase))?;
            let id = cell.get("id").and_then(Value::as_str).unwrap_or("?"); // absent-ok: a view of a cell names it; one that does not is said as `?`
            Some(format!("{} is {phase}", Cell::words(id, cell.get("port").and_then(Value::as_i64))))
        });
        let running = jobs
            .iter()
            .filter(|(_, status)| status.get("running") == Some(&Value::Bool(true)))
            .map(|(name, _)| format!("{name} runs"));
        starting.chain(running).chain(moving).collect()
    }

    fn taken(&self) -> MutexGuard<'_, Option<Taken>> {
        self.taken.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Takes the release `commit`, unless its work (`running.work`) would be cut. What is asked of a scout that cannot do it is refused in
    /// words, and nothing changes. The release already in place is not fetched again: the answer says it as the first one did.
    pub fn take(&self, commit: &str, sha256: &str, running: &Running) -> Result<Value, AppError> {
        let release = self.running.as_ref().ok_or_else(|| {
            AppError::with_status("this scout was not installed as a release: there is nothing here to replace", 409)
        })?;
        if !OwnRelease::is_commit(commit) || sha256.is_empty() {
            return Err(AppError::new("commit and sha256 are required"));
        }
        if release.commit() == commit {
            return Ok(json!({"ok": true, "commit": commit, "restarting": false}));
        }
        let controller = self.config.text("controllerUrl");
        if controller.is_empty() {
            return Err(AppError::with_status("this scout has no controller to fetch from", 409));
        }
        let mut taken = self.taken();
        if taken.as_ref().is_some_and(|taken| taken.commit == commit) {
            return Ok(Self::restarting(commit, running));
        }
        if !running.work.is_empty() {
            return Err(AppError::with_status(format!("not now: {}. Nothing was changed", running.work.join(", ")), 409));
        }
        release.take_new(&self.http, self.commands.as_ref(), &controller, commit, sha256)?;
        // absent-ok: a first release starts the wait now; a later one keeps the moment the wait began.
        let at = taken.as_ref().map_or_else(|| self.clock.monotonic(), |before| before.at);
        *taken = Some(Taken { commit: commit.to_string(), at });
        let waits = match running.requests() {
            Some(requests) => {
                format!("once what passes through it is done ({requests}), {} s at the most", ReleasePatience::SECONDS)
            }
            None => "as soon as its answer goes".to_string(),
        };
        Log::line(&format!("[release] {commit} is in place: this process ends {waits}, and the service starts it"));
        Ok(Self::restarting(commit, running))
    }

    /// The answer of a release in place: `waitsFor` says what the process waits for before it ends, when anything, and how long it waits for
    /// the requests at the most.
    fn restarting(commit: &str, running: &Running) -> Value {
        let mut answer = Map::new();
        answer.insert("ok".to_string(), json!(true));
        answer.insert("commit".to_string(), json!(commit));
        answer.insert("restarting".to_string(), json!(true));
        let words: Vec<String> = running.work.iter().cloned().chain(running.requests()).collect();
        if !words.is_empty() {
            let waits = json!({"words": words, "requests": running.entry, "mostSec": ReleasePatience::SECONDS});
            answer.insert("waitsFor".to_string(), waits);
        }
        Value::Object(answer)
    }

    /// What a look finds, from values alone: what runs, and how long the wait has gone on.
    fn ending(running: &Running, waited: f64) -> Ending {
        let answering: Vec<String> = running.requests().into_iter().chain(running.calls()).collect();
        if !running.work.is_empty() {
            return Ending::Waits(running.work.iter().cloned().chain(answering).collect());
        }
        if answering.is_empty() {
            return Ending::Now;
        }
        if waited >= ReleasePatience::SECONDS {
            return Ending::Cutting(answering);
        }
        Ending::Waits(answering)
    }

    /// One look at the release in place: when the process may end, `end` is called with the words for the log, the door still held, so that
    /// no release is put in place halfway. Nothing while no release is in place, and `running` is not even asked then.
    pub fn look(&self, running: impl FnOnce() -> Running, end: impl FnOnce(&str)) {
        let taken = self.taken();
        let Some(Taken { commit, at }) = taken.as_ref() else {
            return;
        };
        match Self::ending(&running(), self.clock.monotonic() - at) {
            Ending::Now => end(&format!(
                "[release] {commit}: nothing runs that the end would cut, this process ends and the service starts it"
            )),
            Ending::Cutting(cut) => end(&format!(
                "[release] {commit}: {} s waited, this process ends and cuts {}; the service starts it",
                ReleasePatience::SECONDS,
                cut.join(", ")
            )),
            Ending::Waits(_) => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::SystemCommands;
    use crate::tests::{HandClock, StandIn};

    #[test]
    fn a_program_in_a_release_folder_says_its_home_and_commit() {
        let release = OwnRelease::of_program(Path::new("/home/x/caravan-scout/releases/abc123/caravan-scout")).unwrap();
        assert_eq!(release.commit(), "abc123");
        assert_eq!(release.home, PathBuf::from("/home/x/caravan-scout"));
        assert_eq!(OwnRelease::of_program(Path::new("/repo/rust/target/release/caravan-scout")), None);
    }

    #[test]
    fn a_commit_is_a_word_of_hexadecimal_digits() {
        for good in ["abcd", "98865d64", "0123456789abcdef0123456789abcdef01234567"] {
            assert!(OwnRelease::is_commit(good), "{good}");
        }
        for bad in ["", "abc", "../x", "ABCD", "abcd/", "abcd.new", "0123456789abcdef0123456789abcdef012345678"] {
            assert!(!OwnRelease::is_commit(bad), "{bad}");
        }
    }

    #[test]
    fn a_restart_is_refused_only_for_what_it_would_cut() {
        for phase in Heartbeat::STARTING_PHASES {
            assert_eq!(
                OwnUpdate::mid_work(&[json!({"id": "c22001", "port": 22001, "phase": phase})], &[], None),
                [format!(":22001 is {phase}")]
            );
            assert_eq!(
                OwnUpdate::mid_work(&[json!({"id": "c3f9a02b1", "port": null, "phase": phase})], &[], None),
                [format!("c3f9a02b1 is {phase}")],
                "a start that has no port yet is said by its cell's name"
            );
        }
        let quiet = [
            json!({"id": "c22001", "port": 22001, "phase": "running"}),
            json!({"id": "c22002", "phase": "stopped"}),
            json!({"id": "c22003"}),
        ];
        let idle = [("a build", json!({"running": false})), ("an update", json!({}))];
        assert!(OwnUpdate::mid_work(&quiet, &idle, None).is_empty(), "a cell that runs outlives the restart");
        assert_eq!(OwnUpdate::mid_work(&quiet, &[("a build", json!({"running": true}))], None), ["a build runs"]);
        let moving = Some("the model cache is moving to /mnt/hdd".to_string());
        assert_eq!(
            OwnUpdate::mid_work(&quiet, &idle, moving),
            ["the model cache is moving to /mnt/hdd"],
            "a move of a model folder runs inside the process: a restart would cut it halfway"
        );
    }

    fn door(name: &str, running: Option<OwnRelease>, controller: &str) -> (OwnUpdate, PathBuf) {
        door_with_clock(name, running, controller, HandClock::at(1_000))
    }

    fn door_with_clock(name: &str, running: Option<OwnRelease>, controller: &str, clock: Arc<HandClock>) -> (OwnUpdate, PathBuf) {
        let folder = std::env::temp_dir().join(format!("caravan-own-update-{name}-{}", std::process::id()));
        drop(fs::remove_dir_all(&folder));
        fs::create_dir_all(&folder).unwrap();
        let path = folder.join("config.json");
        fs::write(&path, json!({"controllerUrl": controller}).to_string()).unwrap();
        let config = Arc::new(ScoutConfig::load(&path).unwrap());
        let (http, commands) = (Arc::new(HttpClient::new()), Arc::new(SystemCommands));
        (OwnUpdate { running, http, commands, config, clock, taken: Mutex::new(None) }, folder)
    }

    fn working(work: &[&str]) -> Running {
        Running { work: work.iter().map(|words| (*words).to_string()).collect(), ..Running::default() }
    }

    #[test]
    fn what_cannot_be_taken_is_refused_in_words_and_nothing_changes() {
        let release = home("refusals", "aaaa");
        let refused =
            |update: &OwnUpdate, commit: &str, sum: &str, running: &Running| update.take(commit, sum, running).unwrap_err();
        let (no_layout, folder) = door("no-layout", None, "http://controller");
        let error = refused(&no_layout, "bbbb", "ff", &Running::default());
        assert_eq!(error.status, 409);
        assert!(error.to_string().contains("not installed as a release"), "{error}");
        fs::remove_dir_all(folder).unwrap();
        let (update, folder) = door("words", Some(release.clone()), "http://controller");
        for (commit, sum) in [("../x", "ff"), ("", "ff"), ("bbbb", "")] {
            assert_eq!(refused(&update, commit, sum, &Running::default()).status, 400, "{commit} {sum}");
        }
        let busy = refused(&update, "bbbb", "ff", &working(&[":22001 is loading"]));
        assert_eq!(busy.status, 409);
        assert!(busy.to_string().contains(":22001 is loading"), "{busy}");
        assert_eq!(
            update.take("aaaa", "ff", &working(&[":22001 is loading"])).unwrap()["restarting"],
            false,
            "the same release asks for no restart"
        );
        assert_eq!(*update.taken(), None, "negative: a refusal puts no release in place for the look to end the process for");
        fs::remove_dir_all(folder).unwrap();
        let (unpaired, folder) = door("unpaired", Some(release.clone()), "");
        assert_eq!(refused(&unpaired, "bbbb", "ff", &Running::default()).status, 409);
        fs::remove_dir_all(folder).unwrap();
        let folders: Vec<_> =
            fs::read_dir(release.home.join("releases")).unwrap().flatten().map(|entry| entry.file_name()).collect();
        assert_eq!(folders, ["aaaa"], "no refusal leaves a folder");
        assert!(!release.home.join("current").exists());
        fs::remove_dir_all(&release.home).unwrap();
    }

    fn home(name: &str, commit: &str) -> OwnRelease {
        let base = std::env::temp_dir().join(format!("caravan-own-release-{name}-{}", std::process::id()));
        drop(fs::remove_dir_all(&base));
        fs::create_dir_all(base.join("releases").join(commit)).unwrap();
        OwnRelease { home: base, commit: commit.to_string() }
    }

    #[test]
    fn the_link_names_the_new_release_and_old_ones_go() {
        let release = home("prune", "aaaa");
        for (at, name) in ["bbbb", "cccc", "dddd", "eeee"].iter().enumerate() {
            fs::create_dir_all(release.folder(name)).unwrap();
            std::thread::sleep(Duration::from_millis(15 + at as u64));
        }
        release.point_at("eeee").unwrap();
        assert_eq!(fs::read_link(release.home.join("current")).unwrap(), Path::new("releases/eeee"));
        release.point_at("dddd").unwrap();
        assert_eq!(fs::read_link(release.home.join("current")).unwrap(), Path::new("releases/dddd"));
        release.prune();
        assert!(release.folder("aaaa").exists(), "the running one stays, however old");
        assert!(release.folder("eeee").exists() && release.folder("dddd").exists() && release.folder("cccc").exists());
        assert!(!release.folder("bbbb").exists(), "older than the three newest");
        fs::remove_dir_all(&release.home).unwrap();
    }

    /// A bundle as a controller hands it out: a program that says its version, packed by the system's `tar`.
    fn bundle(name: &str) -> Vec<u8> {
        use std::os::unix::fs::PermissionsExt;
        let folder = std::env::temp_dir().join(format!("caravan-own-bundle-{name}-{}", std::process::id()));
        drop(fs::remove_dir_all(&folder));
        fs::create_dir_all(&folder).unwrap();
        let program = folder.join(OwnRelease::PROGRAM);
        fs::write(&program, "#!/bin/sh\necho caravan-scout 0.0.0\n").unwrap();
        fs::set_permissions(&program, fs::Permissions::from_mode(0o755)).unwrap();
        let (packed, from) = (folder.join("bundle.tar.gz"), folder.to_string_lossy().into_owned());
        let argv = ["tar", "-czf", &packed.to_string_lossy(), "-C", &from, OwnRelease::PROGRAM].map(str::to_string);
        let argv: Vec<&str> = argv.iter().map(String::as_str).collect();
        assert!(SystemCommands.run(&argv, Duration::from_secs(30)).unwrap().ok(), "the bundle was not packed");
        let bytes = fs::read(&packed).unwrap();
        fs::remove_dir_all(&folder).unwrap();
        bytes
    }

    fn streams(entry: usize, calls: usize) -> Running {
        Running { connections: entry + calls, entry, ..Running::default() }
    }

    #[test]
    fn the_end_waits_for_what_runs_and_for_the_requests_only_so_long() {
        let patience = ReleasePatience::SECONDS;
        assert_eq!(OwnUpdate::ending(&Running::default(), 0.0), Ending::Now);
        let words = ["2 requests through the machine's entry", "1 call to this scout"].map(str::to_string).to_vec();
        assert_eq!(OwnUpdate::ending(&streams(2, 1), 0.0), Ending::Waits(words.clone()));
        assert_eq!(OwnUpdate::ending(&streams(2, 1), patience - 1.0), Ending::Waits(words.clone()));
        assert_eq!(OwnUpdate::ending(&streams(2, 1), patience), Ending::Cutting(words), "past the patience, what runs is cut");
        let one = ["1 request through the machine's entry".to_string()].to_vec();
        assert_eq!(OwnUpdate::ending(&streams(1, 0), 0.0), Ending::Waits(one.clone()));
        let own_answer = ["1 call to this scout".to_string()].to_vec();
        assert_eq!(
            OwnUpdate::ending(&streams(0, 1), 0.0),
            Ending::Waits(own_answer),
            "the update's own answer goes before the end"
        );
        let work = Running { work: vec!["c22001 is downloading".to_string()], ..streams(1, 0) };
        assert_eq!(
            OwnUpdate::ending(&work, patience * 10.0),
            Ending::Waits([vec!["c22001 is downloading".to_string()], one].concat()),
            "negative: the scout's own work has no patience: nothing would finish it after the end"
        );
    }

    #[test]
    fn requests_through_the_entry_do_not_refuse_a_release_and_its_answer_says_it_waits_for_them() {
        let release = home("waits", "aaaa");
        let packed = bundle("waits");
        let sum = Sha256::of(&packed);
        let controller = StandIn::serving(move |_| StandIn::answer("200 OK", &packed));
        let (update, folder) = door("waits", Some(release.clone()), controller.address());
        let said = update.take("bbbb", &sum, &streams(2, 1)).unwrap();
        let waits =
            json!({"words": ["2 requests through the machine's entry"], "requests": 2, "mostSec": ReleasePatience::SECONDS});
        assert_eq!(said, json!({"ok": true, "commit": "bbbb", "restarting": true, "waitsFor": waits}));
        assert_eq!(fs::read_link(release.home.join("current")).unwrap(), Path::new("releases/bbbb"), "in place while they run");
        let again = update.take("bbbb", &sum, &working(&["c22001 is loading"])).unwrap();
        assert_eq!(again["waitsFor"]["words"], json!(["c22001 is loading"]), "work begun since is waited for, not refused");
        assert_eq!(controller.targets(), [OwnRelease::BUNDLE_PATH], "negative: the release in place was fetched again");
        let quiet = update.take("bbbb", &sum, &Running::default()).unwrap();
        assert_eq!(quiet, json!({"ok": true, "commit": "bbbb", "restarting": true}), "nothing to wait for, no `waitsFor`");
        let refused = update.take("cccc", &sum, &working(&["c22001 is loading"])).unwrap_err();
        assert_eq!(refused.status, 409, "another release is still refused for work under way: {refused}");
        assert_eq!(fs::read_link(release.home.join("current")).unwrap(), Path::new("releases/bbbb"));
        fs::remove_dir_all(folder).unwrap();
        fs::remove_dir_all(&release.home).unwrap();
    }

    #[test]
    fn a_look_ends_the_process_once_nothing_runs_or_the_patience_is_over() {
        let release = home("looks", "aaaa");
        let packed = bundle("looks");
        let sum = Sha256::of(&packed);
        let controller = StandIn::serving(move |_| StandIn::answer("200 OK", &packed));
        let clock = HandClock::at(1_000);
        let (update, folder) = door_with_clock("looks", Some(release.clone()), controller.address(), Arc::clone(&clock));
        let ends = |running: Running| {
            let mut said = None;
            update.look(|| running, |words| said = Some(words.to_string()));
            said
        };
        assert_eq!(ends(Running::default()), None, "negative: no release in place, the process does not end");
        update.take("bbbb", &sum, &streams(1, 1)).unwrap();
        assert_eq!(ends(streams(1, 1)), None, "the request runs");
        clock.pass(300);
        update.take("cccc", &sum, &streams(1, 1)).unwrap();
        assert_eq!(
            fs::read_link(release.home.join("current")).unwrap(),
            Path::new("releases/cccc"),
            "a later release is taken in the wait"
        );
        clock.pass(299);
        assert_eq!(ends(streams(1, 0)), None);
        clock.pass(1);
        let cut = ends(streams(1, 1)).unwrap();
        assert!(
            cut.contains("cccc") && cut.contains("cuts 1 request through the machine's entry, 1 call to this scout"),
            "{cut}"
        );
        assert_eq!(
            ends(working(&["the llama.cpp build runs"])),
            None,
            "negative: the scout's own work holds the end past the patience"
        );
        let quiet = ends(Running::default()).unwrap();
        assert!(quiet.contains("nothing runs that the end would cut"), "{quiet}");
        fs::remove_dir_all(folder).unwrap();
        fs::remove_dir_all(&release.home).unwrap();
    }

    #[test]
    fn with_no_release_in_place_a_look_asks_nothing() {
        let release = home("asks-nothing", "aaaa");
        let (update, folder) = door("asks-nothing", Some(release.clone()), "http://controller");
        update.look(|| panic!("negative: what runs was asked with no release in place"), |words| panic!("ended: {words}"));
        fs::remove_dir_all(folder).unwrap();
        fs::remove_dir_all(&release.home).unwrap();
    }
}
