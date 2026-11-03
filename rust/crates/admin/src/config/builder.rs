//! A cell's command and the files it reads, as this controller finds them that reads the disk.

use super::args::{ArgPaths, LlamaArgs, ModelHeaders};
use super::extra::ExtraFlags;
use super::fields::ConfigFields;
use super::shell::TokenDiff;
use super::text::ConfigText;
use crate::app::App;
use crate::domain::runner::{Config, MODELS_ROOT, RunnerRegistry};
use crate::models::headers::ModelHeader;
use crate::models::locator::{HomePath, Located, Locations, Place};
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// What this controller reads of a model's GGUF header: nothing, for a file it does not reach.
pub struct AppHeaders<'app> {
    app: &'app App,
}

impl<'app> AppHeaders<'app> {
    /// The headers of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn header_of(&self, path: &Path) -> Value {
        ModelHeader::of_path(self.app, path)
    }
}

impl ModelHeaders for AppHeaders<'_> {
    fn model_header(&self, config: &Config, model_path: &str) -> Value {
        let meta = self.header_of(Path::new(model_path));
        if Coerce::truthy(Some(&meta)) {
            return meta;
        }
        let rel = Coerce::stripped(config.get("MODEL_FILE"));
        if !rel.to_lowercase().ends_with(".gguf") || rel.starts_with(['/', '~', '$']) {
            return json!({});
        }
        self.header_of(&self.app.models_dir().join(rel))
    }
}

/// The files a cell reads, each under the config field that names it.
#[derive(Default)]
pub struct FoundFiles {
    rows: Vec<(String, Located)>,
}

impl FoundFiles {
    fn put(&mut self, key: &str, at: Located) {
        match self.rows.iter_mut().find(|(field, _)| field == key) {
            Some(row) => row.1 = at,
            None => self.rows.push((key.to_string(), at)),
        }
    }

    /// The file of a field.
    pub fn get(&self, key: &str) -> Option<&Located> {
        self.rows.iter().find(|(field, _)| field == key).map(|(_, at)| at)
    }

    /// Every file, in the order they were found.
    pub fn iter(&self) -> impl Iterator<Item = &(String, Located)> {
        self.rows.iter()
    }

    /// Whether any of them is read over the network.
    pub fn over_network(&self) -> bool {
        self.rows.iter().any(|(_, at)| at.in_library())
    }

    /// The path of a field's file; empty for none.
    pub fn path(&self, key: &str) -> String {
        self.get(key).map_or_else(String::new, |at| at.path.clone())
    }

    /// The bytes of each file, by its field: what a library says, else what the disk says.
    pub fn sizes(&self) -> BTreeMap<String, i64> {
        let mut sizes = BTreeMap::new();
        for (key, at) in &self.rows {
            let size = if at.size != 0 || at.place != Place::Local {
                at.size
            } else {
                // absent-ok: a file that cannot be read has no size to say, and is left out.
                std::fs::metadata(&at.path).map_or(0, |found| i64::try_from(found.len()).unwrap_or(i64::MAX))
            };
            if size != 0 {
                sizes.insert(key.clone(), size);
            }
        }
        sizes
    }
}

/// The commands of this controller's cells.
pub struct CellCommand<'app> {
    app: &'app App,
}

impl<'app> CellCommand<'app> {
    const MODEL_FILE_FIELDS: [&'static str; 3] = ["MODEL_FILE", "MMPROJ_FILE", "SPEC_DRAFT_MODEL_FILE"];

    /// The commands of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The folder a config keeps its models in.
    pub fn models_dir_of(&self, config: &Config) -> PathBuf {
        self.app.models_dir_of(config)
    }

    /// The window a model's weights were trained with, from its GGUF header where this controller reads it; `None` otherwise.
    pub fn trained_window(&self, model_path: &str, models_dir: Option<&Path>) -> Option<i64> {
        let text = Coerce::strip(model_path);
        if !text.to_lowercase().ends_with(".gguf") {
            return None;
        }
        let expanded = PathBuf::from(HomePath::of(text, &self.app.env.home().to_string_lossy()));
        let path = if expanded.is_absolute() {
            expanded
        } else {
            match models_dir {
                Some(folder) => folder.join(text),
                None => self.app.models_dir().join(text),
            }
        };
        let meta = ModelHeader::of_path(self.app, &path);
        meta.get("contextLength").filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int).filter(|window| *window > 0)
    }

