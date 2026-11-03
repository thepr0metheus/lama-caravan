//! Whether a machine's NVIDIA card will be there after its next reboot. 2026-09-26: the automatic updates installed a kernel, held back the signed NVIDIA modules it needed, and a reboot the next day came up without the card. Everything that said so was on the machine the morning before. Its scout reports those facts as `driver`; this is the one place that reads them.

use rules::Coerce;
use serde_json::{Value, json};

/// A machine's driver facts and what they mean for its next boot.
pub struct DriverOutlook {
    facts: Value,
}

impl DriverOutlook {
    const TEXT: usize = 200;

    /// The outlook of a report's `driver`.
    pub fn new(facts: &Value) -> Self {
        Self { facts: Self::clean(facts) }
    }

    /// `^\d[\w.+-]*$`.
    fn is_kernel(text: &str) -> bool {
        text.chars().next().is_some_and(|first| first.is_ascii_digit())
            && text.chars().all(|letter| letter.is_alphanumeric() || matches!(letter, '_' | '.' | '+' | '-'))
    }

    /// `^\d+(?:\.\d+)+$`.
    fn is_version(text: &str) -> bool {
        let parts: Vec<&str> = text.split('.').collect();
        parts.len() >= 2 && parts.iter().all(|part| !part.is_empty() && part.chars().all(|letter| letter.is_ascii_digit()))
    }

    /// `^nvidia-driver-(\d+)(-open)?$`: the number and the "-open".
    fn package_parts(text: &str) -> Option<(&str, &str)> {
        let rest = text.strip_prefix("nvidia-driver-")?;
        let (number, open) = rest.strip_suffix("-open").map_or((rest, ""), |number| (number, "-open"));
        (!number.is_empty() && number.chars().all(|letter| letter.is_ascii_digit())).then_some((number, open))
    }

    fn text(value: Option<&Value>, shape: Option<fn(&str) -> bool>) -> Value {
        let Some(said) = value.and_then(Value::as_str) else {
            return Value::Null;
        };
        let said = Coerce::first_letters(Coerce::strip(said), Self::TEXT);
        if said.is_empty() || shape.is_some_and(|shape| !shape(said)) { Value::Null } else { json!(said) }
    }

    fn flag(value: Option<&Value>) -> Value {
        value.filter(|said| said.is_boolean()).cloned().unwrap_or(Value::Null)
    }

    /// The facts as the host record keeps them: a kernel and a version only in their own shape, the rest trimmed and cut, a flag only as a flag. `null` when the report has none.
    pub fn clean(raw: &Value) -> Value {
        if !raw.is_object() {
            return Value::Null;
        }
        let module = raw.get("nextModule").filter(|module| module.is_object() && !Self::text(module.get("path"), None).is_null());
        let key = raw.get("dkmsKey").filter(|key| key.is_object());
        let next_module = module.map_or(Value::Null, |module| {
            let signer = Self::text(module.get("signer"), None);
            json!({
                "path": Self::text(module.get("path"), None),
                "version": Self::text(module.get("version"), Some(Self::is_version)),
                "signer": if signer.is_null() { json!("") } else { signer },
            })
        });
        json!({
            "secureBoot": Self::flag(raw.get("secureBoot")),
            "kernelRunning": Self::text(raw.get("kernelRunning"), Some(Self::is_kernel)),
            "kernelNext": Self::text(raw.get("kernelNext"), Some(Self::is_kernel)),
            "loaded": Self::text(raw.get("loaded"), Some(Self::is_version)),
            "installed": Self::text(raw.get("installed"), Some(Self::is_version)),
            "nextModule": next_module,
            "dkmsKey": key.map_or(Value::Null, |key| json!({"signer": Self::text(key.get("signer"), None), "enrolled": Self::flag(key.get("enrolled"))})),
            "package": Self::text(raw.get("package"), Some(|text| Self::package_parts(text).is_some())),
        })
    }

    /// The facts kept.
    pub fn facts(&self) -> &Value {
        &self.facts
    }

    /// The signed modules for `kernel`, named after the driver installed; `None` when the driver package is not known.
    fn signed_modules_package(&self, kernel: &str) -> Option<String> {
        let package = self.facts.get("package").and_then(Value::as_str)?;
        let (number, open) = Self::package_parts(package)?;
        Some(format!("linux-modules-nvidia-{number}{open}-{kernel}"))
    }

