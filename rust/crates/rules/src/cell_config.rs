//! What a cell's config says, read one way for the whole caravan: "yes", its environment, its cards, its V cache and the window it asks for.

use crate::app_error::AppError;
use crate::coerce::Coerce;
use serde_json::{Map, Value};

/// What counts as "yes": one answer for the whole caravan. The flag arrives from the query string, a cell config and a request body, and the vocabularies drifted: `?force=true` read as "no", with a 200 and a cached answer.
pub struct Flag;

impl Flag {
    /// `1`, `true`, `yes`, `on`: any case, with stray whitespace trimmed. Everything else, an empty string and a missing value too, is no. The list is deliberately closed: "anything non-empty" would turn `?force=0` into consent.
    pub fn yes(value: Option<&Value>) -> bool {
        let Some(value) = value else {
            return false;
        };
        let word = match value {
            Value::String(text) => text.clone(),
            Value::Bool(true) => "true".to_string(),
            Value::Bool(false) | Value::Null => return false,
            other => other.to_string(),
        };
        matches!(Coerce::strip(&word).to_lowercase().as_str(), "1" | "true" | "yes" | "on")
    }
}

/// A cell's config field, as `str(config.get(key) or "").strip()` reads it.
pub struct ConfigField;

impl ConfigField {
    /// The field's words, "" for none.
    pub fn word(config: &Map<String, Value>, key: &str) -> String {
        if Coerce::truthy(config.get(key)) { Coerce::stripped(config.get(key)) } else { String::new() }
    }
}

/// A cell's ENV field: newline- or comma-separated; a malformed name is skipped, and so is a `#` comment, since `#` cannot begin a name. One parser for the exports both launchers write and for whatever reads ENV.
pub struct EnvField;

impl EnvField {
    /// (KEY, VALUE) pairs.
    pub fn pairs(raw: Option<&Value>) -> Vec<(String, String)> {
        let text = if Coerce::truthy(raw) { Coerce::text(raw) } else { String::new() };
        text.split(['\n', ','])
            .filter_map(|part| {
                let (key, value) = Coerce::strip(part).split_once('=')?;
                let key = Coerce::strip(key);
                let is_name = key.chars().next().is_some_and(|first| first.is_ascii_alphabetic() || first == '_')
                    && key.chars().all(|letter| letter.is_ascii_alphanumeric() || letter == '_');
                is_name.then(|| (key.to_string(), Coerce::strip(value).to_string()))
            })
            .collect()
    }
}

/// The cards of one cell's config as its process is to see them. `llama-server` touches EVERY card its process can see when it starts, whatever `--device` names: on a full card it dies at once (2026-10-19). So a cell that picks cards sees only those; the process numbers them from 0 again, so the flags that name a card are written for the cards the process sees and not for the board. The field stays what the operator picked; only the start line is written this way.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CudaCards {
    /// `None`: the process keeps every card it sees: the config picks none, or something that is no CUDA card, or a list `llama.cpp` would not read. Empty: it sees no card at all, a CPU cell. Else the board numbers of the cards it sees, in the order the field names them.
    boards: Option<Vec<u32>>,
}

impl CudaCards {
    /// How a card is named in DEVICE: `CUDA(0|[1-9][0-9]*)`, ignoring case: no card has a number with a leading zero.
    fn named(part: &str) -> Option<u32> {
        let number = part.get(..4).filter(|head| head.eq_ignore_ascii_case("CUDA")).and_then(|_| part.get(4..))?;
        let digits = !number.is_empty()
            && number.chars().all(|letter| letter.is_ascii_digit())
            && (number == "0" || !number.starts_with('0'));
        digits.then(|| number.parse().ok()).flatten()
    }

    /// The cards of this config.
    pub fn of(config: &Map<String, Value>) -> Self {
        let layers = config.get("N_GPU_LAYERS").map_or_else(String::new, |value| Coerce::stripped(Some(value)));
        // `str(0)` is "0" in Python, and `Coerce::stripped` reads a falsy 0 as nothing.
        if layers == "0" || config.get("N_GPU_LAYERS").and_then(Value::as_i64) == Some(0) {
            return Self { boards: Some(Vec::new()) };
        }
        let field = ConfigField::word(config, "DEVICE");
        let named: Option<Vec<u32>> = field.split(',').map(Self::named).collect();
        let boards = named.filter(|boards| {
            let mut sorted = boards.clone();
            sorted.sort_unstable();
            sorted.dedup();
            sorted.len() == boards.len()
        });
        Self { boards }
    }

