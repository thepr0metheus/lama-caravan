//! What the controller answers, by topic.

pub mod asked;
pub mod auth;
pub mod cells;
pub mod cloud;
pub mod fleet;
pub mod health;
pub mod hf;
pub mod models;
pub mod pages;
pub mod pools;
pub mod proxies;
pub mod system;
pub mod topology;

use crate::web::RouteTable;

/// The whole table.
pub struct AllRoutes;

impl AllRoutes {
    /// Every route. A path twice is said at the start.
    pub fn table() -> Result<RouteTable, String> {
        let mut table = RouteTable::default();
        table.add_prefix("/api/monitor/", system::SystemRoutes::monitor);
        table.add_prefix("/js/", pages::PageRoutes::static_subdir);
        table.add_prefix("/css/", pages::PageRoutes::static_subdir);
        for routes in [
            auth::AuthRoutes::ROUTES,
            health::HealthRoutes::ROUTES,
            pages::PageRoutes::ROUTES,
            models::ModelRoutes::ROUTES,
            hf::HfRoutes::ROUTES,
            fleet::FleetRoutes::ROUTES,
            cells::CellRoutes::ROUTES,
            topology::TopologyRoutes::ROUTES,
            pools::PoolRoutes::ROUTES,
            cloud::CloudRoutes::ROUTES,
            proxies::ProxyRoutes::ROUTES,
            system::SystemRoutes::ROUTES,
        ] {
            table.add(routes)?;
        }
        Ok(table)
    }
}
