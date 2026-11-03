//! What a cell's server says about itself over HTTP, per port: token rates and its queue from `/metrics` (kept about 2 s), the context window a `llama-server` was launched with and how many requests it
//! takes at once from `/props` (kept about 30 s).
//!
//! `llama-server` and vLLM tell the same facts under different names, and Strata tells them in vLLM's names and its own, but only in Prometheus text, which it gives to a reader that asks for it. A server
//! that does not answer says nothing, and that silence is kept as long as an answer would be. A server that answers it keeps none (404, 501) says that: `noMetrics`.

use crate::http_client::{HttpClient, HttpError};
use crate::machine::Rounded;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

/// Figures by name.
type Figures = BTreeMap<String, f64>;
/// (tokens, seconds) of a rate.
type Pair = (&'static str, &'static str);

/// One scrape, sorted by how each sample is read.
#[derive(Debug, Default)]
struct Scrape {
    gauges: Figures,
    counted: Figures,
    timed: Figures,
    strata: Figures,
}

impl Scrape {
    /// Read as they are: Prometheus name, the view's key.
    const GAUGES: [(&'static str, &'static str); 7] = [
        ("llamacpp:prompt_tokens_seconds", "promptTps"),
        ("llamacpp:predicted_tokens_seconds", "genTps"),
        ("llamacpp:requests_processing", "requestsProcessing"),
        ("llamacpp:kv_cache_usage_ratio", "_kvRatio"),
        ("vllm:num_requests_running", "requestsProcessing"),
        ("vllm:num_requests_waiting", "requestsWaiting"),
        // vLLM's own number is its KV block pool; Strata says the running request's share of its context here.
        ("vllm:kv_cache_usage_perc", "_kvRatio"),
    ];
    /// Counted: the growth per second between two readings is the rate.
    const COUNTERS: [(&'static str, &'static str); 2] =
        [("vllm:prompt_tokens_total", "promptTps"), ("vllm:generation_tokens_total", "genTps")];
    /// Token counts divided by engine compute seconds, not elapsed wall time.
    const TIMED: [(&'static str, Pair); 2] = [
        ("promptTps", ("llamacpp:prompt_tokens_total", "llamacpp:prompt_seconds_total")),
        ("genTps", ("llamacpp:tokens_predicted_total", "llamacpp:tokens_predicted_seconds_total")),
    ];
    /// What a Strata server says of its speed. The running request's own rates are read as they are.
    const STRATA_GAUGES: [(&'static str, &'static str); 2] =
        [("strata:live_tok_s", "genTps"), ("strata:live_prefill_tok_s_mean", "promptTps")];
    const STRATA_READ: &'static str = "strata:prompt_tokens_read";
    /// Its prompt tokens include the ones its cache already held: only the rest was read, and cost the time, so the pair is made of the rest.
    const STRATA_TIMED: [(&'static str, Pair); 2] = [
        ("promptTps", (Self::STRATA_READ, "strata:totals_prompt_seconds_total")),
        ("genTps", ("vllm:generation_tokens_total", "strata:totals_decode_seconds_total")),
    ];
    /// The samples of a scrape that the Strata reading needs, by their names in the text.
    const STRATA_NAMES: [&'static str; 7] = [
        "vllm:prompt_tokens_total",
        "vllm:generation_tokens_total",
        "vllm:prefix_cache_hits_total",
        "strata:totals_prompt_seconds_total",
        "strata:totals_decode_seconds_total",
        "strata:live_tok_s",
        "strata:live_prefill_tok_s_mean",
    ];

    /// The samples of a text. Lines with labels (vLLM's engine, model) are summed per name.
    fn of(text: &str) -> Self {
        let mut out = Self::default();
        for line in text.lines().filter(|line| !line.starts_with('#') && !line.trim().is_empty()) {
            let name = line.split('{').next().and_then(|head| head.split_whitespace().next());
            let number = line.split_whitespace().next_back().and_then(|word| word.parse::<f64>().ok());
            if let (Some(name), Some(number)) = (name, number.filter(|number| number.is_finite() && *number >= 0.0)) {
                out.add(name, number);
            }
        }
        out
    }

    fn add(&mut self, name: &str, number: f64) {
        if Self::STRATA_NAMES.contains(&name) {
            *self.strata.entry(name.to_string()).or_default() += number;
        }
        if let Some((_, key)) = Self::GAUGES.iter().find(|(said, _)| *said == name) {
            *self.gauges.entry((*key).to_string()).or_default() += number;
        } else if Self::COUNTERS.iter().any(|(said, _)| *said == name) {
            *self.counted.entry(name.to_string()).or_default() += number;
        } else if Self::TIMED.iter().any(|(_, (tokens, seconds))| *tokens == name || *seconds == name) {
            *self.timed.entry(name.to_string()).or_default() += number;
        }
    }

    fn is_strata(&self) -> bool {
        self.strata.keys().any(|name| name.starts_with("strata:"))
    }

    /// The samples and the running request's rates of a Strata server.
    fn strata_samples(&self) -> (Figures, Figures) {
        let mut values = Figures::new();
        for name in ["vllm:generation_tokens_total", "strata:totals_prompt_seconds_total", "strata:totals_decode_seconds_total"] {
            if let Some(value) = self.strata.get(name) {
                values.insert(name.to_string(), *value);
            }
        }
        if let (Some(prompt), Some(hits)) =
            (self.strata.get("vllm:prompt_tokens_total"), self.strata.get("vllm:prefix_cache_hits_total"))
        {
            values.insert(Self::STRATA_READ.to_string(), (prompt - hits).max(0.0));
        }
        let live = Self::STRATA_GAUGES
            .iter()
            .filter_map(|(name, key)| self.strata.get(*name).map(|value| ((*key).to_string(), *value)))
            .collect();
        (values, live)
    }
}

/// What the probe remembers between readings.
#[derive(Debug, Default)]
struct Memory {
    metrics: BTreeMap<i64, (f64, Map<String, Value>)>,
    props: BTreeMap<i64, (f64, Map<String, Value>)>,
    counted: BTreeMap<i64, (f64, Figures)>,
    timed: BTreeMap<i64, (String, Figures, Figures)>,
}

/// How a cell's server is asked: a parameter, so that a table answers in a test.
pub trait ServerAsk: Send + Sync {
    /// The text of `/metrics` and the identity of the process that said it.
    fn metrics(&self, port: i64) -> Result<(String, String), HttpError>;
    /// What `/props` says; `None` when it says nothing: another kind of server, or no answer.
    fn props(&self, port: i64) -> Option<Value>;
}

/// The cell's server itself, over HTTP.
pub struct HttpServerAsk {
    /// How to ask.
    pub http: Arc<HttpClient>,
}

impl HttpServerAsk {
    const TIMEOUT: Duration = Duration::from_secs(1);
}

impl ServerAsk for HttpServerAsk {
    /// A reader that asks for text/plain is what Prometheus is: `llama.cpp` and vLLM answer it anyway, Strata only then.
    fn metrics(&self, port: i64) -> Result<(String, String), HttpError> {
        let url = format!("http://127.0.0.1:{port}/metrics");
        let fields = [("Accept", "text/plain".to_string())];
        let answer = self.http.ask("GET", &url, &fields, &[], Self::TIMEOUT)?;
        // absent-ok: a server that names no start of its process has one identity for all it says.
        let start = answer.head.headers.get("Process-Start-Time-Unix").unwrap_or_default();
        let raw = answer.text(64 << 20)?;
        Ok((String::from_utf8_lossy(&raw).into_owned(), start))
    }

    fn props(&self, port: i64) -> Option<Value> {
        self.http.json("GET", &format!("http://127.0.0.1:{port}/props"), &[], &[], Self::TIMEOUT).ok()
    }
}

/// The probe.
pub struct ServerProbe {
    ask: Arc<dyn ServerAsk>,
    clock: Arc<dyn Clock>,
    memory: Mutex<Memory>,
}

impl ServerProbe {
    const METRICS_KEPT: f64 = 2.0;
    const PROPS_KEPT: f64 = 30.0;

    /// A probe of nothing yet.
    pub fn new(ask: Arc<dyn ServerAsk>, clock: Arc<dyn Clock>) -> Self {
        Self { ask, clock, memory: Mutex::new(Memory::default()) }
    }

    fn memory(&self) -> MutexGuard<'_, Memory> {
        self.memory.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The cell's live token rates and its queue: each only when the server says it, or `noMetrics` when it answers that it keeps none.
    pub fn metrics(&self, port: i64) -> Map<String, Value> {
        let now = self.clock.epoch();
        if let Some((at, kept)) = self.memory().metrics.get(&port).filter(|(at, _)| now - *at < Self::METRICS_KEPT) {
            let _read_at = at;
            return kept.clone();
        }
        let (scrape, start, refused) = match self.ask.metrics(port) {
            Ok((text, start)) => (Scrape::of(&text), start, false),
            // The server answered and keeps no metrics: said out loud, so the board says the speed is not measured, not that no request came (2026-10-26). Any other refusal says nothing.
            Err(HttpError::Status(404 | 501, _)) => (Scrape::default(), String::new(), true),
            Err(_) => (Scrape::default(), String::new(), false),
        };
        let mut figures = scrape.gauges.clone();
        let mut counted = scrape.counted.clone();
        if scrape.is_strata() {
            // A Strata server: its own readings of its speed. The growth of vLLM's counters between two scrapes would be zero between two requests and a spike at the one that finished.
            let (values, live) = scrape.strata_samples();
            figures.extend(self.timed_rates(port, &values, "", &live, &Scrape::STRATA_TIMED));
            counted.clear();
        } else if !scrape.timed.is_empty() {
            let gauges = figures.clone();
            for (key, value) in self.timed_rates(port, &scrape.timed, &start, &gauges, &Scrape::TIMED) {
                if !figures.get(&key).is_some_and(|said| *said != 0.0) {
                    figures.insert(key, value);
                }
            }
        }
        let out = self.view_of(port, &figures, &counted, refused, now);
        self.memory().metrics.insert(port, (now, out.clone()));
        out
    }

    fn view_of(&self, port: i64, figures: &Figures, counted: &Figures, refused: bool, now: f64) -> Map<String, Value> {
        let mut out = Map::new();
        if refused {
            out.insert("noMetrics".to_string(), json!(true));
        }
        for (key, value) in figures {
            let said = match key.as_str() {
                "promptTps" | "genTps" => json!(Rounded::to(*value, 2)),
                "requestsProcessing" | "requestsWaiting" => json!(value.trunc() as i64),
                "_kvRatio" => continue,
                _ => json!(value),
            };
            out.insert(key.clone(), said);
        }
        self.add_counted_rates(port, counted, now, &mut out);
        // The context window the server launched with, and the live KV-cache occupancy.
        let ctx_max = self.ctx_max(port);
        if ctx_max != 0 {
            out.insert("ctxMax".to_string(), json!(ctx_max));
            if let Some(ratio) = figures.get("_kvRatio") {
                out.insert("ctxUsed".to_string(), json!((ratio * ctx_max as f64).round_ties_even() as i64));
            }
        }
        out
    }

    fn add_counted_rates(&self, port: i64, counted: &Figures, now: f64, out: &mut Map<String, Value>) {
        if counted.is_empty() {
            return;
        }
        let mut memory = self.memory();
        if let Some((at, before)) = memory.counted.get(&port).filter(|(at, _)| now > *at) {
            for (name, key) in Scrape::COUNTERS {
                // A counter that went down is a restarted server: no rate.
                if let (Some(value), Some(previous)) =
                    (counted.get(name), before.get(name)).into_pair_where(|value, previous| value >= previous)
                {
                    out.insert(key.to_string(), json!(Rounded::to((value - previous) / (now - at), 2)));
                }
            }
        }
        memory.counted.insert(port, (now, counted.clone()));
    }

    /// The latest observed token over compute-time rates, retained while idle. The first scrape uses the server's accumulated average; later scrapes only the new work, which may cover several requests. A
    /// process identity change or a counter decrease discards the previous rates.
    fn timed_rates(&self, port: i64, values: &Figures, start: &str, gauges: &Figures, pairs: &[(&'static str, Pair)]) -> Figures {
        let mut memory = self.memory();
        let (mut previous, mut rates) = match memory.timed.get(&port) {
            Some((said, previous, rates)) if said == start => (previous.clone(), rates.clone()),
            _ => (Figures::new(), Figures::new()),
        };
        // absent-ok: a sample never seen before has nothing to fall below.
        if values.iter().any(|(name, value)| *value < previous.get(name).copied().unwrap_or(0.0)) {
            previous.clear();
            rates.clear();
        }
        for (key, (tokens, seconds)) in pairs {
            let (Some(count), Some(duration)) = (values.get(*tokens), values.get(*seconds)) else {
                rates.remove(*key);
                continue;
            };
            let (mut count, mut duration) = (*count, *duration);
            if let (Some(tokens_before), Some(seconds_before)) = (previous.get(*tokens), previous.get(*seconds)) {
                count -= tokens_before;
                duration -= seconds_before;
            }
            if duration > 0.0 {
                rates.insert((*key).to_string(), Rounded::to(count / duration, 2));
            }
            if let Some(gauge) = gauges.get(*key).filter(|gauge| **gauge > 0.0) {
                rates.insert((*key).to_string(), Rounded::to(*gauge, 2));
            }
        }
        memory.timed.insert(port, (start.to_string(), values.clone(), rates.clone()));
        rates
    }

    /// What a `llama-server` says of itself at `/props`, kept about 30 s per port; empty when the server says nothing: another kind of server, or no answer.
    fn props(&self, port: i64) -> Map<String, Value> {
        let now = self.clock.epoch();
        if let Some((_, kept)) = self.memory().props.get(&port).filter(|(at, _)| now - *at < Self::PROPS_KEPT) {
            return kept.clone();
        }
        // absent-ok: silence is what the board reads as "says nothing".
        let props = self.ask.props(port).and_then(|said| said.as_object().cloned()).unwrap_or_default();
        self.memory().props.insert(port, (now, props.clone()));
        props
    }

    /// `n_ctx` the `llama-server` was launched with; 0 when it does not say.
    pub fn ctx_max(&self, port: i64) -> i64 {
        let props = self.props(port);
        let settings = props.get("default_generation_settings");
        let inner = settings.and_then(|settings| settings.get("n_ctx")).filter(|said| Coerce::truthy(Some(*said)));
        // absent-ok: `int(... or 0)`: a server that says no window has none to take a share of.
        inner.or_else(|| props.get("n_ctx")).and_then(|said| Coerce::int_or_zero(Some(said))).unwrap_or(0)
    }

    /// How many requests the server takes at once, `total_slots` of `/props`; `None` when it does not say: a server of another kind, or one that does not answer.
    pub fn slots_total(&self, port: i64) -> Option<i64> {
        self.props(port).get("total_slots").and_then(Value::as_i64).filter(|slots| *slots > 0)
    }
}

/// Two samples together, when both are there and they stand as asked.
trait PairWhere<'a> {
    fn into_pair_where(self, test: impl Fn(&f64, &f64) -> bool) -> (Option<&'a f64>, Option<&'a f64>);
}

impl<'a> PairWhere<'a> for (Option<&'a f64>, Option<&'a f64>) {
    fn into_pair_where(self, test: impl Fn(&f64, &f64) -> bool) -> (Option<&'a f64>, Option<&'a f64>) {
        match self {
            (Some(value), Some(previous)) if test(value, previous) => (Some(value), Some(previous)),
            _ => (None, None),
        }
    }
}
