"""Cloud provider/account credential resolution for proxied requests,
including on-the-fly OAuth refresh."""
import json
import os
import time

from caravan.common.fsio import atomic_write_text
from caravan.proxy.paths import CLOUD_PROVIDERS_FILE, PROVIDER_SECRETS_FILE
from caravan.proxy.runtime import config_lock


CLOUD_PROVIDER_AUTH = {
    "openai": {"authHeader": "Authorization", "authPrefix": "Bearer ", "extraHeaders": {}},
    "anthropic": {"authHeader": "x-api-key", "authPrefix": "", "extraHeaders": {"anthropic-version": "2023-06-01"}},
    "openrouter": {"authHeader": "Authorization", "authPrefix": "Bearer ", "extraHeaders": {}},
    "custom": {"authHeader": "Authorization", "authPrefix": "Bearer ", "extraHeaders": {}},
}

def _read_cloud_data():
    if not CLOUD_PROVIDERS_FILE.exists():
        return {"accounts": [], "blocks": []}
    try:
        parsed = json.loads(CLOUD_PROVIDERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts": [], "blocks": []}
    if isinstance(parsed, dict) and ("accounts" in parsed or "blocks" in parsed):
        return {
            "accounts": parsed.get("accounts") if isinstance(parsed.get("accounts"), list) else [],
            "blocks": parsed.get("blocks") if isinstance(parsed.get("blocks"), list) else [],
        }
    return {"accounts": [], "blocks": []}

def load_cloud_provider(block_id):
    """Resolve a proxy route's providerId (a model-block id) to an effective
    provider dict combining the block (model/modelMode) and its account
    (type/baseUrl/authMode)."""
    block_id = str(block_id or "").strip()
    if not block_id:
        return None
    data = _read_cloud_data()
    block = next((b for b in data["blocks"] if isinstance(b, dict) and b.get("id") == block_id), None)
    if not block:
        return None
    account = next((a for a in data["accounts"] if isinstance(a, dict) and a.get("id") == block.get("accountId")), None)
    if not account:
        return None
    return {
        "id": block_id,
        "accountId": account.get("id"),
        "type": account.get("type") or "openai",
        "baseUrl": account.get("baseUrl") or "",
        "authMode": account.get("authMode") or "apiKey",
        "oauthConfig": account.get("oauthConfig") if isinstance(account.get("oauthConfig"), dict) else {},
        "model": block.get("model") or "",
        "modelMode": block.get("modelMode") or "rewrite",
    }

def load_cloud_account(account_id):
    """Resolve a router cloud output that targets an ACCOUNT directly (no block):
    same provider shape as load_cloud_provider but with model passthrough (the client's
    requested model is forwarded unchanged)."""
    account_id = str(account_id or "").strip()
    if not account_id:
        return None
    data = _read_cloud_data()
    account = next((a for a in data["accounts"] if isinstance(a, dict) and a.get("id") == account_id), None)
    if not account:
        return None
    return {
        "id": account_id,
        "accountId": account_id,
        "type": account.get("type") or "openai",
        "accountType": account.get("accountType") or "",
        "baseUrl": account.get("baseUrl") or "",
        "authMode": account.get("authMode") or "apiKey",
        "oauthConfig": account.get("oauthConfig") if isinstance(account.get("oauthConfig"), dict) else {},
        "model": "",
        "modelMode": "passthrough",
    }

def _write_provider_secrets(secrets):
    try:
        atomic_write_text(PROVIDER_SECRETS_FILE, json.dumps(secrets, ensure_ascii=False, indent=2) + "\n",
                          chmod=0o600, mkdir=True)
    except Exception:
        pass

def _refresh_oauth(provider, entry):
    oauth = entry.get("oauth") or {}
    cfg = provider.get("oauthConfig") or {}
    if not oauth.get("refreshToken") or not cfg.get("tokenUrl"):
        return oauth.get("accessToken")
    import urllib.request as _u
    import urllib.parse as _up
    data = _up.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": oauth["refreshToken"],
        "client_id": cfg.get("clientId") or "",
    }).encode("ascii")
    req = _u.Request(cfg["tokenUrl"], data=data,
                     headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with _u.urlopen(req, timeout=15) as response:
            tokens = json.loads(response.read().decode("utf-8"))
    except Exception:
        return oauth.get("accessToken")
    now = int(time.time())
    oauth["accessToken"] = tokens.get("access_token") or oauth.get("accessToken")
    if tokens.get("refresh_token"):
        oauth["refreshToken"] = tokens["refresh_token"]
    if tokens.get("expires_in"):
        oauth["expiresAt"] = now + int(tokens["expires_in"])
    oauth["obtainedAt"] = now
    entry["oauth"] = oauth
    with config_lock:
        try:
            parsed = json.loads(PROVIDER_SECRETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            parsed[provider.get("accountId")] = entry
            _write_provider_secrets(parsed)
    return oauth.get("accessToken")

def load_provider_secret(provider):
    """Return the auth header tuple (header_name, header_value) for an effective
    provider dict, or None if no usable credential."""
    account_id = str((provider or {}).get("accountId") or "").strip()
    if not account_id or not PROVIDER_SECRETS_FILE.exists():
        return None
    try:
        parsed = json.loads(PROVIDER_SECRETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    entry = parsed.get(account_id) if isinstance(parsed, dict) else None
    if isinstance(entry, str):
        entry = {"apiKey": entry}
    if not isinstance(entry, dict):
        return None
    auth = CLOUD_PROVIDER_AUTH.get(provider.get("type"), CLOUD_PROVIDER_AUTH["custom"])
    if provider.get("authMode") == "oauth":
        oauth = entry.get("oauth") or {}
        token = oauth.get("accessToken")
        expires_at = int(oauth.get("expiresAt") or 0)
        if token and expires_at and expires_at - int(time.time()) < 60:
            token = _refresh_oauth(provider, entry) or token
        if token:
            return ("Authorization", f"Bearer {token}")
        return None
    key = entry.get("apiKey")
    if key:
        return (auth["authHeader"], f"{auth['authPrefix']}{key}")
    return None
