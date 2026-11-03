//! This machine's NVIDIA driver packages as `apt` sees them, and installing one. The scout reports the facts and runs the install; the controller decides what to install and when. RUNNING is the version in the kernel, INSTALLED the one in the packages: right after an update they differ until a reboot. Names reach `apt` only through allowlists: the controller checks the name too, and the scout checks it again here: it arrives over HTTP. Under Secure Boot the install carries the signed modules for the running kernel and takes the DKMS build out of their way, or the kernel refuses the module after the reboot (2026-09-07).

use crate::commands::Commands;
use crate::driver::DriverFacts;
use crate::errors::{AppError, PyRepr};
use crate::runtimes::job::BackgroundJob;
use os::Account;
use os::clock::Clock;
use regex::Regex;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

/// One package and its version.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Row {
    package: String,
    version: String,
}

impl Row {
    fn json(&self) -> Value {
        json!({"package": self.package, "version": self.version})
    }
}

/// What `apt` says.
pub struct DriverPackages {
    facts: Arc<DriverFacts>,
    commands: Arc<dyn Commands>,
    clock: Arc<dyn Clock>,
    package_name: Regex,
    modules_name: Regex,
    version: Regex,
}

impl DriverPackages {
    const REBOOT_MARKER: &'static str = "/var/run/reboot-required";
    const OS_RELEASE: &'static str = "/etc/os-release";
    const PROC_MODULES: &'static str = "/proc/modules";

    /// The packages of this machine. The patterns are this program's own text.
    pub fn new(facts: Arc<DriverFacts>, commands: Arc<dyn Commands>, clock: Arc<dyn Clock>) -> Result<Self, regex::Error> {
        Ok(Self {
            facts,
            commands,
            clock,
            package_name: Regex::new(r"^nvidia-driver-(\d{2,4})(-open)?$")?,
            modules_name: Regex::new(r"^linux-modules-nvidia-(\d{2,4})(-open)?-[a-z0-9.\-]+$")?,
            version: Regex::new(r"^\d+(\.\d+)+$")?,
        })
    }

    /// (exit code 0, stdout and stderr): the words of a failure are kept, since `nvidia-smi` says why it cannot answer in them.
    fn text(&self, argv: &[&str], seconds: u64) -> String {
        match self.commands.run(argv, Duration::from_secs(seconds)) {
            Ok(ran) => format!("{}\n{}", ran.stdout, ran.stderr).trim().to_string(),
            Err(no_answer) => no_answer.words(argv.first().copied().unwrap_or("the tool")),
        }
    }

    fn by_version(mut rows: Vec<Row>) -> Vec<Row> {
        rows.sort_by_key(|row| std::cmp::Reverse(DriverFacts::version_key(&row.version)));
        rows
    }

