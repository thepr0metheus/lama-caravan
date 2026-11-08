//! Where a cell listens, and the one way to it from outside its machine. Since step 7 of the owner's plan (Papyrus
//! `caravan-scout-port-lease`, 2026-11-08) a cell listens on its machine's loopback alone, and a machine shows the network one port
//! of the caravan, its scout's. A client reaches a model through the machine's entry (`/v1`); the controller reaches one cell —
//! its health, its `/props`, a question of the Talk tab, a live talk's WebSocket — through the scout's door, which hands the
//! request to the cell on the loopback as it came.
//!
//! Both programs read this: the controller writes the address into a cell's command and the door's path into its requests, the
//! scout dials the address and answers the path. Until then each kept its own words for both, and a cell listened on every
//! address: the controller asked it straight over the network, and only the firewall kept others out.

use crate::cell_id::CellId;

/// The rule.
pub struct CellDoor;

impl CellDoor {
    /// The address every cell listens on: its machine's loopback.
    pub const LISTEN: &'static str = "127.0.0.1";
    /// What the scout's path to a cell starts with: `<PREFIX><the cell's name><the cell's own path>`.
    pub const PREFIX: &'static str = "/api/cell/";

    /// The scout's path to `path` of the cell named `cell`. `path` is the cell's own, from its `/`, the query and all.
    pub fn path(cell: &str, path: &str) -> String {
        let path = if path.starts_with('/') { path.to_string() } else { format!("/{path}") };
        format!("{}{cell}{path}", Self::PREFIX)
    }

    /// `(the cell's name, the cell's own path)` of a scout's path; `None` for a path that is no door's or names no cell. A door
    /// with nothing after the name leads to the cell's `/`.
    pub fn read(target: &str) -> Option<(String, String)> {
        let rest = target.strip_prefix(Self::PREFIX)?;
        let cut = rest.find(['/', '?']).unwrap_or(rest.len());
        let (name, path) = rest.split_at(cut);
        // A name only: a port of before, which `CellId::read` would take for that cell's name, is no way into a cell of now.
        let cell = Some(name).filter(|name| CellId::is_name(name))?.to_string();
        let path = match path.chars().next() {
            None => "/".to_string(),
            Some('?') => format!("/{path}"),
            Some(_) => path.to_string(),
        };
        Some((cell, path))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_door_names_its_cell_and_the_cell_s_own_path() {
        assert_eq!(CellDoor::path("c22035", "/health"), "/api/cell/c22035/health");
        assert_eq!(CellDoor::path("c1a2b3c4d", "v1/chat/completions"), "/api/cell/c1a2b3c4d/v1/chat/completions");
        for (target, cell, path) in [
            ("/api/cell/c22035/health", "c22035", "/health"),
            ("/api/cell/c1a2b3c4d/v1/audio/speech?x=1", "c1a2b3c4d", "/v1/audio/speech?x=1"),
            ("/api/cell/c22035", "c22035", "/"),
            ("/api/cell/c22035?lines=3", "c22035", "/?lines=3"),
        ] {
            assert_eq!(CellDoor::read(target), Some((cell.to_string(), path.to_string())), "{target}");
        }
    }

    #[test]
    fn a_door_with_no_cell_s_name_is_none() {
        for target in [
            "/api/cell/",
            "/api/cell/22035/health",
            "/api/cell/C22035/health",
            "/api/cell/c/health",
            "/api/cells/c22035",
            "/v1/models",
        ] {
            assert_eq!(CellDoor::read(target), None, "negative: {target} — a port, a wrong case, an empty name or another path");
        }
    }

    #[test]
    fn a_path_written_is_read_back() {
        for (cell, path) in [("c22001", "/props"), ("c0f0f0f0f", "/backend"), ("c22001", "/")] {
            assert_eq!(CellDoor::read(&CellDoor::path(cell, path)), Some((cell.to_string(), path.to_string())));
        }
    }
}
