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
    secrets = load_provider_secrets()
    entry = secrets.get(account_id) if isinstance(secrets.get(account_id), dict) else {}
    entry["oauth"] = oauth
    secrets[account_id] = entry
    save_provider_secrets(secrets)
    return oauth

def refresh_oauth_token(account):
    """Refresh and persist the access token using the stored refresh token."""
    account_id = account.get("id")
    entry = account_secret_entry(account_id)
    oauth = entry.get("oauth") if isinstance(entry, dict) else None
    cfg = account.get("oauthConfig") or {}
    if not oauth or not oauth.get("refreshToken") or not cfg.get("tokenUrl"):
        return None
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": oauth["refreshToken"],
        "client_id": cfg.get("clientId") or "",
    }).encode("ascii")
    req = urllib.request.Request(cfg["tokenUrl"], data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            tokens = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not tokens.get("refresh_token"):
        tokens["refresh_token"] = oauth["refreshToken"]
    return {"ok": True, "oauth": _store_oauth_tokens(account_id, tokens)}

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
        result = {"state": "error", "error": err or "no code"}
        if code and state == session.get("state"):
            try:
                account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == session.get("accountId")), None)
                tokens = _exchange_oauth_code(account, code, session.get("verifier"), session.get("redirectUri"))
                oauth = _store_oauth_tokens(session.get("accountId"), tokens)
                result = {"state": "done", "email": oauth.get("email", "")}
            except Exception as exc:
                result = {"state": "error", "error": str(exc)}
        with _oauth_lock:
            sess = _oauth_sessions.get(session.get("state"))
            if sess:
                sess["result"] = result
        self.send_response(200 if result["state"] == "done" else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body_ok if result["state"] == "done" else body_err)
        threading.Thread(target=self.server.shutdown, daemon=True).start()

def start_oauth_login(account_id):
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
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
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)
    except OSError as exc:
        raise AppError(f"cannot bind loopback {port}: {exc} (close other login attempts)", 500)
    server.oauth_session = {"state": state, "accountId": account_id, "verifier": verifier,
                            "redirectUri": redirect_uri, "redirectPath": path}
    with _oauth_lock:
        for old_state, sess in list(_oauth_sessions.items()):
            if sess.get("accountId") == account_id:
                try:
                    sess["server"].shutdown()
                except Exception:
                    pass
                _oauth_sessions.pop(old_state, None)
        _oauth_sessions[state] = {"accountId": account_id, "server": server, "result": {"state": "pending"},
                                  "startedAt": int(time.time())}
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def _watchdog():
        time.sleep(300)
        with _oauth_lock:
            sess = _oauth_sessions.get(state)
            if sess and sess["result"].get("state") == "pending":
                sess["result"] = {"state": "error", "error": "timeout"}
                try:
                    sess["server"].shutdown()
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
