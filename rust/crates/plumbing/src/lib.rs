//! What a program of the caravan needs from its machine: asking over HTTP, running a tool, saying words, repeating a pass. The scout and the controller both stand on it: one fact in one place.

pub mod commands;
pub mod http_client;
pub mod log;
pub mod ticking;

pub use commands::{Commands, NoAnswer, Ran, SystemCommands};
pub use http_client::{HttpAnswer, HttpClient, HttpError};
pub use log::{Log, Thousands};
pub use ticking::Ticking;