    /// (version in the kernel, why there is none). Right after an install `nvidia-smi` prints "Failed to initialize NVML: Driver/library version mismatch" where a number is expected: a number has to look like one.
    fn running(&self) -> (String, String) {
        let text = self.text(&["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], 8);
        if let Some(line) = text.lines().map(str::trim).find(|line| self.version.is_match(line)) {
            return (line.to_string(), String::new());
        }
        (String::new(), Coerce::first_letters(&text.split_whitespace().collect::<Vec<_>>().join(" "), 200).to_string())
    }

    /// Installed packages matching `pattern`. `dpkg`'s status is three words and the third carries the value: a removed package says not-installed.
    fn dpkg(&self, pattern: &str) -> Vec<Row> {
        let text = self.text(&["dpkg-query", "-W", "-f=${Package} ${Version} ${Status}\\n", pattern], 10);
        text.lines()
            .filter_map(|line| {
                let parts: Vec<&str> = line.split_whitespace().collect();
                match parts.as_slice() {
                    [package, version, _, _, "installed", ..] => {
                        Some(Row { package: (*package).to_string(), version: (*version).to_string() })
                    }
                    _ => None,
                }
            })
            .collect()
    }

    fn installed(&self) -> Vec<Row> {
        Self::by_version(
            self.dpkg("nvidia-driver-*").into_iter().filter(|row| self.package_name.is_match(&row.package)).collect(),
        )
    }

    fn package_installed(&self, name: &str) -> bool {
        !name.is_empty() && self.dpkg(name).iter().any(|row| row.package == name)
    }

    /// `apt-cache policy`'s CANDIDATE versions: what an install would take.
    fn policy(&self, names: &[String]) -> Vec<Row> {
        if names.is_empty() {
            return Vec::new();
        }
        let mut argv = vec!["apt-cache", "policy"];
        argv.extend(names.iter().map(String::as_str));
        let text = self.text(&argv, 25);
        let mut found = Vec::new();
        let mut current = String::new();
        for line in text.lines() {
            if !line.starts_with(' ') && line.trim_end().ends_with(':') {
                current = line.trim_end().trim_end_matches(':').trim().to_string();
            } else if !current.is_empty() && line.trim().starts_with("Candidate:") {
                let version = line.split_once(':').map_or("", |(_, version)| version.trim());
                if !version.is_empty() && version != "(none)" {
                    found.push(Row { package: current.clone(), version: version.to_string() });
                }
                current.clear();
            }
        }
        found
    }

    fn available(&self) -> Vec<Row> {
        let text = self.text(&["apt-cache", "--names-only", "search", "^nvidia-driver-[0-9]+(-open)?$"], 20);
        let names: Vec<String> = text
            .lines()
            .map(|line| line.split(" - ").next().unwrap_or(line).trim().to_string())
            .filter(|name| self.package_name.is_match(name))
            .collect();
        Self::by_version(self.policy(&names))
    }

    fn module_loaded() -> bool {
        fs::read(Self::PROC_MODULES)
            .is_ok_and(|raw| String::from_utf8_lossy(&raw).lines().any(|line| line.split(' ').next() == Some("nvidia")))
    }

    fn version_id() -> String {
        // absent-ok: a system that names no version has no HWE package to look for.
        let raw = fs::read(Self::OS_RELEASE).unwrap_or_default();
        let text = String::from_utf8_lossy(&raw);
        text.lines()
            .find_map(|line| line.strip_prefix("VERSION_ID="))
            .map_or_else(String::new, |said| said.trim().trim_matches('"').to_string())
    }

    /// `^(\d+\.\d+\.\d+-\d+)`: the kernel's series.
    fn series_of(release: &str) -> &str {
        let mut parts = 0;
        for (at, letter) in release.char_indices() {
            match letter {
                '.' | '-' if parts < 3 => parts += 1,
                '0'..='9' => {}
                _ if parts == 3 => return release.get(..at).unwrap_or_default(),
                _ => return "",
            }
        }
        if parts == 3 { release } else { "" }
    }

    /// The signed-modules metapackage for the RUNNING kernel, or "". Two candidates (HWE and GA) and the exact-kernel name last; the pick is the one whose candidate version starts with the running kernel's series: another series would drag in yet another kernel.
    fn signed_modules(&self, driver_package: &str) -> String {
        let Some(found) = self.package_name.captures(Coerce::strip(driver_package)) else {
            return String::new();
        };
        let word = |at: usize| found.get(at).map_or("", |word| word.as_str());
        let base = format!("linux-modules-nvidia-{}{}", word(1), word(2));
        let release = Account::kernel_release();
        let series = Self::series_of(&release);
        let version_id = Self::version_id();
        let mut names = Vec::new();
        if !version_id.is_empty() {
            names.push(format!("{base}-generic-hwe-{version_id}"));
        }
        names.extend([format!("{base}-generic"), format!("{base}-{release}")]);
        let versions: BTreeMap<String, String> = self.policy(&names).into_iter().map(|row| (row.package, row.version)).collect();
        names
            .into_iter()
            .find(|name| {
                versions
                    .get(name)
                    .is_some_and(|version| !version.is_empty() && (series.is_empty() || version.starts_with(series)))
            })
            // absent-ok: "" says no package fits, as the callers read it.
            .unwrap_or_default()
    }

    /// The OS's own reboot request and its package list (empty when unknown).
    fn reboot_pending() -> (bool, Vec<String>) {
        if !Path::new(Self::REBOOT_MARKER).exists() {
            return (false, Vec::new());
        }
        let Ok(raw) = fs::read(format!("{}.pkgs", Self::REBOOT_MARKER)) else {
            return (true, Vec::new());
        };
        (true, String::from_utf8_lossy(&raw).lines().map(str::trim).filter(|line| !line.is_empty()).map(str::to_string).collect())
    }

    /// Everything the controller's driver panel decides from, read once.
    pub fn facts(&self) -> Value {
        let (running, running_error) = self.running();
        let installed = self.installed();
        let signed = installed.first().map_or_else(String::new, |row| self.signed_modules(&row.package));
        let (reboot, reboot_packages) = Self::reboot_pending();
        let rows = |list: &[Row]| list.iter().map(Row::json).collect::<Vec<Value>>();
        json!({
            "ok": true,
            "running": running,
            "runningError": running_error,
            "installed": rows(&installed),
            "available": rows(&self.available()),
            "secureBoot": self.facts.secure_boot(),
            "moduleLoaded": Self::module_loaded(),
            "signedModules": signed,
            "signedModulesInstalled": !signed.is_empty() && self.package_installed(&signed),
            "rebootPending": reboot,
            "rebootPendingPackages": reboot_packages,
            "kernel": Account::kernel_release(),
            "checkedAt": self.clock.epoch() as i64,
        })
    }

    /// The install, checked: an allowlisted name `apt` offers, and under Secure Boot its signed modules with the DKMS build moved out of their way (a DKMS module in `updates/dkms/` ranks above the signed one).
    fn install_command(&self, package: &str) -> Result<Vec<String>, AppError> {
        let name = Coerce::strip(package).to_string();
        if !self.package_name.is_match(&name) {
            return Err(AppError::new(format!("not a driver package: {}", PyRepr::of(&name))));
        }
        if !self.available().iter().any(|row| row.package == name) {
            return Err(AppError::with_status(format!("no such driver package in apt: {name}"), 404));
        }
        let modules = if self.facts.secure_boot() == Some(true) { self.signed_modules(&name) } else { String::new() };
        if !modules.is_empty() && !self.modules_name.is_match(&modules) {
            return Err(AppError::with_status(format!("not a modules package: {}", PyRepr::of(&modules)), 500));
        }
        let apt = ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "--no-install-recommends", name.as_str()];
        if modules.is_empty() {
            let mut argv = vec!["sudo".to_string(), "-n".to_string()];
            argv.extend(apt.iter().map(|word| (*word).to_string()));
            return Ok(argv);
        }
        let kernel = Account::kernel_release();
        let script = format!(
            "{} {modules} && for m in $(dkms status 2>/dev/null | sed -n 's/^\\(nvidia\\/[^,: ]*\\).*/\\1/p' | sort -u); do dkms remove \"$m\" -k {kernel} >/dev/null 2>&1 || true; done; depmod -a {kernel}",
            apt.join(" ")
        );
        Ok(vec!["sudo".to_string(), "-n".to_string(), "bash".to_string(), "-c".to_string(), script])
    }

    /// Starts the install as the machine's background job; its status right away.
    pub fn install(&self, package: &str, job: &BackgroundJob) -> Result<Value, AppError> {
        let argv = self.install_command(package)?;
        job.start(argv, &format!("driver:{}", Coerce::strip(package)), std::env::vars().collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_series_is_the_kernels_first_four_numbers() {
        assert_eq!(DriverPackages::series_of("6.8.0-45-generic"), "6.8.0-45");
        assert_eq!(DriverPackages::series_of("6.8.0-45"), "6.8.0-45");
        assert_eq!(DriverPackages::series_of("6.8"), "");
        assert_eq!(DriverPackages::series_of("custom"), "");
    }
}
