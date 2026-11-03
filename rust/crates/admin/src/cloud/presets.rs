//! The providers the board can add an account of: the table `CLOUD_PROVIDER_PRESETS` was.

use rules::Coerce;
use serde_json::{Map, Value, json};

/// The table, read once.
pub struct CloudPresets {
    table: Map<String, Value>,
}

impl Default for CloudPresets {
    fn default() -> Self {
        Self::new()
    }
}

impl CloudPresets {
    /// The table of this program.
    pub fn new() -> Self {
        // absent-ok: the table is this crate's own file, and a test reads it.
        let table = serde_json::from_str(include_str!("presets.json")).unwrap_or_default();
        Self { table }
    }

    /// The preset of a type.
    pub fn get(&self, kind: &str) -> Option<&Value> {
        self.table.get(kind)
    }

    /// The preset whose plan signs in by a one-time code; `None` for a plan that does not, or for no plan at all.
    pub fn device_login_preset(&self, account_type: &str) -> Option<&Value> {
        if account_type.is_empty() {
            return None;
        }
        self.table.values().find(|preset| {
            preset.get("accountType").and_then(Value::as_str) == Some(account_type) && Coerce::truthy(preset.get("deviceLogin"))
        })
    }

    /// How an account signs in by a one-time code; `None` when it has none. A test alias uses its original's login.
    pub fn device_login_spec(&self, account: &Value) -> Option<Value> {
        if Coerce::truthy(account.get("testAliasOf")) {
            return None;
        }
        self.device_login_preset(&Coerce::text(account.get("accountType"))).and_then(|preset| preset.get("deviceLogin")).cloned()
    }

    /// What the board may show of the table.
    pub fn public(&self) -> Value {
        let row = |(kind, preset): (&String, &Value)| {
            json!({
                "type": kind,
                "name": preset.get("name"),
                "baseUrl": preset.get("baseUrl"),
                "model": preset.get("model"),
                "authModes": preset.get("authModes").cloned().unwrap_or_else(|| json!(["apiKey"])),
                "accountType": Coerce::text(preset.get("accountType")),
                "deviceLogin": Coerce::truthy(preset.get("deviceLogin")),
                "oauth": preset.get("oauth").filter(|oauth| oauth.is_object()).cloned().unwrap_or_else(|| json!({})),
            })
        };
        Value::Array(self.table.iter().map(row).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_table_reads_and_keeps_its_order() {
        let presets = CloudPresets::new();
        let public = presets.public();
        let kinds: Vec<&str> = public.as_array().unwrap().iter().map(|row| row["type"].as_str().unwrap()).collect();
        assert_eq!(kinds.first(), Some(&"openai-subscription"));
        assert_eq!(kinds.last(), Some(&"custom"));
        assert_eq!(kinds.len(), 12);
    }

    #[test]
    fn only_a_subscription_signs_in_by_a_code() {
        let presets = CloudPresets::new();
        assert!(presets.device_login_preset("openai-subscription").is_some());
        assert!(presets.device_login_preset("openai-api").is_none());
        assert!(presets.device_login_preset("").is_none());
        let account = json!({"accountType": "openai-subscription"});
        assert!(presets.device_login_spec(&account).is_some());
        assert!(presets.device_login_spec(&json!({"accountType": "openai-subscription", "testAliasOf": "a"})).is_none());
    }
}
