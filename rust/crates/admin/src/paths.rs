//! Where the controller's files are, its ports and its name, read from the environment once. Every other module takes them from here, as a parameter.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// The environment the paths are read from: a parameter, so that a test says what it holds.
#[derive(Debug, Clone, Default)]
pub struct Environment {
    vars: BTreeMap<String, String>,
    home: PathBuf,
}

impl Environment {
    /// The process's own.
    pub fn of_process() -> Self {
        let vars =
            std::env::vars_os().filter_map(|(key, value)| Some((key.into_string().ok()?, value.into_string().ok()?))).collect();
        // absent-ok: a process with no HOME has "/" as its home, as a container's user may.
        let home = std::env::var_os("HOME").map_or_else(|| PathBuf::from("/"), PathBuf::from);
        Self { vars, home }
    }

    /// A said one.
    pub fn of(vars: BTreeMap<String, String>, home: PathBuf) -> Self {
        Self { vars, home }
    }

    /// The value, if there is one.
    pub fn get(&self, name: &str) -> Option<&str> {
        self.vars.get(name).map(String::as_str)
    }

    /// The value when it is not empty: `os.environ.get(name) or …`.
    fn said(&self, name: &str) -> Option<&str> {
        self.get(name).filter(|value| !value.is_empty())
    }

    /// The home folder.
    pub fn home(&self) -> &Path {
        &self.home
    }

    /// `Path.expanduser`.
    pub fn expand(&self, text: &str) -> PathBuf {
        match text.strip_prefix("~/") {
            Some(rest) => self.home.join(rest),
            None if text == "~" => self.home.clone(),
            None => PathBuf::from(text),
        }
    }

    fn number(&self, name: &str, otherwise: i64) -> Result<i64, String> {
        match self.get(name) {
            Some(text) => text.trim().parse().map_err(|_| format!("{name} is not a number: {text}")),
            None => Ok(otherwise),
        }
    }
}

/// Which ports a family of the caravan lives in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PortRange {
    /// The first.
    pub base: i64,
    /// The last.
    pub upper: i64,
}

impl PortRange {
    /// Whether `port` is inside. The firewall lets the block in with ONE rule, made once by the operator: every port the caravan hands out lies inside it, and a new port outside it is refused: it would bind, listen and stay unreachable, and nothing would say why.
    pub fn holds(&self, port: i64) -> bool {
        (self.base..=self.upper).contains(&port)
    }
}

impl std::fmt::Display for PortRange {
    fn fmt(&self, out: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(out, "{}–{}", self.base, self.upper)
    }
}

/// The controller's id in stored state: a role name, not a hostname. Slot keys are persisted under it.
pub const CONTROLLER_HOST_ID: &str = "controller";

/// Which ids mean a machine.
pub struct HostIds;

