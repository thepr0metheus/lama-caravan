"""Cloud provider/account credential resolution for proxied requests,
including on-the-fly OAuth refresh."""
import json
import os
import time

from caravan.proxy.paths import MODEL_CATALOG_FILE, CLOUD_PROVIDERS_FILE, PROVIDER_SECRETS_FILE
from caravan.proxy.runtime import config_lock
from caravan.common.cloud_file_keys import CloudFileKeys
from caravan.common.cloud_pools import CloudPools
from caravan.common.entry_models import EntryModels
from caravan.common.cloud_sources import CloudSources
from caravan.common.credential_vault import CredentialVault
from caravan.common.model_kinds import ModelKind
from caravan.common.model_levels import ModelLevels
from caravan.common.model_schedules import ModelSchedules


CLOUD_PROVIDER_AUTH = {
    "openai": {"authHeader": "Authorization", "authPrefix": "Bearer ", "extraHeaders": {}},
    "anthropic": {"authHeader": "x-api-key", "authPrefix": "", "extraHeaders": {"anthropic-version": "2023-06-01"}},
    "openrouter": {"authHeader": "Authorization", "authPrefix": "Bearer ", "extraHeaders": {}},
    "custom": {"authHeader": "Authorization", "authPrefix": "Bearer ", "extraHeaders": {}},
}

