//! The monitor's samples, kept for the charts.

use super::activity::Activity;
use super::incidents::IncidentLog;
use super::machine::{CpuTimes, MachineState};
use crate::app::App;
use crate::proxies::stats::ProxyStats;
use crate::proxies::token_history::TokenHistory;
use files::AtomicFile;
use plumbing::Ticking;
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

/// The history, and what the next sample is measured from.
#[derive(Default)]
pub struct MonitorMemory {
    held: Mutex<MonitorBook>,
}

#[derive(Default)]
struct MonitorBook {
    history: VecDeque<Value>,
    latest_full: Option<Value>,
    last_cpu: Option<CpuTimes>,
    last_disk: Option<Value>,
    last_net: Option<Value>,
    last_persist: f64,
}

/// The monitor of this controller.
pub struct MonitorSampler<'app> {
    app: &'app App,
}

impl<'app> MonitorSampler<'app> {
    const SLIM_ITEM_FIELDS: [&'static str; 24] = [
        "id",
        "label",
        "port",
        "state",
        "phase",
        "isCloud",
        "client",
        "method",
        "path",
        "status",
        "startedAt",
        "finishedAt",
        "durationMs",
        "elapsedMs",
        "firstByteMs",
        "error",
        "errorKind",
        "queuedMs",
        "upstream",
        "upstreamHost",
        "upstreamPort",
        "upstreamType",
        "providerId",
        "chain",
    ];
    const SLIM_SAMPLE_FIELDS: [&'static str; 7] = ["time", "cpuLoad", "cpu", "memory", "disk", "net", "gpu"];
    /// Seconds between two writes of the history: the charts read the one in memory, and the file is only what a restart starts from. Every 10 s
    /// it rewrote an hour of samples, 420 KB, on the NAS's disks (measured 2026-11-03; the owner: «write less»): a restart that is no release
    /// now starts without the last minutes, and a release writes it as it ends (`persist_now`).
    const PERSIST_EVERY: f64 = 600.0;

    /// The monitor of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// How long samples are kept.
    pub fn retention_seconds(&self) -> i64 {
        let said = self
            .app
            .admin
            .read(|doc| doc.get("monitor").and_then(|monitor| monitor.get("retentionSeconds")).and_then(Coerce::int));
        said.unwrap_or(self.app.paths.monitor_retention_default).clamp(60, 3600)
    }

    /// How long samples are kept from now on.
    pub fn set_retention(&self, seconds: Option<&Value>) -> Result<(), AppError> {
        let value = seconds.and_then(Coerce::int).ok_or_else(|| AppError::new("retentionSeconds must be a number"))?;
        self.app.admin.saving(|doc| {
            let monitor = doc.entry("monitor".to_string()).or_insert_with(|| json!({}));
            Coerce::put(monitor, "retentionSeconds", json!(value.clamp(60, 3600)));
        });
        self.trim();
        self.persist(true);
        Ok(())
    }

    fn time_of(row: &Value) -> f64 {
        Coerce::float_or_zero(row.get("time"))
    }

    fn trim(&self) {
        let cutoff = self.app.now() - self.retention_seconds() as f64;
        let mut book = self.app.monitor.held.lock().unwrap_or_else(PoisonError::into_inner);
        while book.history.front().is_some_and(|first| Self::time_of(first) < cutoff) {
            book.history.pop_front();
        }
    }

    fn persist(&self, force: bool) {
        let now = self.app.now();
        let samples: Vec<Value> = {
            let mut book = self.app.monitor.held.lock().unwrap_or_else(PoisonError::into_inner);
            if !force && now - book.last_persist < Self::PERSIST_EVERY {
                return;
            }
            book.last_persist = now;
            book.history.iter().cloned().collect()
        };
        let text = PythonJson::spaced(&json!({"retentionSeconds": self.retention_seconds(), "samples": samples}));
        let path = &self.app.paths.monitor_history_file;
        if let Some(parent) = path.parent() {
            drop(std::fs::create_dir_all(parent));
        }
        // A history that was not written is written on the next pass: the charts read the one in memory.
        drop(AtomicFile::write(path, text.as_bytes()));
    }

    /// The history to the file now, whenever it was last written: a process that is about to end.
    pub fn persist_now(&self) {
        self.persist(true);
    }

    fn load(&self) {
        let Some(payload) =
            std::fs::read(&self.app.paths.monitor_history_file).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok())
        else {
            return;
        };
        let cutoff = self.app.now() - self.retention_seconds() as f64;
        let mut book = self.app.monitor.held.lock().unwrap_or_else(PoisonError::into_inner);
        for sample in payload.get("samples").and_then(Value::as_array).into_iter().flatten() {
            if Self::time_of(sample) >= cutoff {
                book.history.push_back(Self::slim_sample(sample));
            }
        }
    }

