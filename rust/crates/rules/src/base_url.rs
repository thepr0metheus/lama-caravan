//! A provider's address as the proxy calls it: the part of `urlsplit` and `CloudSources.upstream_path` it needs.

/// A provider's address, read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BaseUrl {
    /// Whether it goes over TLS: anything but `http`, as the proxy has always read it.
    pub tls: bool,
    /// The host, in lower case and without brackets.
    pub host: String,
    /// The port: the address's, or its scheme's.
    pub port: u16,
    /// What the `Host` field says: the address's own letters.
    pub netloc: String,
    /// The path before a request's own.
    pub path: String,
}

impl BaseUrl {
    /// The address `text` says; `None` for one with no host, or with a port that is no port: the leg then fails.
    pub fn read(text: &str) -> Option<Self> {
        let (scheme, rest) = text.split_once("://")?;
        let scheme = scheme.to_ascii_lowercase();
        let cut = rest.find(['/', '?', '#']).unwrap_or(rest.len());
        let (netloc, after) = rest.split_at(cut);
        let path_end = after.find(['?', '#']).unwrap_or(after.len());
        let (host, port) = Self::host_and_port(netloc)?;
        let tls = scheme != "http";
        Some(Self {
            tls,
            port: port.unwrap_or(if tls { 443 } else { 80 }),
            host: host.to_lowercase(),
            netloc: netloc.to_string(),
            path: after.get(..path_end).unwrap_or(after).to_string(),
        })
    }

    /// The host and the port of `netloc`, its user dropped. `None`: no host, or a port that does not read.
    fn host_and_port(netloc: &str) -> Option<(&str, Option<u16>)> {
        let place = netloc.rsplit_once('@').map_or(netloc, |(_, place)| place);
        let (host, port) = match place.strip_prefix('[') {
            Some(bracketed) => {
                let (host, after) = bracketed.split_once(']')?;
                (host, after.strip_prefix(':'))
            }
            None => match place.split_once(':') {
                Some((host, port)) => (host, Some(port)),
                None => (place, None),
            },
        };
        if host.is_empty() {
            return None;
        }
        match port.filter(|port| !port.is_empty()) {
            None => Some((host, None)),
            Some(port) if port.bytes().all(|digit| digit.is_ascii_digit()) => Some((host, Some(port.parse().ok()?))),
            Some(_) => None,
        }
    }

    /// Where a redirect from `from` leads, `location` being what its header said: joined as `urljoin` joins them, the fragment gone, and a space
    /// or a letter past ASCII written as `%XX` (a header's value reads as latin-1, a letter a byte). `None`: a place other than http or https.
    pub fn joined(from: &str, location: &str) -> Option<String> {
        // absent-ok: `split` always has a first part.
        let location = location.trim().split('#').next().unwrap_or_default();
        let scheme = location.split_once(':').map(|(word, _)| word).filter(|word| Self::is_scheme(word));
        let written = match scheme {
            Some(word) if word.eq_ignore_ascii_case("http") || word.eq_ignore_ascii_case("https") => location.to_string(),
            Some(_) => return None,
            None => Self::relative(from, location)?,
        };
        let mut out = String::with_capacity(written.len());
        for letter in written.chars() {
            if letter.is_ascii_graphic() {
                out.push(letter);
            } else {
                out.push_str(&format!("%{:02X}", u32::from(letter)));
            }
        }
        Some(out)
    }

