//! A GGUF's runtime facts, from what its header says.

use super::gguf_header::GgufHeader;
use crate::app::App;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::os::unix::fs::MetadataExt;
use std::path::Path;

/// The readings.
pub struct ModelHeader;

impl ModelHeader {
    /// The header's facts, remembered by (path, mtime, size): a file does not change its header without changing those.
    pub fn read_cached(app: &App, path: &Path) -> Map<String, Value> {
        let Ok(meta) = std::fs::metadata(path) else {
            return GgufHeader::read(path);
        };
        let (name, mtime, size) = (path.to_string_lossy().into_owned(), meta.mtime(), meta.size() as i64);
        if let Some(hit) = app.header_memory.recall(&name, mtime, size) {
            return hit;
        }
        let hit = GgufHeader::read(path);
        app.header_memory.remember(&name, mtime, size, &hit);
        hit
    }

    fn found<'meta>(meta: &'meta Map<String, Value>, prefix: &str, name: &str) -> Option<&'meta Value> {
        let exact = meta.get(&format!("{prefix}{name}")).filter(|value| !value.is_null());
        exact.or_else(|| meta.iter().find(|(key, _)| key.ends_with(name)).map(|(_, value)| value))
    }

    fn number(meta: &Map<String, Value>, prefix: &str, name: &str) -> i64 {
        match Self::found(meta, prefix, name) {
            Some(Value::Array(items)) => {
                let numbers = items.iter().filter(|item| item.is_number() || item.is_boolean());
                let most = numbers
                    .map(|item| item.as_f64().unwrap_or_else(|| if item == &json!(true) { 1.0 } else { 0.0 }))
                    .fold(None, |held: Option<f64>, value| Some(held.map_or(value, |held| held.max(value))));
                // absent-ok: `max(..., default=0)`: a list of no numbers is 0.
                most.unwrap_or(0.0).trunc() as i64
            }
            Some(Value::Bool(flag)) => i64::from(*flag),
            // absent-ok: `int(value)` of what does not read is 0: what the callers take for "not said".
            Some(value) => Coerce::int(value).unwrap_or(0),
            None => 0,
        }
    }

    fn layers(meta: &Map<String, Value>, prefix: &str, name: &str) -> Vec<i64> {
        let Some(Value::Array(items)) = Self::found(meta, prefix, name) else {
            return Vec::new();
        };
        // absent-ok: one item that does not read leaves no list at all, as a whole: `[]`.
        items
            .iter()
            .map(|item| if item.is_boolean() { Some(i64::from(item == &json!(true))) } else { Coerce::int(item) })
            .collect::<Option<Vec<i64>>>()
            // absent-ok: a header that names no field has nothing to say of it.
            .unwrap_or_default()
    }

    /// The runtime facts of a header's facts.
    pub fn runtime_meta(meta: &Map<String, Value>) -> Value {
        let arch = Coerce::str_of(meta.get("general.architecture"));
        let prefix = if arch.is_empty() { String::new() } else { format!("{arch}.") };
        let number = |name: &str| Self::number(meta, &prefix, name);
        let layers = |name: &str| Self::layers(meta, &prefix, name);
        let mut pooling = -1;
        if let Some((_, value)) = meta.iter().find(|(key, _)| key.ends_with("pooling_type")) {
            // absent-ok: a pooling that does not read is the same -1 as none.
            pooling = Coerce::int(value).unwrap_or(-1);
        }
        let languages: Vec<String> = match meta.get("general.languages") {
            Some(Value::String(one)) if !one.is_empty() => vec![one.clone()],
            Some(Value::Array(many)) => many.iter().take(8).map(|one| Coerce::str_of(Some(one))).collect(),
            _ => Vec::new(),
        };
        let head_count = number("attention.head_count");
        let head_count_kv = number("attention.head_count_kv");
        let keys = meta.get(GgufHeader::KEYS).filter(|keys| keys.is_i64() || keys.is_u64());
        // absent-ok: `int(meta.get(...) or 0)`: no expert tensors found.
        let expert_bytes = Coerce::i64_or_zero(meta.get(GgufHeader::EXPERT_BYTES));
        json!({
            "architecture": arch,
            "sttVariant": Coerce::text(meta.get("stt.variant")),
            "languages": languages,
            "blockCount": number("block_count"),
            "contextLength": number("context_length"),
            "embeddingLength": number("embedding_length"),
            "headCount": head_count,
            "headCountKv": if head_count_kv != 0 { head_count_kv } else { head_count },
            "keyLength": number("attention.key_length"),
            "valueLength": number("attention.value_length"),
            "headCountKvLayers": layers("attention.head_count_kv"),
            "slidingWindow": number("attention.sliding_window"),
            "slidingWindowLayers": layers("attention.sliding_window_pattern"),
            "keyLengthSwa": number("attention.key_length_swa"),
            "valueLengthSwa": number("attention.value_length_swa"),
            "sharedKvLayers": number("attention.shared_kv_layers"),
            "fullAttentionInterval": number("full_attention_interval"),
            "recurrentLayers": layers("attention.recurrent_layers"),
            "poolingType": pooling,
            "specBlockSize": number("block_size"),
            "expertCount": number("expert_count"),
            "expertBytes": expert_bytes,
            "headerKeys": keys,
        })
    }

    /// The header's runtime facts where this controller reads it; empty for a file that is not here.
    pub fn of_path(app: &App, path: &Path) -> Value {
        if !path.is_file() {
            return json!({});
        }
        Self::runtime_meta(&Self::read_cached(app, path))
    }
}

