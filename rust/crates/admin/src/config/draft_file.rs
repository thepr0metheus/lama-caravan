//! The draft rule by the name the builder reads it under.

use crate::common::draft::DraftFile;

/// `DraftFile(path).launch_type`.
pub struct DraftFileWord;

impl DraftFileWord {
    /// The type a cell with no type of its own launches the file with.
    pub fn launch_type(path: &str) -> &'static str {
        DraftFile::new(path).launch_type()
    }
}
