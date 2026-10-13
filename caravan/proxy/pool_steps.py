"""Which row of a pool serves a request — chosen at admission; a stream never
changes its row.

A pool is an ordered list of rows (caravan/common/cloud_pools.py): an account
with one model, a local model, or a row nothing is cabled to yet, which never
serves. A subscription model's levels are the model's own, the same in every
pool (caravan/common/model_levels.py). The first step that is fit now serves,
always — the pool goes back up the chain as soon as an earlier step is fit
again (the operator, 2026-10-10: a paid step works only while the ones before
it cannot), and nobody picks a step by hand (2026-10-11: the order the
operator set is the only one). A step is not fit while it is switched off;
while its model is closed by its schedule (caravan/common/model_schedules.py:
the owner, 2026-10-12, a schedule is the model's, the same in every pool);
while its account has no sign-in or its provider no longer lists the model;
while one of its limit windows is down to the step's stop level; and for a
while after its provider refused it for its limit (429), its money (402) or
its sign-in (401). Below its switch level a step is fit but gives way: the
pool takes the first step that is fit and above its own switch level, and this
one only when there is none (the operator, 2026-10-11:
caravan/common/usage_reserve.py). Errors that are not about limits belong to
the 🛟 backup node (the operator, 2026-10-10): the pool does not move for them.

State belongs to the proxy: fresh limit readings, refusals and a bounded
journal of switches. The controller edits the chain and draws the decisions.
"""
import json
import threading
import time

from caravan.common.caravan_zone import CaravanZone
from caravan.common.cloud_sources import CloudSources
from caravan.common.model_levels import ModelLevels
from caravan.common.model_schedules import ModelKey, ModelSchedules
from caravan.common.request_kind import is_chat_request
from caravan.common.usage_reserve import UsageReserve
from caravan.common.subscription_resets import SubscriptionResetJournal
from caravan.proxy.capacity import output_has_capacity
from caravan.proxy.config import current_config
from caravan.proxy.events import write_proxy_event
from caravan.proxy.cloud_auth import load_cloud_account, provider_secret_present
from caravan.proxy.output_health import output_health
from caravan.proxy.outputs import router_output
from caravan.proxy.paths import MODEL_CATALOG_FILE, SUBSCRIPTION_RESETS_FILE
from caravan.proxy.subscription_usage import SubscriptionUsage, UsagePage, subscription_usage
from caravan.proxy.translate import is_responses_request


class OwnAnswer:
    """An answer the proxy gives itself, read by the handler exactly as it
    reads a provider's: a status, headers and a body read in pieces."""

    status = 503
    reason = "Service Unavailable"
    #: What the journal and the board call this answer (proxy errorKind).
    KIND = ""
    message = ""
    body = b""
    _headers = []
    _offset = 0

    def getheaders(self):
        return list(self._headers)

    def getheader(self, name, default=None):
        return next((value for key, value in self._headers if key.lower() == str(name).lower()), default)

    def read(self, amount=None):
        end = len(self.body) if amount is None or amount < 0 else self._offset + amount
        chunk = self.body[self._offset:end]
        self._offset += len(chunk)
        return chunk

    def readline(self, limit=-1):
        rest = self.body[self._offset:]
        cut = rest.find(b"\n") + 1 or len(rest)
        if limit is not None and limit >= 0:
            cut = min(cut, limit)
        chunk = rest[:cut]
        self._offset += len(chunk)
        return chunk