#[cfg(test)]
mod tests {
    use super::super::listing::ModelListing;
    use super::super::locator::Locations;
    use super::*;
    use crate::domain::runner::Config;
    use crate::tests::{TestApp, TestFolder};
    use std::time::{Duration, SystemTime};

    /// A GGUF header of version 3 with these (key, text) pairs, tensors or not after it.
    fn gguf_with(pairs: &[(&str, &str)]) -> Vec<u8> {
        let word = |text: &str| [(text.len() as u64).to_le_bytes().to_vec(), text.as_bytes().to_vec()].concat();
        let mut out = b"GGUF".to_vec();
        out.extend(3_u32.to_le_bytes());
        out.extend(0_u64.to_le_bytes());
        out.extend((pairs.len() as u64).to_le_bytes());
        for (key, value) in pairs {
            out.extend(word(key));
            out.extend(8_u32.to_le_bytes());
            out.extend(word(value));
        }
        out
    }

    fn stamped(path: &Path, seconds: u64) {
        let when = SystemTime::UNIX_EPOCH + Duration::from_secs(seconds);
        std::fs::File::options().write(true).open(path).unwrap().set_modified(when).unwrap();
    }

    fn architecture(app: &App, path: &Path) -> Value {
        ModelHeader::read_cached(app, path).get("general.architecture").cloned().unwrap_or(Value::Null)
    }

    #[test]
    fn a_header_is_read_once_and_a_file_that_changed_is_read_again() {
        let folder = TestFolder::new("headers-cached");
        let app = TestApp::over(&folder.path, &[]);
        let path = folder.path.join("a.gguf");
        let first = gguf_with(&[("general.architecture", "first")]);
        let second = gguf_with(&[("general.architecture", "other")]);
        assert_eq!(first.len(), second.len(), "the same size: only the time tells them apart");
        std::fs::write(&path, &first).unwrap();
        stamped(&path, 1_780_000_000);
        assert_eq!(architecture(&app, &path), json!("first"));
        std::fs::write(&path, &second).unwrap();
        stamped(&path, 1_780_000_000);
        assert_eq!(architecture(&app, &path), json!("first"), "the same second and size: recalled, and nothing is parsed");
        stamped(&path, 1_780_000_005);
        assert_eq!(architecture(&app, &path), json!("other"), "written again at the same size: parsed again");
        std::fs::write(&path, gguf_with(&[("general.architecture", "grown!")])).unwrap();
        stamped(&path, 1_780_000_005);
        assert_eq!(architecture(&app, &path), json!("grown!"), "the same second and another size: parsed again");
    }

    #[test]
    fn a_header_read_in_one_start_is_recalled_in_the_next() {
        let folder = TestFolder::new("headers-restart");
        let path = folder.path.join("a.gguf");
        std::fs::write(&path, gguf_with(&[("general.architecture", "first")])).unwrap();
        stamped(&path, 1_780_000_000);
        let app = TestApp::over(&folder.path, &[]);
        assert_eq!(architecture(&app, &path), json!("first"));
        assert!(app.header_memory.flush());
        std::fs::write(&path, gguf_with(&[("general.architecture", "other")])).unwrap();
        stamped(&path, 1_780_000_000);
        assert_eq!(
            architecture(&TestApp::over(&folder.path, &[]), &path),
            json!("first"),
            "the same second and size after a restart: nothing is parsed"
        );
    }

    #[test]
    fn a_header_that_said_nothing_is_read_once_in_a_process_and_again_after_a_restart() {
        let folder = TestFolder::new("headers-nothing");
        let path = folder.path.join("junk.gguf");
        let good = gguf_with(&[("general.architecture", "first")]);
        std::fs::write(&path, vec![b'j'; good.len()]).unwrap();
        stamped(&path, 1_780_000_000);
        let app = TestApp::over(&folder.path, &[]);
        assert!(ModelHeader::read_cached(&app, &path).is_empty());
        std::fs::write(&path, &good).unwrap();
        stamped(&path, 1_780_000_000);
        assert!(ModelHeader::read_cached(&app, &path).is_empty(), "read once in this process");
        assert!(!app.header_memory.flush(), "and nothing was written of it");
        assert_eq!(architecture(&TestApp::over(&folder.path, &[]), &path), json!("first"), "a start that follows reads it again");
    }