    /// The value of `CUDA_VISIBLE_DEVICES` for the process; `None`: the variable is left alone.
    pub fn visible(&self) -> Option<String> {
        self.boards.as_ref().map(|boards| boards.iter().map(u32::to_string).collect::<Vec<_>>().join(","))
    }

    fn renumbers(&self) -> Option<&[u32]> {
        self.boards.as_deref().filter(|boards| !boards.is_empty())
    }

    /// `--device` for the process: the picked cards by the numbers it gives them; else the field as it stands.
    pub fn device(&self, field: &str) -> String {
        self.renumbers().map_or_else(
            || field.to_string(),
            |boards| (0..boards.len()).map(|seen| format!("CUDA{seen}")).collect::<Vec<_>>().join(","),
        )
    }

    /// `--main-gpu` for the process: the number it gives the card the field names. A number that names none of the picked cards stays as it stands, for `llama.cpp` to refuse by its own words.
    pub fn main_gpu(&self, field: &str) -> String {
        let text = Coerce::strip(field);
        let seen = self.renumbers().and_then(|boards| {
            let number = text.parse::<u32>().ok().filter(|_| text.chars().all(|letter| letter.is_ascii_digit()))?;
            boards.iter().position(|board| *board == number)
        });
        seen.map_or_else(|| text.to_string(), |seen| seen.to_string())
    }

    /// The value of the flag of this config field as the process is to be told it.
    pub fn flag_value(&self, key: &str, value: &str) -> String {
        match key {
            "DEVICE" => self.device(value),
            "MAIN_GPU" => self.main_gpu(value),
            _ => value.to_string(),
        }
    }
}

/// `llama.cpp` keeps the V half of its KV cache in a quantized type only with flash attention on. With it off the server exits at once: the card said "Model loading failed", which is not the cause (2026-10-14). Flash attention left unstated is not refused: `llama.cpp` decides for itself, and it is no choice the operator made.
pub struct KvCache;

impl KvCache {
    /// The cache types that hold plain numbers, so need no flash attention. "" is the field left empty: `llama.cpp`'s own default.
    const PLAIN: [&'static str; 4] = ["", "f32", "f16", "bf16"];

    /// The quantized V cache type this config pairs with flash attention OFF, or "" when the pair is fine.
    pub fn refused_type(config: &Map<String, Value>) -> String {
        let flash = ConfigField::word(config, "ENABLE_FLASH_ATTN");
        if flash.is_empty() || Flag::yes(Some(&Value::String(flash))) {
            return String::new();
        }
        let kind = ConfigField::word(config, "CACHE_TYPE_V").to_lowercase();
        if Self::PLAIN.contains(&kind.as_str()) { String::new() } else { kind }
    }

    /// Refuses, naming the cause and the two ways out, a pair `llama.cpp` does not start with.
    pub fn check(config: &Map<String, Value>) -> Result<(), AppError> {
        let kind = Self::refused_type(config);
        if kind.is_empty() {
            return Ok(());
        }
        Err(AppError::new(format!(
            "The V cache type {kind} needs flash attention, which is off: llama.cpp stops with 'quantized V cache requires flash_attn to be enabled'. Turn ENABLE_FLASH_ATTN on, or set CACHE_TYPE_V to f16."
        )))
    }
}

/// The window a cell is started with: the number its field says, and for a field left empty the window its model was trained for: the owner, 2026-10-26. "0" counts as empty: it is `llama.cpp`'s own spelling of "from the model". A field that is not a number gives no window here: the start passes it on as typed and the runner refuses it by the field's name.
pub struct AskedWindow;

impl AskedWindow {
    /// Whether the field asks for the trained window: left empty, or "0".
    pub fn empty(field: &str) -> bool {
        matches!(Coerce::strip(field), "" | "0")
    }

