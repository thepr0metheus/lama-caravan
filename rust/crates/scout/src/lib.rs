//! The scout of one machine. What it answers is kept in `tests/frozen`, by its table of paths (`routes.json`); how it is written: `docs/rust-code.md`.

pub mod api;
pub mod cells;
pub use plumbing::commands;
pub mod config;
pub mod driver;
pub mod driver_packages;
pub mod engines;
pub mod entry;
pub mod errors;
pub mod heartbeat;
pub use plumbing::http_client;
pub mod identity;
pub use plumbing::log;
pub mod machine;
pub mod models;
pub mod own_release;
pub mod paths;
pub mod process;
pub mod report;
pub mod runtimes;
pub mod saved_configs;
pub mod scout;
pub mod starts;
pub mod state;
pub mod telemetry;
#[cfg(test)]
mod tests;
pub use plumbing::ticking;
