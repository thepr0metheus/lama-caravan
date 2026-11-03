//! What the hub says, in the words it says it: a file's hash, why it shut the door on a download, and a list it sends in pages.

use plumbing::{HttpClient, HttpError};
use regex::{Regex, RegexBuilder};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::time::Duration;
use wire::Percent;

/// One file's hash as the hub published it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HubHash {
    /// LFS: sha-256 of the bytes.
    Sha256(String),
    /// Plain git: sha-1 of the blob.
    GitSha1(String),
    /// A mask of asterisks: the hub hides it.
    Hidden,
    /// Nothing usable.
    None,
}

impl HubHash {
    fn is_hex(text: &str, length: usize) -> bool {
        text.len() == length && text.chars().all(|letter| letter.is_ascii_digit() || ('a'..='f').contains(&letter))
    }

    fn word(value: Option<&Value>) -> String {
        Coerce::stripped(value).to_lowercase()
    }

    /// The hash of one file entry of the hub's tree listing.
    pub fn from_tree_item(item: &Value) -> Self {
        if let Some(lfs) = item.get("lfs").filter(|lfs| lfs.is_object()) {
            let value = Self::word(lfs.get("oid"));
            if Self::is_hex(&value, 64) {
                return Self::Sha256(value);
            }
            return if !value.is_empty() && value.chars().all(|letter| letter == '*') { Self::Hidden } else { Self::None };
        }
        let value = Self::word(item.get("oid"));
        if Self::is_hex(&value, 40) { Self::GitSha1(value) } else { Self::None }
    }

    /// The hash a listing entry carries.
    pub fn from_entry(entry: &Value) -> Self {
        let sha256 = Self::word(entry.get("oid"));
        if Self::is_hex(&sha256, 64) {
            return Self::Sha256(sha256);
        }
        let git = Self::word(entry.get("gitOid"));
        if Self::is_hex(&git, 40) {
            return Self::GitSha1(git);
        }
        if entry.get("hashHidden") == Some(&json!(true)) { Self::Hidden } else { Self::None }
    }

    /// The listing's own words for it.
    pub fn fields(&self) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert("oid".to_string(), json!(if let Self::Sha256(value) = self { value.as_str() } else { "" }));
        out.insert("gitOid".to_string(), json!(if let Self::GitSha1(value) = self { value.as_str() } else { "" }));
        out.insert("hashHidden".to_string(), json!(*self == Self::Hidden));
        out
    }

    /// The word for its kind.
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Sha256(_) => "sha256",
            Self::GitSha1(_) => "git-sha1",
            Self::Hidden => "hidden",
            Self::None => "none",
        }
    }

    /// The value, when there is one to hold a file against.
    pub fn value(&self) -> Option<&str> {
        match self {
            Self::Sha256(value) | Self::GitSha1(value) => Some(value),
            Self::Hidden | Self::None => None,
        }
    }
}

/// The hub's refusal of one repository's file, and what to do about it.
pub struct HubAccess;

impl HubAccess {
    /// The field every request to the hub says who it is by.
    pub const USER_AGENT: &'static str = "lama-caravan/1.0";

    /// True for the hub's refusal itself, and for nothing a retry could change.
    pub fn is_wall(error: &HttpError) -> bool {
        matches!(error, HttpError::Status(401 | 403, _))
    }

    /// The fields of a request to the hub.
    pub fn fields(token: &str) -> Vec<(&'static str, String)> {
        let mut out = vec![("User-Agent", Self::USER_AGENT.to_string())];
        if !token.is_empty() {
            out.push(("Authorization", format!("Bearer {token}")));
        }
        out
    }

    /// What the repository's record says about its gate: "auto", "manual"; none when it says neither.
    fn gated(http: &HttpClient, hub: &str, repo: &str, token: &str) -> bool {
        let url = format!("{hub}/api/models/{}", Percent::encode_path(repo));
        let fields: Vec<(&str, String)> = Self::fields(token);
        let record = http.json_following(&url, &fields, Duration::from_secs(8));
        record
            .ok()
            .and_then(|record| record.get("gated").and_then(Value::as_str).map(|gate| matches!(gate, "auto" | "manual")))
            .unwrap_or(false)
    }

    /// The job's `access`, when a failed download was the gate's doing: the page where a person opens it.
    pub fn after(http: &HttpClient, hub: &str, error: &HttpError, repo: &str, token: &str) -> Option<Value> {
        let HttpError::Status(status @ (401 | 403), _) = error else {
            return None;
        };
        Self::gated(http, hub, repo, token).then(|| json!({"kind": "gated", "url": format!("{hub}/{}", Percent::encode_path(repo)), "repo": repo, "status": status, "tokenSet": !token.is_empty()}))
    }
}

/// One list of the hub's API, read page by page.
pub struct HubPages {
    next: Regex,
}

impl HubPages {
    const PAGE_SIZE: usize = 100;
    const MAX_PAGES: usize = 50;

    /// The reader. The pattern is this program's own text.
    pub fn new() -> Result<Self, regex::Error> {
        Ok(Self { next: RegexBuilder::new(r#"<([^>]*)>\s*;[^,]*?\brel="?next"?(?:[^\w-]|$)"#).case_insensitive(true).build()? })
    }

    /// `url` asking for the largest page, unless it names a size already.
    pub fn sized(url: &str) -> String {
        let (head, query) = url.split_once('?').unwrap_or((url, ""));
        if query.split('&').any(|pair| pair == "limit" || pair.starts_with("limit=")) {
            return url.to_string();
        }
        let joined =
            if query.is_empty() { format!("limit={}", Self::PAGE_SIZE) } else { format!("{query}&limit={}", Self::PAGE_SIZE) };
        format!("{head}?{joined}")
    }

    /// The next page the `Link` field names; "" at the end; a place outside the hub's API is refused: a token goes along.
    pub fn next_url(&self, hub: &str, link: &str) -> Result<String, String> {
        let Some(url) =
            self.next.captures(link).and_then(|found| found.get(1)).map(|word| Coerce::strip(word.as_str()).to_string())
        else {
            return Ok(String::new());
        };
        if !url.starts_with(&format!("{hub}/api/")) {
            return Err(format!("the hub named a next page outside its API: {}", Coerce::first_letters(&url, 120)));
        }
        Ok(url)
    }

    /// Every entry of the list at `url`, in the hub's order. An answer that is no list on its first page is the answer.
    pub fn read(
        &self,
        hub: &str,
        url: &str,
        mut get: impl FnMut(&str) -> Result<(Value, String), String>,
    ) -> Result<Value, String> {
        let mut entries = Vec::new();
        let mut page = Self::sized(url);
        for number in 0..Self::MAX_PAGES {
            let (data, link) = get(&page)?;
            let Value::Array(rows) = data else {
                if number == 0 {
                    return Ok(data);
                }
                return Err("a page after the first was not a list".to_string());
            };
            entries.extend(rows);
            page = self.next_url(hub, &link)?;
            if page.is_empty() {
                return Ok(Value::Array(entries));
            }
        }
        Err(format!("the list has more than {} entries; it was not read to the end", Self::PAGE_SIZE * Self::MAX_PAGES))
    }
}

#[cfg(test)]
pub(crate) mod tests;
