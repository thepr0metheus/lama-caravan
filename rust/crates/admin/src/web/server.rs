//! The controller's listener: HTTP/1.1 with connections kept, one thread to a connection, as `ThreadingHTTPServer` did. Only what is decided per request is here: a route's work is its own.

use super::access::{Access, RouteAccess};
use super::exchange::Exchange;
use super::table::RouteTable;
use crate::app::App;
use net::Closing;
use plumbing::Log;
use rules::AppError;
use serde_json::json;
use std::io::BufReader;
use std::net::{TcpListener, TcpStream};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Arc;
use std::time::Duration;
use wire::{HeadError, RequestHead};

/// The server.
pub struct AdminServer {
    app: Arc<App>,
    routes: Arc<RouteTable>,
    server_word: Arc<str>,
}

impl AdminServer {
    /// A connection quiet for this long ends.
    const IDLE: Duration = Duration::from_secs(30);

    /// A server over this controller.
    pub fn new(app: Arc<App>, routes: RouteTable) -> Self {
        let server_word: Arc<str> = Arc::from(format!("lama-caravan/{}", crate::VERSION));
        Self { app, routes: Arc::new(routes), server_word }
    }

    /// Serves `listener` for good.
    pub fn serve(&self, listener: &TcpListener) -> ! {
        loop {
            match listener.accept() {
                Ok((stream, peer)) => self.connection(stream, peer.ip().to_string()),
                Err(error) => {
                    Log::line(&format!("accept failed: {error}"));
                    std::thread::sleep(Duration::from_millis(100));
                }
            }
        }
    }

    fn connection(&self, stream: TcpStream, peer: String) {
        let (app, routes, word) = (Arc::clone(&self.app), Arc::clone(&self.routes), Arc::clone(&self.server_word));
        let started = std::thread::Builder::new().name("admin-connection".to_string()).spawn(move || {
            Connection { app: &app, routes: &routes, peer, server_word: &word }.serve(stream);
        });
        if let Err(error) = started {
            Log::line(&format!("no thread for a connection: {error}"));
        }
    }
}

/// One client's connection.
struct Connection<'server> {
    app: &'server App,
    routes: &'server RouteTable,
    peer: String,
    server_word: &'server str,
}

