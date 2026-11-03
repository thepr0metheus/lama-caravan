//! What decides whether this machine's NVIDIA card comes back after a reboot. 2026-09-26: the automatic updates installed a kernel a day before a reboot, held back the Canonical-signed NVIDIA modules it needed, and the machine came up with Secure Boot refusing the unsigned build: no card until someone fixed it by hand. Nothing had said so before the reboot. The scout reports the facts that would have; the controller draws the conclusion.

use crate::machine::Machine;
use os::Account;
use os::clock::Clock;
use regex::Regex;
use serde_json::{Value, json};
use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex, PoisonError};

/// This machine's NVIDIA driver as its next boot will meet it: Secure Boot, the kernel running and the one that boots next, the driver version loaded and the one installed, and the module the next kernel would load. Cached for a minute: these change when packages are installed, not from one poll to the next. `null` where the question does not arise: not Linux, or no NVIDIA driver anywhere. A fact that cannot be read is `null`, never a guess.
pub struct DriverFacts {
    machine: Arc<Machine>,
    clock: Arc<dyn Clock>,
    kernel_file: Regex,
    loaded: Regex,
    common_name: Regex,
    library: Regex,
    kept: Mutex<Option<(f64, Value)>>,
}

impl DriverFacts {
    const TTL: f64 = 60.0;
    /// The kernels a boot can pick; the newest is what GRUB boots by default.
    const BOOT: &'static str = "/boot";
    /// What the loaded module says of itself.
    const PROC_VERSION: &'static str = "/proc/driver/nvidia/version";
    /// Where the userspace library lives, its version in its file name.
    const LIB_DIRS: [&'static str; 3] = ["/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib"];
    /// The key DKMS signs its builds with on Ubuntu: trusted only if it was enrolled at the console; a build signed by an unenrolled key is refused under Secure Boot just like an unsigned one.
    const DKMS_KEY: &'static str = "/var/lib/shim-signed/mok/MOK.der";
    /// The firmware's own word on Secure Boot: four bytes of attributes, then 1 (on) or 0 (off), readable by anyone.
    const EFI_DIR: &'static str = "/sys/firmware/efi";
    const SECURE_BOOT_VAR: &'static str = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c";

    /// The facts of this machine. The patterns are this program's own text.
    pub fn new(machine: Arc<Machine>, clock: Arc<dyn Clock>) -> Result<Self, regex::Error> {
        Ok(Self {
            machine,
            clock,
            kernel_file: Regex::new(r"^vmlinuz-(\d[\w.+-]*)$")?,
            loaded: Regex::new(r"Kernel Module(?:\s+for\s+\S+)?\s+(\d+(?:\.\d+)+)")?,
            common_name: Regex::new(r"CN\s*=\s*([^,/\n]+)")?,
            library: Regex::new(r"^libnvidia-ml\.so\.(\d+(?:\.\d+)+)$")?,
            kept: Mutex::new(None),
        })
    }

    /// The facts, at most a minute old.
    pub fn facts(&self) -> Value {
        let now = self.clock.monotonic();
        let mut kept = self.kept.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some((_, facts)) = kept.as_ref().filter(|(at, _)| now - *at < Self::TTL) {
            return facts.clone();
        }
        let facts = self.read();
        *kept = Some((now, facts.clone()));
        facts
    }

    fn read(&self) -> Value {
        if !cfg!(target_os = "linux") {
            return Value::Null;
        }
        let running = Account::kernel_release();
        let following = self.next_kernel();
        let loaded = self.loaded_version();
        let installed = self.installed_version();
        let module = following.as_deref().and_then(|kernel| self.module(kernel));
        if loaded.is_none() && installed.is_none() && module.is_none() {
            return Value::Null;
        }
        json!({
            "secureBoot": self.secure_boot(),
            "kernelRunning": Some(running).filter(|kernel| !kernel.is_empty()),
            "kernelNext": following,
            "loaded": loaded,
            "installed": installed,
            "nextModule": module,
            "dkmsKey": self.dkms_key(),
            "package": self.driver_package(installed.as_deref()),
        })
    }

    /// The digits of a version, as numbers.
    pub fn version_key(text: &str) -> Vec<u64> {
        text.split(|letter: char| !letter.is_ascii_digit())
            .filter(|part| !part.is_empty())
            .filter_map(|part| part.parse().ok())
            .collect()
    }

    fn newest<'a>(versions: impl Iterator<Item = &'a str>) -> Option<String> {
        versions.max_by_key(|version| Self::version_key(version)).map(str::to_string)
    }

    fn names_in(folder: &str) -> Vec<String> {
        fs::read_dir(folder).map_or_else(
            |_| Vec::new(),
            |entries| entries.flatten().map(|entry| entry.file_name().to_string_lossy().into_owned()).collect(),
        )
    }

