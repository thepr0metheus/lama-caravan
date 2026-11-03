//! The Hugging Face browser. Every answer of the hub is kept five minutes: a page asks for the same list many times over.

use super::hub::{HubAccess, HubHash, HubPages};
use super::locator::Locations;
use super::model_list::ModelList;
use super::walk::{RelPath, Walker};
use crate::app::App;
use crate::common::artifacts::ModelArtifacts;
use crate::common::misc::{Folders, TtlCache};
use plumbing::HttpError;
use regex::{Regex, RegexBuilder};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;
use std::time::Duration;
use wire::Percent;

mod local;
#[cfg(test)]
mod tests;

/// What the browser remembers and the patterns it reads names with.
pub struct HubMemory {
    cache: TtlCache<String, Value>,
    quant: Regex,
    pages: HubPages,
}

impl HubMemory {
    /// The memory. The patterns are this program's own text.
    pub fn new() -> Result<Self, regex::Error> {
        Ok(Self {
            cache: TtlCache::new(300.0),
            quant: RegexBuilder::new(
                r"\b(PQ2_0|PTQ1_0|NVFP4|MXFP4|IQ\d_[A-Z0-9]+|Q\d[_\-][A-Z0-9]+(?:[_\-][A-Z0-9]+)*|BF16|F16|F32)\b",
            )
            .case_insensitive(true)
            .build()?,
            pages: HubPages::new()?,
        })
    }

    /// Forgets what the hub said: a new token sees other things.
    pub fn clear(&self) {
        self.cache.clear();
    }

    /// The quantization a file's name says, its `-00001-of-00003` tail not counted.
    pub fn quant_of(&self, filename: &str) -> String {
        let name = super::locator::SplitParts::stem_of(filename).unwrap_or(filename);
        self.quant.find(name).map_or_else(String::new, |found| found.as_str().to_uppercase())
    }
}

/// The browser.
pub struct HubBrowser<'app> {
    app: &'app App,
}

