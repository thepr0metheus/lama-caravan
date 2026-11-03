//! A member of a vendor's archive, as the system's `tar` lists it, checked before anything is extracted.

use crate::errors::AppError;
use crate::models::files::Resolved;
use std::path::Path;

/// One line of `tar -tv`: what a member is, its name, where a link of it leads.
#[derive(Debug, PartialEq, Eq)]
pub(super) struct ArchiveLine {
    kind: char,
    name: String,
    target: Option<String>,
}

impl ArchiveLine {
    /// `tar -tv` writes the mode, the owner, the size, the date and the time, in six fields on BSD and five on GNU, and the name after them. A name is told from the fields by where the time stands: the word with two colons or one.
    pub(super) fn read(line: &str) -> Self {
        // absent-ok: an empty line is a member of no kind, and the check refuses it.
        let kind = line.chars().next().unwrap_or('?');
        let words: Vec<&str> = line.split_whitespace().collect();
        let time = words
            .iter()
            .position(|word| word.contains(':') && word.chars().all(|letter| letter.is_ascii_digit() || letter == ':'));
        // absent-ok: a line of no time names no member, and the check refuses a member of no name.
        let rest = time.map_or(&[][..], |at| words.get(at + 1..).unwrap_or_default());
        let joined = rest.join(" ");
        let (name, target) = match (joined.split_once(" -> "), joined.split_once(" link to ")) {
            (Some((name, target)), _) | (None, Some((name, target))) => (name.to_string(), Some(target.to_string())),
            (None, None) => (joined, None),
        };
        Self { kind, name, target }
    }

    pub(super) fn check(&self, root: &Path) -> Result<(), AppError> {
        let unsafe_member = || AppError::new(format!("unsafe PrismML archive member: {}", self.name));
        if self.name.is_empty() || !matches!(self.kind, '-' | 'd' | 'l' | 'h') {
            return Err(unsafe_member());
        }
        let dest = Resolved::of(&root.join(&self.name));
        if !dest.starts_with(root) {
            return Err(unsafe_member());
        }
        if let Some(target) = &self.target {
            let link = if self.kind == 'l' { dest.parent().unwrap_or(root).join(target) } else { root.join(target) };
            if !Resolved::of(&link).starts_with(root) {
                return Err(AppError::new(format!("unsafe PrismML archive link: {}", self.name)));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_archive_line_says_its_name_and_its_link_and_one_that_leaves_is_refused() {
        let root = Resolved::of(Path::new("/tmp/extract-root-that-is-not-there"));
        let root = root.as_path();
        let plain = ArchiveLine::read("-rwxr-xr-x user/group 12 2026-01-01 10:00 bin/llama-server");
        assert_eq!((plain.kind, plain.name.as_str(), plain.target.as_deref()), ('-', "bin/llama-server", None));
        assert!(plain.check(root).is_ok());
        let bsd = ArchiveLine::read("lrwxr-xr-x  0 u g 0 Jan 1 10:00 bin/liba.so -> libb.so");
        assert_eq!((bsd.name.as_str(), bsd.target.as_deref()), ("bin/liba.so", Some("libb.so")));
        assert!(bsd.check(root).is_ok());
        assert!(ArchiveLine::read("-rw-r--r-- u/g 1 2026-01-01 10:00 ../../etc/passwd").check(root).is_err());
        assert!(ArchiveLine::read("lrwxr-xr-x u/g 0 2026-01-01 10:00 a -> ../../outside").check(root).is_err());
        assert!(ArchiveLine::read("crw-r--r-- u/g 0 2026-01-01 10:00 device").check(root).is_err());
    }
}
