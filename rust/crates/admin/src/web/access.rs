//! Who may call a route of the admin. A session cookie for humans, the fleet token for the machine endpoints.

/// How a route is reached.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Access {
    /// By anyone.
    Public,
    /// With the fleet token.
    Machine,
    /// With the fleet token, as a header or a bearer, or a session: Prometheus sends no cookies.
    Metrics,
    /// With a session.
    Session,
}

/// The tables.
pub struct RouteAccess;

impl RouteAccess {
    const PUBLIC_GET: [&'static str; 12] = [
        "/login",
        "/setup",
        "/favicon.svg",
        "/favicon.ico",
        "/api/auth/me",
        "/health",
        "/api/health",
        "/healthz",
        "/openapi.json",
        "/api/packages",
        // A new machine has no token yet, and neither holds a secret: the program and the script that places it.
        "/scout/install.sh",
        "/scout/bundle.tar.gz",
    ];
    const PUBLIC_POST: [&'static str; 2] = ["/api/auth/login", "/api/auth/setup"];
    const MACHINE_GET: [&'static str; 5] =
        ["/api/models/download", "/api/models/folder", "/api/cell-assets", "/api/cell-assets/file", "/api/fleet/cell-start"];
    const MACHINE_POST: [&'static str; 1] = ["/api/topology/client-heartbeat"];
    const VIEWER_ALSO: [&'static str; 1] = ["/api/auth/logout"];
    const ADMIN_GET: [&'static str; 2] = ["/api/agent-proxies/raw", "/api/cell-live"];

    /// How `method path` is reached.
    pub fn kind(method: &str, path: &str) -> Access {
        let get = method == "GET";
        let post = method == "POST";
        if (get && Self::PUBLIC_GET.contains(&path)) || (post && Self::PUBLIC_POST.contains(&path)) {
            return Access::Public;
        }
        if (get && Self::MACHINE_GET.contains(&path)) || (post && Self::MACHINE_POST.contains(&path)) {
            return Access::Machine;
        }
        if get && path == "/metrics" {
            return Access::Metrics;
        }
        Access::Session
    }

    /// Whether a viewer account may call `method path`: it is read-only, and the raw routes file holds the clients' keys.
    pub fn viewer_may(method: &str, path: &str) -> bool {
        (method == "GET" && !Self::ADMIN_GET.contains(&path)) || Self::VIEWER_ALSO.contains(&path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_route_is_reached_its_way() {
        assert_eq!(RouteAccess::kind("GET", "/health"), Access::Public);
        assert_eq!(RouteAccess::kind("POST", "/health"), Access::Session);
        assert_eq!(RouteAccess::kind("POST", "/api/auth/login"), Access::Public);
        assert_eq!(RouteAccess::kind("GET", "/api/models/download"), Access::Machine);
        assert_eq!(RouteAccess::kind("GET", "/metrics"), Access::Metrics);
        assert_eq!(RouteAccess::kind("GET", "/board"), Access::Session);
        assert!(RouteAccess::viewer_may("GET", "/board"));
        assert!(!RouteAccess::viewer_may("GET", "/api/agent-proxies/raw"));
        assert!(!RouteAccess::viewer_may("POST", "/api/x"));
        assert!(RouteAccess::viewer_may("POST", "/api/auth/logout"));
    }
}
