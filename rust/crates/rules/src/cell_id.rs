//! A cell's own name: what the board, the controller and the scout know a cell by. Its port is a detail of one run of it: the
//! scout leases a free one when the cell starts and takes it back when the cell stops (Papyrus `caravan-scout-port-lease`, step 2).
//!
//! Until 2026-11-07 a cell was known by its machine and its port, and the port was held for it whether it ran or not. A cell of
//! then is known by `c<port>` from now on, and both programs come to that name on their own: the controller when it keys its
//! slots anew, the scout when it reads its records, its logs and the mark of a process it started before. So the step needs no
//! word between the two, and a scout not updated yet still names a cell the controller knows. A new cell gets a name nobody had:
//! `c` and eight hex digits of the system's randomness, which the caller draws — this crate has no input of its own.

use serde_json::Value;

/// The rule of a cell's name.
pub struct CellId;

impl CellId {
    /// What every name starts with: a name is never a number, so a port said where a name belongs is told apart.
    const LEAD: char = 'c';
    /// The longest name: `c` and sixteen letters.
    const LONGEST: usize = 17;
    /// The ports a cell of before can have had.
    const PORTS: std::ops::RangeInclusive<i64> = 1..=65535;

    /// The name of a cell that was known by `port` before 2026-11-07.
    pub fn of_port(port: i64) -> String {
        format!("{}{port}", Self::LEAD)
    }

    /// Whether `said` is a cell's name: `c` and one to sixteen lowercase letters or digits.
    pub fn is_name(said: &str) -> bool {
        let mut letters = said.chars();
        letters.next() == Some(Self::LEAD)
            && (2..=Self::LONGEST).contains(&said.len())
            && letters.all(|letter| letter.is_ascii_digit() || letter.is_ascii_lowercase())
    }

    /// A cell's name as anyone says it: a name as it is; a port of a cell of before — a number, or digits as a record's key and
    /// a process's mark kept it — as that cell's name. `None` for anything else: nothing is guessed into a name.
    pub fn read(said: &Value) -> Option<String> {
        match said {
            Value::String(text) if Self::is_name(text) => Some(text.clone()),
            Value::String(text) => Self::port_name(text.trim().parse::<i64>().ok()),
            Value::Number(number) => Self::port_name(number.as_i64()),
            _ => None,
        }
    }

    fn port_name(port: Option<i64>) -> Option<String> {
        port.filter(|port| Self::PORTS.contains(port)).map(Self::of_port)
    }

    /// A new name made of `random` bytes, the first four of them, as eight hex digits; `None` for fewer than four. The caller draws
    /// the bytes and draws again for a name that is taken.
    pub fn fresh(random: &[u8]) -> Option<String> {
        let four = random.get(..4)?;
        Some(four.iter().fold(String::from(Self::LEAD), |mut name, byte| {
            name.push_str(&format!("{byte:02x}"));
            name
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_name_is_read_as_it_is_and_a_port_of_before_as_its_name() {
        assert_eq!(CellId::read(&json!("c3f9a2b1c")), Some("c3f9a2b1c".to_string()));
        assert_eq!(CellId::read(&json!("c22001")), Some("c22001".to_string()));
        assert_eq!(CellId::read(&json!(22001)), Some("c22001".to_string()), "a port of before, as a number");
        assert_eq!(CellId::read(&json!("22001")), Some("c22001".to_string()), "and as a record's key or a process's mark");
        assert_eq!(CellId::of_port(22035), "c22035");
        // Negative: what is neither is no name, and nothing is made of it.
        for said in [
            json!(""),
            json!("c"),
            json!("C22001"),
            json!("x22001"),
            json!("c-1"),
            json!("c22001 "),
            json!(0),
            json!(70000),
            json!(-5),
            json!(true),
            json!(null),
            json!("c0123456789abcdef0"),
            json!(["c1"]),
        ] {
            assert_eq!(CellId::read(&said), None, "{said}");
        }
    }

    #[test]
    fn a_new_name_is_four_random_bytes_in_hex() {
        assert_eq!(CellId::fresh(&[0x3f, 0x9a, 0x02, 0xb1, 0xff]), Some("c3f9a02b1".to_string()));
        assert!(CellId::is_name(&CellId::fresh(&[0, 0, 0, 0]).unwrap_or_default()));
        assert_eq!(CellId::fresh(&[1, 2, 3]), None, "negative: fewer than four bytes make no name");
    }
}
