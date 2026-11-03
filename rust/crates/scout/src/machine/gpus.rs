//! What `nvidia-smi` and `lspci` say of the cards.
//!
//! The field names are a contract with the controller, whose one card renderer draws every machine's cards: rename one, and that value silently
//! turns into "?" on the board.

use crate::commands::{Commands, NoAnswer};
use rules::Coerce;
use serde_json::{Value, json};
use std::time::Duration;

/// The cards of this machine, and why `nvidia-smi` named none.
pub struct GpuProbe;

impl GpuProbe {
    const TIMEOUT: Duration = Duration::from_secs(5);
    const SAID_MAX: usize = 200;
    const FIELDS: &'static str =
        "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw,uuid";
    const APPS_QUERY: &'static str = "--query-compute-apps=gpu_uuid,pid,process_name,used_memory";
    const FORMAT: &'static str = "--format=csv,noheader,nounits";
    /// How `nvidia-smi` says it cannot name a process: another PID namespace, a process gone between two reads.
    const NO_PROCESS_NAME: [&'static str; 4] = ["[not found]", "[n/a]", "n/a", "[insufficient permissions]"];

    /// (the cards, why `nvidia-smi` named none). Its complaint stands beside `lspci`'s fallback: "driver missing" is all `lspci` can say, while the
    /// driver may be installed and waiting for a reboot.
    pub fn reading(commands: &dyn Commands, linux: bool) -> (Vec<Value>, String) {
        let (cards, error) = Self::nvidia(commands);
        if cards.is_empty() {
            return (Self::lspci(commands, linux), error);
        }
        (cards, String::new())
    }

    /// (the cards `nvidia-smi` names, its complaint when it names none). The complaint is the first line it wrote, in either stream: NVML's goes
    /// to stdout, with exit code 0 at times. No `nvidia-smi` at all is no complaint: a host without the driver, where `lspci` decides.
    fn nvidia(commands: &dyn Commands) -> (Vec<Value>, String) {
        let ran = match commands.run(&["nvidia-smi", Self::FIELDS, Self::FORMAT], Self::TIMEOUT) {
            Ok(ran) => ran,
            Err(NoAnswer::NotFound) => return (Vec::new(), String::new()),
            Err(NoAnswer::TimedOut) => return (Vec::new(), "nvidia-smi did not answer in 5 s".to_string()),
            Err(NoAnswer::Failed(words)) => return (Vec::new(), Self::cut(&format!("nvidia-smi: {words}"))),
        };
        let both = format!("{}\n{}", ran.stdout, ran.stderr);
        if !ran.ok() {
            // absent-ok: a tool that a signal ended has no code; the words say so with the -1 Python's `returncode` has for it.
            let code = ran.code.unwrap_or(-1);
            let said = both.lines().map(Coerce::strip).find(|line| !line.is_empty());
            return (Vec::new(), Self::cut(said.map_or(format!("nvidia-smi exited with {code}"), str::to_string).as_str()));
        }
        let cards: Vec<Value> = ran.stdout.lines().filter_map(Self::card).collect();
        if !cards.is_empty() {
            return (cards, String::new());
        }
        // absent-ok: no line of its own to say is no complaint.
        let said = both.lines().find(|line| !Coerce::strip(line).is_empty() && !line.contains(',')).map_or("", Coerce::strip);
        (Vec::new(), Self::cut(said))
    }

    fn cut(words: &str) -> String {
        words.chars().take(Self::SAID_MAX).collect()
    }

    fn card(line: &str) -> Option<Value> {
        let parts: Vec<&str> = line.split(',').map(Coerce::strip).collect();
        let [index, name, total, used, free, utilization, temperature, power, rest @ ..] = parts.as_slice() else {
            return None;
        };
        // absent-ok: an old `nvidia-smi` that names no uuid: "".
        let uuid = rest.first().copied().unwrap_or_default();
        Some(json!({
            "index": index, "name": name, "vendor": "nvidia", "driverStatus": "ok", "memoryTotalMiB": total, "memoryUsedMiB": used,
            "memoryFreeMiB": free, "utilizationGpuPct": utilization, "temperatureC": temperature, "powerDrawW": power, "uuid": uuid,
        }))
    }

    /// Per-process GPU memory, so the controller can map a server's pid to the cards it occupies: `[{gpuUuid, pid, name, usedMiB}]`. A name with a comma
    /// in it stays whole: the memory is the last column.
    pub fn apps(commands: &dyn Commands) -> Vec<Value> {
        let Ok(ran) = commands.run(&["nvidia-smi", Self::APPS_QUERY, Self::FORMAT], Self::TIMEOUT) else {
            return Vec::new();
        };
        if !ran.ok() {
            return Vec::new();
        }
        ran.stdout.lines().filter_map(Self::app).collect()
    }

    fn app(line: &str) -> Option<Value> {
        let parts: Vec<&str> = line.split(',').map(Coerce::strip).collect();
        let [uuid, pid, middle @ .., memory] = parts.as_slice() else {
            return None;
        };
        if parts.len() < 4 || !Self::is_digits(pid) {
            return None;
        }
        let joined = middle.join(",");
        let name = Coerce::strip(&joined);
        let name = if Self::NO_PROCESS_NAME.contains(&name.to_lowercase().as_str()) { "" } else { name };
        // absent-ok: a memory figure that is no number reads 0; the board draws what is known beside it.
        let used = if Self::is_digits(memory) { memory.parse::<i64>().unwrap_or(0) } else { 0 };
        // absent-ok: `rsplit` always has a last part.
        let executable = name.rsplit('/').next().unwrap_or_default();
        Some(json!({"gpuUuid": uuid, "pid": pid.parse::<i64>().ok()?, "name": executable, "usedMiB": used}))
    }

    fn is_digits(text: &str) -> bool {
        !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit())
    }

    /// NVIDIA's cards by `lspci`: works with no driver installed, so a machine with a card and no `nvidia-smi` does not look like it has none.
    fn lspci(commands: &dyn Commands, linux: bool) -> Vec<Value> {
        if !linux {
            return Vec::new();
        }
        let Ok(ran) = commands.run(&["lspci"], Self::TIMEOUT) else {
            return Vec::new();
        };
        if !ran.ok() {
            return Vec::new();
        }
        let is_a_card = |line: &&str| {
            let low = line.to_lowercase();
            low.contains("nvidia") && ["vga", "3d controller", "display"].iter().any(|word| low.contains(word))
        };
        ran.stdout
            .lines()
            .filter(is_a_card)
            .enumerate()
            .map(|(index, line)| {
                json!({"index": index.to_string(), "name": Self::lspci_name(line), "vendor": "nvidia", "driverStatus": "driver_missing"})
            })
            .collect()
    }

    /// "... [GeForce RTX 3090] (rev a1)" is "NVIDIA GeForce RTX 3090".
    fn lspci_name(line: &str) -> String {
        const PLAIN: &str = "NVIDIA GPU";
        let (Some(open), Some(close)) = (line.rfind('['), line.rfind(']')) else {
            return PLAIN.to_string();
        };
        // absent-ok: `]` before the last `[` has nothing between them: the plain name.
        let inner = Coerce::strip(line.get(open + 1..close).unwrap_or_default());
        match inner {
            "" => PLAIN.to_string(),
            name if name.to_lowercase().starts_with("nvidia") => name.to_string(),
            name => format!("NVIDIA {name}"),
        }
    }
}
