//! A process on this machine that the scout did not start: found by the command line it runs, or by the port it listens on. This is how a cell outlives
//! a scout restart: the registry remembers a pid and a marker, and these questions check that memory against the host. Each is one question to the OS; none of them keeps anything.

use crate::commands::Commands;
use crate::machine::Listeners;
use os::{Cpu, Signals};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

/// The group of processes a cell's own scope holds. systemd made it for this one cell, so what stands in it is the cell's, whatever it did to itself: vLLM's engine takes the name `VLLM::EngineCore`
/// over its environment, and the mark goes with it. Stopped while it loaded, the server went, and the engine read on and kept 6 GB of the card with nobody knowing it (2026-11-03).
pub struct CellScope {
    procs: PathBuf,
}

impl CellScope {
    /// The processes in it now.
    pub fn pids(&self) -> Vec<i64> {
        // absent-ok: a scope gone with its last process holds nothing.
        let said = fs::read_to_string(&self.procs).unwrap_or_default();
        said.split_whitespace().filter_map(|word| word.parse().ok()).collect()
    }
}

/// The questions.
pub struct HostProcesses {
    proc_root: PathBuf,
    groups_root: PathBuf,
    commands: Arc<dyn Commands>,
    home: String,
}

impl HostProcesses {
    /// Every cell this scout starts carries it in its environment, and keeps it through `bash -lc … exec python`. A process without it was not started by a scout: it is never adopted
    /// and never killed.
    pub const CELL_ENV: &'static str = "CARAVAN_SCOUT_CELL";
    /// Beside it, whose: the folder of the scout that started it. A machine may hold another scout, a test's or one being replaced, and a scout that took its cells for its own kept them on its
    /// board as crashed the moment the other let them go (2026-11-03).
    pub const HOME_ENV: &'static str = "CARAVAN_SCOUT_HOME";
    /// How many processes a cell's tree may name: a runaway fork is not walked.
    const TREE_LIMIT: usize = 64;
    const QUICK: Duration = Duration::from_secs(5);

    /// The questions on this machine.
    pub fn new(proc_root: PathBuf, commands: Arc<dyn Commands>) -> Self {
        Self { proc_root, groups_root: PathBuf::from("/sys/fs/cgroup"), commands, home: String::new() }
    }

    /// The same with the groups of processes under this folder: a test's.
    #[cfg(test)]
    pub fn groups_under(self, groups_root: PathBuf) -> Self {
        Self { groups_root, ..self }
    }

    /// The same, for the scout of this folder: what another's started is not its own.
    pub fn of_scout(self, home: &Path) -> Self {
        Self { home: home.display().to_string(), ..self }
    }

    fn of(&self, pid: i64, file: &str) -> PathBuf {
        self.proc_root.join(pid.to_string()).join(file)
    }

    /// Whether a scout started `pid`; `None` when the machine will not say: then it counts as not ours for anything that kills.
    pub fn owned(&self, pid: i64) -> Option<bool> {
        if pid <= 1 {
            return None;
        }
        if self.proc_root.is_dir() {
            return match fs::read(self.of(pid, "environ")) {
                Ok(raw) => Some(Self::variable_in(&raw).is_some()),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Some(false),
                Err(_) => None,
            };
        }
        // macOS: `ps -E` adds the environment to the command.
        let ran = self.commands.run(&["ps", "-E", "-ww", "-p", &pid.to_string(), "-o", "command="], Self::QUICK).ok()?;
        if !ran.ok() || ran.stdout.trim().is_empty() {
            return None;
        }
        Some(ran.stdout.contains(&format!(" {}=", Self::CELL_ENV)))
    }

    fn variable_in(raw: &[u8]) -> Option<&[u8]> {
        Self::value_in(raw, Self::CELL_ENV)
    }

