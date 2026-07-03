"""Cloud provider data layer: accounts/blocks (cloud-providers.json) and
credentials (~/.config/llamacpp-easy-admin/provider-secrets.json, 0600).

Pure data — no OAuth flows and no router logic; those live above this layer.
"""
import json
import os
import re

from caravan.admin.paths import CLOUD_PROVIDERS_FILE, PROVIDER_SECRETS_FILE
from caravan.common.errors import AppError
from caravan.common.fsio import atomic_write_text


CLOUD_PROVIDER_PRESETS = {
    "openai-subscription": {
        "name": "OpenAI (ChatGPT Plus subscription)", "baseUrl": "https://chatgpt.com/backend-api",
        "model": "gpt-5.4-mini", "testPath": None,
        "authHeader": "Authorization", "authPrefix": "Bearer ",
        "extraHeaders": {}, "authModes": ["oauth"],
        "accountType": "openai-subscription",
        "oauth": {
            "authorizeUrl": "https://auth.openai.com/oauth/authorize",
            "tokenUrl": "https://auth.openai.com/oauth/token",
            "clientId": "app_EMoamEEZ73f0CkXaXp7hrann",
            "scope": "openid profile email offline_access",
            "redirectPort": 1455,
            "redirectPath": "/auth/callback",
        },
    },
    "openai": {
        "name": "OpenAI (API Credits)", "baseUrl": "https://api.openai.com/v1", "model": "gpt-4o-mini",
        "testPath": "/models", "authHeader": "Authorization", "authPrefix": "Bearer ",
        "extraHeaders": {}, "authModes": ["apiKey", "oauth"],
        "accountType": "openai-api",
        "oauth": {
            "authorizeUrl": "https://auth.openai.com/oauth/authorize",
            "tokenUrl": "https://auth.openai.com/oauth/token",
            "clientId": "app_EMoamEEZ73f0CkXaXp7hrann",
            "scope": "openid profile email offline_access",
            "redirectPort": 1455,
            "redirectPath": "/auth/callback",
        },
    },
    "ollama": {
        "name": "Ollama", "baseUrl": "https://ollama.com/v1", "model": "llama3.3",
        "testPath": "/models", "authHeader": "Authorization", "authPrefix": "Bearer ",
        "extraHeaders": {}, "authModes": ["apiKey"],
    },
    "anthropic": {
        "name": "Anthropic", "baseUrl": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-6",
        "testPath": "/models", "authHeader": "x-api-key", "authPrefix": "",
        "extraHeaders": {"anthropic-version": "2023-06-01"}, "authModes": ["apiKey"],
    },
    "openrouter": {
        "name": "OpenRouter", "baseUrl": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini",
        "testPath": "/models", "authHeader": "Authorization", "authPrefix": "Bearer ",
        "extraHeaders": {}, "authModes": ["apiKey"],
    },
    "custom": {
        "name": "Custom (OpenAI-compatible)", "baseUrl": "", "model": "",
        "testPath": "/models", "authHeader": "Authorization", "authPrefix": "Bearer ",
        "extraHeaders": {}, "authModes": ["apiKey"],
    },
}

