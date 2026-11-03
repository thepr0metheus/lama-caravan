//! What says a folder is a library of the caravan's: the controller leaves it at the top of the folder, and a machine that mounts the folder finds it there.

/// The mark.
pub struct LibraryMark;

impl LibraryMark {
    /// The name of its file, at the top of a library.
    pub const NAME: &'static str = ".caravan-store.json";
}
