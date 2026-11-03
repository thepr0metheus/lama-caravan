//! A crashed cell comes back, as systemd brings the controller's: what `Restart=on-failure` does. A cell that died without being stopped, a non-zero exit or gone while adopted, is launched again the same
//! way 10 s later, at most 3 times in 10 minutes; then it stays down and says why. A clean exit is not a crash.

use crate::cells::Cells;
use crate::cells::saved_start::SavedStart;
use crate::cells::suspect::CrashSuspect;
use crate::cells::table::Cell;
use crate::log::Log;
use os::clock::Clock;
use os::{LocalTime, Signals};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::sync::Arc;

/// A cell's crashes since the operator last started it by hand: the 💥 on the board, and the lines under it on hover. The lines are read when the crash is seen: the relaunch moves that log aside.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct CrashNote {
    /// How many.
    pub count: i64,
    /// When the last one was.
    pub at: String,
    /// Why, in the log's words.
    pub reason: String,
    /// The log's last lines.
    pub tail: String,
    /// When the restarts were.
    restarts: Vec<f64>,
    /// When the next restart is due.
    due: Option<f64>,
    /// It stays down.
    pub gave_up: bool,
    /// It stays down, and it never got ready.
    pub never_ready: bool,
    /// The starts in a row that died before the port listened.
    unready: i64,
}

impl CrashNote {
    /// The note as the controller reads it, or `None`.
    pub fn public(&self) -> Option<Value> {
        if self.count <= 0 {
            return None;
        }
        let mut out = Map::new();
        out.insert("count".to_string(), json!(self.count));
        out.insert("at".to_string(), json!(self.at));
        out.insert("reason".to_string(), json!(self.reason));
        if !self.tail.is_empty() {
            out.insert("tail".to_string(), json!(self.tail));
        }
        if self.gave_up {
            out.insert("gaveUp".to_string(), json!(true));
        }
        if self.never_ready {
            out.insert("neverReady".to_string(), json!(true));
        }
        Some(Value::Object(out))
    }
}

/// How a process ended, in words: the card's and the crash note's alike.
pub struct ProcessEnd;

impl ProcessEnd {
    /// What a SIGKILL that this scout did not send usually is. The process cannot catch it, so its own log says nothing of it: the last line is merely the last thing it said before it was killed.
    const KILLED: &'static str =
        " (killed from outside — on a machine short of memory that is systemd-oomd or the kernel's OOM killer)";
    const REASON_LETTERS: usize = 300;

    /// A signal by its name ("died of SIGSEGV" says what "exited (code -11)" hides, and the build's suspect reads it), the exit code, or that the code is not known: a process adopted after a scout's restart
    /// is not this scout's child, and its exit code is lost.
    pub fn how(status: &Map<String, Value>) -> String {
        let Some(code) = status.get("exitCode").filter(|code| !code.is_null()) else {
            return "ended with an unknown exit code (adopted after a scout restart)".to_string();
        };
        let name = code.as_i64().filter(|code| *code < 0).and_then(|code| i32::try_from(-code).ok()).and_then(Signals::name);
        name.map_or_else(|| format!("exited (code {code})"), |name| format!("died of {name}"))
    }

    /// The crash note's reason: what the log says was the cause, or, when the process was ended by SIGKILL, which is not a thing it did itself, that first, with the log's last words after it.
    pub fn reason(status: &Map<String, Value>) -> String {
        let cause = if Coerce::truthy(status.get("lastError")) { Coerce::text(status.get("lastError")) } else { String::new() };
        let how = Self::how(status);
        let said = if status.get("exitCode").and_then(Value::as_i64) == Some(-i64::from(Signals::KILL)) {
            let words = if cause.is_empty() { String::new() } else { format!(" — its last words: {cause}") };
            format!("{how}{}{words}", Self::KILLED)
        } else if cause.is_empty() {
            how
        } else {
            cause
        };
        Coerce::first_letters(&said, Self::REASON_LETTERS).to_string()
    }
}

/// The watchdog.
pub struct Watchdog {
    cells: Arc<Cells>,
    suspect: Arc<CrashSuspect>,
    clock: Arc<dyn Clock>,
}

