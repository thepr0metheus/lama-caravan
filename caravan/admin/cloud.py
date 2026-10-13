"""Cloud provider data layer: accounts and pools (cloud-providers.json) and
credentials (~/.config/llamacpp-easy-admin/provider-secrets.json, 0600).

Pure data — no OAuth flows and no router logic; those live above this layer.
A pool's chain of steps is caravan/common/cloud_pools.py, and its desk
caravan/admin/pools.py.
"""
import json
import re

from caravan.admin.board_providers import BoardProviders
from caravan.admin.paths import CLOUD_PROVIDERS_FILE, PROVIDER_SECRETS_FILE
from caravan.common.cloud_file_keys import CloudFileKeys
from caravan.common.cloud_sources import CloudSources
from caravan.common.errors import AppError
from caravan.common.fsio import atomic_write_text
from caravan.store.cloud import CachedJsonStore


#: OpenAI's sign-in by a one-time code for the Codex app — what `codex login
#: --device-auth` does (openai/codex, codex-rs/login/src/device_code_auth.rs).
#: The board shows `verifyUrl` and a code; the controller asks `pollUrl`
#: whether the code was accepted and trades what it gets for tokens at the
#: account's tokenUrl with `redirectUri`. Nothing returns to localhost:1455,
#: so a controller on another machine than the browser — a NAS, a container —
#: finishes it by itself (caravan/admin/oauth.py, DeviceLogin).
OPENAI_DEVICE_LOGIN = {
    "userCodeUrl": "https://auth.openai.com/api/accounts/deviceauth/usercode",
    "pollUrl": "https://auth.openai.com/api/accounts/deviceauth/token",
    "verifyUrl": "https://auth.openai.com/codex/device",
    "redirectUri": "https://auth.openai.com/deviceauth/callback",
}

