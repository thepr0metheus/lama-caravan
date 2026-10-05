"""OAuth2 (PKCE) login flows for cloud accounts: session state machine, local
callback listener and token refresh."""
import base64
import hashlib
import json
import secrets as secrets_mod
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from caravan.admin.cloud import (
    account_secret_entry,
    load_cloud_data,
    load_provider_secrets,
    save_provider_secrets,
)
from caravan.common.errors import AppError
from caravan.common.credential_vault import CredentialVault
from caravan.admin.paths import PROVIDER_SECRETS_FILE


_oauth_sessions = {}

_oauth_lock = threading.Lock()

def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _pkce_pair():
    verifier = _b64url(secrets_mod.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge

def _decode_jwt_email(id_token):
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return str(data.get("email") or data.get("preferred_username") or "")
    except Exception:
        return ""

def _exchange_oauth_code(account, code, verifier, redirect_uri):
    cfg = account.get("oauthConfig") or {}
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.get("clientId") or "",
        "code_verifier": verifier,
    }).encode("ascii")
    req = urllib.request.Request(cfg.get("tokenUrl") or "", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))

def _store_oauth_tokens(account_id, tokens):
    now = int(time.time())
    oauth = {
        "accessToken": tokens.get("access_token") or "",
        "refreshToken": tokens.get("refresh_token") or "",
        "tokenType": tokens.get("token_type") or "Bearer",
        "scope": tokens.get("scope") or "",
        "expiresAt": now + int(tokens.get("expires_in") or 0) if tokens.get("expires_in") else 0,
        "obtainedAt": now,
        "email": _decode_jwt_email(tokens.get("id_token") or ""),
    }
    CredentialVault(PROVIDER_SECRETS_FILE).put_oauth(account_id, oauth)
    return oauth

def refresh_oauth_token(account):
    """Renew through the same per-account lock the data plane uses."""
    try:
        oauth = CredentialVault(PROVIDER_SECRETS_FILE).oauth(
            account.get("credentialAccountId") or account["id"], account.get("oauthConfig") or {})
        return {"ok": True, "oauth": oauth} if oauth else None
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

class OAuthLoginDesk:
    """One completion path for loopback callbacks and a pasted remote callback."""
    @staticmethod
    def stop_listener(server):
        server.shutdown()
        server.server_close()

    @staticmethod
    def complete(state, code, error=""):
        with _oauth_lock:
            session = _oauth_sessions.get(state)
            if not session or time.time() - session["startedAt"] > 300:
                raise AppError("OAuth session expired or unknown", 400)
            result = session["result"]
            if result.get("state") == "done":
                return dict(result)
            if result.get("state") != "pending" or session.get("completing"):
                raise AppError("OAuth session is no longer pending", 409)
            if not code and not error:
                raise AppError("OAuth callback has no code", 400)
            session["completing"] = True
        try:
            if error:
                raise AppError("OpenAI login was declined", 400)
            details = session["server"].oauth_session
            account = next((a for a in load_cloud_data()["accounts"] if a["id"] == session["accountId"]), None)
            if not account:
                raise AppError("the subscription was removed during login", 404)
            tokens = _exchange_oauth_code(account, code, details["verifier"], details["redirectUri"])
            if not isinstance(tokens, dict) or not tokens.get("access_token"):
                raise AppError("the provider returned no login token", 502)
            oauth = _store_oauth_tokens(account["id"], tokens)
            from caravan.admin.cloud_pools import CloudPoolDesk
            pools = CloudPoolDesk().complete_login(account["id"])
            from caravan.admin import model_catalog
            from caravan.admin.cloud_api import refresh_account_models_cache
            for pool_id in pools:
                model_catalog.kick_refresh(pool_id, lambda pid=pool_id: refresh_account_models_cache(pid))
            result = {"state": "done", "email": oauth.get("email", "")}
        except Exception:
            # Provider errors can contain the code; keep the browser response free of it.
            result = {"state": "error", "error": "OAuth completion failed; start login again"}
        with _oauth_lock:
            session["result"] = result
            session["completing"] = False
        threading.Thread(target=OAuthLoginDesk.stop_listener, args=(session["server"],), daemon=True).start()
        return result

    @classmethod
    def paste_callback(cls, expected_state, callback_url):
        if not isinstance(expected_state, str) or not expected_state:
            raise AppError("a pending OAuth state is required", 400)
        if not isinstance(callback_url, str) or len(callback_url) > 8192:
            raise AppError("invalid callback URL", 400)
        try:
            parsed = urlparse(callback_url)
            with _oauth_lock:
                session = _oauth_sessions.get(expected_state)
                redirect = urlparse(session["server"].oauth_session["redirectUri"]) if session else None
            if not redirect or (parsed.scheme, parsed.netloc, parsed.path) != (redirect.scheme, redirect.netloc, redirect.path) or parsed.fragment:
                raise ValueError()
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state") != [expected_state] or len(params.get("code", [])) > 1:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise AppError("callback must match this login's localhost URL and state", 400)
        return cls.complete(expected_state, (params.get("code") or [""])[0], (params.get("error") or [""])[0])

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        session = getattr(self.server, "oauth_session", {})
        if parsed.path != session.get("redirectPath"):
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query or "")
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]
        err = (params.get("error") or [""])[0]
        body_ok = b"<html><body style='font-family:sans-serif;background:#0b1014;color:#9ff3e6'><h2>Authorized. You can close this window and return to Llama.cpp Easy Admin.</h2></body></html>"
        body_err = b"<html><body style='font-family:sans-serif;background:#0b1014;color:#fecaca'><h2>Authorization failed. Close this window and try again.</h2></body></html>"
        try:
            if state != session.get("state"):
                raise AppError("state mismatch", 400)
            result = OAuthLoginDesk.complete(state, code, err)
        except AppError:
            result = {"state": "error"}
        self.send_response(200 if result["state"] == "done" else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body_ok if result["state"] == "done" else body_err)

