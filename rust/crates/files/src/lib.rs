//! The caravan's files: the settings it reads and the journal and the state it writes.
//!
//! `docs/architecture.md` says what lies under the data folder.

pub mod atomic;
pub mod credential_vault;
pub mod journal;
pub mod settings;

pub use atomic::AtomicFile;
pub use credential_vault::{AuthField, CredentialVault, TokenRequest};
pub use journal::Journal;
pub use settings::{Documents, Settings, SettingsFiles, SettingsPaths};