    fn join_models(root: &str, rel: &str) -> String {
        let rel = Coerce::strip(rel);
        if rel.is_empty() { String::new() } else { format!("{}/{rel}", root.trim_end_matches('/')) }
    }

    fn word_of(config: &Config, key: &str) -> String {
        Coerce::stripped(config.get(key))
    }

    /// Where this host reads a cell's model files, as `Located` answers keyed by their config field.
    pub fn model_paths(&self, config: &Config, locations: Option<&Locations>) -> FoundFiles {
        let merged = ConfigText::merged(config);
        let models_dir = {
            let said = Self::word_of(&merged, "LLAMA_MODELS_DIR");
            if said.is_empty() { self.app.paths.default_models_dir.to_string_lossy().into_owned() } else { said }
        };
        let root = HomePath::of(&models_dir, &self.app.env.home().to_string_lossy());
        let mut out = FoundFiles::default();
        let runner = self.app.runners.for_config(&merged);
        let reads = runner.model_file_values(&merged);
        let located = |rel: &str| {
            let found = locations.and_then(|locations| locations.locate(rel, &root));
            found.unwrap_or_else(|| Located::local(rel, Self::join_models(&root, rel)))
        };
        for key in Self::MODEL_FILE_FIELDS {
            let said =
                reads.iter().find(|(field, _)| field == key).map(|(_, value)| value.clone()).filter(|value| !value.is_empty());
            let rel = said.unwrap_or_else(|| Self::word_of(&merged, key));
            if !rel.is_empty() {
                out.put(key, located(&rel));
            }
        }
        for (key, rel) in &reads {
            if out.get(key).is_none() {
                out.put(key, located(rel));
            }
        }
        if let Some(field) = runner.row().model_field.filter(|field| !Self::MODEL_FILE_FIELDS.contains(field)) {
            let folder = Self::word_of(&merged, field).trim_end_matches('/').to_string();
            let top = format!("{}/", root.trim_end_matches('/'));
            if let Some(rel) = folder.strip_prefix(&top) {
                if Path::new(&folder).is_dir() || locations.is_none() {
                    out.put(field, Located::local(rel, folder.clone()));
                } else if let Some(found) = locations.and_then(|locations| locations.locate(rel, &root)) {
                    out.put(field, found);
                }
            } else if let Some(place) = runner.named_by_place(&merged) {
                // Found, or it is no place of ours: an HF repo id has the same shape, and vLLM fetches that itself.
                let found = located(&place);
                if found.in_library() || Path::new(&found.path).exists() {
                    out.put(field, found);
                }
            }
        }
        out
    }

    /// The model this cell reads from the controller's models, named by its place there and found there: it comes to the machine as any model's files do.
    pub fn placed_model(&self, config: &Config, found: &FoundFiles) -> Option<String> {
        let place = self.app.runners.for_config(config).named_by_place(config)?;
        found.iter().any(|(_, at)| at.rel == place).then_some(place)
    }

    /// `config` as a start runs it: a folder model that lives in a library is read where it lies.
    pub fn run_config(&self, config: &Config, found: &FoundFiles) -> Config {
        let field =
            self.app.runners.for_config(config).row().model_field.filter(|field| !Self::MODEL_FILE_FIELDS.contains(field));
        let at = field.and_then(|field| found.get(field)).filter(|at| at.in_library());
        let mut out = config.clone();
        if let (Some(field), Some(place)) = (field, self.placed_model(config, found)) {
            out.insert(field.to_string(), json!(format!("{MODELS_ROOT}{place}")));
        } else if let (Some(field), Some(at)) = (field, at) {
            out.insert(field.to_string(), json!(at.path));
        }
        out
    }