    #[test]
    fn a_file_that_is_not_there_is_asked_of_the_reader_each_time_and_remembered_by_nobody() {
        let folder = TestFolder::new("headers-gone");
        let app = TestApp::over(&folder.path, &[]);
        let gone = folder.path.join("gone.gguf");
        assert!(ModelHeader::read_cached(&app, &gone).is_empty());
        assert_eq!(app.header_memory.recall(&gone.to_string_lossy(), 0, 0), None);
        std::fs::write(&gone, gguf_with(&[("general.architecture", "came")])).unwrap();
        assert_eq!(architecture(&app, &gone), json!("came"), "when it comes, it is read");
    }

    #[test]
    fn a_walk_of_the_folder_writes_the_header_that_said_something_and_not_the_file_that_is_no_gguf() {
        let folder = TestFolder::new("headers-walk");
        let app = TestApp::over(&folder.path, &[]);
        let models = app.models_dir();
        let (model, junk) = (models.join("Demo-GGUF/x/Q4_K_M/demo-Q4_K_M.gguf"), models.join("Other-GGUF/x/Q8_0/junk-Q8_0.gguf"));
        std::fs::create_dir_all(model.parent().unwrap()).unwrap();
        std::fs::create_dir_all(junk.parent().unwrap()).unwrap();
        let mut bytes = gguf_with(&[("general.architecture", "llama"), ("llama.context_length", "1")]);
        bytes.extend(b"tensors".repeat(10));
        std::fs::write(&model, &bytes).unwrap();
        std::fs::write(&junk, b"not a gguf at all").unwrap();
        let rows = ModelListing::of(&app).rows(&Config::new(), &Locations::new(&[], "/h"));
        assert_eq!(rows.len(), 2, "two rows: {rows:?}");
        let doc: Value = serde_json::from_slice(&std::fs::read(&app.paths.gguf_headers_file).unwrap()).unwrap();
        let files = doc["files"].as_object().unwrap();
        let said = model.to_string_lossy().into_owned();
        assert_eq!(files.keys().collect::<Vec<_>>(), [&said]);
        assert_eq!(
            files[&said]["meta"],
            json!({"general.architecture": "llama", "llama.context_length": "1", "caravan.keys": 2})
        );
        let meta = std::fs::metadata(&model).unwrap();
        assert_eq!((&files[&said]["mtime"], &files[&said]["size"]), (&json!(meta.mtime()), &json!(meta.size())));
    }

    #[test]
    fn a_later_part_of_a_header_says_its_facts_by_the_name_they_end_in_where_the_architecture_says_none() {
        let meta = json!({"general.architecture": "qwen3", "other.context_length": 512, "qwen3.block_count": 4})
            .as_object()
            .unwrap()
            .clone();
        let facts = ModelHeader::runtime_meta(&meta);
        assert_eq!((&facts["contextLength"], &facts["blockCount"]), (&json!(512), &json!(4)));
        let chosen =
            json!({"general.architecture": "qwen3", "a.block_count": 1, "qwen3.block_count": 4}).as_object().unwrap().clone();
        assert_eq!(ModelHeader::runtime_meta(&chosen)["blockCount"], json!(4), "the architecture's own key goes first");
    }

    #[test]
    fn a_header_comes_to_its_facts() {
        let meta = json!({"general.architecture": "qwen3", "qwen3.context_length": 4096, "qwen3.attention.head_count": [8, 16, 4], "other.block_count": 12, "general.languages": "en", "caravan.keys": 5, "qwen3.pooling_type": 1}).as_object().unwrap().clone();
        let facts = ModelHeader::runtime_meta(&meta);
        assert_eq!(facts.get("contextLength"), Some(&json!(4096)));
        assert_eq!(facts.get("headCount"), Some(&json!(16)));
        assert_eq!(facts.get("headCountKv"), Some(&json!(16)));
        assert_eq!(facts.get("blockCount"), Some(&json!(12)));
        assert_eq!(facts.get("languages"), Some(&json!(["en"])));
        assert_eq!(facts.get("headerKeys"), Some(&json!(5)));
        assert_eq!(facts.get("poolingType"), Some(&json!(1)));
        let empty = ModelHeader::runtime_meta(&Map::new());
        assert_eq!(empty.get("poolingType"), Some(&json!(-1)));
        assert_eq!(empty.get("headerKeys"), Some(&Value::Null));
    }
}
