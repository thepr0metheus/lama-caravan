//! Accounts, sessions and the fleet token: the pages and the routes.

use crate::app::App;
use crate::store::auth::AuthStore;
use crate::web::{Exchange, Routes};
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The routes.
pub struct AuthRoutes;

impl AuthRoutes {
    const SHELL: &'static str = include_str!("../web/page_shell.html");
    const SIGN_IN: &'static str = include_str!("../web/sign_in_form.html");
    const FIRST_RUN: &'static str = include_str!("../web/first_run_form.html");

    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/login", Self::login),
            ("/setup", Self::setup),
            ("/api/auth/me", Self::me),
            ("/api/auth/overview", Self::overview),
        ],
        post: &[
            ("/api/auth/login", Self::sign_in),
            ("/api/auth/setup", Self::first_account),
            ("/api/auth/logout", Self::logout),
            ("/api/auth/users", Self::users),
            ("/api/auth/sessions/revoke", Self::revoke),
            ("/api/auth/fleet-token", Self::fleet_token),
        ],
        delete: &[],
    };

    /// /login: the sign-in form, and nothing else.
    fn login_page() -> String {
        Self::SHELL.replace("<!--FORM-->", Self::SIGN_IN).replace("<!--PAGE-->", "login")
    }

    /// /setup: the first-run page.
    fn setup_page() -> String {
        Self::SHELL
            .replace("<!--FORM-->", Self::FIRST_RUN)
            .replace("<!--PAGE-->", "setup")
            .replace(
                "<p class=\"sub\" data-i18n=\"sub\">Sign in to the fleet controller</p>",
                "<p class=\"sub\" data-i18n=\"subSetup\">Create the first account</p>",
            )
            .replace("<title>LAMA CARAVAN — sign in</title>", "<title>LAMA CARAVAN — first run</title>")
    }

    fn login(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        if !app.auth.enabled()? {
            h.redirect("/setup");
            return Ok(());
        }
        h.send_text(200, "text/html; charset=utf-8", &Self::login_page(), "no-cache");
        Ok(())
    }

    fn setup(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        if app.auth.enabled()? {
            h.redirect("/login");
            return Ok(());
        }
        h.send_text(200, "text/html; charset=utf-8", &Self::setup_page(), "no-cache");
        Ok(())
    }

    fn who(app: &App, h: &Exchange<'_>) -> Result<(String, String, bool), AppError> {
        let session = app.session_of(h)?;
        Ok(session.map_or((String::new(), String::new(), false), |session| (session.user, session.role, true)))
    }

    fn me(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let (user, role, signed_in) = Self::who(app, h)?;
        h.ok(&json!({"enabled": app.auth.enabled()?, "authenticated": signed_in, "user": user, "role": role}));
        Ok(())
    }

    fn word(body: &Value, key: &str) -> String {
        if Coerce::truthy(body.get(key)) { Coerce::text(body.get(key)) } else { String::new() }
    }

    /// A session for an account just proved, and the cookie that says it.
    fn answer_session(app: &App, h: &mut Exchange<'_>, id: i64, name: &str) -> Result<(), AppError> {
        let ua = h.field_or_empty("User-Agent");
        let token = app.auth.create_session(id, &h.client_address(), &ua, app.now_whole())?;
        h.send_json_with(&json!({"ok": true, "user": name}), "Set-Cookie", AuthStore::cookie_header(&token, false));
        Ok(())
    }

    fn sign_in(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let (id, name) = app.auth.verify_login(
            &Self::word(&body, "username"),
            &Self::word(&body, "password"),
            &h.client_address(),
            app.now(),
        )?;
        Self::answer_session(app, h, id, &name)
    }

    fn first_account(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        if app.auth.enabled()? {
            return Err(AppError::with_status("auth is already enabled", 409));
        }
        let password = Self::word(&body, "password");
        let user = app.auth.create_user(&Self::word(&body, "username"), &password, "", app.now_whole())?;
        app.auth.fleet_token_ensure()?;
        let (id, name) = app.auth.verify_login(&Coerce::text(user.get("username")), &password, &h.client_address(), app.now())?;
        Self::answer_session(app, h, id, &name)
    }

    fn logout(app: &App, h: &mut Exchange<'_>, _body: Value) -> Result<(), AppError> {
        let token = h.cookie(AuthStore::SESSION_COOKIE);
        // Always answered: a session that is gone already has nothing to end.
        drop(app.auth.delete_session(&token));
        h.send_json_with(&json!({"ok": true}), "Set-Cookie", AuthStore::cookie_header("", true));
        Ok(())
    }

    fn overview(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let (user, role, _) = Self::who(app, h)?;
        h.ok(&json!({"enabled": app.auth.enabled()?, "user": user, "role": role, "users": app.auth.list_users()?, "sessions": app.auth.list_sessions(app.now_whole())?, "fleetTokenSet": !app.auth.fleet_token()?.is_empty()}));
        Ok(())
    }

    fn users(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let action = if Coerce::truthy(body.get("action")) { Coerce::text(body.get("action")) } else { "create".to_string() };
        let (name, password) = (Self::word(&body, "username"), Self::word(&body, "password"));
        match action.as_str() {
            "create" => {
                let role = if Coerce::truthy(body.get("role")) { Coerce::text(body.get("role")) } else { "admin".to_string() };
                let made = app.auth.create_user(&name, &password, &role, app.now_whole())?;
                h.ok(&json!({"ok": true, "username": made.get("username"), "role": made.get("role")}));
            }
            "set-role" => {
                app.auth.set_role(&name, &Self::word(&body, "role"))?;
                h.ok(&json!({"ok": true}));
            }
            "delete" => {
                app.auth.delete_user(&name)?;
                h.ok(&json!({"ok": true}));
            }
            "set-password" => {
                app.auth.set_password(&name, &password)?;
                h.ok(&json!({"ok": true}));
            }
            _ => return Err(AppError::new("unknown action")),
        }
        Ok(())
    }

    fn revoke(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        if Coerce::truthy(body.get("others")) {
            let token = h.cookie(AuthStore::SESSION_COOKIE);
            h.ok(&json!({"ok": true, "revoked": app.auth.revoke_other_sessions(&token)?}));
            return Ok(());
        }
        app.auth.revoke_session(&Self::word(&body, "id"))?;
        h.ok(&json!({"ok": true}));
        Ok(())
    }

    fn fleet_token(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let token = if Coerce::truthy(body.get("regenerate")) {
            app.auth.fleet_token_regenerate()?
        } else {
            app.auth.fleet_token_ensure()?
        };
        h.ok(&json!({"ok": true, "fleetToken": token}));
        Ok(())
    }
}