class PoolRefusal(OwnAnswer):
    """The pool's own answer when no step is fit: 429 when every step is held
    by a limit (its own switch level included), 503 otherwise. Its words name
    the pool and each step's reason: a refusal the provider never gave must not
    be read as the provider's. Retry-After is the first moment a step is fit
    again — a limit's reset or a schedule's opening. A pool whose every step is
    closed by its schedule is `closed`, and says when it opens (the owner,
    2026-10-12: a client is told 503 and the time the model opens). A pool
    none of whose rows does this kind of work — a recording sent to a pool of
    subscriptions — is `unsupported`: 400, the caller's to fix, never a wait
    (1.3.501)."""

    KIND = "pool_unavailable"
    #: The kinds a pool's own refusal is recorded under now. Such a refusal names
    #: a step's account only when one was asked first and refused.
    POOL_KINDS = ("pool_unavailable", "pool_context_required")
    #: The kinds the caravan's own refusals have been recorded under — the board
    #: counts them apart from the providers' (caravan/admin/cloud_api.py). The
    #: last three are the names before pools of steps (1.3.462), still in the
    #: day of logs the board reads.
    OWN_KINDS = POOL_KINDS + ("usage_reserve", "subscription_pool_unavailable", "subscription_pool_context_required")
    LIMITS = ("reserve", "quota", "payment", "disabled")

    def __init__(self, pool, steps, now, status=None, message=None, zone=None, path=""):
        self.verdict = {"poolId": pool["id"], "steps": steps}
        resets = [s["resetAt"] for s in steps if s.get("resetAt") and s["resetAt"] > now]
        opens = [s["opensAt"] for s in steps if s.get("opensAt") and s["opensAt"] > now]
        self.path = str(path or "").split("?", 1)[0]
        self.unsupported = bool(steps) and all(s.get("reason") == "format_unsupported" for s in steps)
        self.status = status or (429 if steps and all(s.get("reason") in self.LIMITS for s in steps)
                                 else 400 if self.unsupported else 503)
        self.reason = {400: "Bad Request", 429: "Too Many Requests", 503: "Service Unavailable"}[self.status]
        self.retry_after = max(1, int(min(resets + opens) - now)) if resets + opens else 30
        self.closed = bool(steps) and all(s.get("reason") == "closed" for s in steps)
        self.opens_at = min(opens) if opens else None
        # When it opens, in the caravan's own time with its offset: read right in any zone.
        self.opens_text = (zone or CaravanZone.current()).text(self.opens_at) if self.opens_at else ""
        # A pool with no step in it says so: "no step fits: " with nothing
        # after it named no cause.
        self.message = message or ("Pool " + pool["name"] + " has no step: add one on the board"
                                   if not steps else
                                   "Pool " + pool["name"] + " has no step that fits now: " + "; ".join(
                                       f"{s['stepId']} ({s.get('reason', 'unknown')})" for s in steps))
        self.body = json.dumps({"error": {"type": self.KIND, "message": self.message,
                                          "pool_id": pool["id"], "steps": steps,
                                          "resets_at": min(resets) if resets else None,
                                          "opens_at": self.opens_at}}).encode("utf-8")
        self._headers = [("Content-Type", "application/json"), ("Content-Length", str(len(self.body)))]
        if self.status in (429, 503):
            self._headers.append(("Retry-After", str(self.retry_after)))
        self._offset = 0


class PoolContextRefusal(PoolRefusal):
    KIND = "pool_context_required"

    def __init__(self, pool, now):
        super().__init__(pool, [], now, status=400, message=
                         "A pool with more than one step needs the full conversation history in input; "
                         "previous_response_id belongs to one account and cannot be switched safely.")