impl Connection<'_> {
    fn serve(&self, stream: TcpStream) {
        if stream.set_read_timeout(Some(AdminServer::IDLE)).is_err() || stream.set_nodelay(true).is_err() {
            return;
        }
        let Ok(out) = stream.try_clone() else {
            return;
        };
        self.requests(&mut BufReader::new(stream), &out);
        Closing::of(&out);
    }

    /// The requests of this connection, one after another, until one of them or the client ends it.
    fn requests(&self, source: &mut BufReader<TcpStream>, out: &TcpStream) {
        loop {
            let head = match RequestHead::read(source) {
                Ok(head) => head,
                Err(HeadError::Closed | HeadError::Io(_)) => return,
                Err(HeadError::Malformed(words)) => {
                    let now = self.app.now_seconds();
                    let bare = RequestHead { method: "GET".to_string(), target: "/".to_string(), headers: wire::Headers::new() };
                    Exchange::new(bare, source, out, self.peer.clone(), now, self.server_word).send_error_page(
                        400,
                        &format!("Bad request syntax ({words})"),
                        "Bad request syntax or unsupported method",
                    );
                    return;
                }
            };
            if !self.one(head, source, out) {
                return;
            }
        }
    }

    /// Answers one request; whether the connection goes on.
    fn one(&self, head: RequestHead, source: &mut BufReader<TcpStream>, out: &TcpStream) -> bool {
        let wants_close = head.headers.text_of("Connection").to_lowercase().contains("close");
        let mut exchange = Exchange::new(head, source, out, self.peer.clone(), self.app.now_seconds(), self.server_word);
        let handled = catch_unwind(AssertUnwindSafe(|| self.handle(&mut exchange)));
        match handled {
            Ok(Ok(())) => {}
            Ok(Err(error)) => Self::fail(&mut exchange, &error),
            Err(_) => Self::fail(&mut exchange, &AppError::with_status("internal error", 500)),
        }
        !(wants_close || exchange.close)
    }

    /// Answers an error; if the answer has already started, ends the connection instead of corrupting what was being sent.
    fn fail(exchange: &mut Exchange<'_>, error: &AppError) {
        if exchange.responded() {
            exchange.close = true;
            Log::line(&format!("failed mid-response on {}: {}", exchange.parsed.path, error.message));
            return;
        }
        exchange.send_json(&json!({"error": error.message}), error.status);
    }

    fn handle(&self, exchange: &mut Exchange<'_>) -> Result<(), AppError> {
        let method = exchange.method().to_string();
        let path = exchange.parsed.path.clone();
        if !matches!(method.as_str(), "GET" | "POST" | "DELETE") {
            exchange.send_error_page(501, &format!("Unsupported method ('{method}')"), "Server does not support this operation");
            return Ok(());
        }
        if !Guard::allows(self.app, exchange, &path, &method)? {
            return Ok(());
        }
        match method.as_str() {
            "GET" => match self.routes.get(&path) {
                Some(route) => route(self.app, exchange),
                None => Self::not_found(exchange),
            },
            "POST" => {
                // The body is read before the path is looked up: a bad body on an unknown path is its own answer.
                let body = exchange.read_body()?;
                match self.routes.post(&path) {
                    Some(route) => route(self.app, exchange, body),
                    None => Self::not_found(exchange),
                }
            }
            _ => match self.routes.delete(&path) {
                Some(route) => route(self.app, exchange),
                None => Self::not_found(exchange),
            },
        }
    }

    fn not_found(exchange: &mut Exchange<'_>) -> Result<(), AppError> {
        exchange.send_json(&json!({"error": "Not found"}), 404);
        Ok(())
    }
}

/// Whether a request may proceed; a refusal is answered here, and every refusal ends the connection.
struct Guard;

impl Guard {
    fn allows(app: &App, exchange: &mut Exchange<'_>, path: &str, method: &str) -> Result<bool, AppError> {
        let first_run = !app.auth.enabled()?;
        let kind = RouteAccess::kind(method, path);
        if kind == Access::Public {
            return Ok(true);
        }
        if kind == Access::Metrics {
            let authorization = exchange.field_or_empty("Authorization");
            let bearer = rules::Coerce::strip(authorization.strip_prefix("Bearer ").unwrap_or(&authorization)).to_string();
            if app.auth.fleet_token_verify(&exchange.field_or_empty("X-Caravan-Token"))?
                || app.auth.fleet_token_verify(&bearer)?
            {
                return Ok(true);
            }
        }
        if kind == Access::Machine {
            if app.auth.fleet_token_verify(&exchange.field_or_empty("X-Caravan-Token"))? {
                return Ok(true);
            }
            exchange.close = true;
            exchange.send_json(&json!({"error": "fleet token required (X-Caravan-Token)"}), 401);
            return Ok(false);
        }
        let session = app.session_of(exchange)?;
        if let Some(session) = session {
            if session.role == "viewer" && !RouteAccess::viewer_may(method, path) {
                exchange.close = true;
                exchange.send_json(&json!({"error": "read-only account"}), 403);
                return Ok(false);
            }
            return Ok(true);
        }
        exchange.close = true;
        if method == "GET" && (path == "/" || !path.starts_with("/api/")) {
            exchange.start(
                302,
                &[("Location", if first_run { "/setup" } else { "/login" }.to_string()), ("Content-Length", "0".to_string())],
            );
            return Ok(false);
        }
        let words = if first_run { "no account yet: create the first one at /setup" } else { "authentication required" };
        exchange.send_json(&json!({"error": words}), 401);
        Ok(false)
    }
}