def start_oauth_login(account_id):
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if account and account.get("testAliasOf"):
        raise AppError("a test alias uses its original account login", 400)
    if not account:
        raise AppError("unknown account", 404)
    if account.get("authMode") != "oauth":
        raise AppError("account authMode is not oauth", 400)
    cfg = account.get("oauthConfig") or {}
    if not cfg.get("authorizeUrl") or not cfg.get("tokenUrl") or not cfg.get("clientId"):
        raise AppError("account oauthConfig incomplete (authorizeUrl/tokenUrl/clientId)", 400)
    verifier, challenge = _pkce_pair()
    state = _b64url(secrets_mod.token_bytes(16))
    port = int(cfg.get("redirectPort") or 1455)
    path = cfg.get("redirectPath") or "/auth/callback"
    redirect_uri = f"http://localhost:{port}{path}"
    with _oauth_lock:
        old_sessions = [_oauth_sessions.pop(key) for key, sess in list(_oauth_sessions.items())
                        if sess.get("accountId") == account_id and not sess.get("completing")]
    for old in old_sessions:
        OAuthLoginDesk.stop_listener(old["server"])
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)
    except OSError as exc:
        raise AppError(f"cannot bind loopback {port}: {exc} (close other login attempts)", 500)
    server.oauth_session = {"state": state, "accountId": account_id, "verifier": verifier,
                            "redirectUri": redirect_uri, "redirectPath": path}
    with _oauth_lock:
        _oauth_sessions[state] = {"accountId": account_id, "server": server, "result": {"state": "pending"},
                                  "startedAt": int(time.time())}
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def _watchdog():
        time.sleep(300)
        with _oauth_lock:
            sess = _oauth_sessions.get(state)
            if sess and sess["result"].get("state") == "pending" and not sess.get("completing"):
                sess["result"] = {"state": "error", "error": "timeout"}
                try:
                    threading.Thread(target=OAuthLoginDesk.stop_listener, args=(sess["server"],), daemon=True).start()
                except Exception:
                    pass
    threading.Thread(target=_watchdog, daemon=True).start()

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": cfg["clientId"],
        "redirect_uri": redirect_uri,
        "scope": cfg.get("scope") or "",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"authorizeUrl": f"{cfg['authorizeUrl']}?{params}", "state": state, "redirectUri": redirect_uri}

def oauth_login_status(state):
    with _oauth_lock:
        sess = _oauth_sessions.get(str(state or ""))
        if not sess:
            return {"state": "unknown"}
        return dict(sess["result"])
