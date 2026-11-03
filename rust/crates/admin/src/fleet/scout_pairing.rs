//! Adding a machine's scout from the board, and letting it go.

use super::machine_settings::MachineSettings;
use super::scout::ScoutAuth;
use crate::app::App;
use crate::store::topology::Topology;
use plumbing::http_client::HttpError;
use rules::{AppError, Coerce, PyRepr, PythonJson};
use serde_json::{Value, json};
use std::net::{IpAddr, UdpSocket};
use std::time::Duration;

/// The one way a machine joins the fleet as a scout host.
pub struct ScoutPairing<'app> {
    app: &'app App,
}

impl<'app> ScoutPairing<'app> {
    const DEFAULT_PORT: i64 = 8092;

    /// The pairing of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn is_host_word(host: &str) -> bool {
        let bytes = host.as_bytes();
        let edge = |byte: Option<&u8>| byte.is_some_and(u8::is_ascii_alphanumeric);
        !bytes.is_empty()
            && bytes.len() <= 253
            && edge(bytes.first())
            && edge(bytes.last())
            && bytes.iter().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-'))
    }

    /// `http://host:port` of a scout from what the operator typed.
    pub fn scout_url(raw_address: Option<&Value>, raw_port: Option<&Value>) -> Result<String, AppError> {
        let text = Coerce::stripped(raw_address);
        let bare = match text.find("://") {
            Some(at)
                if text
                    .get(..at)
                    .is_some_and(|scheme| !scheme.is_empty() && scheme.chars().all(|letter| letter.is_ascii_alphabetic())) =>
            {
                text.get(at + 3..).unwrap_or("")
            }
            _ => text.as_str(),
        };
        let place = bare.split('/').next().unwrap_or(bare);
        let (host, typed_port) = place.split_once(':').unwrap_or((place, ""));
        if !Self::is_host_word(host) {
            return Err(AppError::new("enter the machine's address — an IP or a host name"));
        }
        let said = if Coerce::truthy(raw_port) { Coerce::str_of(raw_port) } else { String::new() };
        let port = if !said.is_empty() {
            said
        } else if !typed_port.is_empty() {
            typed_port.to_string()
        } else {
            Self::DEFAULT_PORT.to_string()
        };
        let port = Coerce::strip(&port);
        let number = port
            .parse::<i64>()
            .ok()
            .filter(|number| (1..=65535).contains(number) && port.chars().all(|digit| digit.is_ascii_digit()));
        let number = number.ok_or_else(|| AppError::new("the port must be a number from 1 to 65535"))?;
        Ok(format!("http://{host}:{number}"))
    }

    fn is_loopback(host: &str) -> bool {
        host == "localhost" || host.parse::<IpAddr>().is_ok_and(|address| address.is_loopback())
    }

    fn is_controller_url(url: &str) -> bool {
        let Some(rest) = url.strip_prefix("https://").or_else(|| url.strip_prefix("http://")) else {
            return false;
        };
        let (host, port) = rest.split_once(':').map_or((rest, None), |(host, port)| (host, Some(port)));
        Self::is_host_word(host)
            && port.is_none_or(|port| (1..=5).contains(&port.len()) && port.chars().all(|digit| digit.is_ascii_digit()))
    }

    /// The address of this machine facing `host`.
    fn facing_ip(host: &str) -> Result<String, AppError> {
        let route = || -> std::io::Result<String> {
            let socket = UdpSocket::bind("0.0.0.0:0")?;
            socket.connect((host, 9))?;
            Ok(socket.local_addr()?.ip().to_string())
        };
        route().map_err(|error| AppError::with_status(format!("no route from the controller to {host}: {error}"), 502))
    }

    /// The controller as the scout will reach it.
    fn controller_url_for(&self, scout_url: &str) -> Result<String, AppError> {
        let bare = scout_url.split_once("://").map_or(scout_url, |(_, rest)| rest);
        let host = bare.rsplit_once(':').map_or(bare, |(host, _)| host);
        let port = self.app.paths.port;
        if Self::is_loopback(host) {
            return Ok(format!("http://127.0.0.1:{port}"));
        }
        let advertised_url = Coerce::strip(&self.app.paths.topology_server_url).trim_end_matches('/').to_string();
        if !advertised_url.is_empty() {
            if !Self::is_controller_url(&advertised_url) {
                return Err(AppError::with_status(
                    format!(
                        "LLAMA_TOPOLOGY_SERVER_URL must be http(s)://host or http(s)://host:port, not {} — fix it in the controller's settings",
                        PyRepr::of(&advertised_url)
                    ),
                    500,
                ));
            }
            return Ok(advertised_url);
        }
        let advertised_ip = Coerce::strip(&self.app.paths.topology_server_ip);
        let ip = if !advertised_ip.is_empty() && !Self::is_loopback(advertised_ip) {
            advertised_ip.to_string()
        } else {
            Self::facing_ip(host)?
        };
        Ok(format!("http://{ip}:{port}"))
    }

    fn words(failure: &HttpError) -> String {
        if let HttpError::Status(_, said) = failure
            && let Ok(body) = serde_json::from_str::<Value>(said)
            && Coerce::truthy(body.get("error"))
        {
            return Coerce::str_of(body.get("error"));
        }
        failure.to_string()
    }

    /// What the scout says about itself before anything is changed.
    fn pairing_info(&self, url: &str) -> Result<Value, AppError> {
        let other = || AppError::with_status(format!("something other than a caravan-scout answers at {url}"), 502);
        let answer = self.app.http.ask("GET", &format!("{url}/api/pairing"), &[], &[], Duration::from_secs(5));
        let raw = match answer.and_then(|answer| answer.text(1 << 20).map_err(HttpError::Io)) {
            Ok(raw) => raw,
            Err(HttpError::Status(404, _)) => {
                return Err(AppError::with_status(
                    format!("a scout older than 2.0 answers at {url} — update it: git pull and ./install.sh on that machine"),
                    409,
                ));
            }
            Err(HttpError::Status(code, _)) => {
                return Err(AppError::with_status(format!("{url} answered {code} — not a caravan-scout"), 502));
            }
            Err(other_error) => {
                return Err(AppError::with_status(
                    format!("no scout answers at {url}: {other_error} — is ./install.sh done there, and is the port open?"),
                    502,
                ));
            }
        };
        let info: Value = if raw.is_empty() { json!({}) } else { serde_json::from_slice(&raw).map_err(|_| other())? };
        if info.get("service").and_then(Value::as_str) != Some("caravan-scout") {
            return Err(other());
        }
        Ok(info)
    }

    fn post(&self, url: &str, payload: &Value, timeout: u64) -> Result<Value, HttpError> {
        let mut fields = vec![("Content-Type", "application/json".to_string())];
        fields.extend(ScoutAuth::fields(self.app));
        let raw = self
            .app
            .http
            .ask("POST", url, &fields, PythonJson::spaced(payload).as_bytes(), Duration::from_secs(timeout))?
            .text(1 << 20)?;
        if raw.is_empty() {
            return Ok(json!({"ok": true}));
        }
        serde_json::from_slice(&raw).map_err(|error| HttpError::Io(std::io::Error::new(std::io::ErrorKind::InvalidData, error)))
    }

    /// A machine's scout told where its controller is, and heard back from.
    pub fn connect(&self, raw_address: Option<&Value>, raw_port: Option<&Value>) -> Result<Value, AppError> {
        let url = Self::scout_url(raw_address, raw_port)?;
        let info = self.pairing_info(&url)?;
        let controller = self.controller_url_for(&url)?;
        let token = ScoutAuth::fields(self.app)
            .into_iter()
            .find(|(name, _)| *name == "X-Caravan-Token")
            .map_or_else(String::new, |(_, token)| token);
        // Read before the scout is told anything: its first report writes its own settings over them, and a new scout's are the defaults.
        let kept = MachineSettings::of(self.app).kept(&Coerce::text(info.get("hostId")));
        let answer = self.post(&format!("{url}/api/controller-url"), &json!({"url": controller, "token": token}), 20).map_err(|failure| match &failure {
            HttpError::Status(401, _) => AppError::with_status(
                format!("the scout at {url} is paired with another controller (it holds a different fleet token) — take it off there first, or on that machine run ./uninstall.sh and ./install.sh"),
                409,
            ),
            HttpError::Status(..) => AppError::with_status(format!("the scout at {url} refused: {}", Self::words(&failure)), 502),
            other => AppError::with_status(format!("the scout at {url} stopped answering: {other}"), 502),
        })?;
        let empty = json!({});
        let beat = answer.get("heartbeat").filter(|beat| beat.is_object()).unwrap_or(&empty);
        if beat.get("state").and_then(Value::as_str) != Some("ok") {
            let what = if self.app.paths.topology_server_url.is_empty() {
                format!("open port {} on the controller to that machine", self.app.paths.port)
            } else {
                format!("check that {controller} answers on that machine — its name, the reverse proxy, the home certificate")
            };
            let said = Coerce::text(beat.get("error"));
            let said = if said.is_empty() { "no answer".to_string() } else { said };
            return Err(AppError::with_status(
                format!("the scout at {url} took the controller's address ({controller}) but cannot reach it: {said} — {what}"),
                502,
            ));
        }
        let host = beat
            .get("result")
            .filter(|result| result.is_object())
            .and_then(|result| result.get("host"))
            .filter(|host| Coerce::truthy(Some(*host)));
        let either = |key: &str, other_key: &str| {
            let said = host.and_then(|host| host.get(key)).filter(|said| Coerce::truthy(Some(*said)));
            said.or_else(|| info.get(other_key).filter(|said| Coerce::truthy(Some(*said)))).cloned().unwrap_or_else(|| json!(""))
        };
        let mut paired = json!({
            "ok": true, "hostId": either("id", "hostId"), "name": either("name", "hostId"),
            "scoutVersion": either("scoutVersion", "version"), "scoutCommit": either("scoutCommit", "scoutCommit"), "scoutUrl": url, "controllerUrl": controller,
        });
        let (back, not_back) = MachineSettings::of(self.app).give_back(&Coerce::text(paired.get("hostId")), kept.as_ref());
        if !back.is_empty() {
            Coerce::put(&mut paired, "settingsBack", json!(back));
        }
        if !not_back.is_empty() {
            Coerce::put(&mut paired, "settingsNotBack", json!(not_back));
        }
        Ok(paired)
    }

    /// A scout let go, and its record with it.
    pub fn disconnect(&self, host_id: &str) -> Result<Value, AppError> {
        let host_id = Coerce::strip(host_id);
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(host_id).cloned());
        let host = host.ok_or_else(|| AppError::with_status(format!("host not found: {host_id}"), 404))?;
        let agent_url = Coerce::text(host.get("agentUrl")).trim_end_matches('/').to_string();
        let mut unpaired = false;
        if !agent_url.is_empty() {
            match self.post(&format!("{agent_url}/api/unpair"), &json!({}), 10) {
                Ok(_) => unpaired = true,
                Err(HttpError::Status(404, _)) => {}
                Err(failure @ HttpError::Status(..)) => {
                    return Err(AppError::with_status(
                        format!("the scout of {host_id} refused to let go: {}", Self::words(&failure)),
                        502,
                    ));
                }
                Err(_) => {}
            }
        }
        self.app.admin.saving(|doc| {
            Topology::of(doc).hosts().shift_remove(host_id);
        });
        Ok(json!({"ok": true, "hostId": host_id, "unpaired": unpaired}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_scout_s_address_reads_from_what_was_typed() {
        let url = |address: &str, port: Option<Value>| ScoutPairing::scout_url(Some(&json!(address)), port.as_ref());
        assert_eq!(url("10.0.0.1", None).unwrap(), "http://10.0.0.1:8092");
        assert_eq!(url("HTTP://box.home:9000/x", None).unwrap(), "http://box.home:9000");
        assert_eq!(url("box", Some(json!(8100))).unwrap(), "http://box:8100");
        assert!(url("", None).is_err());
        assert!(url("-bad", None).is_err());
        assert!(url("box:99999", None).is_err());
    }

    #[test]
    fn a_controller_url_has_no_path() {
        assert!(ScoutPairing::is_controller_url("https://caravan.home"));
        assert!(ScoutPairing::is_controller_url("http://a:7990"));
        assert!(!ScoutPairing::is_controller_url("https://a/x"));
        assert!(!ScoutPairing::is_controller_url("a:7990"));
        assert!(ScoutPairing::is_loopback("127.0.0.9"));
        assert!(ScoutPairing::is_loopback("localhost"));
        assert!(!ScoutPairing::is_loopback("10.0.0.1"));
    }
}
