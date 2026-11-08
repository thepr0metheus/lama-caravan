//! What a llama cell leaves next to itself under `var/server-cells/<cell id>/`: `start.sh`, the exact command, runnable by hand, and `cell.json`, what it was started with. Both are replaced atomically: a reader of the old file sees it whole.

use crate::models::fetcher::ModelFetcher;
use crate::paths::ScoutPaths;
use rules::{Coerce, ShellWord};
use serde_json::{Map, Value, json};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

/// What a cell was started with, to write down.
pub struct LaunchWords<'a> {
    /// The server.
    pub binary: &'a str,
    /// Its arguments.
    pub args: &'a [String],
    /// The cell's settings.
    pub config: &'a Map<String, Value>,
    /// What this scout made of them.
    pub runtime: &'a Map<String, Value>,
    /// What the server starts with.
    pub environment: &'a Map<String, Value>,
}

/// The artifacts of one scout.
pub struct CellArtifacts<'a> {
    /// Where they lie.
    pub paths: &'a ScoutPaths,
    /// The machine's id.
    pub host_id: String,
    /// The moment.
    pub now: i64,
}

impl CellArtifacts<'_> {
    fn dir_of(&self, cell: &str) -> PathBuf {
        self.paths.server_cells.join(cell)
    }

    /// Writes them for the cell `cell`, whose run holds `port`; what the view shows of them.
    pub fn write(&self, cell: &str, port: i64, launch: &LaunchWords<'_>) -> std::io::Result<Value> {
        let folder = self.dir_of(cell);
        fs::create_dir_all(&folder)?;
        let start_path = folder.join("start.sh");
        let json_path = folder.join("cell.json");
        let mut command = vec![ModelFetcher::expanded(launch.binary).display().to_string()];
        command.extend(launch.args.iter().cloned());
        let exports: String = launch
            .environment
            .iter()
            .map(|(name, value)| format!("export {name}={}\n", ShellWord::quote(&Coerce::text(Some(value)))))
            .collect();
        let quoted: Vec<String> = command.iter().map(|word| ShellWord::quote(word)).collect();
        let script = format!("#!/usr/bin/env bash\nset -euo pipefail\n\n{exports}exec {} \"$@\"\n", quoted.join(" "));
        let temporary = folder.join("start.sh.tmp");
        fs::write(&temporary, script)?;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o755))?;
        fs::rename(&temporary, &start_path)?;
        let payload = json!({
            "hostId": self.host_id,
            "cellId": cell,
            "port": port,
            "config": launch.config,
            "runtime": launch.runtime,
            "cmd": command,
            "env": launch.environment,
            "generatedAt": self.now,
            "startScript": start_path.display().to_string(),
        });
        let text = serde_json::to_string_pretty(&payload).map_err(std::io::Error::other)?;
        let temporary = folder.join("cell.json.tmp");
        fs::write(&temporary, format!("{text}\n"))?;
        fs::rename(&temporary, &json_path)?;
        Ok(json!({
            "dir": folder.display().to_string(),
            "startScript": start_path.display().to_string(),
            "cellJson": json_path.display().to_string(),
            "generatedAt": self.now,
        }))
    }
}
