//! The scout as this controller hands it out. A release carries it: `scout-bundle.tar.gz`, the program and its scripts, and `scout-bundle.json`, what that file is. A new machine
//! takes both through the script `/scout/install.sh`, with one command; a machine that has a scout takes the file when the board says so, and by
//! itself after a delivery when its scout changed (ScoutFollow).

use super::scout::ScoutCall;
use crate::app::App;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::path::PathBuf;

/// What a release says of the bundle it carries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleFacts {
    commit: String,
    sha256: String,
    bytes: u64,
    /// What the bundle carries, the archive's own times aside: the sum of the program and of its scripts' tree (deploy/nas/release_ship.py). Two
    /// releases of one content hand out one scout. `None` for a release built before the script said it: it cannot tell a changed scout from the same.
    content: Option<String>,
}

impl BundleFacts {
    /// The facts in `said`; `None` when a part of them is missing: a half-said bundle is no bundle. The content is said only by newer releases.
    fn read(said: &[u8]) -> Option<Self> {
        let said: Value = serde_json::from_slice(said).ok()?;
        let word = |key: &str| said.get(key).and_then(Value::as_str).filter(|word| !word.is_empty()).map(str::to_string);
        let bytes = said.get("bytes")?.as_u64()?;
        Some(Self { commit: word("commit")?, sha256: word("sha256")?, bytes, content: word("content") })
    }

    fn view(&self) -> Value {
        json!({"commit": self.commit, "sha256": self.sha256, "bytes": self.bytes})
    }

    /// The commit the release was built from.
    pub fn commit(&self) -> &str {
        &self.commit
    }

    /// Whether the release says what its scout is.
    pub fn says_content(&self) -> bool {
        self.content.is_some()
    }

    /// Whether `other` hands out the same scout: `None` when either does not say what its scout is.
    pub fn same_scout(&self, other: &Self) -> Option<bool> {
        Some(self.content.as_ref()? == other.content.as_ref()?)
    }
}

/// The bundle of this controller.
pub struct ScoutBundle<'app> {
    app: &'app App,
}

impl<'app> ScoutBundle<'app> {
    const FILE: &'static str = "scout-bundle.tar.gz";
    const FACTS: &'static str = "scout-bundle.json";
    const INSTALLER: &'static str = include_str!("../../../scout/install.sh");
    /// The other machine fetches the file over its network, checks and unpacks it before it answers.
    const TAKING_SEC: u64 = 300;

    /// The bundle of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The file a machine fetches.
    pub fn file(&self) -> PathBuf {
        self.app.paths.project_root.join(Self::FILE)
    }

    /// What the release says; `None` for a controller with nothing to hand out, such as one run from a build tree.
    pub fn facts(&self) -> Option<BundleFacts> {
        let said = std::fs::read(self.app.paths.project_root.join(Self::FACTS)).ok()?;
        BundleFacts::read(&said).filter(|_| self.file().is_file())
    }

    /// What another release kept beside this one says of its bundle: `releases/<commit>`, the folders release_ship.py keeps. `None` for one
    /// not kept here, or not said. The commit comes from a machine's report: it is found among the folders by name, never joined into a path.
    fn kept(&self, commit: &str) -> Option<BundleFacts> {
        let releases = std::fs::canonicalize(&self.app.paths.project_root).ok()?.parent()?.to_path_buf();
        let folder = std::fs::read_dir(releases).ok()?.flatten().find(|entry| entry.file_name().to_str() == Some(commit))?.path();
        BundleFacts::read(&std::fs::read(folder.join(Self::FACTS)).ok()?)
    }

    /// Whether the scout of the release `running` is the one this controller hands out: `None` when it cannot tell, for a controller with no
    /// release, a release not kept here, or one that does not say what its scout is.
    pub fn same_scout(&self, running: &str) -> Option<bool> {
        let facts = self.facts()?;
        if facts.commit == running {
            return Some(true);
        }
        facts.same_scout(&self.kept(running)?)
    }

    /// The refusal for a controller that has no bundle.
    pub fn none() -> AppError {
        AppError::with_status("this controller carries no scout: only a release built by deploy/nas/release_ship.py has one", 404)
    }

    /// The controller as a new machine reaches it: the address this controller is told to give, else the one the request came to.
    fn address(&self, came_to: &str) -> Result<String, AppError> {
        let told = Coerce::strip(&self.app.paths.topology_server_url).trim_end_matches('/');
        if !told.is_empty() {
            return Ok(told.to_string());
        }
        // It lands inside a script that another machine runs.
        let plain =
            !came_to.is_empty() && came_to.chars().all(|letter| letter.is_ascii_alphanumeric() || ".-:[]".contains(letter));
        plain
            .then(|| format!("http://{came_to}"))
            .ok_or_else(|| AppError::new("the request names no usable address of this controller"))
    }

    /// The script a new machine runs, its blanks filled in: where to fetch from and what must arrive.
    pub fn installer(&self, came_to: &str) -> Result<String, AppError> {
        let facts = self.facts().ok_or_else(Self::none)?;
        Ok(Self::INSTALLER
            .replace("@@CONTROLLER@@", &self.address(came_to)?)
            .replace("@@COMMIT@@", &facts.commit)
            .replace("@@SHA256@@", &facts.sha256))
    }

