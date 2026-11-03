//! The board's server.

pub mod access;
pub mod exchange;
pub mod gzip;
pub mod parsed;
pub mod server;
pub mod table;

pub use exchange::Exchange;
pub use parsed::Parsed;
pub use table::{RouteTable, Routes};
