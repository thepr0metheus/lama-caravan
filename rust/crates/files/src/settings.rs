//! The settings as the proxy reads them: `config/agent-proxies.json`, `config/cloud-providers.json`, and of the credentials and the
//! catalogue only what says which models can be called and how large they are; read again only when a file changes.

use rules::{ClientName, Coerce, Credentials, EntryModels, ModelCatalogue, Policy, Route};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::SystemTime;

/// The documents one reading is made of.
#[derive(Debug, Default)]
pub struct Documents<'a> {
    /// The proxies' file; `None` for one that does not read: there is no route, and nothing can be said of a key.
    pub proxies: Option<&'a Value>,
    /// The cloud file; `None` for one that does not read.
    pub cloud: Option<&'a Value>,
    /// Who has a credential.
    pub credentials: Credentials,
    /// What the providers named as their models' windows.
    pub catalogue: ModelCatalogue,
    /// The journal of a subscription's resets.
    pub resets: Option<&'a Value>,
}

/// One reading of the files. Shared by every request that came during it, and never changed.
#[derive(Debug, Default)]
pub struct Settings {
    /// The proxies' file does not read: no key can be judged, and a client hears that, not that its key is wrong.
    pub unread: bool,
    /// The routes that read, in the file's order; one that does not is no route.
    pub routes: Vec<Route>,
    /// The proxy's settings.
    pub policy: Policy,
    /// What the entry's clients call.
    pub models: EntryModels,
    /// The requests the board asked to stop: id to the reason it gave.
    pub stops: BTreeMap<String, String>,
    /// When each account's limits were last reset by hand: `SubscriptionResetJournal`, read by the row that judges it.
    pub resets: BTreeMap<String, f64>,
    /// The one name every client goes to the providers under, when the operator has set one.
    pub client_name: ClientName,
}

impl Settings {
    /// The last stops the file's reader keeps.
    const STOPS: usize = 100;

    /// The reading of `documents`.
    pub fn read(documents: Documents<'_>) -> Self {
        let Documents { proxies, cloud, credentials, catalogue, resets } = documents;
        let Some(proxies) = proxies else {
            return Self { unread: true, ..Self::default() };
        };
        let raw_routes = proxies.get("routes").and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        Self {
            unread: false,
            routes: raw_routes.iter().filter_map(Route::normalize).collect(),
            policy: Policy::read(proxies.get("policy")),
            models: EntryModels::read(proxies.get("routers"), cloud, &credentials, catalogue),
            stops: Self::stops(proxies.get("stopRequests")),
            resets: Self::resets(resets),
            client_name: ClientName::read(proxies.get("policy")),
        }
    }

    fn resets(raw: Option<&Value>) -> BTreeMap<String, f64> {
        let said = raw.and_then(|document| document.get("resets")).and_then(Value::as_object);
        said.into_iter().flatten().filter_map(|(account, at)| Some((account.clone(), at.as_f64()?))).collect()
    }

    fn stops(raw: Option<&Value>) -> BTreeMap<String, String> {
        let rows = raw.and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let last = rows.len().saturating_sub(Self::STOPS);
        rows.iter()
            .skip(last)
            .map(|row| (Coerce::text(row.get("id")), Coerce::text(row.get("reason"))))
            .filter(|(id, _)| !id.is_empty())
            .collect()
    }
}

/// What tells a file's change: the time and the size it has.
type Stamp = Option<(SystemTime, u64)>;

/// The reading in hand and the stamps it was made under.
struct Kept {
    stamps: Option<[Stamp; 5]>,
    settings: Arc<Settings>,
}

/// Where the settings are.
#[derive(Debug, Clone, Default)]
pub struct SettingsPaths {
    /// `config/agent-proxies.json`.
    pub proxies: PathBuf,
    /// `config/cloud-providers.json`.
    pub cloud: PathBuf,
    /// `secrets/provider-secrets.json`: read for who has a credential, and nothing of a credential is kept.
    pub secrets: PathBuf,
    /// `state/model-catalog.json`.
    pub catalogue: PathBuf,
    /// `state/subscription-resets.json`.
    pub resets: PathBuf,
}

