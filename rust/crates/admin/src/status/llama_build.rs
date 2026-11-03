//! The llama.cpp build on the controller's machine and the job that makes another.

use super::*;

impl<'app> StatusDesk<'app> {
    pub(super) fn llama_server_path(&self) -> PathBuf {
        self.app.paths.llama_home.join("build").join("bin").join("llama-server")
    }

    pub(super) fn lines_count(ran: &Value) -> usize {
        Coerce::text(ran.get("stdout")).lines().filter(|line| !line.trim().is_empty()).count()
    }

    /// `(build number, commit)` of the newest `b<N>` tag `git ls-remote` listed.
    pub(super) fn newest_build_tag(listing: &str) -> (i64, String) {
        let mut best: BTreeMap<i64, String> = BTreeMap::new();
        for line in listing.lines() {
            let mut words = line.split_whitespace();
            let (Some(sha), Some(reference)) = (words.next(), words.next()) else {
                continue;
            };
            if !(7..=40).contains(&sha.len())
                || !sha.chars().all(|letter| letter.is_ascii_hexdigit() && !letter.is_ascii_uppercase())
            {
                continue;
            }
            let Some(rest) = reference.strip_prefix("refs/tags/b") else {
                continue;
            };
            let (digits, peeled) = rest.strip_suffix("^{}").map_or((rest, false), |digits| (digits, true));
            let Ok(number) = digits.parse::<i64>() else {
                continue;
            };
            if peeled || !best.contains_key(&number) {
                best.insert(number, sha.to_string());
            }
        }
        best.last_key_value().map_or((0, String::new()), |(number, sha)| (*number, sha.chars().take(12).collect()))
    }

    fn file_moment(path: &Path) -> String {
        let modified = std::fs::metadata(path)
            .ok()
            .and_then(|found| found.modified().ok())
            .and_then(|at| at.duration_since(std::time::UNIX_EPOCH).ok());
        modified.and_then(|since| LocalTime::of(since.as_secs() as i64)).map_or_else(String::new, |at| at.iso())
    }

    /// The llama.cpp of this machine.
    pub fn llama_cpp_info(&self, fetch_remote: bool) -> Value {
        let binary = self.llama_server_path();
        let exists = binary.exists();
        let shown = binary.to_string_lossy().into_owned();
        let missing = json!({"ok": false, "stdout": "", "stderr": "llama-server binary not found"});
        let of_binary = |flag: &str| {
            if exists {
                Self::shown(self.app.commands.run(&[shown.as_str(), flag], Duration::from_secs(5)).ok())
            } else {
                missing.clone()
            }
        };
        let (version, help) = (of_binary("--version"), of_binary("--help"));
        let home = &self.app.paths.llama_home;
        let git = |argv: &[&str], timeout: u64| self.run_in(argv, home, timeout);
        let head = git(&["git", "rev-parse", "--short", "HEAD"], 5);
        let branch = git(&["git", "branch", "--show-current"], 5);
        let remote = git(&["git", "config", "--get", "remote.origin.url"], 5);
        let dirty = git(&["git", "status", "--porcelain"], 5);
        let tracked = git(&["git", "status", "--porcelain", "--untracked-files=no"], 5);
        let not_checked = json!({"ok": false, "stdout": "", "stderr": "Not checked"});
        let (upstream, tags) = if fetch_remote {
            (
                git(&["git", "ls-remote", "origin", "HEAD"], 30),
                git(&["git", "ls-remote", "--tags", "origin", "refs/tags/b[0-9]*"], 30),
            )
        } else {
            (not_checked.clone(), not_checked)
        };
        let (build, build_commit) = if Coerce::truthy(tags.get("ok")) {
            Self::newest_build_tag(&Coerce::text(tags.get("stdout")))
        } else {
            (0, String::new())
        };
        let mtime = Self::file_moment(&binary);
        let version_word = {
            let said = Coerce::text(version.get("stdout"));
            let said = if said.is_empty() { Coerce::text(version.get("stderr")) } else { said };
            Coerce::strip(&said).to_string()
        };
        let help_text = format!("{}{}", Coerce::text(help.get("stdout")), Coerce::text(help.get("stderr")));
        let tracked_text = Coerce::text(tracked.get("stdout"));
        let sample: Vec<&str> = tracked_text.lines().take(12).collect();
        let upstream_ok = Coerce::truthy(upstream.get("ok"));
        let upstream_stdout = Coerce::text(upstream.get("stdout"));
        let upstream_head: String =
            upstream_stdout.split_whitespace().next().filter(|_| upstream_ok).unwrap_or("").chars().take(12).collect();
        json!({
            "binary": shown, "binaryExists": exists, "binaryMtime": mtime, "version": version_word,
            "supportsChatTemplateFile": help_text.contains("--chat-template-file"),
            "git": {
                "branch": Coerce::stripped(branch.get("stdout")), "head": Coerce::stripped(head.get("stdout")), "remote": Coerce::stripped(remote.get("stdout")),
                "dirtyCount": Self::lines_count(&dirty), "trackedDirtyCount": Self::lines_count(&tracked), "trackedDirtySample": sample,
                "upstreamHead": upstream_head, "upstreamBuild": build, "upstreamBuildCommit": build_commit, "upstreamChecked": fetch_remote,
                "upstreamError": if upstream_ok { String::new() } else { Coerce::text(upstream.get("stderr")) },
            },
        })
    }

