//! Where the proxy listens and where its files are.

use std::path::PathBuf;

/// The proxy's settings from the environment, read once at the start.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProxyConfig {
    /// The address it listens on: `AGENT_PROXY_HOST`.
    pub host: String,
    /// Its port: `CARAVAN_RUST_ENTRY_PORT`.
    pub port: u16,
    /// `config/agent-proxies.json`.
    pub proxies_file: PathBuf,
    /// `config/cloud-providers.json`.
    pub cloud_file: PathBuf,
    /// `secrets/provider-secrets.json`: read for who has a credential.
    pub secrets_file: PathBuf,
    /// `state/model-catalog.json`: the windows the providers named.
    pub catalogue_file: PathBuf,
    /// `state/subscription-resets.json`: when each account's limits were last reset by hand.
    pub resets_file: PathBuf,
    /// `SSL_CERT_FILE`: the certificates a provider's is checked against, as OpenSSL reads it; `None`: the system's own.
    pub cert_file: Option<PathBuf>,
    /// `logs/proxy-events`.
    pub journal_folder: PathBuf,
    /// How many days back a journal's file stays: `AGENT_PROXY_LOG_RETENTION_DAYS`, 30 by default. `None`: all of them, when it says 0 or less.
    pub journal_keep_days: Option<i64>,
    /// `state/agent-proxy-state.json`: what the board reads of it.
    pub state_file: PathBuf,
    /// The commit it was built from, said at the build, for the board's word on what runs: this file comes apart from the image.
    pub commit: String,
    /// The file it runs from, watched for a new version; `None` when it cannot say.
    pub program: Option<PathBuf>,
    /// The process that keeps it: `CARAVAN_PROXY_KEEPER`, the controller's word. `None`: started by hand, with nobody to lose.
    pub keeper: Option<u32>,
}

impl ProxyConfig {
    const DEFAULT_HOST: &'static str = "0.0.0.0";
    const DEFAULT_KEPT_DAYS: i64 = 30;

