//! What a disk has free, where a copy or a move must fit: a parameter of the shelves, so that the program asks the machine's disks and a test says its own figure. Tests that asked the disk they
//! ran on were refused for it: the test of Strata's limit with under 5 GB free on a Mac (2026-11-03), and 28 tests of copies and moves with under 2 GB free (2026-11-07).

use os::Disk;
use std::path::Path;

/// What the disk under a folder has free.
pub trait FreeSpace: Send + Sync {
    /// Bytes free for this user on the disk `folder` lies on; `None` when it does not say.
    fn free_under(&self, folder: &Path) -> Option<u64>;
}

/// The machine's disks, as the system says them.
pub struct SystemDisks;

impl FreeSpace for SystemDisks {
    fn free_under(&self, folder: &Path) -> Option<u64> {
        // A folder not made yet lies on the disk of the nearest one that is.
        let probe = folder.ancestors().find(|up| up.exists()).unwrap_or(folder);
        Disk::usage(probe).map(|(_, free)| free)
    }
}
