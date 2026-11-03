//! The models the cell editor offers, and a stamp of them for the board: one walk at a time, and a look at the disk at most every few seconds.

use super::listing::ModelListing;
use super::locator::Locations;
use super::stores::StoreRegistry;
use crate::app::App;
use net::Sha1;
use rules::{Coerce, PythonJson};
use serde_json::{Value, json};
use std::sync::{Arc, Mutex, PoisonError};

/// The last walk.
#[derive(Default)]
pub struct ModelListMemory {
    rows: Mutex<Option<(Arc<Vec<Value>>, f64)>>,
    walking: Mutex<()>,
}

/// The list.
pub struct ModelList<'app> {
    app: &'app App,
}

impl<'app> ModelList<'app> {
    const TTL: f64 = 5.0;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The snapshot of the libraries, right now: a stale look is refreshed behind this answer.
    pub fn locations(app: &App, wait: bool) -> Locations {
        Locations::new(&StoreRegistry::of(app).library_files(false, wait), &app.env.home().to_string_lossy())
    }

    fn walk(&self) -> Arc<Vec<Value>> {
        // absent-ok: a launch config that does not read names the default folder.
        let config = self.app.parse_config().unwrap_or_default();
        let rows = Arc::new(ModelListing::of(self.app).rows(&config, &Self::locations(self.app, false)));
        *self.app.model_list.rows.lock().unwrap_or_else(PoisonError::into_inner) = Some((Arc::clone(&rows), self.app.now()));
        rows
    }

    fn held(&self) -> Option<(Arc<Vec<Value>>, f64)> {
        self.app.model_list.rows.lock().unwrap_or_else(PoisonError::into_inner).clone()
    }

    /// The rows. The first walk is waited for; after it a walk under way leaves the last list to answer.
    pub fn rows(&self) -> Arc<Vec<Value>> {
        let memory = &self.app.model_list;
        match self.held() {
            Some((rows, at)) if self.app.now() - at < Self::TTL => rows,
            None => {
                let _walking = memory.walking.lock().unwrap_or_else(PoisonError::into_inner);
                match self.held() {
                    Some((rows, _)) => rows,
                    None => self.walk(),
                }
            }
            Some((rows, _)) => match memory.walking.try_lock() {
                Ok(_walking) => self.walk(),
                Err(_) => rows,
            },
        }
    }

    /// The rows and their stamp, of the same list.
    pub fn current(&self) -> (Arc<Vec<Value>>, String) {
        let rows = self.rows();
        let stamp = Self::stamp_of(&rows);
        (rows, stamp)
    }

