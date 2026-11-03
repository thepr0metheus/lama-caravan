//! What the routes read from a request and how they end an answer: said once.

use crate::app::App;
use crate::monitoring::MonitorSampler;
use crate::topology::TopologyState;
use crate::web::Exchange;
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The readings.
pub struct Asked;

impl Asked {
    /// `(q.get(name) or [""])[0].strip()`.
    pub fn word(h: &Exchange<'_>, name: &str) -> String {
        Coerce::strip(&h.parsed.param_or(name, "")).to_string()
    }

    /// `str(body.get(name))`: what a refusal names, `None` for a field not sent.
    pub fn said(body: &Value, name: &str) -> String {
        Coerce::str_of(Some(body.get(name).unwrap_or(&Value::Null)))
    }

    /// `int(body.get(name) or 0)`; a value that is no number fails as in Python, with a 500.
    pub fn int_or_zero(body: &Value, name: &str) -> Result<i64, AppError> {
        Coerce::int_or_zero(body.get(name)).ok_or_else(|| AppError::with_status(format!("{name} is not a number"), 500))
    }

    /// `int(body.get(name))`: a value that is not there fails with Python's words, a 500, as it always did.
    pub fn int_strict(body: &Value, name: &str) -> Result<i64, AppError> {
        match body.get(name).filter(|said| !said.is_null()) {
            None => Err(AppError::with_status(
                "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'",
                500,
            )),
            Some(said) => Coerce::int(said).ok_or_else(|| AppError::with_status(format!("{name} is not a number"), 500)),
        }
    }

    /// `{"ok": True, **done}`.
    pub fn ok_with(done: Value) -> Value {
        let mut out = serde_json::Map::new();
        out.insert("ok".to_string(), json!(true));
        out.extend(Coerce::fields(&done));
        Value::Object(out)
    }

    /// The board, as it stands, with no machine asked.
    pub fn board(app: &App) -> Result<Value, AppError> {
        TopologyState::of(app).state(false)
    }

    /// Sends `out` with the board after it.
    pub fn send_with_board(app: &App, h: &mut Exchange<'_>, mut out: Value) -> Result<(), AppError> {
        Coerce::put(&mut out, "topology", Self::board(app)?);
        h.ok(&out);
        Ok(())
    }

    /// Sends `out` with the board after it, every machine asked first.
    pub fn send_with_fresh_board(app: &App, h: &mut Exchange<'_>, mut out: Value) -> Result<(), AppError> {
        Coerce::put(&mut out, "topology", TopologyState::of(app).state(true)?);
        h.ok(&out);
        Ok(())
    }

    /// Sends `out` with the monitor after it.
    pub fn send_with_monitor(app: &App, h: &mut Exchange<'_>, mut out: Value) {
        Coerce::put(&mut out, "monitor", MonitorSampler::of(app).state(0));
        h.ok(&out);
    }
}