    fn slim_item(item: &Value) -> Value {
        let kept: Map<String, Value> = Self::SLIM_ITEM_FIELDS
            .iter()
            .filter_map(|key| item.get(*key).map(|said| ((*key).to_string(), said.clone())))
            .collect();
        Value::Object(kept)
    }

    /// A sample as the charts' history keeps it.
    pub fn slim_sample(sample: &Value) -> Value {
        let mut slim: Map<String, Value> = Self::SLIM_SAMPLE_FIELDS
            .iter()
            .filter_map(|key| sample.get(*key).map(|said| ((*key).to_string(), said.clone())))
            .collect();
        if let Some(activity) = sample.get("correlatedActivity").filter(|said| said.is_object()) {
            let items = |key: &str| -> Vec<Value> {
                activity
                    .get(key)
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter(|item| item.is_object())
                    .map(Self::slim_item)
                    .collect()
            };
            let words = |part: &str, key: &str| {
                activity
                    .get(part)
                    .and_then(|part| part.get(key))
                    .filter(|said| Coerce::truthy(Some(*said)))
                    .cloned()
                    .unwrap_or_else(|| json!([]))
            };
            slim.insert(
                "correlatedActivity".to_string(),
                json!({
                    "ok": activity.get("ok").cloned().unwrap_or_else(|| json!(true)),
                    "time": activity.get("time"),
                    "activeRequests": items("activeRequests"),
                    "recentRequests": items("recentRequests"),
                    "llamaServer": {"activeRoutes": words("llamaServer", "activeRoutes"), "activeClients": words("llamaServer", "activeClients")},
                    "gpu": {"activeRoutes": words("gpu", "activeRoutes"), "cloudActiveRoutes": words("gpu", "cloudActiveRoutes")},
                }),
            );
        }
        Value::Object(slim)
    }

    /// One sample taken and kept.
    pub fn collect(&self) {
        let machine = MachineState::of(self.app);
        let now = self.app.now();
        let (cpu_now, disk_now, net_now) = (machine.cpu_times(), machine.disk_counters(), machine.net_counters());
        let (last_cpu, last_disk, last_net, previous_time) = {
            let book = self.app.monitor.held.lock().unwrap_or_else(PoisonError::into_inner);
            let previous = book.history.back().map_or(now, Self::time_of);
            (book.last_cpu.clone(), book.last_disk.clone(), book.last_net.clone(), previous)
        };
        let elapsed = (now - previous_time).max(0.001);
        let mut sample = json!({
            "time": now as i64,
            "cpu": MachineState::cpu_percentages(last_cpu.as_ref(), &cpu_now),
            "cpuLoad": MachineState::load_rounded(),
            "gpu": machine.gpu_sample(),
            "agentProxies": ProxyStats::of(self.app).sample(),
            "memory": machine.memory_sample(),
            "disk": MachineState::rate_delta(last_disk.as_ref(), &disk_now, elapsed, &["readBytes", "writeBytes"]),
            "net": MachineState::rate_delta(last_net.as_ref(), &net_now, elapsed, &["rxBytes", "txBytes"]),
            "processes": machine.top_processes(),
        });
        let correlated = Activity::correlate(&sample);
        Coerce::put(&mut sample, "correlatedActivity", correlated);
        TokenHistory::of(self.app).record(&sample);
        IncidentLog::of(self.app).append_from(&sample);
        {
            let mut book = self.app.monitor.held.lock().unwrap_or_else(PoisonError::into_inner);
            book.last_cpu = Some(cpu_now);
            book.last_disk = Some(disk_now);
            book.last_net = Some(net_now);
            book.history.push_back(Self::slim_sample(&sample));
            book.latest_full = Some(sample);
        }
        self.trim();
        self.persist(false);
    }

