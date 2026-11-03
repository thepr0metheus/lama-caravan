//! A question to the machine's tools. A parameter, so that a test answers it: a program under test must never reach for the machine.

use std::io::{self, Read};
use std::process::{Command, Stdio};
use std::time::Duration;

/// What a tool said.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Ran {
    /// Its exit code; `None` when a signal ended it.
    pub code: Option<i32>,
    /// Its standard output.
    pub stdout: String,
    /// Its standard error.
    pub stderr: String,
}

impl Ran {
    /// Whether it exited with 0.
    pub fn ok(&self) -> bool {
        self.code == Some(0)
    }

    /// Its exit code in words: a signal has none to say.
    pub fn code_word(&self) -> String {
        self.code.map_or_else(|| "by a signal".to_string(), |code| code.to_string())
    }
}

/// Why a tool did not answer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NoAnswer {
    /// There is no such tool here.
    NotFound,
    /// It outlived its time, and was killed.
    TimedOut,
    /// It did not start, in the system's words.
    Failed(String),
}

impl NoAnswer {
    /// The words of why `tool` did not answer, as Python's error says them.
    pub fn words(&self, tool: &str) -> String {
        match self {
            Self::NotFound => format!("[Errno 2] No such file or directory: '{tool}'"),
            Self::TimedOut => format!("{tool} did not answer in time"),
            Self::Failed(words) => words.clone(),
        }
    }
}

/// Who answers the questions.
pub trait Commands: Send + Sync {
    /// Runs `argv`, for `timeout` at most.
    fn run(&self, argv: &[&str], timeout: Duration) -> Result<Ran, NoAnswer>;
}

/// The machine's own tools.
pub struct SystemCommands;

impl SystemCommands {
    const TURN: Duration = Duration::from_millis(20);

    fn collected(pipe: Option<impl Read + Send + 'static>) -> std::thread::JoinHandle<Vec<u8>> {
        std::thread::spawn(move || {
            let mut out = Vec::new();
            if let Some(mut pipe) = pipe {
                // What came before a read failed is what it said.
                drop(pipe.read_to_end(&mut out));
            }
            out
        })
    }

    fn text(reader: std::thread::JoinHandle<Vec<u8>>) -> String {
        // absent-ok: a reader that panicked read nothing, and a tool that said nothing is a known answer.
        String::from_utf8_lossy(&reader.join().unwrap_or_default()).into_owned()
    }
}

impl Commands for SystemCommands {
    fn run(&self, argv: &[&str], timeout: Duration) -> Result<Ran, NoAnswer> {
        let (program, rest) = argv.split_first().ok_or_else(|| NoAnswer::Failed("nothing to run".to_string()))?;
        let mut child =
            Command::new(program).args(rest).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().map_err(
                |error| match error.kind() {
                    io::ErrorKind::NotFound => NoAnswer::NotFound,
                    _ => NoAnswer::Failed(error.to_string()),
                },
            )?;
        let (out, err) = (Self::collected(child.stdout.take()), Self::collected(child.stderr.take()));
        let mut spent = Duration::ZERO;
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break status,
                Ok(None) if spent >= timeout => {
                    // It is ending either way: one already gone has nothing to kill.
                    drop(child.kill());
                    drop(child.wait());
                    return Err(NoAnswer::TimedOut);
                }
                Ok(None) => {
                    std::thread::sleep(Self::TURN);
                    spent += Self::TURN;
                }
                Err(error) => return Err(NoAnswer::Failed(error.to_string())),
            }
        };
        Ok(Ran { code: status.code(), stdout: Self::text(out), stderr: Self::text(err) })
    }
}
