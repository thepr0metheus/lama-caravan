//! LM Studio's own command line, `lms`, where every LM Studio, the app and its windowless daemon, puts it: `~/.lmstudio/bin/lms`. Its REST API unloads; the command line starts and stops its daemon and server, and says how long a loaded model is held. It talks to the LM Studio of the user it runs as, which is the scout's.

use crate::commands::{Commands, NoAnswer};
use rules::Coerce;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

/// The command line.
pub struct LmsCli {
    home: PathBuf,
    commands: Arc<dyn Commands>,
}

impl LmsCli {
    /// A question is a moment; it is asked inside a scan or a request, which must not hang on it.
    pub const QUICK: Duration = Duration::from_secs(10);
    /// Starting or stopping its daemon and server takes longer.
    pub const SLOW: Duration = Duration::from_secs(300);
    /// LM Studio's daemon copies `lms` over itself as it starts (seen 2026-09-25: `lms daemon up`, then `lms server start` failed with "Text file busy"). A command that meets the copy is tried again, this often and this far apart.
    const BUSY_TRIES: u32 = 20;
    const BUSY_PAUSE: Duration = Duration::from_millis(250);

    /// The `lms` of this home.
    pub fn new(home: PathBuf, commands: Arc<dyn Commands>) -> Self {
        Self { home, commands }
    }

    fn path_in(home: &Path) -> PathBuf {
        home.join(".lmstudio/bin/lms")
    }

    /// Whether it is there, to run.
    pub fn available_in(home: &Path) -> bool {
        std::fs::metadata(Self::path_in(home)).is_ok_and(|meta| meta.permissions().mode() & 0o111 != 0)
    }

    /// Whether this one is there.
    pub fn available(&self) -> bool {
        Self::available_in(&self.home)
    }

    /// What a failed command said, without its progress lines and the advice after them.
    pub fn said(text: &str) -> String {
        let lines: Vec<&str> =
            text.lines().map(Coerce::strip).filter(|line| !line.is_empty() && !line.starts_with("Loading ")).take(2).collect();
        Coerce::first_letters(&lines.join(" — "), 300).to_string()
    }

    /// `\x1b\[[0-9;?]*[A-Za-z]`.
    fn without_codes(text: &str) -> String {
        let mut out = String::with_capacity(text.len());
        let mut rest = text;
        while let Some(at) = rest.find("\u{1b}[") {
            let (head, tail) = rest.split_at(at);
            out.push_str(head);
            let codes = tail.strip_prefix("\u{1b}[").unwrap_or(tail);
            let length =
                codes.find(|letter: char| !(letter.is_ascii_digit() || matches!(letter, ';' | '?'))).unwrap_or(codes.len());
            let (_, after) = codes.split_at(length);
            let mut letters = after.chars();
            if letters.next().is_some_and(|letter| letter.is_ascii_alphabetic()) {
                rest = letters.as_str();
            } else {
                out.push_str("\u{1b}[");
                rest = codes;
            }
        }
        out.push_str(rest);
        out
    }

    /// (exit code, what it printed, colours stripped); the code is `None` when it did not run or did not finish.
    pub fn run(&self, args: &[&str], timeout: Duration) -> (Option<i32>, String) {
        let path = Self::path_in(&self.home);
        if !self.available() {
            return (None, format!("no lms at {}", path.display()));
        }
        let name = path.display().to_string();
        let mut argv = vec![name.as_str()];
        argv.extend_from_slice(args);
        for attempt in 0..Self::BUSY_TRIES {
            match self.commands.run(&argv, timeout) {
                Ok(ran) => return (ran.code, Self::without_codes(&format!("{}{}", ran.stdout, ran.stderr)).replace('\r', "\n")),
                Err(NoAnswer::TimedOut) => return (None, format!("lms did not finish in {} s", timeout.as_secs())),
                Err(NoAnswer::Failed(words)) if words.contains("Text file busy") && attempt + 1 < Self::BUSY_TRIES => {
                    std::thread::sleep(Self::BUSY_PAUSE)
                }
                Err(NoAnswer::Failed(words)) => return (None, format!("lms did not run: {words}")),
                Err(NoAnswer::NotFound) => return (None, "lms did not run: not found".to_string()),
            }
        }
        (None, "lms did not run".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codes_go_and_what_a_failure_said_stays() {
        assert_eq!(LmsCli::without_codes("\u{1b}[?25lok\u{1b}[0m"), "ok");
        assert_eq!(LmsCli::said("Loading x\n  Model not found \n\nNo model\nadvice"), "Model not found — No model");
    }
}