    /// What a list is, in a few characters: a change of a file's size or date, or a file's coming or going, changes it.
    pub fn stamp_of(rows: &[Value]) -> String {
        // absent-ok: `int(r.get(...) or 0)`: a row with no such figure has none to differ by.
        let figure = |row: &Value, key: &str| Coerce::whole(row.get(key));
        let mut facts: Vec<(String, String, i64, i64, bool)> = rows
            .iter()
            .filter(|row| row.is_object())
            .map(|row| {
                (
                    Coerce::text(row.get("path")),
                    Coerce::text(row.get("kind")),
                    figure(row, "size"),
                    figure(row, "mtime"),
                    Coerce::truthy(row.get("libraryOnly")),
                )
            })
            .collect();
        facts.sort();
        let list: Vec<Value> =
            facts.into_iter().map(|(path, kind, size, mtime, library)| json!([path, kind, size, mtime, library])).collect();
        Coerce::first_letters(&Sha1::of(PythonJson::spaced(&Value::Array(list)).as_bytes()), 16).to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::{HandClock, TestApp, TestFolder};

    fn row(path: &str, kind: &str, size: i64, mtime: i64) -> Value {
        json!({"path": path, "kind": kind, "size": size, "mtime": mtime})
    }

    #[test]
    fn a_stamp_goes_by_the_set_of_files_and_not_by_their_order() {
        let (one, other) = (row("q4.gguf", "model", 4000, 1_700_000_000), row("e.gguf", "model", 50, 1_700_000_001));
        let base = ModelList::stamp_of(&[one.clone(), other.clone()]);
        assert_eq!(base.len(), 16);
        assert_eq!(ModelList::stamp_of(&[other.clone(), one.clone()]), base);
        assert_eq!(
            ModelList::stamp_of(&[one.clone(), other.clone(), json!("junk"), Value::Null]),
            base,
            "what is no row does not touch it"
        );
        assert_ne!(ModelList::stamp_of(std::slice::from_ref(&one)), base, "a file gone");
        assert_ne!(ModelList::stamp_of(&[one, other.clone(), row("x.gguf", "model", 50, 1_700_000_001)]), base, "a file come");
        assert_ne!(ModelList::stamp_of(&[]), base);
    }

    #[test]
    fn a_stamp_moves_with_each_fact_of_a_file_and_each_to_a_stamp_of_its_own() {
        let other = row("e.gguf", "model", 50, 1_700_000_001);
        let stamp = |changed: Value| ModelList::stamp_of(&[changed, other.clone()]);
        let base = stamp(row("q4.gguf", "model", 4000, 1_700_000_000));
        let moved = [
            stamp(row("q8.gguf", "model", 4000, 1_700_000_000)),
            stamp(row("q4.gguf", "mmproj", 4000, 1_700_000_000)),
            stamp(row("q4.gguf", "model", 4001, 1_700_000_000)),
            stamp(row("q4.gguf", "model", 4000, 1_700_000_009)),
            stamp(json!({"path": "q4.gguf", "kind": "model", "size": 4000, "mtime": 1_700_000_000, "libraryOnly": true})),
        ];
        let distinct: std::collections::BTreeSet<&String> = moved.iter().collect();
        assert_eq!(distinct.len(), moved.len());
        assert!(!moved.contains(&base));
    }

    fn stand(name: &str) -> (TestFolder, Arc<HandClock>, Arc<App>) {
        let folder = TestFolder::new(&format!("model-list-{name}"));
        let clock = HandClock::at(1000);
        let app = TestApp::with_clock(&folder.path, &[], clock.clone());
        (folder, clock, app)
    }

    fn put(app: &App, rel: &str) {
        let path = app.models_dir().join(rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, b"x").unwrap();
    }

    fn paths(rows: &[Value]) -> Vec<&str> {
        rows.iter().map(|row| row["path"].as_str().unwrap()).collect()
    }

    #[test]
    fn a_list_is_kept_for_its_five_seconds_and_a_new_model_then_moves_the_stamp() {
        let (_folder, clock, app) = stand("ttl");
        put(&app, "A/x/q/a.gguf");
        let list = ModelList::of(&app);
        let (first, stamp) = list.current();
        assert_eq!(stamp, ModelList::stamp_of(&first), "the rows and the stamp of one and the same walk");
        put(&app, "B/x/q/b.gguf");
        clock.pass(4);
        assert!(Arc::ptr_eq(&list.rows(), &first), "every open board asks for the stamp, and the folder is not walked for it");
        clock.pass(1);
        let (again, moved) = list.current();
        assert_eq!(paths(&again), ["A/x/q/a.gguf", "B/x/q/b.gguf"]);
        assert_ne!(moved, stamp);
    }

    #[test]
    fn a_stale_list_being_made_anew_is_handed_out_at_once_and_no_second_walk_starts() {
        let (_folder, clock, app) = stand("walking");
        put(&app, "A/x/q/a.gguf");
        let list = ModelList::of(&app);
        let first = list.rows();
        put(&app, "B/x/q/b.gguf");
        clock.pass(6);
        {
            let _walking = app.model_list.walking.lock().unwrap();
            assert!(Arc::ptr_eq(&list.rows(), &first), "a walk is under way: the last list answers");
        }
        assert_eq!(paths(&list.rows()).len(), 2, "the walk over, the next caller makes the new list");
    }

    #[test]
    fn callers_before_the_first_list_wait_for_one_walk_and_all_get_its_list() {
        let (_folder, _clock, app) = stand("first-walk");
        put(&app, "A/x/q/a.gguf");
        let callers: Vec<_> = (0..8)
            .map(|_| {
                let app = Arc::clone(&app);
                std::thread::spawn(move || ModelList::of(&app).rows())
            })
            .collect();
        let lists: Vec<Arc<Vec<Value>>> = callers.into_iter().map(|caller| caller.join().unwrap()).collect();
        assert!(lists.iter().all(|list| Arc::ptr_eq(list, &lists[0])), "a dozen pages that open together walk the folder once");
        assert_eq!(paths(&lists[0]), ["A/x/q/a.gguf"]);
    }

    #[test]
    fn a_walk_that_took_longer_than_the_time_a_list_is_kept_is_as_old_as_its_end() {
        let (_folder, clock, app) = stand("slow");
        put(&app, "A/x/q/a.gguf");
        let list = ModelList::of(&app);
        // Every look at the clock takes three seconds: the walk is long, and the list is stamped at its end.
        clock.each_look_takes(3);
        let first = list.rows();
        clock.each_look_takes(0);
        assert!(Arc::ptr_eq(&list.rows(), &first), "no walk follows at once");
    }

    #[test]
    fn a_stamp_is_what_python_writes_of_the_same_list() {
        let rows = [
            json!({"path": "b", "kind": "model", "size": 2, "mtime": 3}),
            json!({"path": "a", "kind": "draft", "size": 1, "mtime": 0, "libraryOnly": true}),
            json!(5),
        ];
        assert_eq!(ModelList::stamp_of(&rows), "dcf80c6d81c14c3d");
    }
}
