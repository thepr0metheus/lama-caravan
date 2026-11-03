//! One request and its answer. The answer is written to the socket as it is made: a body may be a file too large to hold.

use super::gzip::Gzip;
use super::parsed::Parsed;
use rules::{AppError, ClientAddress, Coerce, PythonJson};
use serde_json::Value;
use std::io::{BufReader, Read, Write};
use std::net::TcpStream;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use wire::{HttpDate, Reply, RequestHead};

/// One request on a connection, and what was said back so far.
pub struct Exchange<'conn> {
    head: RequestHead,
    /// The target.
    pub parsed: Parsed,
    source: &'conn mut BufReader<TcpStream>,
    out: &'conn TcpStream,
    peer: String,
    now: u64,
    server_word: &'conn str,
    /// Whether this connection ends after the answer.
    pub close: bool,
    responded: bool,
}

impl<'conn> Exchange<'conn> {
    const GZIP_MIN: usize = 1400;

    /// The exchange of a request.
    pub fn new(
        head: RequestHead,
        source: &'conn mut BufReader<TcpStream>,
        out: &'conn TcpStream,
        peer: String,
        now: u64,
        server_word: &'conn str,
    ) -> Self {
        let parsed = Parsed::of(&head.target);
        Self { head, parsed, source, out, peer, now, server_word, close: false, responded: false }
    }

    /// A field of the request's head, as text.
    pub fn field(&self, name: &str) -> Option<String> {
        self.head.headers.get(name)
    }

    /// The same, "" when it is not there.
    pub fn field_or_empty(&self, name: &str) -> String {
        self.head.headers.text_of(name)
    }

    /// The request's method.
    pub fn method(&self) -> &str {
        &self.head.method
    }

    /// The address of the one who asks: the peer, or who a proxy on this host names.
    pub fn client_address(&self) -> String {
        ClientAddress::of(
            &self.peer,
            self.field(ClientAddress::FORWARDED).as_deref(),
            self.field(ClientAddress::REAL_IP).as_deref(),
        )
    }

    /// The connection's raw socket, for an answer that is no HTTP any more: a WebSocket.
    pub fn socket(&mut self) -> (&mut BufReader<TcpStream>, &'conn TcpStream) {
        self.responded = true;
        (self.source, self.out)
    }

    /// Whether anything of an answer has gone.
    pub fn responded(&self) -> bool {
        self.responded
    }

    /// The head of an answer: its status, the server's name, the date, then these fields.
    pub fn start(&mut self, status: u16, fields: &[(&str, String)]) {
        self.responded = true;
        let mut reply = Reply::new(status).field("Server", self.server_word).field("Date", HttpDate::format(self.now));
        for (name, value) in fields {
            reply = reply.field(name, value.as_str());
        }
        self.write(&reply.head());
    }

    /// Bytes of the answer. A client that has left ends the connection: nobody else is told.
    pub fn write(&mut self, bytes: &[u8]) {
        let mut out = self.out;
        if out.write_all(bytes).is_err() {
            self.close = true;
        }
    }

    fn accepts_gzip(&self) -> bool {
        self.field_or_empty("Accept-Encoding").to_lowercase().contains("gzip")
    }

    /// (body, whether it is gzipped): gzipped when the client asked and it is worth it.
    fn maybe_gzip(&self, data: Vec<u8>) -> (Vec<u8>, bool) {
        if data.len() < Self::GZIP_MIN || !self.accepts_gzip() {
            return (data, false);
        }
        (Gzip::compress(&data), true)
    }

    /// A JSON answer: indented, the letters as themselves, never kept by a cache.
    pub fn send_json(&mut self, payload: &Value, status: u16) {
        let (data, zipped) = self.maybe_gzip(PythonJson::indented_letters(payload).into_bytes());
        let mut fields =
            vec![("Content-Type", "application/json; charset=utf-8".to_string()), ("Cache-Control", "no-store".to_string())];
        if zipped {
            fields.push(("Content-Encoding", "gzip".to_string()));
            fields.push(("Vary", "Accept-Encoding".to_string()));
        }
        fields.push(("Content-Length", data.len().to_string()));
        self.start(status, &fields);
        self.write(&data);
    }

    /// A JSON answer with a status of 200.
    pub fn ok(&mut self, payload: &Value) {
        self.send_json(payload, 200);
    }

    /// A JSON answer with a field of its own, and no gzip: the sign-in's cookie.
    pub fn send_json_with(&mut self, payload: &Value, name: &str, value: String) {
        let data = PythonJson::indented_letters(payload).into_bytes();
        self.start(
            200,
            &[
                ("Content-Type", "application/json; charset=utf-8".to_string()),
                (name, value),
                ("Content-Length", data.len().to_string()),
            ],
        );
        self.write(&data);
    }

    /// Another server's answer handed on as it came, under the type the caller chose for it.
    pub fn send_passed_on(&mut self, status: u16, content_type: &str, body: &[u8]) {
        self.start(
            status,
            &[
                ("Content-Type", content_type.to_string()),
                ("X-Content-Type-Options", "nosniff".to_string()),
                ("Cache-Control", "no-store".to_string()),
                ("Content-Length", body.len().to_string()),
            ],
        );
        self.write(body);
    }

