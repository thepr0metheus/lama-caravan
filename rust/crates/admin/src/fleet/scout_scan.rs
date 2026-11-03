//! Finding the scouts on the local network.

use crate::app::App;
use crate::store::topology::Topology;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::net::{Ipv4Addr, SocketAddr, TcpStream, UdpSocket};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

/// A network of the scan.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
struct Network {
    base: u32,
    bits: u32,
}

impl Network {
    fn read(word: &str) -> Option<Self> {
        let (address, bits) = word.split_once('/').map_or((word, "32"), |(address, bits)| (address, bits));
        let address: Ipv4Addr = address.parse().ok()?;
        let bits: u32 = bits.parse().ok().filter(|bits| *bits <= 32)?;
        // absent-ok: a mask of no bits covers everything.
        let mask = u32::MAX.checked_shl(32 - bits).unwrap_or(0);
        Some(Self { base: u32::from(address) & mask, bits })
    }

    fn size(self) -> u64 {
        1u64 << (32 - self.bits)
    }

    fn is_private(self) -> bool {
        let address = Ipv4Addr::from(self.base);
        address.is_private() && !address.is_loopback()
    }

    /// The addresses a machine can have: not the network's own and its broadcast, in a network large enough to have them.
    fn hosts(self) -> Vec<u32> {
        match self.bits {
            32 => vec![self.base],
            31 => vec![self.base, self.base + 1],
            _ => (self.base + 1..self.base + (1u32 << (32 - self.bits)) - 1).collect(),
        }
    }

    fn word(self) -> String {
        format!("{}/{}", Ipv4Addr::from(self.base), self.bits)
    }
}

/// Which machines of a private network answer as a caravan-scout (the owner, 2026-10-11).
pub struct ScoutScan<'app> {
    app: &'app App,
}

impl<'app> ScoutScan<'app> {
    const DEFAULT_PORT: i64 = 8092;
    const MAX_ADDRESSES: u64 = 1024;
    const CONNECT_TIMEOUT: Duration = Duration::from_millis(400);
    const ASK_TIMEOUT: Duration = Duration::from_secs(2);
    const WORKERS: usize = 64;

    /// The scan of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The controller's own addresses.
    pub fn own_addresses(advertised_ip: &str) -> Vec<String> {
        let mut out = Vec::new();
        let route = || -> std::io::Result<String> {
            let socket = UdpSocket::bind("0.0.0.0:0")?;
            socket.connect(("8.8.8.8", 9))?;
            Ok(socket.local_addr()?.ip().to_string())
        };
        if let Ok(address) = route() {
            out.push(address);
        }
        if !advertised_ip.is_empty() && !out.iter().any(|held| held == advertised_ip) {
            out.push(advertised_ip.to_string());
        }
        out.retain(|address| !address.is_empty() && !address.starts_with("127."));
        out
    }

    fn networks(raw: &str, own: &[String]) -> Result<Vec<Network>, AppError> {
        let mut words: Vec<String> = raw
            .split(|letter: char| letter.is_whitespace() || matches!(letter, ',' | ';'))
            .filter(|word| !word.is_empty())
            .map(str::to_string)
            .collect();
        if words.is_empty() {
            words = own.iter().filter(|address| !address.is_empty()).map(|address| format!("{address}/24")).collect();
        }
        let mut nets = Vec::new();
        for word in &words {
            let net = Network::read(word).ok_or_else(|| {
                AppError::new(format!("{} is not a network — write it as 10.0.30.0/24 or an address", PyRepr::of(word)))
            })?;
            if !net.is_private() {
                return Err(AppError::new(format!("{word} is not a private network: the scan looks only in the home network")));
            }
            if !nets.contains(&net) {
                nets.push(net);
            }
        }
        if nets.is_empty() {
            return Err(AppError::new("no network to scan: write one, e.g. 10.0.30.0/24"));
        }
        if nets.iter().map(|net| net.size()).sum::<u64>() > Self::MAX_ADDRESSES {
            return Err(AppError::new(format!(
                "too many addresses: at most {} in one scan (four /24 networks)",
                Self::MAX_ADDRESSES
            )));
        }
        Ok(nets)
    }

    fn port(raw: Option<&Value>) -> Result<u16, AppError> {
        let said = raw
            .filter(|raw| !raw.is_null() && **raw != json!(""))
            .map_or_else(|| Self::DEFAULT_PORT.to_string(), |raw| Coerce::str_of(Some(raw)));
        let said = Coerce::strip(&said);
        let number = said.parse::<u16>().ok().filter(|number| *number >= 1 && said.chars().all(|digit| digit.is_ascii_digit()));
        number.ok_or_else(|| AppError::new("the port must be a number from 1 to 65535"))
    }