class PoolSteps:
    FRESH_SEC = 300
    FAILED_REFRESH_SEC = 30
    #: How long a step's account rests after its provider refused it, when the
    #: answer names no time: a sign-in refused (401) or no money left (402) is
    #: not over in seconds, and asking every request would only repeat it.
    REST_SEC = {401: 300, 402: 300}
    REASON = {401: "auth_rejected", 402: "payment", 429: "quota"}
    #: The providers a Responses request may go to as it is: the subscription
    #: speaks it, and so does api.openai.com. The rest take chat requests only.
    RESPONSES_TYPES = ("openai",)

    def __init__(self, usage=subscription_usage, fetch=UsagePage.fetch,
                 account=load_cloud_account, credential=provider_secret_present, clock=time.time,
                 listed=None, event=None, resets=None, local=None, dead=None, free=None, zone=None):
        self.usage, self.fetch, self.account = usage, fetch, account
        self.credential, self.clock = credential, clock
        # The zone the models' schedules are written in (caravan/common/caravan_zone.py).
        self.zone = zone or CaravanZone.current()
        self.listed = listed or self._listed
        self.event = event or self._event
        # A local row's cell: what the controller names it (its router outputs),
        # whether traffic found it dead lately, whether it has a free slot now.
        self.local = local or self._local
        self.dead = dead or output_health.is_dead
        self.free = free or (lambda out: output_has_capacity(out, current_config().get("policy") or {}))
        self.resets = resets or SubscriptionResetJournal(SUBSCRIPTION_RESETS_FILE)
        self._resets_seen = {}
        self._lock = threading.RLock()
        self._snapshot_lock = threading.Lock()
        self._selected, self._states, self._tried, self._observed, self._blocked = {}, {}, {}, {}, {}
        self._events = []

    @staticmethod
    def _event(event):
        write_proxy_event("pool_switch", **event)

    @staticmethod
    def _local(output_id):
        """A local model's output as the controller last wrote it — the address
        of its cell or engine — or None when no router names it any more."""
        return router_output(output_id, current_config())

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

    def _closed(self, step, row, now, schedules):
        """The row as closed by its model's schedule, with when it opens — or None while the model
        may serve. A closed model is not asked at all: no connection is tried, no account spent."""
        closed = schedules.closed(ModelKey.of_row(step), now, self.zone)
        return None if closed is None else {**row, "reason": "closed", "opensAt": closed["opensAt"]}

    def _candidate(self, step, provider, responses, excluded, now, levels, schedules, chat=True):
        """Why the step is fit or not now, as one row of the pool's state. `chat` is whether the
        request is a chat's: a subscription does nothing else (request_kind.is_chat_request)."""
        if step.get("kind", "account") == "open":
            return {"stepId": step["id"], "kind": "open", "eligible": False, "reason": "not_connected"}
        if step.get("kind", "account") == "output":
            return self._local_candidate(step, excluded, now, schedules)
        row = {"stepId": step["id"], "kind": "account", "accountId": step["accountId"], "model": step["model"],
               "eligible": False}
        if not step.get("enabled", True):
            return {**row, "reason": "disabled"}
        closed = self._closed(step, row, now, schedules)
        if closed:
            return closed
        if f"row:{step['id']}" in excluded:
            # This request tried the row and it failed before its first byte (an
            # error, a timeout, no connection): the next row is asked.
            return {**row, "reason": "tried"}
        if not provider or not self.credential(provider):
            return {**row, "reason": "credential_missing"}
        subscription = CloudSources.is_subscription(provider)
        if responses and not subscription and str(provider.get("type") or "") not in self.RESPONSES_TYPES:
            return {**row, "reason": "format_unsupported"}
        if subscription and not chat:
            return {**row, "reason": "format_unsupported"}
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
        if self.listed(provider.get("credentialAccountId") or provider["accountId"], step["model"]) is False:
            return {**row, "reason": "model_unavailable"}
        if not subscription:
            # Only a subscription states its limit windows; another provider's
            # step is held only by its refusals (above).
            return {**row, "eligible": True, "reason": "ready"}
        windows, at, error = self._reading(provider, now)
        row.update({"windows": windows, "readAt": at})
        if error:
            return {**row, "reason": error}
        stop, switch = (UsageReserve(pair) for pair in levels.of(step["accountId"], step["model"]))
        if any(w["seconds"] in {**stop.by_seconds, **switch.by_seconds} and not w.get("resetAt") for w in windows):
            return {**row, "reason": "usage_unknown"}
        hit = stop.verdict(windows, now)
        if hit:
            return {**row, "reason": "reserve", "reserve": hit, "resetAt": hit["resetAt"]}
        exhausted = [w for w in windows if w.get("usedPct", 0) >= 100]
        if exhausted:
            return {**row, "reason": "quota", "resetAt": max((w.get("resetAt") or now + 30) for w in exhausted)}
        given = switch.verdict(windows, now)
        if given:
            # Fit, but giving way (resolve): served only when no step above its own switch level is fit.
            return {**row, "eligible": True, "reason": "switch", "reserve": given, "resetAt": given["resetAt"]}
        return {**row, "eligible": True, "reason": "ready"}

    def _local_candidate(self, step, excluded, now, schedules):
        """Why a local model's row is fit or not now. A cell closed by its schedule
        or found dead by traffic lately is not asked; a cell with every slot taken
        gives way — the pool takes a later row that is ready, and this one only when
        none is, the request then waiting in the cell's queue (the owner, 2026-10-12:
        a full queue sends the request on)."""
        row = {"stepId": step["id"], "kind": "output", "output": step["output"], "eligible": False}
        if not step.get("enabled", True):
            return {**row, "reason": "disabled"}
        closed = self._closed(step, row, now, schedules)
        if closed:
            return closed
        if f"row:{step['id']}" in excluded:
            return {**row, "reason": "tried"}
        out = self.local(step["output"])
        if not out:
            return {**row, "reason": "output_missing"}
        if self.dead(step["output"]):
            return {**row, "reason": "unavailable"}
        row["target"] = out
        if not self.free(out):
            return {**row, "eligible": True, "reason": "busy"}
        return {**row, "eligible": True, "reason": "ready"}

    def can_go_on(self, source, excluded=(), body=None, path=""):
        """Whether a row of the pool could still serve this request — asked
        before leaving a failed row for the next one: with none left, the
        client is told the failure it met, not that no row fits. Nothing is
        recorded: the next resolve decides, and says so."""
        pool = (source or {}).get("pool")
        if not pool:
            return False
        responses = is_responses_request(path, body) if (path or body) else False
        chat = is_chat_request(path) if path else True
        levels = ModelLevels({"levels": source.get("levels")})
        schedules = ModelSchedules({"schedules": source.get("schedules")})
        steps = pool.get("steps") or []
        with self._lock:
            providers = {s["id"]: self.account(s["accountId"]) for s in steps if s.get("kind", "account") == "account"}
            now = self.clock()
            return any(self._candidate(s, providers.get(s["id"]), responses, set(excluded), now, levels, schedules,
                                       chat)["eligible"] for s in steps)

    def resolve(self, source, body=None, excluded=(), path=""):
        """(the provider of the step that serves, None), or (source, refusal).
        A source without a pool — an account routed to directly — passes
        through. The caller pins the returned provider for the stream."""
        pool = (source or {}).get("pool")
        if not pool:
            return source, None
        now = self.clock()
        try:
            payload = json.loads(body) if body else {}
        except (ValueError, TypeError):
            payload = {}
        steps = pool.get("steps") or []
        if (isinstance(payload, dict) and payload.get("previous_response_id")
                and sum(1 for s in steps if s.get("enabled", True) and s.get("kind", "account") != "open") > 1):
            return source, PoolContextRefusal(pool, now)
        responses = is_responses_request(path, body) if (path or body) else False
        # A path not said is a chat's, as every caller sent before the pools took forms (1.3.501).
        chat = is_chat_request(path) if path else True
        event = None
        levels = ModelLevels({"levels": source.get("levels")})
        schedules = ModelSchedules({"schedules": source.get("schedules")})
        with self._lock:
            providers = {s["id"]: self.account(s["accountId"]) for s in steps if s.get("kind", "account") == "account"}
            rows = [self._candidate(s, providers.get(s["id"]), responses, set(excluded), now, levels, schedules, chat)
                    for s in steps]
            # The first step fit and above its switch level; with none, the first one giving way.
            fit = ([r["stepId"] for r in rows if r["eligible"] and r["reason"] == "ready"]
                   + [r["stepId"] for r in rows if r["eligible"] and r["reason"] != "ready"])
            previous = self._selected.get(pool["id"])
            chosen = fit[0] if fit else None
            reasons = [{"stepId": r["stepId"], "reason": r["reason"]} for r in rows if r["reason"] != "ready"]
            with self._snapshot_lock:
                # The state the board reads names a cell by its output, not by its address.
                kept = [{k: v for k, v in r.items() if k != "target"} for r in rows]
                self._states[pool["id"]] = {"selectedStepId": chosen, "steps": kept, "decidedAt": now}
                if chosen != previous:
                    event = {"poolId": pool["id"], "from": previous, "to": chosen, "at": now, "reasons": reasons}
                    self._events = (self._events + [event])[-50:]
                    self._selected[pool["id"]] = chosen
            if not chosen:
                result = source, PoolRefusal(pool, [{k: v for k, v in r.items() if k != "target"} for r in rows], now,
                                             zone=self.zone, path=path)
            else:
                step = next(s for s in steps if s["id"] == chosen)
                if step.get("kind", "account") == "output":
                    # A local model: the handler sends this leg to the cell as a
                    # local route goes — its queue, its connection.
                    target = next(r["target"] for r in rows if r["stepId"] == chosen)
                    provider = {"id": source["id"], "poolId": pool["id"], "poolStepId": chosen, "localOutput": target,
                                "model": "", "modelMode": "passthrough", "contextLength": source.get("contextLength")}
                else:
                    provider = {**providers[chosen], "id": source["id"], "poolId": pool["id"], "poolStepId": chosen,
                                "model": step["model"], "modelMode": "rewrite", "contextLength": source.get("contextLength")}
                result = provider, None
        # Events inspect active requests; emit after releasing the selection
        # lock, so state export and request bookkeeping cannot invert locks.
        if event:
            self.event(event)
        return result

    def failed(self, provider, status, headers=None):
        """The step's provider refused it for a limit before any output: its
        account rests, and the request goes on to the pool's next step. True
        for such a refusal; False for any other answer, which stays the step's
        (or the 🛟 backup node's)."""
        if not provider.get("poolId") or status not in self.REASON:
            return False
        owner = provider.get("usageAccountId") or provider["accountId"]
        low = {str(k).lower(): v for k, v in (headers or {}).items()}
        try:
            delay = max(1, min(3600, int(low.get("retry-after") or self.REST_SEC.get(status, 30))))
        except (TypeError, ValueError):
            delay = self.REST_SEC.get(status, 30)
        with self._lock:
            now = self.clock()
            self._blocked[owner] = {"reason": self.REASON[status], "at": now, "until": now + delay}
        return True

    def snapshot(self):
        with self._snapshot_lock:
            return {"pools": json.loads(json.dumps(self._states)), "events": list(self._events)}

    def clear(self):
        """Forget every choice, refusal and try — a fresh proxy's state."""
        with self._lock, self._snapshot_lock:
            for kept in (self._selected, self._states, self._tried, self._observed, self._blocked, self._resets_seen):
                kept.clear()
            self._events = []


pool_steps = PoolSteps()
