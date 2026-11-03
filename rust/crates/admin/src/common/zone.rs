//! The caravan's time zone: the one its schedules are written in: TZ in a container, and the machine's own zone natively. The board is told its name, so a browser in another zone draws the same hours the proxy keeps to. And what a container must be told before it may start.

use os::LocalTime;
use rules::{Coerce, WallClock};
use serde_json::{Value, json};
use std::path::Path;

/// The zone schedules are read in. The system's clock keeps it; here is its name and what it says.
#[derive(Debug, Clone)]
pub struct CaravanZone {
    name: String,
    known: bool,
}

impl CaravanZone {
    const ZONES: &'static str = "/usr/share/zoneinfo";

    /// The zone this process keeps time in: TZ when it names a zone; else the machine's own (/etc/localtime, named by the zone file it leads to); else UTC: said as not known, not passed off as the caravan's choice.
    pub fn current(tz: Option<&str>, localtime: &Path) -> Self {
        // absent-ok: no TZ and an empty one read the same: the machine's own zone.
        let said = Coerce::strip(tz.unwrap_or_default()).trim_start_matches(':').to_string();
        if !said.is_empty() && Self::exists(&said) {
            return Self { name: said, known: true };
        }
        let target = std::fs::canonicalize(localtime).map(|path| path.to_string_lossy().into_owned());
        if let Some(name) = target.ok().and_then(|target| target.split_once("zoneinfo/").map(|(_, name)| name.to_string())) {
            return Self { name, known: true };
        }
        Self { name: "UTC".to_string(), known: false }
    }

    /// Whether the system's zone data has this zone.
    pub fn exists(name: &str) -> bool {
        name == "UTC" || (!name.contains("..") && Path::new(Self::ZONES).join(name).is_file())
    }

    /// Its name.
    pub fn name(&self) -> &str {
        &self.name
    }

    /// The zone's offset at `epoch`, in minutes.
    pub fn offset_minutes(&self, epoch: i64) -> i64 {
        // absent-ok: a moment the system cannot place is at no offset: the system's clock stands at UTC then.
        LocalTime::of(epoch).map_or(0, |local| local.offset_minutes)
    }

    /// `epoch` as a person in any zone reads it right: "2026-10-12 19:00 UTC+04:00".
    pub fn text(&self, epoch: i64) -> String {
        let Some(local) = LocalTime::of(epoch) else {
            return String::new();
        };
        let minutes = local.offset_minutes;
        let sign = if minutes >= 0 { '+' } else { '-' };
        format!(
            "{} {:02}:{:02} UTC{sign}{:02}:{:02}",
            local.date(),
            local.hour,
            local.minute,
            minutes.abs() / 60,
            minutes.abs() % 60
        )
    }

    /// What the board is told: the zone's name, whether it is known, and its offset now.
    pub fn state(&self, now: i64) -> Value {
        json!({"name": self.name, "known": self.known, "offsetMinutes": self.offset_minutes(now)})
    }
}

impl WallClock for CaravanZone {
    fn minute_of_week(&self, epoch: f64) -> i64 {
        // absent-ok: a moment the system cannot place reads as the week's first minute, and every schedule says what it says of that.
        LocalTime::of(epoch.trunc() as i64)
            // absent-ok: a moment the system cannot place reads as the week's first minute
            .map_or(0, |local| i64::from(local.weekday) * 1440 + i64::from(local.hour) * 60 + i64::from(local.minute))
    }

    fn epoch_of_week_minute(&self, epoch: f64, minute: i64) -> i64 {
        // absent-ok: the same moment: a window that opens "now" is no worse a word for a moment the system cannot place.
        LocalTime::epoch_of_week_minute(epoch.trunc() as i64, minute).unwrap_or(epoch.trunc() as i64)
    }

    fn text(&self, epoch: i64) -> String {
        CaravanZone::text(self, epoch)
    }
}

/// The two settings a container cannot guess, checked before anything starts. Without a zone every schedule fires hours off; without an address the agents are handed http://127.0.0.1:<port>, which leads nowhere from their machines. So in a container both must be stated, or the process does not start and says why.
pub struct ContainerPreflight;

impl ContainerPreflight {
    const ADDRESS_VAR: &'static str = "LLAMA_TOPOLOGY_SERVER_IP";

    /// Whether this process runs in the caravan's container: the one place that reads it.
    pub fn in_container(said: Option<&str>) -> bool {
        // absent-ok: the variable not set is not "1".
        Coerce::strip(said.unwrap_or_default()) == "1"
    }

    fn zone_problem(tz: &str) -> Option<String> {
        let name = Coerce::strip(tz);
        if name.is_empty() {
            return Some("TZ is not set: the container would run in UTC and every schedule would fire hours off. Set TZ to this controller's time zone, e.g. TZ=Europe/Berlin (TZ=UTC when UTC is meant)".to_string());
        }
        (!CaravanZone::exists(name.trim_start_matches(':')))
            .then(|| format!("TZ={name}: no such time zone in this image's zone data"))
    }

    fn address_problem(address: &str) -> Option<String> {
        let var = Self::ADDRESS_VAR;
        let raw = Coerce::strip(address);
        if raw.is_empty() {
            return Some(format!(
                "{var} is not set: agents would be handed http://127.0.0.1:<port>, which leads nowhere from their machines. Set it to this machine's LAN address"
            ));
        }
        let itself = raw.to_lowercase() == "localhost"
            || raw.parse::<std::net::IpAddr>().is_ok_and(|ip| ip.is_loopback() || ip.is_unspecified());
        itself.then(|| format!("{var}={raw}: that is this container itself, not an address the fleet reaches"))
    }

    /// Why this process may not start, or nothing: outside a container always nothing.
    pub fn problems(in_container: bool, tz: &str, address: &str) -> Vec<String> {
        if !in_container {
            return Vec::new();
        }
        [Self::zone_problem(tz), Self::address_problem(address)].into_iter().flatten().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_container_is_told_its_zone_and_its_address() {
        assert!(ContainerPreflight::problems(false, "", "").is_empty());
        let both = ContainerPreflight::problems(true, "", "");
        assert_eq!(both.len(), 2);
        assert!(both.first().unwrap().starts_with("TZ is not set"));
        assert!(ContainerPreflight::problems(true, "UTC", "127.0.0.1").first().unwrap().contains("this container itself"));
        assert!(ContainerPreflight::problems(true, "UTC", "0.0.0.0").first().unwrap().contains("this container itself"));
        assert!(ContainerPreflight::problems(true, "UTC", "caravan.home.arpa").is_empty());
        assert!(ContainerPreflight::problems(true, "UTC", "10.0.0.5").is_empty());
    }
}
