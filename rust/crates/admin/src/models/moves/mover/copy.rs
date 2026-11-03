//! One file brought over: copied, read back and proven.

use super::*;

impl<'app> Mover<'app> {
    /// Copies one file and proves the copy; `false` when the item closed.
    pub(super) fn bring(&self, item: usize, file: usize) -> Result<bool, Stop> {
        let (source_root, target_root) = self.roots();
        let Some(found) = self.file_of(item, file) else {
            return Ok(false);
        };
        let (source, last) = (source_root.join(&found.rel), target_root.join(&found.rel));
        let part = PathBuf::from(format!("{}{}", last.to_string_lossy(), Self::PART_SUFFIX));
        loop {
            self.check_cancel()?;
            match self.bring_once(item, file, &source, &last, &part) {
                Ok(Some(done)) => return Ok(done),
                Ok(None) => {}
                Err(Stop::Cancelled) => return Err(Stop::Cancelled),
                Err(Stop::Failed(error)) => {
                    if !self.trouble(item, &error)? {
                        return Ok(false);
                    }
                }
            }
        }
    }

    /// One try: the answer when there is one, none to try again.
    pub(super) fn bring_once(
        &self,
        item: usize,
        file: usize,
        source: &Path,
        last: &Path,
        part: &Path,
    ) -> Result<Option<bool>, Stop> {
        if !source.exists() {
            self.close(item, "skipped", "local-gone", "");
            return Ok(Some(false));
        }
        let Some(found) = self.file_of(item, file) else {
            return Ok(Some(false));
        };
        let stamp = Self::stamp(source)?;
        if found.stamp.is_empty() {
            self.edit(|job| self.on_file(job, item, file, |row| row.stamp.clone_from(&stamp)));
        } else if stamp != found.stamp {
            self.close(item, "skipped", "local-changed", "");
            return Ok(Some(false));
        }
        self.stores_here()?;
        if last.exists() {
            if self.prove(source, last, item, file)? {
                self.proven(item, file, source);
                return Ok(Some(true));
            }
            self.close(item, "skipped", "name-taken", "");
            return Ok(Some(false));
        }
        if let Some(parent) = part.parent() {
            std::fs::create_dir_all(parent)?;
        }
        self.copy(source, part, item, file)?;
        if self.prove(source, part, item, file)? {
            std::fs::rename(part, last)?;
            self.keep_age(last, item, file);
            self.proven(item, file, source);
            return Ok(Some(true));
        }
        Self::discard(part);
        let attempts = self.edit(|job| {
            let mut attempts = 0;
            self.on_file(job, item, file, |row| {
                row.synced = 0;
                row.attempts += 1;
                attempts = row.attempts;
            });
            attempts
        });
        if attempts >= Self::MAX_ATTEMPTS {
            self.close(item, "skipped", "mismatch", "");
            return Ok(Some(false));
        }
        Ok(None)
    }

    pub(super) fn proven(&self, item: usize, file: usize, source: &Path) {
        self.edit(|job| {
            self.on_file(job, item, file, |row| {
                row.state = "proven".to_string();
                row.phase = "proven".to_string();
            });
        });
        let (to_library, id) = {
            let job = self.locked();
            (job.target.get("kind").and_then(Value::as_str) == Some("library"), Coerce::text(job.target.get("id")))
        };
        let Some(found) = self.file_of(item, file).filter(|found| to_library && found.rel.to_lowercase().ends_with(".gguf"))
        else {
            return;
        };
        let raw = ModelHeader::read_cached(self.app, source);
        if !raw.is_empty()
            && let Value::Object(meta) = ModelHeader::runtime_meta(&raw)
        {
            // Not remembered, the header is read again by nobody: the row says less of the model, and nothing else goes wrong.
            drop(self.app.library_meta.remember(&id, &found.rel, found.size, &meta));
        }
    }

    /// The library copy keeps the original's time.
    pub(super) fn keep_age(&self, last: &Path, item: usize, file: usize) {
        let Some(nanos) = self.file_of(item, file).and_then(|found| found.stamp.get(1).copied()) else {
            return;
        };
        let moment = std::time::UNIX_EPOCH + Duration::from_nanos(nanos.max(0) as u64);
        if let Ok(opened) = std::fs::File::options().write(true).open(last) {
            // A file that keeps its new time is the same file: only its age on the page differs.
            drop(opened.set_modified(moment));
        }
    }

    pub(super) fn copy(&self, source: &Path, part: &Path, item: usize, file: usize) -> Result<(), Stop> {
        let Some(found) = self.file_of(item, file) else {
            return Ok(());
        };
        // absent-ok: no partial yet starts at the beginning.
        let mut offset = std::fs::metadata(part).map_or(0, |meta| meta.size() as i64);
        if offset > found.synced {
            std::fs::OpenOptions::new().write(true).open(part)?.set_len(found.synced as u64)?;
            offset = found.synced;
        }
        self.edit(|job| {
            self.on_file(job, item, file, |row| {
                row.phase = "copying".to_string();
                row.done = offset;
            });
        });
        let mut reader = std::fs::File::open(source)?;
        reader.seek(SeekFrom::Start(offset as u64))?;
        let mut writer = std::fs::OpenOptions::new().create(true).append(true).open(part)?;
        let mut chunk = vec![0u8; Self::CHUNK];
        let (mut since, mut done) = (0, offset);
        loop {
            self.check_cancel()?;
            let read = reader.read(&mut chunk)?;
            let Some(block) = chunk.get(..read).filter(|block| !block.is_empty()) else {
                break;
            };
            writer.write_all(block)?;
            done += read as i64;
            since += read as i64;
            self.quiet(|job| self.on_file(job, item, file, |row| row.done = done));
            if since >= Self::CHECKPOINT_BYTES {
                writer.sync_all()?;
                self.edit(|job| self.on_file(job, item, file, |row| row.synced = done));
                since = 0;
            }
        }
        writer.sync_all()?;
        let now = self.app.now_whole();
        self.quiet(|job| {
            self.on_file(job, item, file, |row| {
                row.synced = done;
                row.copied_at = now;
            });
        });
        let landed = std::fs::metadata(part)?.size() as i64;
        if landed != found.size {
            return Err(Stop::Failed(io::Error::other(format!("the library copy holds {landed} of {} bytes", found.size))));
        }
        Ok(())
    }

