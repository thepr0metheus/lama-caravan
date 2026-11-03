//! The memory limits a cell runs under. On Linux with a user systemd a cell is launched in its own transient scope, so that a model that eats the RAM
//! dies alone instead of taking the machine with it. Elsewhere it runs without limits, and the journal says so once: a limit that is not there must not read as one that is.

use crate::commands::Commands;
use crate::log::Log;
use crate::machine::Rounded;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

/// What a cell is launched with, and whether a scope can be made here.
pub struct MemoryScope {
    commands: Arc<dyn Commands>,
    linux: bool,
    /// Asked once per scout run.
    usable: Mutex<Option<bool>>,
}

impl MemoryScope {
    const HIGH: f64 = 0.70;
    const TOP: f64 = 0.80;
    const LIMITS: [&'static str; 3] = ["MemoryHigh=70%", "MemoryMax=80%", "MemorySwapMax=2G"];
    /// Over a cell's promise: room for what its own figure leaves out, and again up to the hard limit.
    const MARGIN_MIB: f64 = 2048.0;
    const READ_LIMIT: &'static str = r#"cat "/sys/fs/cgroup$(sed -n "s/^0:://p" /proc/self/cgroup)/memory.max""#;

    /// The scope on this machine.
    pub fn new(commands: Arc<dyn Commands>, linux: bool) -> Self {
        Self { commands, linux, usable: Mutex::new(None) }
    }

    fn usable(&self) -> bool {
        let mut usable = self.usable.lock().unwrap_or_else(PoisonError::into_inner);
        *usable.get_or_insert_with(|| {
            let (works, why) = self.probe();
            Log::line(&format!("[cells] {why}"));
            works
        })
    }

    /// Whether a cell launched here gets the limits, and why: systemd accepts `MemoryMax` even where the memory controller is not delegated to the user manager, so what a scope
    /// actually has is read from inside one.
    fn probe(&self) -> (bool, String) {
        const NONE: &str = "cells run without memory limits";
        if !self.linux {
            return (false, format!("{NONE}: the limits come from systemd, and this is not Linux"));
        }
        let limits: Vec<String> = Self::LIMITS.iter().map(|limit| (*limit).to_string()).collect();
        let argv = Self::command(&["sh".to_string(), "-c".to_string(), Self::READ_LIMIT.to_string()], &limits);
        let words: Vec<&str> = argv.iter().map(String::as_str).collect();
        let done = match self.commands.run(&words, Duration::from_secs(10)) {
            Ok(done) => done,
            Err(crate::commands::NoAnswer::NotFound) => return (false, format!("{NONE}: systemd-run is not installed")),
            Err(why) => return (false, format!("{NONE}: systemd-run --user did not answer ({})", why.words("systemd-run"))),
        };
        let said = done.stdout.trim();
        let figure = said.parse::<u64>().ok().filter(|_| done.ok());
        let Some(figure) = figure else {
            let why = done.stderr.trim().lines().last().map_or_else(
                || if said.is_empty() { format!("exit {}", done.code_word()) } else { format!("memory.max = {said}") },
                str::to_string,
            );
            return (false, format!("{NONE}: a user scope gets none here ({why})"));
        };
        (true, format!("cells run in their own scope: {} (MemoryMax {:.1} GB)", Self::LIMITS.join(" "), figure as f64 / 1e9))
    }

    /// The scope's limits for a cell that promised `ram_mib` resident: the machine's, raised for a promise above them to the promise and the margin, then the margin more, never
    /// past the machine's memory. A promise above `MemoryHigh` was a cell throttled by its own scope, whose sleeps were the session's memory pressure: systemd-oomd killed it.
    /// The machine's memory not known: the defaults, not a guess.
    pub fn limits(ram_mib: f64, total_mib: Option<f64>) -> Vec<String> {
        let plain = || Self::LIMITS.iter().map(|limit| (*limit).to_string()).collect::<Vec<_>>();
        let Some(total) = total_mib.filter(|total| *total > 0.0 && ram_mib > 0.0) else {
            return plain();
        };
        let high = (total * Self::HIGH).max(ram_mib + Self::MARGIN_MIB);
        if high <= total * Self::HIGH {
            return plain();
        }
        let top = total.min((total * Self::TOP).max(high + Self::MARGIN_MIB));
        vec![
            format!("MemoryHigh={}M", high.min(top).trunc() as i64),
            format!("MemoryMax={}M", top.trunc() as i64),
            Self::LIMITS[2].to_string(),
        ]
    }

    fn command(argv: &[String], limits: &[String]) -> Vec<String> {
        let mut out: Vec<String> =
            ["systemd-run", "--user", "--scope", "--quiet", "--collect"].iter().map(|word| (*word).to_string()).collect();
        for limit in limits {
            out.push("-p".to_string());
            out.push(limit.clone());
        }
        out.push("--".to_string());
        out.extend(argv.iter().cloned());
        out
    }

    /// The command as it is launched: in a limited scope when one can be made, sized for the memory the cell promised.
    pub fn wrap(&self, argv: &[String], ram_mib: f64, total_mib: Option<f64>) -> Vec<String> {
        if !self.usable() {
            return argv.to_vec();
        }
        let limits = Self::limits(ram_mib, total_mib);
        if limits.first().map(String::as_str) != Self::LIMITS.first().copied() {
            Log::line(&format!(
                "[cells] a cell that promised {} GiB runs in a scope of {}",
                Rounded::to(ram_mib / 1024.0, 1),
                limits.join(" ")
            ));
        }
        Self::command(argv, &limits)
    }
}
