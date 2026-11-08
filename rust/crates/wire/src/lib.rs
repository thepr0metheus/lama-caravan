//! HTTP/1.1 on a socket: a request's head and body off the wire, an answer's head and framing, a reply's bytes.
//!
//! It knows nothing of the caravan: no route, no model, no journal. Everything above it takes
//! its messages from here, so one parser answers for how a message is framed. Reading is generic over
//! `Read`, which is how the tests drive it without a socket; only `peer` touches `TcpStream`.

pub mod answer;
pub mod body;
pub mod headers;
pub mod lines;
pub mod peer;
pub mod percent;
pub mod reply;
pub mod request;
#[cfg(test)]
mod stutter;

pub use answer::{AnswerBody, AnswerHead, AnswerHeadReader};
pub use body::{BodyError, RequestBody};
pub use headers::Headers;
pub use lines::{Lines, Next};
pub use peer::Peer;
pub use percent::Percent;
pub use reply::{HttpDate, Reply};
pub use request::{HeadError, RequestHead};