    pub(super) fn hash_file(source: &Path, stop: &AtomicBool) -> io::Result<String> {
        let mut digest = Sha256::new();
        let mut file = std::fs::File::open(source)?;
        let mut chunk = vec![0u8; Self::CHUNK];
        while !stop.load(Ordering::Relaxed) {
            let read = file.read(&mut chunk)?;
            let Some(block) = chunk.get(..read).filter(|block| !block.is_empty()) else {
                return Ok(digest.hex());
            };
            digest.update(block);
        }
        Err(io::Error::other("stopped"))
    }

    /// Reads the copy back and holds it against the source, both digests at once: reading past this host's page cache where the system lets, as a copy read from the cache proves nothing of the disk.
    pub(super) fn prove(&self, source: &Path, copy: &Path, item: usize, file: usize) -> Result<bool, Stop> {
        self.edit(|job| {
            self.on_file(job, item, file, |row| {
                row.phase = "checking".to_string();
                row.done = 0;
            });
        });
        let stop = AtomicBool::new(false);
        let direct = cfg!(target_os = "linux");
        let (local, theirs) = std::thread::scope(|scope| {
            let worker = scope.spawn(|| Self::hash_file(source, &stop));
            let theirs = self.read_back(copy, direct, item, file);
            if theirs.is_err() {
                stop.store(true, Ordering::Relaxed);
            }
            (worker.join().unwrap_or_else(|_| Err(io::Error::other("the digest's thread failed"))), theirs)
        });
        let (their_digest, read) = theirs?;
        let local = local?;
        let same = self.quiet(|job| {
            let mut same = false;
            self.on_file(job, item, file, |row| {
                row.sha256.clone_from(&local);
                row.bypassed = direct;
                same = read == row.size && their_digest == local;
            });
            same
        });
        Ok(same)
    }

    pub(super) fn read_back(&self, copy: &Path, direct: bool, item: usize, file: usize) -> Result<(String, i64), Stop> {
        let mut digest = Sha256::new();
        let mut read_so_far = 0;
        let mut take = |block: &[u8]| -> Result<(), Stop> {
            self.check_cancel()?;
            digest.update(block);
            read_so_far += block.len() as i64;
            let done = read_so_far;
            self.quiet(|job| self.on_file(job, item, file, |row| row.done = done));
            Ok(())
        };
        if direct {
            Self::read_direct(copy, &mut take)?;
        } else {
            let mut opened = std::fs::File::open(copy)?;
            let mut chunk = vec![0u8; Self::CHUNK];
            loop {
                let read = opened.read(&mut chunk)?;
                let Some(block) = chunk.get(..read).filter(|block| !block.is_empty()) else {
                    break;
                };
                take(block)?;
            }
        }
        Ok((digest.hex(), read_so_far))
    }

    pub(super) fn read_direct(copy: &Path, take: &mut impl FnMut(&[u8]) -> Result<(), Stop>) -> Result<(), Stop> {
        let mut child = Command::new("dd")
            .arg(format!("if={}", copy.display()))
            .args(["iflag=direct", "bs=16M", "status=none"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut out = child.stdout.take().ok_or_else(|| io::Error::other("dd gave no output"))?;
        let mut chunk = vec![0u8; Self::CHUNK];
        let read = loop {
            let read = out.read(&mut chunk);
            match read {
                Ok(0) => break Ok(()),
                Ok(count) => {
                    if let Err(stop) = take(chunk.get(..count).unwrap_or_default()) {
                        break Err(stop);
                    }
                }
                Err(error) => break Err(Stop::Failed(error)),
            }
        };
        if read.is_err() {
            // It is ending either way: one already gone has nothing to kill.
            drop(child.kill());
            std::thread::spawn(move || drop(child.wait()));
            return read;
        }
        let said = child.wait_with_output()?;
        if !said.status.success() {
            let words = String::from_utf8_lossy(&said.stderr);
            let tail: String = Coerce::strip(&words).chars().rev().take(200).collect::<Vec<_>>().into_iter().rev().collect();
            return Err(Stop::Failed(io::Error::other(format!("reading back failed: {tail}"))));
        }
        Ok(())
    }

    pub(super) fn settle(&self, item: usize) -> Result<(), Stop> {
        let last =
            // absent-ok: an item the job does not hold has no last moment.
            self.locked().items.get(item).and_then(|row| row.files.iter().map(|file| file.copied_at).max()).unwrap_or_default();
        while self.app.now() - (last as f64) < SETTLE_S {
            self.check_cancel()?;
            std::thread::sleep(Self::BEAT);
        }
        Ok(())
    }
}
