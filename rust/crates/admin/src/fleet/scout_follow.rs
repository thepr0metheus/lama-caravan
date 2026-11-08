//! A machine's scout follows the release this controller carries (the owner, 2026-11-08, of an update after each delivery: "yes, do it"). A
//! delivery restarts this controller on a new release; the next report of each machine finds its scout behind, and the scout is handed the
//! release as the ⋯ menu's Update the scout hands it. It rides on the machines' reports and keeps no timer of its own.
//!
//! Only what changed is handed. A release says what its scout is (BundleFacts' content, written by deploy/nas/release_ship.py): the same
//! program under another commit is not handed, a restart would bring nothing. A machine whose release is not kept here to compare with is
//! handed the new one. A release that does not say what its scout is, one built before the script said it, is handed from the ⋯ menu alone.
//!
//! A scout busy for now refuses with 409, a cell on its way up or a job of its own (own_release.rs): it is asked again at a report RETRY_SEC
//! later, TRIES times at the most in one run of this controller. Any other refusal is said once, in the log, and left to the ⋯ menu. The menu's
//! press is the same cycle by hand (the owner, 2026-11-08: the menu, with the cycle): a busy scout is asked again just so, instead of refused.
//! `CARAVAN_SCOUT_FOLLOW=off` turns off what the controller does by itself; the menu still works.

use super::scout_bundle::{NotTaken, ScoutBundle};
use crate::app::App;
use plumbing::log::Log;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::sync::{Mutex, PoisonError};

/// Why a scout is handed the release.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Change {
    /// Its program or its scripts are not the ones the machine runs.
    Changed,
    /// The release the machine runs is not kept here, or does not say what its scout is: there is nothing to compare with.
    Unknown,
    /// The operator asked, from the ⋯ menu, and the scout was busy then.
    ByHand,
}

impl Change {
    fn words(self) -> &'static str {
        match self {
            Self::Changed => "its scout changed",
            Self::Unknown => "the release it runs cannot be compared with this one",
            Self::ByHand => "asked from the ⋯ menu",
        }
    }
}

/// What one report of a machine leads to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Follow {
    /// Hand the machine the release.
    Hand(Change),
    /// The same scout under another commit: said once, and nothing is handed.
    Same,
    /// Not now: a hand-out is in flight, or the scout said "not now" a moment ago.
    Wait,
    /// Nothing more in this run: taken, refused, asked TRIES times, or said to be the same.
    Settled,
    /// Nothing to follow: no release, a scout that does not say its own, one that runs this release already, or a release that does not say
    /// what its scout is and nobody asked for.
    Nothing,
}

/// What this run did about one machine.
#[derive(Debug, Clone, PartialEq)]
struct Handing {
    /// The release it was about: another release starts afresh.
    release: String,
    change: Change,
    tries: u32,
    /// When the last try started, on the monotonic clock.
    tried_at: f64,
    in_flight: bool,
    settled: bool,
}

/// The machines' hand-outs in this run of the controller. Kept in memory: a restart, a new delivery among them, asks afresh.
#[derive(Default)]
pub struct ScoutFollow {
    machines: Mutex<HashMap<String, Handing>>,
}

impl ScoutFollow {
    /// How long a scout that said "not now" is left alone, seconds.
    pub const RETRY_SEC: f64 = 120.0;
    /// How often one release is offered to a busy scout in one run: half an hour, in which a cell is up and a job is done.
    pub const TRIES: u32 = 15;
    /// The environment's word that turns following off.
    const SWITCH: &'static str = "CARAVAN_SCOUT_FOLLOW";

