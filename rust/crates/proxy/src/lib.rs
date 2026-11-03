//! The caravan's entry: every client's request to any pool or model, on the entry's one port.
//!
//! Each file is one object's: `front` decides, `exchange` walks
//! one request down its pool's rows (`pool_steps`) through `queue`, `upstream` or `provider_call` and `relay`, and `board` and `recorder`
//! say what happens.

pub mod admission;
pub mod board;
pub mod client;
pub mod clock;
pub mod config;
pub mod connection;
pub mod drain;
pub mod exchange;
pub mod front;
pub mod listener;
pub mod log;
pub mod output_health;
pub mod places;
pub mod pool_steps;
pub mod pool_watch;
pub mod provider_access;
pub mod provider_call;
pub mod provider_request;
pub mod proxy;
pub mod queue;
pub mod record;
pub mod recorder;
pub mod relay;
pub mod stop;
pub mod subscription_usage;
pub mod upstream;
pub mod watch;
