//! The scout's start.

use os::Host;
use scout::api::server::Api;
use scout::log::Log;
use scout::report::Report;
use scout::scout::Scout;
use std::io::Write as _;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;

/// Where it reads what it is: `--config` and `--state`, else the environment, else the working folder.
struct Arguments {
    config: PathBuf,
    state: PathBuf,
}

impl Arguments {
    fn expanded(path: &str) -> PathBuf {
        match path.strip_prefix("~/") {
            Some(rest) => std::env::var_os("HOME").map_or_else(|| PathBuf::from(path), |home| PathBuf::from(home).join(rest)),
            None => PathBuf::from(path),
        }
    }

    fn from_environment() -> Self {
        let from_env = |names: [&str; 2], otherwise: &str| {
            names.iter().find_map(|name| std::env::var(name).ok()).unwrap_or_else(|| otherwise.to_string())
        };
        let mut config = from_env(["CARAVAN_SCOUT_CONFIG", "LLM_EASY_ROUTE_CONFIG"], "config.json");
        let mut state = from_env(["CARAVAN_SCOUT_STATE", "LLM_EASY_ROUTE_STATE"], "state.json");
        let mut words = std::env::args().skip(1);
        while let Some(word) = words.next() {
            match word.split_once('=') {
                Some(("--config", value)) => config = value.to_string(),
                Some(("--state", value)) => state = value.to_string(),
                _ if word == "--config" => config = words.next().unwrap_or(config),
                _ if word == "--state" => state = words.next().unwrap_or(state),
                _ => {}
            }
        }
        Self { config: Self::expanded(&config), state: Self::expanded(&state) }
    }
}

fn main() -> ExitCode {
    // The installer and an update ask a new program this before anything depends on it.
    if std::env::args().nth(1).as_deref() == Some("--version") {
        let said = writeln!(std::io::stdout(), "caravan-scout {}", Report::VERSION);
        return if said.is_ok() { ExitCode::SUCCESS } else { ExitCode::FAILURE };
    }
    let arguments = Arguments::from_environment();
    let scout = match Scout::new(&arguments.config, &arguments.state) {
        Ok(scout) => Arc::new(scout),
        Err(error) => {
            Log::line(&format!("the scout did not start: {error}"));
            return ExitCode::FAILURE;
        }
    };
    scout.cells.adopt_survivors();
    scout.start_watches();
    let said = |key: &str, otherwise: String| Some(scout.config.text(key)).filter(|word| !word.is_empty()).unwrap_or(otherwise);
    let host = said("listenHost", "0.0.0.0".to_string());
    let port = said("listenPort", "8092".to_string());
    let listener = match TcpListener::bind(format!("{host}:{port}")) {
        Ok(listener) => listener,
        Err(error) => {
            Log::line(&format!("caravan-scout cannot listen on {host}:{port}: {error}"));
            return ExitCode::FAILURE;
        }
    };
    Log::line(&format!("caravan-scout on {} listening on http://{host}:{port}", Host::short_name()));
    match Api::new(Arc::clone(&scout)) {
        Ok(api) => Arc::new(api).serve(&listener),
        Err(error) => {
            Log::line(&format!("the scout did not start: {error}"));
            return ExitCode::FAILURE;
        }
    }
    ExitCode::SUCCESS
}
