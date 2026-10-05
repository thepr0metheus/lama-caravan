"""Admission-time subscription selection. Streams never change their account.

State belongs to the proxy: selected members, fresh quota readings, cooldowns
and a bounded decision journal. The controller only edits policy and displays
the exported decisions. A test alias resolves to the original quota owner.
"""
import json
import threading
import time

from caravan.common.usage_reserve import UsageReserve
from caravan.common.subscription_resets import SubscriptionResetJournal
from caravan.proxy.events import write_proxy_event
from caravan.proxy.cloud_auth import load_cloud_account, provider_secret_present
from caravan.proxy.paths import MODEL_CATALOG_FILE, SUBSCRIPTION_RESETS_FILE
from caravan.proxy.subscription_usage import ReserveGate, ReserveRefusal, SubscriptionUsage, subscription_usage


class PoolRefusal(ReserveRefusal):
    KIND = "subscription_pool_unavailable"

    def __init__(self, pool, members, now, status=None, message=None):
        self.verdict = {"poolId": pool["id"], "members": members}
        resets = [m["resetAt"] for m in members if m.get("resetAt") and m["resetAt"] > now]
        self.status = status or (429 if members and all(m.get("reason") in ("reserve", "quota", "disabled", "manual_only", "not_selected") for m in members) else 503)
        self.reason = {400: "Bad Request", 429: "Too Many Requests", 503: "Service Unavailable"}[self.status]
        self.retry_after = max(1, int(min(resets) - now)) if resets else 30
        self.message = message or "Subscription pool " + pool["name"] + " has no eligible account: " + "; ".join(
            m["accountId"] + " (" + m.get("reason", "unknown") + ")" for m in members)
        self.body = json.dumps({"error": {"type": self.KIND, "message": self.message,
                                          "pool_id": pool["id"], "members": members,
                                          "resets_at": min(resets) if resets else None}}).encode("utf-8")
        self._headers = [("Content-Type", "application/json"), ("Content-Length", str(len(self.body)))]
        if self.status in (429, 503):
            self._headers.append(("Retry-After", str(self.retry_after)))
        self._offset = 0


class PoolContextRefusal(PoolRefusal):
    KIND = "subscription_pool_context_required"

    def __init__(self, pool, now):
        super().__init__(pool, [], now, status=400, message=
                         "Subscription pools require full conversation history in input; "
                         "previous_response_id belongs to one account and cannot be switched safely.")


