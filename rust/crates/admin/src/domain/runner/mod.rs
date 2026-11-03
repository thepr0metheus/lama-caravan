//! A runner as an object, not as a string everything else compares against. A "runner" is the launch flavour of a cell. One object per runner, the questions are methods on it, and a runner that does not answer a question takes the default's answer. `RunnerRegistry` is the only list, and everything else reads it. What the browser receives is `registry_json`, the dicts in the same order.

mod engines;
mod gr00t;
mod launcher;
mod llama;
mod row_json;
mod specs;
mod speech;
mod strata;
mod vllm;

pub use llama::{LlamaServerRunner, PrismRunner};
pub use specs::{LauncherSpec, LiveSpec, PageSpec, TalkSpec};
pub use speech::TranslateRunner;
pub use strata::StrataRunner;
pub use vllm::VllmRunner;

use rules::{AppError, Coerce, ConfigField, EnvField};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

/// The config of a cell.
pub type Config = Map<String, Value>;

/// What a runner is: the registry's row.
#[derive(Debug, Clone, Copy)]
pub struct RunnerRow {
    /// What the config's RUNNER field holds.
    pub id: &'static str,
    /// Its icon.
    pub icon: &'static str,
    /// The word of its name.
    pub label_key: &'static str,
    /// The word of what it is good for.
    pub benefits_key: &'static str,
    /// The word of what it costs.
    pub minus_key: &'static str,
    /// The word of why the tab is greyed when the picked model is another kind.
    pub needs_key: &'static str,
    /// The KIND of artifact this runner can launch.
    pub artifacts: &'static [&'static str],
    /// The older, extension-only version of the same idea, kept because a browser holding cached JS still reads it.
    pub formats: &'static [&'static str],
    /// The health path as the registry advertises it.
    pub health: &'static str,
    /// Its API.
    pub api: &'static str,
    /// When a cell of this runner cannot run on the CPU.
    pub gpu_only: bool,
    /// When a cell runs on ONE card, the one its ENV pins.
    pub one_card: bool,
    /// When the cell picks its device itself while nothing pins one.
    pub auto_device: bool,
    /// Per-quant hardware gates.
    pub format_requirements: &'static [(&'static str, f64)],
    /// Where in the config this runner keeps its model.
    pub model_field: Option<&'static str>,
    /// How the shared model picker treats this runner.
    pub shared_picker: &'static str,
    /// GGUF architectures only this runner's engine reads.
    pub gguf_archs: &'static [&'static str],
    /// `config.json` `model_type` values only this runner reads.
    pub st_archs: &'static [&'static str],
    /// The config fields that name model files a command cell of this runner reads.
    pub model_files: &'static [&'static str],
    /// The oldest caravan-scout that can start this runner's cells.
    pub min_scout: Option<(u32, u32, u32)>,
    /// When a start writes what it makes from the model on the machine's disk (Strata's pack, about 2.3 GB, at every start): the owner, 2026-11-03, wants it in a folder he chose, and no start
    /// until he chose one.
    pub work_folder: bool,
    /// The field that holds the cell's context window.
    pub context_field: &'static str,
    /// When this cell's work is measured in tokens, so that its window means something to it.
    pub token_context: bool,
    /// When the cell launches through the generic command machinery.
    pub command_path: bool,
    /// Uses the GGUF parameters, placement and memory estimator of `llama.cpp`.
    pub llama_config: bool,
    /// When the command IS the config: typed by a person rather than built from fields.
    pub free_form_command: bool,
    /// What `health_path` answers when the config names no path.
    pub default_health_path: &'static str,
    /// When `start.sh`'s config block must carry a concrete `LLAMA_MODELS_DIR`.
    pub needs_models_dir: bool,
    /// Whether the cell editor draws a tab for this runner.
    pub editor_tab: bool,
    /// A cell whose model runs inside an engine next to it.
    pub engine_cell: bool,
    /// How the voice window talks to it.
    pub talk: TalkSpec,
    /// How the board talks live with it.
    pub live: LiveSpec,
    /// The page it serves itself.
    pub page: PageSpec,
    /// What a launcher cell says.
    pub launcher: Option<LauncherSpec>,
}

impl RunnerRow {
    /// What a runner that says nothing says.
    pub const BASE: Self = Self {
        id: "",
        icon: "",
        label_key: "",
        benefits_key: "",
        minus_key: "",
        needs_key: "",
        artifacts: &["*"],
        formats: &["*"],
        health: "",
        api: "raw",
        gpu_only: false,
        one_card: false,
        auto_device: false,
        format_requirements: &[],
        model_field: None,
        shared_picker: "ignored",
        gguf_archs: &[],
        st_archs: &[],
        model_files: &[],
        min_scout: None,
        work_folder: false,
        context_field: "CTX_SIZE",
        token_context: false,
        command_path: true,
        llama_config: false,
        free_form_command: false,
        default_health_path: "",
        needs_models_dir: false,
        editor_tab: true,
        engine_cell: false,
        talk: TalkSpec::NONE,
        live: LiveSpec { path: "", protocol: "" },
        page: PageSpec { field: "" },
        launcher: None,
    };
}

