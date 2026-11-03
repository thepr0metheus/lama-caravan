//! A program asking over HTTP: the controller, a scout, a cell, an engine, the hub. One request on one connection.

use net::{Dial, Stream, TrustedRoots};
use rules::BaseUrl;
use serde_json::Value;
use std::io::{self, BufReader, Read, Write};
use std::path::PathBuf;
use std::time::Duration;
use wire::{AnswerBody, AnswerHead, AnswerHeadReader};

/// Why a request came to nothing.
#[derive(Debug)]
pub enum HttpError {
    /// The address does not read.
    BadAddress(String),
    /// The connection failed, in the system's words.
    Io(io::Error),
    /// It answered, with a status of 400 or more; the words are its body's head.
    Status(u16, String),
}

impl HttpError {
    /// No answer came at all: the network's fault, not the endpoint's. An answer that is no JSON is an answer.
    pub fn is_silence(&self) -> bool {
        matches!(self, Self::Io(error) if error.kind() != io::ErrorKind::InvalidData)
    }
}

impl std::fmt::Display for HttpError {
    fn fmt(&self, out: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::BadAddress(address) => write!(out, "unknown url type: {address}"),
            Self::Io(error) => write!(out, "{error}"),
            Self::Status(status, _) => write!(out, "HTTP Error {status}: {}", wire::Reply::reason_of(*status)),
        }
    }
}

impl From<io::Error> for HttpError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

/// An answer on its way: the head read, the body still to come.
pub struct HttpAnswer {
    /// Its head.
    pub head: AnswerHead,
    /// Its body.
    pub body: AnswerBody<Stream>,
}

impl HttpAnswer {
    /// The whole body, up to `most` bytes.
    pub fn text(mut self, most: u64) -> io::Result<Vec<u8>> {
        let mut out = Vec::new();
        (&mut self.body).take(most).read_to_end(&mut out)?;
        Ok(out)
    }
}

/// The asking side: its roots of trust, read once.
pub struct HttpClient {
    roots: Result<TrustedRoots, String>,
}

impl HttpClient {
    /// The client, trusting `SSL_CERT_FILE` or the system's certificates.
    pub fn new() -> Self {
        let file = std::env::var_os("SSL_CERT_FILE").map(PathBuf::from);
        Self { roots: TrustedRoots::read(file).map_err(|error| error.0) }
    }

    /// One request. `timeout` holds for the connection and for each read after it. An answer of 400 or more is an error, as `urlopen` has it.
    pub fn ask(
        &self,
        method: &str,
        url: &str,
        fields: &[(&str, String)],
        body: &[u8],
        timeout: Duration,
    ) -> Result<HttpAnswer, HttpError> {
        Self::refused_from(self.answer(method, url, fields, body, timeout)?, 400)
    }

    /// An answer of `from` or more as the error it is, its body's head for words.
    fn refused_from(answer: HttpAnswer, from: u16) -> Result<HttpAnswer, HttpError> {
        if answer.head.status >= from {
            let status = answer.head.status;
            // absent-ok: an error's body that did not come says nothing; the status is the error.
            let said = answer.text(4096).unwrap_or_default();
            return Err(HttpError::Status(status, String::from_utf8_lossy(&said).into_owned()));
        }
        Ok(answer)
    }