    /// `[a-zA-Z][a-zA-Z0-9+.-]*`: what stands before the first colon of an address with a scheme.
    fn is_scheme(word: &str) -> bool {
        word.chars().next().is_some_and(|first| first.is_ascii_alphabetic())
            && word.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '+' | '.' | '-'))
    }

    fn relative(from: &str, location: &str) -> Option<String> {
        let (scheme, rest) = from.split_once("://")?;
        if let Some(other) = location.strip_prefix("//") {
            return Some(format!("{scheme}://{other}"));
        }
        let (netloc, after) = rest.split_at(rest.find(['/', '?', '#']).unwrap_or(rest.len()));
        let (path, kept_query) = after.split_at(after.find(['?', '#']).unwrap_or(after.len()));
        let (asked, query) = location.split_at(location.find('?').unwrap_or(location.len()));
        if asked.is_empty() {
            let query = if query.is_empty() { kept_query.split('#').next().unwrap_or_default() } else { query };
            return Some(format!("{scheme}://{netloc}{path}{query}"));
        }
        let folder = path.rsplit_once('/').map_or("", |(folder, _)| folder);
        let joined = if asked.starts_with('/') { asked.to_string() } else { format!("{folder}/{asked}") };
        Some(format!("{scheme}://{netloc}{}{query}", Self::without_dots(&joined)))
    }

    /// A path with its `.` and `..` walked, never above the root.
    fn without_dots(path: &str) -> String {
        let parts: Vec<&str> = path.split('/').collect();
        let last = parts.len().saturating_sub(1);
        let mut kept: Vec<&str> = Vec::with_capacity(parts.len());
        for (at, part) in parts.iter().enumerate() {
            match *part {
                "." | ".." => {
                    if *part == ".." && kept.len() > 1 {
                        kept.pop();
                    }
                    if at == last {
                        kept.push("");
                    }
                }
                word => kept.push(word),
            }
        }
        kept.join("/")
    }

    /// The path a client's request goes to: the address's own path, then the request's, without its `/v1` when the address already names
    /// its version: the client always speaks `/v1`, and GLM's plan answers at `/v4`.
    pub fn upstream_path(&self, incoming: &str) -> String {
        let base = self.path.trim_end_matches('/');
        let versioned = base
            .rsplit_once("/v")
            .is_some_and(|(_, number)| !number.is_empty() && number.bytes().all(|digit| digit.is_ascii_digit()));
        match incoming.strip_prefix("/v1").filter(|rest| versioned && rest.starts_with('/')) {
            Some(rest) => format!("{base}{rest}"),
            None => format!("{base}{incoming}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read(text: &str) -> BaseUrl {
        BaseUrl::read(text).unwrap()
    }

    #[test]
    fn a_redirect_is_joined_as_urljoin_joins_it() {
        let from = "https://huggingface.co/org/repo/resolve/main/config.json?download=1";
        for (location, want) in [
            // The hub's own: a file that is not in LFS is sent to an address on the same host.
            (
                "/api/resolve-cache/models/org/repo/abc/config.json?x=%2Fa",
                "https://huggingface.co/api/resolve-cache/models/org/repo/abc/config.json?x=%2Fa",
            ),
            ("https://cdn.example.org/a/b?sig=1", "https://cdn.example.org/a/b?sig=1"),
            ("HTTP://other:81/a", "HTTP://other:81/a"),
            ("//cdn.example.org/a", "https://cdn.example.org/a"),
            ("other.json", "https://huggingface.co/org/repo/resolve/main/other.json"),
            ("./other.json?y=2", "https://huggingface.co/org/repo/resolve/main/other.json?y=2"),
            ("../dev/other.json", "https://huggingface.co/org/repo/resolve/dev/other.json"),
            ("/a/../../b", "https://huggingface.co/b"),
            ("/a/b/..", "https://huggingface.co/a/"),
            ("/a/b/.", "https://huggingface.co/a/b/"),
            ("?z=3", "https://huggingface.co/org/repo/resolve/main/config.json?z=3"),
            ("", "https://huggingface.co/org/repo/resolve/main/config.json?download=1"),
            ("/a#part", "https://huggingface.co/a"),
            ("  /a b\u{e9}  ", "https://huggingface.co/a%20b%E9"),
            ("/path:with?colon=http://x", "https://huggingface.co/path:with?colon=http://x"),
        ] {
            assert_eq!(BaseUrl::joined(from, location).as_deref(), Some(want), "{location:?}");
        }
        assert_eq!(BaseUrl::joined("https://x", "a").as_deref(), Some("https://x/a"), "an address with no path");
        assert_eq!(BaseUrl::joined("https://x?q=1", "/a").as_deref(), Some("https://x/a"));
    }

    #[test]
    fn a_redirect_to_elsewhere_than_the_web_goes_nowhere() {
        for location in ["file:///etc/passwd", "ftp://x/y", "javascript:alert(1)", "data:text/plain,x"] {
            assert_eq!(BaseUrl::joined("https://x/y", location), None, "{location}");
        }
        assert_eq!(BaseUrl::joined("not an address", "/a"), None);
    }

    #[test]
    fn an_address_reads_as_urlsplit_reads_it() {
        let plain = read("https://ChatGPT.com/backend-api");
        assert_eq!(
            (plain.tls, plain.host.as_str(), plain.port, plain.netloc.as_str(), plain.path.as_str()),
            (true, "chatgpt.com", 443, "ChatGPT.com", "/backend-api")
        );
        let local = read("http://127.0.0.1:8080/v1?x=1#y");
        assert_eq!((local.tls, local.host.as_str(), local.port, local.path.as_str()), (false, "127.0.0.1", 8080, "/v1"));
        assert!(!read("HTTP://x").tls);
        assert_eq!(read("http://x").port, 80);
        assert_eq!(read("https://x:").port, 443);
        assert!(read("ftp://x").tls, "anything but http");
        assert_eq!(read("https://user:word@x:81/p").host, "x");
        assert_eq!(read("https://user:word@x:81/p").port, 81);
        assert_eq!(read("https://[::1]:81/p").host, "::1");
        assert_eq!(read("https://[::1]/p").port, 443);
        assert_eq!(read("https://x").path, "");
    }

    #[test]
    fn an_address_it_cannot_call_is_none() {
        for odd in [
            "",
            "x",
            "x/y",
            "https://",
            "https:///p",
            "https://x:port",
            "https://x:+80",
            "https://x:70000",
            "https://[::1",
            "https://u@",
        ] {
            assert_eq!(BaseUrl::read(odd), None, "{odd}");
        }
    }

    #[test]
    fn a_request_s_path_follows_the_address_s_own() {
        let cases = [
            ("https://x", "/v1/chat/completions", "/v1/chat/completions"),
            ("https://x/", "/v1/chat/completions", "/v1/chat/completions"),
            ("https://x/api", "/v1/chat/completions", "/api/v1/chat/completions"),
            ("https://x/v1", "/v1/chat/completions", "/v1/chat/completions"),
            ("https://x/v1/", "/v1/chat/completions", "/v1/chat/completions"),
            ("https://x/api/v4", "/v1/chat/completions", "/api/v4/chat/completions"),
            ("https://x/v4", "/other", "/v4/other"),
            ("https://x/v", "/v1/a", "/v/v1/a"),
            ("https://x/v1a", "/v1/a", "/v1a/v1/a"),
            ("https://x/v4", "/v1", "/v4/v1"),
            ("https://x/v4", "/v12/a", "/v4/v12/a"),
        ];
        for (base, incoming, want) in cases {
            assert_eq!(read(base).upstream_path(incoming), want, "{base} {incoming}");
        }
    }
}
