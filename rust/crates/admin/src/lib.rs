//! The controller: its documents, its fleet and the board's server. What it answers is kept in `tests/frozen` and compared from outside (`scripts/test_rust_admin_conformance.py`); how it is written: `docs/rust-code.md`.

#![recursion_limit = "512"]

pub mod app;
pub mod benchmarks;
pub mod board_layout;
pub mod cloud;
pub mod common;
pub mod config;
pub mod data_tree;
pub mod domain;
pub mod fleet;
pub mod metrics;
pub mod models;
pub mod monitoring;
pub mod packages;
pub mod paths;
pub mod proxies;
pub mod routes;
pub mod settings;
pub mod startup;
pub mod status;
pub mod store;
#[cfg(test)]
mod tests;
pub mod topology;
pub mod web;

/// The controller's version: the board shows it.
pub const VERSION: &str = "2.0.0";
