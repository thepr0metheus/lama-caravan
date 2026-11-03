//! How files leave the cache: only what this scout wrote down, never what a running cell holds, never what is being written. The purging part of `ModelFetcher`.

use crate::log::Log;
use crate::models::fetcher::ModelFetcher;
use crate::models::files::{Resolved, Walk};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

/// What a removal is asked.
#[derive(Debug, Default)]
struct Removal {
    /// The kinds of file: `None` for any.
    suffixes: Option<&'static [&'static str]>,
    keep: BTreeSet<PathBuf>,
    /// With these resolved paths, nothing but them.
    only: Option<BTreeSet<PathBuf>>,
}

impl ModelFetcher {
    const MODEL_SUFFIXES: [&'static str; 2] = ["gguf", "tmp"];

    /// Deletes the downloaded files of these kinds that are not kept, the folders they leave empty, and the downloaded model folders: a folder holding a kept path is kept. What is being written now is never
    /// deleted. (what was deleted, the bytes freed)
    fn delete_downloaded(&self, removal: &Removal) -> (Vec<PathBuf>, u64) {
        let cache_dir = self.cache_dir();
        let of_kind = |path: &Path| {
            let suffix = path.extension().map(|suffix| suffix.to_string_lossy().into_owned());
            removal.suffixes.is_none_or(|kinds| suffix.is_some_and(|suffix| kinds.contains(&suffix.as_str())))
        };
        let (mut deleted, mut freed) = (Vec::new(), 0);
        for path in self.downloaded.paths() {
            if path.symlink_metadata().is_err() && !path.exists() {
                self.downloaded.forget(&path);
                continue;
            }
            let is_folder = path.is_dir() && !path.symlink_metadata().is_ok_and(|meta| meta.file_type().is_symlink());
            if !is_folder && !of_kind(&path) {
                continue;
            }
            let resolved = Resolved::of(&path);
            let not_asked = removal.only.as_ref().is_some_and(|only| !only.contains(&resolved));
            if not_asked || removal.keep.contains(&resolved) || self.is_flying(&path) {
                continue;
            }
            if is_folder && removal.keep.iter().any(|kept| kept.starts_with(&resolved)) {
                continue;
            }
            let size = Self::size_of(&path);
            let gone = if is_folder { fs::remove_dir_all(&path) } else { fs::remove_file(&path) };
            if gone.is_err() {
                continue;
            }
            self.downloaded.forget(&path);
            freed += size;
            Self::parents_left_empty(&path, &cache_dir);
            deleted.push(path);
        }
        (deleted, freed)
    }

    pub(super) fn parents_left_empty(path: &Path, cache_dir: &Path) {
        let mut parent = path.parent();
        while let Some(folder) = parent.filter(|folder| *folder != cache_dir && folder.is_dir()) {
            // Only an empty folder goes: the first that holds anything ends the walk.
            if fs::remove_dir(folder).is_err() {
                break;
            }
            parent = folder.parent();
        }
    }

    /// Bytes a file or a folder takes: a link counted as a link, not as what it points at, for a Hugging Face cache links its snapshots to blobs.
    pub fn size_of(path: &Path) -> u64 {
        if !path.is_dir() {
            // absent-ok: a file gone since it was listed takes nothing.
            return fs::metadata(path).map_or(0, |meta| meta.len());
        }
        Walk::entries(path)
            .iter()
            .filter_map(|file| file.symlink_metadata().ok())
            .filter(|meta| meta.file_type().is_symlink() || meta.is_file())
            .map(|meta| meta.len())
            .sum()
    }

    /// Bytes the files and folders this scout downloaded take now: what the record says is its own and the disk still holds.
    pub fn footprint(&self) -> u64 {
        self.downloaded.paths().iter().filter(|path| path.exists()).map(|path| Self::size_of(path)).sum()
    }

    fn resolved_all(paths: &[String]) -> BTreeSet<PathBuf> {
        paths.iter().filter(|path| !path.is_empty()).map(|path| Resolved::of(Path::new(path))).collect()
    }

    fn removed(deleted: &[PathBuf], freed: u64) -> Value {
        json!({"removed": deleted.len(), "freedBytes": freed})
    }

    /// Deletes the `.gguf` and `.tmp` files and the model folders this scout downloaded, but `keep`: on demand, the purge-cache endpoint's.
    pub fn purge(&self, keep: &[String]) -> Value {
        let removal = Removal { suffixes: Some(&Self::MODEL_SUFFIXES), keep: Self::resolved_all(keep), only: None };
        let (deleted, freed) = self.delete_downloaded(&removal);
        if !deleted.is_empty() {
            Log::line(&format!("[llama-node] purge cache: removed {} file(s), freed {freed} bytes", deleted.len()));
        }
        Self::removed(&deleted, freed)
    }

    /// Deletes everything this scout downloaded into the cache, of any kind, but what is being written: the cache is moving to another folder, and a start brings its model there by itself.
    pub fn clear(&self) -> Value {
        let (deleted, freed) = self.delete_downloaded(&Removal::default());
        Self::removed(&deleted, freed)
    }

    /// Deletes these files, the models of a stopped cell that keeps no cache, and nothing else. One stop of an Ollama cell, which has no file here at all, once deleted 92 GB of other cells' models.
    pub fn release(&self, files: &[String], keep: &[String]) -> Value {
        let only = Self::resolved_all(files);
        if only.is_empty() {
            return json!({"removed": 0, "freedBytes": 0});
        }
        let removal = Removal { suffixes: Some(&Self::MODEL_SUFFIXES), keep: Self::resolved_all(keep), only: Some(only) };
        let (deleted, freed) = self.delete_downloaded(&removal);
        if !deleted.is_empty() {
            Log::line(&format!("[llama-node] a stopped cell's models: removed {} file(s), freed {freed} bytes", deleted.len()));
        }
        Self::removed(&deleted, freed)
    }

    /// Deletes these files to make room on the disk, and nothing else.
    pub fn evict(&self, files: &[String], keep: &[String]) -> Value {
        let removal = Removal { suffixes: None, keep: Self::resolved_all(keep), only: Some(Self::resolved_all(files)) };
        let (deleted, freed) = self.delete_downloaded(&removal);
        if !deleted.is_empty() {
            Log::line(&format!("[llama-node] to make room: removed {} file(s), freed {freed} bytes", deleted.len()));
        }
        Self::removed(&deleted, freed)
    }

    /// Bytes the cells' scratch folders take: what they made from their models, in the work folder.
    pub fn scratch_bytes(&self) -> u64 {
        Self::size_of(&self.scratch_root())
    }

    /// The cells' scratch folders, by port. A folder with no port's name is not one of them.
    pub fn scratch_folders(&self) -> Vec<(i64, PathBuf)> {
        let folders = fs::read_dir(self.scratch_root()).into_iter().flatten().flatten();
        folders
            .filter_map(|folder| folder.file_name().to_string_lossy().parse::<i64>().ok().map(|port| (port, folder.path())))
            .collect()
    }

    /// Removes the scratch folders of every port but `keep`. (the files removed, the bytes freed)
    pub fn clear_scratches(&self, keep: &BTreeSet<i64>) -> (u64, u64) {
        let (mut files, mut freed) = (0, 0);
        for (_, folder) in self.scratch_folders().into_iter().filter(|(port, _)| !keep.contains(port)) {
            let size = Self::size_of(&folder);
            let count = Walk::files_with_sizes(&folder).len() as u64;
            if fs::remove_dir_all(&folder).is_ok() {
                files += count;
                freed += size;
            }
        }
        (files, freed)
    }

    /// The `.gguf` files in the cache's folder.
    pub fn listing(&self) -> Vec<Value> {
        let cache_dir = self.cache_dir();
        Walk::entries(&cache_dir)
            .iter()
            .filter(|path| path.extension().is_some_and(|suffix| suffix == "gguf"))
            .filter_map(|path| {
                let rel = path.strip_prefix(&cache_dir).ok()?;
                Some(json!({"path": rel.display().to_string(), "sizeBytes": fs::metadata(path).ok()?.len()}))
            })
            .collect()
    }
}