def load_cloud_data():
    data = {"accounts": [], "blocks": []}
    if not CLOUD_PROVIDERS_FILE.exists():
        return data
    try:
        parsed = json.loads(CLOUD_PROVIDERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return data
    if isinstance(parsed, dict) and ("accounts" in parsed or "blocks" in parsed):
        accounts = parsed.get("accounts") if isinstance(parsed.get("accounts"), list) else []
        blocks = parsed.get("blocks") if isinstance(parsed.get("blocks"), list) else []
        data["accounts"] = [a for a in accounts if isinstance(a, dict) and a.get("id")]
        data["blocks"] = [b for b in blocks if isinstance(b, dict) and b.get("id")]
        return data
    # legacy flat {"providers":[...]} (or bare list) → migrate to account+block pairs
    legacy = parsed.get("providers") if isinstance(parsed, dict) else parsed
    if isinstance(legacy, list):
        for p in legacy:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            acct_id = f"{p['id']}-acct"
            data["accounts"].append({
                "id": acct_id, "type": p.get("type") or "openai", "name": p.get("name") or p["id"],
                "baseUrl": p.get("baseUrl") or "", "authMode": "apiKey",
            })
            data["blocks"].append({
                "id": p["id"], "accountId": acct_id, "name": p.get("name") or p["id"],
                "model": p.get("model") or "", "modelMode": p.get("modelMode") or "rewrite",
            })
    return data

def save_cloud_data(data):
    payload = {"accounts": data.get("accounts", []), "blocks": data.get("blocks", [])}
    atomic_write_text(CLOUD_PROVIDERS_FILE, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

def load_provider_secrets():
    if PROVIDER_SECRETS_FILE.exists():
        try:
            parsed = json.loads(PROVIDER_SECRETS_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}

def save_provider_secrets(secrets):
    atomic_write_text(PROVIDER_SECRETS_FILE, json.dumps(secrets, ensure_ascii=False, indent=2) + "\n",
                      chmod=0o600, mkdir=True)
    try:
        os.chmod(PROVIDER_SECRETS_FILE, 0o600)
    except Exception:
        pass

def account_secret_entry(account_id):
    entry = load_provider_secrets().get(str(account_id or ""))
    if isinstance(entry, str):
        return {"apiKey": entry}
    return entry if isinstance(entry, dict) else {}

def normalize_cloud_account(account):
    if not isinstance(account, dict):
        raise AppError("account must be an object", 400)
    aid = str(account.get("id") or "").strip()
    if not aid or not re.match(r"^[A-Za-z0-9_-]{1,48}$", aid):
        raise AppError("account.id must be 1-48 chars [A-Za-z0-9_-]", 400)
    atype = str(account.get("type") or "openai").strip()
    preset = CLOUD_PROVIDER_PRESETS.get(atype, {})
    name = str(account.get("name") or preset.get("name") or aid).strip()
    base_url = str(account.get("baseUrl") or preset.get("baseUrl") or "").strip().rstrip("/")
    if not base_url.startswith("http"):
        raise AppError("account.baseUrl must be http(s)", 400)
    auth_modes = preset.get("authModes", ["apiKey"])
    auth_mode = str(account.get("authMode") or auth_modes[0]).strip()
    if auth_mode not in auth_modes:
        auth_mode = auth_modes[0]
    account_type = str(account.get("accountType") or preset.get("accountType") or "").strip()
    result = {"id": aid, "type": atype, "name": name, "baseUrl": base_url, "authMode": auth_mode}
    if account_type:
        result["accountType"] = account_type
    if "oauth" in auth_modes:
        defaults = preset.get("oauth", {})
        supplied = account.get("oauthConfig") if isinstance(account.get("oauthConfig"), dict) else {}
        result["oauthConfig"] = {
            "authorizeUrl": str(supplied.get("authorizeUrl") or defaults.get("authorizeUrl") or "").strip(),
            "tokenUrl": str(supplied.get("tokenUrl") or defaults.get("tokenUrl") or "").strip(),
            "clientId": str(supplied.get("clientId") or defaults.get("clientId") or "").strip(),
            "scope": str(supplied.get("scope") or defaults.get("scope") or "").strip(),
            "redirectPort": int(supplied.get("redirectPort") or defaults.get("redirectPort") or 1455),
            "redirectPath": str(supplied.get("redirectPath") or defaults.get("redirectPath") or "/auth/callback").strip(),
        }
    return result

def normalize_cloud_block(block, account_ids):
    if not isinstance(block, dict):
        raise AppError("block must be an object", 400)
    bid = str(block.get("id") or "").strip()
    if not bid or not re.match(r"^[A-Za-z0-9_-]{1,48}$", bid):
        raise AppError("block.id must be 1-48 chars [A-Za-z0-9_-]", 400)
    account_id = str(block.get("accountId") or "").strip()
    if account_id not in account_ids:
        raise AppError("block.accountId must reference an existing account", 400)
    name = str(block.get("name") or bid).strip()
    model = str(block.get("model") or "").strip()
    model_mode = "passthrough" if str(block.get("modelMode") or "rewrite") == "passthrough" else "rewrite"
    # `exposed` = the user ticked this model in the router Outputs panel → it becomes a
    # routable cloud output (cb:<blockId>). Off by default; curated per provider.
    return {"id": bid, "accountId": account_id, "name": name, "model": model,
            "modelMode": model_mode, "exposed": bool(block.get("exposed", False))}

def upsert_cloud_account(account):
    norm = normalize_cloud_account(account)
    data = load_cloud_data()
    data["accounts"] = [a for a in data["accounts"] if a.get("id") != norm["id"]]
    data["accounts"].append(norm)
    save_cloud_data(data)
    return norm

def delete_cloud_account(account_id):
    account_id = str(account_id or "").strip()
    data = load_cloud_data()
    data["accounts"] = [a for a in data["accounts"] if a.get("id") != account_id]
    data["blocks"] = [b for b in data["blocks"] if b.get("accountId") != account_id]
    save_cloud_data(data)
    secrets = load_provider_secrets()
    if account_id in secrets:
        del secrets[account_id]
        save_provider_secrets(secrets)

def upsert_cloud_block(block):
    data = load_cloud_data()
    account_ids = {a["id"] for a in data["accounts"]}
    # Preserve a prior `exposed` choice across re-fetch unless the caller set it.
    if isinstance(block, dict) and "exposed" not in block:
        prev = next((b for b in data["blocks"] if b.get("id") == str(block.get("id") or "").strip()), None)
        if prev is not None:
            block = {**block, "exposed": bool(prev.get("exposed", False))}
    norm = normalize_cloud_block(block, account_ids)
    data["blocks"] = [b for b in data["blocks"] if b.get("id") != norm["id"]]
    data["blocks"].append(norm)
    save_cloud_data(data)
    return norm

def delete_cloud_block(block_id):
    block_id = str(block_id or "").strip()
    data = load_cloud_data()
    data["blocks"] = [b for b in data["blocks"] if b.get("id") != block_id]
    save_cloud_data(data)

def set_cloud_block_exposed(block_id, exposed):
    """Tick/untick a model in the router Outputs panel. Exposed blocks become routable
    cloud outputs (cb:<blockId>). Returns True if the flag changed."""
    block_id = str(block_id or "").strip()
    data = load_cloud_data()
    changed = False
    for b in data["blocks"]:
        if b.get("id") == block_id and bool(b.get("exposed", False)) != bool(exposed):
            b["exposed"] = bool(exposed)
            changed = True
    if changed:
        save_cloud_data(data)
    return changed

def account_auth_headers(account, secret):
    preset = CLOUD_PROVIDER_PRESETS.get(account.get("type"), {})
    headers = dict(preset.get("extraHeaders") or {})
    if account.get("authMode") == "oauth":
        token = (secret.get("oauth") or {}).get("accessToken") if isinstance(secret, dict) else ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
    else:
        key = secret.get("apiKey") if isinstance(secret, dict) else ""
        if key:
            headers[preset.get("authHeader", "Authorization")] = f"{preset.get('authPrefix', 'Bearer ')}{key}"
    return headers

def delete_account_credential(account_id):
    account_id = str(account_id or "").strip()
    secrets = load_provider_secrets()
    if account_id in secrets:
        del secrets[account_id]
        save_provider_secrets(secrets)

def account_credential_summary(account_id):
    account_id = str(account_id or "").strip()
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == account_id), None)
    if account and str(account.get("authMode") or "").strip() == "noKey":
        return {"hasCredential": True, "kind": "noKey", "last4": "", "oauthEmail": ""}
    entry = account_secret_entry(account_id)
    api_key = entry.get("apiKey") if isinstance(entry, dict) else ""
    oauth = entry.get("oauth") if isinstance(entry, dict) else None
    if oauth and oauth.get("accessToken"):
        return {"hasCredential": True, "kind": "oauth", "last4": "", "oauthEmail": oauth.get("email") or ""}
    if api_key:
        return {"hasCredential": True, "kind": "apiKey", "last4": api_key[-4:], "oauthEmail": ""}
    return {"hasCredential": False, "kind": "", "last4": "", "oauthEmail": ""}