/// Where a cell's line finds the models, as a shell word: the scout says where they came to on its machine.
pub const MODELS_ROOT: &str = "\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\"/";

/// The questions a runner answers. A runner that does not answer one takes this default.
pub trait Runner: Send + Sync {
    /// Its row.
    fn row(&self) -> &RunnerRow;

    /// The thing a cell actually serves, as this runner names it. Every runner keeps its model somewhere different, and the board used to read `MODEL_FILE` for all of them: the model picker's leftover value, drawn as fact.
    fn model_ref(&self, config: &Config) -> String {
        self.row().model_field.map_or_else(String::new, |field| ConfigField::word(config, field))
    }

    /// The model of a cell named by its place among the controller's models, for a runner whose own field can say other things too: vLLM's. `None` for what cannot be such a place.
    fn named_by_place(&self, _config: &Config) -> Option<String> {
        None
    }

    /// What a cell RUNS, in one short phrase, for lists with no room for a card. Empty means "the caller already shows the model file".
    fn artifact_label(&self, _config: &Config, _quant_words: &[&str]) -> String {
        String::new()
    }

    /// `{field: path}` of the model files this runner's cell reads, in that order, the empty fields left out.
    fn model_file_values(&self, config: &Config) -> Vec<(String, String)> {
        self.row()
            .model_files
            .iter()
            .map(|field| ((*field).to_string(), ConfigField::word(config, field)))
            .filter(|(_, path)| !path.is_empty())
            .collect()
    }

    /// The shell command this cell runs, without `exec`. The default is the stored COMMAND: right for the two runners that have no command of their own to build.
    fn command(&self, config: &Config) -> Result<String, AppError> {
        Ok(ConfigField::word(config, "COMMAND"))
    }

    /// Where the server of a `llama.cpp`-like runner is under `llama_home`; `None` for a runner that builds no such line.
    fn server_binary(&self, _llama_home: &str) -> Option<String> {
        None
    }

    /// Lines `start.sh` runs before the exec.
    fn bootstrap_lines(&self) -> Vec<String> {
        Vec::new()
    }

    /// Validates and completes `merged` in place, and answers with its command.
    fn prepare(&self, merged: &mut Config, defaults: &RunnerDefaults) -> Result<String, AppError> {
        if self.row().needs_models_dir {
            defaults.fill_models_dir(merged);
        }
        self.command(merged)
    }

    /// Refuses a start that cannot possibly work, naming what is missing. `model` is what the caller resolved for this cell.
    fn preflight_start(&self, _config: &Config, _model: &str) -> Result<(), AppError> {
        Ok(())
    }

    /// What a start reserves on a card the moment it runs: `{device, reserveMiB, who, why, lower}`, so that a start the card cannot hold is refused before it is attempted.
    fn vram_reservation(&self, _config: &Config, _gpus: &[Value]) -> Option<Value> {
        None
    }

    /// What a start keeps resident in the machine's memory: `{reserveMiB, who, why}`. `sizes`: the bytes of each model file, by its config field.
    fn ram_reservation(&self, _config: &Config, _sizes: &BTreeMap<String, i64>) -> Option<Value> {
        None
    }

    /// Whether this runner promises its weights in the machine's memory at all.
    fn keeps_ram(&self) -> bool {
        false
    }

    /// How a start takes VRAM when its cost is not its model's files, for the cell form's estimate bar.
    fn vram_plan(&self) -> Value {
        Value::Null
    }

    /// The environment the engine itself must start with. Every engine gets the card numbering of the board; a runner adds its own.
    ///
    /// The cards are numbered the way `nvidia-smi` and the board number them, by PCI bus: CUDA's own default numbers them fastest first (2026-10-17).
    fn launch_env(&self, _config: &Config) -> Vec<(String, String)> {
        vec![("CUDA_DEVICE_ORDER".to_string(), "PCI_BUS_ID".to_string())]
    }

    /// The card a one-card start lands on: the last `CUDA_VISIBLE_DEVICES` in the cell's ENV, else card 0; `None` when the pin names no single card or the machine has no such card.
    fn pinned_card(&self, config: &Config, gpus: &[Value]) -> Option<i64> {
        PinnedCard::of(config, gpus)
    }

    /// The health path of this config.
    fn health_path(&self, config: &Config) -> String {
        let explicit = ConfigField::word(config, "HEALTH_PATH");
        if explicit.is_empty() { self.row().default_health_path.to_string() } else { explicit }
    }

