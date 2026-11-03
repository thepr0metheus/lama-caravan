//! The models page's routes.

use crate::app::App;
use crate::models::checkpoints::ModelCheckpoints;
use crate::models::folder::ModelFolder;
use crate::models::gc::ModelGc;
use crate::models::model_list::ModelList;
use crate::models::moves::runner::MoveRunner;
use crate::models::notes::{ModelFields, ModelRatings};
use crate::models::staging::ModelStaging;
use crate::models::stores::{StoreRefused, StoreRegistry};
use crate::models::watch::ModelWatch;
use crate::store::topology::Topology;
use crate::web::{Exchange, Routes};
use os::Disk;
use rules::{AppError, Coerce, Flag};
use serde_json::{Map, Value, json};

/// The routes.
pub struct ModelRoutes;

impl ModelRoutes {
    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/api/models", Self::list),
            ("/api/models/rows", Self::rows),
            ("/api/models/freshness", Self::freshness),
            ("/api/models/download", Self::download),
            ("/api/models/folder", Self::folder),
            ("/api/models/disk", Self::disk),
            ("/api/models/unused", Self::unused),
            ("/api/model-notes", Self::notes),
            ("/api/model-stores", Self::stores),
            ("/api/model-stores/moves", Self::moves),
            ("/api/model-stores/files", Self::store_files),
        ],
        post: &[
            ("/api/model-notes", Self::set_note),
            ("/api/model-rating", Self::set_rating),
            ("/api/models/freshness/check", Self::check_now),
            ("/api/models/staged/download", Self::staged_download),
            ("/api/models/staged/revert", Self::staged_revert),
            ("/api/models/staged/drop-prev", Self::staged_drop_prev),
            ("/api/models/freshness/watch", Self::set_watch),
            ("/api/model-stores/add", Self::store_add),
            ("/api/model-stores/repath", Self::store_repath),
            ("/api/model-stores/remove", Self::store_remove),
            ("/api/model-stores/move", Self::store_move),
            ("/api/model-stores/moves/cancel", Self::store_move_cancel),
            ("/api/models/gc", Self::gc),
        ],
        delete: &[],
    };

    fn list(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&ModelCheckpoints::of(app).gguf_models());
        Ok(())
    }

    fn rows(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let (rows, stamp) = ModelList::of(app).current();
        h.ok(&json!({"ok": true, "models": rows.as_slice(), "stamp": stamp}));
        Ok(())
    }

    fn freshness(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let watch = ModelWatch::of(app);
        let mut out = Map::new();
        out.insert("ok".to_string(), json!(true));
        out.extend(Coerce::fields(&watch.report()));
        out.insert("watch".to_string(), watch.settings());
        out.insert("prev".to_string(), ModelStaging::of(app).prev_overview());
        h.ok(&Value::Object(out));
        Ok(())
    }

    fn download(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        ModelCheckpoints::of(app).serve_file(h)
    }

    fn folder(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let rel = h.parsed.param_or("path", "");
        h.ok(&ModelFolder::new(&app.models_dir(), &rel).listing()?);
        Ok(())
    }

    /// Cheap disk headroom for the models folder: the /hf page's badge and the check before a download.
    fn disk(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let dir = app.models_dir();
        let gib = |bytes: u64| Coerce::rounded(bytes as f64 / 1_073_741_824.0, 1);
        match Disk::usage(&dir) {
            Some((total, free)) => h.ok(&json!({"ok": true, "path": dir.to_string_lossy(), "totalGb": gib(total), "freeGb": gib(free)})),
            None => h.ok(&json!({"ok": false, "path": dir.to_string_lossy(), "error": format!("[Errno 2] No such file or directory: '{}'", dir.display())})),
        }
        Ok(())
    }

    fn unused(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&ModelGc::of(app).list_unused());
        Ok(())
    }

    fn notes(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let answer = app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let mut out = Map::new();
            out.insert("ok".to_string(), json!(true));
            out.extend(Coerce::fields(&ModelFields::answer(&mut topology)));
            out.insert("limit".to_string(), json!(1000));
            out.insert("root".to_string(), json!("(root)"));
            out.insert("ratings".to_string(), Value::Object(ModelRatings::new(topology.model_ratings()).all()));
            out
        });
        h.ok(&Value::Object(answer));
        Ok(())
    }

    fn set_note(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let model = Coerce::stripped(body.get("model"));
        let field = body.get("field").cloned().unwrap_or_else(|| json!("note"));
        let text = Coerce::text(body.get("note"));
        let note = app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let mut notes = ModelFields::of(&mut topology, &Coerce::str_of(Some(&field)))?;
            notes.set(&model, &text)
        })?;
        app.save_admin();
        h.ok(&json!({"ok": true, "model": model, "field": field, "note": note}));
        Ok(())
    }

    fn set_rating(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let model = Coerce::stripped(body.get("model"));
        let (rating, all) = app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let mut ratings = ModelRatings::new(topology.model_ratings());
            let rating = ratings.set(&model, body.get("rating"))?;
            Ok::<_, AppError>((rating, ratings.all()))
        })?;
        app.save_admin();
        h.ok(&json!({"ok": true, "model": model, "rating": rating, "ratings": all}));
        Ok(())
    }

    fn stores(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let force = h.parsed.flag("force", false);
        h.ok(&json!({"ok": true, "stores": StoreRegistry::of(app).statuses(force)}));
        Ok(())
    }

    fn moves(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&json!({"ok": true, "jobs": MoveRunner::of(app).summaries()}));
        Ok(())
    }

    fn store_files(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let force = h.parsed.flag("force", false);
        h.ok(&json!({"ok": true, "libraries": StoreRegistry::of(app).library_files(force, true)}));
        Ok(())
    }

    fn check_now(app: &App, h: &mut Exchange<'_>, _body: Value) -> Result<(), AppError> {
        let watch = ModelWatch::of(app);
        let mut out = Map::new();
        out.insert("ok".to_string(), json!(true));
        out.extend(Coerce::fields(&watch.check_pass(true)));
        out.extend(Coerce::fields(&watch.report()));
        h.ok(&Value::Object(out));
        Ok(())
    }

    /// A refusal of these routes is an answer of 200 that says so.
    fn or_said(h: &mut Exchange<'_>, answer: Result<Value, AppError>) -> Result<(), AppError> {
        match answer {
            Ok(said) => h.ok(&said),
            Err(error) => h.ok(&json!({"ok": false, "error": error.message})),
        }
        Ok(())
    }

    fn staged_download(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        Self::or_said(h, ModelStaging::of(app).start_update(&Coerce::text(body.get("file"))))
    }

    fn staged_revert(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let staging = ModelStaging::of(app);
        Self::or_said(
            h,
            staging.live_path_for(&Coerce::text(body.get("file"))).and_then(|live| ModelStaging::restore_prev(&live)),
        )
    }

    fn staged_drop_prev(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let staging = ModelStaging::of(app);
        Self::or_said(h, staging.live_path_for(&Coerce::text(body.get("file"))).and_then(|live| ModelStaging::drop_prev(&live)))
    }

    fn set_watch(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&json!({"ok": true, "watch": ModelWatch::of(app).set_settings(&body)}));
        Ok(())
    }

    fn or_refused(h: &mut Exchange<'_>, answer: Result<Value, StoreRefused>) -> Result<(), AppError> {
        match answer {
            Ok(said) => h.ok(&said),
            Err(refused) => h.ok(&json!({"ok": false, "error": refused.error.message, "code": refused.code})),
        }
        Ok(())
    }

    fn with_ok(said: Value) -> Value {
        let mut out = Map::new();
        out.insert("ok".to_string(), json!(true));
        out.extend(Coerce::fields(&said));
        Value::Object(out)
    }

    fn store_add(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let answer = StoreRegistry::of(app).add(
            &Coerce::text(body.get("path")),
            &Coerce::text(body.get("name")),
            Flag::yes(body.get("force")),
        );
        Self::or_refused(h, answer.map(|store| json!({"ok": true, "store": store})))
    }

    fn store_repath(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let answer = StoreRegistry::of(app).repath(&Coerce::text(body.get("id")), &Coerce::text(body.get("path")));
        Self::or_refused(h, answer.map(Self::with_ok))
    }

    fn store_remove(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        Self::or_refused(h, StoreRegistry::of(app).remove(&Coerce::text(body.get("id"))).map(Self::with_ok))
    }

    fn store_move(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let files = body.get("files").and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let from = Coerce::text(body.get("from"));
        let answer =
            MoveRunner::of(app).start(files, &Coerce::text(body.get("to")), (!from.is_empty()).then_some(from.as_str()), None);
        Self::or_refused(h, answer.map(|job| json!({"ok": true, "job": job})))
    }

    fn store_move_cancel(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let answer = MoveRunner::of(app).cancel(&super::asked::Asked::said(&body, "id"));
        Self::or_refused(h, answer.map(|job| json!({"ok": true, "job": job})))
    }

    fn gc(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelGc::of(app).delete(&body)?);
        Ok(())
    }
}