    /// One request, whatever its answer's status.
    pub fn answer(
        &self,
        method: &str,
        url: &str,
        fields: &[(&str, String)],
        body: &[u8],
        timeout: Duration,
    ) -> Result<HttpAnswer, HttpError> {
        let place = BaseUrl::read(url).ok_or_else(|| HttpError::BadAddress(url.to_string()))?;
        let socket = Dial { turn: timeout, limit: timeout }.open::<io::Error>(&place.host, place.port, &mut || Ok(()))?;
        socket.set_read_timeout(Some(timeout))?;
        socket.set_write_timeout(Some(timeout))?;
        let mut stream = if place.tls {
            let roots = self.roots.as_ref().map_err(|words| io::Error::new(io::ErrorKind::NotFound, words.clone()))?;
            roots.wrap::<io::Error>(socket, &place.host, &mut || {
                Err(io::Error::new(io::ErrorKind::TimedOut, "the handshake timed out"))
            })?
        } else {
            Stream::Plain(socket)
        };
        let query = url.split_once('?').map_or(String::new(), |(_, query)| format!("?{query}"));
        let path = if place.path.is_empty() { "/" } else { place.path.as_str() };
        let mut head = format!(
            "{method} {path}{query} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nAccept-Encoding: identity\r\n",
            place.netloc
        );
        for (name, value) in fields {
            head.push_str(&format!("{name}: {value}\r\n"));
        }
        if !body.is_empty() || method == "POST" {
            head.push_str(&format!("Content-Length: {}\r\n", body.len()));
        }
        head.push_str("\r\n");
        stream.write_all(head.as_bytes())?;
        stream.write_all(body)?;
        stream.flush()?;
        let mut source = BufReader::new(stream);
        let answer_head = AnswerHeadReader::new().read(&mut source)?;
        let answer_body = AnswerBody::new(source, &answer_head, method);
        Ok(HttpAnswer { head: answer_head, body: answer_body })
    }

    /// A GET that follows redirects, as `urlopen` does: a release's file is served from another host.
    pub fn following(&self, url: &str, timeout: Duration) -> Result<HttpAnswer, HttpError> {
        self.following_with(url, &[], timeout)
    }

    /// The same with fields of its own, which go along to where it is sent, as `urlopen` has it. A `Location` may be relative: the hub sends an
    /// ordinary file of a repository to `/api/resolve-cache/…`.
    pub fn following_with(&self, url: &str, fields: &[(&str, String)], timeout: Duration) -> Result<HttpAnswer, HttpError> {
        const MOST: usize = 10;
        let mut at = url.to_string();
        for _ in 0..MOST {
            let answer = self.answer("GET", &at, fields, &[], timeout)?;
            let next = answer.head.headers.get("Location").filter(|_| matches!(answer.head.status, 301 | 302 | 303 | 307 | 308));
            let Some(next) = next else {
                // A redirect with nowhere to go is no answer either: its body is not what was asked for, and a download would land it as the file.
                return Self::refused_from(answer, 300);
            };
            at = BaseUrl::joined(&at, &next).ok_or(HttpError::BadAddress(next))?;
        }
        Err(HttpError::Status(310, "too many redirects".to_string()))
    }

    /// A JSON answer to a GET that follows redirects: a renamed repository answers at its new name.
    pub fn json_following(&self, url: &str, fields: &[(&str, String)], timeout: Duration) -> Result<Value, HttpError> {
        Self::parsed(self.following_with(url, fields, timeout)?)
    }

    fn parsed(answer: HttpAnswer) -> Result<Value, HttpError> {
        const MOST: u64 = 64 << 20;
        serde_json::from_slice(&answer.text(MOST)?)
            .map_err(|error| HttpError::Io(io::Error::new(io::ErrorKind::InvalidData, error)))
    }

    /// A JSON answer; a body that is no JSON is an error of its own words.
    pub fn json(
        &self,
        method: &str,
        url: &str,
        fields: &[(&str, String)],
        body: &[u8],
        timeout: Duration,
    ) -> Result<Value, HttpError> {
        Self::parsed(self.ask(method, url, fields, body, timeout)?)
    }
}

impl Default for HttpClient {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::sync::mpsc::{Receiver, channel};

    /// A path, its status, its fields, its body.
    type Row = (&'static str, &'static str, &'static str, &'static str);