def _read_cloud_data():
    """The cloud document as the proxy reads it: accounts and pools — and, in a file of
    the old form, its model blocks, which CloudPools reads as pools — with every key the
    file keeps beside them (caravan/common/cloud_file_keys.py): the models' levels and
    schedules, the sets of models the entry's consumers call."""
    lists = ("accounts", "pools", "blocks")
    try:
        parsed = json.loads(CLOUD_PROVIDERS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no file, or one that does not read, is an empty document
        parsed = None
    parsed = parsed if isinstance(parsed, dict) else {}
    return {**{key: parsed.get(key) if isinstance(parsed.get(key), list) else [] for key in lists},
            **CloudFileKeys.read_all(parsed)}

def _cached_context_length(account_id, model_id):
    """What the account's catalogue last heard from the provider for this model.

    A cache, deliberately: the alternative is a network call on an endpoint the
    proxy answers locally today, which would let a third party's availability
    decide whether this port can describe itself. Absent when the catalogue has
    not been refreshed or the provider named no window — absence stays absence.
    """
    if not account_id or not model_id:
        return None
    try:
        data = json.loads(MODEL_CATALOG_FILE.read_text(encoding="utf-8"))
        models = (((data.get("accounts") or {}).get(str(account_id)) or {}).get("models")) or []
    except Exception:
        return None
    for model in models:
        if isinstance(model, dict) and model.get("id") == model_id:
            found = model.get("contextLength")
            return found if isinstance(found, int) and found > 0 else None
    return None


def load_cloud_provider(pool_id):
    """A cable's cloud end — a pool, by the id a route's providerId and the
    kanban's output `cb:<id>` name — as the proxy routes it: the pool with its
    steps and the window it stands for. Which step serves is chosen per request
    (caravan/proxy/pool_steps.py); `model` stays empty until then, and `name`
    is what a client is told it calls."""
    pool_id = str(pool_id or "").strip()
    if not pool_id:
        return None
    data = _read_cloud_data()
    secrets = CredentialVault(PROVIDER_SECRETS_FILE).read()
    sources = CloudSources(data, secrets)
    reading = CloudPools(data, secrets)
    pool = reading.get(pool_id)
    if not pool:
        return None
    # A file of the old form keeps its levels as the accounts' reserves: the
    # steps its blocks become carry them, and ModelLevels reads them as their
    # models' — as it reads a step's from before 1.3.486.
    levels = ModelLevels({**data, "pools": list(data.get("pools") or []) + [{"steps": reading.legacy_steps}]})

    def named(account_id, model):
        owner = sources.canonical(account_id)
        return _cached_context_length(owner["id"] if owner else account_id, model)
    return {
        "id": pool_id,
        "pool": pool,
        "name": pool["name"],
        "model": "",
        "modelMode": "rewrite",
        # The window the pool stands for: the operator's figure, or the
        # smallest its steps' providers name when they ticked that (the rule is
        # CloudPools.window, shared with the board so both say one number) — a
        # cell's the window it serves, as its router output carries it. The
        # catalogue is read only when the switch is on: it is a file on disk,
        # and a pool that never asked for it should not depend on it.
        "contextLength": CloudPools.window(pool, named, _output_window),
        # Each subscription model's stop and switch levels, the same in every
        # pool (caravan/common/model_levels.py) — read with the pool, so a request
        # is judged by one reading of the file.
        "levels": levels.stored(),
        # When each model is open (caravan/common/model_schedules.py): a row of a
        # model closed now is passed over, read with the pool for the same reason.
        "schedules": ModelSchedules(data).stored(),
    }

def _output_window(output_id):
    """The window a pool's cell serves, as its router output carries it, or None."""
    from caravan.proxy.outputs import router_output
    return (router_output(output_id) or {}).get("contextLength")


def load_pool_kind(pool):
    """What a pool's rows do together (caravan/common/model_kinds.py), from one reading of the
    cloud file and the routers' outputs: what the entry tells its clients of a model, and the
    work it refuses a model before sending."""
    from caravan.proxy.config import current_config
    from caravan.proxy.outputs import router_output
    accounts = CloudSources(_read_cloud_data()).accounts
    config = current_config()
    return ModelKind.of_pool(pool, accounts.get, lambda output_id: router_output(output_id, config))


def load_cloud_pools():
    """Every pool as the proxy reads it, in the file's order: what the entry
    publishes to its consumers (caravan/common/entry_models.py)."""
    return CloudPools(_read_cloud_data(), CredentialVault(PROVIDER_SECRETS_FILE).read()).all()

def load_entry_models():
    """The entry's reading of what its consumers call: the pools and the sets that
    hold them, from one reading of the file (caravan/common/entry_models.py)."""
    data = _read_cloud_data()
    return EntryModels(CloudPools(data, CredentialVault(PROVIDER_SECRETS_FILE).read()).all(), data.get("sets"))

def load_cloud_account(account_id):
    """One account as a provider: what a pool's step goes to, and what a route
    that names an account and no pool reaches — then with the client's model
    forwarded unchanged (passthrough)."""
    account_id = str(account_id or "").strip()
    if not account_id:
        return None
    data = _read_cloud_data()
    account = CloudSources(data, CredentialVault(PROVIDER_SECRETS_FILE).read()).source(account_id)
    if not account:
        return None
    return {
        "id": account_id,
        "accountId": account_id,
        "credentialAccountId": account.get("credentialAccountId") or account_id,
        "usageAccountId": account.get("usageAccountId") or account_id,
        "type": account.get("type") or "openai",
        "accountType": account.get("accountType") or "",
        "baseUrl": account.get("baseUrl") or "",
        "authMode": account.get("authMode") or "apiKey",
        "oauthConfig": account.get("oauthConfig") if isinstance(account.get("oauthConfig"), dict) else {},
        "model": "",
        "modelMode": "passthrough",
    }

def _refresh_oauth(provider, entry):
    """Facade for the shared cross-process renewal owner; entry is a legacy argument."""
    return CredentialVault(PROVIDER_SECRETS_FILE).oauth(
        provider.get("credentialAccountId") or provider.get("accountId"),
        provider.get("oauthConfig") or {}).get("accessToken")

def provider_secret_present(provider):
    """Cheap presence check for /health: is ANY credential stored for the
    provider's account? No refresh, no network — health must not mutate tokens."""
    account_id = str((provider or {}).get("credentialAccountId") or (provider or {}).get("accountId") or "").strip()
    if (provider or {}).get("pool"):
        return any(provider_secret_present(load_cloud_account(s.get("accountId")))
                   for s in provider["pool"].get("steps", []) if s.get("enabled", True))
    if not account_id or not PROVIDER_SECRETS_FILE.exists():
        return False
    try:
        parsed = json.loads(PROVIDER_SECRETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    entry = parsed.get(account_id) if isinstance(parsed, dict) else None
    if isinstance(entry, str):
        return bool(entry)
    if not isinstance(entry, dict):
        return False
    return bool(entry.get("apiKey") or (entry.get("oauth") or {}).get("accessToken"))

def load_provider_secret(provider):
    """Return the auth header tuple (header_name, header_value) for an effective
    provider dict, or None if no usable credential."""
    account_id = str((provider or {}).get("credentialAccountId") or (provider or {}).get("accountId") or "").strip()
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
            try:
                token = _refresh_oauth(provider, entry) or token
            except Exception:
                return None   # an expired credential is not a working sign-in
        if token:
            return ("Authorization", f"Bearer {token}")
        return None
    key = entry.get("apiKey")
    if key:
        return (auth["authHeader"], f"{auth['authPrefix']}{key}")
    return None