    /// The release a machine's scout runs, as its last report said; `None` for a scout that does not say: an older one, or one not installed as a release, has nothing to replace itself by.
    fn running(&self, host_id: &str) -> Result<Option<String>, AppError> {
        let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(host_id).cloned());
        let host = host.ok_or_else(|| AppError::with_status(format!("no scout has reported for host {host_id}"), 404))?;
        Ok(host.get("scoutCommit").and_then(Value::as_str).filter(|commit| !commit.is_empty()).map(str::to_string))
    }

    /// What the board shows: the release on offer, the one `host_id` runs, each named or said to be absent, whether the two are one scout (null:
    /// cannot tell), and the command that installs a scout on a new machine. An empty `host_id` asks about no machine.
    pub fn status(&self, host_id: &str, came_to: &str) -> Result<Value, AppError> {
        let running = if host_id.is_empty() { None } else { self.running(host_id)? };
        let same = running.as_deref().and_then(|running| self.same_scout(running));
        let facts = self.facts();
        let address = facts.as_ref().map(|_| self.address(came_to)).transpose()?;
        let command = address.map(|address| format!("curl -fsSL {address}/scout/install.sh | bash"));
        let release = facts.as_ref().map(BundleFacts::view);
        Ok(json!({"ok": true, "release": release, "running": running, "sameScout": same, "installCommand": command}))
    }

    /// The scout to tell and what to tell it, or the refusal for a controller with nothing to hand out and for a scout that cannot replace itself.
    fn handing(&self, host_id: &str) -> Result<(ScoutCall<'app>, Value), AppError> {
        let facts = self.facts().ok_or_else(Self::none)?;
        let call = ScoutCall::of_host(self.app, host_id)?;
        if self.running(host_id)?.is_none() {
            let words = format!(
                "the scout on {host_id} was not installed as a release and cannot replace itself: run the command of ＋ Add scout on that machine"
            );
            return Err(AppError::with_status(words, 409));
        }
        Ok((call, json!({"commit": facts.commit, "sha256": facts.sha256})))
    }

    /// Tells the machine's scout to take the release this controller carries. It answers, ends, and its service starts the new one; the cells that
    /// run outlive it. A refusal says whose it is: the scout's keeps its status, and one busy for now says 409 (own_release.rs).
    pub fn update(&self, host_id: &str) -> Result<Value, NotTaken> {
        let (call, offer) = self.handing(host_id).map_err(NotTaken::Controller)?;
        call.post_as_said("/api/scout/update", &offer, Self::TAKING_SEC).map_err(NotTaken::Scout)
    }
}

/// Why a release was not taken.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NotTaken {
    /// This controller refused before any scout was asked: it carries no release, or the machine's scout cannot replace itself.
    Controller(AppError),
    /// The scout refused, with its own status, or did not answer usably (502).
    Scout(AppError),
}

impl NotTaken {
    /// The scout says it is busy for now: a cell on its way up, or a job of its own. Asked again later, it may take it.
    pub fn busy(&self) -> bool {
        matches!(self, Self::Scout(error) if error.status == 409)
    }

    /// The refusal as the board is answered: the controller's own as it is, the scout's as 502 with its words, as before it was told apart.
    pub fn answered(self) -> AppError {
        match self {
            Self::Controller(error) => error,
            Self::Scout(error) => AppError::with_status(error.message, 502),
        }
    }

    /// The refusal in words, for the log.
    pub fn words(&self) -> &str {
        match self {
            Self::Controller(error) | Self::Scout(error) => &error.message,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_half_said_bundle_is_no_bundle() {
        let whole = br#"{"commit": "abcd1234", "sha256": "ff", "bytes": 12}"#;
        assert_eq!(
            BundleFacts::read(whole),
            Some(BundleFacts { commit: "abcd1234".to_string(), sha256: "ff".to_string(), bytes: 12, content: None })
        );
        for half in [
            &br#"{"sha256": "ff", "bytes": 12}"#[..],
            br#"{"commit": "", "sha256": "ff", "bytes": 12}"#,
            br#"{"commit": "a", "sha256": "ff"}"#,
            b"not json",
            b"",
        ] {
            assert_eq!(BundleFacts::read(half), None, "{}", String::from_utf8_lossy(half));
        }
    }

    #[test]
    fn one_content_is_one_scout_and_an_unsaid_one_tells_nothing() {
        let facts = |commit: &str, content: &str| {
            let said = json!({"commit": commit, "sha256": "ff", "bytes": 12, "content": content});
            BundleFacts::read(said.to_string().as_bytes()).unwrap()
        };
        let (old, same, other) = (facts("aaaa1111", "c1"), facts("bbbb2222", "c1"), facts("cccc3333", "c2"));
        assert!(same.says_content());
        assert_eq!(same.same_scout(&old), Some(true), "another commit, one content: the same scout");
        assert_eq!(other.same_scout(&old), Some(false));
        let unsaid = BundleFacts::read(br#"{"commit": "dddd4444", "sha256": "ff", "bytes": 12, "content": ""}"#).unwrap();
        assert!(!unsaid.says_content(), "an empty content says nothing");
        assert_eq!(unsaid.same_scout(&old), None, "negative: a release that does not say is not the same scout, and not another");
        assert_eq!(old.same_scout(&unsaid), None);
        assert_eq!(old.view(), json!({"commit": "aaaa1111", "sha256": "ff", "bytes": 12}), "the board's view is unchanged");
    }

    #[test]
    fn the_installer_has_its_three_blanks() {
        for blank in ["@@CONTROLLER@@", "@@COMMIT@@", "@@SHA256@@"] {
            assert!(ScoutBundle::INSTALLER.contains(blank), "{blank}");
        }
    }
}
