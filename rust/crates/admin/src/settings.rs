//! Every setting the GUI can change, in one file, and back again. One difference, named: the accounts live in a JSON document here (`AuthStore`), so an export carries that document, and an import still takes the old database file.

use crate::app::App;
use files::{AtomicFile, CredentialVault};
use net::{Base64Std, Randomness, Scrypt, SealedBytes};
use os::LocalTime;
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::io::{ErrorKind, Write};
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::{Path, PathBuf};

mod import;

/// The copy an import takes of the settings it is about to replace.
struct CopyBeforeImport {
    directory: PathBuf,
}

impl CopyBeforeImport {
    const SUFFIX: &'static str = "-before-import.json";
    const ATTEMPTS: u32 = 1000;

    /// Writes the copy and says where it is. A second import in the same microsecond takes the next one.
    fn write(&self, text: &str, epoch: f64) -> Result<PathBuf, AppError> {
        let failed = |error: std::io::Error| AppError::with_status(format!("the settings copy did not write: {error}"), 500);
        std::fs::DirBuilder::new().recursive(true).mode(0o700).create(&self.directory).map_err(failed)?;
        let second = epoch.trunc() as i64;
        let start = ((epoch - epoch.trunc()) * 1_000_000.0) as u32;
        let stamp = LocalTime::of(second).map_or_else(|| second.to_string(), |local| local.compact());
        for attempt in 0..Self::ATTEMPTS {
            let path = self.directory.join(format!("{stamp}-{:06}{}", start + attempt, Self::SUFFIX));
            let file = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&path);
            match file {
                Ok(mut file) => {
                    file.write_all(text.as_bytes()).map_err(failed)?;
                    return Ok(path);
                }
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
                Err(error) => return Err(failed(error)),
            }
        }
        Err(AppError::with_status(format!("no free name for the settings copy in {}", self.directory.display()), 500))
    }
}

/// One settings file: what a bundle calls it, and where it is.
struct SettingsFile {
    name: &'static str,
    path: PathBuf,
}

/// The whole of it.
pub struct SettingsBundle<'app> {
    app: &'app App,
}

impl<'app> SettingsBundle<'app> {
    const FORMAT: i64 = 1;
    const KIND: &'static str = "lama-caravan-settings";
    const REDACTED: &'static str = "__redacted__";
    const LOCK_MARK: &'static str = "aes-256-gcm/scrypt";
    const SCRYPT_COST: usize = 1 << 15;
    const SCRYPT_SIZE: usize = 8;
    const SCRYPT_PARALLEL: usize = 1;
    const KEY_BYTES: usize = 32;
    const SALT_BYTES: usize = 16;
    const NONCE_BYTES: usize = 12;
    const SECRETS: &'static str = "provider-secrets";
    const ACCOUNTS: &'static str = "auth-db";
    const RETIRED: [(&'static str, &'static str); 2] = [
        (
            "server-cells",
            "the controller runs no cells of its own since step 6.9 — its old launch files are not restored; the cells come back with admin-state",
        ),
        (
            "client-labels",
            "the controller no longer watches its own server's clients since step 6.9 — their labels are not restored; nothing reads them",
        ),
    ];
    const CONFIG: &'static str = "controller-config";
    const ADMIN: &'static str = "admin-state";
    const PROXIES: &'static str = "agent-proxies";

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// Whether this host can lock the credentials at all: the lock is compiled in.
    pub fn passphrase_available() -> bool {
        true
    }

    fn files(&self) -> [SettingsFile; 5] {
        let paths = &self.app.paths;
        [
            SettingsFile { name: Self::CONFIG, path: paths.start_script.clone() },
            SettingsFile { name: Self::ADMIN, path: paths.admin_state_file.clone() },
            SettingsFile { name: Self::PROXIES, path: paths.agent_proxy_config_file.clone() },
            SettingsFile { name: "cloud-providers", path: paths.cloud_providers_file.clone() },
            SettingsFile { name: "model-catalog", path: paths.model_catalog_file.clone() },
        ]
    }

