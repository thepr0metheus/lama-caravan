//! The machine this controller runs on, among the machines with a scout.

use crate::app::App;
use rules::Coerce;
use serde_json::Value;

/// Which scout's machine is the one this controller runs on.
pub struct ControllerMachine {
    hostname: String,
}

impl ControllerMachine {
    /// This computer, by its name.
    pub fn new(hostname: &str) -> Self {
        Self { hostname: Self::short(hostname) }
    }

    /// The computer `app` runs on.
    pub fn of(app: &App) -> Self {
        Self::new(&app.hostname())
    }

    fn short(name: &str) -> String {
        name.split('.').next().map_or_else(String::new, |first| Coerce::strip(first).to_lowercase())
    }

    /// This computer's name as the board shows it.
    pub fn name(hostname: &str) -> String {
        hostname.split('.').next().map_or_else(String::new, |first| Coerce::strip(first).to_string())
    }

    /// True when `host`, a host record, is this controller's machine.
    pub fn is_host(&self, host: &Value) -> bool {
        !self.hostname.is_empty() && host.is_object() && Self::short(&Coerce::text(host.get("hostname"))) == self.hostname
    }

    /// The id of this controller's machine among `hosts`; empty when no scout reports from it.
    pub fn host_id<'hosts>(&self, hosts: impl Iterator<Item = &'hosts Value>) -> String {
        let mut rows = hosts;
        rows.find(|host| self.is_host(host)).map_or_else(String::new, |host| Coerce::text(host.get("id")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_machine_is_known_by_its_short_name() {
        let here = ControllerMachine::new("Box.local");
        assert!(here.is_host(&json!({"hostname": "box"})));
        assert!(!here.is_host(&json!({"hostname": "other"})));
        assert!(!ControllerMachine::new("").is_host(&json!({"hostname": ""})));
        let hosts = [json!({"id": "a", "hostname": "x"}), json!({"id": "b", "hostname": "BOX.home"})];
        assert_eq!(here.host_id(hosts.iter()), "b");
        assert_eq!(ControllerMachine::name("Box.local"), "Box");
    }
}
