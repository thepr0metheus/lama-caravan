//! The GGUF catalog: what the models folder and the libraries hold, as the cell editor's picker reads it.

use super::headers::ModelHeader;
use super::locator::{LibraryStore, Locations, SplitParts};
use super::walk::{RelPath, Walker};
use super::watch::ModelWatch;
use crate::app::App;
use crate::common::draft::{DraftFile, DraftPairing};
use crate::domain::runner::Config;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

/// A GGUF of the walk.
#[derive(Debug, Clone)]
struct Found {
    path: Option<PathBuf>,
    rel: String,
    kind: &'static str,
    size: i64,
    mtime: i64,
    store: Option<LibraryStore>,
}

/// The catalog.
pub struct ModelListing<'app> {
    app: &'app App,
}

impl<'app> ModelListing<'app> {
    const VISION_WORDS: [&'static str; 6] = ["vision", "vl", "mm", "multimodal", "llava", "minicpmv"];
    const EMBED_WORDS: [&'static str; 3] = ["embed", "embedding", "embeddings"];

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn family_defaults(family: &str) -> Value {
        let keep_cache = json!({"ENABLE_FLASH_ATTN": "1", "ENABLE_JINJA": "1", "CACHE_TYPE_K": "q8_0", "CACHE_TYPE_V": "q8_0"});
        match family {
            "gemma4" => {
                json!({"ENABLE_FLASH_ATTN": "1", "ENABLE_JINJA": "1", "CACHE_TYPE_K": "q8_0", "CACHE_TYPE_V": "q8_0", "SPEC_TYPE": "draft-mtp", "SPEC_DRAFT_N_MAX": "2", "SPEC_DRAFT_N_GPU_LAYERS": "999"})
            }
            "qwen3.6" => {
                json!({"ENABLE_FLASH_ATTN": "1", "ENABLE_JINJA": "1", "CACHE_TYPE_K": "q8_0", "CACHE_TYPE_V": "q8_0", "SPEC_TYPE": "draft-mtp", "SPEC_DRAFT_N_MAX": "2"})
            }
            "qwen3" | "qwen2.5" => keep_cache,
            _ => json!({}),
        }
    }

    /// Recommended launch flags for an embedding model.
    pub fn embedding_family_defaults(haystack: &str, pooling_type: i64, context_length: i64) -> Value {
        let pool = match pooling_type {
            0 => "none",
            1 => "mean",
            2 => "cls",
            3 => "last",
            4 => "rank",
            _ if haystack.contains("bge") => "cls",
            _ if ["e5", "gte", "nomic", "minilm", "mpnet"].iter().any(|word| haystack.contains(word)) => "mean",
            _ => "last",
        };
        let mut out = json!({"ENABLE_EMBEDDINGS": "1", "POOLING": pool, "ENABLE_JINJA": "0", "SPEC_TYPE": "", "CACHE_TYPE_K": "", "CACHE_TYPE_V": ""});
        if let (true, Value::Object(fields)) = (context_length > 0, &mut out) {
            fields.insert("CTX_SIZE".to_string(), json!(context_length.to_string()));
        }
        out
    }

    /// The model family from a path's top folder: `^[a-z][a-z0-9]*(\.[0-9]+)?`, and its number after a dash when the word ends in a letter.
    pub fn detect_family(rel: &str) -> String {
        // absent-ok: a path with no word has no family.
        let top = rel.split('/').find(|part| !part.is_empty()).unwrap_or_default().to_lowercase();
        if !top.chars().next().is_some_and(|first| first.is_ascii_lowercase()) {
            return String::new();
        }
        let word = top.chars().take_while(|letter| letter.is_ascii_lowercase() || letter.is_ascii_digit()).count();
        let mut end = word;
        if let Some(digits) = top.get(word..).and_then(|rest| rest.strip_prefix('.')) {
            let count = digits.chars().take_while(char::is_ascii_digit).count();
            if count > 0 {
                end = word + 1 + count;
            }
        }
        let (family, rest) = top.split_at(end);
        if family.chars().last().is_some_and(|last| last.is_ascii_digit()) {
            return family.to_string();
        }
        let digits: String =
            // absent-ok: no digits after the word: no version.
            rest.strip_prefix('-').map(|tail| tail.chars().take_while(char::is_ascii_digit).collect()).unwrap_or_default();
        format!("{family}{digits}")
    }

    /// A GGUF's role by its path and, once its header was read, by the architecture the header names; none for a file that is no part of a model.
    pub fn gguf_kind(rel: &str, architecture: &str) -> Option<&'static str> {
        let name = RelPath::name(rel).to_lowercase();
        let first = rel.split('/').next().unwrap_or_default();
        if name.contains("vocab") || (!rel.is_empty() && matches!(first, "vocabs" | "templates")) {
            return None;
        }
        if !DraftFile::new(rel).sidecar_type().is_empty() {
            return Some("draft");
        }
        let arch = architecture.to_lowercase();
        if arch == "clip" || name.contains("mmproj") || name.contains("mm-proj") {
            return Some("mmproj");
        }
        if name.contains("projector") {
            return if arch.is_empty() { Some("mmproj") } else { None };
        }
        Some("model")
    }

    /// True for a file its header shows is no model of its own: a piece with no window of its own that no runner's engine claims.
    fn refuses_alone(&self, rel: &str, header: &Value) -> bool {
        if !header.get("headerKeys").is_some_and(|keys| keys.is_i64() || keys.is_u64()) {
            return false;
        }
        if Coerce::truthy(header.get("contextLength")) || Coerce::truthy(header.get("sttVariant")) {
            return false;
        }
        if SplitParts::of(rel).is_some_and(|part| part.index > 1) {
            return false;
        }
        let arch = Coerce::text(header.get("architecture"));
        !self.app.runners.all().any(|runner| runner.row().gguf_archs.contains(&arch.as_str()))
    }

    /// A GGUF header's runtime facts: read here for a file on this disk, remembered for one in a library.
    fn header(&self, path: Option<&Path>, rel: &str, size: i64, store: Option<&LibraryStore>) -> Value {
        match (store, path) {
            (None, Some(path)) => ModelHeader::runtime_meta(&ModelHeader::read_cached(self.app, path)),
            (Some(store), _) => self.app.library_meta.lookup(&store.id, rel, size).map_or_else(|| json!({}), Value::Object),
            (None, None) => json!({}),
        }
    }

    fn kind_of(&self, path: Option<&Path>, rel: &str, size: i64, store: Option<&LibraryStore>) -> Option<&'static str> {
        Self::gguf_kind(rel, "")?;
        let header = self.header(path, rel, size, store);
        let kind = Self::gguf_kind(rel, &Coerce::text(header.get("architecture")))?;
        (!(kind == "model" && self.refuses_alone(rel, &header))).then_some(kind)
    }