impl Watchdog {
    const RESTART_SEC: f64 = 10.0;
    const BURST: usize = 3;
    /// The window of the burst, in seconds.
    pub const WINDOW_SEC: i64 = 600;

    /// The watch over these cells.
    pub fn new(cells: Arc<Cells>, suspect: Arc<CrashSuspect>, clock: Arc<dyn Clock>) -> Self {
        Self { cells, suspect, clock }
    }

    /// One pass.
    pub fn tick(&self) {
        let now = self.clock.epoch();
        let listening = self.cells.machine.listening_ports();
        for (port, cell) in self.cells.table.all() {
            let status = cell.process.status();
            let running = status.get("running") == Some(&Value::Bool(true));
            if running {
                Self::watch(port, &cell, listening.as_ref());
            }
            let note = cell.facts().crash.clone();
            if let Some(due) = note.as_ref().and_then(|note| note.due) {
                if let Some(note) = note.filter(|_| !running && now >= due) {
                    self.restart(port, &cell, note, now);
                }
                continue;
            }
            let gave_up = note.as_ref().is_some_and(|note| note.gave_up);
            if !running && Coerce::truthy(status.get("crashed")) && !gave_up {
                // absent-ok: a first crash starts a note of none.
                self.crashed(port, &cell, &status, note.unwrap_or_default(), now);
            }
        }
    }

    /// Notes that this run's port has listened: a run that did is a run that got ready. A machine that will not say what listens leaves it unknown.
    fn watch(port: i64, cell: &Cell, listening: Option<&BTreeSet<i64>>) {
        if let Some(listening) = listening {
            let mut facts = cell.facts();
            facts.listened = Some(facts.listened == Some(true) || listening.contains(&port));
        }
    }

    fn crashed(&self, port: i64, cell: &Cell, status: &Map<String, Value>, mut note: CrashNote, now: f64) {
        note.count += 1;
        // absent-ok: a system that cannot place the moment has no time to show.
        note.at = LocalTime::of(now as i64).map_or_else(String::new, |moment| moment.iso_with_zone());
        let how = ProcessEnd::how(status);
        note.reason = ProcessEnd::reason(status);
        // A run that listened got ready, and the starts before it were not "never ready"; one that was watched and never listened was a start that did not take. A run nobody could watch changes nothing.
        let listened = cell.facts().listened.take();
        match listened {
            Some(true) => note.unready = 0,
            Some(false) => note.unready += 1,
            None => {}
        }
        note.tail = cell.process.log().tail();
        Self::schedule(port, &mut note, now);
        let words = format!("{}\n{how}\n{}", note.reason, note.tail);
        cell.facts().crash = Some(note);
        if status.get("runner").and_then(Value::as_str) != Some("prism") {
            self.suspect.crashed(&words);
        }
    }

    fn schedule(port: i64, note: &mut CrashNote, now: f64) {
        note.restarts.retain(|at| now - *at < Self::WINDOW_SEC as f64);
        let recent = note.restarts.len();
        // A start that takes minutes to die never fills the window: Strata's load ends in a kill after 4 to 8 minutes, and the cell was restarted without end (2026-10-18). Starts that all died before the
        // port ever listened are counted on their own: after BURST restarts that did not take, the next death is the last.
        let never = note.unready > Self::BURST as i64;
        if recent >= Self::BURST || never {
            note.gave_up = true;
            note.never_ready = never && recent < Self::BURST;
            note.due = None;
            if note.never_ready {
                Log::line(&format!(
                    "[watchdog] :{port} never got ready in {} starts — not restarting it: {}",
                    note.count, note.reason
                ));
            } else {
                Log::line(&format!(
                    "[watchdog] :{port} crashed {} times in {} minutes — not restarting it: {}",
                    recent + 1,
                    Self::WINDOW_SEC / 60,
                    note.reason
                ));
            }
        } else {
            note.due = Some(now + Self::RESTART_SEC);
            Log::line(&format!("[watchdog] :{port} crashed ({}) — restarting in {} s", note.reason, Self::RESTART_SEC));
        }
    }

