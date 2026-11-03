//! What ends a move: the source kept or removed, its trouble said, the store waited for.

use super::*;

impl<'app> Mover<'app> {
    /// Every end that is a library carries its own mark: checked before a byte moves in either direction.
    pub(super) fn stores_here(&self) -> io::Result<()> {
        let ends: Vec<(String, String)> = {
            let job = self.locked();
            [&job.source, &job.target]
                .iter()
                .filter(|end| end.get("kind").and_then(Value::as_str) == Some("library"))
                .map(|end| (Coerce::text(end.get("root")), Coerce::text(end.get("id"))))
                .collect()
        };
        for (root, id) in ends {
            let doc: Option<Value> =
                std::fs::read(Path::new(&root).join(MARKER_NAME)).ok().and_then(|raw| serde_json::from_slice(&raw).ok());
            let found = Coerce::text(doc.as_ref().and_then(|doc| doc.get("id")));
            if found != id {
                let more = if found.is_empty() { String::new() } else { format!(" (it carries {found})") };
                return Err(io::Error::other(format!("{root} does not carry this library's mark{more}")));
            }
        }
        Ok(())
    }

    /// Why the source stays, or "".
    pub(super) fn why_keep(&self, item: usize) -> io::Result<String> {
        let (source_root, target_root) = self.roots();
        let Some(row) = self.locked().items.get(item).cloned() else {
            return Ok(String::new());
        };
        if !row.folder.is_empty() {
            let here: std::collections::BTreeSet<String> = Self::walk_all(&source_root.join(&row.folder))?
                .into_iter()
                .filter(|(kind, ..)| *kind == "file")
                .map(|(_, rel, ..)| rel)
                .collect();
            let cut = row.folder.len() + 1;
            let planned: std::collections::BTreeSet<String> =
                row.files.iter().filter_map(|file| file.rel.get(cut..).map(str::to_string)).collect();
            if here != planned {
                return Ok("folder-changed".to_string());
            }
        }
        for file in &row.files {
            let local = source_root.join(&file.rel);
            if local.exists() && Self::stamp(&local)? != file.stamp {
                return Ok("local-changed".to_string());
            }
            match std::fs::metadata(target_root.join(&file.rel)) {
                Ok(meta) if meta.size() as i64 == file.size => {}
                Ok(_) => return Ok("copy-missing".to_string()),
                Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok("copy-missing".to_string()),
                Err(error) => return Err(error),
            }
        }
        let rels: Vec<String> = row.files.iter().map(|file| file.rel.clone()).collect();
        Ok(if ModelGc::of(self.app).holders(&rels).is_empty() { String::new() } else { "in-use".to_string() })
    }

    pub(super) fn error_word(error: &io::Error) -> String {
        let kind = match error.kind() {
            io::ErrorKind::NotFound => "FileNotFoundError",
            io::ErrorKind::PermissionDenied => "PermissionError",
            _ => "OSError",
        };
        format!("{kind}: {error}")
    }

    /// An operation failed: waits when the library is what is gone; counts it when the library answers. `false` when the item closed.
    pub(super) fn trouble(&self, item: usize, error: &io::Error) -> Result<bool, Stop> {
        let detail = Self::error_word(error);
        if self.library_answers() {
            let errors = self.edit(|job| {
                // absent-ok: an item the job does not hold has copied nothing.
                job.items.get_mut(item).map_or(0, |row| {
                    row.errors += 1;
                    row.errors
                })
            });
            if errors >= Self::MAX_ERRORS {
                self.close(item, "skipped", "errors", &detail);
                return Ok(false);
            }
        }
        self.wait(&detail)?;
        Ok(true)
    }

    pub(super) fn wait(&self, detail: &str) -> Result<(), Stop> {
        self.edit(|job| {
            job.status = "waiting".to_string();
            job.reason = detail.to_string();
        });
        loop {
            for _ in 0..Self::WAIT_S {
                self.check_cancel()?;
                std::thread::sleep(Self::BEAT);
            }
            if self.library_answers() {
                break;
            }
        }
        self.edit(|job| {
            job.status = "running".to_string();
            job.reason.clear();
        });
        Ok(())
    }

    /// While a job waits: every library end answers, carries its own mark, and the target takes writes.
    pub(super) fn library_answers(&self) -> bool {
        let (source, target) = {
            let job = self.locked();
            (job.source.clone(), job.target.clone())
        };
        let probe = StoreProbe::new();
        for (end, is_target) in [(&source, false), (&target, true)] {
            if end.get("kind").and_then(Value::as_str) != Some("library") {
                continue;
            }
            let look = probe.look(&Coerce::text(end.get("root")), false);
            let mark = look.get("marker").filter(|mark| mark.is_object());
            let carries = mark.is_some_and(|mark| Coerce::str_of(mark.get("id")) == Coerce::str_of(end.get("id")));
            if !(Coerce::truthy(look.get("ok")) && Coerce::truthy(look.get("exists")) && carries)
                || (is_target && !Coerce::truthy(look.get("writable")))
            {
                return false;
            }
        }
        true
    }

    pub(super) fn close(&self, item: usize, state: &str, note: &str, detail: &str) {
        let (_, target_root) = self.roots();
        self.edit(|job| {
            if let Some(row) = job.items.get_mut(item) {
                if state != "done" {
                    for file in row.files.iter().filter(|file| file.state != "proven") {
                        Self::discard(&PathBuf::from(format!(
                            "{}{}",
                            target_root.join(&file.rel).to_string_lossy(),
                            Self::PART_SUFFIX
                        )));
                    }
                }
                row.state = state.to_string();
                row.note = note.to_string();
                row.detail = detail.to_string();
            }
        });
    }

    pub(super) fn discard(path: &Path) {
        // One that will not go stays as a partial, and the next try starts from what is synced.
        drop(std::fs::remove_file(path));
    }

    pub(super) fn prune_dirs(&self, folder: &Path, root: &Path) {
        let mut at = folder.to_path_buf();
        while at != root && at.starts_with(root) {
            if std::fs::remove_dir(&at).is_err() {
                return;
            }
            let Some(parent) = at.parent() else {
                return;
            };
            at = parent.to_path_buf();
        }
    }
}