    /// `[binary, *args]` for a server on this host, with all paths resolved to where they are.
    pub fn local_command(&self, config: &Config, locations: Option<&Locations>) -> Result<Vec<String>, AppError> {
        let merged = ConfigText::merged(config);
        let runner = self.app.runners.for_config(&merged);
        if !runner.row().llama_config {
            let id = RunnerRegistry::runner_id(&merged);
            let id = if id.is_empty() { "unknown".to_string() } else { id };
            return Err(AppError::new(format!("the {id} runner builds its own command, not a llama-server line")));
        }
        let found = self.model_paths(&merged, locations);
        let (model, mmproj, spec) = (found.path("MODEL_FILE"), found.path("MMPROJ_FILE"), found.path("SPEC_DRAFT_MODEL_FILE"));
        let paths = ArgPaths {
            model: &model,
            mmproj: &mmproj,
            spec: &spec,
            local_paths: true,
            over_network: found.over_network(),
            header_path: "",
        };
        let headers = AppHeaders::of(self.app);
        let args = LlamaArgs::build(&merged, &paths, &headers);
        let home = self.app.paths.llama_home.to_string_lossy().into_owned();
        // absent-ok: a llama-config runner has a binary: `llama_config` was checked above.
        let binary = runner.server_binary(&home).unwrap_or_default();
        Ok(std::iter::once(binary).chain(args).collect())
    }

    /// The argument list for a scout's machine: its paths are its own to fill in.
    pub fn remote_args(&self, config: &Config, over_network: bool, header_path: &str) -> Vec<String> {
        let paths = ArgPaths {
            model: "{{MODEL_PATH}}",
            mmproj: "{{MMPROJ_PATH}}",
            spec: "{{SPEC_PATH}}",
            local_paths: false,
            over_network,
            header_path,
        };
        let headers = AppHeaders::of(self.app);
        LlamaArgs::build(config, &paths, &headers)
    }

    /// Each token of the built command with the config field that produced it: the board lights the field when a person points at the flag.
    pub fn token_owners(config: &Config, build: impl Fn(&Config) -> Result<Vec<String>, AppError>) -> Vec<Value> {
        let Ok(base) = build(config) else {
            return Vec::new();
        };
        let mut claims: BTreeMap<usize, (usize, &str)> = BTreeMap::new();
        for field in ConfigFields::ALL {
            if Coerce::stripped(config.get(field)).is_empty() {
                continue;
            }
            let mut probe = config.clone();
            probe.insert(field.to_string(), json!(""));
            let Ok(without) = build(&probe) else {
                continue;
            };
            let lost = TokenDiff::lost(&base, &without);
            for index in &lost {
                if claims.get(index).is_none_or(|held| lost.len() < held.0) {
                    claims.insert(*index, (lost.len(), field));
                }
            }
        }
        let mut owners: Vec<Option<String>> = (0..base.len()).map(|at| claims.get(&at).map(|held| held.1.to_string())).collect();
        let flags = ExtraFlags::flag_to_field();
        let mut at = 0;
        while at < base.len() {
            let token = base.get(at).map_or("", String::as_str);
            let next = base.get(at + 1).map_or("", String::as_str);
            let paired = token.starts_with("--") && at + 1 < base.len() && !next.starts_with('-');
            let held = owners.get(at).cloned().flatten();
            let mut owner = held.or_else(|| if paired { owners.get(at + 1).cloned().flatten() } else { None });
            if owner.is_none() && token.starts_with('-') {
                owner = flags.get(token).map(|field| (*field).to_string());
            }
            if let Some(slot) = owners.get_mut(at) {
                slot.clone_from(&owner);
            }
            if paired {
                if let Some(slot) = owners.get_mut(at + 1) {
                    *slot = owner;
                }
                at += 2;
            } else {
                at += 1;
            }
        }
        owners.into_iter().map(|owner| owner.map_or(Value::Null, Value::String)).collect()
    }

    /// True when a cell runs a command a person wrote, not one built from fields.
    pub fn is_command_cell(&self, config: &Config) -> bool {
        self.app.runners.for_config(config).row().free_form_command
    }
}
