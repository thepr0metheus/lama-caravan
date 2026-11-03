//! What the cells run on: the `llama.cpp` build, the vLLM venv, the PrismML runtime, and the long job that changes them.

pub mod builds;
pub mod job;
pub mod prism;
mod prism_archive;
pub mod vllm;

pub use job::BackgroundJob;
