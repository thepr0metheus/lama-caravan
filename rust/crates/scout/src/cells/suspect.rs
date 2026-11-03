//! A fresh `llama.cpp` build and crashing cells: the scout says so, and the board offers a rollback.
//!
//! Only the words of an engine's death count: a cell that will not start for want of a model or a port is not the build's fault. With the binary younger than 6 hours, 3 such crashes in 15 minutes make an
//! incident, kept in `state.json` under this build until the operator dismisses it for this build or the build changes. The rollback is the operator's. Crash times are counted in memory: a scout's restart
//! forgets those before it; an incident already raised stays.

use crate::log::Log;
use crate::runtimes::builds::LlamaBuilds;
use crate::state::ScoutState;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::sync::{Arc, Mutex, PoisonError};

/// The suspect.
pub struct CrashSuspect {
    state: Arc<ScoutState>,
    builds: Arc<LlamaBuilds>,
    clock: Arc<dyn Clock>,
    crashes: Mutex<Vec<f64>>,
}

/// This build: its commit, when its binary was made, and the key an incident and a dismissal are kept under.
struct BuildKey {
    commit: String,
    built_at: i64,
    key: String,
}

impl CrashSuspect {
    const MARKERS: [&'static str; 5] = ["CUDA error", "GGML_ABORT", "SIGSEGV", "SIGABRT", "Aborted (core dumped)"];
    const MIN_CRASHES: usize = 3;
    const WINDOW_SEC: f64 = 900.0;
    const FRESH_SEC: f64 = 21600.0;
    const INCIDENT: &'static str = "llamaSuspect";
    const DISMISSED: &'static str = "llamaSuspectDismissed";

    /// The suspect of this state and these builds.
    pub fn new(state: Arc<ScoutState>, builds: Arc<LlamaBuilds>, clock: Arc<dyn Clock>) -> Self {
        Self { state, builds, clock, crashes: Mutex::new(Vec::new()) }
    }

    /// The commit a version line names, in parentheses: 6 to 40 hexadecimal letters.
    fn commit_in(version: &str) -> String {
        let is_commit =
            |word: &str| (6..=40).contains(&word.len()) && word.chars().all(|letter| matches!(letter, '0'..='9' | 'a'..='f'));
        version
            .split('(')
            .skip(1)
            .filter_map(|rest| rest.split_once(')').map(|(word, _)| word))
            .find(|word| is_commit(word))
            .map_or_else(String::new, str::to_string)
    }

    fn build(&self, version: Option<&str>) -> BuildKey {
        let commit = version.map_or_else(|| Self::commit_in(&self.builds.binary_version()), Self::commit_in);
        let built_at = self.builds.binary_built_at();
        let key = format!("{commit}:{built_at}");
        BuildKey { commit, built_at, key }
    }

    /// A cell died saying `words`: its reason and last lines.
    pub fn crashed(&self, words: &str) {
        if !Self::MARKERS.iter().any(|marker| words.contains(marker)) {
            return;
        }
        let now = self.clock.epoch();
        let count = {
            let mut crashes = self.crashes.lock().unwrap_or_else(PoisonError::into_inner);
            crashes.retain(|at| now - *at < Self::WINDOW_SEC);
            crashes.push(now);
            crashes.len()
        };
        let build = self.build(None);
        // No binary: built at 0, never fresh.
        if count < Self::MIN_CRASHES || now - build.built_at as f64 >= Self::FRESH_SEC {
            return;
        }
        if self.state.get(Self::DISMISSED).as_ref().and_then(Value::as_str) == Some(build.key.as_str()) {
            return;
        }
        self.state.change(|doc| {
            let before = doc.get(Self::INCIDENT);
            let first = before
                .filter(|before| before.get("key").and_then(Value::as_str) == Some(build.key.as_str()))
                .and_then(|before| before.get("firstSeenAt"))
                .and_then(Value::as_i64);
            let incident = json!({
                "key": build.key,
                "commit": build.commit,
                "builtAt": build.built_at,
                "firstSeenAt": first.filter(|first| *first != 0).unwrap_or(now as i64),
                "lastSeenAt": now as i64,
                "crashes15m": count,
            });
            doc.insert(Self::INCIDENT.to_string(), incident);
        });
        let minutes = ((now - build.built_at as f64) / 60.0).floor() as i64;
        let commit = if build.commit.is_empty() { "commit unknown" } else { build.commit.as_str() };
        Log::line(&format!(
            "[suspect] {count} crashes in 15 minutes on a llama.cpp build {minutes} minutes old ({commit}) — the board offers a rollback"
        ));
    }

    /// The banner's word, for both reports: `{"suspect": false}`, or the incident with the build to roll back to (`null` when the archive holds no other). `version` when the caller has just read it.
    pub fn verdict(&self, version: Option<&str>) -> Value {
        let build = self.build(version);
        let mut incident = self.state.get(Self::INCIDENT).filter(|incident| Coerce::truthy(Some(incident)));
        if incident.as_ref().is_some_and(|incident| incident.get("key").and_then(Value::as_str) != Some(build.key.as_str())) {
            // Restored or updated since: a new build starts clean.
            self.state.change(|doc| doc.remove(Self::INCIDENT));
            incident = None;
        }
        // A dismissal takes the incident away, and none comes back for that build.
        let Some(incident) = incident else {
            return json!({"suspect": false});
        };
        json!({
            "suspect": true,
            "crashes15m": incident.get("crashes15m").cloned().unwrap_or_else(|| json!(0)),
            "builtAt": build.built_at,
            "currentCommit": build.commit,
            "firstSeenAt": incident.get("firstSeenAt"),
            "lastSeenAt": incident.get("lastSeenAt"),
            "restoreCandidate": self.candidate(&build.commit),
        })
    }

    /// The newest archived build of another commit, or `None`.
    fn candidate(&self, commit: &str) -> Option<Value> {
        const SHOWN: [&str; 5] = ["id", "commit", "version", "builtAt", "sizeMb"];
        let archive = self.builds.archive();
        let builds = archive.get("builds").and_then(Value::as_array)?;
        builds.iter().find_map(|build| {
            let other = if Coerce::truthy(build.get("commit")) { Coerce::text(build.get("commit")) } else { String::new() };
            let another = !other.is_empty() && !commit.is_empty() && !other.starts_with(commit) && !commit.starts_with(&other);
            another.then(|| {
                let fields: Map<String, Value> =
                    SHOWN.iter().filter_map(|key| build.get(*key).map(|value| ((*key).to_string(), value.clone()))).collect();
                Value::Object(fields)
            })
        })
    }

    /// The operator hid the banner: for this build only.
    pub fn dismiss(&self) -> Value {
        let build = self.build(None);
        self.state.change(|doc| {
            doc.insert(Self::DISMISSED.to_string(), json!(build.key));
            doc.remove(Self::INCIDENT);
        });
        json!({"ok": true, "dismissed": build.key})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_commit_is_what_the_parentheses_hold_when_it_reads_as_one() {
        assert_eq!(CrashSuspect::commit_in("version: 362 (3ac3c20)"), "3ac3c20");
        assert_eq!(CrashSuspect::commit_in("version (nope) 362 (3ac3c20) built"), "3ac3c20");
        assert_eq!(CrashSuspect::commit_in("version: 362 (abc)"), "");
        assert_eq!(CrashSuspect::commit_in(""), "");
    }
}