    /// What a report leads to, from values alone: `release` the commit this controller hands out (`None`: none), `says` whether its release
    /// says what its scout is, `running` the commit the machine's scout says, `same` whether the two are one scout (`None`: cannot tell; asked
    /// only when it matters, it reads a release folder), `handing` what this run did about the machine, `now` the monotonic clock.
    fn decide(
        release: Option<&str>,
        says: bool,
        running: &str,
        same: impl FnOnce() -> Option<bool>,
        handing: Option<&Handing>,
        now: f64,
    ) -> Follow {
        let Some(release) = release.filter(|release| !running.is_empty() && *release != running) else {
            return Follow::Nothing;
        };
        if let Some(handing) = handing.filter(|handing| handing.release == release) {
            if handing.in_flight {
                return Follow::Wait;
            }
            if handing.settled || handing.tries >= Self::TRIES {
                return Follow::Settled;
            }
            if now - handing.tried_at < Self::RETRY_SEC {
                return Follow::Wait;
            }
            return Follow::Hand(handing.change);
        }
        if !says {
            return Follow::Nothing;
        }
        match same() {
            Some(true) => Follow::Same,
            Some(false) => Follow::Hand(Change::Changed),
            None => Follow::Hand(Change::Unknown),
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, Handing>> {
        self.machines.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// One report of `host_id`, decided and kept under one lock: two reports at once, a beat and a pull, hand the release once. The tries of one
    /// release add up.
    fn step(
        &self,
        host_id: &str,
        release: Option<&str>,
        says: bool,
        running: &str,
        same: impl FnOnce() -> Option<bool>,
        now: f64,
    ) -> Follow {
        let mut machines = self.lock();
        let before = machines.get(host_id);
        let follow = Self::decide(release, says, running, same, before, now);
        if let (Some(release), Follow::Hand(_) | Follow::Same) = (release, follow) {
            // absent-ok: a machine this run did nothing about has tried nothing.
            let tries = before.filter(|handing| handing.release == release).map_or(0, |handing| handing.tries);
            let (change, in_flight) = if let Follow::Hand(change) = follow { (change, true) } else { (Change::Changed, false) };
            let handing =
                Handing { release: release.to_string(), change, tries: tries + 1, tried_at: now, in_flight, settled: !in_flight };
            machines.insert(host_id.to_string(), handing);
        }
        follow
    }

    /// A press of the menu begins a hand-out: in flight, so that a report meanwhile does not hand it again, and a fresh round of tries from it.
    /// `false` when one is under way already.
    fn begin_by_hand(&self, host_id: &str, release: &str, now: f64) -> bool {
        let mut machines = self.lock();
        if machines.get(host_id).is_some_and(|handing| handing.release == release && handing.in_flight) {
            return false;
        }
        let handing = Handing {
            release: release.to_string(),
            change: Change::ByHand,
            tries: 1,
            tried_at: now,
            in_flight: true,
            settled: false,
        };
        machines.insert(host_id.to_string(), handing);
        true
    }

    /// What the scout said to a hand-out, kept so that the next report knows; the words for the log, none for a hand-out nobody waits for.
    fn settled(&self, host_id: &str, release: &str, said: &Result<Value, NotTaken>) -> Option<String> {
        let mut machines = self.lock();
        let handing = machines.get_mut(host_id).filter(|handing| handing.release == release)?;
        handing.in_flight = false;
        let again = said.as_ref().err().is_some_and(NotTaken::busy) && handing.tries < Self::TRIES;
        handing.settled = !again;
        Some(match said {
            Ok(said) => format!("{host_id} took {release}: {}, and its next report names it", Self::restarts(said)),
            Err(refusal) if again => format!(
                "{host_id} does not take {release} now ({}): asked again at a report {} s on, try {} of {}",
                refusal.words(),
                Self::RETRY_SEC,
                handing.tries,
                Self::TRIES
            ),
            Err(refusal) => format!(
                "{host_id} did not take {release} ({}): the ⋯ menu of its page, Update the scout, asks again",
                refusal.words()
            ),
        })
    }

    /// When a scout that took the release restarts, as it said: at once, or once what passes through it is done, its `waitsFor` (own_release.rs).
    /// A figure it does not say is said as unknown, not guessed.
    fn restarts(said: &Value) -> String {
        let Some(waits) = said.get("waitsFor") else {
            return "its scout restarts".to_string();
        };
        let words: Vec<&str> =
            waits.get("words").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str).collect();
        let most =
            waits.get("mostSec").and_then(Value::as_f64).map_or_else(|| "an unsaid time".to_string(), |most| format!("{most} s"));
        format!("its scout restarts once what passes through it is done ({}), {most} at the most", words.join(", "))
    }

    /// After a report of `host_id` was kept: hands the machine this controller's release when its scout is behind, as the ⋯ menu would. Quick:
    /// the hand-out runs on a thread of its own, since the scout fetches the bundle before it answers.
    pub fn heard(app: &App, host_id: &str, report: &Value) {
        if app.env.get(Self::SWITCH) == Some("off") {
            return;
        }
        let bundle = ScoutBundle::of(app);
        let facts = bundle.facts();
        let release = facts.as_ref().map(|facts| facts.commit().to_string());
        let says = facts.as_ref().is_some_and(|facts| facts.says_content());
        let running = Coerce::stripped(report.get("scoutCommit"));
        let now = app.clock.monotonic();
        let follow = app.scout_follow.step(host_id, release.as_deref(), says, &running, || bundle.same_scout(&running), now);
        let Some(release) = release.filter(|_| matches!(follow, Follow::Hand(_) | Follow::Same)) else {
            return;
        };
        if let Follow::Hand(change) = follow {
            Log::line(&format!("[scout-release] {host_id} runs {running}: hands it {release}, {}", change.words()));
            Self::hand(app, host_id, &release);
        } else {
            Log::line(&format!("[scout-release] {host_id} runs {running}, the same scout as {release}: nothing to hand"));
        }
    }

    /// The ⋯ menu's Update the scout. The scout takes the release now; one busy for now is not refused: the reports take it over, asked again
    /// RETRY_SEC apart, TRIES times, and the answer says so (`waiting`). Its other refusals are the board's as before.
    pub fn by_hand(app: &App, host_id: &str) -> Result<Value, AppError> {
        let bundle = ScoutBundle::of(app);
        let release = bundle.facts().map(|facts| facts.commit().to_string());
        if let Some(release) = release.as_deref()
            && !app.scout_follow.begin_by_hand(host_id, release, app.clock.monotonic())
        {
            return Err(AppError::with_status(
                format!("{release} is being handed to {host_id} already: its answer comes in a moment"),
                409,
            ));
        }
        let said = bundle.update(host_id);
        if let Some(release) = release.as_deref() {
            Self::told(app, host_id, release, &said);
        }
        match said {
            Ok(said) => Ok(said),
            Err(refusal) if refusal.busy() => {
                let waiting = json!({"words": refusal.words(), "retrySec": Self::RETRY_SEC, "tries": Self::TRIES});
                Ok(json!({"ok": true, "commit": release, "restarting": false, "waiting": waiting}))
            }
            Err(refusal) => Err(refusal.answered()),
        }
    }

    /// The hand-out, on a thread of its own; what it ends with is kept (`settled`) whichever way it ends.
    fn hand(app: &App, host_id: &str, release: &str) {
        let Some(shared) = app.shared() else {
            Self::told(app, host_id, release, &Err(NotTaken::Controller(AppError::new("the controller is ending"))));
            return;
        };
        let (host, handed) = (host_id.to_string(), release.to_string());
        let started = std::thread::Builder::new().name("scout-follow".to_string()).spawn(move || {
            let said = ScoutBundle::of(&shared).update(&host);
            Self::told(&shared, &host, &handed, &said);
        });
        if let Err(error) = started {
            let refusal = NotTaken::Controller(AppError::new(format!("no thread for the hand-out: {error}")));
            Self::told(app, host_id, release, &Err(refusal));
        }
    }

    fn told(app: &App, host_id: &str, release: &str, said: &Result<Value, NotTaken>) {
        if let Some(words) = app.scout_follow.settled(host_id, release, said) {
            Log::line(&format!("[scout-release] {words}"));
        }
    }
}

#[cfg(test)]
mod tests;
