//! The launch line of every real cell, unchanged. Each config of `tests/golden/cells` rendered and compared with `commands/<port>.sh` and, for a command cell, with
//! the one line a scout runs, `shell-lines/<port>.txt`.
//!
//! It is deliberately the dumbest possible test: the same input, the same bytes out. When it goes red, either something was lost, or a change was intended, and the
//! files are written again (`CARAVAN_GOLDEN_WRITE=1 cargo test -p admin --test golden`) in a commit of its own that says which cells changed and why. `tests/golden`
//! is a photograph of one operator's fleet and stays out of the public tree: without it there is nothing to compare, and this says so.
// A test may stop where it found something wrong; clippy sees only `#[test]` bodies as tests, not their helpers.
#![allow(clippy::unwrap_used, clippy::panic, clippy::indexing_slicing)]
#![allow(clippy::print_stdout, reason = "nothing compared is said out loud")]

use admin::app::{App, Outside};
use admin::domain::runner::Config;
use admin::fleet::launch::LaunchScript;
use admin::paths::{AdminPaths, Environment};
use os::clock::SystemClock;
use plumbing::SystemCommands;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

/// The same home the files were written under: without it every path differs and the test says everything changed, which is the same as saying nothing.
const HOME: &str = "/home/caravan";

fn golden() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/golden")
}

fn app() -> Arc<App> {
    let data = std::env::temp_dir().join(format!("caravan-golden-{}", std::process::id()));
    let pairs = [
        ("LLAMA_HOME", format!("{HOME}/llama.cpp")),
        ("LLAMA_MODELS_DIR", format!("{HOME}/llama.cpp/models")),
        ("HOME", HOME.to_string()),
        ("CARAVAN_DATA_DIR", data.to_string_lossy().to_string()),
    ];
    let vars: BTreeMap<String, String> = pairs.into_iter().map(|(name, value)| (name.to_string(), value)).collect();
    let env = Environment::of(vars, PathBuf::from(HOME));
    let paths = AdminPaths::from_env(&env, PathBuf::from(env!("CARGO_MANIFEST_DIR")), false).unwrap();
    App::new(paths, Outside { clock: Arc::new(SystemClock::new()), commands: Arc::new(SystemCommands), env }).unwrap()
}

/// `want` against `got`, by the line where they part; `CARAVAN_GOLDEN_WRITE` writes `got` over the file instead.
fn same(path: &PathBuf, got: &str, problems: &mut Vec<String>) {
    if std::env::var_os("CARAVAN_GOLDEN_WRITE").is_some() {
        fs::write(path, got).unwrap();
        return;
    }
    let want = fs::read_to_string(path).unwrap_or_else(|error| panic!("{path:?}: {error}"));
    if want == got {
        return;
    }
    let (kept, said): (Vec<&str>, Vec<&str>) = (want.lines().collect(), got.lines().collect());
    let at = (0..kept.len().max(said.len())).find(|at| kept.get(*at) != said.get(*at)).unwrap_or(0);
    problems.push(format!("{path:?}, line {}:\n  was {:?}\n  now {:?}", at + 1, kept.get(at), said.get(at)));
}

#[test]
fn every_real_cell_starts_with_the_line_it_had() {
    let root = golden();
    let Ok(cells) = fs::read_dir(root.join("cells")) else {
        println!("tests/golden is not here: nothing compared");
        return;
    };
    let app = app();
    let script = LaunchScript::of(&app);
    let mut problems = Vec::new();
    let mut compared = 0;
    for entry in cells {
        let path = entry.unwrap().path();
        let port = path.file_stem().unwrap().to_string_lossy().to_string();
        let config: Config = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        let refused = |words: String| format!("__REFUSED__ {words}");
        let rendered = script.render(&config, None).unwrap_or_else(|error| refused(error.message));
        same(&root.join("commands").join(format!("{port}.sh")), &rendered, &mut problems);
        compared += 1;
        if app.runners.for_config(&config).row().command_path {
            let line = script.command_cell_shell_line(&config).unwrap_or_else(|error| refused(error.message));
            same(&root.join("shell-lines").join(format!("{port}.txt")), &format!("{line}\n"), &mut problems);
            compared += 1;
        }
    }
    assert!(compared > 0, "tests/golden/cells holds no cell");
    assert!(problems.is_empty(), "{} of {compared} differ:\n{}", problems.len(), problems.join("\n"));
}
