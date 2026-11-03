//! The board: what stands on it and who is wired to what.

use super::asked::Asked;
use crate::app::App;
use crate::board_layout::{ClientOrder, ServerOrder};
use crate::fleet::clients::ClientDesk;
use crate::topology::TopologyState;
use crate::topology::assignments::Assignments;
use crate::web::{Exchange, Routes};
use rules::AppError;
use serde_json::{Value, json};

/// The routes.
pub struct TopologyRoutes;

impl TopologyRoutes {
    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[("/api/topology", Self::topology)],
        post: &[
            ("/api/topology/assignments", Self::assignments),
            ("/api/topology/agent-proxy-bind", Self::bind),
            ("/api/topology/client-alias", Self::client_alias),
            ("/api/topology/server-order", Self::server_order),
            ("/api/consumers/order", Self::client_order),
            ("/api/topology/agent-route/context", Self::route_context),
            ("/api/topology/agent-route/remove", Self::route_remove),
            ("/api/topology/agent-route/model", Self::route_model),
        ],
        delete: &[],
    };

    fn topology(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&TopologyState::of(app).state(true)?);
        Ok(())
    }

    fn assignments(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let result = Assignments::of(app).apply(&body)?;
        Asked::send_with_fresh_board(app, h, json!({"ok": true, "result": result}))
    }

    fn bind(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let result = Assignments::of(app).bind(&body)?;
        Asked::send_with_fresh_board(app, h, json!({"ok": true, "result": result}))
    }

    fn client_alias(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let result = ClientDesk::of(app).set_alias(body.get("hostId"), body.get("name"))?;
        Asked::send_with_board(app, h, json!({"ok": true, "result": result}))
    }

    fn server_order(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = ServerOrder::save(app, body.get("order"))?;
        Asked::send_with_board(app, h, done)
    }

    fn client_order(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = ClientOrder::save(app, body.get("order"))?;
        Asked::send_with_board(app, h, done)
    }

    fn route_context(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&Assignments::of(app).set_context(&body)?);
        Ok(())
    }

    fn route_remove(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&Assignments::of(app).remove_route(&body)?);
        Ok(())
    }

    fn route_model(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&Assignments::of(app).set_model(&body)?);
        Ok(())
    }
}