    /// The job as it stands.
    pub fn update_status(&self) -> Value {
        let mut snap = self.app.update_job.held.lock().unwrap_or_else(PoisonError::into_inner).clone();
        let lines = Coerce::list(snap.get("lines"));
        let tail: Vec<Value> = lines.iter().skip(lines.len().saturating_sub(Self::LINES_SHOWN)).cloned().collect();
        Coerce::put(&mut snap, "lines", Value::Array(tail));
        snap
    }

    pub(super) fn builds_dir(&self) -> PathBuf {
        match self.app.env.get("LLAMA_BUILDS_DIR").filter(|said| !said.is_empty()) {
            Some(said) => PathBuf::from(said),
            None => self.app.env.home().join(".local/share/lama-caravan/llama-builds"),
        }
    }

    /// The archived builds, the newest first.
    pub fn builds_list(&self) -> Value {
        let mut entries: Vec<PathBuf> =
            std::fs::read_dir(self.builds_dir()).into_iter().flatten().flatten().map(|entry| entry.path()).collect();
        entries.sort();
        entries.reverse();
        let rows: Vec<Value> = entries
            .iter()
            .filter_map(|entry| {
                let mut row: Value = serde_json::from_slice(&std::fs::read(entry.join("meta.json")).ok()?).ok()?;
                Coerce::put(&mut row, "id", json!(entry.file_name().map(|name| name.to_string_lossy().into_owned())));
                Some(row)
            })
            .collect();
        // absent-ok: `int(os.environ.get("LLAMA_BUILDS_KEEP") or 5)`: the installer's own default.
        let keep: i64 = self.app.env.get("LLAMA_BUILDS_KEEP").and_then(|said| said.parse().ok()).unwrap_or(5);
        json!({"ok": true, "builds": rows, "keep": keep})
    }

    /// An archived build restored, as the same background job the update uses.
    pub fn start_restore(&self, build_id: Option<&Value>) -> Result<Value, AppError> {
        let build_id = Coerce::stripped(build_id);
        if build_id.is_empty() {
            return Err(AppError::new("build id is required"));
        }
        self.start_update("", &build_id)
    }

    /// The background update started, or an archive's restore when `restore_id` is set.
    pub fn start_update(&self, tag: &str, restore_id: &str) -> Result<Value, AppError> {
        if self.app.paths.is_container {
            return Err(AppError::new(
                "the container image has no llama.cpp build environment — update llama.cpp on caravan-scout hosts instead",
            ));
        }
        let script = self.app.paths.project_root.join("scripts").join("install-llama.sh");
        if !script.exists() {
            return Err(AppError::with_status(format!("install script not found: {}", script.to_string_lossy()), 500));
        }
        let shown = script.to_string_lossy().into_owned();
        let (tag, restore_id) = (Coerce::strip(tag), Coerce::strip(restore_id));
        let mut command = vec!["bash".to_string(), shown];
        let word = if restore_id.is_empty() {
            command.extend(["--force".to_string(), "--no-restart".to_string()]);
            if !tag.is_empty() {
                command.extend(["--llama-tag".to_string(), tag.to_string()]);
            }
            tag.to_string()
        } else {
            command.extend(["--restore".to_string(), restore_id.to_string()]);
            format!("restore:{restore_id}")
        };
        self.start_shared_job(command, &word)
    }