    fn first_group<'a>(pattern: &Regex, text: &'a str) -> Option<&'a str> {
        pattern.captures(text)?.get(1).map(|found| found.as_str())
    }

    /// The newest kernel in `/boot`: what the default boot entry starts. Only versioned names count: `vmlinuz` is a link to one.
    fn next_kernel(&self) -> Option<String> {
        let names = Self::names_in(Self::BOOT);
        Self::newest(names.iter().filter_map(|name| Self::first_group(&self.kernel_file, name)))
    }

    fn loaded_version(&self) -> Option<String> {
        let raw = fs::read(Self::PROC_VERSION).ok()?;
        let text = String::from_utf8_lossy(&raw);
        Self::first_group(&self.loaded, &text).map(str::to_string)
    }

    /// The userspace driver's version, from its library's file name.
    fn installed_version(&self) -> Option<String> {
        let names: Vec<String> = Self::LIB_DIRS.iter().flat_map(|folder| Self::names_in(folder)).collect();
        Self::newest(names.iter().filter_map(|name| Self::first_group(&self.library, name)))
    }

    /// The `nvidia` module `kernel` would load: where it lies, its version and who signed it ("" when nobody did). `None` when there is none.
    fn module(&self, kernel: &str) -> Option<Value> {
        let path = self.machine.run_text(&["modinfo", "-k", kernel, "-n", "nvidia"]);
        let path = path.trim();
        if path.is_empty() {
            return None;
        }
        let version = self.machine.run_text(&["modinfo", "-k", kernel, "-F", "version", "nvidia"]);
        let signer = self.machine.run_text(&["modinfo", "-k", kernel, "-F", "signer", "nvidia"]);
        Some(
            json!({"path": path, "version": Some(version.trim()).filter(|version| !version.is_empty()), "signer": signer.trim()}),
        )
    }

    /// The key DKMS signs with: its name, as a module's signer reads, and whether the firmware trusts it. `null` when there is no such key.
    fn dkms_key(&self) -> Value {
        if !Path::new(Self::DKMS_KEY).exists() {
            return Value::Null;
        }
        let subject = self.machine.run_text(&["openssl", "x509", "-inform", "der", "-in", Self::DKMS_KEY, "-noout", "-subject"]);
        let signer = Self::first_group(&self.common_name, &subject).map(str::trim);
        let test = self.machine.run_text(&["mokutil", "--test-key", Self::DKMS_KEY]).to_lowercase();
        let enrolled = if test.contains("is already enrolled") {
            Some(true)
        } else if test.contains("is not enrolled") {
            Some(false)
        } else {
            None
        };
        json!({"signer": signer, "enrolled": enrolled})
    }

    /// The firmware's variable; a machine that did not boot through EFI has no Secure Boot at all; `mokutil` when the variable cannot be read; `None` when nothing can say.
    pub fn secure_boot(&self) -> Option<bool> {
        // absent-ok: a variable that does not read says nothing; what follows asks others.
        let data = fs::read(Self::SECURE_BOOT_VAR).unwrap_or_default();
        if let [_, _, _, _, flag @ (0 | 1)] = data.as_slice() {
            return Some(*flag == 1);
        }
        if !Path::new(Self::EFI_DIR).exists() {
            return Some(false);
        }
        let said = self.machine.run_text(&["mokutil", "--sb-state"]).to_lowercase();
        if said.contains("secureboot enabled") {
            Some(true)
        } else if said.contains("secureboot disabled") {
            Some(false)
        } else {
            None
        }
    }

    /// The installed `nvidia-driver-*` package the driver in use comes from, on a Debian-style system: the one whose version is the library's. Several can be installed at once, so the first one would be a guess.
    fn driver_package(&self, installed: Option<&str>) -> Option<String> {
        let installed = installed.filter(|installed| !installed.is_empty())?;
        let said = self.machine.run_text(&["dpkg-query", "-W", "-f", "${Package} ${Version} ${Status}\\n", "nvidia-driver-*"]);
        said.lines().find_map(|line| {
            let mut parts = line.splitn(3, ' ');
            let (name, version, status) = (parts.next()?, parts.next()?, parts.next()?);
            let upstream = version.split_once(':').map_or(version, |(_, rest)| rest);
            (status.trim() == "install ok installed"
                && name.starts_with("nvidia-driver-")
                && upstream.starts_with(&format!("{installed}-")))
            .then(|| name.to_string())
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_version_key_orders_numbers_as_numbers() {
        assert_eq!(DriverFacts::version_key("6.8.0-45-generic"), [6, 8, 0, 45]);
        assert!(DriverFacts::version_key("6.10.0") > DriverFacts::version_key("6.8.0"));
    }
}