    /// Why Secure Boot will refuse the module the next kernel would load: "unsigned", or "untrusted-key". `None` otherwise: only what the facts prove is said.
    fn next_module_refused(&self) -> Option<&'static str> {
        let module = self.facts.get("nextModule").filter(|module| !module.is_null())?;
        if self.facts.get("secureBoot") != Some(&Value::Bool(true)) {
            return None;
        }
        let signer = Coerce::text(module.get("signer"));
        if signer.is_empty() {
            return Some("unsigned");
        }
        let key = self.facts.get("dkmsKey");
        let key_signer = key.and_then(|key| key.get("signer")).and_then(Value::as_str);
        let enrolled = key.and_then(|key| key.get("enrolled"));
        (key_signer.is_some_and(|said| !said.is_empty() && said == signer) && enrolled == Some(&Value::Bool(false)))
            .then_some("untrusted-key")
    }

    /// What the board says before it happens.
    pub fn warnings(&self) -> Vec<Value> {
        let mut out = Vec::new();
        if self.facts.is_null() {
            return out;
        }
        let word = |key: &str| self.facts.get(key).and_then(Value::as_str);
        if let (Some(following), Some(running)) = (word("kernelNext"), word("kernelRunning")).filter2() {
            let missing = self.facts.get("nextModule").is_none_or(Value::is_null);
            let reason = if missing { Some("missing") } else { self.next_module_refused() };
            if let (true, Some(reason)) = (following != running, reason) {
                out.push(json!({"kind": "nextBootNoDriver", "reason": reason, "kernel": following, "package": self.signed_modules_package(following)}));
            }
        }
        if let (Some(loaded), Some(installed)) = (word("loaded"), word("installed")).filter2()
            && loaded != installed
        {
            out.push(json!({"kind": "rebootForDriver", "loaded": loaded, "installed": installed}));
        }
        out
    }
}

/// Two words, both there.
trait BothSaid<'a> {
    fn filter2(self) -> (Option<&'a str>, Option<&'a str>);
}

impl<'a> BothSaid<'a> for (Option<&'a str>, Option<&'a str>) {
    fn filter2(self) -> (Option<&'a str>, Option<&'a str>) {
        match self {
            (Some(one), Some(other)) => (Some(one), Some(other)),
            _ => (None, None),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_kernel_with_no_module_warns_before_the_reboot() {
        let outlook = DriverOutlook::new(
            &json!({"kernelRunning": "6.8.0-45", "kernelNext": "6.8.0-47", "package": "nvidia-driver-570-open", "secureBoot": true}),
        );
        let warnings = outlook.warnings();
        assert_eq!(
            warnings,
            [
                json!({"kind": "nextBootNoDriver", "reason": "missing", "kernel": "6.8.0-47", "package": "linux-modules-nvidia-570-open-6.8.0-47"})
            ]
        );
    }

    #[test]
    fn secure_boot_refuses_what_is_unsigned_or_untrusted() {
        let unsigned = DriverOutlook::new(
            &json!({"kernelRunning": "6.8", "kernelNext": "6.9", "secureBoot": true, "nextModule": {"path": "/m", "signer": ""}}),
        );
        assert_eq!(unsigned.warnings().first().and_then(|row| row.get("reason")), Some(&json!("unsigned")));
        let untrusted = DriverOutlook::new(
            &json!({"kernelRunning": "6.8", "kernelNext": "6.9", "secureBoot": true, "nextModule": {"path": "/m", "signer": "dkms"}, "dkmsKey": {"signer": "dkms", "enrolled": false}}),
        );
        assert_eq!(untrusted.warnings().first().and_then(|row| row.get("reason")), Some(&json!("untrusted-key")));
        let trusted = DriverOutlook::new(
            &json!({"kernelRunning": "6.8", "kernelNext": "6.9", "secureBoot": true, "nextModule": {"path": "/m", "signer": "Canonical"}}),
        );
        assert!(trusted.warnings().is_empty());
        let off = DriverOutlook::new(
            &json!({"kernelRunning": "6.8", "kernelNext": "6.9", "secureBoot": false, "nextModule": {"path": "/m", "signer": ""}}),
        );
        assert!(off.warnings().is_empty());
    }

    #[test]
    fn the_driver_in_use_differs_until_a_reboot() {
        let outlook = DriverOutlook::new(&json!({"loaded": "570.1", "installed": "570.2"}));
        assert_eq!(outlook.warnings(), [json!({"kind": "rebootForDriver", "loaded": "570.1", "installed": "570.2"})]);
    }

    #[test]
    fn what_has_no_shape_is_not_kept() {
        let clean =
            DriverOutlook::clean(&json!({"kernelNext": "not a kernel!", "loaded": "x", "package": "other", "secureBoot": "yes"}));
        assert_eq!(clean.get("kernelNext"), Some(&Value::Null));
        assert_eq!(clean.get("loaded"), Some(&Value::Null));
        assert_eq!(clean.get("package"), Some(&Value::Null));
        assert_eq!(clean.get("secureBoot"), Some(&Value::Null));
        assert_eq!(DriverOutlook::clean(&json!(5)), Value::Null);
    }
}
