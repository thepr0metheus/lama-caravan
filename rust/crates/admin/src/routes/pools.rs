//! Routing's pools, the providers on the board, the model's clock.

use super::asked::Asked;
use crate::app::App;
use crate::cloud::board_providers::ProviderDesk;
use crate::cloud::data::CloudData;
use crate::cloud::entry_move::EntryMove;
use crate::cloud::pools::PoolDesk;
use crate::cloud::refs::CloudModelRefs;
use crate::cloud::schedules::ModelScheduleDesk;
use crate::proxies::config::ProxiesConfig;
use crate::web::{Exchange, Routes};
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The routes.
pub struct PoolRoutes;

impl PoolRoutes {
    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[("/api/pools/refs", Self::refs)],
        post: &[
            ("/api/models/schedule", Self::model_schedule),
            ("/api/pools/level", Self::level),
            ("/api/pools/model-jobs", Self::model_jobs),
            ("/api/pools/create", Self::create),
            ("/api/pools/copy", Self::copy),
            ("/api/pools/save", Self::save),
            ("/api/pools/add-step", Self::add_step),
            ("/api/pools/add-row", Self::add_row),
            ("/api/pools/order", Self::order),
            ("/api/pools/arrange", Self::arrange),
            ("/api/pools/connect-row", Self::connect_row),
            ("/api/pools/add-model", Self::add_model),
            ("/api/pools/remove-model", Self::remove_model),
            ("/api/pools/remove-step", Self::remove_step),
            ("/api/pools/delete", Self::delete),
            ("/api/board-providers/add", Self::provider_add),
            ("/api/board-providers/remove", Self::provider_remove),
            ("/api/entry-move/seen", Self::move_seen),
        ],
        delete: &[],
    };

    fn refs(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let pool_id = Asked::word(h, "id");
        let config = ProxiesConfig::of(app).load()?;
        let mut refs = CloudModelRefs::new(&config);
        let cloud = CloudData::of(app);
        let routes: &[Value] = config.get("routes").and_then(Value::as_array).map_or(&[], Vec::as_slice);
        let clients = cloud.pool_names(&cloud.load()).callers(routes, &pool_id);
        h.ok(&json!({"ok": true, "refs": refs.of(&pool_id), "held": refs.held(&pool_id), "clients": clients}));
        Ok(())
    }

    fn model_schedule(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let key = body.get("model").cloned().unwrap_or(Value::Null);
        let said = ModelScheduleDesk::of(app).set(&key, body.get("schedule").unwrap_or(&Value::Null))?;
        Asked::send_with_board(app, h, json!({"ok": true, "model": key, "schedule": said}))
    }

    fn level(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let desk = PoolDesk::of(app);
        let (mut account, mut model) = (Coerce::text(body.get("accountId")), body.get("model").cloned());
        if account.is_empty() && Coerce::truthy(body.get("poolId")) {
            let (owner, name) = desk.row_target(&Coerce::text(body.get("poolId")), &Coerce::text(body.get("stepId")))?;
            account = owner;
            model = Some(json!(name));
        }
        let levels = desk.set_level(
            &account,
            model.as_ref(),
            body.get("windowSeconds"),
            body.get("pct"),
            &Coerce::text(body.get("level")),
        )?;
        Asked::send_with_board(app, h, Asked::ok_with(levels))
    }

    fn model_jobs(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let jobs = PoolDesk::of(app).set_jobs(&Coerce::text(body.get("accountId")), body.get("model"), body.get("jobs"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "jobs": jobs}))
    }

    fn create(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let pool = PoolDesk::of(app).create(
            body.get("name"),
            body.get("accountId"),
            body.get("model"),
            body.get("target"),
            body.get("nameAfter"),
        )?;
        Asked::send_with_board(app, h, json!({"ok": true, "pool": pool}))
    }

    fn copy(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let pool = PoolDesk::of(app).copy(&Coerce::text(body.get("id")))?;
        Asked::send_with_board(app, h, json!({"ok": true, "pool": pool}))
    }

    fn save(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let supplied = body.get("pool").filter(|pool| Coerce::truthy(Some(*pool))).cloned().unwrap_or_else(|| json!({}));
        let pool = PoolDesk::of(app).save_pool(&supplied)?;
        Asked::send_with_board(app, h, json!({"ok": true, "pool": pool}))
    }

    fn add_step(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let pool =
            PoolDesk::of(app).add_step(&Asked::said(&body, "poolId"), &Coerce::text(body.get("accountId")), body.get("model"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "pool": pool}))
    }

    fn add_row(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let pool = PoolDesk::of(app).add_row(&Asked::said(&body, "poolId"), body.get("target"), body.get("nameAfter"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "pool": pool}))
    }

    fn order(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let order = PoolDesk::of(app).order(body.get("ids"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "order": order}))
    }

    fn arrange(app: &App, h: &mut Exchange<'_>, _body: Value) -> Result<(), AppError> {
        let order = PoolDesk::of(app).arrange()?;
        Asked::send_with_board(app, h, json!({"ok": true, "order": order}))
    }

    fn connect_row(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let pool = PoolDesk::of(app).connect_row(
            &Asked::said(&body, "poolId"),
            &Coerce::text(body.get("rowId")),
            body.get("target"),
            body.get("nameAfter"),
        )?;
        Asked::send_with_board(app, h, json!({"ok": true, "pool": pool}))
    }

    fn add_model(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let models = PoolDesk::of(app).add_model(&Asked::said(&body, "accountId"), body.get("model"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "models": models}))
    }

    fn remove_model(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let models = PoolDesk::of(app).remove_model(&Asked::said(&body, "accountId"), body.get("model"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "models": models}))
    }

    fn remove_step(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let pool = PoolDesk::of(app).remove_step(&Asked::said(&body, "poolId"), &Asked::said(&body, "stepId"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "pool": pool}))
    }

    fn delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = PoolDesk::of(app).delete(&Coerce::text(body.get("id")), body.get("resolution"))?;
        Asked::send_with_board(app, h, Asked::ok_with(done))
    }

    fn provider_add(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let providers = ProviderDesk::of(app).add(&Coerce::text(body.get("kind")))?;
        Asked::send_with_board(app, h, json!({"ok": true, "providers": providers}))
    }

    fn provider_remove(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let providers = ProviderDesk::of(app).remove(&Coerce::text(body.get("kind")))?;
        Asked::send_with_board(app, h, json!({"ok": true, "providers": providers}))
    }

    fn move_seen(app: &App, h: &mut Exchange<'_>, _body: Value) -> Result<(), AppError> {
        let marked = EntryMove::of(app).seen();
        Asked::send_with_board(app, h, json!({"ok": true, "marked": marked}))
    }
}
