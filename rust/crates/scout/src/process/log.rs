//! The log a cell's process writes. A new run moves the previous run's log aside instead of truncating it, and a dead process's log is
//! read for the reason it died and for its last lines. What is read leaves the machine, so keys are scrubbed out of it first: the value goes, its name stays.

use crate::log::Log;
use os::LocalTime;
use regex::{Regex, RegexBuilder};
use serde_json::{Value, json};
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// The patterns a log is read by: built once, at the scout's start.
#[derive(Debug)]
pub struct LogPatterns {
    secrets: Vec<(Regex, &'static str)>,
    run_stamp: Regex,
    debugger_noise: Regex,
    library_footers: Regex,
    progress_noise: Regex,
    exception_line: Regex,
    cause_elsewhere: Regex,
    level: Regex,
}

impl LogPatterns {
    /// The patterns. They are this program's own text: one that does not compile is no state to start in, and says so.
    pub fn new() -> Result<Self, regex::Error> {
        Ok(Self {
            secrets: vec![
                (Self::plain(r"\b(lcv1_|sk-|hf_|ghp_|glpat-)[A-Za-z0-9_\-]{6,}")?, "${1}…"),
                (Self::any_case(r#"\b(bearer)\s+[^\s"',}]+"#)?, "${1} …"),
                (
                    Self::any_case(
                        r#"\b((?:[a-z0-9]+_)*(?:api[_-]?key|password|passwd|secret))\b("?\s*[=:]\s*"?|\s+)[^\s"',}]+"#,
                    )?,
                    "${1}${2}…",
                ),
                (
                    Self::any_case(
                        r#"\b((?:[a-z0-9]+_)*(?:token|authorization))\b("?\s*[=:]\s*"?|\s+)[A-Za-z0-9_\-.~+/=]{12,}"#,
                    )?,
                    "${1}${2}…",
                ),
            ],
            run_stamp: Self::plain(r"^\d{8}-\d{6}(?:-\d+)?$")?,
            debugger_noise: Self::plain(
                r"^\s*(?:#\d+\s+0x[0-9a-f]+\s|warning: \d+\s|\[Inferior \d+ \(process \d+\) detached\]|\[New LWP |\[Thread debugging |Using host libthread_db)",
            )?,
            library_footers: Self::plain(
                r"^\s*(?:\([A-Za-z]+ pid=\d+\)\s+)?For further information visit https?://errors\.pydantic\.dev/",
            )?,
            progress_noise: Self::plain(r"^\s*\[strata\]\s+still starting \(\d+ s\)")?,
            exception_line: Self::plain(r"^\s*(?:\([A-Za-z]+ pid=\d+\)\s+)?(?:[A-Za-z_]\w*\.)*\w*(?:Error|Exception)\b:\s")?,
            cause_elsewhere: Self::any_case(r"see root cause above|validation errors? for ")?,
            level: Self::plain(r"^\s*[\d.]+\s+([IWED])\s")?,
        })
    }

    fn plain(pattern: &str) -> Result<Regex, regex::Error> {
        Regex::new(pattern)
    }

    fn any_case(pattern: &str) -> Result<Regex, regex::Error> {
        RegexBuilder::new(pattern).case_insensitive(true).build()
    }

    /// `text` without the keys in it.
    pub fn scrub(&self, text: &str) -> String {
        let mut out = text.to_string();
        for (pattern, kept) in &self.secrets {
            out = pattern.replace_all(&out, *kept).into_owned();
        }
        out
    }
}

/// The log of one process; a log of nothing keeps nothing and reads nothing.
#[derive(Debug, Clone)]
pub struct CellLog {
    path: Option<PathBuf>,
    patterns: Arc<LogPatterns>,
}

impl CellLog {
    const TAIL_LINES: usize = 8;
    const TAIL_CHARS: usize = 1500;
    const TAIL_BYTES: u64 = 64 * 1024;
    const VIEW_LINES: i64 = 300;
    const VIEW_MAX: i64 = 2000;
    const VIEW_BYTES: u64 = 512 * 1024;
    const KEPT_RUNS: usize = 15;
    const REASON_CHARS: usize = 300;
    /// Actionable patterns the board can classify into friendly messages. Not level-filtered on purpose: nothing benign says "corrupted or incomplete", and
    /// the corrupted download's repair reads this very answer.
    const PRIORITY: [&'static str; 15] = [
        "invalid ggml type",
        "unsupported quantization",
        "not within the file bounds",
        "corrupted or incomplete",
        "unexpected end of file",
        "out of memory",
        "cudaerroromemoryallocation",
        "failed to allocate",
        "not enough memory",
        "mismatch between text model",
        "wrong mmproj",
        "mtmd_init_from_file",
        "no such file",
        "failed to open",
        "no kernel image",
    ];
    const MARKERS: [&'static str; 5] = ["error", "abort", "failed", "invalid argument", "what()"];
    const CATASTROPHES: [&'static str; 6] =
        ["terminate called", "what():", "traceback", "cuda error", "segmentation fault", "killed"];

    /// The log at `path`.
    pub fn new(path: Option<PathBuf>, patterns: Arc<LogPatterns>) -> Self {
        Self { path, patterns }
    }

    /// Where it is written.
    pub fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    /// The end of the file, at most `bytes`: the text and whether it began in the middle of the file.
    fn end_of_file(&self, bytes: u64) -> Option<(String, bool)> {
        let mut file = fs::File::open(self.path.as_ref()?).ok()?;
        let size = file.seek(SeekFrom::End(0)).ok()?;
        file.seek(SeekFrom::Start(size.saturating_sub(bytes))).ok()?;
        let mut raw = Vec::new();
        file.read_to_end(&mut raw).ok()?;
        Some((String::from_utf8_lossy(&raw).into_owned(), size > bytes))
    }

    /// The last lines the process wrote, keys scrubbed: what the card shows on hover. "" when there is no log or nothing in it.
    pub fn tail(&self) -> String {
        let Some((text, _)) = self.end_of_file(Self::TAIL_BYTES) else {
            return String::new();
        };
        let lines: Vec<&str> = text.lines().filter(|line| !line.trim().is_empty()).map(str::trim_end).collect();
        let (_, last) = lines.split_at(lines.len().saturating_sub(Self::TAIL_LINES));
        let scrubbed = self.patterns.scrub(&last.join("\n"));
        let letters: Vec<char> = scrubbed.chars().collect();
        letters.split_at(letters.len().saturating_sub(Self::TAIL_CHARS)).1.iter().collect()
    }

    /// How many lines a view asks for: a whole number between 1 and 2000, 300 for anything that is not a number.
    pub fn view_count(asked: Option<&str>) -> usize {
        // absent-ok: not said or no number is the view's own default.
        let count = asked.and_then(|word| word.trim().parse::<i64>().ok()).unwrap_or(Self::VIEW_LINES);
        // absent-ok: a clamp to 1..=2000 always fits.
        usize::try_from(count.clamp(1, Self::VIEW_MAX)).unwrap_or(1)
    }

    /// The last lines of the log, keys scrubbed and blank lines left out: what the board's window shows of a run. Read from the middle of a long file, the first
    /// line is the end of a line: it is left out, not shown cut.
    pub fn lines(&self, asked: Option<&str>) -> Vec<String> {
        let Some((text, cut)) = self.end_of_file(Self::VIEW_BYTES) else {
            return Vec::new();
        };
        let kept: Vec<&str> =
            text.lines().skip(usize::from(cut)).filter(|line| !line.trim().is_empty()).map(str::trim_end).collect();
        let (_, last) = kept.split_at(kept.len().saturating_sub(Self::view_count(asked)));
        last.iter().map(|line| self.patterns.scrub(line)).collect()
    }

    fn stem_and_suffix(path: &Path) -> (String, String) {
        let name = |part: Option<&std::ffi::OsStr>| part.map_or_else(String::new, |part| part.to_string_lossy().into_owned());
        let suffix = path.extension().map_or_else(String::new, |extension| format!(".{}", extension.to_string_lossy()));
        (name(path.file_stem()), suffix)
    }

    /// The files rotate kept of the runs before this one.
    fn kept_runs(&self, path: &Path) -> Vec<PathBuf> {
        let (stem, suffix) = Self::stem_and_suffix(path);
        let folder = path.parent().unwrap_or(Path::new("."));
        let Ok(entries) = fs::read_dir(folder) else {
            return Vec::new();
        };
        entries
            .flatten()
            .map(|entry| entry.path())
            .filter(|file| {
                let name = file.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
                let middle = name.strip_prefix(&format!("{stem}.")).and_then(|rest| rest.strip_suffix(suffix.as_str()));
                file.is_file() && middle.is_some_and(|middle| self.patterns.run_stamp.is_match(middle))
            })
            .collect()
    }

    /// This log and the logs rotate kept of the runs before it, newest first: `[{name, bytes, modifiedAt}]`. Nothing for a process with no log, or when none of them is there.
    pub fn runs(&self) -> Vec<Value> {
        let Some(path) = &self.path else {
            return Vec::new();
        };
        let mut found = if path.is_file() { vec![path.clone()] } else { Vec::new() };
        found.extend(self.kept_runs(path));
        let mut rows: Vec<(i64, Value)> = found
            .iter()
            .filter_map(|file| {
                let meta = file.metadata().ok()?;
                let modified = FileTimes::modified(&meta);
                let name = file.file_name()?.to_string_lossy().into_owned();
                Some((modified, json!({"name": name, "bytes": meta.len(), "modifiedAt": modified})))
            })
            .collect();
        rows.sort_by_key(|(modified, _)| std::cmp::Reverse(*modified));
        rows.into_iter().map(|(_, row)| row).collect()
    }

    /// The log of the run named `name`: this log's own file, or a file rotate kept of it. `None` for any other name: no other file of the folder is read.
    pub fn run(&self, name: &str) -> Option<Self> {
        let path = self.path.as_ref().filter(|_| !name.is_empty())?;
        let known = self.runs().iter().any(|row| row.get("name").and_then(Value::as_str) == Some(name));
        known.then(|| Self::new(Some(path.with_file_name(name)), Arc::clone(&self.patterns)))
    }

    /// The reason the process died, keys scrubbed.
    pub fn crash_reason(&self) -> String {
        self.patterns.scrub(&self.reason())
    }

    fn first_letters(line: &str) -> String {
        line.chars().take(Self::REASON_CHARS).collect()
    }

    /// A concise reason from the tail of the log: corruption and memory patterns first, then an exception line of a log with no levels, then any error line, then the
    /// last line. Level-aware: on a log of `<time> <LEVEL> <subsys>:` the informational and warning lines are skipped, and the blind fallback is dropped.
    fn reason(&self) -> String {
        let Some(text) = self.path.as_ref().and_then(|path| fs::read(path).ok()) else {
            return String::new();
        };
        let text = String::from_utf8_lossy(&text);
        let lines: Vec<&str> = text.lines().filter(|line| !line.trim().is_empty()).map(str::trim_end).collect();
        let patterns = &self.patterns;
        let (_, last_lines) = lines.split_at(lines.len().saturating_sub(80));
        let tail: Vec<&str> = last_lines
            .iter()
            .copied()
            .filter(|line| {
                !(patterns.debugger_noise.is_match(line)
                    || patterns.library_footers.is_match(line)
                    || patterns.progress_noise.is_match(line))
            })
            .collect();
        let level_of =
            |line: &str| patterns.level.captures(line).and_then(|found| found.get(1)).map(|level| level.as_str().to_string());
        let levelled = tail.iter().any(|line| level_of(line).is_some());
        let found = |test: &dyn Fn(&str, &str) -> bool| {
            tail.iter().rev().find(|line| test(line, &line.to_lowercase())).map(|line| Self::first_letters(line))
        };
        if let Some(line) = found(&|_, low| Self::PRIORITY.iter().any(|word| low.contains(word))) {
            return line;
        }
        if !levelled {
            let exception = found(&|line, _| patterns.exception_line.is_match(line) && !patterns.cause_elsewhere.is_match(line));
            if let Some(line) = exception {
                return line;
            }
        }
        let skip = |line: &str| levelled && matches!(level_of(line).as_deref(), Some("I" | "W"));
        let marked =
            found(&|line, low| !skip(line) && Self::MARKERS.iter().any(|word| low.contains(word)) && !low.contains("build:"));
        if let Some(line) = marked {
            return line;
        }
        if let Some(line) = found(&|_, low| Self::CATASTROPHES.iter().any(|word| low.contains(word))) {
            return line;
        }
        // A levelled log with nothing but I and W left: why it went is not known, and saying nothing beats blaming the last harmless line.
        if levelled {
            return String::new();
        }
        tail.last().map_or_else(String::new, |line| Self::first_letters(line))
    }

    /// The file this run writes to, opened fresh: its folder made first, and the previous run's log kept aside. `None` without a path.
    pub fn open_new(&self, now: i64) -> std::io::Result<Option<fs::File>> {
        let Some(path) = &self.path else {
            return Ok(None);
        };
        if let Some(folder) = path.parent() {
            fs::create_dir_all(folder)?;
        }
        self.rotate(now);
        fs::File::create(path).map(Some)
    }

    /// The previous run's log moved aside instead of truncated: a start wipes the log of a crash otherwise. The newest 15 are kept; logging never blocks a start.
    fn rotate(&self, now: i64) {
        let Some(path) = &self.path else {
            return;
        };
        let (stem, suffix) = Self::stem_and_suffix(path);
        if path.metadata().is_ok_and(|meta| meta.len() > 0) {
            let stamp = LocalTime::of(now).map_or_else(String::new, |at| at.compact());
            let mut aside = path.with_file_name(format!("{stem}.{stamp}{suffix}"));
            let mut more = 1;
            while aside.exists() {
                aside = path.with_file_name(format!("{stem}.{stamp}-{more}{suffix}"));
                more += 1;
            }
            if let Err(error) = fs::rename(path, &aside) {
                Log::line(&format!("[cells] a log was not kept aside: {error}"));
            }
        }
        let mut kept: Vec<(i64, PathBuf)> = self
            .all_rotated(path, &stem, &suffix)
            .into_iter()
            // absent-ok: a file gone since the listing is the oldest there is: the next to go.
            .map(|file| (file.metadata().map_or(0, |meta| FileTimes::modified(&meta)), file))
            .collect();
        kept.sort_by_key(|(modified, _)| std::cmp::Reverse(*modified));
        for (_, old) in kept.iter().skip(Self::KEPT_RUNS) {
            // What cannot be removed stays until the next start: logging never blocks one.
            drop(fs::remove_file(old));
        }
    }

    /// `p.parent.glob(f"{p.stem}.*{p.suffix}")`.
    fn all_rotated(&self, path: &Path, stem: &str, suffix: &str) -> Vec<PathBuf> {
        let folder = path.parent().unwrap_or(Path::new("."));
        let Ok(entries) = fs::read_dir(folder) else {
            return Vec::new();
        };
        let prefix = format!("{stem}.");
        entries
            .flatten()
            .map(|entry| entry.path())
            .filter(|file| {
                file.file_name().is_some_and(|name| {
                    let name = name.to_string_lossy();
                    name.starts_with(&prefix) && name.ends_with(suffix) && name.len() >= prefix.len() + suffix.len()
                })
            })
            .collect()
    }
}

/// The times of a file, as whole seconds.
pub struct FileTimes;

impl FileTimes {
    /// `int(st_mtime)`; 0 when the system does not say.
    pub fn modified(meta: &fs::Metadata) -> i64 {
        use std::os::unix::fs::MetadataExt;
        meta.mtime()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn log_of(name: &str, text: &str) -> (CellLog, PathBuf) {
        let folder = std::env::temp_dir().join(format!("caravan-cell-log-{name}-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let path = folder.join("llama-server.log");
        fs::write(&path, text).unwrap();
        (CellLog::new(Some(path), Arc::new(LogPatterns::new().unwrap())), folder)
    }

    #[test]
    fn every_pattern_compiles_and_means_what_it_says() {
        let patterns = LogPatterns::new().unwrap();
        assert!(patterns.level.is_match("0.00.817.809 W load: x"));
        assert!(patterns.run_stamp.is_match("20261101-120000-2"));
        assert!(!patterns.run_stamp.is_match("x20261101-120000"));
        assert!(
            patterns.exception_line.is_match("(EngineCore pid=2087114) torch._inductor.exc.InductorError: AssertionError: x")
        );
        assert!(patterns.cause_elsewhere.is_match("RuntimeError: Engine core initialization failed. See root cause above."));
    }

    #[test]
    fn a_key_goes_and_its_name_stays() {
        let patterns = LogPatterns::new().unwrap();
        for (line, want) in [
            ("key sk-abcdef1234 here", "key sk-… here"),
            ("Authorization: Bearer abc.def", "Authorization: Bearer …"),
            ("api_key=abc123", "api_key=…"),
            ("\"password\": \"hunter2\"", "\"password\": \"…\""),
            ("EOS token = 151645", "EOS token = 151645"),
            ("auth_token = abcdefghijklmnop", "auth_token = …"),
        ] {
            assert_eq!(patterns.scrub(line), want, "{line}");
        }
    }

    #[test]
    fn the_reason_reads_past_what_only_follows_the_cause() {
        let reason = |text: &str| {
            let (log, folder) = log_of("reason", text);
            let said = log.crash_reason();
            fs::remove_dir_all(folder).unwrap();
            said
        };
        assert_eq!(reason("0.1 I load: fine\n0.2 W load: odd\n"), "", "a levelled log with nothing but I and W");
        assert_eq!(reason("plain words\nlast words\n"), "last words", "a log of no levels ends in its last line");
        assert_eq!(reason("0.1 E main: something failed\n0.2 I load: fine\n"), "0.1 E main: something failed");
        assert_eq!(reason("error: out of memory\n#3  0x00007f in ggml_abort () from x\n"), "error: out of memory");
        assert_eq!(
            reason("ValueError: the cause\nRuntimeError: Engine core initialization failed. See root cause above.\n"),
            "ValueError: the cause"
        );
        assert_eq!(
            reason("Value error, bad\nFor further information visit https://errors.pydantic.dev/2/x\n"),
            "Value error, bad"
        );
    }

    #[test]
    fn a_new_run_keeps_the_last_one_aside() {
        let (log, folder) = log_of("rotate", "the crash");
        drop(log.open_new(1_700_000_000).unwrap());
        let names: Vec<String> = log.runs().iter().map(|row| row["name"].as_str().unwrap().to_string()).collect();
        assert_eq!(names.len(), 2, "{names:?}");
        let kept = names.iter().find(|name| name.as_str() != "llama-server.log").unwrap();
        assert_eq!(log.run(kept).unwrap().tail(), "the crash");
        assert!(log.run("../other").is_none());
        fs::remove_dir_all(folder).unwrap();
    }
}
