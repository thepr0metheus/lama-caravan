//! Who listens where, as the OS says it, and what follows from it for an engine.

use crate::engines::kind::EngineKind;
use rules::Coerce;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::net::IpAddr;

/// The rules of a listener's addresses.
pub struct Listening;

impl Listening {
    /// Addresses a port listens on that take connections from anywhere.
    const WILDCARDS: [&'static str; 4] = ["*", "0.0.0.0", "::", "[::]"];
    const MOST_HOPS: u32 = 64;

    /// (port, its listener) worth asking as `kind`: its usual port and the ports its processes listen on; never a cell's.
    pub fn candidates(kind: &dyn EngineKind, rows: Option<&[Value]>, own: &BTreeSet<i64>) -> Vec<(i64, Option<Value>)> {
        let Some(rows) = rows else {
            return if own.contains(&kind.default_port()) { Vec::new() } else { vec![(kind.default_port(), None)] };
        };
        rows.iter()
            .filter_map(|row| row.get("port").and_then(Value::as_i64).map(|port| (port, row)))
            .filter(|(port, row)| !own.contains(port) && (*port == kind.default_port() || kind.is_its_process(row.get("proc"))))
            .map(|(port, row)| (port, Some(row.clone())))
            .collect()
    }

    /// An address as ss or lsof write it, without brackets or interface.
    fn bare(address: &str) -> &str {
        let trimmed = Coerce::strip(address).trim_matches(|letter| matches!(letter, '[' | ']'));
        trimmed.split('%').next().unwrap_or(trimmed)
    }

    fn is_loopback(address: &str) -> bool {
        let bare = Self::bare(address);
        bare.eq_ignore_ascii_case("localhost") || bare.parse::<IpAddr>().is_ok_and(|ip| ip.is_loopback())
    }

    fn addresses(listener: Option<&Value>) -> Vec<String> {
        listener
            .and_then(|listener| listener.get("addrs"))
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|address| Coerce::text(Some(address)))
            .collect()
    }

    /// Where the engine takes connections from: "loopback", this machine only, so that the controller's proxy on another machine cannot reach it, or "network"; "" when the OS did not say.
    pub fn scope(listener: Option<&Value>) -> &'static str {
        let addresses = Self::addresses(listener);
        if addresses.is_empty() {
            ""
        } else if addresses.iter().all(|address| Self::is_loopback(address)) {
            "loopback"
        } else {
            "network"
        }
    }

    /// The address to ask the engine at from this machine: loopback where it listens there or everywhere, else the one address it is bound to.
    pub fn ask_host(listener: Option<&Value>) -> String {
        let addresses = Self::addresses(listener);
        let everywhere = addresses.iter().any(|address| {
            Self::WILDCARDS.contains(&address.as_str()) || (Self::is_loopback(address) && Self::bare(address) != "::1")
        });
        if addresses.is_empty() || everywhere {
            return "127.0.0.1".to_string();
        }
        if addresses.iter().any(|address| Self::bare(address) == "::1") {
            return "[::1]".to_string();
        }
        let bare = addresses.first().map_or("", |address| Self::bare(address));
        if bare.contains(':') { format!("[{bare}]") } else { bare.to_string() }
    }

    /// The engine's processes: the one on its port, those of its name, and everything they started: Ollama's runners, LM Studio's helpers. The cards' memory is attributed through these. Two engines of one kind share what their name claims.
    pub fn pids(kind: &dyn EngineKind, listener: Option<&Value>, processes: Option<&BTreeMap<i64, Value>>) -> Vec<i64> {
        let own = listener.and_then(|listener| listener.get("pid")).and_then(Value::as_i64).filter(|pid| *pid > 0);
        let mut roots: BTreeSet<i64> = own.into_iter().collect();
        let Some(processes) = processes else {
            return roots.into_iter().collect();
        };
        roots.extend(processes.iter().filter(|(_, row)| kind.is_its_process(row.get("name"))).map(|(pid, _)| *pid));
        let mut mine = Vec::new();
        for pid in processes.keys() {
            let (mut current, mut hops) = (*pid, 0);
            while let Some(row) = processes.get(&current).filter(|_| hops < Self::MOST_HOPS) {
                if roots.contains(&current) {
                    mine.push(*pid);
                    break;
                }
                let Some(parent) = row.get("ppid").and_then(Value::as_i64) else {
                    break;
                };
                current = parent;
                hops += 1;
            }
        }
        mine
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn where_an_engine_is_asked_follows_where_it_listens() {
        let of = |addresses: Value| Some(json!({"addrs": addresses}));
        assert_eq!(Listening::ask_host(None), "127.0.0.1");
        assert_eq!(Listening::ask_host(of(json!(["*"])).as_ref()), "127.0.0.1");
        assert_eq!(Listening::ask_host(of(json!(["127.0.0.1"])).as_ref()), "127.0.0.1");
        assert_eq!(Listening::ask_host(of(json!(["[::1]"])).as_ref()), "[::1]");
        assert_eq!(Listening::ask_host(of(json!(["10.0.1.5"])).as_ref()), "10.0.1.5");
        assert_eq!(Listening::ask_host(of(json!(["fe80::1%eth0"])).as_ref()), "[fe80::1]");
    }

    #[test]
    fn the_scope_is_loopback_only_when_every_address_is() {
        assert_eq!(Listening::scope(None), "");
        assert_eq!(Listening::scope(Some(&json!({"addrs": ["127.0.0.1", "::1"]}))), "loopback");
        assert_eq!(Listening::scope(Some(&json!({"addrs": ["127.0.0.1", "*"]}))), "network");
        assert_eq!(Listening::scope(Some(&json!({"addrs": ["localhost"]}))), "loopback");
    }
}
