//! The port a cell runs on: leased when its start begins, from the range the start names, and given back when the cell stops or its
//! start fails (Papyrus `caravan-scout-port-lease`, step 2). Until 2026-11-07 a cell WAS its port: the controller held one for it
//! whether it ran or not and said it in every request, and the scout knew the cell by it everywhere. A port is now a detail of one run.

use crate::errors::{AppError, PyRepr};
use serde_json::Value;
use std::collections::BTreeSet;
use std::ops::RangeInclusive;

/// The ports a start may be leased one of, and the rule of which one: the lowest that nobody holds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PortLease {
    base: i64,
    upper: i64,
}

impl PortLease {
    /// The range of a start that names none: the cells' range of the fleet since 2026-09.
    pub const CELLS: Self = Self { base: 22001, upper: 22999 };
    /// What a port can be.
    const PORTS: RangeInclusive<i64> = 1..=65535;

    /// The range a start's `ports` names, `{base, upper}`; the cells' own when it names none. Refused when it is no range of ports: a
    /// start leased a port the controller did not mean is the wrong cell.
    pub fn of(said: Option<&Value>) -> Result<Self, AppError> {
        let Some(said) = said.filter(|said| !said.is_null()) else {
            return Ok(Self::CELLS);
        };
        let bound = |key: &str| said.get(key).and_then(Value::as_i64).filter(|port| Self::PORTS.contains(port));
        match (bound("base"), bound("upper")) {
            (Some(base), Some(upper)) if base <= upper => Ok(Self { base, upper }),
            _ => Err(AppError::new(format!(
                "ports must be {{base, upper}}: whole numbers from 1 to 65535, base not above upper — not {}",
                PyRepr::of_value(said)
            ))),
        }
    }

    /// The lowest port of the range that no cell of this scout holds (`held`), no record of a cell that may still run names
    /// (`recorded`) and nothing on the machine listens on (`listening`; `None` when the machine will not say, and the other two are all
    /// there is to go by). The refusal's words when every one is taken.
    pub fn pick(&self, held: &BTreeSet<i64>, recorded: &BTreeSet<i64>, listening: Option<&BTreeSet<i64>>) -> Result<i64, String> {
        let taken = |port: &i64| {
            held.contains(port) || recorded.contains(port) || listening.is_some_and(|listening| listening.contains(port))
        };
        (self.base..=self.upper)
            .find(|port| !taken(port))
            .ok_or_else(|| format!("no free port for a cell in {}–{}", self.base, self.upper))
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, reason = "a test may stop where it found something wrong")]

    use super::*;
    use serde_json::json;

    fn set(ports: &[i64]) -> BTreeSet<i64> {
        ports.iter().copied().collect()
    }

    #[test]
    fn the_lowest_port_nobody_holds_is_leased() {
        let lease = PortLease::of(Some(&json!({"base": 22001, "upper": 22005}))).unwrap();
        let none = BTreeSet::new();
        assert_eq!(lease.pick(&none, &none, Some(&none)), Ok(22001), "the lowest first");
        assert_eq!(lease.pick(&set(&[22001, 22003]), &none, Some(&none)), Ok(22002), "a port a cell holds is skipped");
        assert_eq!(lease.pick(&none, &set(&[22001]), None), Ok(22002), "and one a record names, whatever the machine says");
        assert_eq!(lease.pick(&none, &none, Some(&set(&[22001, 22002]))), Ok(22003), "and one something listens on");
        assert_eq!(lease.pick(&set(&[22001]), &set(&[22002]), Some(&set(&[22003]))), Ok(22004), "all three at once");
        assert_eq!(
            lease.pick(&none, &none, None),
            Ok(22001),
            "a machine that will not say what listens leaves the table and the records to go by"
        );
    }

    #[test]
    fn a_range_with_every_port_taken_is_refused_in_words() {
        let lease = PortLease::of(Some(&json!({"base": 22001, "upper": 22002}))).unwrap();
        assert_eq!(
            lease.pick(&set(&[22001]), &BTreeSet::new(), Some(&set(&[22002]))),
            Err("no free port for a cell in 22001–22002".to_string())
        );
        let one = PortLease::of(Some(&json!({"base": 22010, "upper": 22010}))).unwrap();
        assert_eq!(one.pick(&BTreeSet::new(), &BTreeSet::new(), None), Ok(22010), "a range of one port is that port");
    }

    #[test]
    fn a_start_that_names_no_range_has_the_cells_own_and_a_bad_one_is_refused() {
        assert_eq!(PortLease::of(None).ok(), Some(PortLease::CELLS));
        assert_eq!(PortLease::of(Some(&Value::Null)).ok(), Some(PortLease::CELLS));
        assert_eq!(
            PortLease::CELLS.pick(&BTreeSet::new(), &BTreeSet::new(), None),
            Ok(22001),
            "the cells' range starts at 22001"
        );
        for bad in [
            json!({"base": 22010, "upper": 22001}),
            json!({"base": 0, "upper": 22001}),
            json!({"base": 22001, "upper": 70000}),
            json!({"base": "22001", "upper": 22002}),
            json!({"base": 22001}),
            json!(22001),
        ] {
            let refused = PortLease::of(Some(&bad)).map_err(|error| error.message);
            assert!(refused.as_ref().is_err_and(|words| words.starts_with("ports must be {base, upper}")), "{bad}: {refused:?}");
        }
    }
}
