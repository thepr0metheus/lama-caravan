//! The GPU driver of the controller's machine. What is installed and running is read by the machine's scout; what that means is decided here.

use super::machine_scout::MachineScout;
use crate::app::App;
use plumbing::Ticking;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Value, json};
use std::cmp::Ordering;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

/// The last status, for a moment.
#[derive(Default)]
pub struct DriverMemory {
    status: Mutex<Option<(f64, Value)>>,
}

/// The driver desk of this controller.
pub struct GpuDriver<'app> {
    app: &'app App,
}

impl<'app> GpuDriver<'app> {
    /// How long a look at the driver holds for a page that asks.
    pub const STATUS_TTL: f64 = 120.0;
    const FACTS_TIMEOUT: u64 = 90;
    const STATE_KEY: &'static str = "gpuDriverAuto";
    const INTERVAL_DEFAULT: i64 = 6 * 3600;

    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn interval(&self) -> i64 {
        // absent-ok: `int(os.environ.get(name) or 6 * 3600)`: the variable says nothing, or nothing a number.
        self.app
            .env
            .get("LLAMA_DRIVER_WATCH_SECONDS")
            .and_then(|said| Coerce::strip(said).parse().ok())
            .filter(|seconds| *seconds != 0)
            .unwrap_or(Self::INTERVAL_DEFAULT)
    }

    /// A version as a list of numbers: "610.43.02" beats "595.84" part by part, not as a string.
    fn version_key(text: &str) -> Vec<u64> {
        let runs = text.split(|letter: char| !letter.is_ascii_digit()).filter(|run| !run.is_empty());
        let numbers: Vec<u64> = runs.filter_map(|run| run.parse().ok()).collect();
        if numbers.is_empty() { vec![0] } else { numbers }
    }

    /// Just the driver's own version, without the Debian revision.
    fn driver_key(text: &str) -> Vec<u64> {
        Self::version_key(text.split('-').next().unwrap_or(text))
    }