/// The files, with their last reading. A request asks for the current settings, and a file is read only when its stamp moved: six
/// `stat` calls instead of a parse.
pub struct SettingsFiles {
    paths: SettingsPaths,
    kept: Mutex<Kept>,
}

impl SettingsFiles {
    /// The settings in these files.
    pub fn new(paths: SettingsPaths) -> Self {
        Self { paths, kept: Mutex::new(Kept { stamps: None, settings: Arc::new(Settings::default()) }) }
    }

    /// The settings as the files say them now.
    pub fn current(&self) -> Arc<Settings> {
        let paths = &self.paths;
        let stamps = [&paths.proxies, &paths.cloud, &paths.secrets, &paths.catalogue, &paths.resets].map(Self::stamp);
        let mut kept = self.kept.lock().unwrap_or_else(PoisonError::into_inner);
        if kept.stamps != Some(stamps) {
            let (proxies, cloud) = (Self::parsed(&paths.proxies), self.cloud_data());
            let resets = Self::parsed(&paths.resets);
            kept.settings = Arc::new(Settings::read(Documents {
                proxies: proxies.as_ref(),
                cloud: cloud.as_ref(),
                credentials: self.credentials(),
                catalogue: ModelCatalogue::read(Self::parsed(&paths.catalogue).as_ref()),
                resets: resets.as_ref(),
            }));
            kept.stamps = Some(stamps);
        }
        Arc::clone(&kept.settings)
    }

    fn stamp(path: &PathBuf) -> Stamp {
        let meta = fs::metadata(path).ok()?;
        Some((meta.modified().ok()?, meta.len()))
    }

    fn parsed(path: &PathBuf) -> Option<Value> {
        serde_json::from_slice(&fs::read(path).ok()?).ok()
    }

    /// The cloud file: none yet is an empty caravan, with nothing to doubt; one that does not read is a doubt.
    fn cloud_data(&self) -> Option<Value> {
        if !self.paths.cloud.exists() {
            return Some(Value::Object(serde_json::Map::new()));
        }
        Self::parsed(&self.paths.cloud)
    }

