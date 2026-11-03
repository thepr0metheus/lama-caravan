//! What the running controller is made of, named as osv.dev names it. There is no Python here to list: the crates the program
//! was built with, and the image's own packages.

use crate::app::App;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::Path;

/// The packages of this copy of the controller.
pub struct InstalledPackages<'app> {
    app: &'app App,
}

impl<'app> InstalledPackages<'app> {
    /// The packages of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// `{runtime, os, packages}`.
    pub fn listing(&self) -> Value {
        let root = Path::new("/");
        let system = Self::system(root);
        let mut packages = self.crates();
        if let Some(system) = system.as_ref().filter(|system| Coerce::truthy(system.get("listed"))) {
            packages.extend(Self::debian(root, &Coerce::text(system.get("version"))));
        }
        json!({"runtime": {"name": "rust", "version": crate::VERSION}, "os": system, "packages": packages})
    }

    fn is_version_word(version: &str) -> bool {
        !version.is_empty() && version.split('.').all(|part| !part.is_empty() && part.chars().all(|digit| digit.is_ascii_digit()))
    }

    /// `ID` and `VERSION_ID` of os-release, and whether its packages are listed.
    fn system(root: &Path) -> Option<Value> {
        let text = std::fs::read_to_string(root.join("etc/os-release")).ok()?;
        let mut fields = BTreeMap::new();
        for line in text.lines() {
            if let Some((key, value)) = line.split_once('=') {
                fields.insert(Coerce::strip(key).to_string(), Coerce::strip(value).trim_matches(['"', '\'']).to_string());
            }
        }
        let name = fields.get("ID").filter(|name| !name.is_empty())?.clone();
        // absent-ok: a package that names no version is listed without one.
        let version = fields.get("VERSION_ID").cloned().unwrap_or_default();
        let listed = name == "debian" && Self::is_version_word(&version) && root.join("var/lib/dpkg/status").is_file();
        Some(json!({"name": name, "version": version, "listed": listed}))
    }

    /// The third-party crates, each once, from the list the image's build wrote.
    fn crates(&self) -> Vec<Value> {
        let path = self.app.paths.project_root.join("bin").join("rust-packages.txt");
        let Ok(text) = std::fs::read_to_string(path) else {
            return Vec::new();
        };
        let mut found = BTreeMap::new();
        for line in text.lines() {
            let Some((name, version)) = Coerce::strip(line).split_once(" v") else {
                continue;
            };
            let name_ok =
                !name.is_empty() && name.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '_' | '-'));
            if name_ok && !version.is_empty() && !version.contains(char::is_whitespace) {
                found.insert(
                    (name.to_string(), version.to_string()),
                    json!({"ecosystem": "crates.io", "name": name, "version": version}),
                );
            }
        }
        found.into_values().collect()
    }

    /// dpkg's installed packages, each by its source and the source's version.
    fn debian(root: &Path, os_version: &str) -> Vec<Value> {
        let ecosystem = format!("Debian:{}", os_version.split('.').next().unwrap_or(os_version));
        let Ok(raw) = std::fs::read(root.join("var/lib/dpkg/status")) else {
            return Vec::new();
        };
        let text = String::from_utf8_lossy(&raw);
        let mut found = BTreeMap::new();
        for record in text.split("\n\n") {
            let mut fields: BTreeMap<&str, &str> = BTreeMap::new();
            for line in record.lines().filter(|line| !line.starts_with([' ', '\t'])) {
                if let Some((key, value)) = line.split_once(':') {
                    fields.entry(Coerce::strip(key)).or_insert_with(|| Coerce::strip(value));
                }
            }
            if fields.get("Status").and_then(|status| status.split_whitespace().next_back()) != Some("installed") {
                continue;
            }
            let said = fields.get("Source").or_else(|| fields.get("Package")).copied().unwrap_or("");
            let (source, own) = said.split_once(" (").map_or((said, None), |(source, own)| (source, Some(own)));
            let version = match own {
                Some(own) => Coerce::strip(own.trim_end_matches(')')),
                None => fields.get("Version").copied().unwrap_or(""),
            };
            if !source.is_empty() && !version.is_empty() {
                found.insert(
                    (source.to_string(), version.to_string()),
                    json!({"ecosystem": ecosystem, "name": source, "version": version}),
                );
            }
        }
        found.into_values().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dpkg_records_are_read_by_their_source() {
        let root = std::env::temp_dir().join(format!("caravan-packages-{}", std::process::id()));
        std::fs::create_dir_all(root.join("var/lib/dpkg")).unwrap();
        std::fs::create_dir_all(root.join("etc")).unwrap();
        std::fs::write(root.join("etc/os-release"), "ID=debian\nVERSION_ID=\"12\"\n").unwrap();
        std::fs::write(
            root.join("var/lib/dpkg/status"),
            "Package: a\nStatus: install ok installed\nVersion: 1.0\n\nPackage: b\nSource: c (2.0)\nStatus: install ok installed\nVersion: 3\n\nPackage: d\nStatus: deinstall ok config-files\nVersion: 4\n",
        )
        .unwrap();
        let system = InstalledPackages::system(&root).unwrap();
        assert_eq!(system, json!({"name": "debian", "version": "12", "listed": true}));
        let packages = InstalledPackages::debian(&root, "12");
        assert_eq!(
            packages,
            [
                json!({"ecosystem": "Debian:12", "name": "a", "version": "1.0"}),
                json!({"ecosystem": "Debian:12", "name": "c", "version": "2.0"})
            ]
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