    /// The bytes of the expert tensors in one file of a model; none when that is not known.
    fn expert_bytes(&self, path: Option<&Path>, rel: &str, size: i64, store: Option<&LibraryStore>) -> Option<i64> {
        match (store, path) {
            (None, Some(path)) => {
                let raw = ModelHeader::read_cached(self.app, path);
                // absent-ok: a header read that names no expert tensors has none.
                (!raw.is_empty()).then(|| Coerce::i64_or_zero(raw.get(super::gguf_header::GgufHeader::EXPERT_BYTES)))
            }
            (Some(store), _) => {
                let meta = self.app.library_meta.lookup(&store.id, rel, size)?;
                meta.get("expertBytes").map(|said| Coerce::whole(Some(said)))
            }
            (None, None) => None,
        }
    }

    fn found_here(&self, models_dir: &Path) -> Vec<Found> {
        let mut out = Vec::new();
        for path in Walker::ending_in(models_dir, ".gguf") {
            if !path.is_file() {
                continue;
            }
            let Some(rel) = Walker::relative(&path, models_dir) else {
                continue;
            };
            let (size, mtime) = std::fs::metadata(&path).map_or((0, 0), |meta| (meta.size() as i64, meta.mtime()));
            if let Some(kind) = self.kind_of(Some(&path), &rel, size, None) {
                out.push(Found { path: Some(path), rel, kind, size, mtime, store: None });
            }
        }
        out
    }

    fn found_in_libraries(&self, locations: &Locations, local: &BTreeSet<String>) -> Vec<Found> {
        let mut out = Vec::new();
        for (rel, store, file) in locations.library_entries() {
            if local.contains(rel) {
                continue;
            }
            // absent-ok: `f.get("size") or 0`: what the look did not get is no size.
            let size = Coerce::whole(file.get("size"));
            if let Some(kind) = self.kind_of(None, rel, size, Some(store)) {
                // absent-ok: as above.
                let mtime = Coerce::whole(file.get("mtime"));
                out.push(Found { path: None, rel: rel.clone(), kind, size, mtime, store: Some(store.clone()) });
            }
        }
        out
    }

    fn where_of(store: Option<&LibraryStore>) -> Map<String, Value> {
        let mut out = Map::new();
        if let Some(store) = store {
            out.insert("store".to_string(), json!({"id": store.id, "name": store.name}));
            out.insert("libraryOnly".to_string(), json!(true));
        }
        out
    }

    fn size_gb(size: i64) -> f64 {
        Coerce::rounded(size as f64 / 1_073_741_824.0, 2)
    }

