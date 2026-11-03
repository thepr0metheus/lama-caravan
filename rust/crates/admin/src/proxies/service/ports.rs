//! Who listens on which port, from the kernel's tables.

use super::*;

/// Which local TCP ports are listening, and whose, from the kernel's own table.
pub struct ListeningPorts {
    pub(super) proc_root: PathBuf,
    pub(super) inodes: BTreeMap<i64, BTreeSet<String>>,
    /// Whether the table was there at all: on a system with no /proc nothing is known.
    pub known: bool,
}

impl ListeningPorts {
    pub(super) const LISTEN: &'static str = "0A";

    /// Read once.
    pub fn read() -> Self {
        Self::of(Path::new("/proc"))
    }

    /// Read from another root: a test's.
    pub fn of(proc_root: &Path) -> Self {
        let (mut inodes, mut known): (BTreeMap<i64, BTreeSet<String>>, bool) = (BTreeMap::new(), false);
        for table in ["tcp", "tcp6"] {
            let Ok(text) = std::fs::read_to_string(proc_root.join("net").join(table)) else {
                continue;
            };
            known = true;
            for row in text.lines().skip(1) {
                let fields: Vec<&str> = row.split_whitespace().collect();
                if fields.get(3).copied() != Some(Self::LISTEN) {
                    continue;
                }
                let port = fields
                    .get(1)
                    .and_then(|address| address.rsplit(':').next())
                    .and_then(|hex| i64::from_str_radix(hex, 16).ok());
                if let (Some(port), Some(inode)) = (port, fields.get(9)) {
                    inodes.entry(port).or_default().insert((*inode).to_string());
                }
            }
        }
        Self { proc_root: proc_root.to_path_buf(), inodes, known }
    }

    /// Whether something listens on `port`.
    pub fn busy(&self, port: i64) -> bool {
        self.inodes.contains_key(&port)
    }

    /// Every port something listens on.
    pub fn ports(&self) -> Vec<i64> {
        self.inodes.keys().copied().collect()
    }

    pub(super) fn owner_map(&self) -> BTreeMap<String, (i64, String)> {
        let mut owners = BTreeMap::new();
        for entry in std::fs::read_dir(&self.proc_root).into_iter().flatten().flatten() {
            let Some(pid) = entry.file_name().to_str().and_then(|name| name.parse::<i64>().ok()) else {
                continue;
            };
            let Ok(comm) = std::fs::read_to_string(entry.path().join("comm")) else {
                continue;
            };
            for fd in std::fs::read_dir(entry.path().join("fd")).into_iter().flatten().flatten() {
                let Ok(target) = std::fs::read_link(fd.path()) else {
                    continue;
                };
                let target = target.to_string_lossy();
                if let Some(inode) = target.strip_prefix("socket:[").and_then(|rest| rest.strip_suffix(']')) {
                    owners.entry(inode.to_string()).or_insert_with(|| (pid, Coerce::strip(&comm).to_string()));
                }
            }
        }
        owners
    }

    /// (pid, command) of whoever listens; (0, "?") when something does and its owner cannot be told, (0, "") when nothing does.
    pub fn owner(&self, port: i64) -> (i64, String) {
        let Some(inodes) = self.inodes.get(&port).filter(|inodes| !inodes.is_empty()) else {
            return (0, String::new());
        };
        let owners = self.owner_map();
        inodes.iter().find_map(|inode| owners.get(inode).cloned()).unwrap_or_else(|| (0, "?".to_string()))
    }
}