impl HostIds {
    /// Ids that meant the controller in older stores and older cached frontends. An id that ever meant "the controller" may never come to mean one of its clients.
    pub const LEGACY: [&'static str; 1] = ["skynet"];

    /// Any spelling of the controller's id as the canonical one; client ids pass through untouched.
    pub fn canonical(host_id: &str) -> String {
        let id = rules::Coerce::strip(host_id);
        if Self::LEGACY.contains(&id) { CONTROLLER_HOST_ID.to_string() } else { id.to_string() }
    }

    /// True when a slot belongs to the controller rather than a client: asked instead of comparing to a literal.
    pub fn is_controller(host_id: &str) -> bool {
        Self::canonical(host_id) == CONTROLLER_HOST_ID
    }
}

/// Every path and port of the controller.
#[derive(Debug, Clone)]
pub struct AdminPaths {
    /// Where `static/` is: the repository, or the image's folder.
    pub project_root: PathBuf,
    /// Whether this runs in a container: no systemd, no host-only operations.
    pub is_container: bool,
    /// `CARAVAN_DATA_DIR`.
    pub data_dir: Option<PathBuf>,
    /// The address it listens on.
    pub host: String,
    /// The port it listens on.
    pub port: i64,
    /// `llama.cpp`'s folder.
    pub llama_home: PathBuf,
    /// The controller's own config block.
    pub start_script: PathBuf,
    /// The default models folder.
    pub default_models_dir: PathBuf,
    /// The legacy unit.
    pub service_name: String,
    /// The board's files.
    pub static_dir: PathBuf,
    /// Named launch-config backups for every node.
    pub server_backups_dir: PathBuf,
    /// The copy of every setting before a settings import.
    pub settings_backup_dir: PathBuf,
    /// `admin.json`.
    pub admin_state_file: PathBuf,
    /// The monitor's history.
    pub monitor_history_file: PathBuf,
    /// The incident log.
    pub incident_log_file: PathBuf,
    /// One manifest per model move.
    pub store_moves_dir: PathBuf,
    /// Header facts of GGUF files in a library.
    pub library_meta_file: PathBuf,
    /// What the headers under the models folder said.
    pub gguf_headers_file: PathBuf,
    /// Seconds between the monitor's samples.
    pub monitor_sample_interval: f64,
    /// The monitor's retention by default.
    pub monitor_retention_default: i64,
    /// The incidents' retention.
    pub incident_retention_seconds: i64,
    /// The proxy's state.
    pub agent_proxy_state_file: PathBuf,
    /// The proxy's document.
    pub agent_proxy_config_file: PathBuf,
    /// The cloud accounts.
    pub cloud_providers_file: PathBuf,
    /// The journal of subscription resets.
    pub subscription_resets_file: PathBuf,
    /// The cloud keys.
    pub provider_secrets_file: PathBuf,
    /// The model catalog.
    pub model_catalog_file: PathBuf,
    /// The token history.
    pub token_history_file: PathBuf,
    /// How many rows it keeps.
    pub token_history_max: i64,
    /// For how long.
    pub token_history_retention_sec: i64,
    /// The proxy's request log.
    pub agent_proxy_log_dir: PathBuf,
    /// The controller's unit.
    pub admin_service_name: String,
    /// A machine is online while its scout's last report is at most this old.
    pub host_report_ttl: i64,
    /// The prices' cache.
    pub model_pricing_cache: PathBuf,
    /// The benchmark scores' cache.
    pub aa_scores_cache: PathBuf,
    /// The controller's address as clients see it.
    pub topology_server_ip: String,
    /// The controller as the fleet reaches it by name; empty: the address and the port.
    pub topology_server_url: String,
    /// The cells' ports.
    pub cell_ports: PortRange,
    /// The proxy's ports.
    pub proxy_ports: PortRange,
    /// The benchmarks' folder.
    pub bench_cache_dir: PathBuf,
    /// The accounts database.
    pub auth_db: PathBuf,
}

impl AdminPaths {
    /// Where the prices come from.
    pub const MODEL_PRICING_URL: &'static str =
        "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json";
    /// How long they are good for.
    pub const MODEL_PRICING_TTL: i64 = 24 * 3600;