CLOUD_PROVIDER_PRESETS = {
    "openai-subscription": {
        "name": "OpenAI (ChatGPT Plus subscription)", "baseUrl": "https://chatgpt.com/backend-api",
        "model": "gpt-5.4-mini", "testPath": None,
        "authHeader": "Authorization", "authPrefix": "Bearer ",
        "extraHeaders": {}, "authModes": ["oauth"],
        "accountType": "openai-subscription",
        # What the sign-in by code trades its answer at, what renews it, and
        # where a deleted account's sign-in is ended (oauth.SignOut).
        "oauth": {
            "tokenUrl": "https://auth.openai.com/oauth/token",
            "clientId": "app_EMoamEEZ73f0CkXaXp7hrann",
            "revokeUrl": "https://auth.openai.com/oauth/revoke",
        },
        "deviceLogin": OPENAI_DEVICE_LOGIN,
    },
    "openai": {
        "name": "OpenAI (API Credits)", "baseUrl": "https://api.openai.com/v1", "model": "gpt-4o-mini",
        "testPath": "/models", "authHeader": "Authorization", "authPrefix": "Bearer ",
        # A key only: its OAuth was the return to localhost, which is gone. The
        # first subscriptions were made as this type, and they keep OAuth by
        # their plan (normalize_cloud_account, device_login_spec).
        "extraHeaders": {}, "authModes": ["apiKey"],
        "accountType": "openai-api",
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

#: The two documents. Everything about caching, invalidation and the file mode
#: lives in the store; this module is what the caravan MEANS by their contents.
_providers = CachedJsonStore(CLOUD_PROVIDERS_FILE)
_secrets = CachedJsonStore(PROVIDER_SECRETS_FILE)

#: Kept as module names because a handful of callers and tests reach for them.
_CLOUD_DATA_CACHE = _providers._cache
_SECRETS_CACHE = _secrets._cache


#: What the old form kept beside accounts and pools: its model blocks and the
#: models the operator deleted from them. They ride along until the controller
#: rewrites the file as pools of steps (caravan/admin/pools.py, PoolDesk.migrate).
LEGACY_KEYS = ("blocks", "deletedModels")


def _parse_cloud_data(parsed):
    """Accounts, pools, the subscription models' levels, the models added to
    the kanban and the providers on the main board — and, in a file of the old
    form, its model blocks."""
    data = {"accounts": [], "pools": [], "migrations": []}
    if isinstance(parsed, dict) and ("accounts" in parsed or "blocks" in parsed or "pools" in parsed):
        data["pools"] = [p for p in (parsed.get("pools") or []) if isinstance(p, dict) and p.get("id")]
        # The models' levels, the kanban's added models, the board's providers, the sets and the
        # schedules: one table names them for every reader and writer (CloudFileKeys).
        data.update(CloudFileKeys.read(parsed))
        done = parsed.get("migrations")
        data["migrations"] = [str(m) for m in done if isinstance(m, str)] if isinstance(done, list) else []
        accounts = parsed.get("accounts") if isinstance(parsed.get("accounts"), list) else []
        # An entry with no id cannot be pointed at by a step or a route, so it
        # is dropped rather than carried half-loaded into the board.
        data["accounts"] = [a for a in accounts if isinstance(a, dict) and a.get("id")]
        blocks = parsed.get("blocks") if isinstance(parsed.get("blocks"), list) else []
        if blocks:
            data["blocks"] = [b for b in blocks if isinstance(b, dict) and b.get("id")]
        if isinstance(parsed.get("deletedModels"), dict) and parsed["deletedModels"]:
            data["deletedModels"] = parsed["deletedModels"]
        return data
    # legacy flat {"providers":[...]} (or bare list) → migrate to account+block
    # pairs. The BLOCK keeps the original id: proxy routes already point at it,
    # and re-minting it would orphan every one of them.
    legacy = parsed.get("providers") if isinstance(parsed, dict) else parsed
    if isinstance(legacy, list):
        data["blocks"] = []
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


def load_cloud_data():
    """Accounts and pools, cached on the file's own (mtime, size).

    See caravan/store/cloud.py for why the cache is not an optimisation detail
    and why its key is the file generation rather than a timer.
    """
    # A fresh dict per call: this one is handed to callers that sort and filter
    # it, and a shared empty would be theirs to corrupt for everyone else.
    got = _providers.read(_parse_cloud_data)
    return got if got is not None else {"accounts": [], "pools": [], "migrations": []}


def save_cloud_data(data):
    # `migrations` travels with the file: a one-off that leaves no trace is not
    # a one-off, it is a job that runs at every start. The old form's keys are
    # written back while they hold anything — a save before the migration must
    # not drop the blocks it is about to turn into pools.
    # The kept keys (caravan/common/cloud_file_keys.py) travel while they hold anything:
    # a key not written here is dropped from the file by the next save of anything.
    _providers.write({"accounts": data.get("accounts", []), "pools": data.get("pools", []),
                      "migrations": sorted(set(data.get("migrations") or [])),
                      **CloudFileKeys.written(data),
                      **{key: data[key] for key in LEGACY_KEYS if data.get(key)}})


#: Name of the completed migration, stamped into the cloud data file itself.
MIGRATION_CONTEXT_AUTO = "contextAuto-2026-09"


def migrate_context_auto():
    """Stamp `contextAuto` on blocks that were living off the silent fallback.

    Until the switch existed, a block that stated no window still published
    whatever the account's catalogue had cached — nobody chose that, which is
    why the fallback became a decision. But turning the decision off for
    everyone would quietly take a REAL number away from every block whose
    provider does report one (279 of 502 on the fleet the day this shipped:
    OpenRouter publishes genuine 131072 / 200000 / 1000000 windows).

    So the previously implicit choice is written down instead of changed: a
    block with no stated window whose catalogue knows one gets contextAuto
    True, visible in the editor and untickable. Blocks created after this keep
    the off default. A block that already carries the key is left exactly as
    the operator set it.

    Runs once for real, and that had to be fixed: it ran at every controller
    start, so a block created LATER — window deliberately left empty — was
    stamped on the next restart and began publishing a figure nobody chose.
    That the docstring promised otherwise made it worse, not better. The fact
    that it has run is now written down beside the data it changed.
    """
    from caravan.admin.model_catalog import cached_models_entry

    data = load_cloud_data()
    if MIGRATION_CONTEXT_AUTO in (data.get("migrations") or []):
        return 0
    windows = {}
    changed = 0
    for block in data.get("blocks", []):
        if not isinstance(block, dict) or "contextAuto" in block or block.get("contextLength"):
            continue
        acct = block.get("accountId")
        if acct not in windows:
            windows[acct] = {m.get("id"): m.get("contextLength")
                             for m in ((cached_models_entry(acct) or {}).get("models") or [])
                             if isinstance(m, dict)}
        if windows[acct].get(block.get("model")):
            block["contextAuto"] = True
            changed += 1
    # Stamped ALWAYS, even when there was nothing to change: "found nothing to
    # stamp" is a completed migration too — otherwise it would keep waiting
    # for the first matching block and fire on it a month later.
    data["migrations"] = sorted(set(data.get("migrations") or []) | {MIGRATION_CONTEXT_AUTO})
    save_cloud_data(data)
    return changed


def load_provider_secrets():
    """The keys, cached the same way. Rotating one changes the file, so the next
    call reparses — a stale cache here would authenticate with a revoked key.

    Read-only on purpose. Writes go through CredentialVault: it re-reads the
    file under the lock a token renewal takes, and a copy read here and written
    back would put a spent refresh token over the renewed one."""
    got = _secrets.read(lambda raw: raw if isinstance(raw, dict) else {})
    return got if isinstance(got, dict) else {}


def account_secret_entry(account_id):
    owner = CloudSources(load_cloud_data()).canonical(account_id)
    entry = load_provider_secrets().get(owner["id"] if owner else str(account_id or ""))
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
    account_type = str(account.get("accountType") or preset.get("accountType") or "").strip()
    auth_modes = list(preset.get("authModes", ["apiKey"]))
    # OAuth is the sign-in by code now, so a plan that signs in by code keeps
    # it whatever the account's type says: the first subscriptions were made
    # as type `openai`, and a save must not turn them into key accounts.
    by_code = device_login_preset(account_type)
    if by_code and "oauth" not in auth_modes:
        auth_modes.append("oauth")
    auth_mode = str(account.get("authMode") or auth_modes[0]).strip()
    if auth_mode not in auth_modes:
        auth_mode = auth_modes[0]
    result = {"id": aid, "type": atype, "name": name, "baseUrl": base_url, "authMode": auth_mode}
    if account_type:
        result["accountType"] = account_type
    if "oauth" in auth_modes:
        defaults = preset.get("oauth") or by_code.get("oauth") or {}
        supplied = account.get("oauthConfig") if isinstance(account.get("oauthConfig"), dict) else {}
        result["oauthConfig"] = {
            "tokenUrl": str(supplied.get("tokenUrl") or defaults.get("tokenUrl") or "").strip(),
            "clientId": str(supplied.get("clientId") or defaults.get("clientId") or "").strip(),
        }
    if account.get("testAliasOf"):
        result["testAliasOf"] = str(account["testAliasOf"])
    return result

def upsert_cloud_account(account):
    data = load_cloud_data()
    # An edit sends only what it changes — the name, the address, how it signs
    # in. What it leaves out (a custom OAuth setup, the plan type) stays as it
    # is stored: normalizing the bare edit would put the preset's defaults back.
    aid = str(account.get("id") or "").strip() if isinstance(account, dict) else ""
    prev = next((a for a in data["accounts"] if a.get("id") == aid), None) if aid else None
    norm = normalize_cloud_account({**prev, **account} if prev else account)
    if norm.get("testAliasOf"):
        owner = CloudSources(data).canonical(norm["testAliasOf"])
        if not CloudSources.is_subscription(owner) or owner["id"] == norm["id"]:
            raise AppError("invalid test alias owner", 400)
    data["accounts"] = [a for a in data["accounts"] if a.get("id") != norm["id"]]
    data["accounts"].append(norm)
    # An account stands in no pool by itself: the row that names it is the
    # operator's (the kanban, caravan/admin/pools.py). It stands under its
    # provider on the main board, which is put there if it is missing
    # (caravan/admin/board_providers.py).
    providers = BoardProviders(data)
    if providers.add(BoardProviders.kind(norm)):
        data["boardProviders"] = providers.stored()
    save_cloud_data(data)
    return norm

def delete_cloud_account(account_id):
    """Delete an account and the steps that name it, then end its sign-in at
    the provider. Answers how that went — {ok, error} — or None when the
    account had no sign-in of its own to end (a key, a test alias)."""
    from caravan.admin.pools import PoolDesk
    # oauth.py reads this module, so it is imported here.
    from caravan.admin.oauth import SignOut, end_pending_logins
    aid = str(account_id or "").strip()
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == aid), None)
    removed = PoolDesk().remove_account(aid)
    # Its sign-in in progress goes with it.
    end_pending_logins(aid)
    leaving = SignOut.of(account, removed)
    return leaving.send() if leaving else None

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
    from caravan.common.credential_vault import CredentialVault
    CredentialVault(PROVIDER_SECRETS_FILE).delete(str(account_id or "").strip())

