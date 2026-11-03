//! The two outside tables: the Artificial Analysis index, read from its pages, and the Open LLM Leaderboard, read whole in the background.

use super::Benchmarks;
use super::tables::BenchTables;
use crate::app::App;
use crate::common::misc::TtlCache;
use files::AtomicFile;
use plumbing::Log;
use regex::Regex;
use rules::{Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::Duration;

/// The index's scores as known; `None` before the first read of the file.
#[derive(Default)]
struct IndexMap {
    scores: Option<Map<String, Value>>,
    misses: HashMap<String, f64>,
}

/// The leaderboard as read.
#[derive(Default)]
struct Leaderboard {
    rows: HashMap<String, Map<String, Value>>,
    loaded_at: f64,
    loading: bool,
}

/// What these readings keep, and the rules they read by.
pub struct BenchMemory {
    pub(super) json_cache: TtlCache<String, Value>,
    html_cache: TtlCache<String, String>,
    frontier: Mutex<Option<(Vec<Value>, f64)>>,
    index: Mutex<IndexMap>,
    board: Mutex<Leaderboard>,
    pair: Regex,
    pub(super) dash_run: Regex,
    pub(super) repo_tail: Regex,
    pub(super) gguf_tail: Regex,
    pub(super) author_hints: Vec<(Regex, &'static str)>,
    tag: Regex,
    dots: Regex,
    kind_tail: Regex,
    version_tail: Regex,
    dashes: Regex,
}

impl BenchMemory {
    const URL_TTL: f64 = 3600.0;

    /// Empty, the rules compiled.
    pub fn new() -> Result<Self, regex::Error> {
        let mut author_hints = Vec::with_capacity(BenchTables::AUTHOR_HINTS.len());
        for (pattern, author) in BenchTables::AUTHOR_HINTS {
            author_hints.push((Regex::new(pattern)?, author));
        }
        Ok(Self {
            json_cache: TtlCache::new(Self::URL_TTL),
            html_cache: TtlCache::new(Self::URL_TTL),
            frontier: Mutex::new(None),
            index: Mutex::default(),
            board: Mutex::default(),
            pair: Regex::new(
                r#""artificialAnalysisIntelligenceIndex":([0-9.]+)[^}]{0,80}?"detailsUrl":"/models/([a-z0-9.\-]+)""#,
            )?,
            dash_run: Regex::new(r"[-_]+")?,
            repo_tail: Regex::new(r"(?i)[-_](gguf|q[\d]+|imatrix|exl2)$")?,
            gguf_tail: Regex::new(r"(?i)[-_]gguf$")?,
            author_hints,
            tag: Regex::new(r":.*$")?,
            dots: Regex::new(r"[._]")?,
            kind_tail: Regex::new(r"[-_](it|instruct|chat|hf|tulu)$")?,
            version_tail: Regex::new(r"-v\d+(-\d+)*$")?,
            dashes: Regex::new(r"-+")?,
        })
    }

    fn slug(&self, model_id: &str, drop_tag: bool) -> String {
        let name = model_id.rsplit('/').next().unwrap_or(model_id).to_lowercase();
        let name = if drop_tag { self.tag.replace(&name, "").into_owned() } else { name };
        let name = self.dots.replace_all(&name, "-").into_owned();
        let name = self.kind_tail.replace(&name, "").into_owned();
        let name = self.version_tail.replace(&name, "").into_owned();
        self.dashes.replace_all(&name, "-").trim_matches('-').to_string()
    }
}

/// The Artificial Analysis Intelligence Index.
pub struct QualityIndex<'app> {
    app: &'app App,
}

impl<'app> QualityIndex<'app> {
    const FRONTIER_TTL: f64 = 12.0 * 3600.0;
    const MAP_TTL: f64 = 7.0 * 86400.0;
    const MISS_TTL: f64 = 86400.0;
    const FETCH_CAP: usize = 12;
    const PAGE_TIMEOUT: u64 = 20;
    const BROWSER: &'static str =
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36";

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn memory(&self) -> &'app BenchMemory {
        &self.app.bench
    }

    /// A page, an hour in memory; "" when it did not come.
    fn page(&self, url: &str) -> String {
        let memory = self.memory();
        let key = url.to_string();
        if let Some(hit) = memory.html_cache.get(&key, self.app.now(), None) {
            return hit;
        }
        let fields = [("User-Agent", Self::BROWSER.to_string())];
        let fetched = self.app.http.following_with(url, &fields, Duration::from_secs(Self::PAGE_TIMEOUT));
        let Some(raw) = fetched.ok().and_then(|answer| answer.text(64 << 20).ok()) else {
            return String::new();
        };
        let text = String::from_utf8_lossy(&raw).into_owned();
        memory.html_cache.put(key, text.clone(), self.app.now());
        text
    }

    /// Every `{slug: score}` a page's data holds, the first for a slug kept.
    fn scores_in(&self, html: &str) -> Map<String, Value> {
        let mut out = Map::new();
        for pair in self.memory().pair.captures_iter(html) {
            let (Some(score), Some(slug)) = (pair.get(1), pair.get(2)) else {
                continue;
            };
            if out.contains_key(slug.as_str()) {
                continue;
            }
            if let Ok(score) = score.as_str().parse::<f64>() {
                out.insert(slug.as_str().to_string(), json!(Coerce::rounded(score, 1)));
            }
        }
        out
    }

    fn page_of(&self, slug: &str) -> String {
        self.page(&format!("https://artificialanalysis.ai/models/{slug}"))
    }

    /// The index of a model of the hub, from its page.
    pub(super) fn score_of(&self, model_id: &str) -> Option<f64> {
        let slug = self.memory().slug(model_id, false);
        self.scores_in(&self.page_of(&slug)).get(&slug).and_then(Value::as_f64)
    }

    fn frontier_held(&self) -> MutexGuard<'app, Option<(Vec<Value>, f64)>> {
        self.memory().frontier.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The scores of the curated frontier models: `force` reads them now and waits, else what was read, else what is written here.
    pub fn reference_models(&self, force: bool) -> Value {
        if force {
            let results: Vec<Value> = BenchTables::FRONTIER
                .iter()
                .map(|model| {
                    let found = self.scores_in(&self.page_of(model.slug)).get(model.slug).and_then(Value::as_f64);
                    json!({"name": model.name, "org": model.org, "slug": model.slug, "aa": found.unwrap_or(model.aa)})
                })
                .collect();
            *self.frontier_held() = Some((results.clone(), self.app.now()));
            return json!({"ok": true, "models": results, "source": "aa"});
        }
        if let Some((models, when)) = self.frontier_held().as_ref()
            && self.app.now() - when < Self::FRONTIER_TTL
        {
            return json!({"ok": true, "models": models, "source": "cache"});
        }
        let defaults: Vec<Value> = BenchTables::FRONTIER
            .iter()
            .map(|model| json!({"name": model.name, "org": model.org, "slug": model.slug, "aa": model.aa}))
            .collect();
        json!({"ok": true, "models": defaults, "source": "default"})
    }

    fn load_map(&self, held: &mut IndexMap) -> Map<String, Value> {
        let mut seeded: Map<String, Value> =
            BenchTables::FRONTIER.iter().map(|model| (model.slug.to_string(), json!(model.aa))).collect();
        let raw = std::fs::read(&self.app.paths.aa_scores_cache).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
        if let Some(raw) = raw {
            // absent-ok: `raw.get("cached_at", 0)`: a file that does not say when is as old as can be.
            let cached_at = Coerce::float_or_zero(raw.get("cached_at"));
            if self.app.now() - cached_at < Self::MAP_TTL {
                for (slug, score) in Coerce::fields(raw.get("scores").unwrap_or(&Value::Null)) {
                    seeded.entry(slug).or_insert(score);
                }
                for (slug, when) in Coerce::fields(raw.get("neg").unwrap_or(&Value::Null)) {
                    if let Some(when) = Coerce::float(&when) {
                        held.misses.entry(slug).or_insert(when);
                    }
                }
            }
        }
        seeded
    }

    fn save_map(&self, held: &IndexMap) {
        let misses: Map<String, Value> = held.misses.iter().map(|(slug, when)| (slug.clone(), json!(when))).collect();
        let body = PythonJson::spaced_letters(&json!({"cached_at": self.app.now(), "scores": held.scores, "neg": misses}));
        let path = &self.app.paths.aa_scores_cache;
        let made = path.parent().map_or(Ok(()), std::fs::create_dir_all);
        if let Err(error) = made.and_then(|()| AtomicFile::write(path, body.as_bytes())) {
            Log::line(&format!("benchmarks: the index's scores not kept: {error}"));
        }
    }

    /// The index of the given model ids. The lock stays held while pages are read: two windows asking do not read the same page twice.
    pub fn scores(&self, model_ids: &[String], fetch: bool) -> Value {
        let memory = self.memory();
        let mut held = memory.index.lock().unwrap_or_else(PoisonError::into_inner);
        let mut known = match held.scores.take() {
            Some(known) => known,
            None => self.load_map(&mut held),
        };
        let now = self.app.now();
        let mut result = Map::new();
        let mut missed: Vec<(String, String)> = Vec::new();
        for model in model_ids.iter().filter(|model| !Coerce::strip(model).is_empty()) {
            let slug = memory.slug(model, true);
            match known.get(&slug) {
                Some(score) => {
                    result.insert(model.clone(), score.clone());
                }
                None => missed.push((model.clone(), slug)),
            }
        }
        let mut dirty = false;
        if fetch {
            let mut fetched = 0;
            for (model, slug) in &missed {
                if fetched >= Self::FETCH_CAP {
                    break;
                }
                let tried = held.misses.get(slug).is_some_and(|when| now - when < Self::MISS_TTL);
                if tried {
                    continue;
                }
                fetched += 1;
                let harvested = self.scores_in(&self.page_of(slug));
                if !harvested.is_empty() {
                    known.extend(harvested);
                    dirty = true;
                }
                if let Some(score) = known.get(slug) {
                    result.insert(model.clone(), score.clone());
                } else {
                    held.misses.insert(slug.clone(), now);
                    dirty = true;
                }
            }
        }
        held.scores = Some(known);
        if dirty {
            self.save_map(&held);
        }
        let bad: Vec<&String> = missed
            .iter()
            .filter(|(model, slug)| {
                !result.contains_key(model) && held.misses.get(slug).is_some_and(|when| now - when < Self::MISS_TTL)
            })
            .map(|(model, _)| model)
            .collect();
        json!({"ok": true, "scores": result, "misses": bad})
    }
}