    /// All of them, from the environment. `project_root` is where the program finds `static/`.
    pub fn from_env(env: &Environment, project_root: PathBuf, is_container: bool) -> Result<Self, String> {
        let said_data = env.get("CARAVAN_DATA_DIR").filter(|text| !rules::Coerce::strip(text).is_empty());
        let data_dir = said_data.map(|text| env.expand(text));
        let default = |rel: &str, legacy: PathBuf| data_dir.as_ref().map_or(legacy, |dir| dir.join(rel));
        let chosen = |name: &str, rel: &str, legacy: PathBuf| env.said(name).map_or_else(|| default(rel, legacy), PathBuf::from);
        let home = env.home().to_path_buf();
        let llama_home = env.expand(env.get("LLAMA_HOME").unwrap_or(&home.join("llama.cpp").to_string_lossy()));
        let state = home.join(".local/state/llamacpp-easy-admin");
        let expanded = |path: PathBuf| env.expand(&path.to_string_lossy());
        let cell_base = env.number("CARAVAN_CELL_BASE_PORT", 22001)?;
        let cell_span = env.number("CARAVAN_CELL_PORT_SPAN", 998)?;
        let proxy_base = env.number("CARAVAN_PROXY_BASE_PORT", cell_base + 1000)?;
        let proxy_span = env.number("CARAVAN_PROXY_PORT_SPAN", 998)?;
        let monitor_interval = env.get("LLAMA_MONITOR_SAMPLE_INTERVAL").map_or(Ok(1.0), |text| {
            text.trim().parse().map_err(|_| format!("LLAMA_MONITOR_SAMPLE_INTERVAL is not a number: {text}"))
        })?;
        Ok(Self {
            is_container,
            host: env.get("LLAMACPP_ADMIN_HOST").unwrap_or("0.0.0.0").to_string(),
            port: env.number("LLAMACPP_ADMIN_PORT", 7990)?,
            start_script: expanded(chosen("LLAMA_START_SCRIPT", "config/start-server.sh", llama_home.join("start-server.sh"))),
            default_models_dir: expanded(chosen("LLAMA_MODELS_DIR", "models", llama_home.join("models"))),
            service_name: env.get("LLAMA_SERVICE_NAME").unwrap_or("llamacpp-current.service").to_string(),
            static_dir: project_root.join("static"),
            server_backups_dir: expanded(chosen(
                "LAMA_CARAVAN_SERVER_BACKUPS_DIR",
                "server-backups",
                project_root.join("var/server-backups"),
            )),
            settings_backup_dir: expanded(chosen(
                "CARAVAN_SETTINGS_BACKUPS",
                "settings-backups",
                project_root.join("var/settings-backups"),
            )),
            admin_state_file: chosen("LLAMA_ADMIN_STATE", "state/admin.json", state.join("admin.json")),
            monitor_history_file: chosen(
                "LLAMA_MONITOR_HISTORY",
                "state/monitor-history.json",
                state.join("monitor-history.json"),
            ),
            incident_log_file: chosen("LLAMA_INCIDENT_LOG", "state/incident-log.jsonl", state.join("incident-log.jsonl")),
            store_moves_dir: chosen("CARAVAN_STORE_MOVES_DIR", "state/store-moves", state.join("store-moves")),
            library_meta_file: chosen("CARAVAN_LIBRARY_META", "state/library-meta.json", state.join("library-meta.json")),
            gguf_headers_file: chosen("CARAVAN_GGUF_HEADERS", "state/gguf-headers.json", state.join("gguf-headers.json")),
            monitor_sample_interval: monitor_interval,
            monitor_retention_default: env.number("LLAMA_MONITOR_RETENTION_SECONDS", 600)?,
            incident_retention_seconds: env.number("LLAMA_INCIDENT_RETENTION_SECONDS", 30 * 24 * 60 * 60)?,
            agent_proxy_state_file: chosen(
                "AGENT_PROXY_STATE_FILE",
                "state/agent-proxy-state.json",
                project_root.join("agent-proxy-state.json"),
            ),
            agent_proxy_config_file: chosen(
                "AGENT_PROXY_CONFIG_FILE",
                "config/agent-proxies.json",
                project_root.join("agent-proxies.json"),
            ),
            cloud_providers_file: chosen(
                "CLOUD_PROVIDERS_FILE",
                "config/cloud-providers.json",
                project_root.join("cloud-providers.json"),
            ),
            subscription_resets_file: chosen(
                "CARAVAN_SUBSCRIPTION_RESETS_FILE",
                "state/subscription-resets.json",
                project_root.join("var/subscription-resets.json"),
            ),
            provider_secrets_file: chosen(
                "PROVIDER_SECRETS_FILE",
                "secrets/provider-secrets.json",
                home.join(".config/llamacpp-easy-admin/provider-secrets.json"),
            ),
            model_catalog_file: chosen("MODEL_CATALOG_FILE", "state/model-catalog.json", project_root.join("model-catalog.json")),
            token_history_file: chosen("TOKEN_HISTORY_FILE", "state/token-history.json", project_root.join("token-history.json")),
            token_history_max: env.number("TOKEN_HISTORY_MAX", 12000)?,
            token_history_retention_sec: env.number("TOKEN_HISTORY_RETENTION_SEC", 14 * 24 * 3600)?,
            agent_proxy_log_dir: chosen("AGENT_PROXY_LOG_DIR", "logs/proxy-events", project_root.join("logs/proxy-events")),
            admin_service_name: env.get("LLAMA_ADMIN_SERVICE_NAME").unwrap_or("lama-caravan.service").to_string(),
            host_report_ttl: env.number("CARAVAN_HOST_REPORT_TTL", 180)?,
            model_pricing_cache: default("logs/model-pricing-cache.json", project_root.join("logs/model-pricing-cache.json")),
            aa_scores_cache: default("logs/aa-scores-cache.json", project_root.join("logs/aa-scores-cache.json")),
            topology_server_ip: env.get("LLAMA_TOPOLOGY_SERVER_IP").unwrap_or("127.0.0.1").to_string(),
            // absent-ok: empty says "the address and the port".
            topology_server_url: rules::Coerce::strip(env.get("LLAMA_TOPOLOGY_SERVER_URL").unwrap_or_default()).to_string(),
            cell_ports: PortRange { base: cell_base, upper: cell_base + cell_span },
            proxy_ports: PortRange { base: proxy_base, upper: proxy_base + proxy_span },
            bench_cache_dir: default("state/bench-cache", project_root.join(".bench_cache")),
            auth_db: env.get("LLAMA_ADMIN_AUTH_DB").map_or_else(
                || chosen("LLAMA_ADMIN_STATE", "state/admin.json", state.join("admin.json")).with_file_name("auth.db"),
                PathBuf::from,
            ),
            llama_home,
            data_dir,
            project_root,
        })
    }

