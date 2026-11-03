//! The cell servers a command cell runs, fetched from the controller before it starts.
//!
//! Before this, every host obtained those files on its own, and nothing compared the copies: a client that had not pulled in a while quietly ran an old cell server while the board showed it as current. Failure here never
//! blocks a start: an out-of-date cell is worth more than no cell, and every such fallback is logged with the reason, because silence is how the drift lasted that long.

use crate::http_client::HttpClient;
use crate::log::Log;
use net::Sha256;
use rules::Coerce;
use serde_json::{Map, Value};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::Duration;
use wire::Percent;

/// One sync.
pub struct CellAssets<'a> {
    /// The controller's address.
    pub controller: String,
    /// The fields its requests carry.
    pub fields: Vec<(&'static str, String)>,
    /// Where the files go.
    pub home: PathBuf,
    /// How to ask.
    pub http: &'a HttpClient,
}

impl CellAssets<'_> {
    const TIMEOUT: Duration = Duration::from_secs(10);
    /// Launcher stem, the runner the controller's manifest uses: a LAST RESORT, only when the manifest does not say. A hardcoded copy once bit us: `transcribe` shipped on the controller and was never added here, and the client ran
    /// whatever a human had once copied in, for four days, with a green board.
    const LAUNCHER_RUNNER: [(&'static str, &'static str); 4] =
        [("moonshine", "moonshine"), ("whisper", "whisper"), ("tts", "custom"), ("transcribe", "transcribe")];

    /// `run_<stem>.sh` as a command line names it: the stem, "" when it names no launcher of ours.
    pub fn launcher_stem(command: &str) -> String {
        let is_word = |letter: char| letter.is_alphanumeric() || letter == '_';
        let mut searched = 0;
        while let Some(found) = command.get(searched..).and_then(|rest| rest.find("run_")) {
            let at = searched + found;
            searched = at + 4;
            // absent-ok: the search stands at a letter's start, so both halves read.
            let (before, tail) = command.split_at(at);
            if before.chars().next_back().is_some_and(is_word) {
                continue;
            }
            // absent-ok: `run_` was found here.
            let rest = tail.strip_prefix("run_").unwrap_or_default();
            let length = rest
                .find(|letter: char| !(letter.is_ascii_lowercase() || letter.is_ascii_digit() || letter == '_'))
                .unwrap_or(rest.len());
            let (stem, after) = rest.split_at(length);
            let ends = after.strip_prefix(".sh").is_some_and(|past| !past.chars().next().is_some_and(is_word));
            if !stem.is_empty() && ends {
                return stem.to_string();
            }
        }
        String::new()
    }

    /// Which runner owns `run_<stem>.sh`, according to the controller itself.
    fn runner_from_manifest(stem: &str, manifest: &Value) -> Option<String> {
        let launcher = format!("run_{stem}.sh");
        let runners = manifest.get("runners")?.as_object()?;
        runners
            .iter()
            .find(|(_, names)| {
                names.as_array().is_some_and(|names| names.iter().any(|name| name.as_str() == Some(launcher.as_str())))
            })
            .map(|(runner, _)| runner.clone())
    }

    fn digest(path: &Path) -> String {
        // absent-ok: a file that does not read has no digest, and is fetched.
        fs::read(path).map_or_else(|_| String::new(), |bytes| Sha256::of(&bytes))
    }

    /// Brings `$HOME`'s copies of this command's cell files up to the controller's: `{name: "current"|"updated"|"kept: <why>"}`. Never fails.
    pub fn sync(&self, command: &str) -> Map<String, Value> {
        let mut out = Map::new();
        let stem = Self::launcher_stem(command);
        if stem.is_empty() {
            return out;
        }
        let base = self.controller.trim_end_matches('/');
        if base.is_empty() {
            Log::line("[llama-node] cell-assets: no controllerUrl — keeping local copies");
            return out;
        }
        let manifest = match self.http.json("GET", &format!("{base}/api/cell-assets"), &self.fields, &[], Self::TIMEOUT) {
            Ok(manifest) => manifest,
            Err(error) => {
                Log::line(&format!("[llama-node] cell-assets: manifest unavailable ({error}) — keeping local copies"));
                return out;
            }
        };
        // The controller is the side that gains runners: asked first, before the table above.
        let by_table = || Self::LAUNCHER_RUNNER.iter().find(|(said, _)| *said == stem).map(|(_, runner)| (*runner).to_string());
        let Some(runner) = Self::runner_from_manifest(&stem, &manifest).or_else(by_table) else {
            Log::line(&format!(
                "[llama-node] cell-assets: run_{stem}.sh belongs to no runner the controller publishes — keeping local copies (upgrade the controller, or this cell runs whatever is already in $HOME)"
            ));
            return out;
        };
        let wanted = manifest.get("runners").and_then(|runners| runners.get(&runner)).and_then(Value::as_array).cloned();
        for name in wanted.into_iter().flatten().filter_map(|name| name.as_str().map(str::to_string)) {
            let said = manifest.get("assets").and_then(|assets| assets.get(&name));
            let word = self.brought(base, &name, said);
            out.insert(name, Value::String(word));
        }
        out
    }

    fn brought(&self, base: &str, name: &str, said: Option<&Value>) -> String {
        let want = said
            .and_then(|said| said.get("sha256"))
            .filter(|hash| Coerce::truthy(Some(*hash)))
            .map_or_else(String::new, |hash| Coerce::text(Some(hash)));
        let target = self.home.join(name);
        if !want.is_empty() && Self::digest(&target) == want {
            return "current".to_string();
        }
        match self.fetched(base, name, &want, said, &target) {
            Ok(word) => word,
            Err(error) => {
                Log::line(&format!("[llama-node] cell-assets: {name} not fetched ({error}) — keeping local copy"));
                format!("kept: {error}")
            }
        }
    }

    fn fetched(&self, base: &str, name: &str, want: &str, said: Option<&Value>, target: &Path) -> Result<String, String> {
        const MOST: u64 = 256 << 20;
        let url = format!("{base}/api/cell-assets/file?name={}", Percent::encode_path(name));
        let answer = self.http.ask("GET", &url, &self.fields, &[], Self::TIMEOUT).map_err(|error| error.to_string())?;
        let payload = answer.text(MOST).map_err(|error| error.to_string())?;
        if !want.is_empty() && Sha256::of(&payload) != want {
            // A truncated body would otherwise overwrite a working launcher with rubbish.
            Log::line(&format!("[llama-node] cell-assets: {name} arrived with the wrong hash — keeping local copy"));
            return Ok("kept: hash mismatch".to_string());
        }
        let temporary = target.with_file_name(format!("{name}.new"));
        fs::write(&temporary, payload).map_err(|error| error.to_string())?;
        if name.ends_with(".sh") || said.is_some_and(|said| Coerce::truthy(said.get("executable"))) {
            fs::set_permissions(&temporary, fs::Permissions::from_mode(0o755)).map_err(|error| error.to_string())?;
        }
        // Atomic: never a half-written launcher.
        fs::rename(&temporary, target).map_err(|error| error.to_string())?;
        Log::line(&format!("[llama-node] cell-assets: {name} updated from controller"));
        Ok("updated".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_launcher_is_found_by_its_whole_name() {
        assert_eq!(CellAssets::launcher_stem("bash $HOME/run_moonshine.sh \"$PORT\" en"), "moonshine");
        assert_eq!(CellAssets::launcher_stem("python3 ~/run_tts_2.sh"), "tts_2");
        assert_eq!(CellAssets::launcher_stem("xrun_whisper.sh"), "");
        assert_eq!(CellAssets::launcher_stem("run_whisper.shell"), "");
        assert_eq!(CellAssets::launcher_stem("run_Upper.sh run_b.sh"), "b");
        assert_eq!(CellAssets::launcher_stem("python3 server.py"), "");
    }

    #[test]
    fn the_manifest_is_asked_before_the_table() {
        let manifest = serde_json::json!({"runners": {"strata": ["run_strata.sh", "other.py"], "x": []}});
        assert_eq!(CellAssets::runner_from_manifest("strata", &manifest).as_deref(), Some("strata"));
        assert_eq!(CellAssets::runner_from_manifest("whisper", &manifest), None);
    }
}
