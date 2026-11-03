//! What a router output's upstream is.

use crate::coerce::Coerce;
use serde_json::Value;

/// The kinds of upstream a router output names. A type outside this table is read as `Llama`, as the file has always
/// been.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpstreamType {
    /// A cell: one model on its own port.
    Llama,
    /// A model of an engine next to the cells: many models on the engine's port.
    Engine,
    /// A model of a machine's entry, its scout: many models on the scout's port.
    Machine,
    /// A pool or an account.
    Cloud,
}

impl UpstreamType {
    /// The type an output says.
    pub fn of(output: &Value) -> Self {
        match Coerce::stripped(output.get("upstreamType")).to_lowercase().as_str() {
            "engine" => Self::Engine,
            "machine" => Self::Machine,
            "cloud" => Self::Cloud,
            _ => Self::Llama,
        }
    }

    /// The word the journal and the board call it.
    pub fn word(self) -> &'static str {
        match self {
            Self::Llama => "llama",
            Self::Engine => "engine",
            Self::Machine => "machine",
            Self::Cloud => "cloud",
        }
    }
}