/// The Open LLM Leaderboard v2, read whole in the background.
pub struct OpenLeaderboard<'app> {
    app: &'app App,
}

impl<'app> OpenLeaderboard<'app> {
    const TTL: f64 = 86400.0;
    const PAGE: i64 = 100;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn held(&self) -> MutexGuard<'app, Leaderboard> {
        self.app.bench.board.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn load(&self) {
        let token = self.app.hf_token();
        let reader = Benchmarks::of(self.app);
        let mut rows = HashMap::new();
        let mut offset = 0i64;
        let mut total = None;
        loop {
            let url = format!(
                "https://datasets-server.huggingface.co/rows?dataset=open-llm-leaderboard%2Fcontents&config=default&split=train&offset={offset}&limit={}",
                Self::PAGE
            );
            let data = reader.fetch_json(&url, 30, &token);
            if !data.is_object() || Coerce::truthy(data.get("_error")) {
                break;
            }
            // absent-ok: `data.get("num_rows_total") or 0`: a page that does not say how many ends with the first empty page.
            let all = *total.get_or_insert_with(|| Coerce::whole(data.get("num_rows_total")));
            let page: &[Value] = data.get("rows").and_then(Value::as_array).map_or(&[], Vec::as_slice);
            for found in page {
                let row = found.get("row");
                let name = Coerce::stripped(row.and_then(|row| row.get("fullname"))).to_lowercase();
                if name.is_empty() {
                    continue;
                }
                let mut scores = Map::new();
                for (field, key) in BenchTables::OPEN_LLM {
                    if let Some(score) = Benchmarks::normalize_score(row.and_then(|row| row.get(field))) {
                        scores.insert(key.to_string(), json!(score));
                    }
                }
                if !scores.is_empty() {
                    rows.insert(name, scores);
                }
            }
            offset += i64::try_from(page.len()).unwrap_or(i64::MAX);
            if page.is_empty() || (all != 0 && offset >= all) {
                break;
            }
        }
        let mut held = self.held();
        if !rows.is_empty() {
            held.rows = rows;
            held.loaded_at = self.app.now();
        }
        held.loading = false;
    }