def device_login_preset(account_type):
    """The preset whose plan signs in by a one-time code — {} for a plan that
    does not (or for no plan at all)."""
    kind = str(account_type or "")
    if not kind:
        return {}
    return next((p for p in CLOUD_PROVIDER_PRESETS.values()
                 if p.get("accountType") == kind and p.get("deviceLogin")), {})


def device_login_spec(account):
    """How an account signs in by a one-time code — its provider's device
    login (OPENAI_DEVICE_LOGIN) — or {} when it has none.

    Read through accountType, not type: the first subscription accounts were
    made as type `openai` with accountType `openai-subscription`, and they sign
    in with ChatGPT all the same. A test alias signs in through its original.
    """
    account = account or {}
    if account.get("testAliasOf"):
        return {}
    return dict(device_login_preset(account.get("accountType")).get("deviceLogin") or {})

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
    """Every account as the board shows it: its sign-in in summary (never the
    key), and the steps of the pools that name it — what its deletion takes."""
    # oauth.py reads this module, so it is imported here.
    from caravan.admin.oauth import SignOut
    from caravan.common.cloud_pools import CloudPools
    result = []
    own = load_provider_secrets()
    data = load_cloud_data()
    used = {}
    for pool in CloudPools(data).all():
        for step in pool["steps"]:
            if step["kind"] == "account":
                used.setdefault(step["accountId"], []).append({"poolId": pool["id"], "poolName": pool["name"], "stepId": step["id"]})
    for a in CloudSources(data).accounts.values():
        summary = account_credential_summary(a["id"])
        result.append({
            "id": a["id"], "type": a.get("type"), "name": a.get("name"),
            "baseUrl": a.get("baseUrl"), "authMode": a.get("authMode") or "apiKey",
            "accountType": a.get("accountType") or "",
            "subscription": CloudSources.is_subscription(a),
            "oauthConfig": a.get("oauthConfig") or {},
            "hasCredential": summary["hasCredential"],
            "credentialKind": summary["kind"],
            "keyLast4": summary["last4"],
            "oauthEmail": summary["oauthEmail"],
            "deviceLogin": bool(device_login_spec(a)),
            # Whether deleting it ends a sign-in at the provider: the delete
            # confirmation says so only when the delete will (SignOut.of).
            "signOutOnDelete": SignOut.of(a, own.get(a["id"])) is not None,
            "usedIn": used.get(a["id"], []),
            **({"testAliasOf": a["testAliasOf"]} if a.get("testAliasOf") else {}),
        })
    return result

def cloud_provider_presets_public():
    return [
        {"type": ptype, "name": cfg.get("name"), "baseUrl": cfg.get("baseUrl"),
         "model": cfg.get("model"), "authModes": cfg.get("authModes", ["apiKey"]),
         "accountType": cfg.get("accountType") or "",
         "deviceLogin": bool(cfg.get("deviceLogin")),
         "oauth": {k: v for k, v in (cfg.get("oauth") or {}).items()}}
        for ptype, cfg in CLOUD_PROVIDER_PRESETS.items()
    ]
