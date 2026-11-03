//! The isolated, pinned PrismML runtime used by Bonsai cells. A release is installed once, its libraries beside its own server: a stock libggml cannot interpret Prism's tensor types, and
//! installing into `llama.cpp`'s build tree, or inheriting its `LD_LIBRARY_PATH`, can make a correctly selected Prism binary load the wrong libraries.

use crate::commands::Commands;
use crate::config::ScoutConfig;
use crate::errors::AppError;
use crate::http_client::HttpClient;
use crate::models::fetcher::ModelFetcher;
use crate::models::files::{Resolved, Walk};
use crate::runtimes::prism_archive::ArchiveLine;
use net::Sha256;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

/// How a download of the runtime goes: bytes so far, of how many, the file.
pub type RuntimeProgress<'a> = &'a dyn Fn(u64, u64, &str);

/// The runtime.
pub struct PrismRuntime {
    config: Arc<ScoutConfig>,
    commands: Arc<dyn Commands>,
    http: Arc<HttpClient>,
    installing: Mutex<()>,
    help: Mutex<BTreeMap<String, BTreeSet<String>>>,
}

impl PrismRuntime {
    const RELEASE: &'static str = "prism-b10743-adfffbe";
    const BASE_URL: &'static str = "https://github.com/PrismML-Eng/llama.cpp/releases/download";
    /// Digests published on the pinned release; no moving 'latest' at startup.
    const ASSETS: [(&'static str, &'static str); 9] = [
        ("linux-cuda-12.4-x64", "fef4c7e8d83ff261d89809c1b302fe5f826adc1a74e13654b67ec056fbc1c639"),
        ("linux-cuda-12.8-x64", "43b73a24d5cd83c4482750ee52e59afac497c669c008a319e44e43a0033757e2"),
        ("linux-cuda-13.3-x64", "bfa6e1e0af2f21295e863cf26444c49b5d0094221ea785836cd810325fca2159"),
        ("ubuntu-x64", "1bb340929fddae8667c97ec6d4064a5768fe1dd08eeee0074b8d5e08f07dfc31"),
        ("ubuntu-arm64", "ee4cb83a2985572459a5686ef175503d4e526b46b97c7fcc7152e868169b3060"),
        ("macos-arm64", "596d257973080ca5011a4be50477c5f93ed1d231fcccfc2afb44bb573bb9629a"),
        ("macos-x64", "3527598651d783b66d525afbcdd0cbbba12a8d59c388bb0e13fa85715381969d"),
        ("ubuntu-vulkan-x64", "95a3d082629643642842bc2195e0730880273005171517cf857804702f693edc"),
        ("ubuntu-rocm-7.2-x64", "fc539098d17f3a25668027a8f4cd35c7e5b78148abe2cd7948c66ebb988cc203"),
    ];

    /// The runtime of this scout.
    pub fn new(config: Arc<ScoutConfig>, commands: Arc<dyn Commands>, http: Arc<HttpClient>) -> Self {
        Self { config, commands, http, installing: Mutex::new(()), help: Mutex::new(BTreeMap::new()) }
    }

    fn root(&self) -> PathBuf {
        let said = self.config.text("prismRuntimeDir");
        let said = if said.is_empty() { "~/.local/share/caravan/prismml".to_string() } else { said };
        Resolved::of(&ModelFetcher::expanded(&said))
    }