    /// The sampler's thread.
    pub fn start_thread(app: &Arc<App>) -> std::io::Result<()> {
        let app = Arc::clone(app);
        std::thread::Builder::new().name("monitor".to_string()).spawn(move || {
            let sampler = MonitorSampler::of(&app);
            sampler.load();
            Ticking::forever("monitor", Duration::from_secs_f64(app.paths.monitor_sample_interval), || sampler.collect());
        })?;
        Ok(())
    }

    /// The monitor's payload.
    pub fn state(&self, since: i64) -> Value {
        self.trim();
        let (samples, latest_full): (Vec<Value>, Option<Value>) = {
            let book = self.app.monitor.held.lock().unwrap_or_else(PoisonError::into_inner);
            (book.history.iter().cloned().collect(), book.latest_full.clone())
        };
        // absent-ok: no sample yet: the page asks for everything.
        let newest = samples.last().map_or(0.0, Self::time_of);
        let newest = if newest.fract() == 0.0 { json!(newest as i64) } else { json!(newest) };
        let incidents = IncidentLog::of(self.app).load(200);
        let shown_samples: Vec<&Value> = if since > 0 {
            samples.iter().filter(|sample| Self::time_of(sample) > since as f64).collect()
        } else {
            samples.iter().collect()
        };
        let shown_incidents: Vec<&Value> = if since > 0 {
            incidents.iter().filter(|row| Self::time_of(row) > since as f64).collect()
        } else {
            incidents.iter().collect()
        };
        let mut out = json!({
            "ok": true,
            "intervalSeconds": self.app.paths.monitor_sample_interval,
            "retentionSeconds": self.retention_seconds(),
            "samples": shown_samples,
        });
        if since > 0 {
            Coerce::put(&mut out, "partial", json!(true));
        }
        Coerce::put(&mut out, "newestSample", newest);
        Coerce::put(&mut out, "latest", latest_full.or_else(|| samples.last().cloned()).unwrap_or(Value::Null));
        Coerce::put(&mut out, "incidents", json!(shown_incidents));
        Coerce::put(&mut out, "incidentRetentionSeconds", json!(self.app.paths.incident_retention_seconds));
        Coerce::put(&mut out, "time", json!(self.app.now_whole()));
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_kept_sample_holds_only_what_the_charts_read() {
        let sample = json!({"time": 5, "cpu": 1, "processes": [1], "correlatedActivity": {"time": 5, "activeRequests": [{"id": "a", "request": {"x": 1}}], "gpu": {"activeRoutes": ["L"], "activeClients": ["c"]}}});
        let slim = MonitorSampler::slim_sample(&sample);
        assert!(slim.get("processes").is_none());
        assert_eq!(slim["correlatedActivity"]["activeRequests"], json!([{"id": "a"}]));
        assert_eq!(slim["correlatedActivity"]["gpu"], json!({"activeRoutes": ["L"], "cloudActiveRoutes": []}));
        assert_eq!(slim["correlatedActivity"]["ok"], true);
    }

    #[test]
    fn the_history_goes_to_its_file_once_in_its_time_and_whenever_it_is_asked() {
        let folder = crate::tests::TestFolder::new("monitor-persist");
        let clock = crate::tests::HandClock::at(1_000);
        let app = crate::tests::TestApp::with_clock(&folder.path, &[], clock.clone());
        let sampler = MonitorSampler::of(&app);
        let sample = |at: f64| app.monitor.held.lock().unwrap().history.push_back(json!({"time": at}));
        let kept = || -> Vec<f64> {
            let doc: Value = serde_json::from_slice(&std::fs::read(&app.paths.monitor_history_file).unwrap()).unwrap();
            doc["samples"].as_array().unwrap().iter().map(MonitorSampler::time_of).collect()
        };
        sample(app.now());
        sampler.persist(false);
        assert_eq!(kept(), [1_000.0], "a process's first sample is written at once");
        clock.pass(MonitorSampler::PERSIST_EVERY as u64 - 10);
        sample(app.now());
        sampler.persist(false);
        assert_eq!(kept(), [1_000.0], "negative: the samples of its time wait for it in memory");
        clock.pass(10);
        sample(app.now());
        sampler.persist(false);
        assert_eq!(kept(), [1_000.0, 1_590.0, 1_600.0], "after it, they are all written");
        clock.pass(10);
        sample(app.now());
        sampler.persist_now();
        assert_eq!(kept(), [1_000.0, 1_590.0, 1_600.0, 1_610.0], "a process about to end writes them whenever it is");
    }
}
