//! What listens on this machine: `ss` on Linux, `lsof` where there is none.

use crate::commands::{Commands, NoAnswer};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::time::Duration;

/// One socket a tool named.
#[derive(Debug)]
struct Socket {
    port: i64,
    address: String,
    process: String,
    pid: i64,
}

/// A tool's reading: its sockets, `None` when it failed.
type SocketsRead = fn(&dyn Commands) -> Result<Option<Vec<Socket>>, NoAnswer>;

/// The ports listening here.
pub struct Listeners;

impl Listeners {
    const QUICK: Duration = Duration::from_secs(5);
    const FULL: Duration = Duration::from_secs(6);

    /// The ports listening right now; `None` when neither tool answers: not "nothing listens". The local address is the 4th and the 9th column.
    pub fn ports(commands: &dyn Commands) -> Option<BTreeSet<i64>> {
        let tools: [(&[&str], usize); 2] = [(&["ss", "-ltnH"], 3), (&["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], 8)];
        for (argv, column) in tools {
            let Ok(ran) = commands.run(argv, Self::QUICK) else {
                continue;
            };
            if !ran.ok() && ran.stdout.trim().is_empty() {
                continue;
            }
            let ports = ran.stdout.lines().filter_map(|line| Self::port_of(line.split_whitespace().nth(column)?));
            return Some(ports.collect());
        }
        None
    }

    fn port_of(address: &str) -> Option<i64> {
        let (_, port) = address.rsplit_once(':').unwrap_or(("", address));
        port.bytes().all(|byte| byte.is_ascii_digit()).then(|| port.parse().ok()).flatten()
    }

    /// Each port listening, with its owner where the OS says and the addresses it is bound on: `{ok, ports}`. A tool that fails is no answer, `{ok: false}`,
    /// not an empty machine.
    pub fn listing(commands: &dyn Commands) -> Value {
        let mut errors = Vec::new();
        let mut rows = None;
        for (tool, read) in [("ss", Self::ss_rows as SocketsRead), ("lsof", Self::lsof_rows as SocketsRead)] {
            match read(commands) {
                Ok(Some(found)) => {
                    rows = Some(found);
                    break;
                }
                Ok(None) => errors.push(format!("{tool} failed")),
                Err(why) => errors.push(format!("{tool}: {}", why.words(tool))),
            }
        }
        let Some(rows) = rows else {
            let said: String = errors.join("; ").chars().take(160).collect();
            return json!({"ok": false, "error": said, "ports": []});
        };
        json!({"ok": true, "ports": Self::by_port(rows)})
    }

    /// One row per port: a socket bound on both v4 and v6 is one listener.
    fn by_port(rows: Vec<Socket>) -> Vec<Value> {
        let mut best: BTreeMap<i64, Socket> = BTreeMap::new();
        let mut addresses: BTreeMap<i64, Vec<String>> = BTreeMap::new();
        for row in rows {
            let said = addresses.entry(row.port).or_default();
            if !row.address.is_empty() && !said.contains(&row.address) {
                said.push(row.address.clone());
            }
            let keeps_its_owner = best.get(&row.port).is_some_and(|held| !held.process.is_empty() || row.process.is_empty());
            if !keeps_its_owner {
                best.insert(row.port, row);
            }
        }
        best.into_values()
            .map(|row| {
                let bound = addresses.remove(&row.port);
                json!({"port": row.port, "proc": row.process, "pid": row.pid, "addrs": bound})
            })
            .collect()
    }

    /// `ss -ltnpH`, one row per socket; `None` when it failed.
    fn ss_rows(commands: &dyn Commands) -> Result<Option<Vec<Socket>>, NoAnswer> {
        let ran = commands.run(&["ss", "-ltnpH"], Self::FULL)?;
        if !ran.ok() {
            return Ok(None);
        }
        let mut rows = Vec::new();
        for line in ran.stdout.lines() {
            let Some(local) = line.split_whitespace().nth(3) else {
                continue;
            };
            let Some(port) = Self::port_of(local) else {
                continue;
            };
            let (address, _) = local.rsplit_once(':').unwrap_or(("", local));
            let (process, pid) = Self::owner_in(line);
            rows.push(Socket { port, address: address.to_string(), process, pid });
        }
        Ok(Some(rows))
    }

    /// The pid listening on `port`: via `ss`, and `lsof` where there is no `ss`; 0 if none.
    pub fn owner_of(commands: &dyn Commands, port: i64) -> i64 {
        let want = port.to_string();
        match commands.run(&["ss", "-ltnpH"], Self::QUICK) {
            Ok(ran) => ran
                .stdout
                .lines()
                .filter(|line| {
                    let local = line.split_whitespace().nth(3);
                    // absent-ok: a line with no fourth column names no port.
                    local.and_then(|local| local.rsplit(':').next()).unwrap_or_default() == want
                })
                .find_map(Self::pid_said)
                // absent-ok: 0 is this function's word for "nobody listens".
                .unwrap_or(0),
            Err(NoAnswer::NotFound) => {
                let asked = commands.run(&["lsof", "-nP", &format!("-iTCP:{port}"), "-sTCP:LISTEN", "-t"], Self::QUICK);
                // absent-ok: no answer and no process both read 0 here: this function's word for "nobody listens".
                asked.ok().and_then(|ran| ran.stdout.split_whitespace().next()?.parse().ok()).unwrap_or(0)
            }
            Err(_) => 0,
        }
    }

    /// `pid=(\d+)`.
    fn pid_said(line: &str) -> Option<i64> {
        let (_, after) = line.split_once("pid=")?;
        let digits: String = after.chars().take_while(char::is_ascii_digit).collect();
        digits.parse().ok()
    }

    /// `\("([^"]+)",pid=(\d+)`: the first process a line of `ss` names.
    fn owner_in(line: &str) -> (String, i64) {
        let mut rest = line;
        while let Some((_, after)) = rest.split_once("(\"") {
            rest = after;
            let Some((name, tail)) = after.split_once('"') else {
                continue;
            };
            let Some(digits) = tail.strip_prefix(",pid=") else {
                continue;
            };
            let digits: String = digits.chars().take_while(char::is_ascii_digit).collect();
            if let (false, Ok(pid)) = (name.is_empty(), digits.parse()) {
                return (name.to_string(), pid);
            }
        }
        (String::new(), 0)
    }

    /// `lsof` for where there is no `ss`. `+c 0` keeps a command's whole name, and it writes a space in it as `\x20`. Exit 1 with nothing on stderr is
    /// its "no such sockets": nothing listens.
    fn lsof_rows(commands: &dyn Commands) -> Result<Option<Vec<Socket>>, NoAnswer> {
        let ran = commands.run(&["lsof", "+c", "0", "-nP", "-iTCP", "-sTCP:LISTEN"], Self::FULL)?;
        if !ran.ok() && (ran.code != Some(1) || !ran.stderr.trim().is_empty()) {
            return Ok(None);
        }
        let mut rows = Vec::new();
        for line in ran.stdout.lines().skip(1) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            let (Some(process), Some(pid), Some(last)) = (parts.first(), parts.get(1), parts.last()) else {
                continue;
            };
            let Some(pid) = pid.parse::<i64>().ok().filter(|_| parts.len() >= 9) else {
                continue;
            };
            let name = if *last == "(LISTEN)" { parts.get(parts.len() - 2).copied().unwrap_or(last) } else { last };
            let Some(port) = Self::port_of(name) else {
                continue;
            };
            let (address, _) = name.rsplit_once(':').unwrap_or(("", name));
            rows.push(Socket { port, address: address.to_string(), process: process.replace("\\x20", " "), pid });
        }
        Ok(Some(rows))
    }
}
