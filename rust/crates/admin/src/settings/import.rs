//! A settings file taken back: what it would change, and the change.

use super::*;

impl<'app> SettingsBundle<'app> {
    /// Carries a redacted secret forward from what is on disk.
    pub(super) fn merge_secrets(name: &str, mut incoming: Value, current: &Value) -> Value {
        if !incoming.is_object() || !current.is_object() {
            return incoming;
        }
        if name == Self::ADMIN {
            if incoming.get("hfToken").and_then(Value::as_str) == Some(Self::REDACTED) {
                Coerce::put(&mut incoming, "hfToken", current.get("hfToken").cloned().unwrap_or_else(|| json!("")));
            }
            if incoming.get("monitor").is_none()
                && let Some(kept) = current.get("monitor")
            {
                Coerce::put(&mut incoming, "monitor", kept.clone());
            }
        }
        if name == Self::PROXIES {
            let held = current.get("routes").and_then(Value::as_array);
            for route in incoming.get_mut("routes").and_then(Value::as_array_mut).into_iter().flatten() {
                if route.get("apiKey").and_then(Value::as_str) != Some(Self::REDACTED) {
                    continue;
                }
                let id = Coerce::stripped(route.get("id"));
                let key = held
                    .into_iter()
                    .flatten()
                    .find(|row| row.is_object() && !id.is_empty() && Coerce::stripped(row.get("id")) == id)
                    .and_then(|row| row.get("apiKey").cloned())
                    .unwrap_or_else(|| json!(""));
                Coerce::put(route, "apiKey", key);
            }
        }
        incoming
    }

    pub(super) fn validate(bundle: &Value) -> Result<&Map<String, Value>, AppError> {
        if !bundle.is_object() {
            return Err(AppError::new("not a settings file"));
        }
        if Coerce::text(bundle.get("kind")) != Self::KIND {
            return Err(AppError::new("this file is not a Lama Caravan settings export"));
        }
        if bundle.get("format").and_then(Value::as_i64) != Some(Self::FORMAT) {
            let said = rules::PyRepr::of_value(bundle.get("format").unwrap_or(&Value::Null));
            return Err(AppError::new(format!("settings format {said} — this controller reads format {}", Self::FORMAT)));
        }
        bundle.get("files").and_then(Value::as_object).ok_or_else(|| AppError::new("settings file has no files section"))
    }