    /// Who has a credential: no document yet is nobody, with nothing to doubt, and one that does not read is a doubt, as in `CredentialVault`.
    fn credentials(&self) -> Credentials {
        if !self.paths.secrets.exists() {
            return Credentials::default();
        }
        Credentials::read(Self::parsed(&self.paths.secrets).as_ref())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rules::{ClientDeny, Pick};
    use serde_json::json;

    const CHAT: &str = "/v1/chat/completions";

    fn paths_in(folder: &std::path::Path) -> SettingsPaths {
        SettingsPaths {
            proxies: folder.join("agent-proxies.json"),
            cloud: folder.join("cloud-providers.json"),
            secrets: folder.join("provider-secrets.json"),
            catalogue: folder.join("model-catalog.json"),
            resets: folder.join("subscription-resets.json"),
        }
    }

    #[test]
    fn a_reading_says_what_the_file_says() {
        let proxies = json!({
            "routes": [{"label": "a", "id": "client-a", "apiKey": "k"}, {"label": "broken"}, {"id": "c1", "kind": "service"}],
            "policy": {"maxSlots": 2},
            "entry": {"port": 23999},
            "routers": [{"outputs": [{"id": "mm:a", "upstreamType": "machine", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 1, "copyPorts": [2]}]}],
            "stopRequests": [{"id": "r1", "reason": "preempted"}, {"reason": "no id"}, {"id": "r2"}],
        });
        let cloud = json!({});
        let settings = Settings::read(Documents { proxies: Some(&proxies), cloud: Some(&cloud), ..Documents::default() });
        assert!(!settings.unread);
        assert_eq!(settings.routes.len(), 1);
        assert_eq!(settings.policy.max_slots, 2);
        assert!(matches!(settings.models.for_request(&ClientDeny::default(), "m", CHAT), Pick::Pool(_)));
        assert_eq!(settings.stops.get("r1").map(String::as_str), Some("preempted"));
        assert_eq!(settings.stops.get("r2").map(String::as_str), Some(""));
        assert_eq!(settings.stops.len(), 2);
    }

    #[test]
    fn a_file_that_does_not_read_has_no_route() {
        let settings = Settings::read(Documents::default());
        assert!(settings.routes.is_empty());
        assert!(settings.unread);
    }

    #[test]
    fn no_cloud_file_is_nothing_to_doubt_and_a_broken_one_is_a_doubt() {
        let folder = std::env::temp_dir().join(format!("caravan-settings-cloud-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let paths = paths_in(&folder);
        let (proxies, cloud) = (paths.proxies.clone(), paths.cloud.clone());
        let output = r#"{"id": "mm:a", "upstreamType": "machine", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 1, "copyPorts": [2]}"#;
        fs::write(&proxies, format!(r#"{{"routers": [{{"outputs": [{output}]}}]}}"#)).unwrap();
        let files = SettingsFiles::new(paths);
        assert!(matches!(files.current().models.for_request(&ClientDeny::default(), "m", CHAT), Pick::Pool(_)));
        fs::write(&cloud, "not json").unwrap();
        assert_eq!(files.current().models.for_request(&ClientDeny::default(), "m", CHAT), Pick::Unsure);
        fs::write(&cloud, r#"{"pools": [{"id": "p", "name": "m", "steps": []}]}"#).unwrap();
        assert!(
            matches!(files.current().models.for_request(&ClientDeny::default(), "m", CHAT), Pick::Pool(pool) if pool.id == "p"),
            "a name that is a pool's is the pool's"
        );
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn who_has_a_credential_and_how_large_a_model_is_follow_their_files() {
        let folder = std::env::temp_dir().join(format!("caravan-settings-secrets-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let paths = paths_in(&folder);
        fs::write(&paths.proxies, r#"{"routes": [{"id": "c1", "kind": "consumer"}]}"#).unwrap();
        let cloud = r#"{"accounts": [{"id": "a"}], "addedModels": {"a": ["m"]}, "pools": [{"id": "p", "contextAuto": true, "steps": [{"id": "r", "accountId": "a", "model": "m"}]}]}"#;
        fs::write(&paths.cloud, cloud).unwrap();
        let (secrets, catalogue) = (paths.secrets.clone(), paths.catalogue.clone());
        let files = SettingsFiles::new(paths);
        let current = || files.current();
        let names = |settings: &Settings| -> Vec<String> {
            settings.models.models(&ClientDeny::default()).into_iter().map(|pool| pool.name.clone()).collect()
        };
        assert_eq!(names(&current()), ["p"], "no document of credentials: the account cannot be called");
        assert!(current().models.sure());
        fs::write(&secrets, r#"{"a": {"apiKey": "k"}}"#).unwrap();
        assert_eq!(names(&current()), ["p", "m"]);
        fs::write(&secrets, "not json").unwrap();
        assert!(!current().models.sure(), "a document that does not read is a doubt");
        fs::write(&secrets, r#"{"a": "k"}"#).unwrap();
        let window = |settings: &Settings| {
            let pool = settings.models.models(&ClientDeny::default()).into_iter().next().unwrap().clone();
            settings.models.window(&pool)
        };
        assert_eq!(window(&current()), None);
        fs::write(&catalogue, r#"{"accounts": {"a": {"models": [{"id": "m", "contextLength": 7}]}}}"#).unwrap();
        assert_eq!(window(&current()), Some(7));
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn a_reading_follows_the_file() {
        let folder = std::env::temp_dir().join(format!("caravan-settings-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let paths = paths_in(&folder);
        let proxies = paths.proxies.clone();
        fs::write(&proxies, r#"{"routes": [{"id": "c1"}]}"#).unwrap();
        let files = SettingsFiles::new(paths);
        assert_eq!(files.current().routes.len(), 1);
        let same = files.current();
        assert!(Arc::ptr_eq(&same, &files.current()), "no change, no new reading");
        fs::write(&proxies, r#"{"routes": [{"id": "c1"}, {"id": "c2"}]}"#).unwrap();
        assert_eq!(files.current().routes.len(), 2);
        fs::write(&proxies, "not json at all").unwrap();
        assert!(files.current().routes.is_empty());
        fs::remove_dir_all(&folder).unwrap();
    }
}