    /// The window; `None` when neither is known.
    pub fn of(field: &str, trained: Option<i64>) -> Option<i64> {
        if Self::empty(field) {
            return trained.filter(|window| *window > 0);
        }
        Coerce::strip(field).parse::<i64>().ok().filter(|window| *window > 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn config(raw: Value) -> Map<String, Value> {
        raw.as_object().unwrap().clone()
    }

    #[test]
    fn yes_is_a_closed_list() {
        for good in [json!("1"), json!(" TRUE "), json!("Yes"), json!("on"), json!(1), json!(true)] {
            assert!(Flag::yes(Some(&good)), "{good}");
        }
        for bad in [json!("0"), json!("no"), json!(""), json!(0), json!(false), Value::Null, json!("y")] {
            assert!(!Flag::yes(Some(&bad)), "{bad}");
        }
        assert!(!Flag::yes(None));
    }

    #[test]
    fn env_pairs_skip_what_is_no_name() {
        let pairs = EnvField::pairs(Some(&json!("A=1, B = two\n#C=3\n1D=4\nE\nF=a=b")));
        assert_eq!(
            pairs,
            [("A".to_string(), "1".to_string()), ("B".to_string(), "two".to_string()), ("F".to_string(), "a=b".to_string())]
        );
        assert!(EnvField::pairs(None).is_empty());
    }

    #[test]
    fn a_cell_sees_the_cards_it_picked_numbered_from_zero() {
        let cards = CudaCards::of(&config(json!({"DEVICE": "CUDA1,cuda3"})));
        assert_eq!(cards.visible().as_deref(), Some("1,3"));
        assert_eq!(cards.device("CUDA1,cuda3"), "CUDA0,CUDA1");
        assert_eq!(cards.main_gpu("3"), "1");
        assert_eq!(cards.main_gpu("7"), "7");
        assert_eq!(cards.flag_value("OTHER", "x"), "x");
    }

    #[test]
    fn a_cpu_cell_sees_none_and_a_list_llama_would_not_read_changes_nothing() {
        let cpu = CudaCards::of(&config(json!({"N_GPU_LAYERS": "0", "DEVICE": "CUDA1"})));
        assert_eq!(cpu.visible().as_deref(), Some(""));
        assert_eq!(cpu.device("CUDA1"), "CUDA1");
        assert_eq!(CudaCards::of(&config(json!({"N_GPU_LAYERS": 0}))).visible().as_deref(), Some(""));
        for field in ["", "none", "Vulkan0", "CUDA1,CUDA1", "CUDA01", "CUDA1, CUDA2"] {
            assert_eq!(CudaCards::of(&config(json!({"DEVICE": field}))).visible(), None, "{field}");
        }
    }

    #[test]
    fn a_quantized_v_cache_needs_flash_attention_said_on_or_unsaid() {
        assert_eq!(KvCache::refused_type(&config(json!({"ENABLE_FLASH_ATTN": "0", "CACHE_TYPE_V": "q8_0"}))), "q8_0");
        assert_eq!(KvCache::refused_type(&config(json!({"ENABLE_FLASH_ATTN": "1", "CACHE_TYPE_V": "q8_0"}))), "");
        assert_eq!(KvCache::refused_type(&config(json!({"CACHE_TYPE_V": "q8_0"}))), "");
        assert_eq!(KvCache::refused_type(&config(json!({"ENABLE_FLASH_ATTN": "off", "CACHE_TYPE_V": "F16"}))), "");
        assert!(KvCache::check(&config(json!({"ENABLE_FLASH_ATTN": "no", "CACHE_TYPE_V": "q4_0"}))).is_err());
    }

    #[test]
    fn an_empty_window_asks_for_the_trained_one() {
        assert_eq!(AskedWindow::of("", Some(262_144)), Some(262_144));
        assert_eq!(AskedWindow::of("0", Some(100)), Some(100));
        assert_eq!(AskedWindow::of("4096", Some(100)), Some(4096));
        assert_eq!(AskedWindow::of("abc", Some(100)), None);
        assert_eq!(AskedWindow::of("", None), None);
        assert!(AskedWindow::empty(" 0 "));
        assert!(!AskedWindow::empty("abc"));
    }
}
