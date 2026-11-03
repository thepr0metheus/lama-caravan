//! A failure the HTTP surface answers with its own status and words: `AppError`.

pub use rules::{AppError, PyRepr};

/// A system error in the words of `exc.strerror`, without the number Rust adds.
pub struct OsWords;

impl OsWords {
    /// "Permission denied", not "Permission denied (os error 13)".
    pub fn of(error: &std::io::Error) -> String {
        let said = error.to_string();
        match said.rfind(" (os error ") {
            Some(at) => said.get(..at).unwrap_or(&said).to_string(),
            None => said,
        }
    }
}