    /// Each worker takes the next address until none is left.
    fn in_parallel<T: Send>(addresses: &[u32], work: &(dyn Fn(u32) -> Option<T> + Sync)) -> Vec<T> {
        let next = Mutex::new(addresses.iter());
        let found = Mutex::new(Vec::new());
        std::thread::scope(|scope| {
            for _ in 0..Self::WORKERS.min(addresses.len()) {
                scope.spawn(|| {
                    loop {
                        let address = next.lock().unwrap_or_else(PoisonError::into_inner).next().copied();
                        let Some(address) = address else {
                            return;
                        };
                        if let Some(row) = work(address) {
                            found.lock().unwrap_or_else(PoisonError::into_inner).push(row);
                        }
                    }
                });
            }
        });
        found.into_inner().unwrap_or_else(PoisonError::into_inner)
    }

    fn identify(&self, address: u32, port: u16, known: &BTreeSet<String>) -> Option<(u32, Value)> {
        let shown = Ipv4Addr::from(address);
        let url = format!("http://{shown}:{port}/api/pairing");
        let raw = self.app.http.ask("GET", &url, &[], &[], Self::ASK_TIMEOUT).ok()?.text(1 << 20).ok()?;
        let info: Value = if raw.is_empty() { json!({}) } else { serde_json::from_slice(&raw).ok()? };
        if info.get("service").and_then(Value::as_str) != Some("caravan-scout") {
            return None;
        }
        let host_id = Coerce::stripped(info.get("hostId"));
        let state = if !host_id.is_empty() && known.contains(&host_id) {
            "here"
        } else if !Coerce::stripped(info.get("controllerUrl")).is_empty() {
            "taken"
        } else {
            "free"
        };
        let name = {
            let said = Coerce::text(info.get("hostname"));
            if !said.is_empty() {
                said
            } else if !host_id.is_empty() {
                host_id.clone()
            } else {
                shown.to_string()
            }
        };
        Some((
            address,
            json!({"address": shown.to_string(), "port": port, "hostId": host_id, "name": name, "version": Coerce::text(info.get("version")), "state": state}),
        ))
    }

    /// `{networks, port, scanned, found}`.
    pub fn scan(&self, raw_networks: Option<&Value>, raw_port: Option<&Value>) -> Result<Value, AppError> {
        let own = Self::own_addresses(Coerce::strip(&self.app.paths.topology_server_ip));
        let nets = Self::networks(&Coerce::text(raw_networks), &own)?;
        let port = Self::port(raw_port)?;
        let mut addresses: Vec<u32> = Vec::new();
        for net in &nets {
            for address in net.hosts() {
                if !addresses.contains(&address) {
                    addresses.push(address);
                }
            }
        }
        let known: BTreeSet<String> = self.app.admin.change(|doc| Topology::of(doc).hosts().keys().cloned().collect());
        let reachable = Self::in_parallel(&addresses, &|address| {
            let place = SocketAddr::from((Ipv4Addr::from(address), port));
            TcpStream::connect_timeout(&place, Self::CONNECT_TIMEOUT).ok().map(|_| address)
        });
        let known = Arc::new(known);
        let mut found = Self::in_parallel(&reachable, &|address| self.identify(address, port, &known));
        found.sort_by_key(|row| row.0);
        let rows: Vec<Value> = found.into_iter().map(|row| row.1).collect();
        let words: Vec<String> = nets.iter().map(|net| net.word()).collect();
        Ok(json!({"networks": words, "port": port, "scanned": addresses.len(), "found": rows}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_network_reads_as_python_reads_it() {
        let net = Network::read("10.0.30.20/24").unwrap();
        assert_eq!(net.word(), "10.0.30.0/24");
        assert_eq!(net.hosts().len(), 254);
        assert_eq!(Network::read("10.0.30.20").unwrap().hosts().len(), 1);
        assert!(Network::read("nonsense").is_none());
        assert!(Network::read("10.0.0.0/33").is_none());
    }

    #[test]
    fn the_scan_stays_in_the_home_network_and_in_bounds() {
        assert!(ScoutScan::networks("8.8.8.0/24", &[]).unwrap_err().message.contains("not a private"));
        assert!(ScoutScan::networks("10.0.0.0/16", &[]).unwrap_err().message.contains("too many"));
        assert!(ScoutScan::networks("", &[]).unwrap_err().message.contains("no network"));
        assert_eq!(ScoutScan::networks("", &["10.0.30.5".to_string()]).unwrap()[0].word(), "10.0.30.0/24");
        assert_eq!(ScoutScan::networks("10.0.1.0/24, 10.0.1.0/24; 10.0.2.0/24", &[]).unwrap().len(), 2);
    }

    #[test]
    fn a_port_is_a_number_in_range() {
        assert_eq!(ScoutScan::port(None).unwrap(), 8092);
        assert_eq!(ScoutScan::port(Some(&json!("9000"))).unwrap(), 9000);
        assert!(ScoutScan::port(Some(&json!("0"))).is_err());
        assert!(ScoutScan::port(Some(&json!("x"))).is_err());
    }
}