    /// Text made here, with a type of its own.
    pub fn send_text(&mut self, status: u16, content_type: &str, text: &str, cache: &str) {
        let (data, zipped) = self.maybe_gzip(text.as_bytes().to_vec());
        let mut fields = vec![("Content-Type", content_type.to_string())];
        if zipped {
            fields.push(("Content-Encoding", "gzip".to_string()));
            fields.push(("Vary", "Accept-Encoding".to_string()));
        }
        fields.push(("Content-Length", data.len().to_string()));
        fields.push(("Cache-Control", cache.to_string()));
        self.start(status, &fields);
        self.write(&data);
    }

    /// A redirect.
    pub fn redirect(&mut self, place: &str) {
        self.start(
            302,
            &[("Location", place.to_string()), ("Cache-Control", "no-cache".to_string()), ("Content-Length", "0".to_string())],
        );
    }

    /// `send_error(status)`: the little page Python's server says it with.
    pub fn send_error_page(&mut self, status: u16, words: &str, explain: &str) {
        let body = format!(
            "<!DOCTYPE HTML>\n<html lang=\"en\">\n    <head>\n        <meta charset=\"utf-8\">\n        <style type=\"text/css\">\n            :root {{\n                color-scheme: light dark;\n            }}\n        </style>\n        <title>Error response</title>\n    </head>\n    <body>\n        <h1>Error response</h1>\n        <p>Error code: {status}</p>\n        <p>Message: {words}.</p>\n        <p>Error code explanation: {status} - {explain}.</p>\n    </body>\n</html>\n"
        );
        self.start(
            status,
            &[
                ("Connection", "close".to_string()),
                ("Content-Type", "text/html;charset=utf-8".to_string()),
                ("Content-Length", body.len().to_string()),
            ],
        );
        self.write(body.as_bytes());
        self.close = true;
    }

    /// A file: by its ETag "not modified", gzipped when it is text.
    pub fn send_file(&mut self, path: &Path, content_type: &str) {
        let Ok(meta) = std::fs::metadata(path) else {
            self.send_error_page(404, "Not Found", "Nothing matches the given URI");
            return;
        };
        let stamp = i128::from(meta.mtime()) * 1_000_000_000 + i128::from(meta.mtime_nsec());
        let etag = format!("\"{stamp:x}-{:x}\"", meta.size());
        if self.field("If-None-Match").as_deref() == Some(etag.as_str()) {
            self.start(304, &[("ETag", etag), ("Cache-Control", "no-cache".to_string())]);
            return;
        }
        let Ok(data) = std::fs::read(path) else {
            self.send_error_page(404, "Not Found", "Nothing matches the given URI");
            return;
        };
        let main_type = content_type.split(';').next().unwrap_or(content_type);
        let is_text = content_type.split('/').next() == Some("text")
            || matches!(main_type, "application/javascript" | "application/json" | "image/svg+xml");
        let (data, zipped) = if is_text { self.maybe_gzip(data) } else { (data, false) };
        let mut fields = vec![("Content-Type", content_type.to_string())];
        if zipped {
            fields.push(("Content-Encoding", "gzip".to_string()));
            fields.push(("Vary", "Accept-Encoding".to_string()));
        }
        fields.push(("Content-Length", data.len().to_string()));
        fields.push(("ETag", etag));
        fields.push(("Cache-Control", "no-cache".to_string()));
        self.start(200, &fields);
        self.write(&data);
    }

    /// The request's JSON body, which must be an object. No body reads as an empty one. A body that cannot be measured ends the connection: what follows it is no request.
    pub fn read_body(&mut self) -> Result<Value, AppError> {
        let raw = self.read_raw_body()?;
        let parsed: Value = match raw.is_empty() {
            true => Value::Object(serde_json::Map::new()),
            false => std::str::from_utf8(&raw)
                .ok()
                .and_then(|text| serde_json::from_str(text).ok())
                .ok_or_else(|| AppError::new("request body is not valid JSON"))?,
        };
        let kind = match &parsed {
            Value::Object(_) => return Ok(parsed),
            Value::Null => "null",
            Value::Bool(_) => "boolean",
            Value::Number(_) => "number",
            Value::String(_) => "string",
            Value::Array(_) => "array",
        };
        Err(AppError::new(format!("request body must be a JSON object, not {kind}")))
    }

    /// The bytes of the request's body.
    pub fn read_raw_body(&mut self) -> Result<Vec<u8>, AppError> {
        if self.field_or_empty("Transfer-Encoding").to_lowercase().contains("chunked") {
            self.close = true;
            return Err(AppError::with_status("chunked request bodies are not accepted", 411));
        }
        let said = self.field("Content-Length").unwrap_or_else(|| "0".to_string());
        let Ok(length) = Coerce::strip(&said).parse::<i64>() else {
            self.close = true;
            return Err(AppError::new("bad Content-Length"));
        };
        let mut raw = Vec::new();
        if length > 0 && (&mut *self.source).take(length as u64).read_to_end(&mut raw).is_err() {
            self.close = true;
        }
        Ok(raw)
    }

    /// The session cookie's value, as `SimpleCookie` reads the field: "" when there is none.
    pub fn cookie(&self, name: &str) -> String {
        let field = self.field_or_empty("Cookie");
        let found = field.split(';').filter_map(|pair| pair.split_once('=')).find(|(said, _)| Coerce::strip(said) == name);
        found.map_or_else(String::new, |(_, value)| Coerce::strip(value).trim_matches('"').to_string())
    }
}
