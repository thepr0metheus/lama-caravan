//! What the view shows: the files a start asked for, under the names the controller gave them, and nothing else. The controller is asked once, when a start names a file; the kernel's questions are answered from here.

use rules::AppError;
use std::collections::BTreeMap;
use std::path::{Component, Path};

/// One thing in the view.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ViewNode {
    /// A folder, and what is in it by name.
    Folder(BTreeMap<String, u64>),
    /// A file of the controller's: where it reads it, and what it weighs.
    File {
        /// Its path inside the library.
        rel: String,
        /// Its bytes.
        size: u64,
    },
    /// A link, as a model folder has them.
    Link(String),
}

/// The tree, by node number.
#[derive(Debug)]
pub struct ViewTree {
    nodes: BTreeMap<u64, ViewNode>,
    next: u64,
}

impl Default for ViewTree {
    fn default() -> Self {
        Self { nodes: BTreeMap::from([(Self::ROOT, ViewNode::Folder(BTreeMap::new()))]), next: Self::ROOT + 1 }
    }
}

impl ViewTree {
    /// The kernel's number for the top of a mount.
    pub const ROOT: u64 = 1;

    /// The words of `rel`, refused when it would leave the view: a listing comes over the network.
    fn words(rel: &str) -> Result<Vec<String>, AppError> {
        let refused = || AppError::with_status(format!("{rel:?} is no path inside the library"), 409);
        let path = Path::new(rel);
        if path.as_os_str().is_empty() {
            return Err(refused());
        }
        path.components()
            .map(|part| match part {
                Component::Normal(word) => Ok(word.to_string_lossy().into_owned()),
                _ => Err(refused()),
            })
            .collect()
    }

    fn numbered(&mut self, node: ViewNode) -> u64 {
        let number = self.next;
        self.next += 1;
        self.nodes.insert(number, node);
        number
    }

    /// The folder at these words, made where there is none. A file where a folder must be is refused: the controller listed the two at once.
    fn folder_at(&mut self, words: &[String]) -> Result<u64, AppError> {
        let mut here = Self::ROOT;
        for word in words {
            let known = self.lookup(here, word);
            here = match known {
                Some(number) if matches!(self.nodes.get(&number), Some(ViewNode::Folder(_))) => number,
                Some(_) => return Err(AppError::with_status(format!("{word} is a file and a folder in the library"), 409)),
                None => {
                    let number = self.numbered(ViewNode::Folder(BTreeMap::new()));
                    self.place(here, word, number);
                    number
                }
            };
        }
        Ok(here)
    }

    fn place(&mut self, folder: u64, name: &str, number: u64) {
        if let Some(ViewNode::Folder(names)) = self.nodes.get_mut(&folder) {
            names.insert(name.to_string(), number);
        }
    }

    fn put(&mut self, rel: &str, node: ViewNode) -> Result<u64, AppError> {
        let words = Self::words(rel)?;
        let (name, folders) = words.split_last().ok_or_else(|| AppError::with_status("an empty path".to_string(), 409))?;
        let folder = self.folder_at(folders)?;
        if let Some(same) = self.lookup(folder, name).filter(|number| self.nodes.get(number) == Some(&node)) {
            return Ok(same);
        }
        // Another file under an old name takes a number of its own: a program still reading the old one reads what it opened.
        let number = self.numbered(node);
        self.place(folder, name, number);
        Ok(number)
    }

    /// Shows the controller's file `rel`, of `size` bytes.
    pub fn offer_file(&mut self, rel: &str, size: u64) -> Result<u64, AppError> {
        self.put(rel, ViewNode::File { rel: rel.to_string(), size })
    }

    /// Shows a link at `rel`.
    pub fn offer_link(&mut self, rel: &str, target: &str) -> Result<u64, AppError> {
        self.put(rel, ViewNode::Link(target.to_string()))
    }

    /// What `name` in `folder` is.
    pub fn lookup(&self, folder: u64, name: &str) -> Option<u64> {
        match self.nodes.get(&folder) {
            Some(ViewNode::Folder(names)) => names.get(name).copied(),
            _ => None,
        }
    }

    /// The thing of this number.
    pub fn node(&self, number: u64) -> Option<&ViewNode> {
        self.nodes.get(&number)
    }
}