    /// The rows: models first, with what goes with each, then the projectors and the drafts.
    pub fn rows(&self, config: &Config, locations: &Locations) -> Vec<Value> {
        let models_dir = self.app.models_dir_of(config);
        if !models_dir.exists() && locations.library_entries().next().is_none() {
            return Vec::new();
        }
        let fresh = ModelWatch::of(self.app).freshness_by_path();
        let mut ggufs = self.found_here(&models_dir);
        let local: BTreeSet<String> = ggufs.iter().map(|entry| entry.rel.clone()).collect();
        ggufs.extend(self.found_in_libraries(locations, &local));
        ggufs.sort_by(|left, right| left.rel.split('/').cmp(right.rel.split('/')));
        let sisters = Sisters::of(self, &ggufs);
        let mut rows: Vec<Value> =
            ggufs.iter().filter(|entry| entry.kind == "model").map(|entry| self.model_row(entry, &sisters, &fresh)).collect();
        for entry in ggufs.iter().filter(|entry| entry.kind != "model") {
            // absent-ok: a file with no time reads as old.
            let mut row = json!({"path": entry.rel, "name": RelPath::name(&entry.rel), "kind": entry.kind, "size": entry.size, "sizeGb": Self::size_gb(entry.size), "mtime": entry.mtime, "fresh": fresh.get(&entry.rel).cloned().unwrap_or_default()});
            if let Value::Object(fields) = &mut row {
                if entry.kind == "draft" {
                    fields.insert(
                        "ggufMeta".to_string(),
                        self.header(entry.path.as_deref(), &entry.rel, entry.size, entry.store.as_ref()),
                    );
                }
                fields.extend(Self::where_of(entry.store.as_ref()));
            }
            rows.push(row);
        }
        self.app.header_memory.flush();
        rows
    }

    /// `(what a model looks like it does, the settings a new cell starts from)`, by its name and its header; the family follows.
    fn what_it_does(rel: &str, meta: &Value, has_projector: bool, family: &mut String) -> (&'static str, Value) {
        let lowered = rel.to_lowercase();
        let words: String = lowered
            .chars()
            .map(|letter| if letter.is_ascii_lowercase() || letter.is_ascii_digit() { letter } else { ' ' })
            .collect();
        let tokens: Vec<&str> = words.split_whitespace().collect();
        let hints = |list: &[&str]| tokens.iter().any(|token| list.contains(token));
        // absent-ok: `.get("poolingType", -1)`: a header not read has no pooling.
        let pooling = meta.get("poolingType").and_then(Value::as_i64).unwrap_or(-1);
        if Coerce::truthy(meta.get("sttVariant")) {
            *family = "asr".to_string();
            return ("asr", json!({}));
        }
        if hints(&Self::EMBED_WORDS) || pooling >= 0 {
            *family = "embedding".to_string();
            return (
                "embedding_likely",
                Self::embedding_family_defaults(&tokens.join(" "), pooling, Coerce::i64_or_zero(meta.get("contextLength"))),
            );
        }
        (if has_projector || hints(&Self::VISION_WORDS) { "vision_likely" } else { "text" }, Self::family_defaults(family))
    }

