//! Connections to what the caravan calls: a model's machine over plain TCP, a provider over TLS, and the ones kept open between requests.
//!
//! The one crate that knows TLS (`scripts/check_rust_contract.py` holds it here). It reads no clock: a wait comes back to the caller after
//! its turn, so that the proxy's own look-out goes on running around every wait.

pub mod closing;
pub mod dial;
pub mod digest;
pub mod kept;
pub mod sealed;
pub mod stream;
pub mod tls;

pub use closing::Closing;
pub use dial::Dial;
pub use digest::{Base64Std, Base64Url, Pbkdf2, Randomness, Sha1, Sha1Stream, Sha256};
pub use kept::{KeptConnections, Target};
pub use sealed::{Scrypt, SealedBytes};
pub use stream::Stream;
pub use tls::{TlsError, TrustedRoots};
