//! What a waiting stream is kept alive with.

use serde_json::json;

/// An event that carries a real content-bearing delta, `reasoning_content`. A client (OpenClaw, read from its logs) resets its
/// read timeout only on chunks with token text and ignores comment lines, role-only chunks and `content: null`; a space on the
/// thinking channel counts as activity and never reaches the visible answer.
pub struct Keepalive;

impl Keepalive {
    /// The event's bytes, for a model named `model` at the moment `created`.
    pub fn bytes(model: &str, created: i64) -> Vec<u8> {
        let payload = json!({
            "choices": [{"finish_reason": null, "index": 0, "delta": {"reasoning_content": " "}}],
            "created": created,
            "id": "chatcmpl-keepalive",
            "model": model,
            "object": "chat.completion.chunk",
        });
        format!("data: {payload}\n\n").into_bytes()
    }
}
