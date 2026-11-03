//! What a store's mount says of itself, and what the look at it comes to.

use super::*;

/// Where a path is mounted from, whether that machine answers, and whether /etc/fstab names it: asked WITHOUT touching the path itself.
pub struct MountFacts;

impl MountFacts {
    pub(super) const MOUNTS: &'static str = "/proc/self/mountinfo";
    pub(super) const FSTAB: &'static str = "/etc/fstab";

    pub(super) fn normal(path: &str) -> String {
        let trimmed = path.trim_end_matches('/');
        if trimmed.is_empty() { "/".to_string() } else { trimmed.to_string() }
    }

    pub(super) fn port(kind: &str) -> Option<u16> {
        match kind {
            "nfs" | "nfs4" => Some(2049),
            "cifs" | "smb3" => Some(445),
            _ => None,
        }
    }

    /// (source, type) of the LAST thing mounted at `path`: mounts stack, and the last one is what a reader gets.
    pub(super) fn mounted(path: &str, table: &str) -> Option<(String, String)> {
        let want = Self::normal(path);
        let mut found = None;
        for line in table.lines() {
            let (left, right) = line.split_once(" - ").unwrap_or((line, ""));
            let (fields, rest): (Vec<&str>, Vec<&str>) = (left.split_whitespace().collect(), right.split_whitespace().collect());
            if let (Some(point), Some(kind), Some(source)) = (fields.get(4), rest.first(), rest.get(1))
                && Self::normal(&point.replace("\\040", " ")) == want
            {
                found = Some(((*source).to_string(), (*kind).to_string()));
            }
        }
        found
    }

    /// Whether /etc/fstab names this mount point: "not mounted" reads very differently when nothing was ever going to mount it.
    pub(super) fn in_fstab(path: &str, table: &str) -> bool {
        let want = Self::normal(path);
        table.lines().any(|line| {
            line.split('#').next().unwrap_or_default().split_whitespace().nth(1).is_some_and(|point| Self::normal(point) == want)
        })
    }

    /// The machine a source names.
    pub(super) fn host(source: &str) -> String {
        if let Some(rest) = source.strip_prefix("//") {
            return rest.split('/').next().unwrap_or_default().to_string();
        }
        if source.contains(':') && !source.starts_with('/') {
            return source.split(':').next().unwrap_or_default().to_string();
        }
        String::new()
    }

    /// `{source, type, host, answers, inFstab}`.
    pub fn at(path: &str) -> Value {
        const KNOCK: std::time::Duration = std::time::Duration::from_millis(1500);
        let table = std::fs::read_to_string(Self::FSTAB);
        let in_fstab = table.as_deref().is_ok_and(|table| Self::in_fstab(path, table));
        let mounts = std::fs::read_to_string(Self::MOUNTS);
        let Some((source, kind)) = mounts.as_deref().ok().and_then(|table| Self::mounted(path, table)) else {
            return json!({"inFstab": in_fstab, "source": "", "type": "", "host": "", "answers": null});
        };
        let host = Self::host(&source);
        let answers = match Self::port(&kind).filter(|_| !host.is_empty()) {
            Some(port) => {
                use std::net::ToSocketAddrs;
                let address = (host.as_str(), port).to_socket_addrs().ok().and_then(|mut found| found.next());
                json!(address.is_some_and(|address| std::net::TcpStream::connect_timeout(&address, KNOCK).is_ok()))
            }
            None => Value::Null,
        };
        json!({"inFstab": in_fstab, "source": source, "type": kind, "host": host, "answers": answers})
    }
}

/// What was measured about one store, when, and the one word for it.
#[derive(Debug, Clone)]
pub struct StoreStatus {
    /// The word.
    pub state: &'static str,
    pub(super) detail: String,
    pub(super) checked_at: i64,
    /// The figures.
    pub measured: Map<String, Value>,
}

impl StoreStatus {
    pub(super) const LOW_SPACE_BYTES: f64 = 50.0 * 1_073_741_824.0;
    pub(super) const MEASURED: [&'static str; 10] =
        ["free", "total", "files", "bytes", "folders", "more", "entries", "entriesMore", "dirs", "dirsMore"];

    pub(super) fn new(state: &'static str, detail: impl Into<String>, checked_at: i64) -> Self {
        Self { state, detail: detail.into(), checked_at, measured: Map::new() }
    }

    pub(super) fn judge(store: &ModelStore, probe: &Value, now: i64) -> Self {
        if !Coerce::truthy(probe.get("ok")) {
            let words = if Coerce::truthy(probe.get("error")) {
                Coerce::text(probe.get("error"))
            } else {
                "the probe failed".to_string()
            };
            return Self::new("unknown", words, now);
        }
        if !Coerce::truthy(probe.get("exists")) {
            return Self::new("missing", format!("no directory at {}", store.path), now);
        }
        let mark = probe.get("marker").filter(|mark| mark.is_object() && Coerce::truthy(Some(*mark)));
        if store.role == "library" {
            let Some(mark) = mark else {
                return Self::new("not-mounted", "the folder carries no library mark: the share is not mounted here", now);
            };
            if Coerce::str_of(mark.get("id")) != store.id {
                let other = if Coerce::truthy(mark.get("name")) {
                    Coerce::text(mark.get("name"))
                } else {
                    Coerce::str_of(mark.get("id"))
                };
                return Self::new("foreign", format!("another library is mounted here: {other}"), now);
            }
        }
        let measured: Map<String, Value> =
            Self::MEASURED.iter().filter_map(|key| probe.get(*key).map(|value| ((*key).to_string(), value.clone()))).collect();
        let with = |state: &'static str, detail: String| Self { state, detail, checked_at: now, measured: measured.clone() };
        if !Coerce::truthy(probe.get("writable")) {
            return with("read-only", "this host cannot write here".to_string());
        }
        if let Some(free) = probe.get("free").and_then(Value::as_f64).filter(|free| *free < Self::LOW_SPACE_BYTES) {
            return with("low-space", format!("{:.1} GB free", free / 1_073_741_824.0));
        }
        with("ok", String::new())
    }

    pub(super) fn to_json(&self) -> Map<String, Value> {
        let mut doc = Map::new();
        doc.insert("state".to_string(), json!(self.state));
        doc.insert("detail".to_string(), json!(self.detail));
        doc.insert("checkedAt".to_string(), json!(self.checked_at));
        for key in ["free", "total", "files", "folders", "more", "mount"] {
            if let Some(value) = self.measured.get(key) {
                doc.insert(key.to_string(), value.clone());
            }
        }
        if let Some(size) = self.measured.get("bytes") {
            doc.insert("size".to_string(), size.clone());
        }
        doc
    }
}
