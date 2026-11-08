//! One row of the scout's table of paths: its path, what it is for, who may ask. The rows of one list are the whole surface: the handlers answer by them, and `/openapi.json` is written from them, so that what the scout does and what it says it does are one list. The words live in `routes.json`.

use rules::Coerce;
use serde_json::{Map, Value};

/// The ways a path is answered.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RouteKind {
    /// The HTML of the scout's page.
    Page,
    /// An open GET.
    Public,
    /// A GET behind the token.
    Get,
    /// A GET behind the token, with a query.
    Query,
    /// A POST behind the token.
    Post,
    /// A path the server answers itself, ahead of the gate: the pairing form's.
    Own,
    /// A path of the machine's entry by OpenAI's API.
    Entry,
    /// The controller's way into a cell: the request passed on to the cell as it came (cells/door.rs).
    Door,
}

/// A row.
#[derive(Debug, Clone)]
pub struct RouteRow {
    fields: Map<String, Value>,
}

impl RouteRow {
    /// The table, from the words kept with this program. A table that does not read is no table: the guard's test sees that, and the start says so.
    pub fn table() -> Result<Vec<Self>, serde_json::Error> {
        let rows: Vec<Map<String, Value>> = serde_json::from_str(include_str!("../routes.json"))?;
        Ok(rows.into_iter().map(|fields| Self { fields }).collect())
    }

    /// `GET` or `POST`.
    pub fn method(&self) -> String {
        Coerce::text(self.fields.get("method"))
    }

    /// Its path.
    pub fn path(&self) -> String {
        Coerce::text(self.fields.get("path"))
    }

    /// A field's words, "" for none.
    pub fn word(&self, name: &str) -> String {
        Coerce::text(self.fields.get(name))
    }

    fn says(&self, name: &str) -> bool {
        Coerce::truthy(self.fields.get(name))
    }

    /// A list field.
    pub fn list(&self, name: &str) -> Vec<String> {
        self.fields.get(name).and_then(Value::as_array).into_iter().flatten().map(|word| Coerce::text(Some(word))).collect()
    }

    /// What each `{name}` of its path template is.
    pub fn params(&self) -> Vec<(String, String)> {
        self.fields
            .get("params")
            .and_then(Value::as_object)
            .into_iter()
            .flatten()
            .map(|(name, said)| (name.clone(), Coerce::text(Some(said))))
            .collect()
    }

    /// Which way it is answered.
    pub fn kind(&self) -> RouteKind {
        if self.says("page") {
            RouteKind::Page
        } else if self.says("door") {
            RouteKind::Door
        } else if self.says("entry") {
            RouteKind::Entry
        } else if self.method() == "POST" {
            if self.says("own") { RouteKind::Own } else { RouteKind::Post }
        } else if self.says("query") {
            RouteKind::Query
        } else if self.says("public") {
            RouteKind::Public
        } else {
            RouteKind::Get
        }
    }

    /// Whether anyone may ask: the page, the paths marked `public` and the machine's entry.
    pub fn needs_no_token(&self) -> bool {
        self.says("page") || self.says("public") || self.says("entry")
    }

    /// Whether the route's own code reads a body. The door's passes it on unread.
    pub fn reads_a_body(&self) -> bool {
        self.method() == "POST" && (self.says("body") || self.says("body_more"))
    }

    /// Whether it is the door to a cell.
    pub fn is_door(&self) -> bool {
        self.says("door")
    }

    /// Whether the body's fields are a floor and not the whole.
    pub fn body_more(&self) -> bool {
        self.says("body_more")
    }

    /// Whether it is a path of the entry.
    pub fn is_entry(&self) -> bool {
        self.says("entry")
    }
}
