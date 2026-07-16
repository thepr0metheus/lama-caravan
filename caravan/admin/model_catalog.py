"""Provider model catalog cache + upstream endpoint health (circuit breaker).

Three jobs, all backed by one small state file (state/model-catalog.json):

1) Which models does a provider CURRENTLY serve — per-account list with a 1h
   TTL, refreshed in a background thread so topology reads never block on the
   network. Blocks whose model fell out of this list are painted "unlisted"
   in the UI.
2) Endpoint health — an upstream helper call that keeps failing is DISABLED
   after BREAK_AFTER consecutive failures (exponential backoff), so we stop
   hammering the provider with requests we know are broken. Every tripped
   endpoint is reported in topology (cloudApiHealth) for the provider card,
   with a manual retry to re-arm it.
3) The codex client_version to send to chatgpt.com — env override wins, else
   the newest of the npm "@openai/codex" latest (cached a day) and a built-in
   floor. The floor matters: model gating references versions ABOVE the
   published CLI (5.6 unlocks at 0.150.0 while npm latest was 0.144.5), so
   npm alone would silently lose models.
"""
import json
import os
import re
import threading
import time
import urllib.request

from caravan.admin.paths import MODEL_CATALOG_FILE
from caravan.common.errors import AppError
from caravan.common.fsio import atomic_write_text

_LOCK = threading.RLock()
_REFRESH_THREADS = {}   # account_id -> Thread; alive = refresh in flight

MODELS_TTL_SEC = 3600
NPM_TTL_SEC = 86400
BREAK_AFTER = 3                 # consecutive failures before an endpoint trips
BREAK_BASE_SEC = 6 * 3600       # first backoff once tripped
BREAK_MAX_SEC = 48 * 3600
CODEX_CLIENT_VERSION_FLOOR = "0.160.0"
NPM_LATEST_URL = "https://registry.npmjs.org/@openai/codex/latest"


