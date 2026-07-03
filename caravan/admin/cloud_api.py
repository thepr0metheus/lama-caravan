"""Live calls to cloud provider APIs: model lists, costs, limits, subscription
usage, plus the usage-stats aggregation over proxy event logs."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from caravan.admin.cloud import (
    CLOUD_PROVIDER_PRESETS,
    account_auth_headers,
    account_secret_entry,
    load_cloud_data,
    load_provider_secrets,
    save_cloud_data,
    save_provider_secrets,
)
from caravan.admin.oauth import refresh_oauth_token
from caravan.admin.paths import AGENT_PROXY_LOG_DIR
from caravan.admin.pricing import fetch_model_pricing
from caravan.admin.state import admin_state
from caravan.common.errors import AppError


def test_account_key(account, key):
    preset = CLOUD_PROVIDER_PRESETS.get(account.get("type"), {})
    url = account["baseUrl"].rstrip("/") + preset.get("testPath", "/models")
    headers = account_auth_headers(account, {"apiKey": key})
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return {"ok": True, "status": response.status}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"ok": False, "status": exc.code, "error": "key rejected"}
        if exc.code in (404, 405):
            return {"ok": True, "status": exc.code, "note": f"validated (endpoint returned {exc.code})"}
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def set_account_key(account_id, key):
    account_id = str(account_id or "").strip()
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == account_id), None)
    if not account:
        raise AppError("unknown account", 404)
    key = str(key or "").strip()
    if not key:
        raise AppError("api key required", 400)
    result = test_account_key(account, key)
    if not result.get("ok"):
        return {"ok": False, "test": result}
    secrets = load_provider_secrets()
    entry = secrets.get(account_id) if isinstance(secrets.get(account_id), dict) else {}
    entry["apiKey"] = key
    secrets[account_id] = entry
    save_provider_secrets(secrets)
    return {"ok": True, "test": result, "last4": key[-4:]}

def fetch_account_models(account_id):
    """Fetch models via GET /models for any OpenAI-compatible account."""
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if not account:
        raise AppError("unknown account", 404)
    preset = CLOUD_PROVIDER_PRESETS.get(account.get("type"), {})
    test_path = preset.get("testPath", "/models")
    if not test_path:
        raise AppError("model listing not supported for this account type", 400)
    # OAuth accounts: refresh the access token first (it may have expired) so the
    # /models call carries a valid bearer — same as the subscription path.
    if account.get("authMode") == "oauth":
        try:
            refresh_oauth_token(account)
        except Exception:
            pass
    secret = account_secret_entry(account_id)
    headers = account_auth_headers(account, secret)
    url = account["baseUrl"].rstrip("/") + test_path
    req = urllib.request.Request(url, headers={**headers, "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise AppError(f"HTTP {e.code}: {e.read().decode()[:200]}", 502)
    except Exception as e:
        raise AppError(f"failed to fetch models: {e}", 502)
    # OpenAI format: {"data": [...]} · Ollama native format: {"models": [...]}
    items = (data.get("data") or data.get("models") or []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    models = []
    for m in items:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("name") or m.get("model") or ""
        if mid:
            models.append({"id": mid, "name": m.get("name") or mid})
    return sorted(models, key=lambda m: m["id"].lower())

def fetch_account_costs(account_id, days=30):
    """Official OpenAI-compatible spend via GET <baseUrl>/organization/costs (needs an
    API key with the api.usage.read scope, e.g. an Admin key). Returns daily cost series
    + total, or {ok:False,error} with a scope hint on 403. This is SPEND, not a balance —
    OpenAI exposes no remaining-credit balance to API keys."""
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if not account:
        raise AppError("unknown account", 404)
    base = (account.get("baseUrl") or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "account has no baseUrl"}
    if account.get("authMode") == "oauth":
        try:
            refresh_oauth_token(account)
        except Exception:
            pass
    headers = {**account_auth_headers(account, account_secret_entry(account_id)), "Accept": "application/json"}
    start = int(time.time()) - int(days) * 86400
    url = f"{base}/organization/costs?start_time={start}&bucket_width=1d&limit={int(days) + 1}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code in (401, 403) and "api.usage.read" in body:
            return {"ok": False, "error": "needs an API key with the api.usage.read scope (Admin key or a key granted Usage read)"}
        if e.code in (401, 403):
            return {"ok": False, "error": f"not permitted ({e.code})"}
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    total = 0.0
    currency = "usd"
    series = []
    for bucket in (data.get("data") or []):
        c = 0.0
        for res in (bucket.get("results") or []):
            amt = res.get("amount") or {}
            c += float(amt.get("value") or 0)
            currency = amt.get("currency") or currency
        total += c
        series.append({"t": bucket.get("start_time"), "cost": round(c, 4)})
    return {"ok": True, "total": round(total, 4), "currency": currency, "windowDays": int(days), "days": series}

def fetch_openrouter_limits(account_id):
    """Fetch rate-limit info from OpenRouter GET /api/v1/auth/key.
    Returns daily token usage/limit and per-interval request cap."""
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if not account:
        raise AppError("unknown account", 404)
    base = (account.get("baseUrl") or "https://openrouter.ai/api/v1").rstrip("/")
    url = f"{base}/auth/key"
    headers = {**account_auth_headers(account, account_secret_entry(account_id)), "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "authError": True, "error": "key invalid or revoked"}
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    kd = data.get("data") or {}
    rl = kd.get("rate_limit") or {}
    return {
        "ok": True,
        "isFreeTier": bool(kd.get("is_free_tier")),
        "label": kd.get("label"),
        "usage": kd.get("usage"),
        "limit": kd.get("limit"),
        "rateLimit": {"requests": rl.get("requests"), "interval": rl.get("interval")} if rl else None,
    }

def cloud_spend_summary(days=30):
    """Local spend-meter: aggregate $ spent through the proxy from the event logs
    (cloud `finished` events: tokens × per-model pricing), per cloud account + model,
    over the last `days`. Independent of any provider billing API."""
    pricing = fetch_model_pricing() or {}
    data = load_cloud_data()
    blocks_by_id = {b.get("id"): b for b in data.get("blocks", [])}
    summary = {}
    for i in range(int(days)):
        dstr = datetime.fromtimestamp(time.time() - i * 86400).strftime("%Y-%m-%d")
        path = AGENT_PROXY_LOG_DIR / f"{dstr}.jsonl"
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for ln in lines:
            if '"finished"' not in ln or '"cloud"' not in ln:
                continue
            try:
                it = (json.loads(ln).get("item") or {})
            except Exception:
                continue
            if str(it.get("upstreamType")) != "cloud":
                continue
            blk = blocks_by_id.get(str(it.get("providerId") or "")) or {}
            acct = str(it.get("cloudAccountId") or blk.get("accountId") or "")
            if not acct:
                continue
            model = blk.get("model") or it.get("model") or "?"
            u = it.get("usage") or {}
            pt, ct = int(u.get("prompt") or 0), int(u.get("completion") or 0)
            pr = pricing.get(model) or {}
            cost = pt / 1e6 * float(pr.get("inputPer1M") or 0) + ct / 1e6 * float(pr.get("outputPer1M") or 0)
            a = summary.setdefault(acct, {"total": 0.0, "requests": 0, "promptTokens": 0, "completionTokens": 0, "byModel": {}})
            a["total"] += cost; a["requests"] += 1; a["promptTokens"] += pt; a["completionTokens"] += ct
            m = a["byModel"].setdefault(model, {"model": model, "cost": 0.0, "requests": 0})
            m["cost"] += cost; m["requests"] += 1
    out = {}
    for acct, a in summary.items():
        models = sorted(a["byModel"].values(), key=lambda x: -x["cost"])
        for m in models:
            m["cost"] = round(m["cost"], 4)
        out[acct] = {"total": round(a["total"], 4), "requests": a["requests"],
                     "promptTokens": a["promptTokens"], "completionTokens": a["completionTokens"],
                     "windowDays": int(days), "byModel": models}
    return out

def usage_stats(days=30):
    """Combined usage/spend stats over the last `days` for the statistics panel.

    Single pass over the proxy event logs' `finished` events, classified by
    upstreamType:
      - cloud  → $ actually spent (tokens × LiteLLM per-model pricing), per account + model.
      - local  → tokens processed (llama servers), per model, plus a "would have cost in
                 the cloud" estimate from the global manual rate (admin_state.localPricing).
    Also returns a per-day series so the UI can show a breakdown. Capped by the log
    retention window (no long-term store)."""
    days = max(1, min(int(days), 365))
    pricing = fetch_model_pricing() or {}
    overrides = admin_state.get("apiPricing") or {}
    data = load_cloud_data()
    blocks_by_id = {b.get("id"): b for b in data.get("blocks", [])}
    rate = admin_state.get("localPricing") or {}
    rate_in = float(rate.get("inputPer1M") or 0)
    rate_out = float(rate.get("outputPer1M") or 0)

    def model_price(model):
        """Resolve a model's per-1M price: manual override wins, else LiteLLM, else 0.
        Returns (inputPer1M, outputPer1M, has_price)."""
        ov = overrides.get(model)
        if isinstance(ov, dict) and (ov.get("inputPer1M") or ov.get("outputPer1M")):
            return float(ov.get("inputPer1M") or 0), float(ov.get("outputPer1M") or 0), True
        pr = pricing.get(model)
        if isinstance(pr, dict) and (pr.get("inputPer1M") or pr.get("outputPer1M")):
            return float(pr.get("inputPer1M") or 0), float(pr.get("outputPer1M") or 0), True
        return 0.0, 0.0, False

    cloud_acct = {}   # acct -> {total, requests, promptTokens, completionTokens, byModel{}}
    cloud_model = {}  # model -> {model, cost, requests, promptTokens, completionTokens}
    local_model = {}  # model -> {model, requests, promptTokens, completionTokens, wouldCost}
    daily = {}        # date -> {cloudCost, cloudTokens, localTokens, localWouldCost}

    for i in range(days):
        dstr = datetime.fromtimestamp(time.time() - i * 86400).strftime("%Y-%m-%d")
        path = AGENT_PROXY_LOG_DIR / f"{dstr}.jsonl"
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        d = daily.setdefault(dstr, {"date": dstr, "cloudCost": 0.0, "cloudTokens": 0,
                                    "localTokens": 0, "localWouldCost": 0.0})
        for ln in lines:
            if '"finished"' not in ln:
                continue
            try:
                it = (json.loads(ln).get("item") or {})
            except Exception:
                continue
            utype = str(it.get("upstreamType") or "llama")
            u = it.get("usage") or {}
            pt, ct = int(u.get("prompt") or 0), int(u.get("completion") or 0)
            if utype == "cloud":
                blk = blocks_by_id.get(str(it.get("providerId") or "")) or {}
                acct = str(it.get("cloudAccountId") or blk.get("accountId") or "")
                if not acct:
                    continue
                model = blk.get("model") or it.get("model") or "?"
                p_in, p_out, has_price = model_price(model)
                cost = pt / 1e6 * p_in + ct / 1e6 * p_out
                a = cloud_acct.setdefault(acct, {"total": 0.0, "requests": 0, "promptTokens": 0,
                                                 "completionTokens": 0, "byModel": {}})
                a["total"] += cost; a["requests"] += 1; a["promptTokens"] += pt; a["completionTokens"] += ct
                am = a["byModel"].setdefault(model, {"model": model, "cost": 0.0, "requests": 0,
                                                     "promptTokens": 0, "completionTokens": 0, "hasPrice": has_price})
                am["cost"] += cost; am["requests"] += 1; am["promptTokens"] += pt; am["completionTokens"] += ct
                am["hasPrice"] = has_price
                cm = cloud_model.setdefault(model, {"model": model, "cost": 0.0, "requests": 0,
                                                    "promptTokens": 0, "completionTokens": 0})
                cm["cost"] += cost; cm["requests"] += 1; cm["promptTokens"] += pt; cm["completionTokens"] += ct
                d["cloudCost"] += cost; d["cloudTokens"] += pt + ct
            else:
                model = it.get("model") or "(unspecified)"
                would = pt / 1e6 * rate_in + ct / 1e6 * rate_out
                lm = local_model.setdefault(model, {"model": model, "requests": 0, "promptTokens": 0,
                                                    "completionTokens": 0, "wouldCost": 0.0})
                lm["requests"] += 1; lm["promptTokens"] += pt; lm["completionTokens"] += ct
                lm["wouldCost"] += would
                d["localTokens"] += pt + ct; d["localWouldCost"] += would

    # ---- shape the response ----
    acct_names = {str(x.get("id")): (x.get("name") or x.get("id")) for x in data.get("accounts", [])}
    acct_sub = {str(x.get("id")): (str(x.get("accountType") or "") == "openai-subscription"
                                   or "chatgpt.com" in str(x.get("baseUrl") or ""))
                for x in data.get("accounts", [])}
    cloud_by_account = {}
    cloud_total = 0.0; cloud_req = 0; cloud_pt = 0; cloud_ct = 0
    for acct, a in cloud_acct.items():
        models = sorted(a["byModel"].values(), key=lambda x: -x["cost"])
        for m in models:
            m["cost"] = round(m["cost"], 4)
            pin, pout, _ = model_price(m["model"])
            m["priceIn"] = pin; m["priceOut"] = pout
        cloud_by_account[acct] = {"id": acct, "name": acct_names.get(acct, acct),
                                  "subscription": bool(acct_sub.get(acct)),
                                  "total": round(a["total"], 4), "requests": a["requests"],
                                  "promptTokens": a["promptTokens"], "completionTokens": a["completionTokens"],
                                  "byModel": models}
        cloud_total += a["total"]; cloud_req += a["requests"]
        cloud_pt += a["promptTokens"]; cloud_ct += a["completionTokens"]
    cloud_models = sorted(cloud_model.values(), key=lambda x: -x["cost"])
    for m in cloud_models:
        m["cost"] = round(m["cost"], 4)

    local_models = sorted(local_model.values(), key=lambda x: -(x["promptTokens"] + x["completionTokens"]))
    for m in local_models:
        m["wouldCost"] = round(m["wouldCost"], 4)
    local_pt = sum(m["promptTokens"] for m in local_models)
    local_ct = sum(m["completionTokens"] for m in local_models)
    local_req = sum(m["requests"] for m in local_models)
    local_would = sum(m["wouldCost"] for m in local_models)

    daily_series = []
    for dstr in sorted(daily.keys()):
        d = daily[dstr]
        daily_series.append({"date": dstr, "cloudCost": round(d["cloudCost"], 4),
                             "cloudTokens": d["cloudTokens"], "localTokens": d["localTokens"],
                             "localWouldCost": round(d["localWouldCost"], 4)})

    return {
        "ok": True, "windowDays": days,
        "rate": {"inputPer1M": rate_in, "outputPer1M": rate_out},
        "cloud": {"total": round(cloud_total, 4), "requests": cloud_req,
                  "promptTokens": cloud_pt, "completionTokens": cloud_ct,
                  "byAccount": cloud_by_account, "byModel": cloud_models},
        "local": {"wouldCost": round(local_would, 4), "requests": local_req,
                  "promptTokens": local_pt, "completionTokens": local_ct,
                  "byModel": local_models},
        "daily": daily_series,
    }

def fetch_subscription_models(account_id):
    """Fetch available models from chatgpt.com/backend-api/codex/models for an openai-subscription account."""
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if not account:
        raise AppError("unknown account", 404)
    token, account_id_header = _subscription_auth_headers(account)
    req = urllib.request.Request(
        "https://chatgpt.com/backend-api/codex/models?client_version=0.132.0",
        headers={
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": account_id_header,
            "originator": "pi",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise AppError(f"chatgpt.com returned {e.code}: {e.read().decode()[:200]}", 502)
    except Exception as e:
        raise AppError(f"failed to fetch models: {e}", 502)
    models = [
        {"id": m["slug"], "name": m.get("display_name") or m["slug"]}
        for m in data.get("models", [])
        if m.get("visibility") != "hide" and m.get("supported_in_api")
    ]
    return models

def auto_create_blocks(account_id):
    """Fetch all models for an account and create a block for each missing one."""
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if not account:
        raise AppError("unknown account", 404)
    is_subscription = (account.get("accountType") or "") == "openai-subscription"
    models = fetch_subscription_models(account_id) if is_subscription else fetch_account_models(account_id)
    if not models:
        return {"created": 0, "total": 0}
    data = load_cloud_data()
    existing_ids = {b["id"] for b in data["blocks"]}
    existing_models = {b["model"] for b in data["blocks"] if b.get("accountId") == account_id}
    created = 0
    for m in models:
        mid = m["id"]
        if mid in existing_models:
            continue
        slug = re.sub(r"[^A-Za-z0-9_-]", "-", mid)[:40].strip("-") or "model"
        bid, n = slug, 1
        while bid in existing_ids:
            bid, n = f"{slug}-{n}", n + 1
        data["blocks"].append({"id": bid, "accountId": account_id, "name": mid, "model": mid, "modelMode": "rewrite"})
        existing_ids.add(bid)
        created += 1
    if created:
        save_cloud_data(data)
    return {"created": created, "total": len(models)}

def _subscription_auth_headers(account):
    """Return (token, account_id_header) for a subscription account, refreshing if needed."""
    secrets = load_provider_secrets()
    entry = secrets.get(account["id"])
    if not isinstance(entry, dict):
        raise AppError("no credential stored for this account", 400)
    oauth = entry.get("oauth") or {}
    token = oauth.get("accessToken") or ""
    if not token:
        raise AppError("no OAuth token — log in first", 400)
    expires_at = int(oauth.get("expiresAt") or 0)
    if expires_at and expires_at - int(time.time()) < 60:
        token_url = (account.get("oauthConfig") or {}).get("tokenUrl") or ""
        refresh = oauth.get("refreshToken") or ""
        if token_url and refresh:
            data = urllib.parse.urlencode({
                "grant_type": "refresh_token", "refresh_token": refresh,
                "client_id": (account.get("oauthConfig") or {}).get("clientId") or "",
            }).encode("ascii")
            try:
                req = urllib.request.Request(token_url, data=data,
                                             headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
                with urllib.request.urlopen(req, timeout=15) as r:
                    tokens = json.loads(r.read().decode())
                token = tokens.get("access_token") or token
                oauth["accessToken"] = token
                if tokens.get("refresh_token"):
                    oauth["refreshToken"] = tokens["refresh_token"]
                if tokens.get("expires_in"):
                    oauth["expiresAt"] = int(time.time()) + int(tokens["expires_in"])
                entry["oauth"] = oauth
                secrets[account["id"]] = entry
                save_provider_secrets(secrets)
            except Exception:
                pass
    try:
        import base64 as _b64
        parts = token.split(".")
        pad = "=" * (4 - len(parts[1]) % 4)
        jwt_payload = json.loads(_b64.urlsafe_b64decode(parts[1] + pad))
        account_id_header = jwt_payload["https://api.openai.com/auth"]["chatgpt_account_id"]
    except Exception:
        account_id_header = ""
    return token, account_id_header

def fetch_subscription_usage(account_id):
    """Fetch Codex usage limits and credits from chatgpt.com for a subscription account."""
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if not account:
        raise AppError("unknown account", 404)
    token, acct_id_header = _subscription_auth_headers(account)
    base_headers = {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": acct_id_header,
        "originator": "pi",
        "Accept": "application/json",
    }
    # Try candidate endpoints in order (wham/usage is the confirmed analytics endpoint)
    candidates = [
        "https://chatgpt.com/backend-api/wham/usage",
        "https://chatgpt.com/backend-api/codex/usage",
        "https://chatgpt.com/backend-api/agentic_usage",
    ]
    last_err = None
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers=base_headers, method="GET")
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            return _normalize_subscription_usage(data)
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} from {url}"
            if e.code in (401, 403):
                raise AppError(f"auth error: {e.code}", 401)
            continue  # try next candidate
        except Exception as e:
            last_err = str(e)
            continue
    raise AppError(f"could not fetch usage from any endpoint: {last_err}", 502)

def _normalize_subscription_usage(data):
    """Normalize chatgpt.com wham/usage response into a stable shape for the UI.

    Real response shape (confirmed):
    {
      "rate_limit": {
        "primary_window":   { "used_percent": 3,   "limit_window_seconds": 18000,  "reset_after_seconds": 14217, "reset_at": 1779899331 },
        "secondary_window": { "used_percent": 100, "limit_window_seconds": 604800, "reset_after_seconds": 336233, "reset_at": 1780221347 }
      },
      "credits": { "has_credits": true, "balance": "394.7967250000", ... }
    }
    """
    limits = []
    rate_limit = data.get("rate_limit") or {}

    def window_to_limit(window, label):
        if not isinstance(window, dict):
            return None
        used_pct = int(window.get("used_percent") or 0)
        remaining_pct = max(0, 100 - used_pct)
        reset_at_ts = window.get("reset_at")
        resets_at = ""
        if reset_at_ts:
            try:
                import datetime
                resets_at = datetime.datetime.utcfromtimestamp(int(reset_at_ts)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                resets_at = str(reset_at_ts)
        return {"label": label, "remainingPct": remaining_pct, "resetsAt": resets_at}

    primary = rate_limit.get("primary_window")
    secondary = rate_limit.get("secondary_window")
    # primary_window is typically 5h (18000s), secondary is weekly (604800s)
    if isinstance(primary, dict):
        secs = int(primary.get("limit_window_seconds") or 0)
        label = f"{secs // 3600}h limit" if secs >= 3600 else "Hourly limit"
        lim = window_to_limit(primary, label)
        if lim:
            limits.append(lim)
    if isinstance(secondary, dict):
        secs = int(secondary.get("limit_window_seconds") or 0)
        label = "Weekly limit" if secs >= 604800 else (f"{secs // 86400}d limit" if secs >= 86400 else "Limit")
        lim = window_to_limit(secondary, label)
        if lim:
            limits.append(lim)
    for extra in (rate_limit.get("additional_rate_limits") or []):
        lim = window_to_limit(extra, "Limit")
        if lim:
            limits.append(lim)

    # Credits
    credits_val = None
    credits_obj = data.get("credits") or {}
    if isinstance(credits_obj, dict) and credits_obj.get("has_credits"):
        try:
            credits_val = round(float(credits_obj["balance"]))
        except Exception:
            pass

    return {
        "ok": True,
        "limits": limits,
        "credits": credits_val,
    }