    /// A server of one answer per path; what it was asked comes out of the receiver, the whole head of each request.
    fn stand_in(table: &'static [Row]) -> (String, Receiver<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = format!("http://{}", listener.local_addr().unwrap());
        let (told, asked) = channel();
        std::thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                let mut stream = stream;
                let mut head = vec![0u8; 8192];
                let read = stream.read(&mut head).unwrap();
                let head = String::from_utf8_lossy(head.get(..read).unwrap()).into_owned();
                let path = head.split_whitespace().nth(1).unwrap().to_string();
                told.send(head).unwrap();
                let (status, fields, body) = table
                    .iter()
                    .find(|row| row.0 == path)
                    .map_or(("404 Not Found", "", "nothing here"), |row| (row.1, row.2, row.3));
                let answer =
                    format!("HTTP/1.1 {status}\r\n{fields}Content-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
                stream.write_all(answer.as_bytes()).unwrap();
            }
        });
        (address, asked)
    }

    const TIMEOUT: Duration = Duration::from_secs(5);

    #[test]
    fn a_relative_location_is_followed_with_the_fields_kept() {
        const TABLE: &[Row] = &[
            (
                "/org/repo/resolve/main/config.json",
                "307 Temporary Redirect",
                "Location: /api/resolve-cache/abc/config.json?x=1\r\n",
                "Temporary Redirect",
            ),
            ("/api/resolve-cache/abc/config.json?x=1", "200 OK", "", "{\"dtype\": \"bfloat16\"}"),
        ];
        let (address, asked) = stand_in(TABLE);
        let fields = [("Authorization", "Bearer t".to_string()), ("Range", "bytes=5-".to_string())];
        let url = format!("{address}/org/repo/resolve/main/config.json");
        let said = HttpClient::new().json_following(&url, &fields, TIMEOUT).unwrap();
        assert_eq!(said, serde_json::json!({"dtype": "bfloat16"}));
        asked.recv().unwrap();
        let second = asked.recv().unwrap();
        assert!(second.starts_with("GET /api/resolve-cache/abc/config.json?x=1 HTTP/1.1"), "{second}");
        assert!(
            second.contains("Authorization: Bearer t\r\n") && second.contains("Range: bytes=5-\r\n"),
            "the fields travel: {second}"
        );
    }

    #[test]
    fn an_error_at_the_end_of_a_redirect_is_the_error_with_its_words() {
        const TABLE: &[Row] = &[("/a", "302 Found", "Location: /b\r\n", ""), ("/b", "403 Forbidden", "", "the door is shut")];
        let (address, _asked) = stand_in(TABLE);
        let Err(HttpError::Status(403, words)) = HttpClient::new().following_with(&format!("{address}/a"), &[], TIMEOUT) else {
            panic!("no 403");
        };
        assert_eq!(words, "the door is shut");
    }

    #[test]
    fn a_redirect_that_goes_round_ends_and_one_out_of_the_web_is_refused() {
        const TABLE: &[Row] =
            &[("/round", "302 Found", "Location: /round\r\n", ""), ("/out", "302 Found", "Location: file:///etc/passwd\r\n", "")];
        let (address, _asked) = stand_in(TABLE);
        let client = HttpClient::new();
        assert!(matches!(client.following(&format!("{address}/round"), TIMEOUT), Err(HttpError::Status(310, _))));
        assert!(matches!(client.following(&format!("{address}/out"), TIMEOUT), Err(HttpError::BadAddress(_))));
    }

    #[test]
    fn a_redirect_with_nowhere_to_go_is_an_error_and_not_its_body() {
        const TABLE: &[Row] = &[("/moved", "302 Found", "", "moved"), ("/same", "304 Not Modified", "", "")];
        let (address, _asked) = stand_in(TABLE);
        let client = HttpClient::new();
        let Err(HttpError::Status(302, words)) = client.following(&format!("{address}/moved"), TIMEOUT) else {
            panic!("no error");
        };
        assert_eq!(words, "moved");
        assert!(matches!(client.following(&format!("{address}/same"), TIMEOUT), Err(HttpError::Status(304, _))));
    }

    #[test]
    fn a_plain_ask_does_not_follow() {
        const TABLE: &[Row] = &[("/a", "307 Temporary Redirect", "Location: /b\r\n", "")];
        let (address, _asked) = stand_in(TABLE);
        let answer = HttpClient::new().ask("GET", &format!("{address}/a"), &[], b"", TIMEOUT).unwrap();
        assert_eq!(answer.head.status, 307);
    }
}