class SubscriptionPools:
    FRESH_SEC = 300
    FAILED_REFRESH_SEC = 30

    def __init__(self, usage=subscription_usage, fetch=ReserveGate.fetch_usage_page,
                 account=load_cloud_account, credential=provider_secret_present, clock=time.time,
                 listed=None, event=None, resets=None):
        self.usage, self.fetch, self.account = usage, fetch, account
        self.credential, self.clock = credential, clock
        self.listed = listed or self._listed
        self.event = event or self._event
        self.resets = resets or SubscriptionResetJournal(SUBSCRIPTION_RESETS_FILE)
        self._resets_seen = {}
        self._lock = threading.RLock()
        self._snapshot_lock = threading.Lock()
        self._selected, self._states, self._tried, self._observed, self._blocked = {}, {}, {}, {}, {}
        self._events = []

    @staticmethod
    def _event(event):
        write_proxy_event("subscription_pool_switch", **event)

    @staticmethod
    def _listed(account_id, model):
        if not model:
            return None
        try:
            data = json.loads(MODEL_CATALOG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        entry = (data.get("accounts") or {}).get(account_id)
        if not entry or not isinstance(entry.get("models"), list):
            return None
        return any(m.get("id") == model for m in entry["models"])

    def _reading(self, provider, now):
        owner = provider.get("usageAccountId") or provider["accountId"]
        windows, at = self.usage.windows(owner), self.usage.read_at(owner)
        expired = any(w.get("resetAt") and w["resetAt"] <= now for w in windows)
        observed = self._observed.get(owner)
        reset_at = self.resets.reset_at(owner)
        if at is not None and at >= reset_at and now - at < self.FRESH_SEC and not expired:
            return windows, at, None
        if observed and observed["at"] >= reset_at and now - observed["at"] < self.FRESH_SEC and observed.get("unlimited"):
            return [], observed["at"], None
        if now - self._tried.get(owner, -float("inf")) >= self.FAILED_REFRESH_SEC:
            self._tried[owner] = now
            try:
                payload = self.fetch(provider)
            except Exception:
                payload = None
            fresh = SubscriptionUsage.windows_from_usage_page(payload)
            rate = payload.get("rate_limit") if isinstance(payload, dict) else None
            if fresh:
                self.usage.keep(owner, fresh, now)
                return fresh, now, None
            if (isinstance(rate, dict) and rate.get("allowed") is True and not rate.get("limit_reached")
                    and all(rate.get(slot) is None for slot in ("primary_window", "secondary_window"))):
                self._observed[owner] = {"at": now, "unlimited": True}
                return [], now, None
        return windows, at, "usage_unknown"

    def _candidate(self, member, provider, model, auto, excluded, now):
        row = {"accountId": member["accountId"], "eligible": False}
        if not member.get("enabled", True):
            return {**row, "reason": "disabled"}
        if auto and not member.get("automatic", True):
            return {**row, "reason": "manual_only"}
        if not provider or not self.credential(provider):
            return {**row, "reason": "credential_missing"}
        owner = provider.get("usageAccountId") or provider["accountId"]
        row["usageAccountId"] = owner
        reset_at = self.resets.reset_at(owner)
        if reset_at > self._resets_seen.get(owner, 0):
            self._resets_seen[owner] = reset_at
            blocked = self._blocked.get(owner)
            if blocked and blocked["reason"] == "quota" and blocked["at"] <= reset_at:
                self._blocked.pop(owner)
            if self._tried.get(owner, 0) < reset_at:
                self._tried.pop(owner, None)
        if owner in excluded:
            return {**row, "reason": "upstream_refused"}
        blocked = self._blocked.get(owner)
        if blocked and blocked["until"] > now:
            return {**row, "reason": blocked["reason"], "resetAt": blocked["until"]}
        if self.listed(provider.get("credentialAccountId") or provider["accountId"], model) is False:
            return {**row, "reason": "model_unavailable"}
        windows, at, error = self._reading(provider, now)
        row.update({"windows": windows, "readAt": at})
        if error:
            return {**row, "reason": error}
        reserve = UsageReserve(provider.get("usageReserve"))
        if any(w["seconds"] in reserve.by_seconds and not w.get("resetAt") for w in windows):
            return {**row, "reason": "usage_unknown"}
        hit = reserve.verdict(windows, now)
        if hit:
            return {**row, "reason": "reserve", "reserve": hit, "resetAt": hit["resetAt"]}
        exhausted = [w for w in windows if w.get("usedPct", 0) >= 100]
        if exhausted:
            return {**row, "reason": "quota", "resetAt": max((w.get("resetAt") or now + 30) for w in exhausted)}
        return {**row, "eligible": True, "reason": "ready"}

    def resolve(self, source, body=None, excluded=()):
        """Return (effective provider, optional HTTP refusal). Normal accounts
        pass through. The caller pins the returned provider for the stream."""
        pool = (source or {}).get("pool")
        if not pool:
            return source, None
        now = self.clock()
        try:
            payload = json.loads(body) if body else {}
        except (ValueError, TypeError):
            payload = {}
        if isinstance(payload, dict) and payload.get("previous_response_id"):
            return source, PoolContextRefusal(pool, now)
        model = source.get("model") if source.get("modelMode") == "rewrite" else payload.get("model")
        manual = pool.get("mode") == "manual" and (not pool.get("manualUntil") or pool["manualUntil"] > now)
        event = None
        with self._lock:
            providers = {m["accountId"]: self.account(m["accountId"]) for m in pool["members"]}
            rows = [self._candidate(m, providers[m["accountId"]], model, not manual, set(excluded), now)
                    if not manual or m["accountId"] == pool.get("manualAccountId")
                    else {"accountId": m["accountId"], "eligible": False, "reason": "not_selected"}
                    for m in pool["members"]]
            ready = [r["accountId"] for r in rows if r["eligible"]]
            previous = self._selected.get(pool["id"])
            chosen = (previous if not pool.get("returnToPrimary") and previous in ready else ready[0]) if ready else None
            reasons = [{"accountId": r["accountId"], "reason": r["reason"]} for r in rows if not r["eligible"]]
            with self._snapshot_lock:
                self._states[pool["id"]] = {"selectedAccountId": chosen, "mode": "manual" if manual else "auto",
                                           "members": rows, "decidedAt": now}
                if chosen != previous:
                    event = {"poolId": pool["id"], "from": previous, "to": chosen, "at": now,
                             "mode": "manual" if manual else "auto", "reasons": reasons}
                    self._events = (self._events + [event])[-50:]
                    self._selected[pool["id"]] = chosen
            if not chosen:
                result = source, PoolRefusal(pool, rows, now)
            else:
                provider = {**providers[chosen], "id": source["id"], "poolId": pool["id"],
                            "poolMemberId": chosen, "poolAutomatic": not manual,
                            "model": source.get("model") or "", "modelMode": source.get("modelMode") or "passthrough"}
                provider["contextLength"] = source.get("contextLength")
                result = provider, None
        # Events inspect active requests; emit after releasing the selection
        # lock, so state export and request bookkeeping cannot invert locks.
        if event:
            self.event(event)
        return result

    def failed(self, provider, status, headers=None):
        if not provider.get("poolId") or status not in (401, 429):
            return False
        owner = provider.get("usageAccountId") or provider["accountId"]
        low = {str(k).lower(): v for k, v in (headers or {}).items()}
        try:
            delay = max(1, min(3600, int(low.get("retry-after", 30))))
        except (TypeError, ValueError):
            delay = 30
        with self._lock:
            now = self.clock()
            self._blocked[owner] = {"reason": "auth_rejected" if status == 401 else "quota",
                                    "at": now, "until": now + (300 if status == 401 else delay)}
        return bool(provider.get("poolAutomatic"))

    def snapshot(self):
        with self._snapshot_lock:
            return {"pools": json.loads(json.dumps(self._states)), "events": list(self._events)}


subscription_pools = SubscriptionPools()