impl<'app> HubBrowser<'app> {
    const SKIP_REPO_FILES: [&'static str; 5] = [".gitattributes", "readme.md", "license", "license.txt", "notice.txt"];
    const NOT_WEIGHTS: [&'static str; 7] = [".md", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".svg"];
    const ST_NAME_HINTS: [&'static str; 9] = ["NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8", "INT4", "W4A16", "BNB"];
    const DUPLICATE_WEIGHTS: [&'static str; 8] = [".pt", ".pth", ".bin", ".h5", ".msgpack", ".onnx", ".ckpt", ".tflite"];

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn get(&self, url: &str, timeout: Duration) -> Result<(Value, String), HttpError> {
        let fields = HubAccess::fields(&self.app.hf_token());
        // Following: a renamed repository answers at its new name, with a 307.
        let answer = self.app.http.following_with(url, &fields, timeout)?;
        let link = answer.head.headers.text_of("Link");
        let raw = answer.text(64 << 20)?;
        let parsed = serde_json::from_slice(&raw)
            .map_err(|error| HttpError::Io(std::io::Error::new(std::io::ErrorKind::InvalidData, error)))?;
        Ok((parsed, link))
    }

    /// The hub's answer to `path`, or `{"_error": words}`.
    pub fn request(&self, path: &str, all_pages: bool) -> Value {
        const TIMEOUT: Duration = Duration::from_secs(12);
        let url = format!("{}/api/{path}", self.app.hub());
        let authorized = if self.app.hf_token().is_empty() { "" } else { "?auth=1" };
        let key = format!("{url}{authorized}{}", if all_pages { " pages" } else { "" });
        let memory = &self.app.hub_memory;
        if let Some(hit) = memory.cache.get(&key, self.app.now(), None) {
            return hit;
        }
        let answer = if all_pages {
            memory.pages.read(self.app.hub(), &url, |page| self.get(page, TIMEOUT).map_err(|error| error.to_string()))
        } else {
            self.get(&url, TIMEOUT).map(|(data, _)| data).map_err(|error| error.to_string())
        };
        match answer {
            Ok(data) => {
                memory.cache.put(key, data.clone(), self.app.now());
                data
            }
            Err(words) => json!({"_error": words}),
        }
    }

    fn classify_gguf(filename: &str) -> &'static str {
        let name = filename.to_lowercase();
        if ["mmproj", "mm-proj", "projector"].iter().any(|word| name.contains(word)) {
            "mmproj"
        } else if name.contains("mtp") {
            "mtp"
        } else if name.contains("vocab") {
            "vocab"
        } else {
            "model"
        }
    }

    /// A human badge for a safetensors checkpoint.
    fn safetensors_format(repo_id: &str, config: Option<&Value>) -> String {
        let upper = repo_id.to_uppercase();
        if let Some(hint) = Self::ST_NAME_HINTS.iter().find(|hint| upper.contains(**hint)) {
            return (*hint).to_string();
        }
        let field = |path: &[&str]| path.iter().try_fold(config?, |value, key| value.get(*key));
        let method = Coerce::text(field(&["quantization_config", "quant_method"])).to_lowercase();
        if !method.is_empty() {
            return match method.as_str() {
                "modelopt" => "NVFP4".to_string(),
                "fp8" => "FP8".to_string(),
                "awq" => "AWQ".to_string(),
                "gptq" => "GPTQ".to_string(),
                "autoround" => "AUTOROUND".to_string(),
                "bitsandbytes" => "BNB".to_string(),
                other => other.to_uppercase(),
            };
        }
        let said = field(&["torch_dtype"]).filter(|said| Coerce::truthy(Some(*said))).or_else(|| field(&["dtype"]));
        match Coerce::text(said).to_lowercase().as_str() {
            "bfloat16" => "BF16".to_string(),
            "float16" => "FP16".to_string(),
            "float32" => "FP32".to_string(),
            _ => "SAFETENSORS".to_string(),
        }
    }

    /// The repository's config.json as the hub gives it.
    fn repo_config(&self, repo_id: &str) -> Option<Value> {
        let url = format!("{}/{}/resolve/main/config.json", self.app.hub(), Percent::encode_path(repo_id));
        let fields = HubAccess::fields(&self.app.hf_token());
        let answer = self.app.http.following_with(&url, &fields, Duration::from_secs(8)).ok()?;
        serde_json::from_slice(&answer.text(16 << 20).ok()?).ok()
    }

    /// `^[\w.\-]+/[\w.\-]+$`.
    pub fn is_repo_id(repo_id: &str) -> bool {
        let word = |part: &str| {
            !part.is_empty() && part.chars().all(|letter| letter.is_alphanumeric() || matches!(letter, '_' | '.' | '-'))
        };
        repo_id.split_once('/').is_some_and(|(author, name)| word(author) && word(name))
    }

    /// A repository's files: GGUFs, a checkpoint's parts, and the rest.
    pub fn list_files(&self, repo_id: &str) -> Value {
        let repo_id = Coerce::strip(repo_id).trim_matches('/').to_string();
        if !Self::is_repo_id(&repo_id) {
            return json!({"ok": false, "error": "invalid repo id"});
        }
        let raw = self.request(&format!("models/{}/tree/main?recursive=true&expand=true", Percent::encode_path(&repo_id)), true);
        let Some(items) = raw.as_array() else {
            let said = raw
                .get("_error")
                .filter(|said| Coerce::truthy(Some(*said)))
                .or_else(|| raw.get("error").filter(|said| Coerce::truthy(Some(*said))));
            return json!({"ok": false, "error": said.cloned().unwrap_or_else(|| json!("unexpected response"))});
        };
        let (mut last_modified, mut files, mut st_files, mut other_files) = (String::new(), Vec::new(), Vec::new(), Vec::new());
        for item in items.iter().filter(|item| item.get("type").and_then(Value::as_str) == Some("file")) {
            let path = Coerce::str_of(item.get("path"));
            let name = RelPath::name(&path).to_string();
            let date = Coerce::text(item.get("lastCommit").and_then(|commit| commit.get("date")));
            if !date.is_empty() && (last_modified.is_empty() || date > last_modified) {
                last_modified = date.clone();
            }
            let lfs_size = item.get("lfs").and_then(|lfs| lfs.get("size")).filter(|size| Coerce::truthy(Some(*size)));
            let size = lfs_size
                .or_else(|| item.get("size").filter(|size| Coerce::truthy(Some(*size))))
                .cloned()
                .unwrap_or_else(|| json!(0));
            let digest = HubHash::from_tree_item(item).fields();
            let lower = name.to_lowercase();
            if lower.ends_with(".gguf") {
                let kind = Self::classify_gguf(&name);
                let mut row = json!({"path": path, "name": name, "kind": kind, "quant": if kind == "model" { self.app.hub_memory.quant_of(&name) } else { String::new() }, "size": size, "date": date});
                if let Value::Object(fields) = &mut row {
                    fields.extend(digest);
                }
                files.push(row);
                continue;
            }
            let mut row = json!({"path": path, "name": name, "size": size});
            if let Value::Object(fields) = &mut row {
                fields.extend(digest);
            }
            if Self::SKIP_REPO_FILES.contains(&lower.as_str()) || Self::NOT_WEIGHTS.iter().any(|end| lower.ends_with(end)) {
                other_files.push(row);
            } else {
                st_files.push(row);
            }
        }
        self.listing_of(&repo_id, files, st_files, other_files, &last_modified)
    }

    fn listing_of(
        &self,
        repo_id: &str,
        files: Vec<Value>,
        mut st_files: Vec<Value>,
        mut other_files: Vec<Value>,
        last_modified: &str,
    ) -> Value {
        let is_weights = |row: &Value| Coerce::text(row.get("name")).to_lowercase().ends_with(".safetensors");
        if st_files.iter().any(is_weights) {
            let (kept, doubles): (Vec<Value>, Vec<Value>) = st_files.into_iter().partition(|row| {
                let lower = Coerce::text(row.get("name")).to_lowercase();
                !Self::DUPLICATE_WEIGHTS.iter().any(|end| lower.ends_with(end))
            });
            other_files.extend(doubles);
            st_files = kept;
        } else {
            other_files.append(&mut st_files);
        }
        other_files.sort_by_key(|row| Coerce::text(row.get("name")).to_lowercase());
        let mut result = json!({"ok": true, "repo": repo_id, "files": files, "lastModified": last_modified});
        let Value::Object(fields) = &mut result else {
            return result;
        };
        if !other_files.is_empty() {
            fields.insert("otherFiles".to_string(), json!(other_files));
        }
        if st_files.iter().any(is_weights) {
            let config = self.repo_config(repo_id);
            // absent-ok: `int(f.get("size") or 0)`: what the hub did not size adds nothing.
            let total: i64 = st_files.iter().map(|row| Coerce::whole(row.get("size"))).sum();
            fields.insert(
                "safetensors".to_string(),
                json!({"format": Self::safetensors_format(repo_id, config.as_ref()), "files": st_files, "totalSize": total}),
            );
        }
        result
    }

    /// The format badge of a model-tree entry.
    fn tree_item_format(item: &Value) -> String {
        let tags: Vec<String> = item
            .get("tags")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|tag| Coerce::str_of(Some(tag)).to_lowercase())
            .collect();
        let has = |word: &str| tags.iter().any(|tag| tag == word);
        let library = Coerce::text(item.get("library_name")).to_lowercase();
        if has("gguf") || library == "llama.cpp" {
            return "GGUF".to_string();
        }
        if has("mlx") || library == "mlx" {
            return "MLX".to_string();
        }
        if has("onnx") || library == "onnx" {
            return "ONNX".to_string();
        }
        if let Some(word) =
            ["nvfp4", "mxfp4", "awq", "gptq", "autoround", "fp8", "exl2", "exl3", "bnb"].iter().find(|word| has(word))
        {
            return word.to_uppercase();
        }
        let upper = Coerce::text(item.get("id")).to_uppercase();
        if let Some(hint) = Self::ST_NAME_HINTS.iter().find(|hint| upper.contains(**hint)) {
            return (*hint).to_string();
        }
        if upper.ends_with("-GGUF") || upper.contains("-GGUF-") {
            return "GGUF".to_string();
        }
        if has("safetensors") { "SAFETENSORS".to_string() } else { String::new() }
    }

    fn tree_items(raw: &Value, exclude: &str) -> Vec<Value> {
        let exclude = exclude.to_lowercase();
        let rows = raw.as_array().into_iter().flatten();
        let named = rows.filter(|row| {
            let id = Coerce::text(row.get("id"));
            !id.is_empty() && id.to_lowercase() != exclude
        });
        let count =
            |row: &Value, key: &str| row.get(key).filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!(0));
        named.map(|row| json!({"id": Coerce::text(row.get("id")), "downloads": count(row, "downloads"), "likes": count(row, "likes"), "format": Self::tree_item_format(row)})).collect()
    }

    /// The model tree, the part the caravan can act on: this model's quantizations, its base, and the base's other quantizations.
    pub fn model_tree(&self, repo_id: &str) -> Value {
        let repo_id = Coerce::strip(repo_id).trim_matches('/').to_string();
        if !Self::is_repo_id(&repo_id) {
            return json!({"ok": false, "error": "invalid repo id"});
        }
        let filter = |base: &str| {
            format!(
                "models?filter={}&sort=downloads&direction=-1&limit=30",
                Percent::encode_path(&format!("base_model:quantized:{base}"))
            )
        };
        let quants = Self::tree_items(&self.request(&filter(&repo_id), false), &repo_id);
        let info = self.request(&format!("models/{}", Percent::encode_path(&repo_id)), false);
        let mut base = String::new();
        if info.is_object() && !Coerce::truthy(info.get("_error")) {
            let tags = info.get("tags").and_then(Value::as_array).into_iter().flatten();
            let found =
                tags.filter_map(|tag| Coerce::str_of(Some(tag)).strip_prefix("base_model:quantized:").map(str::to_string)).next();
            base = found.map_or_else(String::new, |word| Coerce::strip(&word).to_string());
        }
        let siblings = if !base.is_empty() && base.to_lowercase() != repo_id.to_lowercase() {
            Self::tree_items(&self.request(&filter(&base), false), &repo_id)
        } else {
            Vec::new()
        };
        json!({"ok": true, "repo": repo_id, "quantizations": quants, "base": base, "siblings": siblings})
    }

    /// One repository as the /hf page reads it.
    fn repo_record(row: &Value) -> Value {
        let or = |key: &str, otherwise: Value| row.get(key).cloned().unwrap_or(otherwise);
        let tags: Vec<&Value> =
            row.get("tags").and_then(Value::as_array).into_iter().flatten().filter(|tag| tag.is_string()).take(40).collect();
        json!({"id": or("id", json!("")), "downloads": or("downloads", json!(0)), "likes": or("likes", json!(0)), "createdAt": or("createdAt", json!("")), "pipelineTag": Coerce::text(row.get("pipeline_tag")), "tags": tags})
    }

    /// A search; a query that looks like a repository's id is that repository.
    pub fn search(&self, query: &str, limit: i64) -> Value {
        let query = Coerce::strip(query);
        if query.is_empty() {
            return json!({"ok": false, "error": "missing query"});
        }
        if query.contains('/') {
            let repo_id = query.trim_matches('/');
            let info = self.request(&format!("models/{}", Percent::encode_path(repo_id)), false);
            if info.is_object() && !Coerce::truthy(info.get("_error")) && Coerce::truthy(info.get("id")) {
                return json!({"ok": true, "repos": [Self::repo_record(&info)]});
            }
            return json!({"ok": true, "repos": [{"id": repo_id}]});
        }
        let limit = limit.clamp(5, 100);
        let raw = self.request(
            &format!("models?search={}&filter=gguf&limit={limit}&sort=downloads&direction=-1", Percent::encode_path(query)),
            false,
        );
        let Some(rows) = raw.as_array() else {
            return json!({"ok": false, "error": raw.get("_error").cloned().unwrap_or_else(|| json!("search failed"))});
        };
        json!({"ok": true, "repos": rows.iter().filter(|row| Coerce::truthy(row.get("id"))).map(Self::repo_record).collect::<Vec<_>>()})
    }

    fn model_name(repo_id: &str) -> &str {
        repo_id.rsplit('/').next().unwrap_or(repo_id)
    }
}