    pub(super) fn entry_of<'bundle>(files: &'bundle Map<String, Value>, name: &str) -> Option<&'bundle Value> {
        files.get(name).filter(|entry| entry.get("content").is_some_and(|content| !content.is_null()))
    }

    /// What applying this bundle would change, before anything is written.
    pub fn preview_import(&self, bundle: &Value) -> Result<Value, AppError> {
        let files = Self::validate(bundle)?;
        let mut rows = Vec::new();
        for file in self.files() {
            let Some(entry) = Self::entry_of(files, file.name) else {
                rows.push(json!({"name": file.name, "action": "skip", "note": "not in the file"}));
                continue;
            };
            let same = if file.name == Self::CONFIG {
                Self::read_text(&file.path).map(Value::String).as_ref() == entry.get("content")
            } else {
                let current = Self::read_json(&file.path)?;
                let incoming = Self::merge_secrets(
                    file.name,
                    entry.get("content").cloned().unwrap_or(Value::Null),
                    current.as_ref().unwrap_or(&json!({})),
                );
                current.as_ref() == Some(&incoming)
            };
            rows.push(json!({"name": file.name, "action": if same { "same" } else { "replace" }}));
        }
        for name in [Self::SECRETS, Self::ACCOUNTS] {
            let Some(entry) = Self::entry_of(files, name) else {
                let omitted = files.get(name).map_or_else(String::new, |entry| Coerce::text(entry.get("omitted")));
                let note = if omitted.is_empty() { "not in the file".to_string() } else { omitted };
                rows.push(json!({"name": name, "action": "skip", "note": note}));
                continue;
            };
            let locked = Self::locked(entry.get("content"));
            let plain_note = if name == Self::ACCOUNTS { "credentials" } else { "cloud keys" };
            rows.push(json!({
                "name": name,
                "action": if locked { "locked" } else { "replace" },
                "note": if locked { "needs the passphrase" } else { plain_note },
            }));
        }
        for (name, why) in Self::RETIRED {
            if Coerce::truthy(files.get(name).and_then(|entry| entry.get("content"))) {
                rows.push(json!({"name": name, "action": "skip", "note": why}));
            }
        }
        Ok(
            json!({"changes": rows, "includesSecrets": Coerce::truthy(bundle.get("includesSecrets")), "exportedAt": bundle.get("exportedAt")}),
        )
    }

    pub(super) fn write_file(path: &Path, body: &[u8]) -> Result<(), AppError> {
        let failed = |error: std::io::Error| AppError::with_status(format!("{}: {error}", path.display()), 500);
        if let Some(folder) = path.parent() {
            std::fs::create_dir_all(folder).map_err(failed)?;
        }
        AtomicFile::write(path, body).map_err(failed)
    }

    /// Writes the bundle's settings over the current ones.
    pub fn apply(&self, bundle: &Value, passphrase: &str) -> Result<Value, AppError> {
        let files = Self::validate(bundle)?;
        let copy = CopyBeforeImport { directory: self.app.paths.settings_backup_dir.clone() };
        let before = copy.write(&PythonJson::indented(&self.export(true)?), self.app.now())?;
        let mut written = Vec::new();
        let mut skipped: Vec<String> = Vec::new();
        for file in self.files() {
            let Some(entry) = Self::entry_of(files, file.name) else {
                continue;
            };
            if file.name == Self::CONFIG {
                let text = Coerce::str_of(entry.get("content"));
                Self::write_file(&file.path, text.as_bytes())?;
            } else {
                let current = Self::read_json(&file.path)?.unwrap_or_else(|| json!({}));
                let data = Self::merge_secrets(file.name, entry.get("content").cloned().unwrap_or(Value::Null), &current);
                Self::write_file(&file.path, PythonJson::indented(&data).as_bytes())?;
            }
            written.push(file.name.to_string());
        }
        for (name, _) in Self::RETIRED {
            if Coerce::truthy(files.get(name).and_then(|entry| entry.get("content"))) {
                skipped.push(name.to_string());
            }
        }
        self.apply_credentials(files, passphrase, &mut written, &mut skipped)?;
        self.app.admin.reload();
        Ok(json!({"written": written, "skipped": skipped, "backup": before.to_string_lossy()}))
    }

    pub(super) fn apply_credentials(
        &self,
        files: &Map<String, Value>,
        passphrase: &str,
        written: &mut Vec<String>,
        skipped: &mut Vec<String>,
    ) -> Result<(), AppError> {
        for name in [Self::SECRETS, Self::ACCOUNTS] {
            let Some(entry) = Self::entry_of(files, name) else {
                continue;
            };
            let Some(decoded) = Self::opened(entry, passphrase)? else {
                skipped.push(name.to_string());
                continue;
            };
            let taken = if name == Self::ACCOUNTS {
                self.apply_accounts(entry, &decoded)?
            } else {
                match decoded {
                    Value::Object(document) => {
                        let vault = CredentialVault::new(self.app.paths.provider_secrets_file.clone());
                        vault.replace(document).map_err(|error| AppError::with_status(error.to_string(), 500))?;
                        true
                    }
                    _ => false,
                }
            };
            if taken {
                written.push(name.to_string());
            } else {
                skipped.push(name.to_string());
            }
        }
        Ok(())
    }

    /// The accounts: a document, or the database file an older export carries as base64.
    pub(super) fn apply_accounts(&self, entry: &Value, decoded: &Value) -> Result<bool, AppError> {
        if Coerce::text(entry.get("kind")) == "base64" {
            let raw = decoded
                .as_str()
                .and_then(Base64Std::decode)
                .ok_or_else(|| AppError::new("the accounts database in this settings file is not base64"))?;
            self.app.auth.replace_from_database(raw)?;
            return Ok(true);
        }
        match decoded {
            Value::Object(document) => {
                self.app.auth.replace_document(document.clone())?;
                Ok(true)
            }
            _ => Ok(false),
        }
    }
}
