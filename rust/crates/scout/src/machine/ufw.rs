//! Who `ufw` lets reach a port, as `ufw` itself decides.

use rules::Coerce;
use serde_json::{Value, json};

/// One rule for connections coming in, as `ufw status` lists it.
struct UfwRule {
    to: Vec<String>,
    lets_in: bool,
    source: String,
}

/// `ufw status`, read.
pub struct UfwRules;

impl UfwRules {
    const LETS_IN: [&'static str; 2] = ["ALLOW", "LIMIT"];
    const KEEPS_OUT: [&'static str; 2] = ["DENY", "REJECT"];
    const NO_PROTOCOL: &'static str = "";

    /// The IPv4 rules for connections coming in, in its order. An outgoing or a forwarded rule is not one, nor an IPv6 one: the controller
    /// and the network reach a cell over IPv4. A comment is cut off.
    fn rules(out: &str) -> Vec<UfwRule> {
        let mut rules = Vec::new();
        for line in out.lines() {
            let text = line.split('#').next().unwrap_or(line);
            if text.contains("(v6)") {
                continue;
            }
            let words: Vec<&str> = text.split_whitespace().collect();
            let found = words.iter().position(|word| Self::LETS_IN.contains(word) || Self::KEEPS_OUT.contains(word));
            let Some(at) = found.filter(|at| *at > 0) else {
                continue;
            };
            // absent-ok: a rule of no source is said below as what it means: `Anywhere`.
            let mut rest = words.get(at + 1..).unwrap_or_default();
            if let Some(direction) = rest.first().filter(|word| matches!(**word, "IN" | "OUT" | "FWD")) {
                if *direction != "IN" {
                    continue;
                }
                // absent-ok: as above.
                rest = rest.get(1..).unwrap_or_default();
            }
            let source = if rest.is_empty() { "Anywhere".to_string() } else { rest.join(" ") };
            let to = words.get(..at).unwrap_or_default().iter().map(|word| (*word).to_string()).collect();
            rules.push(UfwRule { to, lets_in: words.get(at).is_some_and(|word| Self::LETS_IN.contains(word)), source });
        }
        rules
    }

    /// `[0-9][0-9,:]*(/(tcp|udp))?`: the ports of a rule's To, and what comes after the slash.
    fn ports_of(word: &str) -> Option<(&str, &str)> {
        let (ports, protocol) = word.split_once('/').unwrap_or((word, Self::NO_PROTOCOL));
        let starts = ports.chars().next().is_some_and(|first| first.is_ascii_digit());
        let plain = ports.chars().all(|letter| letter.is_ascii_digit() || matches!(letter, ',' | ':'));
        let known = if word.contains('/') { matches!(protocol, "tcp" | "udp") } else { true };
        (starts && plain && known).then_some((ports, protocol))
    }

    /// Whether a rule's To holds TCP `port`: its ports name it, or it names no port (`Anywhere`, an address of this machine) and so holds every
    /// one. An application's profile is a name whose ports the status does not say: not counted, rather than guessed.
    fn covers(to: &[String], port: i64) -> bool {
        let before_on = to.iter().position(|word| word == "on").map_or(to, |at| to.get(..at).unwrap_or_default());
        let Some((ports, protocol)) = before_on.iter().find_map(|word| Self::ports_of(word)) else {
            return !before_on.is_empty() && before_on.iter().all(|word| word == "Anywhere" || word.contains('.'));
        };
        if protocol == "udp" {
            return false;
        }
        ports.split(',').any(|part| {
            let (low, high) = part.split_once(':').unwrap_or((part, ""));
            let high = if high.is_empty() { low } else { high };
            match (low.parse::<i64>(), high.parse::<i64>()) {
                (Ok(low), Ok(high)) => low <= port && port <= high,
                _ => false,
            }
        })
    }

    /// Who may reach TCP `port`: `{state, allowedFrom[]}`, state `open` (ufw off), `all`, `restricted`, `blocked` or `unknown`. The first rule that
    /// holds the port and the caller's address wins; the first rule for everyone decides the rest; with none, ufw's own default keeps the rest out.
    pub fn access(status: &str, port: &Value) -> Value {
        let Some(port) = Coerce::int(port) else {
            return json!({"state": "unknown"});
        };
        if status.is_empty() {
            return json!({"state": "unknown"});
        }
        if status.to_lowercase().contains("status: inactive") {
            return json!({"state": "open", "allowedFrom": []});
        }
        let mut allowed: Vec<String> = Vec::new();
        let mut decided: Vec<String> = Vec::new();
        for rule in Self::rules(status).into_iter().filter(|rule| Self::covers(&rule.to, port)) {
            if rule.source == "Anywhere" {
                if rule.lets_in {
                    return json!({"state": "all", "allowedFrom": ["Anywhere"]});
                }
                break;
            }
            if !decided.contains(&rule.source) {
                decided.push(rule.source.clone());
                if rule.lets_in {
                    allowed.push(rule.source);
                }
            }
        }
        if allowed.is_empty() {
            return json!({"state": "blocked", "allowedFrom": []});
        }
        json!({"state": "restricted", "allowedFrom": allowed})
    }
}