    fn system_word() -> &'static str {
        match std::env::consts::OS {
            "macos" => "darwin",
            other => other,
        }
    }

    /// Which of the release's archives fits this system, its architecture, its CUDA and the backend asked.
    pub fn asset(system: &str, machine: &str, cuda: &str, backend: &str) -> Result<String, AppError> {
        let arch = match machine.to_lowercase().as_str() {
            "x86_64" | "amd64" => Some("x64"),
            "arm64" | "aarch64" => Some("arm64"),
            _ => None,
        };
        if let (true, true, Some(arch)) = (system == "darwin", matches!(backend, "auto" | "cpu"), arch) {
            return Ok(format!("macos-{arch}"));
        }
        let Some(arch) = arch.filter(|_| system == "linux") else {
            return Err(AppError::new(format!("PrismML has no managed runtime for {system}/{machine}")));
        };
        if backend == "cpu" || (backend == "auto" && cuda.is_empty()) {
            return Ok(format!("ubuntu-{arch}"));
        }
        if arch == "x64" {
            match backend {
                "vulkan" => return Ok("ubuntu-vulkan-x64".to_string()),
                "rocm" => return Ok("ubuntu-rocm-7.2-x64".to_string()),
                _ => {}
            }
        }
        if !matches!(backend, "auto" | "cuda") || arch != "x64" {
            return Err(AppError::new(format!("PrismML has no managed {backend} runtime for {machine}")));
        }
        let version =
            cuda.split_once('.').and_then(|(major, minor)| Some((major.parse::<u32>().ok()?, minor.parse::<u32>().ok()?)));
        let version = version
            .filter(|version| *version >= (12, 4))
            .ok_or_else(|| AppError::new("PrismML CUDA needs an NVIDIA driver supporting CUDA 12.4 or newer"))?;
        let flavor = if version >= (13, 3) {
            "13.3"
        } else if version >= (12, 8) {
            "12.8"
        } else {
            "12.4"
        };
        Ok(format!("linux-cuda-{flavor}-x64"))
    }

    /// The version `CUDA Version: 13.3` or `CUDA UMD Version: 13.3` of `nvidia-smi`'s page says.
    fn cuda_in(page: &str) -> Option<String> {
        ["CUDA Version:", "CUDA UMD Version:"].iter().find_map(|label| {
            let (_, rest) = page.split_once(label)?;
            let word: String = rest.trim_start().chars().take_while(|letter| letter.is_ascii_digit() || *letter == '.').collect();
            let (major, minor) = word.split_once('.')?;
            let digits = !major.is_empty() && !minor.is_empty() && minor.chars().all(|letter| letter.is_ascii_digit());
            digits.then_some(word.clone())
        })
    }

    fn selected_asset(&self) -> Result<String, AppError> {
        let mut cuda = String::new();
        if Self::system_word() == "linux"
            && let Ok(ran) = self.commands.run(&["nvidia-smi"], Duration::from_secs(10))
            && ran.ok()
        {
            // absent-ok: a page that names no CUDA is a machine with none, and the CPU's archive fits.
            cuda = Self::cuda_in(&ran.stdout).unwrap_or_default();
        }
        let backend = self.config.text("prismBackend");
        Self::asset(Self::system_word(), std::env::consts::ARCH, &cuda, if backend.is_empty() { "auto" } else { &backend })
    }

    /// What the runtime starts with: its own libraries.
    pub fn environment(binary: &str) -> Map<String, Value> {
        let folder = Path::new(binary).parent().unwrap_or(Path::new(""));
        let beside = folder.parent().map(|parent| parent.join("lib"));
        let libraries: Vec<String> = [Some(folder.to_path_buf()), Some(folder.join("lib")), beside]
            .into_iter()
            .flatten()
            .filter(|path| path.is_dir())
            .map(|path| path.display().to_string())
            .collect();
        let joined = libraries.join(":");
        let mut out = Map::new();
        out.insert("LD_LIBRARY_PATH".to_string(), json!(joined));
        out.insert("DYLD_LIBRARY_PATH".to_string(), json!(joined));
        out
    }

    fn probe(&self, binary: &str, option: &str) -> Result<String, AppError> {
        let environment = Self::environment(binary);
        let settings: Vec<String> =
            environment.iter().map(|(name, value)| format!("{name}={}", Coerce::text(Some(value)))).collect();
        let mut argv = vec!["env"];
        argv.extend(settings.iter().map(String::as_str));
        argv.extend(["CUDA_VISIBLE_DEVICES=", binary, option]);
        let ran = self
            .commands
            .run(&argv, Duration::from_secs(30))
            .map_err(|_| AppError::new(format!("PrismML runtime cannot run {option}: it did not answer")))?;
        if !ran.ok() {
            let said = if ran.stderr.trim().is_empty() { ran.stdout.trim() } else { ran.stderr.trim() };
            let letters: Vec<char> = said.chars().collect();
            let (_, tail) = letters.split_at(letters.len().saturating_sub(1200));
            return Err(AppError::new(format!("PrismML runtime cannot run {option}: {}", tail.iter().collect::<String>())));
        }
        Ok(format!("{}{}", ran.stdout, ran.stderr))
    }

    /// Validates links as well as names before extracting a vendor archive, then extracts it with the system's `tar`.
    fn unpack(&self, archive: &Path, target: &Path) -> Result<(), AppError> {
        let archive_name = archive.display().to_string();
        let listing = self
            .commands
            .run(&["tar", "-tvzf", &archive_name], Duration::from_secs(120))
            .map_err(|_| AppError::new("PrismML archive cannot be read"))?;
        if !listing.ok() {
            return Err(AppError::new("PrismML archive cannot be read"));
        }
        let root = Resolved::of(target);
        for line in listing.stdout.lines() {
            ArchiveLine::read(line).check(&root)?;
        }
        let into = target.display().to_string();
        let extracted = self
            .commands
            .run(&["tar", "-xzf", &archive_name, "-C", &into, "--no-same-owner"], Duration::from_secs(600))
            .map_err(|_| AppError::new("PrismML archive cannot be extracted"))?;
        if !extracted.ok() {
            return Err(AppError::new(format!("PrismML archive cannot be extracted: {}", extracted.stderr.trim())));
        }
        Ok(())
    }

    /// The server's path, installing the release once.
    pub fn ensure(&self, progress: RuntimeProgress<'_>) -> Result<String, AppError> {
        let said = Coerce::strip(&self.config.text("prismServerBin")).to_string();
        if !said.is_empty() {
            let binary = ModelFetcher::expanded(&said).display().to_string();
            self.probe(&binary, "--version")?;
            return Ok(binary);
        }
        let _one_install = self.installing.lock().unwrap_or_else(PoisonError::into_inner);
        let flavor = self.selected_asset()?;
        let root = self.root();
        let directory = root.join(format!("{}-{flavor}", Self::RELEASE));
        let manifest = fs::read(directory.join("runtime.json")).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
        if let Some(relative) = manifest.as_ref().and_then(|info| info.get("binary")).and_then(Value::as_str) {
            let binary = directory.join(relative);
            if binary.is_file() {
                self.activate(&binary)?;
                return Ok(binary.display().to_string());
            }
        }
        fs::create_dir_all(&root).map_err(Self::failed)?;
        let staging = root.join(format!(".install-{}", std::process::id()));
        fs::create_dir_all(&staging).map_err(Self::failed)?;
        let installed = self.install(&flavor, &staging, &directory, progress);
        // What cannot be removed stays until the next install, and is named by its process.
        drop(fs::remove_dir_all(&staging));
        installed
    }

    fn failed(error: std::io::Error) -> AppError {
        AppError::new(format!("PrismML runtime was not installed: {error}"))
    }

    fn install(&self, flavor: &str, staging: &Path, directory: &Path, progress: RuntimeProgress<'_>) -> Result<String, AppError> {
        let archive = staging.join("runtime.tar.gz");
        let digest = self.fetch(flavor, &archive, progress)?;
        let wanted = Self::ASSETS.iter().find(|(name, _)| *name == flavor).map(|(_, digest)| *digest);
        if wanted != Some(digest.as_str()) {
            return Err(AppError::new("PrismML archive SHA-256 mismatch — runtime was not installed"));
        }
        let extracted = staging.join("files");
        fs::create_dir(&extracted).map_err(Self::failed)?;
        self.unpack(&archive, &extracted)?;
        let candidates: Vec<PathBuf> = Walk::entries(&extracted)
            .into_iter()
            .filter(|path| path.file_name().is_some_and(|name| name == "llama-server"))
            .collect();
        let [binary] = candidates.as_slice() else {
            return Err(AppError::new("PrismML archive must contain exactly one llama-server"));
        };
        use std::os::unix::fs::PermissionsExt;
        let mode = fs::metadata(binary).map_err(Self::failed)?.permissions().mode();
        fs::set_permissions(binary, fs::Permissions::from_mode(mode | 0o111)).map_err(Self::failed)?;
        let version = self.probe(&binary.display().to_string(), "--version")?;
        let relative = binary
            .strip_prefix(&extracted)
            .map_err(|_| AppError::new("PrismML archive names a server outside itself"))?
            .to_path_buf();
        let manifest = json!({
            "release": Self::RELEASE,
            "asset": flavor,
            "sha256": digest,
            "binary": relative.display().to_string(),
            "version": version.trim(),
        });
        let text = serde_json::to_string_pretty(&manifest).map_err(|error| AppError::new(error.to_string()))?;
        fs::write(extracted.join("runtime.json"), format!("{text}\n")).map_err(Self::failed)?;
        // An incomplete prior install is never published as current.
        if directory.exists() {
            return Err(AppError::new(format!("incomplete PrismML install at {}; move it aside and retry", directory.display())));
        }
        fs::rename(&extracted, directory).map_err(Self::failed)?;
        let installed = directory.join(relative);
        self.activate(&installed)?;
        Ok(installed.display().to_string())
    }

    /// The archive on the disk, and its digest.
    fn fetch(&self, flavor: &str, archive: &Path, progress: RuntimeProgress<'_>) -> Result<String, AppError> {
        const TIMEOUT: Duration = Duration::from_secs(60);
        let name = format!("llama-{0}-bin-{flavor}.tar.gz", Self::RELEASE);
        let url = format!("{}/{}/{name}", Self::BASE_URL, Self::RELEASE);
        let refused = |words: String| AppError::new(format!("PrismML runtime was not fetched: {words}"));
        let mut answer = self.http.following(&url, TIMEOUT).map_err(|error| refused(error.to_string()))?;
        // absent-ok: an answer of no said length shows bytes without a whole.
        let total: u64 = answer.head.headers.get("Content-Length").and_then(|said| said.trim().parse().ok()).unwrap_or(0);
        let mut output = fs::File::create(archive).map_err(Self::failed)?;
        let mut digest = Sha256::new();
        let mut block = vec![0u8; 1 << 20];
        let mut downloaded = 0u64;
        loop {
            let count = answer.body.read(&mut block).map_err(|error| refused(error.to_string()))?;
            let Some(part) = block.get(..count).filter(|_| count != 0) else {
                break;
            };
            output.write_all(part).map_err(Self::failed)?;
            digest.update(part);
            downloaded += count as u64;
            progress(downloaded, total, &name);
        }
        Ok(digest.hex())
    }

    /// A stable path for generated previews, a versioned path for running cells.
    fn activate(&self, binary: &Path) -> Result<(), AppError> {
        let root = self.root();
        let link = root.join(".current.tmp");
        // Not there is what is wanted.
        drop(fs::remove_file(&link));
        let folder = binary.parent().unwrap_or(binary);
        let relative = folder.strip_prefix(&root).unwrap_or(folder);
        std::os::unix::fs::symlink(relative, &link).map_err(Self::failed)?;
        fs::rename(&link, root.join("current")).map_err(Self::failed)
    }

    /// The flags a help page names.
    fn flags_in(page: &str) -> BTreeSet<String> {
        let letters: Vec<char> = page.chars().collect();
        let mut found = BTreeSet::new();
        let mut at = 0;
        while at < letters.len() {
            let starts = letters.get(at) == Some(&'-')
                && letters.get(at + 1) == Some(&'-')
                && letters.get(at + 2).is_some_and(char::is_ascii_lowercase);
            let after_word = at
                .checked_sub(1)
                .and_then(|before| letters.get(before))
                .is_some_and(|before| before.is_alphanumeric() || *before == '_');
            if !starts || after_word {
                at += 1;
                continue;
            }
            let mut end = at + 3;
            while letters.get(end).is_some_and(|letter| letter.is_ascii_lowercase() || letter.is_ascii_digit() || *letter == '-')
            {
                end += 1;
            }
            found.insert(letters.iter().skip(at).take(end - at).collect());
            at = end;
        }
        found
    }

    /// Refuses a start whose flags the server does not know.
    pub fn validate_args(&self, binary: &str, args: &[String]) -> Result<(), AppError> {
        let kept = self.help.lock().unwrap_or_else(PoisonError::into_inner).get(binary).cloned();
        let known = match kept {
            Some(known) => known,
            None => {
                let known = Self::flags_in(&self.probe(binary, "--help")?);
                self.help.lock().unwrap_or_else(PoisonError::into_inner).insert(binary.to_string(), known.clone());
                known
            }
        };
        let asked: BTreeSet<&str> =
            args.iter().filter(|arg| arg.starts_with("--")).map(|arg| arg.split('=').next().unwrap_or(arg)).collect();
        let unknown: Vec<&str> = asked.into_iter().filter(|flag| !known.contains(*flag)).collect();
        if unknown.is_empty() {
            return Ok(());
        }
        Err(AppError::new(format!(
            "PrismML {} does not support: {}; adjust the cell settings",
            Self::RELEASE,
            unknown.join(", ")
        )))
    }

    /// What the board shows of the runtime.
    pub fn facts(&self) -> Value {
        let said = Coerce::strip(&self.config.text("prismServerBin")).to_string();
        if !said.is_empty() {
            let binary = ModelFetcher::expanded(&said);
            return json!({"supported": true, "installed": binary.is_file(), "binary": binary.display().to_string(), "release": "custom"});
        }
        let root = self.root();
        let current = root.join("current");
        if current.exists() {
            let resolved = Resolved::of(&current);
            let manifest = resolved
                .ancestors()
                .take_while(|folder| folder.starts_with(&root))
                .map(|folder| folder.join("runtime.json"))
                .find(|file| file.is_file());
            let info =
                manifest.as_ref().and_then(|file| fs::read(file).ok()).and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
            if let (Some(file), Some(Value::Object(info))) = (&manifest, info)
                && let Some(relative) = info.get("binary").and_then(Value::as_str)
            {
                let binary = file.parent().unwrap_or(file).join(relative);
                let mut out = Map::new();
                out.insert("supported".to_string(), json!(true));
                out.insert("installed".to_string(), json!(true));
                out.extend(info.clone());
                out.insert("binary".to_string(), json!(binary.display().to_string()));
                return Value::Object(out);
            }
        }
        json!({"supported": true, "installed": false, "release": Self::RELEASE})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn asset(system: &str, machine: &str, cuda: &str, backend: &str) -> String {
        PrismRuntime::asset(system, machine, cuda, backend).unwrap_or_else(|error| format!("!{}", error.message))
    }

    #[test]
    fn the_archive_follows_the_system_the_cuda_and_the_backend() {
        assert_eq!(asset("darwin", "arm64", "", "auto"), "macos-arm64");
        assert_eq!(asset("linux", "x86_64", "", "auto"), "ubuntu-x64");
        assert_eq!(asset("linux", "aarch64", "", "cpu"), "ubuntu-arm64");
        assert_eq!(asset("linux", "x86_64", "13.3", "auto"), "linux-cuda-13.3-x64");
        assert_eq!(asset("linux", "x86_64", "12.9", "cuda"), "linux-cuda-12.8-x64");
        assert_eq!(asset("linux", "x86_64", "12.4", "auto"), "linux-cuda-12.4-x64");
        assert_eq!(asset("linux", "x86_64", "", "vulkan"), "ubuntu-vulkan-x64");
        assert!(asset("linux", "x86_64", "11.8", "auto").starts_with("!PrismML CUDA needs"));
        assert!(asset("linux", "arm64", "13.3", "cuda").starts_with("!PrismML has no managed cuda"));
        assert!(asset("win32", "x86_64", "", "auto").starts_with("!PrismML has no managed runtime"));
    }

    #[test]
    fn the_flags_of_a_help_page_are_read_past_words_that_hold_dashes() {
        let flags = PrismRuntime::flags_in("  -m, --model FILE\n  --ctx-size N  see word--not-a-flag and --Upper --n-gpu-layers");
        assert_eq!(flags.into_iter().collect::<Vec<_>>(), ["--ctx-size", "--model", "--n-gpu-layers"]);
    }

    #[test]
    fn the_cuda_is_read_off_the_page() {
        assert_eq!(PrismRuntime::cuda_in("| CUDA Version: 13.3   |").as_deref(), Some("13.3"));
        assert_eq!(PrismRuntime::cuda_in("CUDA UMD Version: 12.8").as_deref(), Some("12.8"));
        assert_eq!(PrismRuntime::cuda_in("no card here"), None);
    }
}