    /// The row as the browser reads it.
    fn as_json(&self) -> Value {
        row_json::RowJson::of(self.row(), self.vram_plan(), self.keeps_ram())
    }
}

/// The card ENV pins.
pub struct PinnedCard;

impl PinnedCard {
    /// The last `CUDA_VISIBLE_DEVICES` of the ENV field as a number, else 0; `None` when it names no single card, or the machine has no such card.
    pub fn of(config: &Config, gpus: &[Value]) -> Option<i64> {
        let word = Self::word(config);
        // As it is written: a card is named by its index, and "00" names no card, here and in the browser alike.
        let device = Self::device(config).filter(|_| gpus.iter().any(|gpu| Coerce::str_of(gpu.get("index")) == word))?;
        Some(device)
    }

    /// The same, whatever the machine has.
    pub fn device(config: &Config) -> Option<i64> {
        let word = Self::word(config);
        word.chars().all(|letter| letter.is_ascii_digit()).then(|| word.parse().ok()).flatten()
    }

    fn word(config: &Config) -> String {
        let pinned: Vec<String> = EnvField::pairs(config.get("ENV"))
            .into_iter()
            .filter(|(key, _)| key == "CUDA_VISIBLE_DEVICES")
            .map(|(_, value)| value)
            .collect();
        pinned.last().map_or_else(|| "0".to_string(), |value| Coerce::strip(value).trim_matches('"').to_string())
    }
}

/// Where the shared models lie, for a config that must say it.
#[derive(Debug, Clone)]
pub struct RunnerDefaults {
    /// `DEFAULT_MODELS_DIR`.
    pub models_dir: String,
    /// `~`.
    pub home: String,
}

impl RunnerDefaults {
    fn fill_models_dir(&self, merged: &mut Config) {
        if !Coerce::truthy(merged.get("LLAMA_MODELS_DIR")) {
            merged.insert("LLAMA_MODELS_DIR".to_string(), json!(self.models_dir));
        }
    }
}

/// A RUNNER value nothing in the registry answers to: a config saved by a NEWER caravan, or corrupted, is read as "a cell whose runner I do not know" rather than crashing a page that was only trying to draw a card. Deliberately absent from the registry, so that nothing offers it in the editor.
struct UnknownRunner;

impl UnknownRunner {
    const ROW: RunnerRow = RunnerRow { model_field: Some("MODEL_FILE"), command_path: false, ..RunnerRow::BASE };
}

impl Runner for UnknownRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }
}

/// The one list of runners. Order is the order the editor draws the tabs in.
pub struct RunnerRegistry {
    runners: Vec<Box<dyn Runner>>,
    unknown: UnknownRunner,
}

impl RunnerRegistry {
    /// The list. The patterns in it are this program's own text.
    pub fn new(defaults: &RunnerDefaults) -> Result<Self, regex::Error> {
        let mut runners: Vec<Box<dyn Runner>> = vec![
            Box::new(llama::LlamaServerRunner),
            Box::new(llama::PrismRunner { home: defaults.home.clone() }),
            Box::new(vllm::VllmRunner),
            Box::new(strata::StrataRunner::new()?),
            Box::new(gr00t::Gr00tRunner),
        ];
        runners.extend(speech::SpeechRunners::all());
        runners.extend(launcher::LauncherRunners::all());
        runners.extend(engines::OtherRunners::all());
        Ok(Self { runners, unknown: UnknownRunner })
    }

    /// The effective runner id of a cell config. Explicit RUNNER wins; legacy `CELL_KIND="command"` maps to custom; the default is `llama-server`.
    pub fn runner_id(config: &Config) -> String {
        let id = ConfigField::word(config, "RUNNER").to_lowercase();
        if !id.is_empty() {
            return id;
        }
        if ConfigField::word(config, "CELL_KIND").to_lowercase() == "command" {
            "custom".to_string()
        } else {
            "llama-server".to_string()
        }
    }

    /// The runner with this id, or the unknown-runner stand-in.
    pub fn get(&self, id: &str) -> &dyn Runner {
        let id = Coerce::strip(id).to_lowercase();
        self.runners.iter().find(|runner| runner.row().id == id).map_or(&self.unknown as &dyn Runner, Box::as_ref)
    }

    /// The runner a config runs on. Never none.
    pub fn for_config(&self, config: &Config) -> &dyn Runner {
        self.get(&Self::runner_id(config))
    }

    /// The registry as the frontend has always received it.
    pub fn registry_json(&self) -> Value {
        Value::Array(self.runners.iter().map(|runner| runner.as_json()).collect())
    }

    /// Every runner, in the editor's order.
    pub fn all(&self) -> impl Iterator<Item = &dyn Runner> {
        self.runners.iter().map(Box::as_ref)
    }
}