def cloud_accounts_state():
    result = []
    for a in load_cloud_data()["accounts"]:
        summary = account_credential_summary(a["id"])
        result.append({
            "id": a["id"], "type": a.get("type"), "name": a.get("name"),
            "baseUrl": a.get("baseUrl"), "authMode": a.get("authMode") or "apiKey",
            "accountType": a.get("accountType") or "",
            "oauthConfig": a.get("oauthConfig") or {},
            "hasCredential": summary["hasCredential"],
            "credentialKind": summary["kind"],
            "keyLast4": summary["last4"],
            "oauthEmail": summary["oauthEmail"],
        })
    return result

def cloud_blocks_state():
    data = load_cloud_data()
    accounts = {a["id"]: a for a in data["accounts"]}
    result = []
    for b in data["blocks"]:
        account = accounts.get(b.get("accountId")) or {}
        summary = account_credential_summary(b.get("accountId"))
        result.append({
            "id": b["id"], "accountId": b.get("accountId"), "name": b.get("name"),
            "model": b.get("model"), "modelMode": b.get("modelMode") or "rewrite",
            "exposed": bool(b.get("exposed", False)),
            "accountName": account.get("name") or b.get("accountId"),
            "type": account.get("type"), "baseUrl": account.get("baseUrl"),
            "accountType": account.get("accountType") or "",
            "authMode": account.get("authMode") or "apiKey",
            "hasKey": summary["hasCredential"], "credentialKind": summary["kind"],
            "keyLast4": summary["last4"],
        })
    return result

def cloud_provider_presets_public():
    return [
        {"type": ptype, "name": cfg.get("name"), "baseUrl": cfg.get("baseUrl"),
         "model": cfg.get("model"), "authModes": cfg.get("authModes", ["apiKey"]),
         "accountType": cfg.get("accountType") or "",
         "oauth": {k: v for k, v in (cfg.get("oauth") or {}).items()}}
        for ptype, cfg in CLOUD_PROVIDER_PRESETS.items()
    ]
