//! How long a release in place waits for the requests that run before the program it replaces ends: the controller for its proxy's
//! (admin startup.rs), a machine's scout for those through its entry (scout own_release.rs). One figure for the two: a client's request
//! passes through both, and a release cuts it only past this, whichever of the two programs it replaces.

/// The patience of a release.
pub struct ReleasePatience;

impl ReleasePatience {
    /// Ten minutes, in seconds: a long answer is written whole in them, and a stream held past them holds a release back no longer.
    pub const SECONDS: f64 = 600.0;
}