    pub(super) fn without_colors(line: &str) -> String {
        let mut out = String::with_capacity(line.len());
        let mut letters = line.chars().peekable();
        while let Some(letter) = letters.next() {
            if letter == '\x1b' && letters.peek() == Some(&'[') {
                let mut lookahead = letters.clone();
                lookahead.next();
                let mut end_found = false;
                for following in lookahead.by_ref() {
                    if following == 'm' {
                        end_found = true;
                        break;
                    }
                    if !(following.is_ascii_digit() || following == ';') {
                        break;
                    }
                }
                if end_found {
                    letters = lookahead;
                    continue;
                }
            }
            out.push(letter);
        }
        out
    }

    /// One background job at a time: a llama.cpp update, an archive's restore, a vLLM install.
    pub(super) fn start_shared_job(&self, command: Vec<String>, tag: &str) -> Result<Value, AppError> {
        {
            let mut job = self.app.update_job.held.lock().unwrap_or_else(PoisonError::into_inner);
            if Coerce::truthy(job.get("running")) {
                return Err(AppError::with_status("a build/install job is already running", 409));
            }
            *job = json!({"running": true, "startedAt": self.app.now_whole(), "tag": tag, "lines": [], "done": false, "rc": null, "error": ""});
        }
        let app = self.app.shared().ok_or_else(|| AppError::with_status("the controller is stopping", 503))?;
        let started = std::thread::Builder::new().name("llama-update".to_string()).spawn(move || Self::run_job(&app, &command));
        started.map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Ok(self.update_status())
    }

    pub(super) fn run_job(app: &App, command: &[String]) {
        let path = format!("/usr/local/cuda/bin:{}", app.env.get("PATH").unwrap_or("/usr/bin:/bin"));
        let (mut rc, mut error) = (json!(-1), String::new());
        let (program, rest) = command.split_first().map_or(("", &[][..]), |(program, rest)| (program.as_str(), rest));
        let spawned = Command::new(program)
            .args(rest)
            .current_dir(&app.paths.project_root)
            .env("PATH", path)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();
        match spawned {
            Ok(mut child) => {
                let reader = child.stderr.take();
                if let Some(stderr) = reader {
                    Self::keep_reading(app, stderr);
                }
                if let Some(stdout) = child.stdout.take() {
                    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                        Self::keep_line(app, &line);
                    }
                }
                match child.wait() {
                    Ok(status) => rc = json!(status.code().unwrap_or(-1)),
                    Err(failure) => error = failure.to_string(),
                }
            }
            Err(failure) => error = failure.to_string(),
        }
        let mut job = app.update_job.held.lock().unwrap_or_else(PoisonError::into_inner);
        Coerce::put(&mut job, "running", json!(false));
        Coerce::put(&mut job, "done", json!(true));
        Coerce::put(&mut job, "rc", rc);
        Coerce::put(&mut job, "error", json!(error));
    }

    pub(super) fn keep_reading(app: &App, stderr: std::process::ChildStderr) {
        if let Some(held) = app.shared() {
            let reader = std::thread::Builder::new().name("llama-update-err".to_string()).spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    Self::keep_line(&held, &line);
                }
            });
            drop(reader);
        }
    }

    pub(super) fn keep_line(app: &App, line: &str) {
        let clean = Self::without_colors(line.trim_end());
        let mut job = app.update_job.held.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(lines) = job.get_mut("lines").and_then(Value::as_array_mut) {
            lines.push(json!(clean));
            if lines.len() > Self::LINES_KEPT {
                lines.drain(..100);
            }
        }
    }
}
