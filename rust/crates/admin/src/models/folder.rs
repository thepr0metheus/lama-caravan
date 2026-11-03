//! A model that is a folder, as a scout rebuilds it: one folder under the models directory, listed for a scout.

use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

/// The folder.
pub struct ModelFolder {
    models_dir: PathBuf,
    rel: String,
}

impl ModelFolder {
    const MAX_FILES: usize = if cfg!(test) { 50 } else { 5000 };
    const PARTIAL: [&'static str; 3] = [".part", ".part.json", ".tmp"];

    /// The folder `rel` under `models_dir`.
    pub fn new(models_dir: &Path, rel: &str) -> Self {
        Self { models_dir: models_dir.to_path_buf(), rel: Coerce::strip(rel).trim_matches('/').to_string() }
    }

    /// The folder, resolved; refused when it leaves the models directory.
    pub fn root(&self) -> Result<PathBuf, AppError> {
        if self.rel.is_empty() {
            return Err(AppError::new("path is required"));
        }
        let base = std::fs::canonicalize(&self.models_dir).unwrap_or_else(|_| self.models_dir.clone());
        let root = super::walk::Resolved::under(&base, &self.rel);
        if !root.starts_with(&base) {
            return Err(AppError::with_status("the path leaves the models directory", 403));
        }
        if !root.is_dir() {
            return Err(AppError::with_status(format!("no model folder at {}", self.rel), 404));
        }
        Ok(root)
    }

    /// `{path, files, links, size}`.
    pub fn listing(&self) -> Result<Value, AppError> {
        let root = self.root()?;
        let base = std::fs::canonicalize(&self.models_dir).unwrap_or_else(|_| self.models_dir.clone());
        let (mut files, mut links) = (Vec::new(), Vec::new());
        self.walk(&root, &root, &base, &mut files, &mut links)?;
        // absent-ok: every row was written with its size just above.
        let size: i64 = files.iter().map(|row: &Value| Coerce::i64_or_zero(row.get("size"))).sum();
        Ok(json!({"path": self.rel, "files": files, "links": links, "size": size}))
    }

    fn walk(
        &self,
        here: &Path,
        root: &Path,
        base: &Path,
        files: &mut Vec<Value>,
        links: &mut Vec<Value>,
    ) -> Result<(), AppError> {
        let (mut folders, mut names) = (Vec::new(), Vec::new());
        for entry in std::fs::read_dir(here).into_iter().flatten().flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            let meta = std::fs::metadata(entry.path());
            if meta.as_ref().is_ok_and(std::fs::Metadata::is_dir) {
                folders.push(name);
            } else {
                names.push(name);
            }
        }
        folders.sort();
        names.sort();
        let linked_folders = folders.iter().filter(|name| here.join(name).is_symlink()).cloned();
        names.extend(linked_folders);
        for name in names {
            self.one(&here.join(&name), &name, root, base, files, links)?;
            if files.len() > Self::MAX_FILES {
                return Err(AppError::with_status(
                    format!("{} holds more than {} files: not a model folder", self.rel, Self::MAX_FILES),
                    413,
                ));
            }
        }
        for name in folders.iter().filter(|name| !here.join(name).is_symlink()) {
            self.walk(&here.join(name), root, base, files, links)?;
        }
        Ok(())
    }

