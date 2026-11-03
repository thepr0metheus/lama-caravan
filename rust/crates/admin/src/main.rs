//! The controller's start.

use admin::app::{App, Outside};
use admin::common::zone::ContainerPreflight;
use admin::models::store_probe::{StoreProbe, StoreProbeChild};
use admin::paths::{AdminPaths, Environment};
use admin::routes::AllRoutes;
use admin::startup::Startup;
use admin::web::server::AdminServer;
use os::clock::{Clock, SystemClock};
use plumbing::{Log, SystemCommands};
use rules::PythonJson;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;
use std::time::Duration;

/// The program.
struct Program;

impl Program {
    /// The container's check of itself: the image has no other tool to ask with.
    const HEALTH_FLAG: &'static str = "--health";

    fn health() -> ExitCode {
        let port = std::env::var("LLAMACPP_ADMIN_PORT").unwrap_or_else(|_| "7990".to_string());
        let asked = TcpStream::connect(format!("127.0.0.1:{port}")).and_then(|mut socket| {
            socket.set_read_timeout(Some(Duration::from_secs(5)))?;
            socket.write_all(b"GET /healthz HTTP/1.0\r\n\r\n")?;
            let mut said = [0u8; 16];
            let count = socket.read(&mut said)?;
            Ok(String::from_utf8_lossy(said.get(..count).unwrap_or_default()).contains(" 200"))
        });
        if asked.is_ok_and(|fine| fine) { ExitCode::SUCCESS } else { ExitCode::FAILURE }
    }

    /// Where the board's files are: beside the program's folder in an image, `CARAVAN_ROOT` when it says otherwise.
    fn project_root(env: &Environment) -> PathBuf {
        if let Some(said) = env.get("CARAVAN_ROOT") {
            return PathBuf::from(said);
        }
        // absent-ok: a program that cannot say where it is looks from where it stands.
        let exe = std::env::current_exe().unwrap_or_default();
        let above = exe.parent().and_then(|folder| folder.parent()).map(PathBuf::from);
        above.filter(|folder| folder.join("static").is_dir()).unwrap_or_else(|| PathBuf::from("."))
    }

    /// A look inside a store, as a process of its own: one line on the standard output, and the end.
    fn store_probe_child(args: &[String]) -> ExitCode {
        let word = |at: usize| args.get(at).map_or("", String::as_str);
        let now = SystemClock::new().epoch().trunc() as i64;
        let said = StoreProbeChild::answer(word(2), word(3), word(4), now);
        Log::out(&PythonJson::spaced(&said));
        ExitCode::SUCCESS
    }

    fn run() -> Result<(), String> {
        let env = Environment::of_process();
        let in_container = ContainerPreflight::in_container(env.get("CARAVAN_CONTAINER"));
        // absent-ok: a variable not set is what the check says.
        let found = ContainerPreflight::problems(
            in_container,
            // absent-ok: a variable not set is what the check says.
            env.get("TZ").unwrap_or_default(),
            // absent-ok: a variable not set is what the check says.
            env.get("LLAMA_TOPOLOGY_SERVER_IP").unwrap_or_default(),
        );
        if !found.is_empty() {
            return Err(format!(
                "lama-caravan: will not start in a container without these settings:\n  - {}",
                found.join("\n  - ")
            ));
        }
        let paths = AdminPaths::from_env(&env, Self::project_root(&env), in_container)?;
        paths.check_port_ranges()?;
        let address = format!("{}:{}", paths.host, paths.port);
        let outside = Outside { clock: Arc::new(SystemClock::new()), commands: Arc::new(SystemCommands), env };
        let app = App::new(paths, outside).map_err(|error| error.to_string())?;
        let routes = AllRoutes::table()?;
        Startup::of(&app).run()?;
        let listener = TcpListener::bind(&address).map_err(|error| format!("{address}: {error}"))?;
        Log::line(&format!("lama-caravan listening on http://{address}"));
        AdminServer::new(app, routes).serve(&listener)
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some(StoreProbe::CHILD_FLAG) {
        return Program::store_probe_child(&args);
    }
    if args.get(1).map(String::as_str) == Some(Program::HEALTH_FLAG) {
        return Program::health();
    }
    match Program::run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(words) => {
            Log::line(&words);
            ExitCode::from(2)
        }
    }
}