    fn excluded() -> Value {
        json!({
            "token-history.json": "measurements of what was served, not a setting",
            "monitor-history.json": "sampled load, not a setting",
            "incident-log.jsonl": "what happened here, not a setting",
            "agent-proxy-state.json": "live proxy bindings — rebuilt from the routes",
            "logs/": "logs",
        })
    }

    /// `(what may travel, the names of what did not)`.
    fn redacted(name: &str, data: Value) -> (Value, Vec<String>) {
        let Value::Object(mut out) = data else {
            return (data, Vec::new());
        };
        let mut hit = Vec::new();
        if name == Self::ADMIN {
            out.shift_remove("monitor");
            if Coerce::truthy(out.get("hfToken")) {
                out.insert("hfToken".to_string(), json!(Self::REDACTED));
                hit.push("admin-state.hfToken".to_string());
            }
        } else if name == Self::PROXIES {
            for route in out.get_mut("routes").and_then(Value::as_array_mut).into_iter().flatten() {
                if route.is_object() && Coerce::truthy(route.get("apiKey")) {
                    let port = route.get("port").map_or_else(|| "?".to_string(), |port| Coerce::str_of(Some(port)));
                    Coerce::put(route, "apiKey", json!(Self::REDACTED));
                    hit.push(format!("agent-proxies.routes[:{port}].apiKey"));
                }
            }
        }
        (Value::Object(out), hit)
    }

    fn read_json(path: &Path) -> Result<Option<Value>, AppError> {
        let raw = match std::fs::read(path) {
            Ok(raw) => raw,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(Self::unreadable(path, &error.to_string())),
        };
        serde_json::from_slice(&raw).map(Some).map_err(|error| Self::unreadable(path, &error.to_string()))
    }

    fn unreadable(path: &Path, words: &str) -> AppError {
        let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        AppError::new(format!("{name} is not readable as JSON: {words}"))
    }

    fn read_text(path: &Path) -> Option<String> {
        std::fs::read(path).ok().map(|raw| String::from_utf8_lossy(&raw).into_owned())
    }

    fn credentials(&self, include: bool, files: &mut Map<String, Value>) -> Result<Vec<String>, AppError> {
        if !include {
            files.insert(Self::SECRETS.to_string(), json!({"kind": "json", "content": null, "omitted": "secrets not requested"}));
            files
                .insert(Self::ACCOUNTS.to_string(), json!({"kind": "json", "content": null, "omitted": "secrets not requested"}));
            return Ok(Vec::new());
        }
        let mut carried = Vec::new();
        let secrets = Self::read_json(&self.app.paths.provider_secrets_file)?;
        if let Some(content) = secrets {
            files.insert(Self::SECRETS.to_string(), json!({"kind": "json", "content": content}));
            carried.push(Self::SECRETS.to_string());
        } else {
            files.insert(
                Self::SECRETS.to_string(),
                json!({"kind": "json", "content": null, "omitted": "not present on this host"}),
            );
        }
        files.insert(Self::ACCOUNTS.to_string(), json!({"kind": "json", "content": self.app.auth.document()?}));
        carried.push(Self::ACCOUNTS.to_string());
        Ok(carried)
    }

    /// The current settings as one object.
    pub fn export(&self, include_secrets: bool) -> Result<Value, AppError> {
        let mut files = Map::new();
        let mut redacted = Vec::new();
        for file in self.files() {
            if file.name == Self::CONFIG {
                files.insert(file.name.to_string(), json!({"kind": "text", "content": Self::read_text(&file.path)}));
                continue;
            }
            let mut data = Self::read_json(&file.path)?;
            if !include_secrets && (file.name == Self::ADMIN || file.name == Self::PROXIES) {
                data = data.map(|data| {
                    let (out, hits) = Self::redacted(file.name, data);
                    redacted.extend(hits);
                    out
                });
            }
            files.insert(file.name.to_string(), json!({"kind": "json", "content": data}));
        }
        let mut carried = self.credentials(include_secrets, &mut files)?;
        carried.sort();
        Ok(json!({
            "format": Self::FORMAT,
            "kind": Self::KIND,
            "exportedAt": self.app.now_whole(),
            "includesSecrets": include_secrets,
            "containsCredentials": carried,
            "redacted": redacted,
            "excluded": Self::excluded(),
            "files": files,
        }))
    }

