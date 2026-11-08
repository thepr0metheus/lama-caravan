//! Whether the machine can hold what a start reserves: the card's memory and the RAM.

use crate::cells::ledger::MemoryLedger;
use crate::starts::StartRequest;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;

impl StartRequest {
    /// A holder is named in a refusal from this much memory on: less is a driver's or a display's context, not something to stop to make room.
    const NAMED_MIB: f64 = 256.0;

    fn number(value: Option<&Value>) -> Option<f64> {
        value.and_then(Coerce::float)
    }

    /// The refusal when the card cannot hold what the cell reserves the moment it starts; `None` when it can, or when the start reserves nothing up front. How much a runner reserves is the controller's knowledge; it sends it as `vram`
    /// `{device, reserveMiB, who, why, lower}`. What is free is this machine's, read now. Refused rather than started: otherwise the cell dies in a crash loop a minute later. Best effort: no `nvidia-smi`, no such card, no refusal.
    /// The words name the way out for THIS card: a card too small for the reserve is said to be, the holders named are the ones on that card, and another card with the room is named when there is one.
    pub(crate) fn short_of_vram(&self, id: &str) -> Option<Value> {
        let want = self.payload.get("vram").filter(|want| want.is_object())?;
        let device = Coerce::int_or_zero(want.get("device"))?.to_string();
        let reserve = match want.get("reserveMiB").filter(|said| Coerce::truthy(Some(*said))) {
            Some(said) => Coerce::float(said)?,
            None => 0.0,
        };
        let gpus = self.cells.machine.gpus();
        let card = gpus.iter().find(|gpu| Coerce::text(gpu.get("index")) == device);
        let free = Self::number(card.and_then(|card| card.get("memoryFreeMiB")))?;
        if reserve <= 0.0 || free >= reserve {
            return None;
        }
        let card = card?;
        let word = |key: &str, otherwise: &str| {
            if Coerce::truthy(want.get(key)) { Coerce::text(want.get(key)) } else { otherwise.to_string() }
        };
        let (lower, who, why) = (word("lower", "what it reserves"), word("who", "the cell"), word("why", ""));
        let reason = if why.is_empty() { String::new() } else { format!(" ({why})") };
        let wants = format!("{who} wants {:.1} GiB reserved{reason}", reserve / 1024.0);
        // absent-ok: a card of no said size cannot be told too small.
        let total = Self::number(card.get("memoryTotalMiB")).unwrap_or(0.0);
        let elsewhere = Self::room_elsewhere(&gpus, reserve)
            .map_or_else(String::new, |(index, room)| format!(", or pick GPU {index} ({:.1} GiB free)", room / 1024.0));
        if total != 0.0 && reserve > total {
            // Stopping cells cannot make the card bigger: the only ways out are another card or a smaller reserve.
            return Some(
                json!({"ok": false, "error": format!("{wants} but GPU {device} has only {:.1} GiB in all — lower {lower}{elsewhere}", total / 1024.0)}),
            );
        }
        let holders: Vec<String> =
            self.holders_of(id, card).iter().map(|(name, mib)| format!("{name} ({:.1} GiB)", mib / 1024.0)).collect();
        let hint = if holders.is_empty() {
            format!(" — lower {lower}")
        } else {
            format!(" — stop {} or lower {lower}", holders.join(", "))
        };
        Some(
            json!({"ok": false, "error": format!("{wants} but only {:.1} GiB VRAM is free on GPU {device}{hint}{elsewhere}", free / 1024.0)}),
        )
    }

    /// Who holds memory on `card` right now, the biggest first: a cell of this scout by the name its model has at the machine's entry (what its own process and the processes it started hold there), the
    /// executable's name for anything else. Not by a port: the board shows none. Only what is on THIS card: the refusal used to name every running cell of the machine, and a machine with two cards sent the
    /// operator to stop cells that held nothing there (2026-10-17).
    fn holders_of(&self, id: &str, card: &Value) -> Vec<(String, f64)> {
        let uuid = Coerce::text(card.get("uuid"));
        let apps = self.cells.machine.compute_apps();
        let mut owners: BTreeMap<i64, (String, String)> = BTreeMap::new();
        for (other, cell) in self.cells.table.all() {
            let status = cell.process.status();
            if status.get("running") != Some(&Value::Bool(true)) {
                continue;
            }
            let Some(pid) = status.get("pid").and_then(Value::as_i64) else {
                continue;
            };
            let named = cell.facts().name.clone();
            let shown = if named.is_empty() { other.clone() } else { named };
            owners.insert(pid, (other.clone(), shown.clone()));
            for child in self.cells.processes.descendants(pid) {
                owners.insert(child, (other.clone(), shown.clone()));
            }
        }
        let mut held: BTreeMap<String, f64> = BTreeMap::new();
        for app in apps.iter().filter(|app| !uuid.is_empty() && Coerce::text(app.get("gpuUuid")) == uuid) {
            let pid = app.get("pid").and_then(Value::as_i64);
            let owner = pid.and_then(|pid| owners.get(&pid));
            // The cell being started is not what is in its way.
            if owner.is_some_and(|(other, _)| other == id) {
                continue;
            }
            let name = match owner {
                Some((_, shown)) => shown.clone(),
                None if Coerce::truthy(app.get("name")) => Coerce::text(app.get("name")),
                None => format!("pid {}", Coerce::text(app.get("pid"))),
            };
            // absent-ok: an app of no said memory holds none to name.
            *held.entry(name).or_default() += Self::number(app.get("usedMiB")).unwrap_or(0.0);
        }
        let mut named: Vec<(String, f64)> = held.into_iter().filter(|(_, mib)| *mib >= Self::NAMED_MIB).collect();
        named.sort_by(|left, right| right.1.total_cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        named
    }

    /// Another card of this machine with the room the start wants free: (index, free MiB), the one with the most room. The card the start is for has less free than it wants: it is never its own answer.
    fn room_elsewhere(gpus: &[Value], reserve: f64) -> Option<(String, f64)> {
        let mut best: Option<(String, f64)> = None;
        for gpu in gpus {
            let Some(free) = Self::number(gpu.get("memoryFreeMiB")) else {
                continue;
            };
            if free >= reserve && best.as_ref().is_none_or(|(_, room)| free > *room) {
                best = Some((Coerce::text(gpu.get("index")), free));
            }
        }
        best
    }

    /// The refusal when the machine's memory cannot hold what the cell keeps resident; `None` when it can, or when the start promises nothing. Strata keeps its 37 GB in RAM: the card's check never saw that.
    pub(crate) fn short_of_ram(&self, id: &str) -> Option<Value> {
        let want = self.payload.get("ram").filter(|want| want.is_object())?;
        MemoryLedger::new(&self.cells.table, &self.cells.paths.meminfo).short(id, want)
    }
}
