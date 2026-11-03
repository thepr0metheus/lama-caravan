//! A model's file given to a scout, whole or a part of it: the copy of a cache and the reads of a machine that keeps none come here.

use super::checkpoints::ModelCheckpoints;
use super::model_list::ModelList;
use super::walk::{RelPath, Resolved};
use crate::web::Exchange;
use rules::{AppError, ByteRange, Coerce};
use std::io::{Read, Seek};
use std::path::PathBuf;

impl ModelCheckpoints<'_> {
    /// The head of an answer with a file of `whole` bytes in it: what a `Range` field asks, or all of it. (where it starts, how much) to send; `None` when nothing is. A part is how a machine with no copy
    /// reads a model (the scout's `LibraryView`), as a program asks for it.
    fn started(h: &mut Exchange<'_>, whole: u64, name: &str) -> Option<(u64, u64)> {
        let kind = ("Content-Type", "application/octet-stream".to_string());
        let named = ("Content-Disposition", format!("attachment; filename=\"{name}\""));
        match ByteRange::of(h.field("Range").as_deref(), whole) {
            ByteRange::Whole => {
                h.start(200, &[kind, ("Content-Length", whole.to_string()), named]);
                Some((0, whole))
            }
            ByteRange::Part { from, to } => {
                let told = ("Content-Range", format!("bytes {from}-{to}/{whole}"));
                h.start(206, &[kind, ("Content-Length", (to - from + 1).to_string()), told, named]);
                Some((from, to - from + 1))
            }
            ByteRange::PastEnd => {
                h.start(416, &[("Content-Length", "0".to_string()), ("Content-Range", format!("bytes */{whole}"))]);
                None
            }
        }
    }

    /// The file of `rel` in a library, as this host reads it. Only what a look at the libraries found: `rel` is a key here, and leads nowhere else.
    fn in_a_library(&self, rel: &str) -> Option<PathBuf> {
        let models_dir = self.app.models_dir();
        let found = ModelList::locations(self.app, false).locate(rel, &models_dir.to_string_lossy())?;
        found.in_library().then(|| PathBuf::from(found.path)).filter(|path| path.is_file())
    }

    /// Streams a model file to the requesting scout: of the models folder or of a library, so that a machine needs no mount of its own.
    pub fn serve_file(&self, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let rel = Coerce::strip(&h.parsed.param_or("path", "")).to_string();
        let empty_answer = |h: &mut Exchange<'_>, status: u16| h.start(status, &[("Content-Length", "0".to_string())]);
        if rel.is_empty() {
            empty_answer(h, 400);
            return Ok(());
        }
        let models_dir = self.app.models_dir();
        let base = std::fs::canonicalize(&models_dir).unwrap_or_else(|_| models_dir.clone());
        let target = Resolved::under(&base, &rel);
        if !target.starts_with(&base) {
            empty_answer(h, 403);
            return Ok(());
        }
        let Some(target) = Some(target).filter(|target| target.is_file()).or_else(|| self.in_a_library(&rel)) else {
            empty_answer(h, 404);
            return Ok(());
        };
        let whole = std::fs::metadata(&target).map_err(|error| AppError::with_status(error.to_string(), 500))?.len();
        let name = RelPath::name(&target.to_string_lossy()).to_string();
        let Some((from, size)) = Self::started(h, whole, &name) else {
            return Ok(());
        };
        let mut file = std::fs::File::open(&target).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        file.seek(std::io::SeekFrom::Start(from)).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        let mut chunk = vec![0u8; 1 << 20];
        let mut sent = 0u64;
        while sent < size {
            let room = chunk.len().min(usize::try_from(size - sent).unwrap_or(usize::MAX));
            let read = file
                .read(chunk.get_mut(..room).unwrap_or_default())
                .map_err(|error| AppError::with_status(error.to_string(), 500))?;
            let Some(bytes) = chunk.get(..read).filter(|bytes| !bytes.is_empty()) else {
                break;
            };
            h.write(bytes);
            if h.close {
                return Ok(());
            }
            sent += read as u64;
        }
        if sent != size {
            h.close = true;
            plumbing::Log::line(&format!("short read serving {rel}: {sent} of {size} bytes"));
        }
        Ok(())
    }
}
