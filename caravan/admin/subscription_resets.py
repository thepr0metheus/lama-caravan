"""Banked OpenAI resets: read-only listing; explicit, idempotent consumption.

HTTP contract follows openai/codex's backend-client/client/rate_limit_resets.rs.
No routing policy consumes credits. A timed-out attempt keeps its request id
across browser/controller restarts and must be resolved before another spend.
"""
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime

from caravan.common.cloud_sources import CloudSources
from caravan.common.errors import AppError
from caravan.common.subscription_resets import SubscriptionResetJournal


class SubscriptionResetDesk:
    URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
    OUTCOMES = {"reset", "already_redeemed", "nothing_to_reset", "no_credit"}

    def __init__(self, sources=None, auth=None, request=None, journal=None, clock=time.time):
        from caravan.admin.cloud import load_cloud_data, load_provider_secrets
        from caravan.admin.cloud_api import _subscription_auth_headers
        from caravan.admin.paths import SUBSCRIPTION_RESETS_FILE
        self.sources = sources or (lambda: CloudSources(load_cloud_data(), load_provider_secrets()))
        self.auth, self.request = auth or _subscription_auth_headers, request or self._request
        self.journal = journal or SubscriptionResetJournal(SUBSCRIPTION_RESETS_FILE)
        self.clock = clock

    def _account(self, account_id):
        sources = self.sources()
        account = sources.canonical(account_id)
        if not sources.is_subscription(account):
            raise AppError("an individual ChatGPT subscription is required", 400)
        return account, sources.quota_owner(account_id)["id"]

    def _request(self, account, method, payload=None):
        token, account_id = self.auth(account)
        headers = {"Authorization": "Bearer " + token, "chatgpt-account-id": account_id,
                   "originator": "pi", "Accept": "application/json"}
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.URL + ("/consume" if method == "POST" else ""),
                                     headers=headers, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise AppError(f"ChatGPT reset endpoint: HTTP {exc.code}", 502)
        except (OSError, ValueError) as exc:
            raise AppError(f"ChatGPT reset endpoint unavailable: {exc}", 502)

    def list(self, account_id):
        account, owner = self._account(account_id)
        payload = self.request(account, "GET")
        if not isinstance(payload, dict):
            raise AppError("ChatGPT reset details are unavailable", 502)
        rows = payload.get("credits")
        if not isinstance(rows, list) or not isinstance(payload.get("available_count"), int):
            raise AppError("ChatGPT reset details are unavailable", 502)
        credits = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                raise AppError("ChatGPT returned an invalid reset credit", 502)
            expired = False
            if row.get("expires_at"):
                try:
                    expired = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")).timestamp() <= self.clock()
                except (ValueError, TypeError):
                    raise AppError("ChatGPT returned an invalid reset expiry", 502)
            credits.append({"id": row["id"], "resetType": row.get("reset_type"),
                            "status": row.get("status"), "expiresAt": row.get("expires_at"),
                            "title": row.get("title"), "description": row.get("description"),
                            "usable": row.get("status") == "available" and row.get("reset_type") == "codex_rate_limits" and not expired})
        attempts = self.journal.read().get("attempts", {})
        pending = [{"idempotencyKey": key, "creditId": row["creditId"]} for key, row in attempts.items()
                   if row["accountId"] == owner and not row.get("outcome")]
        return {"ok": True, "accountId": account["id"], "usageAccountId": owner,
                "availableCount": payload["available_count"], "credits": credits,
                "pending": pending, "readAt": self.clock()}

    def consume(self, account_id, credit_id, key, confirmed=False):
        if confirmed is not True:
            raise AppError("explicit reset confirmation is required", 400)
        try:
            if str(uuid.UUID(str(key))) != key:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise AppError("idempotencyKey must be a UUID", 400)
        if not isinstance(credit_id, str) or not credit_id or len(credit_id) > 256:
            raise AppError("creditId is required", 400)
        account, owner = self._account(account_id)
        with self.journal.locked() as data:
            attempts = data["attempts"]
            old = attempts.get(key)
            if old and (old["accountId"] != owner or old["creditId"] != credit_id):
                raise AppError("this request id belongs to another reset", 409)
            if old and old.get("outcome"):
                return {"ok": True, "outcome": old["outcome"], "idempotencyKey": key}
            if not old:
                if any(row["accountId"] == owner and not row.get("outcome") for row in attempts.values()):
                    raise AppError("resolve the pending reset using its original request id first", 409)
                credits = self.list(account_id)["credits"]
                if not any(row["id"] == credit_id and row["usable"] for row in credits):
                    raise AppError("the selected reset is no longer available", 409)
                attempts[key] = {"accountId": owner, "creditId": credit_id, "at": self.clock()}
                self.journal.write(data)  # record BEFORE any possible spend
            result = self.request(account, "POST", {"credit_id": credit_id, "redeem_request_id": key})
            outcome = result.get("code") if isinstance(result, dict) else None
            if outcome not in self.OUTCOMES:
                raise AppError("unknown reset outcome; retry with the same request id", 502)
            attempts[key]["outcome"] = outcome
            if outcome in ("reset", "already_redeemed"):
                data["resets"][owner] = self.clock()
            self.journal.write(data)
            return {"ok": True, "outcome": outcome, "idempotencyKey": key}
