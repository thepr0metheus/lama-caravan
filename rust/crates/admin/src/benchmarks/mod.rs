//! Model quality metadata. Scores from the hub's model cards, the Open LLM Leaderboard, Chatbot Arena and Artificial Analysis; what cannot be fetched is left out, never guessed.

pub mod quality;
pub mod tables;

use crate::app::App;
use crate::models::hf::HubBrowser;
use files::AtomicFile;
use plumbing::Log;
use quality::{BenchMemory, OpenLeaderboard, QualityIndex};
use regex::Regex;
use rules::{Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::time::Duration;
use tables::BenchTables;
use wire::Percent;

/// The readings.
pub struct Benchmarks<'app> {
    app: &'app App,
}

impl<'app> Benchmarks<'app> {
    const RESULT_TTL: f64 = 90.0 * 86400.0;
    const INLINE_SHOWN: usize = 3;
    const USER_AGENT: &'static str = "lama-caravan/1.0";

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn memory(&self) -> &'app BenchMemory {
        &self.app.bench
    }

    /// A JSON answer, an hour in memory, or `{"_error": words}`.
    pub(super) fn fetch_json(&self, url: &str, timeout: u64, token: &str) -> Value {
        let key = format!("{url}{}", if token.is_empty() { "" } else { "|auth" });
        if let Some(hit) = self.memory().json_cache.get(&key, self.app.now(), None) {
            return hit;
        }
        let mut fields = vec![("User-Agent", Self::USER_AGENT.to_string())];
        if !token.is_empty() {
            fields.push(("Authorization", format!("Bearer {token}")));
        }
        match self.app.http.json("GET", url, &fields, b"", Duration::from_secs(timeout)) {
            Ok(data) => {
                self.memory().json_cache.put(key, data.clone(), self.app.now());
                data
            }
            Err(error) => json!({"_error": error.to_string()}),
        }
    }

    /// A score as the table holds it: a fraction becomes a percent; what is not a number is none.
    pub(super) fn normalize_score(value: Option<&Value>) -> Option<f64> {
        let number = value.filter(|value| !value.is_null()).and_then(Coerce::float)?;
        let scaled = if number > 0.0 && number <= 1.0 { Coerce::rounded(number * 100.0, 1) } else { number };
        Some(Coerce::rounded(scaled, 1))
    }

    fn from_card(card: &Value) -> Map<String, Value> {
        let mut scores = Map::new();
        let data = card.get("cardData").filter(|said| Coerce::truthy(Some(*said)));
        let evals = data
            .and_then(|data| data.get("eval_results"))
            .filter(|said| Coerce::truthy(Some(*said)))
            .or_else(|| card.get("eval_results"));
        for entry in evals.and_then(Value::as_array).into_iter().flatten().filter(|entry| entry.is_object()) {
            let dataset = entry.get("dataset");
            let named = dataset.and_then(|dataset| dataset.get("name")).filter(|said| Coerce::truthy(Some(*said)));
            let said = named.or_else(|| dataset.and_then(|dataset| dataset.get("type")));
            let name = Coerce::text(said).to_lowercase().replace('-', "_");
            let Some((_, key)) = BenchTables::DATASETS.iter().find(|(pattern, _)| name.contains(pattern)) else {
                continue;
            };
            let metrics = entry.get("metrics").and_then(Value::as_array).into_iter().flatten();
            let found = metrics.filter(|metric| metric.is_object()).find_map(|metric| Self::normalize_score(metric.get("value")));
            if let Some(score) = found {
                scores.entry((*key).to_string()).or_insert_with(|| json!(score));
            }
        }
        scores
    }

    fn arena_elo(&self, model_id: &str) -> Map<String, Value> {
        let mut out = Map::new();
        let token = self.app.hf_token();
        if token.is_empty() {
            return out;
        }
        let name = model_id.rsplit('/').next().unwrap_or(model_id);
        let url = format!(
            "https://datasets-server.huggingface.co/search?dataset=lmsys%2Fchatbot-arena-leaderboard&config=default&split=train&query={}&limit=5",
            Percent::encode_path(name)
        );
        let raw = self.fetch_json(&url, 12, &token);
        if !raw.is_object() || Coerce::truthy(raw.get("_error")) {
            return out;
        }
        let first = |row: Option<&Value>, keys: &[&str]| -> Option<Value> {
            keys.iter().find_map(|key| row.and_then(|row| row.get(*key)).filter(|said| Coerce::truthy(Some(*said))).cloned())
        };
        for found in raw.get("rows").and_then(Value::as_array).into_iter().flatten() {
            let row = found.get("row");
            let row_key = Coerce::text(first(row, &["key", "model", "Model"]).as_ref()).to_lowercase();
            if !(row_key.contains(&name.to_lowercase()) || model_id.to_lowercase().contains(&row_key)) {
                continue;
            }
            if let Some(elo) = Self::normalize_score(first(row, &["elo", "Elo", "elo_rating", "rating"]).as_ref()) {
                out.insert("arena_elo".to_string(), json!(elo));
                return out;
            }
        }
        out
    }

    fn cache_path(&self, repo_id: &str) -> PathBuf {
        let safe: String = repo_id
            .chars()
            .map(|letter| if letter.is_ascii_alphanumeric() || matches!(letter, '_' | '.' | '-') { letter } else { '_' })
            .collect();
        self.app.paths.bench_cache_dir.join(format!("{safe}.json"))
    }

    fn cache_load(&self, repo_id: &str) -> Option<Value> {
        let raw = std::fs::read(self.cache_path(repo_id)).ok()?;
        let parsed: Value = serde_json::from_slice(&raw).ok()?;
        // absent-ok: `raw.get("cached_at", 0)`: a file that does not say when is as old as can be.
        let cached_at = Coerce::float_or_zero(parsed.get("cached_at"));
        if self.app.now() - cached_at > Self::RESULT_TTL {
            return None;
        }
        parsed.get("data").filter(|data| Coerce::truthy(Some(*data))).cloned()
    }

    fn cache_save(&self, repo_id: &str, data: &Value) {
        let body = PythonJson::spaced_letters(&json!({"cached_at": self.app.now(), "data": data}));
        let written = std::fs::create_dir_all(&self.app.paths.bench_cache_dir)
            .and_then(|()| AtomicFile::write(&self.cache_path(repo_id), body.as_bytes()));
        if let Err(error) = written {
            Log::line(&format!("benchmarks: {repo_id} not cached: {error}"));
        }
    }

    /// `re.sub(r'[-_]+', '-', s)`.
    fn squeezed(text: &str, run: &Regex) -> String {
        run.replace_all(text, "-").into_owned()
    }

    /// Cached scores of a locally-running model, by a fuzzy match of its name.
    pub fn search(&self, query: &str) -> Value {
        let wanted = Coerce::strip(query).to_lowercase();
        if wanted.chars().count() < 3 {
            return json!({"ok": false, "error": "query too short"});
        }
        let Ok(folder) = std::fs::read_dir(&self.app.paths.bench_cache_dir) else {
            return json!({"ok": false});
        };
        let run = &self.memory().dash_run;
        let squeezed = Self::squeezed(&wanted, run);
        let mut files: Vec<PathBuf> = folder
            .flatten()
            .map(|entry| entry.path())
            .filter(|path| path.extension().is_some_and(|extension| extension == "json"))
            .collect();
        files.sort();
        for path in files {
            let stem = path.file_stem().map_or_else(String::new, |stem| stem.to_string_lossy().to_lowercase());
            if !stem.contains(&wanted) && !Self::squeezed(&stem, run).contains(&squeezed) {
                continue;
            }
            let Some(parsed) = std::fs::read(&path).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok()) else {
                continue;
            };
            let data = parsed.get("data");
            if Coerce::truthy(data.and_then(|data| data.get("scores"))) {
                let mut out = Map::new();
                out.insert("ok".to_string(), json!(true));
                for (key, said) in Coerce::fields(data.unwrap_or(&Value::Null)) {
                    out.insert(key, said);
                }
                return Value::Object(out);
            }
        }
        json!({"ok": false})
    }

    fn infer_base_models(&self, repo_id: &str) -> Vec<String> {
        let Some((author, name)) = repo_id.split_once('/') else {
            return vec![repo_id.to_string()];
        };
        let memory = self.memory();
        let cut = memory.repo_tail.replace(name, "").into_owned();
        let clean = memory.gguf_tail.replace(&cut, "").into_owned();
        let card = HubBrowser::of(self.app).request(&format!("models/{}", Percent::encode_path(repo_id)), false);
        if card.is_object() && !Coerce::truthy(card.get("_error")) {
            let data = card.get("cardData").filter(|said| Coerce::truthy(Some(*said)));
            let said = data
                .and_then(|data| data.get("base_model"))
                .filter(|said| Coerce::truthy(Some(*said)))
                .or_else(|| card.get("base_model"));
            let listed: Vec<String> = match said {
                Some(Value::String(one)) if !one.is_empty() => vec![one.clone()],
                Some(Value::Array(many)) => {
                    many.iter().filter_map(Value::as_str).filter(|one| !one.is_empty()).map(str::to_string).collect()
                }
                _ => Vec::new(),
            };
            let other: Vec<String> = listed
                .into_iter()
                .filter(|base| base.split('/').next().is_none_or(|owner| owner.to_lowercase() != author.to_lowercase()))
                .collect();
            if !other.is_empty() {
                return other;
            }
        }
        let mut candidates = Vec::new();
        if let Some((_, hint)) = memory.author_hints.iter().find(|(pattern, _)| pattern.is_match(&clean)) {
            candidates.push(format!("{hint}/{clean}"));
        }
        let same_author = format!("{author}/{clean}");
        if !candidates.contains(&same_author) {
            candidates.push(same_author);
        }
        candidates
    }

    fn result_of(repo_id: &str, base_models: &[String], data_from: &str, scores: &Map<String, Value>) -> Value {
        let inline: Vec<&str> =
            BenchTables::INLINE.iter().copied().filter(|key| scores.contains_key(*key)).take(Self::INLINE_SHOWN).collect();
        let groups: Vec<Value> = BenchTables::GROUPS
            .iter()
            .map(|(id, label, keys)| {
                let held: Vec<&str> = keys.iter().copied().filter(|key| scores.contains_key(*key)).collect();
                json!({"id": id, "label": label, "keys": held})
            })
            .collect();
        let mut meta = Map::new();
        for key in scores.keys() {
            if let Some((_, row)) = BenchTables::META.iter().find(|(name, _)| name == key) {
                meta.insert(key.clone(), json!(row));
            }
        }
        json!({
            "ok": true,
            "repo": repo_id,
            "base_models": base_models,
            "data_from": data_from,
            "scores": scores,
            "inline": inline,
            "groups": groups,
            "meta": meta,
        })
    }

    /// Every score there is for a GGUF repository, judged by its base model.
    pub fn get(&self, repo_id: &str, force: bool) -> Value {
        let repo_id = Coerce::strip(repo_id);
        let repo_id = repo_id.trim_matches('/');
        if !HubBrowser::is_repo_id(repo_id) {
            return json!({"ok": false, "error": "invalid repo id"});
        }
        if !force && let Some(cached) = self.cache_load(repo_id) {
            let mut out = Coerce::fields(&cached);
            out.insert("from_cache".to_string(), json!(true));
            return Value::Object(out);
        }
        let mut scores = Map::new();
        let mut data_from = String::new();
        let base_models = {
            let found = self.infer_base_models(repo_id);
            if found.is_empty() { vec![repo_id.to_string()] } else { found }
        };
        let hub = HubBrowser::of(self.app);
        for base_id in base_models.iter().take(3) {
            let card = hub.request(&format!("models/{}", Percent::encode_path(base_id)), false);
            let mut sources = Vec::new();
            if card.is_object() && !Coerce::truthy(card.get("_error")) {
                sources.push(Self::from_card(&card));
            }
            sources.push(OpenLeaderboard::of(self.app).scores(base_id));
            sources.push(self.arena_elo(base_id));
            for (key, score) in sources.into_iter().flatten() {
                scores.entry(key).or_insert(score);
            }
            if !scores.is_empty() {
                data_from.clone_from(base_id);
                break;
            }
        }
        if scores.is_empty() {
            let index = QualityIndex::of(self.app);
            let tried = base_models.iter().take(2).map(String::as_str).chain(std::iter::once(repo_id));
            for model in tried {
                if let Some(score) = index.score_of(model) {
                    scores.insert("aa_intelligence".to_string(), json!(score));
                    data_from = model.to_string();
                    break;
                }
            }
        }
        let result = Self::result_of(repo_id, &base_models, &data_from, &scores);
        if !scores.is_empty() {
            self.cache_save(repo_id, &result);
        }
        result
    }
}
