//! How loaded this machine is and how much memory it has: `Machine.cpu_ram`.

use crate::commands::Commands;
use os::Cpu;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::time::Duration;

/// `round(value, digits)`: the digits of the exact binary value, as Python's does.
pub struct Rounded;

impl Rounded {
    /// `value` to `digits` places.
    pub fn to(value: f64, digits: usize) -> f64 {
        format!("{value:.digits$}").parse().unwrap_or(value)
    }
}

/// The figures of one look.
pub struct Resources<'a> {
    commands: &'a dyn Commands,
    linux: bool,
}

impl<'a> Resources<'a> {
    const GIB_IN_KIB: f64 = 1024.0 * 1024.0;
    const GIB: f64 = 1024.0 * 1024.0 * 1024.0;

    /// A look through `commands`.
    pub fn new(commands: &'a dyn Commands, linux: bool) -> Self {
        Self { commands, linux }
    }

    /// Core counts for the controller's compute-target picker: `availableCores` is what this process may use, on a core-pinned VM its slice and not the host's total.
    pub fn reading(&self) -> Value {
        let cores = Cpu::count();
        let mut info = Map::new();
        if let Some(load) = Cpu::load_1min() {
            info.insert("loadPct".to_string(), json!(Rounded::to((load / cores as f64 * 100.0).min(100.0), 1)));
            info.insert("load1".to_string(), json!(Rounded::to(load, 2)));
            info.insert("ncpu".to_string(), json!(cores));
        }
        info.insert("logicalCores".to_string(), json!(cores));
        info.insert("availableCores".to_string(), json!(Cpu::available()));
        info.insert("physicalCores".to_string(), json!(Self::physical_cores().filter(|count| *count > 0).unwrap_or(cores)));
        if let Some(memory) = self.memory() {
            info.insert("ram".to_string(), memory);
        }
        Value::Object(info)
    }

    fn physical_cores() -> Option<usize> {
        let text = std::fs::read_to_string("/proc/cpuinfo").ok()?;
        let mut cores = BTreeSet::new();
        let mut package = "";
        for line in text.lines() {
            let word = line.split_once(':').map(|(_, word)| word.trim());
            if line.starts_with("physical id") {
                // absent-ok: a line with no colon names no package: the one before stands, or none.
                package = word.unwrap_or(package);
            } else if line.starts_with("core id") {
                cores.insert((package, word));
            }
        }
        Some(cores.len())
    }

    fn memory(&self) -> Option<Value> {
        if self.linux {
            let text = std::fs::read_to_string("/proc/meminfo").ok();
            if let Some(text) = text {
                return Some(Self::of_meminfo(&text));
            }
        }
        let ran = self.commands.run(&["sysctl", "-n", "hw.memsize"], Duration::from_secs(4)).ok().filter(|ran| ran.ok())?;
        let bytes = ran.stdout.trim().parse::<f64>().ok()?;
        Some(json!({"usedGb": null, "totalGb": Rounded::to(bytes / Self::GIB, 1)}))
    }

    /// `MemTotal` and `MemAvailable`. Used is what the kernel could not hand out now: a page cache of models is not memory taken.
    pub fn of_meminfo(text: &str) -> Value {
        let figure = |name: &str| -> f64 {
            let said = text.lines().find_map(|line| line.strip_prefix(name)?.strip_prefix(':'));
            // absent-ok: `mem.get(name, "0 kB")`: a kernel that does not say reads 0 there too.
            said.and_then(|said| said.split_whitespace().next()?.parse().ok()).unwrap_or(0.0)
        };
        let (total, available) = (figure("MemTotal"), figure("MemAvailable"));
        let used = (total - available).max(0.0);
        json!({"usedGb": Rounded::to(used / Self::GIB_IN_KIB, 1), "totalGb": Rounded::to(total / Self::GIB_IN_KIB, 1)})
    }
}
