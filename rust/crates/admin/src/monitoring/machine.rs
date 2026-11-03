//! What this machine is doing now: its processors, memory, disks and network, and its cards as its scout reports them.

use crate::app::App;
use crate::fleet::machine_scout::MachineScout;
use crate::fleet::terminal::TerminalFrame;
use os::Cpu;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::path::Path;
use std::time::Duration;

/// One line of `/proc/stat`.
pub type CpuTimes = Vec<(String, u64, u64)>;

/// The readings of this machine.
pub struct MachineState<'app> {
    app: &'app App,
}

impl<'app> MachineState<'app> {
    /// The readings of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn lines_without_noise(text: &str) -> String {
        let kept: Vec<&str> =
            text.lines().filter(|line| !line.contains("Session terminated") && !line.contains("killing shell")).collect();
        kept.join("\n")
    }

    /// A terminal snapshot of the controller's machine, taken by its scout.
    pub fn snapshot(&self, kind: &str) -> Result<Value, AppError> {
        let scout = MachineScout::of(self.app);
        let now = self.app.now_whole();
        match kind {
            "nvidia-smi" => {
                let answer = scout.read("/api/monitor/nvidia-smi", 8);
                let said = answer.get("output").filter(|said| Coerce::truthy(Some(*said))).or_else(|| answer.get("error"));
                let source =
                    answer.get("source").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!(kind));
                let time = answer.get("time").filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int).unwrap_or(now);
                Ok(
                    json!({"kind": kind, "ok": Coerce::truthy(answer.get("ok")), "output": Coerce::stripped(said), "time": time, "source": source}),
                )
            }
            "btop" => {
                let answer = scout.read("/api/monitor/btop", 12);
                if Coerce::truthy(answer.get("error"))
                    && !Coerce::truthy(answer.get("frame"))
                    && !Coerce::truthy(answer.get("top"))
                {
                    return Ok(json!({"kind": kind, "ok": false, "output": answer.get("error"), "time": now}));
                }
                let raw = Coerce::text(answer.get("frame"));
                let output = Self::lines_without_noise(&TerminalFrame::to_text(&raw, 40, 120));
                let html = Self::lines_without_noise(&TerminalFrame::to_html(&raw, 40, 120));
                if !output.trim().is_empty()
                    && !output.contains("Failed to get size of terminal")
                    && !output.contains("Terminal size too small")
                {
                    return Ok(json!({"kind": kind, "ok": true, "output": output, "html": html, "time": now, "source": "btop"}));
                }
                let top = Coerce::stripped(answer.get("top"));
                let shown = format!("btop snapshot unavailable; showing top fallback.\n\n{top}");
                Ok(json!({"kind": kind, "ok": !top.is_empty(), "output": shown, "time": now, "source": "top"}))
            }
            _ => Err(AppError::with_status("Unknown monitor", 404)),
        }
    }

    /// The processor lines of `/proc/stat`.
    pub fn cpu_times(&self) -> CpuTimes {
        let Ok(text) = std::fs::read_to_string("/proc/stat") else {
            return Vec::new();
        };
        Self::parse_cpu_times(&text)
    }

    fn parse_cpu_times(text: &str) -> CpuTimes {
        let mut rows = Vec::new();
        for line in text.lines().filter(|line| line.starts_with("cpu")) {
            let mut parts = line.split_whitespace();
            let Some(name) = parts.next() else {
                continue;
            };
            if name != "cpu"
                && !name.get(3..).is_some_and(|digits| !digits.is_empty() && digits.chars().all(|digit| digit.is_ascii_digit()))
            {
                continue;
            }
            let values: Vec<u64> = parts.filter_map(|word| word.parse().ok()).collect();
            // absent-ok: a line with fewer columns has no idle time to add.
            let idle = values.get(3).copied().unwrap_or(0) + values.get(4).copied().unwrap_or(0);
            rows.push((name.to_string(), values.iter().sum(), idle));
        }
        rows
    }

    /// `{total, cores}` between two readings.
    pub fn cpu_percentages(previous: Option<&CpuTimes>, current: &CpuTimes) -> Value {
        let Some(previous) = previous.filter(|previous| !previous.is_empty()) else {
            return json!({"total": 0, "cores": []});
        };
        let (mut cores, mut total_pct) = (Vec::new(), json!(0));
        for (name, total, idle) in current {
            let old = previous.iter().find(|row| row.0 == *name);
            let pct = old.and_then(|old| {
                let total_delta = total.checked_sub(old.1).filter(|delta| *delta > 0)?;
                let idle_delta = idle.saturating_sub(old.2);
                Some(Coerce::rounded(100.0 * (1.0 - idle_delta as f64 / total_delta as f64), 1))
            });
            let shown = pct.map_or_else(|| json!(0), |pct| json!(pct));
            if name == "cpu" {
                total_pct = shown;
            } else {
                cores.push(shown);
            }
        }
        json!({"total": total_pct, "cores": cores})
    }

    /// Bytes read and written on this machine's disks so far.
    pub fn disk_counters(&self) -> Value {
        let (mut read, mut written) = (0u64, 0u64);
        // absent-ok: a machine with no such file says nothing: the sample shows none.
        for line in std::fs::read_to_string("/proc/diskstats").unwrap_or_default().lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            let (Some(name), Some(sectors_read), Some(sectors_written)) = (parts.get(2), parts.get(5), parts.get(9)) else {
                continue;
            };
            if parts.len() < 14 || ["loop", "ram", "zram", "sr"].iter().any(|prefix| name.starts_with(prefix)) {
                continue;
            }
            let ends_in_digit = name.chars().last().is_some_and(|letter| letter.is_ascii_digit());
            if ends_in_digit && !name.starts_with("nvme") && !name.starts_with("mmcblk") {
                continue;
            }
            // absent-ok: a column that is no number adds nothing.
            read += sectors_read.parse::<u64>().unwrap_or(0);
            // absent-ok: a column that is no number adds nothing.
            written += sectors_written.parse::<u64>().unwrap_or(0);
        }
        json!({"readBytes": read * 512, "writeBytes": written * 512})
    }

    /// Bytes through this machine's network so far.
    pub fn net_counters(&self) -> Value {
        let (mut received, mut sent) = (0u64, 0u64);
        // absent-ok: a machine with no such file says nothing: the sample shows none.
        for line in std::fs::read_to_string("/proc/net/dev").unwrap_or_default().lines().skip(2) {
            let Some((name, raw)) = line.split_once(':') else {
                continue;
            };
            if Coerce::strip(name) == "lo" {
                continue;
            }
            let parts: Vec<&str> = raw.split_whitespace().collect();
            // absent-ok: a column that is no number adds nothing.
            received += parts.first().and_then(|word| word.parse::<u64>().ok()).unwrap_or(0);
            // absent-ok: a column that is no number adds nothing.
            sent += parts.get(8).and_then(|word| word.parse::<u64>().ok()).unwrap_or(0);
        }
        json!({"rxBytes": received, "txBytes": sent})
    }

    /// Each counter's rate between two readings.
    pub fn rate_delta(previous: Option<&Value>, current: &Value, elapsed: f64, keys: &[&str]) -> Value {
        let mut out = Map::new();
        for key in keys {
            let rate = match previous.filter(|_| elapsed > 0.0) {
                Some(previous) => {
                    // absent-ok: a figure not said is none.
                    let at = |side: &Value| side.get(*key).and_then(Value::as_f64).unwrap_or(0.0);
                    ((at(current) - at(previous)) / elapsed).round().max(0.0) as i64
                }
                None => 0,
            };
            out.insert(format!("{key}PerSec"), json!(rate));
        }
        Value::Object(out)
    }

    /// The first card of the controller's machine this second, as its scout samples it.
    pub fn gpu_sample(&self) -> Value {
        let since = self.app.now_whole() - 15;
        let answer = MachineScout::of(self.app).read(&format!("/api/telemetry?since={since}"), 1);
        let Some(samples) = answer.get("samples").and_then(Value::as_array) else {
            let said = Coerce::text(answer.get("error"));
            return json!({"ok": false, "error": if said.is_empty() { "the scout sent no samples".to_string() } else { said }});
        };
        let Some(last) = samples.last() else {
            return json!({"ok": false, "error": "the scout on the controller's machine has no sample yet"});
        };
        let Some(card) = last.get("gpus").and_then(Value::as_array).and_then(|cards| cards.first()) else {
            return json!({"ok": false, "error": "no GPU on the controller's machine"});
        };
        let number = |key: &str| {
            card.get(key).filter(|said| said.is_number()).and_then(Value::as_f64).map_or_else(|| json!(0), |said| json!(said))
        };
        // absent-ok: a figure the card does not report is none.
        let figure = |key: &str| card.get(key).filter(|said| said.is_number()).and_then(Value::as_f64).unwrap_or(0.0);
        let (used, total) = (figure("memUsedMiB"), figure("memTotalMiB"));
        let pct = if total > 0.0 { json!(Coerce::rounded(100.0 * used / total, 1)) } else { json!(0) };
        json!({
            "ok": true, "utilPct": number("utilPct"), "memoryUsedMiB": number("memUsedMiB"), "memoryTotalMiB": number("memTotalMiB"),
            "memoryPct": pct, "temperatureC": number("tempC"), "powerW": number("powerW"),
        })
    }

    /// The memory of this machine, with how much of it is used.
    pub fn memory_sample(&self) -> Value {
        let mut memory = self.memory_state();
        if !Coerce::truthy(memory.get("ok")) {
            return memory;
        }
        // absent-ok: a figure not said is none.
        let figure = |key: &str| memory.get(key).and_then(Value::as_f64).unwrap_or(0.0);
        let (total, used) = (figure("totalMiB"), figure("usedMiB"));
        let pct = if total > 0.0 { json!(Coerce::rounded(100.0 * used / total, 1)) } else { json!(0) };
        Coerce::put(&mut memory, "usedPct", pct);
        memory
    }

    /// The busiest processes of the controller's machine, as its scout lists them.
    pub fn top_processes(&self) -> Value {
        let answer = MachineScout::of(self.app).read("/api/host/processes", 2);
        answer.get("processes").filter(|said| said.is_array()).cloned().unwrap_or_else(|| json!([]))
    }

    /// The cards of the controller's machine, as its scout reports them.
    pub fn gpu_state(&self) -> Value {
        let host = MachineScout::of(self.app).host();
        if !Coerce::truthy(Some(&host)) {
            return json!({"ok": false, "gpus": [], "error": MachineScout::NO_SCOUT});
        }
        let cards: Vec<&Value> =
            host.get("gpus").and_then(Value::as_array).into_iter().flatten().filter(|card| card.is_object()).collect();
        if cards.is_empty() {
            return json!({"ok": false, "gpus": [], "error": Coerce::text(host.get("gpuError"))});
        }
        json!({"ok": true, "gpus": cards})
    }

    fn load_average() -> (f64, f64, f64) {
        // absent-ok: a system that keeps no load says none, as `os.getloadavg()` failing does in the sample.
        let [one, five, fifteen] = Cpu::load_average().unwrap_or([0.0; 3]);
        (one, five, fifteen)
    }

    /// The load average, rounded.
    pub fn load_rounded() -> Value {
        let (one, five, fifteen) = Self::load_average();
        json!([Coerce::rounded(one, 2), Coerce::rounded(five, 2), Coerce::rounded(fifteen, 2)])
    }

    fn cpu_snapshot() -> Value {
        // absent-ok: a machine with no such file says nothing: the sample shows none.
        let first = Self::parse_cpu_times(&std::fs::read_to_string("/proc/stat").unwrap_or_default());
        std::thread::sleep(Duration::from_millis(120));
        // absent-ok: a machine with no such file says nothing: the sample shows none.
        let second = Self::parse_cpu_times(&std::fs::read_to_string("/proc/stat").unwrap_or_default());
        let (Some(before), Some(after)) = (first.first(), second.first()) else {
            return json!(0);
        };
        let total = after.1.saturating_sub(before.1);
        if total == 0 {
            return json!(0);
        }
        json!(Coerce::rounded(100.0 * (1.0 - after.2.saturating_sub(before.2) as f64 / total as f64), 1))
    }

    /// The processors of this machine.
    pub fn cpu_state(&self) -> Value {
        let Ok(raw) = std::fs::read("/proc/cpuinfo") else {
            return json!({"ok": false, "error": "this machine has no /proc/cpuinfo"});
        };
        let info = String::from_utf8_lossy(&raw);
        let mut model = "unknown".to_string();
        if let Some(line) = info.lines().find(|line| line.starts_with("model name"))
            && let Some((_, said)) = line.split_once(':')
        {
            model = Coerce::strip(said).to_string();
        }
        let logical = Cpu::count();
        let (mut sockets, mut cores, mut current) = (BTreeSet::new(), BTreeSet::new(), String::new());
        for line in info.lines() {
            let Some((_, said)) = line.split_once(':') else {
                continue;
            };
            if line.starts_with("physical id") {
                current = Coerce::strip(said).to_string();
                sockets.insert(current.clone());
            } else if line.starts_with("core id") {
                cores.insert((current.clone(), Coerce::strip(said).to_string()));
            }
        }
        let (one, five, fifteen) = Self::load_average();
        json!({
            "ok": true, "model": model, "logicalCores": logical, "physicalCores": if cores.is_empty() { logical } else { cores.len() },
            "availableCores": Cpu::available(), "sockets": if sockets.is_empty() { 1 } else { sockets.len() },
            "load1": Coerce::rounded(one, 2), "load5": Coerce::rounded(five, 2), "load15": Coerce::rounded(fifteen, 2),
            "usagePct": Self::cpu_snapshot(),
        })
    }

    fn memory_darwin(&self) -> Value {
        let run = |argv: &[&str]| self.app.commands.run(argv, Duration::from_secs(3)).ok().filter(plumbing::commands::Ran::ok);
        let (Some(total), Some(stats)) = (run(&["sysctl", "-n", "hw.memsize"]), run(&["vm_stat"])) else {
            return json!({"ok": false, "error": "sysctl/vm_stat unavailable"});
        };
        let Ok(total_bytes) = Coerce::strip(&total.stdout).parse::<u64>() else {
            return json!({"ok": false, "error": "sysctl said no number"});
        };
        let (mut page, mut pages) = (4096u64, std::collections::BTreeMap::new());
        for line in stats.stdout.lines() {
            if line.starts_with("Mach Virtual Memory Statistics") {
                let digits = line
                    .split("page size of ")
                    .nth(1)
                    .map(|rest| rest.chars().take_while(char::is_ascii_digit).collect::<String>());
                if let Some(size) = digits.and_then(|digits| digits.parse().ok()) {
                    page = size;
                }
                continue;
            }
            if let Some((key, raw)) = line.split_once(':') {
                pages
                    // absent-ok: a column that is no number adds nothing.
                    .insert(Coerce::strip(key).to_string(), Coerce::strip(raw).trim_end_matches('.').parse::<u64>().unwrap_or(0));
            }
        }
        // absent-ok: a line vm_stat did not print is none.
        let count = |key: &str| pages.get(key).copied().unwrap_or(0);
        let free = (count("Pages free") + count("Pages speculative")) * page;
        let available = free + (count("Pages inactive") + count("Pages purgeable")) * page;
        let mib = |bytes: u64| (bytes as f64 / 1_048_576.0).round() as i64;
        json!({"ok": true, "totalMiB": mib(total_bytes), "availableMiB": mib(available), "freeMiB": mib(free), "usedMiB": mib(total_bytes.saturating_sub(available))})
    }

    /// The memory of this machine.
    pub fn memory_state(&self) -> Value {
        if !Path::new("/proc/meminfo").exists() {
            return self.memory_darwin();
        }
        let text = match std::fs::read_to_string("/proc/meminfo") {
            Ok(text) => text,
            Err(error) => return json!({"ok": false, "error": error.to_string()}),
        };
        let figure = |key: &str| -> Option<u64> {
            let line = text.lines().find(|line| line.split(':').next() == Some(key))?;
            line.split(':').nth(1)?.split_whitespace().next()?.parse().ok()
        };
        // absent-ok: a line the file does not hold is none.
        let total = figure("MemTotal").unwrap_or(0);
        // absent-ok: a line the file does not hold is none.
        let free = figure("MemFree").unwrap_or(0);
        let available = figure("MemAvailable").unwrap_or(free);
        let mib = |kib: u64| (kib as f64 / 1024.0).round() as i64;
        json!({"ok": true, "totalMiB": mib(total), "availableMiB": mib(available), "freeMiB": mib(free), "usedMiB": mib(total.saturating_sub(available))})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn processor_lines_are_read_as_totals_and_idle() {
        let rows = MachineState::parse_cpu_times("cpu 1 2 3 4 5\ncpu0 1 1 1 1\ncpux 9\nintr 5\n");
        assert_eq!(rows, [("cpu".to_string(), 15, 9), ("cpu0".to_string(), 4, 1)]);
    }

    #[test]
    fn percentages_are_between_two_readings() {
        let (before, after) = (
            vec![("cpu".to_string(), 100, 50), ("cpu0".to_string(), 100, 50)],
            vec![("cpu".to_string(), 200, 100), ("cpu0".to_string(), 100, 50)],
        );
        assert_eq!(MachineState::cpu_percentages(None, &after), json!({"total": 0, "cores": []}));
        assert_eq!(MachineState::cpu_percentages(Some(&before), &after), json!({"total": 50.0, "cores": [0]}));
    }

    #[test]
    fn a_rate_is_the_difference_over_the_time() {
        let (before, after) = (json!({"a": 100}), json!({"a": 300}));
        assert_eq!(MachineState::rate_delta(Some(&before), &after, 2.0, &["a"]), json!({"aPerSec": 100}));
        assert_eq!(MachineState::rate_delta(None, &after, 2.0, &["a"]), json!({"aPerSec": 0}));
        assert_eq!(MachineState::rate_delta(Some(&after), &before, 2.0, &["a"]), json!({"aPerSec": 0}));
    }
}
