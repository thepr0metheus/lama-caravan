//! The machine second by second, for the board's charts. This machine's cards and processor, sampled every second while a board watches it and every ten seconds otherwise; ten minutes kept. The controller asks for what is new about once a second while a board is open; each ask marks the machine watched for 30 s. Unwatched, the history thins instead of stopping, so that an opened board still has the last ten minutes.

use crate::machine::{Machine, Rounded};
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

/// What it remembers.
#[derive(Debug, Default)]
struct Memory {
    ring: VecDeque<(i64, Value)>,
    asked_at: f64,
    cpu_before: Option<(u64, u64)>,
}

/// The telemetry.
pub struct Telemetry {
    machine: Arc<Machine>,
    clock: Arc<dyn Clock>,
    proc_stat: PathBuf,
    memory: Mutex<Memory>,
}

impl Telemetry {
    const WATCHED_SEC: f64 = 1.0;
    const IDLE_SEC: f64 = 10.0;
    const WATCH_WINDOW: f64 = 30.0;
    const RETENTION: i64 = 600;

    /// The telemetry of this machine.
    pub fn new(machine: Arc<Machine>, clock: Arc<dyn Clock>, proc_stat: PathBuf) -> Self {
        Self { machine, clock, proc_stat, memory: Mutex::new(Memory::default()) }
    }

    fn memory(&self) -> MutexGuard<'_, Memory> {
        self.memory.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// How long until the next sample.
    pub fn rest(&self) -> f64 {
        if self.clock.epoch() - self.memory().asked_at < Self::WATCH_WINDOW { Self::WATCHED_SEC } else { Self::IDLE_SEC }
    }

    /// (total, idle) jiffies of all cores, or `None` without `/proc/stat`.
    fn cpu_times(&self) -> Option<(u64, u64)> {
        let text = std::fs::read_to_string(&self.proc_stat).ok()?;
        let mut words = text.lines().next()?.split_whitespace();
        if words.next()? != "cpu" {
            return None;
        }
        let values: Vec<u64> = words.map(|word| word.parse().ok()).collect::<Option<Vec<u64>>>()?;
        // absent-ok: `iowait` is the fifth field of a kernel that has one.
        let idle = values.get(3).copied()? + values.get(4).copied().unwrap_or(0);
        Some((values.iter().sum(), idle))
    }

    /// The share of the processor busy since the last sample: from `/proc/stat` between two samples; without `/proc` (macOS) the one-minute load average stands in.
    fn cpu_pct(&self, fallback: Option<f64>) -> Option<f64> {
        let now = self.cpu_times();
        let before = std::mem::replace(&mut self.memory().cpu_before, now);
        let Some((total, idle)) = now else {
            return fallback;
        };
        let (total_before, idle_before) = before.filter(|(total_before, _)| total > *total_before)?;
        Some(Rounded::to(100.0 * (1.0 - (idle - idle_before) as f64 / (total - total_before) as f64), 1))
    }

    fn number(value: Option<&Value>) -> Option<f64> {
        value.and_then(Coerce::float).map(|number| Rounded::to(number, 1))
    }

    /// Reads the machine once and keeps it.
    pub fn sample(&self) -> Value {
        let cpu = self.machine.cpu_ram();
        let at = self.clock.epoch() as i64;
        let gpus: Vec<Value> = self
            .machine
            .gpus()
            .iter()
            .map(|gpu| {
                let index = Some(Coerce::text(gpu.get("index")))
                    .filter(|word| !word.is_empty() && word.chars().all(|letter| letter.is_ascii_digit()))
                    .and_then(|word| word.parse::<i64>().ok());
                json!({
                    "index": index,
                    "memUsedMiB": Self::number(gpu.get("memoryUsedMiB")),
                    "memTotalMiB": Self::number(gpu.get("memoryTotalMiB")),
                    "utilPct": Self::number(gpu.get("utilizationGpuPct")),
                    "powerW": Self::number(gpu.get("powerDrawW")),
                    "tempC": Self::number(gpu.get("temperatureC")),
                })
            })
            .collect();
        let row = json!({
            "t": at,
            "gpus": gpus,
            "cpuPct": self.cpu_pct(cpu.get("loadPct").and_then(Value::as_f64)),
            "ram": cpu.get("ram").filter(|ram| ram.is_object()),
        });
        let mut memory = self.memory();
        match memory.ring.back_mut() {
            Some((last, kept)) if *last == at => *kept = row.clone(),
            _ => memory.ring.push_back((at, row.clone())),
        }
        while memory.ring.front().is_some_and(|(oldest, _)| *oldest < at - Self::RETENTION) {
            memory.ring.pop_front();
        }
        row
    }

    /// How this machine is sampled: said in both reports.
    pub fn describe(&self) -> Value {
        json!({"watchedSeconds": Self::WATCHED_SEC, "idleSeconds": Self::IDLE_SEC, "retentionSeconds": Self::RETENTION})
    }

    /// The samples newer than `since` (epoch s), all ten minutes for 0, and the machine is watched for the next 30 s.
    pub fn since(&self, since: Option<&str>) -> Value {
        // absent-ok: a `since` of no number asks for all of them.
        let after = since.and_then(|since| Coerce::float(&json!(since))).map_or(0, |since| since.trunc() as i64);
        let rows: Vec<Value> = {
            let mut memory = self.memory();
            memory.asked_at = self.clock.epoch();
            memory.ring.iter().filter(|(at, _)| *at > after).map(|(_, row)| row.clone()).collect()
        };
        json!({"ok": true, "watchedSeconds": Self::WATCHED_SEC, "idleSeconds": Self::IDLE_SEC, "retentionSeconds": Self::RETENTION, "samples": rows})
    }
}
