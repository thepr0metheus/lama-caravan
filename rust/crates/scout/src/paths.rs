//! Where the scout's things lie on this machine.

use std::path::PathBuf;

/// The places a run of the scout reads and writes outside its state.
#[derive(Debug, Clone)]
pub struct ScoutPaths {
    /// The scout's own folder: `scripts/` lies in it. `CARAVAN_SCOUT_ROOT`, else where it runs: the unit's working directory.
    pub root: PathBuf,
    /// What a cell leaves next to itself: `LAMA_CARAVAN_SERVER_CELLS_DIR`, else `var/server-cells` of the root.
    pub server_cells: PathBuf,
    /// The kernel's process table.
    pub proc_root: PathBuf,
    /// The kernel's word on the memory.
    pub meminfo: PathBuf,
    /// The home of the scout's user.
    pub home: PathBuf,
}

impl ScoutPaths {
    /// The places this environment says.
    pub fn from_environment() -> Self {
        let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let root = std::env::var_os("CARAVAN_SCOUT_ROOT").map_or(cwd, PathBuf::from);
        let home = std::env::var_os("HOME").map_or_else(|| PathBuf::from("/"), PathBuf::from);
        let server_cells = std::env::var("LAMA_CARAVAN_SERVER_CELLS_DIR").map_or_else(
            |_| root.join("var/server-cells"),
            |said| match said.strip_prefix("~/") {
                Some(rest) => home.join(rest),
                None => PathBuf::from(said),
            },
        );
        Self { root, server_cells, proc_root: PathBuf::from("/proc"), meminfo: PathBuf::from("/proc/meminfo"), home }
    }
}