    fn one(
        &self,
        path: &Path,
        name: &str,
        root: &Path,
        base: &Path,
        files: &mut Vec<Value>,
        links: &mut Vec<Value>,
    ) -> Result<(), AppError> {
        let rel = path.strip_prefix(root).map_or_else(|_| name.to_string(), |rel| rel.to_string_lossy().into_owned());
        if path.is_symlink() {
            let target = std::fs::read_link(path).map_err(|error| AppError::with_status(error.to_string(), 500))?;
            let parent = path.parent().unwrap_or(root);
            // Worked out when it leads nowhere as well: `../../gone` starts with this folder's path as it is written, and it is not inside.
            let lands = super::walk::Resolved::under(parent, &target.to_string_lossy());
            if !target.is_absolute() && lands.starts_with(root) {
                links.push(json!({"path": rel, "target": target.to_string_lossy()}));
                return Ok(());
            }
            if !lands.starts_with(base) || !lands.is_file() {
                return Err(AppError::with_status(format!("{}/{rel} links outside the models directory", self.rel), 409));
            }
            let size = std::fs::metadata(&lands).map_err(|error| AppError::with_status(error.to_string(), 500))?.len();
            files.push(json!({"path": rel, "size": size}));
        } else if Self::PARTIAL.iter().any(|end| name.ends_with(end)) {
            return Ok(());
        } else if path.is_file() {
            let size = std::fs::metadata(path).map_err(|error| AppError::with_status(error.to_string(), 500))?.len();
            files.push(json!({"path": rel, "size": size}));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_folder_lists_its_files_and_links_and_nothing_half_written() {
        let base = std::env::temp_dir().join(format!("model-folder-{}", std::process::id()));
        let root = base.join("m/a");
        std::fs::create_dir_all(root.join("sub")).unwrap();
        std::fs::write(root.join("x.bin"), b"123").unwrap();
        std::fs::write(root.join("y.part"), b"1").unwrap();
        std::fs::write(root.join("sub/z"), b"12").unwrap();
        std::os::unix::fs::symlink("x.bin", root.join("l")).unwrap();
        let listing = ModelFolder::new(&base, " m/a/ ").listing().unwrap();
        assert_eq!(
            listing,
            json!({"path": "m/a", "files": [{"path": "x.bin", "size": 3}, {"path": "sub/z", "size": 2}], "links": [{"path": "l", "target": "x.bin"}], "size": 5})
        );
        assert_eq!(ModelFolder::new(&base, "../..").root().unwrap_err().status, 403);
        assert_eq!(ModelFolder::new(&base, "nope").root().unwrap_err().status, 404);
        assert_eq!(ModelFolder::new(&base, "").root().unwrap_err().status, 400);
        std::fs::remove_dir_all(&base).unwrap();
    }

    /// A tree of models in a folder of its own.
    fn tree(name: &str) -> (crate::tests::TestFolder, PathBuf) {
        let folder = crate::tests::TestFolder::new(&format!("folder-{name}"));
        let models = folder.path.join("models");
        let put = |rel: &str, size: usize| {
            let path = models.join(rel);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, vec![b'x'; size]).unwrap();
        };
        let link = |rel: &str, target: &str| {
            let path = models.join(rel);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::os::unix::fs::symlink(target, path).unwrap();
        };
        put("GR00T/nvidia/BF16/config.json", 10);
        put("GR00T/nvidia/BF16/model-00001-of-00002.safetensors", 100);
        put("GR00T/nvidia/BF16/experiment_cfg/conf.yaml", 5);
        put("GR00T/nvidia/BF16/extra.safetensors.part", 7);
        put("GR00T/nvidia/BF16/extra.safetensors.part.json", 3);
        put("GR00T/nvidia/BF16/half.bin.tmp", 3);
        put("shared/tokenizer.json", 33);
        link("GR00T/nvidia/BF16/tokenizer.json", "../../../shared/tokenizer.json");
        put("whisper/models--S--small/blobs/abc", 50);
        put("whisper/models--S--small/refs/main", 4);
        link("whisper/models--S--small/snapshots/h1/model.bin", "../../blobs/abc");
        link("whisper/models--S--small/snapshots/h2", "h1");
        put("plain/model.gguf", 12);
        std::fs::write(folder.path.join("secret.txt"), b"s").unwrap();
        link("leaky/model/link.bin", &folder.path.join("secret.txt").to_string_lossy());
        link("dead/model/link.bin", "../../nowhere");
        link("wide/model/link.bin", "../../plain");
        (folder, models)
    }

    #[test]
    fn a_checkpoint_keeps_its_subfolders_and_a_link_to_another_model_s_file_is_that_file() {
        let (_folder, models) = tree("checkpoint");
        let got = ModelFolder::new(&models, "GR00T/nvidia/BF16/").listing().unwrap();
        assert_eq!(got["path"], json!("GR00T/nvidia/BF16"), "named with no slash at its end");
        assert_eq!(
            got["files"],
            json!([
                {"path": "config.json", "size": 10},
                {"path": "model-00001-of-00002.safetensors", "size": 100},
                {"path": "tokenizer.json", "size": 33},
                {"path": "experiment_cfg/conf.yaml", "size": 5},
            ]),
            "a download still landing is not part of the model"
        );
        assert_eq!((&got["size"], &got["links"]), (&json!(148), &json!([])));
    }

    #[test]
    fn a_hugging_face_cache_keeps_its_links_as_links_and_they_weigh_nothing() {
        let (_folder, models) = tree("cache");
        let got = ModelFolder::new(&models, "whisper/models--S--small").listing().unwrap();
        assert_eq!(got["files"], json!([{"path": "blobs/abc", "size": 50}, {"path": "refs/main", "size": 4}]));
        assert_eq!(
            got["links"],
            json!([{"path": "snapshots/h2", "target": "h1"}, {"path": "snapshots/h1/model.bin", "target": "../../blobs/abc"}])
        );
        assert_eq!(got["size"], json!(54));
    }

    #[test]
    fn a_folder_that_reaches_outside_or_is_no_folder_is_refused_by_its_status() {
        let (_folder, models) = tree("refusals");
        let status = |rel: &str| ModelFolder::new(&models, rel).listing().err().map(|refused| (refused.status, refused.message));
        for rel in ["leaky/model", "dead/model", "wide/model"] {
            let (code, words) = status(rel).unwrap();
            assert_eq!(code, 409, "{rel}");
            assert!(words.contains("links outside the models directory"), "{words}");
        }
        for (rel, want) in [
            ("", 400),
            ("   ", 400),
            ("../outside", 403),
            ("a/../../outside", 403),
            ("plain/model.gguf", 404),
            ("no/such/folder", 404),
        ] {
            assert_eq!(status(rel).map(|said| said.0), Some(want), "{rel:?}");
        }
    }

    #[test]
    fn a_folder_of_more_files_than_a_model_has_is_refused() {
        let (_folder, models) = tree("many");
        let many = models.join("many");
        std::fs::create_dir_all(&many).unwrap();
        for at in 0..ModelFolder::MAX_FILES {
            std::fs::File::create(many.join(format!("f{at}"))).unwrap();
        }
        let got = ModelFolder::new(&models, "many").listing().unwrap();
        assert_eq!(got["files"].as_array().unwrap().len(), ModelFolder::MAX_FILES, "the limit itself is a list");
        std::fs::File::create(many.join("one-more")).unwrap();
        assert_eq!(ModelFolder::new(&models, "many").listing().err().map(|refused| refused.status), Some(413));
    }
}
