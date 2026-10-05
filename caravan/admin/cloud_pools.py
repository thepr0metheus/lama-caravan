"""Subscription pools: policy/configuration, aliases and migration of models.

Model blocks keep their ids when adopted by a pool, so ports, cables and client
configuration continue to name the same models. No credential lives on a pool.
"""
import json
import re
import time

from caravan.common.cloud_sources import CloudSources
from caravan.common.errors import AppError


class CloudPoolDesk:
    def __init__(self, load=None, save=None, state_file=None, clock=time.time, vault=None):
        from caravan.admin.cloud import load_cloud_data, save_cloud_data
        from caravan.admin.paths import AGENT_PROXY_STATE_FILE, PROVIDER_SECRETS_FILE
        from caravan.common.credential_vault import CredentialVault
        self.load, self.save = load or load_cloud_data, save or save_cloud_data
        self.state_file, self.clock = state_file or AGENT_PROXY_STATE_FILE, clock
        self.vault = vault or CredentialVault(PROVIDER_SECRETS_FILE)

    def normalize(self, supplied, data):
        if not isinstance(supplied, dict):
            raise AppError("pool must be an object", 400)
        pid = str(supplied.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", pid) or pid in CloudSources(data).accounts:
            raise AppError("pool.id must be unique, 1-48 letters, digits, _ or -", 400)
        mode = supplied.get("mode", "auto")
        if mode not in ("auto", "manual"):
            raise AppError("pool.mode must be auto or manual", 400)
        sources, members, seen = CloudSources(data), [], set()
        raw = supplied.get("members")
        if not isinstance(raw, list) or not raw:
            raise AppError("a pool needs at least one subscription account", 400)
        for member in raw:
            if not isinstance(member, dict):
                raise AppError("pool member must be an object", 400)
            aid = str(member.get("accountId") or "")
            if aid in seen or not sources.is_subscription(sources.canonical(aid)):
                raise AppError("pool members must be distinct existing subscription accounts", 400)
            seen.add(aid)
            pending = bool(member.get("pendingLogin", False))
            members.append({"accountId": aid, "enabled": False if pending else bool(member.get("enabled", True)),
                            "automatic": bool(member.get("automatic", True)),
                            **({"pendingLogin": True} if pending else {})})
        manual = str(supplied.get("manualAccountId") or "")
        if manual and manual not in seen:
            raise AppError("manualAccountId must be a pool member", 400)
        if mode == "manual" and not manual:
            raise AppError("manual mode needs manualAccountId", 400)
        try:
            until = int(supplied.get("manualUntil") or 0)
        except (TypeError, ValueError):
            raise AppError("manualUntil must be a Unix timestamp", 400)
        return {"id": pid, "name": str(supplied.get("name") or pid).strip(), "members": members,
                "mode": mode, "manualAccountId": manual, "manualUntil": max(0, until),
                "returnToPrimary": bool(supplied.get("returnToPrimary", False))}

    def upsert(self, supplied, adopt_account_id=None):
        data = self.load()
        if not isinstance(supplied, dict):
            raise AppError("pool must be an object", 400)
        old = next((p for p in data.get("pools", []) if p["id"] == supplied.get("id")), {})
        pool = self.normalize({**old, **supplied}, data)
        moved = 0
        if adopt_account_id:
            if adopt_account_id not in {m["accountId"] for m in pool["members"]}:
                raise AppError("the adopted account must belong to the pool", 400)
            for block in data["blocks"]:
                if block.get("accountId") == adopt_account_id:
                    block.setdefault("usageOriginAccountId", adopt_account_id)
                    block["accountId"] = pool["id"]
                    moved += 1
        data["pools"] = [p for p in data.get("pools", []) if p["id"] != pool["id"]] + [pool]
        self.save(data)
        return {"pool": pool, "adoptedModels": moved}

    def connect_account(self, pool_id, supplied):
        """Create a real subscription and reserve its place, disabled until login."""
        from caravan.admin.cloud import normalize_cloud_account
        data = self.load()
        sources = CloudSources(data)
        pool = sources.pools.get(pool_id)
        if not pool:
            raise AppError("unknown subscription pool", 404)
        account = normalize_cloud_account(supplied)
        if account["id"] in sources.accounts or account["id"] in sources.pools:
            raise AppError("the new subscription needs a unique id", 409)
        if not sources.is_subscription(account) or account.get("testAliasOf") or account.get("authMode") != "oauth":
            raise AppError("a new OAuth subscription is required", 400)
        data["accounts"].append(account)
        pool["members"].append({"accountId": account["id"], "enabled": False,
                                "automatic": True, "pendingLogin": True})
        self.save(data)
        return account

    def complete_login(self, account_id):
        """Enable only places reserved by this creation flow; preserve manual exclusions."""
        data, changed = self.load(), []
        for pool in data.get("pools", []):
            for member in pool["members"]:
                if member["accountId"] == account_id and member.get("pendingLogin"):
                    member.pop("pendingLogin")
                    member["enabled"] = True
                    changed.append(pool["id"])
        if changed:
            self.save(data)
        return list(dict.fromkeys(changed))

    def clone_test(self, source_id):
        data = self.load()
        sources = CloudSources(data)
        owner = sources.canonical(source_id)
        if not sources.is_subscription(owner):
            raise AppError("test aliases require an existing ChatGPT subscription", 400)
        existing = next((a for a in data["accounts"] if a.get("testAliasOf") == owner["id"]), None)
        if existing:
            return existing
        stem = owner["id"][:40] + "-test"
        aid, number = stem, 2
        while aid in sources.accounts or aid in sources.pools:
            aid, number = f"{stem}-{number}", number + 1
        alias = {**owner, "id": aid, "name": owner.get("name", owner["id"]) + " · TEST",
                 "testAliasOf": owner["id"]}
        alias.pop("usageReserve", None)  # the quota and its reserve have one owner
        data["accounts"].append(alias)
        self.save(data)
        return alias

    def delete(self, pool_id):
        data = self.load()
        if any(b.get("accountId") == pool_id for b in data["blocks"]):
            raise AppError("move or remove the pool's model blocks before deleting it", 409)
        data["pools"] = [p for p in data.get("pools", []) if p["id"] != pool_id]
        self.save(data)

    def remove_account(self, account_id):
        """Delete one registration and detach it from nonempty pools.

        Matching OpenAI identities share quota, not the registration's lifetime
        or its credential. Pool model blocks keep their ids, ports and cables.
        Legacy aliases remain dependent and must be removed before their owner.
        """
        account_id = str(account_id or "").strip()
        data = self.load()
        if any(a.get("testAliasOf") == account_id for a in data["accounts"]):
            raise AppError("delete this account's legacy test aliases first", 409)
        affected = [p for p in data.get("pools", [])
                    if any(m.get("accountId") == account_id for m in p.get("members", []))]
        if any(not any(m.get("accountId") != account_id for m in p["members"]) for p in affected):
            raise AppError("connect another subscription or remove the pool before deleting its last account", 409)
        for pool in affected:
            pool["members"] = [m for m in pool["members"] if m.get("accountId") != account_id]
            if pool.get("manualAccountId") == account_id:
                pool.update(mode="auto", manualAccountId="", manualUntil=0)
        data["accounts"] = [a for a in data["accounts"] if a.get("id") != account_id]
        data["blocks"] = [b for b in data["blocks"] if b.get("accountId") != account_id]
        self.save(data)
        self.vault.delete(account_id)

    def runtime(self):
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
            rows = state.get("subscriptionPools") or {}
            if self.clock() - float(state.get("time") or 0) > 30:
                return {"available": False, "pools": {}}
            return {"available": True, "pools": rows.get("pools", {}), "events": rows.get("events", [])}
        except (OSError, ValueError, TypeError):
            return {"available": False, "pools": {}}