    /// Refuses a configuration that will corrupt the fleet later: a loud early death beats an allocator that quietly hands out the controller's own port.
    pub fn check_port_ranges(&self) -> Result<(), String> {
        let (cells, proxies, port) = (self.cell_ports, self.proxy_ports, self.port);
        let mut problems = Vec::new();
        if cells.base < 1024 {
            problems.push(format!("cell base {} is inside the privileged range (<1024)", cells.base));
        }
        if cells.upper - cells.base < 10 {
            problems.push(format!("cell span {} leaves fewer than 10 ports", cells.upper - cells.base));
        }
        if cells.upper >= 30000 {
            problems.push(format!("cell range ceiling {} reaches into the k8s NodePort / ephemeral neighbourhood (>=30000); listeners there lose bind races", cells.upper));
        }
        if cells.holds(port) {
            problems.push(format!("controller port {port} sits INSIDE the cell range {}-{} — the allocator would hand it out (this exact bug forced the 8090→7990 move)", cells.base, cells.upper));
        }
        if cells.holds(proxies.base) {
            problems.push(format!(
                "proxy base {} sits inside the cell range {}-{}; give proxies their own block",
                proxies.base, cells.base, cells.upper
            ));
        }
        if proxies.upper - proxies.base < 10 {
            problems.push(format!("proxy span {} leaves fewer than 10 ports", proxies.upper - proxies.base));
        }
        if proxies.upper >= 30000 {
            problems.push(format!("proxy range ceiling {} reaches into the k8s NodePort / ephemeral neighbourhood (>=30000); listeners there lose bind races", proxies.upper));
        }
        if proxies.holds(cells.base) {
            problems.push(format!(
                "cell base {} sits inside the proxy range {}-{}; give cells their own block",
                cells.base, proxies.base, proxies.upper
            ));
        }
        if proxies.holds(port) {
            problems.push(format!(
                "controller port {port} sits INSIDE the proxy range {}-{} — the allocator would hand it out",
                proxies.base, proxies.upper
            ));
        }
        if problems.is_empty() { Ok(()) } else { Err(format!("port range misconfiguration:\n  - {}", problems.join("\n  - "))) }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paths(vars: &[(&str, &str)]) -> AdminPaths {
        let vars = vars.iter().map(|(key, value)| ((*key).to_string(), (*value).to_string())).collect();
        AdminPaths::from_env(&Environment::of(vars, PathBuf::from("/home/me")), PathBuf::from("/repo"), false).unwrap()
    }

    #[test]
    fn a_data_folder_moves_every_mutable_default() {
        let with = paths(&[("CARAVAN_DATA_DIR", "/data")]);
        assert_eq!(with.admin_state_file, PathBuf::from("/data/state/admin.json"));
        assert_eq!(with.default_models_dir, PathBuf::from("/data/models"));
        assert_eq!(with.start_script, PathBuf::from("/data/config/start-server.sh"));
        let without = paths(&[]);
        assert_eq!(without.admin_state_file, PathBuf::from("/home/me/.local/state/llamacpp-easy-admin/admin.json"));
        assert_eq!(without.default_models_dir, PathBuf::from("/home/me/llama.cpp/models"));
        assert_eq!(without.agent_proxy_config_file, PathBuf::from("/repo/agent-proxies.json"));
    }

    #[test]
    fn a_file_of_its_own_wins_over_the_data_folder() {
        let with = paths(&[("CARAVAN_DATA_DIR", "/data"), ("LLAMA_ADMIN_STATE", "/own/admin.json")]);
        assert_eq!(with.admin_state_file, PathBuf::from("/own/admin.json"));
    }

    #[test]
    fn a_controller_inside_a_range_is_refused() {
        assert!(paths(&[]).check_port_ranges().is_ok());
        let inside = paths(&[("LLAMACPP_ADMIN_PORT", "22010")]).check_port_ranges().unwrap_err();
        assert!(inside.contains("sits INSIDE the cell range 22001-22999"), "{inside}");
    }

    #[test]
    fn the_old_name_of_the_controller_is_the_controller() {
        assert_eq!(HostIds::canonical(" skynet "), CONTROLLER_HOST_ID);
        assert!(HostIds::is_controller("controller"));
        assert!(!HostIds::is_controller("pi"));
        assert_eq!(HostIds::canonical("pi"), "pi");
    }
}
