//! A request's target, as `urlparse` and `parse_qs` read it.

use wire::Percent;

/// The target's path and query.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Parsed {
    /// The path, undecoded: routes are looked up as they came.
    pub path: String,
    /// The query, undecoded.
    pub query: String,
}

impl Parsed {
    /// `urlparse(target)`: a fragment goes, an absolute target loses its scheme and host, and what follows a `;` of the last segment is no part of the path.
    pub fn of(target: &str) -> Self {
        let target = target.split_once('#').map_or(target, |(head, _)| head);
        let (rest, query) = target.split_once('?').unwrap_or((target, ""));
        let path = Self::after_host(rest);
        // absent-ok: no `/`: the whole word is the segment.
        let segment_start = path.rfind('/').map_or(0, |at| at + 1);
        let bare = path
            .get(segment_start..)
            .and_then(|last| last.find(';'))
            .and_then(|at| path.get(..segment_start + at))
            .unwrap_or(path);
        Self { path: bare.to_string(), query: query.to_string() }
    }

    fn after_host(rest: &str) -> &str {
        let is_scheme = |word: &str| {
            word.chars().next().is_some_and(|first| first.is_ascii_alphabetic())
                && word.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '+' | '-' | '.'))
        };
        let after_scheme = rest.split_once(':').filter(|(word, _)| is_scheme(word)).map_or(rest, |(_, after)| after);
        match after_scheme.strip_prefix("//") {
            Some(authority) => authority.find('/').and_then(|at| authority.get(at..)).unwrap_or(""),
            None => after_scheme,
        }
    }

    /// `parse_qs`: each `name=value` with a value; `+` is a space, escapes decoded.
    pub fn pairs(&self) -> Vec<(String, String)> {
        let word = |raw: &str| Percent::decode(&raw.replace('+', " "));
        self.query
            .split('&')
            .filter_map(|pair| pair.split_once('='))
            .filter(|(_, value)| !value.is_empty())
            .map(|(name, value)| (word(name), word(value)))
            .collect()
    }

    /// The first value of a parameter.
    pub fn param(&self, name: &str) -> Option<String> {
        self.pairs().into_iter().find(|(said, _)| said == name).map(|(_, value)| value)
    }

    /// The first value of a parameter, or `otherwise`: `(q.get(name) or [otherwise])[0]`.
    pub fn param_or(&self, name: &str, otherwise: &str) -> String {
        self.param(name).unwrap_or_else(|| otherwise.to_string())
    }

    /// Every value of a parameter.
    pub fn params(&self, name: &str) -> Vec<String> {
        self.pairs().into_iter().filter(|(said, _)| said == name).map(|(_, value)| value).collect()
    }

    /// A boolean parameter: `1`, `true`, `yes`, `on`, any case; a parameter not said is `default`.
    pub fn flag(&self, name: &str, default: bool) -> bool {
        self.param(name)
            .map_or(default, |value| matches!(rules::Coerce::strip(&value).to_lowercase().as_str(), "1" | "true" | "yes" | "on"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_target_comes_apart_as_urlparse_has_it() {
        assert_eq!(Parsed::of("/a/b?x=1#f"), Parsed { path: "/a/b".to_string(), query: "x=1".to_string() });
        assert_eq!(Parsed::of("/a;p/b;q?x").path, "/a;p/b");
        assert_eq!(Parsed::of("http://h:1/a?x=1").path, "/a");
        assert_eq!(Parsed::of("//h/a").path, "/a");
        assert_eq!(Parsed::of("/a:b").path, "/a:b");
    }

    #[test]
    fn a_query_reads_as_parse_qs_has_it() {
        let parsed = Parsed::of("/?a=1+2&b=&c&a=%D1%8E&d=on");
        assert_eq!(parsed.param("a").as_deref(), Some("1 2"));
        assert_eq!(parsed.params("a"), ["1 2", "ю"]);
        assert_eq!(parsed.param("b"), None);
        assert_eq!(parsed.param("c"), None);
        assert_eq!(parsed.param_or("b", "z"), "z");
        assert!(parsed.flag("d", false));
        assert!(parsed.flag("z", true));
        assert!(!parsed.flag("a", true));
    }
}
