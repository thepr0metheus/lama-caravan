//! The move of 2026-11-07, once, at the controller's start: every client's record gets its id and loses the number it had. Keys,
//! names and settings stay as they were.

use super::{ClientIds, FormerPorts};
use crate::app::App;
use crate::board_layout::ClientOrder;
use crate::proxies::config::ProxiesConfig;
use rules::{AppError, Coerce, RouteId};
use serde_json::{Value, json};
#[cfg(test)]
use std::path::PathBuf;

/// The records as the move leaves them, and what it did.
#[derive(Debug, Default, PartialEq)]
struct Moved {
    routes: Vec<Value>,
    given: Vec<Value>,
    retired: Vec<Value>,
    changed: bool,
}

/// Gives the clients' records their ids.
pub struct ClientIdsGiven;

impl ClientIdsGiven {
    /// The fields of the number a record had: what the move takes away.
    const NUMBER_FIELDS: [&'static str; 2] = ["port", "portClosed"];
    /// What the copy of the file before the move is called after the file's own name.
    const COPY_SUFFIX: &'static str = "bak-before-client-ids";

    /// The file as it was, kept beside it under a name of its own: a release before the move reads no record without a number, and
    /// the way back past it is this copy (deploy/nas/README.md). No copy, no move.
    fn keep_copy(app: &App) -> Result<(), AppError> {
        let path = app.proxies.path();
        let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let copy = path.with_file_name(format!("{name}.{}-{}", Self::COPY_SUFFIX, app.stamp()));
        std::fs::copy(path, &copy)
            .map(drop)
            .map_err(|error| AppError::with_status(format!("the copy before the move was not kept: {error}"), 500))
    }

    /// A record of the old kind, made by the form of a port of its own: the entry has refused it since 2026-11-02
    /// (`entry:not-a-consumer`), and without its number nothing is left of it.
    fn is_old_kind(route: &Value) -> bool {
        Coerce::stripped(route.get("kind")).to_lowercase() != "consumer"
    }

    /// `routes` with every client known by its id; `former` learns the number each one had.
    fn moved(routes: Vec<Value>, former: &mut FormerPorts) -> Result<Moved, AppError> {
        let mut taken = ClientIds::taken(&routes);
        let mut out = Moved::default();
        for route in routes {
            if !route.is_object() {
                out.routes.push(route);
                continue;
            }
            // absent-ok: a record that names no number had none, and leaves none behind.
            let port = Coerce::int_or_zero(route.get("port")).unwrap_or(0);
            let label = Coerce::text(route.get("label"));
            if Self::is_old_kind(&route) {
                out.retired.push(json!({"label": label, "port": port}));
                out.changed = true;
                continue;
            }
            let mut row = route;
            let mut id = ClientIds::of(&row);
            if !RouteId::acceptable(&id) {
                id = ClientIds::mint(&taken)?;
                taken.insert(id.clone());
                Coerce::put(&mut row, ClientIds::FIELD, json!(id));
                out.given.push(json!({"label": label, "id": id, "port": port}));
                out.changed = true;
            }
            former.note(port, &id);
            for field in Self::NUMBER_FIELDS {
                out.changed |= Coerce::take(&mut row, field).is_some();
            }
            out.routes.push(row);
        }
        Ok(out)
    }

    /// The move, when something is left to move: what it gave and what it retired, `None` when every record already has its id.
    pub fn migrate(app: &App) -> Result<Option<Value>, AppError> {
        let config = ProxiesConfig::of(app);
        let mut payload = config.read_payload();
        let Some(routes) = payload.get("routes").and_then(Value::as_array).cloned() else {
            return Ok(None);
        };
        let mut former = FormerPorts::of(&payload);
        let moved = Self::moved(routes, &mut former)?;
        if !moved.changed {
            return Ok(None);
        }
        Self::keep_copy(app)?;
        Coerce::put(&mut payload, "routes", Value::Array(moved.routes));
        Coerce::put(&mut payload, FormerPorts::FIELD, former.json());
        config.write_payload(payload)?;
        ClientOrder::adopt_ids(app, &former);
        Ok(Some(json!({"given": moved.given, "retired": moved.retired})))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::{TestApp, TestFolder};

    #[test]
    fn the_move_keeps_every_key_and_the_history_and_runs_once() {
        let folder = TestFolder::new("client-ids-given");
        let app = TestApp::over(&folder.path, &[]);
        let path = app.proxies.path().to_path_buf();
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let before = json!({"routes": [
            {"label": "hermes", "port": 23001, "kind": "consumer", "apiKey": "lcv1_one", "portClosed": true, "deny": ["pool:a"]},
            {"label": "opencode m4", "port": 23003, "kind": "consumer", "builtin": "opencode", "apiKey": "lcv1_two", "portClosed": true},
        ], "entry": {"port": 23999}});
        std::fs::write(&path, before.to_string()).unwrap();
        app.admin.saving(|doc| {
            doc.insert("topology".to_string(), json!({"layout": {"clientOrder": [23003, 23001, 23009]}}));
        });
        let done = ClientIdsGiven::migrate(&app).unwrap().unwrap();
        assert_eq!(done["given"].as_array().unwrap().len(), 2);
        let after: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        let routes = after["routes"].as_array().unwrap();
        let ids: Vec<String> = routes.iter().map(ClientIds::of).collect();
        assert!(ids.iter().all(|id| RouteId::acceptable(id) && id.starts_with("client-")), "{ids:?}");
        assert_eq!((routes[0]["apiKey"].clone(), routes[1]["apiKey"].clone()), (json!("lcv1_one"), json!("lcv1_two")));
        assert!(routes.iter().all(|route| route.get("port").is_none() && route.get("portClosed").is_none()));
        assert_eq!((routes[0]["deny"].clone(), routes[1]["builtin"].clone()), (json!(["pool:a"]), json!("opencode")));
        assert_eq!(after["formerPorts"], json!({"23001": ids[0], "23003": ids[1]}));
        let order = app.admin.read(|doc| doc["topology"]["layout"]["clientOrder"].clone());
        assert_eq!(order, json!([ids[1], ids[0]]));
        let copies: Vec<PathBuf> = std::fs::read_dir(path.parent().unwrap())
            .unwrap()
            .flatten()
            .map(|entry| entry.path())
            .filter(|found| found.to_string_lossy().contains(".bak-before-client-ids-"))
            .collect();
        assert_eq!(copies.len(), 1);
        assert_eq!(serde_json::from_slice::<Value>(&std::fs::read(&copies[0]).unwrap()).unwrap(), before);
        let written = std::fs::read(&path).unwrap();
        assert!(ClientIdsGiven::migrate(&app).unwrap().is_none());
        assert_eq!(std::fs::read(&path).unwrap(), written);
    }

    #[test]
    fn a_client_keeps_its_key_and_its_name_and_loses_its_number() {
        let routes = vec![
            json!({"label": "hermes", "port": 23001, "kind": "consumer", "apiKey": "k1", "portClosed": true, "deny": ["pool:a"]}),
            json!({"label": "kept", "id": "client-kept", "port": 23002, "kind": "consumer", "apiKey": "k2"}),
            json!({"label": "old", "port": 23003, "kind": "", "apiKey": "k3"}),
            json!("not a record"),
        ];
        let mut former = FormerPorts::default();
        let moved = ClientIdsGiven::moved(routes, &mut former).unwrap();
        assert!(moved.changed);
        assert_eq!(moved.routes.len(), 3);
        let hermes = &moved.routes[0];
        let id = ClientIds::of(hermes);
        assert!(id.starts_with("client-"));
        assert_eq!(
            (hermes.get("port"), hermes.get("portClosed"), hermes["apiKey"].clone(), hermes["deny"].clone()),
            (None, None, json!("k1"), json!(["pool:a"]))
        );
        assert_eq!(moved.routes[1], json!({"label": "kept", "id": "client-kept", "kind": "consumer", "apiKey": "k2"}));
        assert_eq!(moved.routes[2], json!("not a record"));
        assert_eq!(former.id_of(23001), Some(id.as_str()));
        assert_eq!(former.id_of(23002), Some("client-kept"));
        assert_eq!(former.id_of(23003), None);
        assert_eq!(moved.given, vec![json!({"label": "hermes", "id": id, "port": 23001})]);
        assert_eq!(moved.retired, vec![json!({"label": "old", "port": 23003})]);
    }

    #[test]
    fn a_second_move_finds_nothing_to_move() {
        let mut former = FormerPorts::default();
        let first = ClientIdsGiven::moved(vec![json!({"label": "a", "port": 23001, "kind": "consumer"})], &mut former).unwrap();
        let again = ClientIdsGiven::moved(first.routes.clone(), &mut former).unwrap();
        assert!(!again.changed);
        assert_eq!(again.routes, first.routes);
        assert_eq!(former.json().as_object().unwrap().len(), 1);
    }
}
