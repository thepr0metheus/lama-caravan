"""Cloud identities and virtual sources, shared by the board and the proxy.

A pool owns routing policy, never credentials. A test alias owns a label,
never another refresh token or quota. Keeping those distinctions here prevents
the UI and the data plane from inventing different meanings for a duplicate.
"""
import base64
import json


class CloudSources:
    SUBSCRIPTION = "openai-subscription"

    def __init__(self, data, secrets=None):
        self.data = data
        self.secrets = secrets or {}
        self.accounts = {a["id"]: a for a in data.get("accounts", []) if isinstance(a, dict) and a.get("id")}
        self.pools = {p["id"]: p for p in data.get("pools", []) if isinstance(p, dict) and p.get("id")}

    @classmethod
    def is_subscription(cls, account):
        return bool(account and (account.get("accountType") == cls.SUBSCRIPTION
                                or "chatgpt.com" in str(account.get("baseUrl") or "")))

    def canonical(self, account_id):
        account = self.accounts.get(str(account_id))
        if account and account.get("testAliasOf"):
            owner = self.accounts.get(account["testAliasOf"])
            return owner if owner and not owner.get("testAliasOf") else None
        return account

    @staticmethod
    def quota_identity(token):
        """Compare stored token claims for quota deduplication, not OAuth
        verification. This never authorizes a request or trusts client input."""
        try:
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return str((claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id") or "")
        except (ValueError, TypeError, IndexError):
            return ""

    def quota_owner(self, account_id):
        account = self.canonical(account_id)
        if not account:
            return None
        def identity(aid):
            entry = self.secrets.get(aid)
            return self.quota_identity((entry.get("oauth") or {}).get("accessToken") or "") if isinstance(entry, dict) else ""
        key = identity(account["id"])
        if key:
            for candidate in sorted(self.accounts.values(), key=lambda a: a["id"]):
                if not candidate.get("testAliasOf") and self.is_subscription(candidate) and identity(candidate["id"]) == key:
                    return candidate
        return account

    def source(self, source_id):
        account = self.accounts.get(str(source_id))
        if account:
            owner = self.canonical(source_id)
            if not owner:
                return None
            quota = self.quota_owner(source_id)
            return {**owner, "usageReserve": quota.get("usageReserve") or {}, "id": account["id"], "name": account.get("name") or account["id"],
                    **({"testAliasOf": owner["id"]} if account.get("testAliasOf") else {}),
                    "credentialAccountId": owner["id"], "usageAccountId": quota["id"]}
        pool = self.pools.get(str(source_id))
        if pool:
            return {"id": pool["id"], "name": pool["name"], "type": self.SUBSCRIPTION,
                    "accountType": self.SUBSCRIPTION, "baseUrl": "https://chatgpt.com/backend-api",
                    "authMode": "oauth", "pool": pool, "isPool": True}
        return None

    def all(self):
        return [self.source(i) for i in (*self.accounts, *self.pools) if self.source(i)]

    def members(self, pool):
        return [(m, self.source(m.get("accountId"))) for m in pool.get("members", [])]

    @staticmethod
    def common_models(lists):
        """Only models every supplied catalogue lists; a failed catalogue is
        the caller's error, not an empty list to be discarded here."""
        if not lists:
            return []
        shared = set.intersection(*({m["id"] for m in rows} for rows in lists))
        return [m for m in lists[0] if m["id"] in shared]
