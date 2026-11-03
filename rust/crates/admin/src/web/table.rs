//! The route tables. Prefix routes are checked before the exact ones, in order.

use super::exchange::Exchange;
use crate::app::App;
use rules::AppError;
use serde_json::Value;
use std::collections::HashMap;

/// A route's work on a request with no body.
pub type GetRoute = fn(&App, &mut Exchange<'_>) -> Result<(), AppError>;
/// A route's work on a request with a JSON body.
pub type PostRoute = fn(&App, &mut Exchange<'_>, Value) -> Result<(), AppError>;

/// A topic's routes, as it lists them.
#[derive(Debug, Clone, Copy, Default)]
pub struct Routes {
    /// GET by path.
    pub get: &'static [(&'static str, GetRoute)],
    /// POST by path.
    pub post: &'static [(&'static str, PostRoute)],
    /// DELETE by path.
    pub delete: &'static [(&'static str, GetRoute)],
}

/// All of them.
#[derive(Debug, Default)]
pub struct RouteTable {
    prefix: Vec<(&'static str, GetRoute)>,
    get: HashMap<&'static str, GetRoute>,
    post: HashMap<&'static str, PostRoute>,
    delete: HashMap<&'static str, GetRoute>,
}

impl RouteTable {
    /// A route that owns every path under a prefix.
    pub fn add_prefix(&mut self, prefix: &'static str, route: GetRoute) {
        self.prefix.push((prefix, route));
    }

    /// A topic's routes. The same path twice is the program's own defect, said at the start.
    pub fn add(&mut self, routes: Routes) -> Result<(), String> {
        let twice = |path: &str| format!("duplicate route {path}");
        for (path, route) in routes.get {
            if self.get.insert(path, *route).is_some() {
                return Err(twice(path));
            }
        }
        for (path, route) in routes.post {
            if self.post.insert(path, *route).is_some() {
                return Err(twice(path));
            }
        }
        for (path, route) in routes.delete {
            if self.delete.insert(path, *route).is_some() {
                return Err(twice(path));
            }
        }
        Ok(())
    }

    /// Every exact route: (method in small letters, path).
    pub fn exact(&self) -> Vec<(&'static str, &'static str)> {
        let of = |method: &'static str, paths: Vec<&'static str>| paths.into_iter().map(move |path| (method, path));
        of("get", self.get.keys().copied().collect())
            .chain(of("post", self.post.keys().copied().collect()))
            .chain(of("delete", self.delete.keys().copied().collect()))
            .collect()
    }

    /// The route of a GET.
    pub fn get(&self, path: &str) -> Option<GetRoute> {
        let prefixed = self.prefix.iter().find(|(prefix, _)| path.starts_with(prefix));
        prefixed.map(|(_, route)| *route).or_else(|| self.get.get(path).copied())
    }

    /// The route of a POST.
    pub fn post(&self, path: &str) -> Option<PostRoute> {
        self.post.get(path).copied()
    }

    /// The route of a DELETE.
    pub fn delete(&self, path: &str) -> Option<GetRoute> {
        self.delete.get(path).copied()
    }

    /// Every path, by method: what the description of the API is held to.
    pub fn paths(&self) -> Vec<(&'static str, &'static str)> {
        let mut out: Vec<(&'static str, &'static str)> = Vec::new();
        out.extend(self.get.keys().map(|path| ("GET", *path)));
        out.extend(self.post.keys().map(|path| ("POST", *path)));
        out.extend(self.delete.keys().map(|path| ("DELETE", *path)));
        out.sort();
        out
    }
}
