//! Who sent a request.

use crate::coerce::Coerce;
use std::net::IpAddr;

/// The sender of a request, as the journal knows it: the peer, or the address a proxy on this host names for it.
/// Only a proxy on this host is believed, and of `X-Forwarded-For` only the last entry: that is the one the proxy
/// appended, and anything before it the sender wrote.
pub struct ClientAddress;

impl ClientAddress {
    /// The field a proxy on this host appends the sender to.
    pub const FORWARDED: &'static str = "X-Forwarded-For";
    /// The field it names the sender in.
    pub const REAL_IP: &'static str = "X-Real-IP";

    fn ip(text: &str) -> Option<IpAddr> {
        Coerce::strip(text).parse().ok()
    }

    /// Whether the peer is this host: a proxy in front of the caravan, not a sender. `::ffff:127.0.0.1` is too.
    pub fn is_local(peer: &str) -> bool {
        match Self::ip(peer) {
            Some(IpAddr::V4(ip)) => ip.is_loopback(),
            Some(IpAddr::V6(ip)) => ip.is_loopback() || ip.to_ipv4_mapped().is_some_and(|mapped| mapped.is_loopback()),
            None => false,
        }
    }

    /// The sender's address, from the peer's and the two headers a proxy on this host sets.
    pub fn of(peer: &str, forwarded: Option<&str>, real_ip: Option<&str>) -> String {
        if !Self::is_local(peer) {
            return peer.to_string();
        }
        // absent-ok: a field not sent names nobody, as an empty one; the peer stays below.
        let last = forwarded.unwrap_or_default().split(',').map(Coerce::strip).rfind(|part| !part.is_empty());
        // absent-ok: as above.
        let named = last.unwrap_or_else(|| Coerce::strip(real_ip.unwrap_or_default()));
        Self::ip(named).map_or_else(|| peer.to_string(), |ip| ip.to_string())
    }
}