    /// The newest candidate of the same flavor as what is installed.
    fn pick_newest<'rows>(available: &'rows [Value], installed_top: Option<&Value>) -> Option<&'rows Value> {
        let top = Self::version_key(&Coerce::text(available.first()?.get("version")));
        let same: Vec<&Value> =
            available.iter().filter(|row| Self::version_key(&Coerce::text(row.get("version"))) == top).collect();
        let want_open = installed_top.is_none_or(|installed| Coerce::text(installed.get("package")).ends_with("-open"));
        same.iter().find(|row| Coerce::text(row.get("package")).ends_with("-open") == want_open).or_else(|| same.first()).copied()
    }

    fn forget_status(&self) {
        *self.app.driver.status.lock().unwrap_or_else(PoisonError::into_inner) = None;
    }

    /// What is installed, running and available, and whether a reboot is needed.
    pub fn status(&self, ttl: f64) -> Result<Value, AppError> {
        let now = self.app.now();
        {
            let held = self.app.driver.status.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some((_, data)) = held.as_ref().filter(|(at, _)| now - *at < ttl) {
                return Ok(data.clone());
            }
        }
        let scout = MachineScout::of(self.app);
        let facts = scout.read("/api/host/driver", Self::FACTS_TIMEOUT);
        if !Coerce::truthy(facts.get("ok")) {
            let said = Coerce::text(facts.get("error"));
            let reason = if said.is_empty() { "its scout gave no answer".to_string() } else { said };
            let status = if reason == MachineScout::NO_SCOUT { 409 } else { 502 };
            return Err(AppError::with_status(
                format!("the driver of the controller's machine cannot be read: {reason}"),
                status,
            ));
        }
        let mut data = Self::decided(&facts);
        Coerce::put(&mut data, "hostId", json!(scout.host_id()));
        Coerce::put(&mut data, "auto", self.auto_settings());
        Coerce::put(&mut data, "checkedAt", json!(now as i64));
        *self.app.driver.status.lock().unwrap_or_else(PoisonError::into_inner) = Some((now, data.clone()));
        Ok(data)
    }

    /// What the scout's facts mean.
    fn decided(facts: &Value) -> Value {
        let running = Coerce::text(facts.get("running"));
        let mut running_error = Coerce::text(facts.get("runningError"));
        let list = |key: &str| Coerce::list(facts.get(key));
        let (installed, available) = (list("installed"), list("available"));
        let top = installed.first();
        let newest = Self::pick_newest(&available, top);
        let version = |row: &Value| Coerce::text(row.get("version"));
        let update = newest.is_some_and(|newest| {
            top.is_none_or(|top| Self::version_key(&version(newest)).cmp(&Self::version_key(&version(top))) == Ordering::Greater)
        });
        let mut reboot =
            top.is_some_and(|top| !running.is_empty() && Self::driver_key(&version(top)) > Self::driver_key(&running));
        if top.is_some() && running.is_empty() && !running_error.is_empty() {
            reboot = true;
        }
        let secure_boot = Coerce::truthy(facts.get("secureBoot"));
        let signed = Coerce::text(facts.get("signedModules"));
        let signed_ok = !signed.is_empty() && Coerce::truthy(facts.get("signedModulesInstalled"));
        let rejected = secure_boot && top.is_some() && running.is_empty() && !Coerce::truthy(facts.get("moduleLoaded"));
        let os_reboot = Coerce::truthy(facts.get("rebootPending"));
        let os_packages = if os_reboot { list("rebootPendingPackages") } else { Vec::new() };
        if rejected {
            reboot = false;
            let mut why = "Secure Boot rejected the unsigned kernel module".to_string();
            if !signed.is_empty() && !signed_ok {
                why.push_str(&format!("; install {signed}"));
            }
            running_error = if running_error.is_empty() { why } else { format!("{running_error} — {why}") };
        }
        let shown: Vec<&Value> = available.iter().take(8).collect();
        json!({
            "ok": true, "hostId": null, "running": running, "runningError": running_error, "installed": top, "installedAll": installed,
            "available": shown, "newest": newest, "updateAvailable": update, "rebootForDriver": reboot, "rebootPending": os_reboot,
            "rebootPendingPackages": os_packages, "rebootRequired": reboot || os_reboot, "auto": null, "secureBoot": secure_boot,
            "signedModules": signed, "signedModulesInstalled": signed_ok, "moduleRejected": rejected,
        })
    }

    /// The watcher's settings.
    pub fn auto_settings(&self) -> Value {
        let saved = self
            .app
            .admin
            .read(|doc| doc.get(Self::STATE_KEY).filter(|said| said.is_object()).cloned())
            .unwrap_or_else(|| json!({}));
        json!({
            "check": Coerce::truthy(saved.get("check")),
            "install": Coerce::truthy(saved.get("install")),
            // absent-ok: `int(saved.get("lastCheckAt") or 0)`: a check never made is one long ago.
            "lastCheckAt": Coerce::whole(saved.get("lastCheckAt")),
            "lastInstall": saved.get("lastInstall").filter(|said| Coerce::truthy(Some(*said))),
        })
    }

    /// Both checkboxes set together: an install needs a check.
    pub fn set_auto_settings(&self, payload: &Value) -> Value {
        let install = Coerce::truthy(payload.get("install"));
        let check = Coerce::truthy(payload.get("check")) || install;
        self.app.admin.saving(|doc| {
            let mut saved = doc.get(Self::STATE_KEY).filter(|said| said.is_object()).cloned().unwrap_or_else(|| json!({}));
            Coerce::put(&mut saved, "check", json!(check));
            Coerce::put(&mut saved, "install", json!(install));
            doc.insert(Self::STATE_KEY.to_string(), saved);
        });
        self.forget_status();
        self.auto_settings()
    }

    fn is_package(name: &str) -> bool {
        let Some(rest) = name.strip_prefix("nvidia-driver-") else {
            return false;
        };
        let digits = rest.strip_suffix("-open").unwrap_or(rest);
        (2..=4).contains(&digits.len()) && digits.chars().all(|digit| digit.is_ascii_digit())
    }

    /// The named driver installed on the controller's machine, through its scout.
    pub fn update(&self, package: &str) -> Result<Value, AppError> {
        let name = Coerce::strip(package);
        if !Self::is_package(name) {
            return Err(AppError::new(format!("not a driver package: {}", PyRepr::of(name))));
        }
        self.forget_status();
        MachineScout::of(self.app).post("/api/host/driver/install", &json!({"package": name}), 30)
    }

    /// The install job on the controller's machine, as its scout tells it.
    pub fn update_status(&self) -> Value {
        MachineScout::of(self.app).read("/api/host/driver/install-status", 10)
    }

    fn remember(&self, key: &str, said: Value) {
        self.app.admin.saving(|doc| {
            let mut saved = doc.get(Self::STATE_KEY).filter(|row| row.is_object()).cloned().unwrap_or_else(|| json!({}));
            Coerce::put(&mut saved, key, said);
            doc.insert(Self::STATE_KEY.to_string(), saved);
        });
    }

    /// One watcher pass.
    pub fn watch_pass(&self) -> Result<Value, AppError> {
        let auto = self.auto_settings();
        if !Coerce::truthy(auto.get("check")) {
            return Ok(json!({"checked": false, "installed": null, "reason": "auto-check off"}));
        }
        self.forget_status();
        let status = self.status(0.0)?;
        let now = self.app.now_whole();
        self.remember("lastCheckAt", json!(now));
        let update = Coerce::truthy(status.get("updateAvailable"));
        let newest = status.get("newest").filter(|said| Coerce::truthy(Some(*said)));
        let Some(newest) = newest.filter(|_| Coerce::truthy(auto.get("install")) && update) else {
            let reason = if update { "auto-install off" } else { "up to date" };
            return Ok(json!({"checked": true, "installed": null, "reason": reason}));
        };
        let name = Coerce::text(newest.get("package"));
        if let Err(error) = self.update(&name) {
            return Ok(json!({"checked": true, "installed": null, "reason": error.message}));
        }
        self.remember("lastInstall", json!({"package": name, "version": newest.get("version"), "at": now}));
        Ok(json!({"checked": true, "installed": name, "reason": "started"}))
    }

    /// Seconds to wait before the next pass.
    fn wait_seconds(&self, now: i64, last: i64) -> i64 {
        let interval = self.interval();
        if last == 0 {
            return interval;
        }
        (interval - (now - last)).clamp(0, interval)
    }

    /// The watcher's thread: the time since the last check counts across restarts, or a controller redeployed daily would never check.
    pub fn start_thread(app: &Arc<App>) -> std::io::Result<()> {
        let app = Arc::clone(app);
        std::thread::Builder::new().name("gpu-driver-watch".to_string()).spawn(move || {
            let desk = GpuDriver::of(&app);
            // absent-ok: a check never made is no reason to hurry: `wait_seconds` reads 0 as that.
            let last = Coerce::i64_or_zero(desk.auto_settings().get("lastCheckAt"));
            let mut wait = desk.wait_seconds(app.now_whole(), last);
            loop {
                if wait > 0 {
                    std::thread::sleep(Duration::from_secs(wait.unsigned_abs()));
                }
                // A pass that fails says so on the next read of the panel.
                Ticking::once("gpu-driver-watch", || drop(desk.watch_pass()));
                wait = desk.interval();
            }
        })?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_version_compares_part_by_part() {
        assert!(GpuDriver::version_key("610.43.02") > GpuDriver::version_key("595.84"));
        assert!(GpuDriver::driver_key("610.43.02-0ubuntu1") == GpuDriver::driver_key("610.43.02"));
        assert_eq!(GpuDriver::version_key("x"), vec![0]);
    }

    #[test]
    fn the_newest_of_the_same_flavor_is_offered() {
        let available = [
            json!({"version": "600", "package": "nvidia-driver-600"}),
            json!({"version": "600", "package": "nvidia-driver-600-open"}),
            json!({"version": "590", "package": "nvidia-driver-590"}),
        ];
        let open = json!({"package": "nvidia-driver-590-open"});
        let closed = json!({"package": "nvidia-driver-590"});
        assert_eq!(GpuDriver::pick_newest(&available, Some(&open)).unwrap()["package"], "nvidia-driver-600-open");
        assert_eq!(GpuDriver::pick_newest(&available, Some(&closed)).unwrap()["package"], "nvidia-driver-600");
        assert_eq!(GpuDriver::pick_newest(&available, None).unwrap()["package"], "nvidia-driver-600-open");
        assert!(GpuDriver::pick_newest(&[], None).is_none());
    }

    #[test]
    fn secure_boot_is_said_as_itself_not_as_a_reboot() {
        let facts = json!({"running": "", "runningError": "no module", "installed": [{"version": "600", "package": "p"}], "available": [], "secureBoot": true, "signedModules": "signed-pkg"});
        let decided = GpuDriver::decided(&facts);
        assert_eq!(decided["moduleRejected"], true);
        assert_eq!(decided["rebootForDriver"], false);
        assert_eq!(decided["runningError"], "no module — Secure Boot rejected the unsigned kernel module; install signed-pkg");
    }

    #[test]
    fn a_reboot_is_needed_when_the_installed_driver_is_newer() {
        let facts = json!({"running": "590.1", "installed": [{"version": "600.2-1", "package": "p"}], "available": [{"version": "610", "package": "q"}]});
        let decided = GpuDriver::decided(&facts);
        assert_eq!(decided["rebootForDriver"], true);
        assert_eq!(decided["updateAvailable"], true);
        assert_eq!(decided["rebootRequired"], true);
    }

    #[test]
    fn a_package_is_a_driver_s() {
        assert!(GpuDriver::is_package("nvidia-driver-595"));
        assert!(GpuDriver::is_package("nvidia-driver-595-open"));
        assert!(!GpuDriver::is_package("nvidia-driver-5"));
        assert!(!GpuDriver::is_package("nvidia-driver-595; rm"));
    }
}
