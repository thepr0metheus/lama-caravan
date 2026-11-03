//! Which commit a checkout's code is: `git rev-parse` of the checkout, else the commit an image build baked into CARAVAN_GIT_HEAD (the image ships without .git), else the commit `git archive` wrote into VERSION, else nothing: an empty string, never a guessed number.

use plumbing::Commands;
use rules::Coerce;
use std::path::Path;
use std::time::Duration;

/// The commit of the checkout at a folder, and where the answer came from.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CheckoutCommit {
    /// "" when none names one.
    pub commit: String,
    /// Whether git said it.
    pub from_git: bool,
    /// Whether the build's word said it.
    pub baked: bool,
    /// Git's own complaint, for a caller that shows why git did not answer.
    pub error: String,
}

impl CheckoutCommit {
    /// The variable an image build bakes its commit into.
    pub const BAKED_ENV: &'static str = "CARAVAN_GIT_HEAD";

    /// The commit at `root`, as `git -C` reads it.
    pub fn of(root: &Path, short: bool, baked_env: Option<&str>, commands: &dyn Commands) -> Self {
        let place = root.to_string_lossy().into_owned();
        let mut argv = vec!["git", "-C", place.as_str(), "rev-parse"];
        if short {
            argv.push("--short");
        }
        argv.push("HEAD");
        let head = commands.run(&argv, Duration::from_secs(3));
        let (found, error) = match &head {
            Ok(ran) if ran.ok() => (Coerce::strip(&ran.stdout).to_string(), String::new()),
            Ok(ran) => (String::new(), Coerce::strip(&ran.stderr).to_string()),
            Err(no) => (String::new(), Coerce::strip(&no.words("git")).to_string()),
        };
        let baked = if found.is_empty() {
            // absent-ok: a program built with no commit says none.
            let said = Coerce::strip(baked_env.unwrap_or_default()).to_string();
            if said.is_empty() { Self::archived(root) } else { said }
        } else {
            String::new()
        };
        Self {
            from_git: !found.is_empty(),
            baked: !baked.is_empty(),
            commit: if found.is_empty() { baked } else { found },
            error,
        }
    }

    /// The commit `git archive` wrote into VERSION, or "". A checkout's own VERSION still reads `$Format:%h$`, which names nothing.
    pub fn archived(root: &Path) -> String {
        let Ok(text) = std::fs::read_to_string(root.join("VERSION")) else {
            return String::new();
        };
        let text = Coerce::strip(&text);
        let is_commit =
            (4..=40).contains(&text.len()) && text.chars().all(|letter| letter.is_ascii_digit() || ('a'..='f').contains(&letter));
        if is_commit { text.to_string() } else { String::new() }
    }
}
