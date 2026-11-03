//! The proxy's start: its settings from the environment, then the listener.

use proxy::config::ProxyConfig;
use proxy::listener::Listener;
use proxy::log::Log;
use proxy::places::PlacesWatch;
use proxy::pool_watch::PoolWatch;
use proxy::proxy::Proxy;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;

fn main() -> ExitCode {
    let config = match ProxyConfig::from_lookup(|name| std::env::var(name).ok()) {
        Ok(config) => ProxyConfig { program: std::env::args_os().next().map(PathBuf::from), ..config },
        Err(words) => {
            Log::line(&format!("caravan-proxy: {words}"));
            return ExitCode::from(2);
        }
    };
    let proxy = Arc::new(Proxy::new(config));
    match Listener::bind(Arc::clone(&proxy)) {
        Ok(listener) => {
            proxy.start_state_writer();
            PoolWatch::start(&proxy);
            PlacesWatch::start(&proxy);
            listener.serve()
        }
        Err(words) => {
            Log::line(&format!("caravan-proxy: {words}"));
            ExitCode::from(1)
        }
    }
}
