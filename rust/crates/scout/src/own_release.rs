//! This scout as one release of the caravan: `<home>/releases/<commit>/caravan-scout`, and the next one fetched from its controller by the button on the machine's page.
//!
//! The program is replaced by a link, as the controller's is: `<home>/current` names the running release, and the service starts what it names. Nothing changes until what arrived
//! has been checked against the sum the controller named and has run here: a scout that does not start cannot be reached from the board again.

use crate::commands::Commands;
use crate::config::ScoutConfig;
use crate::errors::AppError;
use crate::heartbeat::Heartbeat;
use crate::http_client::HttpClient;
use crate::log::Log;
use net::Sha256;
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
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

/// The door a new release comes in by: the part of the scout that fetches it and ends the process for the service to start it.
pub struct OwnUpdate {
    running: Option<OwnRelease>,
    http: Arc<HttpClient>,
    commands: Arc<dyn Commands>,
    config: Arc<ScoutConfig>,
}

impl OwnUpdate {
    /// How long the answer has to go out before the process ends: the controller waits for it.
    const ANSWER_GOES: Duration = Duration::from_millis(500);

    /// The door of the running program.
    pub fn new(http: Arc<HttpClient>, commands: Arc<dyn Commands>, config: Arc<ScoutConfig>) -> Self {
        Self { running: OwnRelease::running(), http, commands, config }
    }

    /// What a restart of this process would cut, in words: a cell on its way up, whose copy runs inside it, and a job of its own. Cells that run outlive it.
    pub fn mid_work(cells: &[Value], jobs: &[(&str, Value)]) -> Vec<String> {
        let starting = cells.iter().filter_map(|cell| {
            let phase = cell.get("phase").and_then(Value::as_str).filter(|phase| Heartbeat::STARTING_PHASES.contains(phase))?;
            Some(format!(":{} is {phase}", cell.get("port").map_or_else(|| "?".to_string(), ToString::to_string)))
        });
        let running = jobs
            .iter()
            .filter(|(_, status)| status.get("running") == Some(&Value::Bool(true)))
            .map(|(name, _)| format!("{name} runs"));
        starting.chain(running).collect()
    }

    /// Takes the release `commit`, unless a restart would cut something named in `mid_work`. What is asked of a scout that cannot do it is refused in words, and nothing changes.
    pub fn take(&self, commit: &str, sha256: &str, mid_work: &[String]) -> Result<Value, AppError> {
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
        if !mid_work.is_empty() {
            return Err(AppError::with_status(format!("not now: {}. Nothing was changed", mid_work.join(", ")), 409));
        }
        release.take_new(&self.http, self.commands.as_ref(), &controller, commit, sha256)?;
        Log::line(&format!("[release] {commit} is in place: this process ends and the service starts it"));
        Self::end_after_the_answer()?;
        Ok(json!({"ok": true, "commit": commit, "restarting": true}))
    }

    fn end_after_the_answer() -> Result<(), AppError> {
        std::thread::Builder::new()
            .name("release-end".to_string())
            .spawn(|| {
                std::thread::sleep(Self::ANSWER_GOES);
                std::process::exit(0);
            })
            .map(drop)
            .map_err(|error| {
                AppError::with_status(format!("the release is in place, and this process did not end: {error}"), 500)
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::SystemCommands;

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
            assert_eq!(OwnUpdate::mid_work(&[json!({"port": 22001, "phase": phase})], &[]), [format!(":22001 is {phase}")]);
        }
        let quiet =
            [json!({"port": 22001, "phase": "running"}), json!({"port": 22002, "phase": "stopped"}), json!({"port": 22003})];
        let idle = [("a build", json!({"running": false})), ("an update", json!({}))];
        assert!(OwnUpdate::mid_work(&quiet, &idle).is_empty(), "a cell that runs outlives the restart");
        assert_eq!(OwnUpdate::mid_work(&quiet, &[("a build", json!({"running": true}))]), ["a build runs"]);
    }

    fn door(name: &str, running: Option<OwnRelease>, controller: &str) -> (OwnUpdate, PathBuf) {
        let folder = std::env::temp_dir().join(format!("caravan-own-update-{name}-{}", std::process::id()));
        drop(fs::remove_dir_all(&folder));
        fs::create_dir_all(&folder).unwrap();
        let path = folder.join("config.json");
        fs::write(&path, json!({"controllerUrl": controller}).to_string()).unwrap();
        let config = Arc::new(ScoutConfig::load(&path).unwrap());
        (OwnUpdate { running, http: Arc::new(HttpClient::new()), commands: Arc::new(SystemCommands), config }, folder)
    }

    #[test]
    fn what_cannot_be_taken_is_refused_in_words_and_nothing_changes() {
        let release = home("refusals", "aaaa");
        let refused = |update: &OwnUpdate, commit: &str, sum: &str, work: &[String]| update.take(commit, sum, work).unwrap_err();
        let (no_layout, folder) = door("no-layout", None, "http://controller");
        let error = refused(&no_layout, "bbbb", "ff", &[]);
        assert_eq!(error.status, 409);
        assert!(error.to_string().contains("not installed as a release"), "{error}");
        fs::remove_dir_all(folder).unwrap();
        let (update, folder) = door("words", Some(release.clone()), "http://controller");
        for (commit, sum) in [("../x", "ff"), ("", "ff"), ("bbbb", "")] {
            assert_eq!(refused(&update, commit, sum, &[]).status, 400, "{commit} {sum}");
        }
        let busy = refused(&update, "bbbb", "ff", &[":22001 is loading".to_string()]);
        assert_eq!(busy.status, 409);
        assert!(busy.to_string().contains(":22001 is loading"), "{busy}");
        assert_eq!(
            update.take("aaaa", "ff", &[":22001 is loading".to_string()]).unwrap()["restarting"],
            false,
            "the same release asks for no restart"
        );
        fs::remove_dir_all(folder).unwrap();
        let (unpaired, folder) = door("unpaired", Some(release.clone()), "");
        assert_eq!(refused(&unpaired, "bbbb", "ff", &[]).status, 409);
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
}