    /// The settings `lookup` finds: the environment, or a test's table. Without a port it does not start: it has no default to guess, and
    /// an entry nobody asked for would listen.
    pub fn from_lookup(lookup: impl Fn(&str) -> Option<String>) -> Result<Self, String> {
        let said = |name: &str| lookup(name).map(|value| value.trim().to_string()).filter(|value| !value.is_empty());
        let Some(port) = said("CARAVAN_RUST_ENTRY_PORT") else {
            return Err("CARAVAN_RUST_ENTRY_PORT is not set: the proxy has no port to listen on".to_string());
        };
        let port = port
            .parse::<u16>()
            .ok()
            .filter(|port| *port > 0)
            .ok_or_else(|| format!("CARAVAN_RUST_ENTRY_PORT is not a port: {port}"))?;
        let Some(data) = said("CARAVAN_DATA_DIR").map(PathBuf::from) else {
            return Err("CARAVAN_DATA_DIR is not set: the proxy does not know where the caravan's files are".to_string());
        };
        let path = |name: &str, under: &str| said(name).map_or_else(|| data.join(under), PathBuf::from);
        let kept = said("AGENT_PROXY_LOG_RETENTION_DAYS").unwrap_or_else(|| Self::DEFAULT_KEPT_DAYS.to_string());
        let kept = kept.parse::<i64>().map_err(|_| format!("AGENT_PROXY_LOG_RETENTION_DAYS is no number: {kept}"))?;
        let keeper = said("CARAVAN_PROXY_KEEPER");
        let keeper =
            keeper.map(|pid| pid.parse::<u32>().map_err(|_| format!("CARAVAN_PROXY_KEEPER is no process: {pid}"))).transpose()?;
        Ok(Self {
            host: said("AGENT_PROXY_HOST").unwrap_or_else(|| Self::DEFAULT_HOST.to_string()),
            port,
            proxies_file: path("AGENT_PROXY_CONFIG_FILE", "config/agent-proxies.json"),
            cloud_file: path("CLOUD_PROVIDERS_FILE", "config/cloud-providers.json"),
            secrets_file: path("PROVIDER_SECRETS_FILE", "secrets/provider-secrets.json"),
            catalogue_file: path("MODEL_CATALOG_FILE", "state/model-catalog.json"),
            resets_file: path("CARAVAN_SUBSCRIPTION_RESETS_FILE", "state/subscription-resets.json"),
            cert_file: said("SSL_CERT_FILE").map(PathBuf::from),
            journal_folder: path("AGENT_PROXY_LOG_DIR", "logs/proxy-events"),
            journal_keep_days: Some(kept).filter(|days| *days > 0),
            state_file: path("AGENT_PROXY_STATE_FILE", "state/agent-proxy-state.json"),
            // absent-ok: "" is "not known" in the state file's `sourceCommit`, as in `StartRecord`: never a guess.
            commit: option_env!("CARAVAN_BUILD_COMMIT").unwrap_or_default().to_string(),
            program: None,
            keeper,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn config(pairs: &[(&str, &str)]) -> Result<ProxyConfig, String> {
        let table: BTreeMap<String, String> = pairs.iter().map(|(name, value)| (name.to_string(), value.to_string())).collect();
        ProxyConfig::from_lookup(|name| table.get(name).cloned())
    }

    #[test]
    fn the_days_of_the_journal_are_kept_and_trimmed() {
        let with = |pairs: &[(&str, &str)]| {
            let mut all = vec![("CARAVAN_RUST_ENTRY_PORT", "23998"), ("CARAVAN_DATA_DIR", "/data")];
            all.extend_from_slice(pairs);
            config(&all)
        };
        assert_eq!(with(&[]).unwrap().journal_keep_days, Some(30));
        assert_eq!(with(&[("AGENT_PROXY_LOG_RETENTION_DAYS", "7")]).unwrap().journal_keep_days, Some(7));
        assert_eq!(with(&[("AGENT_PROXY_LOG_RETENTION_DAYS", "0")]).unwrap().journal_keep_days, None);
        assert!(with(&[("AGENT_PROXY_LOG_RETENTION_DAYS", "x")]).unwrap_err().contains("no number"));
    }

    #[test]
    fn without_a_port_or_a_data_folder_it_says_so_and_does_not_start() {
        assert!(config(&[("CARAVAN_DATA_DIR", "/data")]).unwrap_err().contains("CARAVAN_RUST_ENTRY_PORT"));
        assert!(config(&[("CARAVAN_RUST_ENTRY_PORT", "x"), ("CARAVAN_DATA_DIR", "/data")]).unwrap_err().contains("not a port"));
        assert!(config(&[("CARAVAN_RUST_ENTRY_PORT", "0"), ("CARAVAN_DATA_DIR", "/data")]).unwrap_err().contains("not a port"));
        assert!(config(&[("CARAVAN_RUST_ENTRY_PORT", "23998")]).unwrap_err().contains("CARAVAN_DATA_DIR"));
    }

    #[test]
    fn its_files_stand_under_the_data_folder() {
        let config =
            config(&[("CARAVAN_RUST_ENTRY_PORT", "23998"), ("CARAVAN_DATA_DIR", "/data"), ("AGENT_PROXY_HOST", "127.0.0.1")])
                .unwrap();
        assert_eq!((config.host.as_str(), config.port), ("127.0.0.1", 23998));
        assert_eq!(config.proxies_file, PathBuf::from("/data/config/agent-proxies.json"));
        assert_eq!(config.cloud_file, PathBuf::from("/data/config/cloud-providers.json"));
        assert_eq!(config.secrets_file, PathBuf::from("/data/secrets/provider-secrets.json"));
        assert_eq!(config.catalogue_file, PathBuf::from("/data/state/model-catalog.json"));
        assert_eq!(config.resets_file, PathBuf::from("/data/state/subscription-resets.json"));
        assert_eq!(config.cert_file, None);
        assert_eq!(config.journal_folder, PathBuf::from("/data/logs/proxy-events"));
        assert_eq!(config.state_file, PathBuf::from("/data/state/agent-proxy-state.json"));
    }
    #[test]
    fn the_controller_names_the_process_that_keeps_it_and_a_proxy_started_by_hand_has_none() {
        let with = |keeper: &str| {
            config(&[("CARAVAN_RUST_ENTRY_PORT", "23998"), ("CARAVAN_DATA_DIR", "/data"), ("CARAVAN_PROXY_KEEPER", keeper)])
        };
        assert_eq!(with("4242").unwrap().keeper, Some(4242));
        assert_eq!(with("").unwrap().keeper, None);
        assert_eq!(config(&[("CARAVAN_RUST_ENTRY_PORT", "23998"), ("CARAVAN_DATA_DIR", "/data")]).unwrap().keeper, None);
        assert!(with("me").unwrap_err().contains("CARAVAN_PROXY_KEEPER"), "a word that is no process is not taken for nobody");
    }
}
