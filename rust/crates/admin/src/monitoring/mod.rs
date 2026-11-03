//! The local system monitor. The controller's own machine is read through its scout; `/proc` is what the controller's process itself sees.

pub mod activity;
pub mod incidents;
pub mod machine;
pub mod sampler;

pub use machine::MachineState;
pub use sampler::{MonitorMemory, MonitorSampler};