    /// The cell once more: with the settings saved since its start, when they changed, for a cell that failed at its start is what an operator changes them for (2026-11-01: three tries with the old ones). Else its
    /// process as it ran: nothing new to bring, and a controller that does not answer stops nothing.
    fn again(&self, port: i64, cell: &Cell) -> Value {
        let saved = self.cells.saved.of(port);
        match saved {
            SavedStart::Request(request) if cell.facts().request.as_ref() != Some(&request) => {
                Log::line(&format!("[watchdog] :{port} comes back with the settings saved since its start"));
                match Cells::start(&self.cells, request) {
                    Ok(said) => said,
                    Err(error) => json!({"ok": false, "error": error.message}),
                }
            }
            _ => cell.process.relaunch(),
        }
    }

    fn restart(&self, port: i64, cell: &Cell, mut note: CrashNote, now: f64) {
        // Another process of this scout's still runs the port, the cell that was lost and is still loading, or running: the crash was a second copy's, started beside it. Launching a third would load the
        // model once more; the one that runs is held instead.
        let lost = self.cells.survivor(port);
        if lost != 0 {
            Log::line(&format!("[watchdog] :{port} not restarted: pid {lost} still runs it — holding that one"));
            self.cells.adopt_found(port, lost);
            cell.facts().crash = None;
            return;
        }
        let result = self.again(port, cell);
        cell.facts().listened = None;
        note.restarts.push(now);
        note.due = None;
        if result.get("ok") == Some(&Value::Bool(true)) {
            Log::line(&format!("[watchdog] :{port} restarted (pid {})", Coerce::text(result.get("pid"))));
        } else {
            let said = if Coerce::truthy(result.get("error")) {
                Coerce::text(result.get("error"))
            } else {
                "the restart failed".to_string()
            };
            note.reason = Coerce::first_letters(&said, ProcessEnd::REASON_LETTERS).to_string();
            Self::schedule(port, &mut note, now);
        }
        cell.facts().crash = Some(note);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn status(code: Value, words: &str) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert("exitCode".to_string(), code);
        out.insert("lastError".to_string(), json!(words));
        out
    }

    #[test]
    fn an_end_is_said_by_its_signal_its_code_or_that_it_is_not_known() {
        assert_eq!(ProcessEnd::how(&status(json!(-11), "")), "died of SIGSEGV");
        assert_eq!(ProcessEnd::how(&status(json!(3), "")), "exited (code 3)");
        assert_eq!(ProcessEnd::how(&status(Value::Null, "")), "ended with an unknown exit code (adopted after a scout restart)");
    }

    #[test]
    fn a_kill_from_outside_is_said_before_the_logs_last_words() {
        let said = ProcessEnd::reason(&status(json!(-9), "loading"));
        assert!(said.starts_with("died of SIGKILL (killed from outside"), "{said}");
        assert!(said.ends_with(" — its last words: loading"), "{said}");
        assert_eq!(ProcessEnd::reason(&status(json!(1), "out of memory")), "out of memory");
        assert_eq!(ProcessEnd::reason(&status(json!(1), "")), "exited (code 1)");
    }

    #[test]
    fn the_fourth_crash_in_the_window_stays_down() {
        let mut note = CrashNote { count: 1, ..CrashNote::default() };
        Watchdog::schedule(8000, &mut note, 100.0);
        assert_eq!(note.due, Some(110.0));
        note.restarts = vec![1.0, 2.0, 3.0];
        Watchdog::schedule(8000, &mut note, 100.0);
        assert!(note.gave_up && !note.never_ready);
        assert_eq!(note.due, None);
    }

    #[test]
    fn starts_that_never_listen_stop_whatever_the_clock_says() {
        let mut note = CrashNote { count: 5, unready: 4, ..CrashNote::default() };
        Watchdog::schedule(8000, &mut note, 100.0);
        assert!(note.gave_up && note.never_ready);
        let mut old = CrashNote { restarts: vec![1.0, 2.0, 3.0], ..CrashNote::default() };
        Watchdog::schedule(8000, &mut old, 1000.0);
        assert!(!old.gave_up, "restarts past the window do not count");
    }

    #[test]
    fn a_note_of_no_crash_says_nothing() {
        assert_eq!(CrashNote::default().public(), None);
        let note = CrashNote { count: 2, at: "t".into(), reason: "r".into(), gave_up: true, ..CrashNote::default() };
        assert_eq!(note.public(), Some(json!({"count": 2, "at": "t", "reason": "r", "gaveUp": true})));
    }
}