def _load():
    try:
        data = json.loads(MODEL_CATALOG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    atomic_write_text(MODEL_CATALOG_FILE, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _mutate(fn):
    with _LOCK:
        data = _load()
        fn(data)
        _save(data)


# ── endpoint circuit breaker ─────────────────────────────────────────────────
# Keys are "<accountId>:<what>" (e.g. "openai-subscription:models") or
# "global:<what>" for account-less calls (npm version probe).

def endpoint_state(key):
    with _LOCK:
        return dict((_load().get("endpoints") or {}).get(str(key)) or {})


def endpoint_blocked(key):
    st = endpoint_state(key)
    return time.time() < float(st.get("disabledUntil") or 0)


def record_ok(key):
    def fn(data):
        eps = data.setdefault("endpoints", {})
        if str(key) in eps:
            del eps[str(key)]
    _mutate(fn)


def record_fail(key, error):
    def fn(data):
        eps = data.setdefault("endpoints", {})
        st = eps.setdefault(str(key), {})
        st["failCount"] = int(st.get("failCount") or 0) + 1
        st["lastError"] = str(error)[:300]
        st["lastErrorAt"] = int(time.time())
        over = st["failCount"] - BREAK_AFTER
        if over >= 0:
            st["disabledUntil"] = int(time.time() + min(BREAK_BASE_SEC * (2 ** over), BREAK_MAX_SEC))
    _mutate(fn)


def retry_endpoint(key):
    """Manual re-arm from the provider card: forget the trip, keep no grudge."""
    record_ok(key)


def endpoints_report():
    """Everything that failed at least once, for the cloudApiHealth panel."""
    now = time.time()
    out = {}
    with _LOCK:
        for key, st in (_load().get("endpoints") or {}).items():
            if not isinstance(st, dict):
                continue
            out[key] = {
                "failCount": int(st.get("failCount") or 0),
                "lastError": str(st.get("lastError") or ""),
                "lastErrorAt": int(st.get("lastErrorAt") or 0),
                "disabledUntil": int(st.get("disabledUntil") or 0),
                "disabled": now < float(st.get("disabledUntil") or 0),
            }
    return out


def guarded_call(key, fn):
    """Run an upstream call through the breaker: refuse while tripped, record
    the outcome otherwise. The caller's own exceptions propagate unchanged."""
    if endpoint_blocked(key):
        st = endpoint_state(key)
        raise AppError(
            f"endpoint disabled after {st.get('failCount', 0)} failures "
            f"(retry from the provider card): {st.get('lastError', '')[:120]}", 503)
    try:
        result = fn()
    except Exception as e:
        record_fail(key, getattr(e, "message", None) or str(e))
        raise
    record_ok(key)
    return result


# ── codex client_version ─────────────────────────────────────────────────────

def _semver_tuple(s):
    return tuple(int(x) for x in re.findall(r"\d+", str(s) or "0")[:4]) or (0,)


def _npm_latest_cached():
    with _LOCK:
        cached = _load().get("codexNpm") or {}
    if time.time() - float(cached.get("checkedAt") or 0) < NPM_TTL_SEC:
        return str(cached.get("version") or "")
    if endpoint_blocked("global:codex-npm"):
        return str(cached.get("version") or "")

    def _fetch():
        with urllib.request.urlopen(NPM_LATEST_URL, timeout=8) as r:
            return str(json.loads(r.read().decode()).get("version") or "")
    try:
        version = guarded_call("global:codex-npm", _fetch)
    except Exception:
        return str(cached.get("version") or "")
    _mutate(lambda data: data.__setitem__("codexNpm", {"version": version, "checkedAt": int(time.time())}))
    return version


def effective_codex_client_version():
    """env CARAVAN_CODEX_CLIENT_VERSION verbatim, else max(npm latest, floor)."""
    env = os.environ.get("CARAVAN_CODEX_CLIENT_VERSION", "").strip()
    if env:
        return env, "env"
    npm = _npm_latest_cached()
    if npm and _semver_tuple(npm) > _semver_tuple(CODEX_CLIENT_VERSION_FLOOR):
        return npm, "npm"
    return CODEX_CLIENT_VERSION_FLOOR, "floor"


# ── per-account model list cache ─────────────────────────────────────────────

def cached_models_entry(account_id):
    with _LOCK:
        entry = (_load().get("accounts") or {}).get(str(account_id))
    return entry if isinstance(entry, dict) else None


def cached_model_ids(account_id):
    """set of model ids, or None when no successful fetch is cached yet."""
    entry = cached_models_entry(account_id)
    if not entry:
        return None
    models = entry.get("models") or []
    ids = {str(m.get("id")) for m in models if isinstance(m, dict) and m.get("id")}
    return ids or None


def store_models(account_id, models):
    def fn(data):
        data.setdefault("accounts", {})[str(account_id)] = {
            "models": [{"id": m.get("id"), "name": m.get("name") or m.get("id")}
                       for m in (models or []) if isinstance(m, dict) and m.get("id")],
            "fetchedAt": int(time.time()),
        }
    _mutate(fn)


def models_stale(account_id):
    entry = cached_models_entry(account_id)
    return not entry or time.time() - float(entry.get("fetchedAt") or 0) > MODELS_TTL_SEC


def kick_refresh(account_id, fetcher):
    """Refresh an account's model list in a daemon thread (at most one per
    account). `fetcher()` must return the models and is expected to run its
    network call through guarded_call (failures feed the breaker, and while
    tripped the fetcher raises instantly, so the stale cache just stays)."""
    account_id = str(account_id)
    with _LOCK:
        th = _REFRESH_THREADS.get(account_id)
        if th and th.is_alive():
            return

        def _run():
            try:
                store_models(account_id, fetcher())
            except Exception:
                pass  # breaker already recorded it; stale cache remains authoritative
        th = threading.Thread(target=_run, daemon=True, name=f"model-catalog-{account_id}")
        _REFRESH_THREADS[account_id] = th
        th.start()
