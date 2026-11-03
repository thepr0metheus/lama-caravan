//! How a key finds its route.

use crate::route::Route;

/// Why a key names no route.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyMiss {
    /// The request carries no key.
    NoKey,
    /// No enabled route carries it.
    UnknownKey,
    /// Two enabled routes carry it, so it opens neither.
    AmbiguousKey,
}

/// The one door the consumers share.
pub struct KeyEntry;

impl KeyEntry {
    /// Routing's test of a client carries this header.
    pub const PROBE_HEADER: &'static str = "X-Caravan-Probe";
    /// What the journal calls that test.
    pub const PROBE_CLIENT: &'static str = "routing-probe";

    /// The key a request carries: `Authorization: Bearer …`, else `x-api-key`; "" for none. `Bearer ` with nothing after
    /// it is an empty key, and `x-api-key` is not read then: as it always was.
    pub fn presented_key(authorization: Option<&str>, x_api_key: Option<&str>) -> String {
        match authorization.and_then(|value| value.strip_prefix("Bearer ")) {
            Some(rest) => crate::Coerce::strip(rest).to_string(),
            // absent-ok: no key is "", which `route_for` answers as `KeyMiss::NoKey`: named there.
            None => crate::Coerce::strip(x_api_key.unwrap_or_default()).to_string(),
        }
    }

    /// Equality of two keys in a time that does not depend on where they differ: only on their lengths, as
    /// `hmac.compare_digest` does.
    pub fn same(left: &str, right: &str) -> bool {
        let (left, right) = (left.as_bytes(), right.as_bytes());
        if left.len() != right.len() {
            return false;
        }
        let difference = left.iter().zip(right).fold(0u8, |seen, (a, b)| seen | (a ^ b));
        std::hint::black_box(difference) == 0
    }

    /// The enabled route this key names, or why there is none.
    pub fn route_for<'a>(key: &str, routes: &'a [Route]) -> Result<&'a Route, KeyMiss> {
        if key.is_empty() {
            return Err(KeyMiss::NoKey);
        }
        let mut found =
            routes.iter().filter(|route| route.enabled && !route.api_key.is_empty() && Self::same(&route.api_key, key));
        match (found.next(), found.next()) {
            (None, _) => Err(KeyMiss::UnknownKey),
            (Some(_), Some(_)) => Err(KeyMiss::AmbiguousKey),
            (Some(route), None) => Ok(route),
        }
    }
}
