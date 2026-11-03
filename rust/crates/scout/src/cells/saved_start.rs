//! What a cell that starts by itself starts with. A cell's settings are the controller's: the scout asks it for the request of the settings as they are saved now, and a start by the watchdog or at the machine's boot
//! goes by that. Before this a cell that failed at its start was tried again with what it had failed with, whatever the operator had saved since (2026-11-01), and a machine that was off while settings changed came
//! up with the old ones.

use crate::config::ScoutConfig;
use crate::http_client::HttpClient;
use rules::Coerce;
use serde_json::{Map, Value};
use std::sync::Arc;
use std::time::Duration;
use wire::Percent;

/// What the controller says of a cell's start.
#[derive(Debug, PartialEq)]
pub enum SavedStart {
    /// The request of its settings as they are now.
    Request(Map<String, Value>),
    /// It has no such cell.
    NoCell,
    /// It did not say: it does not answer, or the cell cannot be started as it stands. The machine goes by what it has.
    NotKnown,
}

/// The asking.
pub struct SavedStarts {
    config: Arc<ScoutConfig>,
    http: Arc<HttpClient>,
}

impl SavedStarts {
    /// A start must not wait long for a controller that is not there: the machine boots, or a cell is down.
    const TIMEOUT: Duration = Duration::from_secs(5);

    /// The asking of this scout's controller.
    pub fn new(config: Arc<ScoutConfig>, http: Arc<HttpClient>) -> Self {
        Self { config, http }
    }

    /// What the controller says of the cell on `port`.
    pub fn of(&self, port: i64) -> SavedStart {
        let controller = self.config.text("controllerUrl");
        let controller = controller.trim_end_matches('/');
        if controller.is_empty() {
            return SavedStart::NotKnown;
        }
        let url =
            format!("{controller}/api/fleet/cell-start?hostId={}&port={port}", Percent::encode(&self.config.text("hostId")));
        let token = self.config.token();
        let fields: Vec<(&str, String)> = if token.is_empty() { Vec::new() } else { vec![("X-Caravan-Token", token)] };
        let Ok(said) = self.http.json("GET", &url, &fields, &[], Self::TIMEOUT) else {
            return SavedStart::NotKnown;
        };
        if !Coerce::truthy(said.get("ok")) {
            return SavedStart::NotKnown;
        }
        match said.get("request") {
            Some(Value::Object(request)) => SavedStart::Request(request.clone()),
            Some(Value::Null) => SavedStart::NoCell,
            _ => SavedStart::NotKnown,
        }
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, reason = "a helper of a test may stop where it found something wrong")]

    use super::*;
    use crate::tests::{StandIn, TestFolder};
    use serde_json::json;
    use std::fs;

    fn asking(folder: &TestFolder, controller: &str) -> SavedStarts {
        fs::write(
            folder.path.join("config.json"),
            json!({"controllerUrl": controller, "controllerToken": "fleet", "hostId": "the box"}).to_string(),
        )
        .unwrap();
        let config = Arc::new(ScoutConfig::load(&folder.path.join("config.json")).unwrap());
        SavedStarts::new(config, Arc::new(HttpClient::new()))
    }

    #[test]
    fn the_controller_is_asked_for_the_cell_by_name_and_port_with_the_fleet_s_token() {
        let folder = TestFolder::new("saved-asks");
        let said = json!({"ok": true, "request": {"port": 5, "modelPath": "m"}});
        let controller = StandIn::serving(move |_| StandIn::answer("200 OK", said.to_string().as_bytes()));
        let got = asking(&folder, controller.address()).of(5);
        assert_eq!(
            got,
            SavedStart::Request(Map::from_iter([("port".to_string(), json!(5)), ("modelPath".to_string(), json!("m"))]))
        );
        assert_eq!(controller.targets(), ["/api/fleet/cell-start?hostId=the%20box&port=5"]);
        assert!(controller.asked()[0].contains("X-Caravan-Token: fleet"));
    }

    #[test]
    fn no_such_cell_is_said_and_every_other_silence_is_not_known() {
        let folder = TestFolder::new("saved-silence");
        let answering = |body: Value| StandIn::serving(move |_| StandIn::answer("200 OK", body.to_string().as_bytes()));
        let none = answering(json!({"ok": true, "request": null}));
        assert_eq!(asking(&folder, none.address()).of(5), SavedStart::NoCell);
        let cannot = answering(json!({"ok": false, "error": "cell has no saved model"}));
        assert_eq!(
            asking(&folder, cannot.address()).of(5),
            SavedStart::NotKnown,
            "it cannot be started as it stands: the machine goes by what it has"
        );
        let old = StandIn::serving(|_| StandIn::answer("404 Not Found", b"nothing here"));
        assert_eq!(
            asking(&folder, old.address()).of(5),
            SavedStart::NotKnown,
            "a controller of before this asks nothing of anybody"
        );
        let strange = answering(json!({"ok": true}));
        assert_eq!(asking(&folder, strange.address()).of(5), SavedStart::NotKnown);
        assert_eq!(asking(&folder, "").of(5), SavedStart::NotKnown, "no controller named");
        assert_eq!(asking(&folder, "http://127.0.0.1:9").of(5), SavedStart::NotKnown, "nobody there");
    }
}
