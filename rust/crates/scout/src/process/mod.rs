//! A cell's process on this machine and the log it writes: how it is started or adopted, how it stops, and what its log says when it dies.

pub mod cell_process;
mod held;
pub mod host;
mod launcher;
pub mod log;
pub mod scope;
#[cfg(test)]
mod tests;

pub use cell_process::{CellProcess, ProcessParts};
pub use host::{CellScope, HostProcesses};
pub use log::{CellLog, FileTimes, LogPatterns};
pub use scope::MemoryScope;
