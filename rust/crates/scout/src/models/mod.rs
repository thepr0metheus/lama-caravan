//! The model cache on this machine: files downloaded from the controller, verified, and purged.

mod cache_move;
pub mod cache_off;
mod cleanup;
mod copy;
pub mod fetcher;
pub mod files;
mod folder;
pub mod folders;
mod foreign;
pub mod keeper;
pub mod pace;
pub mod relocate;
mod room;
pub mod shelf;
#[cfg(test)]
mod tests;
pub mod uses;
pub mod view;
mod work;

pub use cache_off::CacheOff;
pub use fetcher::{Fetch, ModelFetcher, Progress, RoomMaker};
pub use files::{DownloadedFiles, Resolved, SplitGguf, Walk};
pub use folders::Folders;
pub use keeper::{CacheKeeper, CellsInUse};
pub use pace::CopyPace;
pub use shelf::{Shelf, ShelfParts};