    fn model_row(&self, entry: &Found, sisters: &Sisters, fresh: &BTreeMap<String, String>) -> Value {
        let split = SplitParts::of(&entry.rel);
        let whole = split.as_ref().filter(|part| part.index == 1).and_then(|part| sisters.split_sizes.get(&part.group));
        let total = whole.map_or(entry.size, |parts| parts.values().sum());
        let top = entry.rel.split('/').next().unwrap_or_default();
        let mut family = Self::detect_family(&entry.rel);
        let upper = top.to_uppercase();
        let has_mtp_builtin = upper.ends_with("-MTP")
            || upper.ends_with("_MTP")
            || upper.ends_with("-MTP-GGUF")
            || upper.ends_with("_MTP-GGUF")
            || ["-MTP-", "_MTP-", "-MTP_", "_MTP_", "-MTP.", "_MTP."].iter().any(|word| upper.contains(word));
        let mut meta = self.header(entry.path.as_deref(), &entry.rel, entry.size, entry.store.as_ref());
        if let (Some(_), Some(part)) = (whole, split.as_ref()) {
            let experts = sisters.split_experts.get(&part.group);
            let known = experts.filter(|experts| experts.len() as i64 == part.total && experts.values().all(Option::is_some));
            // absent-ok: known says every part is there and read: 0 is only for the case nothing is known, which the board reads as "not said".
            let sum: i64 = known.map_or(0, |experts| experts.values().map(|part| part.unwrap_or(0)).sum());
            if let Value::Object(fields) = &mut meta {
                fields.insert("expertBytes".to_string(), json!(sum));
            }
        }
        let compatible: Vec<String> = sisters.merged(&entry.rel, "mmproj").into_iter().take(5).collect();
        let by_folder = sisters.merged(&entry.rel, "draft");
        let by_arch = sisters.pairing.of(&Coerce::text(meta.get("architecture")));
        let by_arch = by_arch
            .iter()
            .filter_map(Value::as_str)
            .filter(|draft| !by_folder.iter().any(|said| said == draft))
            .map(str::to_string);
        let drafts: Vec<String> = by_folder.iter().cloned().chain(by_arch).take(5).collect();
        let (capability, defaults) = Self::what_it_does(&entry.rel, &meta, !compatible.is_empty(), &mut family);
        let mut row = Map::new();
        row.insert("path".to_string(), json!(entry.rel));
        row.insert("name".to_string(), json!(RelPath::name(&entry.rel)));
        row.insert("kind".to_string(), json!(entry.kind));
        row.insert("size".to_string(), json!(total));
        row.insert("sizeGb".to_string(), json!(Self::size_gb(total)));
        if let (Some(whole), Some(part)) = (whole, split.as_ref()) {
            row.insert("parts".to_string(), json!(part.total));
            row.insert("partsFound".to_string(), json!(whole.len()));
        }
        row.insert("mtime".to_string(), json!(entry.mtime));
        // absent-ok: a file with no time reads as old.
        row.insert("fresh".to_string(), json!(fresh.get(&entry.rel).cloned().unwrap_or_default()));
        row.insert("capability".to_string(), json!(capability));
        row.insert("compatibleMmprojs".to_string(), json!(compatible));
        // absent-ok: no projector fits: the row shows none.
        row.insert("suggestedMmproj".to_string(), json!(compatible.first().cloned().unwrap_or_default()));
        row.insert("compatibleDrafts".to_string(), json!(drafts));
        // absent-ok: no draft fits: the row shows none.
        row.insert("suggestedDraft".to_string(), json!(drafts.first().cloned().unwrap_or_default()));
        row.insert("hasMtpBuiltin".to_string(), json!(has_mtp_builtin));
        row.insert("detectedFamily".to_string(), json!(family));
        row.insert("familyDefaults".to_string(), defaults);
        row.insert("ggufMeta".to_string(), meta);
        row.extend(Self::where_of(entry.store.as_ref()));
        Value::Object(row)
    }
}

/// What goes with what in one walk: the sizes of the parts of each split file, the projectors and drafts of each folder, and the drafts by architecture.
struct Sisters {
    split_sizes: BTreeMap<(String, String, String), BTreeMap<i64, i64>>,
    split_experts: BTreeMap<(String, String, String), BTreeMap<i64, Option<i64>>>,
    companions: BTreeMap<String, (Vec<String>, Vec<String>)>,
    pairing: DraftPairing,
}

impl Sisters {
    fn of(listing: &ModelListing<'_>, ggufs: &[Found]) -> Self {
        let mut this = Self {
            split_sizes: BTreeMap::new(),
            split_experts: BTreeMap::new(),
            companions: BTreeMap::new(),
            pairing: DraftPairing::default(),
        };
        for entry in ggufs {
            if entry.kind == "model" {
                if let Some(part) = SplitParts::of(&entry.rel) {
                    this.split_sizes.entry(part.group.clone()).or_default().insert(part.index, entry.size);
                    this.split_experts.entry(part.group).or_default().insert(
                        part.index,
                        listing.expert_bytes(entry.path.as_deref(), &entry.rel, entry.size, entry.store.as_ref()),
                    );
                }
                continue;
            }
            let row = this.companions.entry(RelPath::parent(&entry.rel)).or_default();
            if entry.kind == "mmproj" {
                row.0.push(entry.rel.clone());
            } else {
                row.1.push(entry.rel.clone());
                let header = listing.header(entry.path.as_deref(), &entry.rel, entry.size, entry.store.as_ref());
                this.pairing.add(json!(entry.rel), &Coerce::text(header.get("architecture")));
            }
        }
        this
    }

    /// The companions of a model: its own folder's first, then `default/`, then its other quant folders', each once.
    fn merged(&self, rel: &str, kind: &str) -> Vec<String> {
        let parent = RelPath::parent(rel);
        let quant_root = RelPath::parent(&parent);
        let default_sibling = RelPath::sibling(&parent, "default");
        let others = self
            .companions
            .keys()
            .filter(|folder| **folder != parent && **folder != default_sibling && RelPath::parent(folder) == quant_root);
        let groups = [&parent, &default_sibling].into_iter().chain(others);
        let mut out: Vec<String> = Vec::new();
        for group in groups {
            if let Some((mmprojs, drafts)) = self.companions.get(group) {
                for file in if kind == "mmproj" { mmprojs } else { drafts } {
                    if !out.contains(file) {
                        out.push(file.clone());
                    }
                }
            }
        }
        out
    }
}

#[cfg(test)]
mod tests;