    fn value_in<'raw>(raw: &'raw [u8], name: &str) -> Option<&'raw [u8]> {
        let prefix = format!("{name}=");
        raw.split(|byte| *byte == 0).find_map(|item| item.strip_prefix(prefix.as_bytes()))
    }

    /// The group `pid` stands in, as the system names it.
    fn group_of(&self, pid: i64) -> Option<String> {
        let said = fs::read_to_string(self.of(pid, "cgroup")).ok()?;
        said.lines().find_map(|line| line.strip_prefix("0::")).map(|path| path.trim().to_string())
    }

    /// The scope `pid` runs in, when it is one made for a command alone, as a cell's is. `None` for any other group, whose processes are not the cell's to lose: a cell with no limits stands in
    /// this scout's own group, a service's or a login's.
    pub fn scope_of(&self, pid: i64) -> Option<CellScope> {
        let group = self.group_of(pid)?;
        let name = group.rsplit('/').next()?;
        let made_alone = name.starts_with("run-") && name.ends_with(".scope");
        let mine = self.group_of(i64::from(std::process::id()));
        (made_alone && mine.as_deref() != Some(group.as_str()))
            .then(|| CellScope { procs: self.groups_root.join(group.trim_start_matches('/')).join("cgroup.procs") })
    }

    /// The port this scout started `pid` for, or 0: a cell of no word on whose was started before scouts said it. This, not the command line, is how a cell is known again: a launcher is often an `exec` chain, each link rewriting argv, while the
    /// environment is kept through every exec and every child.
    pub fn port_of(&self, pid: i64) -> i64 {
        let Ok(raw) = fs::read(self.of(pid, "environ")) else {
            return 0;
        };
        if Self::value_in(&raw, Self::HOME_ENV).is_some_and(|home| home != self.home.as_bytes()) {
            return 0;
        }
        // absent-ok: no mark, or a mark that is no number, is 0: this function's word for "not a scout's".
        Self::variable_in(&raw).and_then(|value| std::str::from_utf8(value).ok()?.parse().ok()).unwrap_or(0)
    }

    /// The fields of `/proc/<pid>/stat` after its name, which may hold anything.
    fn stat_fields(&self, pid: i64) -> Option<Vec<String>> {
        let raw = fs::read(self.of(pid, "stat")).ok()?;
        let text = String::from_utf8_lossy(&raw);
        let (_, after) = text.rsplit_once(')')?;
        Some(after.split_whitespace().map(str::to_string).collect())
    }

    fn parent_of(&self, pid: i64) -> i64 {
        // absent-ok: a process gone between two reads has no parent to say: 0 is no pid.
        self.stat_fields(pid).and_then(|fields| fields.get(1)?.parse().ok()).unwrap_or(0)
    }

    /// The cells of this machine a scout started, by the mark their processes carry: port to the pids at the root of the cell's tree. A cell is a tree, and its root is the one whose
    /// parent does not carry it. Nothing where `/proc` does not say.
    pub fn tagged_cells(&self) -> BTreeMap<i64, Vec<i64>> {
        let me = i64::from(std::process::id());
        let Ok(entries) = fs::read_dir(&self.proc_root) else {
            return BTreeMap::new();
        };
        let mut trees: BTreeMap<i64, BTreeMap<i64, i64>> = BTreeMap::new();
        for pid in entries.flatten().filter_map(|entry| entry.file_name().to_str()?.parse::<i64>().ok()) {
            let port = if pid == me { 0 } else { self.port_of(pid) };
            if port != 0 {
                trees.entry(port).or_default().insert(pid, self.parent_of(pid));
            }
        }
        trees
            .into_iter()
            .map(|(port, tree)| {
                let roots: Vec<i64> = tree.iter().filter(|(_, parent)| !tree.contains_key(parent)).map(|(pid, _)| *pid).collect();
                (port, roots)
            })
            .collect()
    }

    /// When `pid` started, in epoch seconds; 0 when `/proc` does not say: a cell found again without a record is then as old as its adoption.
    pub fn started_at(&self, pid: i64) -> i64 {
        let ticks = self.stat_fields(pid).and_then(|fields| fields.get(19)?.parse::<i64>().ok());
        let booted = fs::read_to_string(self.proc_root.join("stat"))
            .ok()
            .and_then(|text| text.lines().find_map(|line| line.strip_prefix("btime ")?.trim().parse::<i64>().ok()));
        match (ticks, booted, Cpu::clock_ticks()) {
            (Some(ticks), Some(booted), Some(per_second)) => booted + ticks / per_second,
            _ => 0,
        }
    }

    /// The process a scout started for `port` that still runs, listening or not yet: a cell loading its model does not listen for a minute and more. `prefer` when it is one of them,
    /// else the first root; 0 when no process carries the mark of that port.
    pub fn carrier(&self, port: i64, prefer: i64) -> i64 {
        if prefer > 1 && self.port_of(prefer) == port {
            return prefer;
        }
        // absent-ok: 0 is this function's word for no process.
        self.tagged_cells().get(&port).and_then(|roots| roots.first().copied()).unwrap_or(0)
    }

    /// The processes `pid` started, and theirs: a cell's server can hand the card to a child, and the card's memory is then the child's.
    pub fn descendants(&self, pid: i64) -> Vec<i64> {
        if pid <= 1 {
            return Vec::new();
        }
        let mut found: Vec<i64> = Vec::new();
        let mut todo = vec![pid];
        while let Some(parent) = (!todo.is_empty() && found.len() < Self::TREE_LIMIT).then(|| todo.remove(0)) {
            let Ok(tasks) = fs::read_dir(self.of(parent, "task")) else {
                continue;
            };
            let mut children: Vec<PathBuf> = tasks.flatten().map(|task| task.path().join("children")).collect();
            children.sort();
            for file in children {
                let Ok(text) = fs::read_to_string(file) else {
                    continue;
                };
                for kid in text.split_whitespace().filter_map(|word| word.parse::<i64>().ok()) {
                    if kid != pid && !found.contains(&kid) && found.len() < Self::TREE_LIMIT {
                        found.push(kid);
                        todo.push(kid);
                    }
                }
            }
        }
        found
    }

    /// What the processes have read so far, in bytes: for each, the larger of what it read by calls (`rchar`) and of what it fetched from storage (`read_bytes`: the pages of a mapped
    /// model count only here). `None` where `/proc` says nothing.
    pub fn bytes_read(&self, pids: &[i64]) -> Option<i64> {
        let mut total = None;
        for pid in pids {
            let Ok(text) = fs::read_to_string(self.of(*pid, "io")) else {
                continue;
            };
            let counts = text.lines().filter_map(|line| {
                let (key, value) = line.split_once(':')?;
                matches!(key, "rchar" | "read_bytes").then(|| value.trim().parse::<i64>().ok()).flatten()
            });
            if let Some(most) = counts.max() {
                // absent-ok: the first count starts the sum.
                total = Some(total.unwrap_or(0) + most);
            }
        }
        total
    }

    /// The memory a cell's processes hold in RAM, in bytes: the RSS of `pid` and of everything it started, from one `ps` table. `None` when there is no table or it does not hold the
    /// process: "not told" is not "nothing".
    pub fn resident(pid: i64, table: Option<&BTreeMap<i64, Value>>) -> Option<i64> {
        let table = table.filter(|table| table.contains_key(&pid))?;
        let mut children: BTreeMap<i64, Vec<i64>> = BTreeMap::new();
        for (child, row) in table {
            // absent-ok: a row of no parent hangs from no process.
            children.entry(row.get("ppid").and_then(Value::as_i64).unwrap_or(0)).or_default().push(*child);
        }
        let mut found = BTreeSet::new();
        let mut todo = vec![pid];
        while let Some(current) = (!todo.is_empty() && found.len() < Self::TREE_LIMIT + 1).then(|| todo.remove(0)) {
            if found.insert(current) {
                todo.extend(children.get(&current).into_iter().flatten().copied());
            }
        }
        // absent-ok: a process the table holds with no figure holds nothing that was told.
        let kib: i64 = found.iter().filter_map(|member| table.get(member)?.get("rssKb")?.as_i64()).sum();
        Some(kib * 1024)
    }

    /// The exec'd argv[0] may be a resolved binary path, so besides the exact substring also accept the marker's argument tail.
    pub fn marker_matches(marker: &str, command_line: &str) -> bool {
        if marker.is_empty() || command_line.is_empty() {
            return false;
        }
        if command_line.contains(marker) {
            return true;
        }
        let tail: Vec<&str> = marker.split_whitespace().skip(1).collect();
        !tail.is_empty() && command_line.contains(&tail.join(" "))
    }

    /// The command line of `pid`; "" when it is gone.
    pub fn command_line(&self, pid: i64) -> String {
        let asked = self.commands.run(&["ps", "-p", &pid.to_string(), "-o", "command="], Self::QUICK);
        asked.map_or_else(|_| String::new(), |ran| ran.stdout.trim().to_string())
    }

    /// The pid listening on `port`, by any address; 0 if none. Lets a cell be known by its port when the marker no longer matches.
    pub fn listener(&self, port: i64) -> i64 {
        Listeners::owner_of(self.commands.as_ref(), port)
    }

    /// Whether a process still runs: a signal of nothing tells. One that is another user's still runs.
    pub fn alive(pid: i64) -> bool {
        Signals::alive(pid)
    }
}