    /// Starts the read when the table is empty or older than a day.
    pub fn ensure(&self) {
        {
            let mut held = self.held();
            if held.loading || (!held.rows.is_empty() && self.app.now() - held.loaded_at < Self::TTL) {
                return;
            }
            held.loading = true;
        }
        let Some(app) = self.app.shared() else {
            self.held().loading = false;
            return;
        };
        let started =
            std::thread::Builder::new().name("open-llm-board".to_string()).spawn(move || OpenLeaderboard::of(&app).load());
        if let Err(error) = started {
            Log::line(&format!("benchmarks: the leaderboard's read did not start: {error}"));
            self.held().loading = false;
        }
    }

    /// The scores of a base model, as far as they are read.
    pub(super) fn scores(&self, model_id: &str) -> Map<String, Value> {
        self.ensure();
        // absent-ok: a model the leaderboard does not list has no scores from it.
        self.held().rows.get(&model_id.to_lowercase()).cloned().unwrap_or_default()
    }

    /// How far the read is.
    pub fn status(&self) -> Value {
        let held = self.held();
        let age = (held.loaded_at != 0.0).then(|| Coerce::rounded((self.app.now() - held.loaded_at) / 3600.0, 1));
        json!({"loaded": !held.rows.is_empty(), "count": held.rows.len(), "loading": held.loading, "age_hours": age})
    }
}
