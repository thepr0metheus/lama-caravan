//! What the file keeps beside its accounts and pools, each as the controller reads and writes it: levels of the subscription models, models added to Routing's right column, what the operator said a key's model does, and when each model is open.

use super::daytime::Daytime;
use super::model_jobs::ModelJobs;
use rules::{AppError, Coerce, PoolRow, PyRepr};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

mod levels;
pub use levels::AccountModelJobs;
pub use levels::AddedModels;
pub use levels::ModelLevels;
pub use levels::UsageLevels;

mod schedules;
pub use schedules::ModelKey;
pub use schedules::ModelSchedules;
pub use schedules::WeekWindows;

/// `str(value or "").strip()`.
struct Word;

impl Word {
    fn of(value: Option<&Value>) -> String {
        if Coerce::truthy(value) { Coerce::stripped(value) } else { String::new() }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn levels_are_read_from_the_file_and_the_old_steps() {
        let data = json!({"levels": {"a": {"m": {"stopAt": {"18000": 95}, "switchAt": {"18000": 5, "604800": 7}}}}, "pools": [{"steps": [{"accountId": "b", "model": "n", "switchAt": {"18000": 3}}, {"accountId": "b", "model": "n", "stopAt": {"18000": 8}}, {"accountId": "a", "model": "m", "stopAt": {"18000": 1}}]}]});
        let mut levels = ModelLevels::new(&data);
        assert_eq!(levels.of("a", "m"), (json!({"18000": 90}), json!({"18000": 90, "604800": 7})));
        assert_eq!(levels.of("b", "n"), (json!({"18000": 8}), json!({"18000": 8})));
        assert_eq!(levels.of("c", "x"), (json!({"18000": 10, "604800": 10}), json!({"18000": 10, "604800": 10})));
        assert!(!levels.is_set("c", "x"));
        levels.put("c", "x", &json!({"18000": 20}), &json!({"18000": 10}));
        assert_eq!(levels.of("c", "x"), (json!({"18000": 20}), json!({"18000": 20})));
        levels.forget_account("a");
        assert!(!levels.is_set("a", "m"));
    }

    #[test]
    fn added_models_keep_their_order() {
        let mut added = AddedModels::new(&json!({"addedModels": {"a": ["x", "y", "x", "z"]}}));
        assert_eq!(added.of("a"), ["x", "y", "z"]);
        added.put_first("a", &["z".to_string(), "nope".to_string()]);
        assert_eq!(added.of("a"), ["z", "x", "y"]);
        assert!(added.remove("a", "x"));
        assert!(!added.remove("a", "x"));
        assert_eq!(added.stored(), json!({"a": ["z", "y"]}));
    }

    #[test]
    fn what_is_said_of_a_keys_model_is_in_the_vocabulary() {
        let mut jobs = AccountModelJobs::new(&json!({"modelJobs": {"a": {"m": ["tts", "llm", "voice-chat"]}}}));
        assert_eq!(jobs.of("a", "m"), Some(vec!["llm", "tts"]));
        assert_eq!(jobs.put("a", "m", &[]), None);
        assert_eq!(AccountModelJobs::unknown(&[json!("llm"), json!("x"), json!(1)]), [json!("x"), json!(1)]);
    }

    #[test]
    fn a_window_says_what_is_wrong_with_it() {
        assert_eq!(
            WeekWindows::parse(Some(&json!([{"from": "9:00", "to": "10:00", "days": [1, 1, 0]}]))).unwrap(),
            [json!({"days": [0, 1], "from": "09:00", "to": "10:00"})]
        );
        assert_eq!(
            WeekWindows::parse(Some(&json!([{"from": "9:00"}]))).unwrap_err().message,
            "window 1: `to` is required, as HH:MM"
        );
        assert_eq!(
            WeekWindows::parse(Some(&json!([{"from": "9:00", "to": "1:00", "days": [9]}]))).unwrap_err().message,
            "window 1: days must be numbers 0..6 (Monday is 0), got 9"
        );
        assert_eq!(WeekWindows::parse(Some(&json!("x"))).unwrap_err().message, "windows must be a list");
        assert_eq!(
            WeekWindows::clean(Some(
                &json!([{"from": "x", "to": "y"}, {"from": "1:00", "to": "2:00", "days": [0, 1, 2, 3, 4, 5, 6]}])
            )),
            [json!({"days": [], "from": "01:00", "to": "02:00"})]
        );
    }

    #[test]
    fn a_models_key_reads_back() {
        assert_eq!(ModelKey::parse("acc:a/m"), Some(("account", "a".to_string(), "m".to_string())));
        assert_eq!(ModelKey::parse("out:srv:h:1"), Some(("output", "srv:h:1".to_string(), String::new())));
        assert_eq!(ModelKey::parse("acc:a"), None);
        assert_eq!(ModelKey::parse("x"), None);
        assert_eq!(ModelKey::of_row(&json!({"kind": "open"})), "");
    }

    #[test]
    fn a_schedule_follows_its_cell() {
        let mut schedules =
            ModelSchedules::new(&json!({"schedules": {"out:srv:h:1": {"enabled": true, "windows": []}, "nonsense": {}}}));
        assert!(schedules.follow("srv:h:1", "srv:h:2"));
        assert!(schedules.of("out:srv:h:2").is_some());
        assert!(schedules.swap("srv:h:2", "srv:h:3"));
        assert!(schedules.of("out:srv:h:3").is_some());
        assert!(!schedules.swap("srv:h:8", "srv:h:9"));
    }
}
