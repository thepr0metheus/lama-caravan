//! The scout as this controller hands it out. A release carries it: `scout-bundle.tar.gz`, the program and its scripts, and `scout-bundle.json`, what that file is. A new machine
//! takes both through the script `/scout/install.sh`, with one command; a machine that has a scout takes the file when the board says so.

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
}

impl BundleFacts {
    /// The facts in `said`; `None` when a part of them is missing: a half-said bundle is no bundle.
    fn read(said: &[u8]) -> Option<Self> {
        let said: Value = serde_json::from_slice(said).ok()?;
        let word = |key: &str| said.get(key).and_then(Value::as_str).filter(|word| !word.is_empty()).map(str::to_string);
        Some(Self { commit: word("commit")?, sha256: word("sha256")?, bytes: said.get("bytes")?.as_u64()? })
    }

    fn view(&self) -> Value {
        json!({"commit": self.commit, "sha256": self.sha256, "bytes": self.bytes})
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

    /// What the board shows: the release on offer, the one `host_id` runs, each named or said to be absent, and the command that installs a scout on a new machine. An empty `host_id` asks about no machine.
    pub fn status(&self, host_id: &str, came_to: &str) -> Result<Value, AppError> {
        let running = if host_id.is_empty() { None } else { self.running(host_id)? };
        let facts = self.facts();
        let address = facts.as_ref().map(|_| self.address(came_to)).transpose()?;
        let command = address.map(|address| format!("curl -fsSL {address}/scout/install.sh | bash"));
        Ok(json!({"ok": true, "release": facts.as_ref().map(BundleFacts::view), "running": running, "installCommand": command}))
    }

    /// Tells the machine's scout to take the release this controller carries. It answers, ends, and its service starts the new one; the cells that run outlive it.
    pub fn update(&self, host_id: &str) -> Result<Value, AppError> {
        let facts = self.facts().ok_or_else(Self::none)?;
        let call = ScoutCall::of_host(self.app, host_id)?;
        if self.running(host_id)?.is_none() {
            let words = format!(
                "the scout on {host_id} was not installed as a release and cannot replace itself: run the command of ＋ Add scout on that machine"
            );
            return Err(AppError::with_status(words, 409));
        }
        call.post("/api/scout/update", &json!({"commit": facts.commit, "sha256": facts.sha256}), Self::TAKING_SEC)
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
            Some(BundleFacts { commit: "abcd1234".to_string(), sha256: "ff".to_string(), bytes: 12 })
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
    fn the_installer_has_its_three_blanks() {
        for blank in ["@@CONTROLLER@@", "@@COMMIT@@", "@@SHA256@@"] {
            assert!(ScoutBundle::INSTALLER.contains(blank), "{blank}");
        }
    }
}
