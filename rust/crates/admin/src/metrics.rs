//! The Prometheus text of `/metrics`. Cheap reads only.

use crate::app::App;
use crate::domain::host::HostRecord;
use crate::monitoring::MachineState;
use crate::proxies::stats::ProxyStats;
use crate::store::topology::Topology;
use os::Disk;
use rules::Coerce;
use serde_json::{Value, json};

/// The lines of one exposition.
#[derive(Default)]
struct Exposition {
    lines: Vec<String>,
}

impl Exposition {
    fn escaped(value: &str) -> String {
        value.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', " ")
    }

    fn metric(&mut self, name: &str, help: &str, kind: &str) {
        self.lines.push(format!("# HELP {name} {help}"));
        self.lines.push(format!("# TYPE {name} {kind}"));
    }

    fn sample(&mut self, name: &str, value: &str, labels: &[(&str, String)]) {
        if labels.is_empty() {
            self.lines.push(format!("{name} {value}"));
            return;
        }
        let said: Vec<String> = labels.iter().map(|(key, label)| format!("{key}=\"{}\"", Self::escaped(label))).collect();
        self.lines.push(format!("{name}{{{}}} {value}", said.join(",")));
    }

    fn sample_of(&mut self, name: &str, value: Option<&Value>, labels: &[(&str, String)]) {
        if let Some(value) = value.filter(|value| !value.is_null()) {
            self.sample(name, &Coerce::str_of(Some(value)), labels);
        }
    }
}

/// The text of this controller.
pub struct MetricsText<'app> {
    app: &'app App,
}

impl<'app> MetricsText<'app> {
    /// The text of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The exposition.
    pub fn build(&self) -> String {
        let mut out = Exposition::default();
        out.metric("caravan_build_info", "Static build info", "gauge");
        out.sample("caravan_build_info", "1", &[("version", crate::VERSION.to_string())]);
        self.hosts_and_cells(&mut out);
        Self::gpus(&mut out, &MachineState::of(self.app).gpu_state());
        self.routes(&mut out);
        format!("{}\n", out.lines.join("\n"))
    }

    fn hosts_and_cells(&self, out: &mut Exposition) {
        let now = self.app.now();
        let (hosts, slots) = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            (topology.hosts().clone(), topology.slots().len())
        });
        out.metric("caravan_client_online", "1 while the machine's scout reported within the host report window", "gauge");
        out.metric("caravan_client_last_seen_seconds", "Seconds since the machine's scout last reported", "gauge");
        for record in hosts.values() {
            let host = Coerce::text(record.get("id"));
            if host.is_empty() {
                continue;
            }
            let (state, age) = HostRecord::liveness(record, now as i64, self.app.paths.host_report_ttl);
            out.sample("caravan_client_online", if state == "online" { "1" } else { "0" }, &[("host", host.clone())]);
            if age.is_some() {
                let seen = Coerce::float_or_zero(record.get("lastSeen"));
                out.sample(
                    "caravan_client_last_seen_seconds",
                    &json!(Coerce::rounded(now - seen, 1)).to_string(),
                    &[("host", host)],
                );
            }
        }
        out.metric("caravan_cells_total", "Declared server cells (slots)", "gauge");
        out.sample("caravan_cells_total", &slots.to_string(), &[]);
        if let Ok(config) = self.app.parse_config()
            && let Some((total, free)) = Disk::usage(&self.app.models_dir_of(&config))
        {
            out.metric("caravan_models_disk_bytes", "Models-dir filesystem size/free", "gauge");
            out.sample("caravan_models_disk_bytes", &total.to_string(), &[("kind", "total".to_string())]);
            out.sample("caravan_models_disk_bytes", &free.to_string(), &[("kind", "free".to_string())]);
        }
    }

    fn gpus(out: &mut Exposition, gpu_read: &Value) {
        out.metric("caravan_gpu_vram_used_mib", "GPU memory used (MiB)", "gauge");
        out.metric("caravan_gpu_util_pct", "GPU utilization percent", "gauge");
        out.metric("caravan_gpu_temperature_c", "GPU temperature", "gauge");
        out.metric("caravan_gpu_power_w", "GPU power draw", "gauge");
        for card in gpu_read.get("gpus").and_then(Value::as_array).into_iter().flatten() {
            let labels = [
                ("gpu", card.get("index").map_or_else(|| "0".to_string(), |index| Coerce::str_of(Some(index)))),
                ("name", Coerce::text(card.get("name"))),
            ];
            out.sample_of("caravan_gpu_vram_used_mib", card.get("memoryUsedMiB"), &labels);
            out.sample_of("caravan_gpu_util_pct", card.get("utilizationGpuPct"), &labels);
            out.sample_of("caravan_gpu_temperature_c", card.get("temperatureC"), &labels);
            out.sample_of("caravan_gpu_power_w", card.get("powerDrawW"), &labels);
        }
    }

    fn routes(&self, out: &mut Exposition) {
        let stats = ProxyStats::of(self.app);
        let state = stats.sample();
        out.metric("caravan_route_active_requests", "Requests currently streaming on the route", "gauge");
        out.metric("caravan_route_queue_depth", "Requests waiting in the route's queue", "gauge");
        for (port, row) in state.get("agents").and_then(Value::as_object).into_iter().flatten().filter(|(_, row)| row.is_object())
        {
            let route = {
                let said = row
                    .get("route")
                    .filter(|said| Coerce::truthy(Some(*said)))
                    .or_else(|| row.get("name").filter(|said| Coerce::truthy(Some(*said))));
                said.map_or_else(|| port.clone(), |said| Coerce::str_of(Some(said)))
            };
            let labels = [("port", port.clone()), ("route", route)];
            let active = row.get("active").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!(0));
            out.sample_of("caravan_route_active_requests", Some(&active), &labels);
            let depth = match row.get("queue") {
                Some(Value::Array(queue)) => json!(queue.len()),
                Some(number @ Value::Number(_)) => number.clone(),
                _ => json!(0),
            };
            out.sample_of("caravan_route_queue_depth", Some(&depth), &labels);
        }
        let daily = stats.daily_stats("");
        out.metric("caravan_route_requests_today", "Requests received today (resets at midnight)", "gauge");
        for (route, entry) in daily.get("routes").and_then(Value::as_object).into_iter().flatten() {
            for result in ["total", "failed", "paused"] {
                out.sample_of(
                    "caravan_route_requests_today",
                    entry.get(result),
                    &[("route", route.clone()), ("result", result.to_string())],
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_sample_escapes_its_labels() {
        let mut out = Exposition::default();
        out.metric("m", "help", "gauge");
        out.sample("m", "1", &[("a", "x\"y\nz".to_string())]);
        out.sample("n", "2", &[]);
        out.sample_of("o", None, &[]);
        assert_eq!(out.lines, ["# HELP m help", "# TYPE m gauge", "m{a=\"x\\\"y z\"} 1", "n 2"]);
    }
}
