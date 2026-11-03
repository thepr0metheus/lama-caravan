//! Looking at what runs on this machine: read only, and never inside a report.

use crate::engines::ForeignEngines;
use crate::engines::kind::EngineKind;
use crate::engines::listening::Listening;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

impl ForeignEngines {
    /// Who listens on `port` now, as the OS says: to reach the engine at the address it is bound to.
    pub(crate) fn listener_of(&self, port: i64) -> Option<Value> {
        let heard = self.machine.listeners();
        let rows = heard.get("ports").and_then(Value::as_array).filter(|_| Coerce::truthy(heard.get("ok")))?;
        rows.iter().find(|row| row.get("port").and_then(Value::as_i64) == Some(port)).cloned()
    }

    /// A scan, kept.
    pub fn refresh(&self) {
        let views = self.scan();
        self.memory().views = Some(views);
    }

    fn scan(&self) -> Vec<Value> {
        let heard = self.machine.listeners();
        // None: the OS would not say what listens: each kind's usual port is asked blind then, and where it listens stays unknown.
        let rows = heard.get("ports").and_then(Value::as_array).filter(|_| Coerce::truthy(heard.get("ok")));
        let own: BTreeSet<i64> = self.cells.table.all().iter().map(|(port, _)| *port).collect();
        let processes = self.machine.processes();
        let mut found = Vec::new();
        for kind in &self.kinds {
            for (port, listener) in Listening::candidates(kind.as_ref(), rows.map(Vec::as_slice), &own) {
                let target = self.port_of(port, &Listening::ask_host(listener.as_ref()));
                let Some(seen) = kind.read(&|path| target.borrowed().ask(path)) else {
                    continue;
                };
                let by_name = listener.as_ref().is_some_and(|listener| kind.is_its_process(listener.get("proc")));
                let state = seen.get("state").and_then(Value::as_str);
                if (state == Some("auth") && !by_name)
                    || (state == Some("unreachable") && !(by_name && port == kind.default_port()))
                {
                    continue;
                }
                found.push(self.view(kind.as_ref(), port, listener.as_ref(), &seen, processes.as_ref()));
            }
        }
        self.servers.annotate(&self.kinds, found, rows.map(Vec::as_slice))
    }

    fn view(
        &self,
        kind: &dyn EngineKind,
        port: i64,
        listener: Option<&Value>,
        seen: &Value,
        processes: Option<&BTreeMap<i64, Value>>,
    ) -> Value {
        let pids = Listening::pids(kind, listener, processes);
        let scope = Listening::scope(listener);
        // A kind that did not answer says no models: `null`, not `[]`: an engine that wants a token has models too.
        let mut view =
            json!({"kind": kind.id(), "label": kind.label(), "port": port, "listen": scope, "version": "", "models": null});
        if let (Value::Object(fields), Value::Object(said)) = (&mut view, seen) {
            fields.extend(said.clone());
            fields.insert("pids".to_string(), json!(pids));
            // What the board may do to it. No load, no download: a cell loads its model, and an engine's own tools bring one.
            fields.insert("controls".to_string(), json!(kind.controls(seen)));
            // Who ufw lets reach its port, as a cell's port says it: asked only when it listens beyond this machine: on 127.0.0.1 no rule matters.
            fields.insert(
                "firewall".to_string(),
                if scope == "loopback" { Value::Null } else { self.machine.firewall(&json!(port)) },
            );
            // The memory its processes hold (RSS); `null` when ps will not say.
            let ram = processes.map(|table| {
                pids.iter()
                    .filter_map(|pid| table.get(pid))
                    .filter_map(|row| row.get("rssKb").and_then(Value::as_i64))
                    .sum::<i64>()
                    * 1024
            });
            fields.insert("ramBytes".to_string(), json!(ram));
        }
        view
    }
}
