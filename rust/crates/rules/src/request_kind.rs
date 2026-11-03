//! What kind of request this is, by method and path.

/// One answer for the fleet on whether a failure is the model's or only the path's.
pub struct RequestKind;

impl RequestKind {
    /// Paths whose answer says something about the model behind an exit.
    const INFERENCE: [&'static str; 14] = [
        "/chat/completions",
        "/completions",
        "/embeddings",
        "/responses",
        "/messages",
        "/rerank",
        "/audio/transcriptions",
        "/audio/translations",
        "/audio/speech",
        "/infill",
        "/tokenize",
        "/detokenize",
        "/generate",
        "/predict",
    ];
    /// The paths of a chat.
    const CHAT: [&'static str; 2] = ["/chat/completions", "/responses"];

    /// The path without its query and its trailing slashes.
    fn clean(path: &str) -> &str {
        path.split_once('?').map_or(path, |(before, _)| before).trim_end_matches('/')
    }

    /// True for a request whose failure is the model's failure, not the path's.
    pub fn is_inference(method: &str, path: &str) -> bool {
        method.eq_ignore_ascii_case("POST") && Self::INFERENCE.iter().any(|end| Self::clean(path).ends_with(end))
    }

    /// True for a chat's path.
    pub fn is_chat(path: &str) -> bool {
        Self::CHAT.iter().any(|end| Self::clean(path).ends_with(end))
    }

    /// True for the path of a chat completion: the one kind of work a chat model serves, and what a cell's
    /// "no thinking" lever applies to.
    pub fn is_chat_completion(path: &str) -> bool {
        Self::clean(path).ends_with("/chat/completions")
    }
}