    fn lock_key(passphrase: &str, salt: &[u8]) -> Vec<u8> {
        Scrypt::derive(passphrase.as_bytes(), salt, Self::SCRYPT_COST, Self::SCRYPT_SIZE, Self::SCRYPT_PARALLEL, Self::KEY_BYTES)
    }

    /// Locks ONLY the accounts and the cloud keys.
    pub fn encrypt_credentials(mut bundle: Value, passphrase: &str) -> Result<Value, AppError> {
        if passphrase.is_empty() {
            return Ok(bundle);
        }
        let no_random = || AppError::with_status("the system gives no random bytes", 500);
        for name in [Self::SECRETS, Self::ACCOUNTS] {
            let Some(entry) = bundle.get_mut("files").and_then(|files| files.get_mut(name)) else {
                continue;
            };
            let Some(content) = entry.get("content").filter(|content| !content.is_null()) else {
                continue;
            };
            let salt = Randomness::bytes(Self::SALT_BYTES).ok_or_else(no_random)?;
            let nonce = Randomness::bytes(Self::NONCE_BYTES).ok_or_else(no_random)?;
            let raw = PythonJson::spaced(content);
            let sealed = SealedBytes::seal(&Self::lock_key(passphrase, &salt), &nonce, raw.as_bytes())
                .ok_or_else(|| AppError::with_status("the credentials did not lock", 500))?;
            let locked = json!({
                "enc": Self::LOCK_MARK,
                "salt": Base64Std::encode(&salt),
                "nonce": Base64Std::encode(&nonce),
                "data": Base64Std::encode(&sealed),
            });
            Coerce::put(entry, "content", locked);
            Coerce::put(entry, "encrypted", json!(true));
        }
        Coerce::put(&mut bundle, "credentialsEncrypted", json!(true));
        Ok(bundle)
    }

    fn locked(content: Option<&Value>) -> bool {
        content.and_then(|content| content.get("enc")).is_some_and(|mark| Coerce::truthy(Some(mark)))
    }

    /// The content; `None` when it stays locked.
    fn opened(entry: &Value, passphrase: &str) -> Result<Option<Value>, AppError> {
        let content = entry.get("content");
        let Some(locked) = content.filter(|content| Coerce::text(content.get("enc")) == Self::LOCK_MARK) else {
            return Ok(content.cloned());
        };
        if passphrase.is_empty() {
            return Ok(None);
        }
        let wrong = || AppError::new("wrong passphrase for the credentials in this settings file");
        let part = |name: &str| Base64Std::decode(&Coerce::text(locked.get(name))).ok_or_else(wrong);
        let key = Self::lock_key(passphrase, &part("salt")?);
        let raw = SealedBytes::open(&key, &part("nonce")?, &part("data")?).ok_or_else(wrong)?;
        serde_json::from_slice(&raw).map(Some).map_err(|_| wrong())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn the_copy_before_an_import_is_nobody_else_s() {
        let folder = std::env::temp_dir().join(format!("settings-copy-{}", std::process::id()));
        let copy = CopyBeforeImport { directory: folder.join("settings-backups") };
        let path = copy.write("{}", 1_700_000_000.5).unwrap();
        let mode = |path: &Path| std::fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode(&copy.directory), 0o700);
        assert_eq!(mode(&path), 0o600);
        std::fs::remove_dir_all(&folder).unwrap();
    }
}
