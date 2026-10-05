#!/usr/bin/env python3
"""Admission, quota identity, model migration and concurrent OAuth renewal.

All quotas, time and network responses are injected. Tests never borrow the
operator's credentials or change live routing.
"""
import copy
import base64
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-pools-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
sys.path.insert(0, str(ROOT))

from caravan.admin.cloud_pools import CloudPoolDesk
from caravan.common.cloud_sources import CloudSources
from caravan.common.credential_vault import CredentialVault
from caravan.common.errors import AppError
from caravan.proxy.subscription_pool import SubscriptionPools
from caravan.proxy.subscription_usage import SubscriptionUsage


def windows(short=10, weekly=10, reset=2000):
    return [{"seconds": 18000, "usedPct": short, "resetAt": reset},
            {"seconds": 604800, "usedPct": weekly, "resetAt": reset + 1000}]


class Selection(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.usage = SubscriptionUsage()
        self.accounts = {i: {"id": i, "accountId": i, "usageAccountId": i, "credentialAccountId": i,
                             "usageReserve": {"18000": 20, "604800": 10}} for i in ("a", "b")}
        self.accounts["a-test"] = {**self.accounts["a"], "id": "a-test", "accountId": "a-test"}
        self.pool = {"id": "pool", "name": "Work", "mode": "auto", "members": [
            {"accountId": "a", "enabled": True, "automatic": True},
            {"accountId": "b", "enabled": True, "automatic": True}]}
        self.source = {"id": "stable-model", "model": "m", "modelMode": "rewrite", "contextLength": 128000, "pool": self.pool}
        self.usage.keep("a", windows(), self.now)
        self.usage.keep("b", windows(), self.now)
        self.fetches, self.events = [], []
        self.selector = SubscriptionPools(self.usage, self.fetch, self.accounts.get,
                                          lambda p: True, lambda: self.now, listed=lambda a, m: True,
                                          event=self.events.append)

    def fetch(self, provider):
        self.fetches.append(provider["accountId"])
        return None

    def choose(self):
        return self.selector.resolve(self.source)

    def test_priority_and_stable_model_contract(self):
        p, refusal = self.choose()
        self.assertIsNone(refusal)
        self.assertEqual((p["accountId"], p["id"], p["model"], p["contextLength"]), ("a", "stable-model", "m", 128000))
        self.assertNotIn("pool", p)
        self.assertEqual(self.fetches, [])

    def test_short_boundary_switch_and_stickiness(self):
        self.choose()
        self.usage.keep("a", windows(short=80), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.usage.keep("a", windows(), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.pool["returnToPrimary"] = True
        self.assertEqual(self.choose()[0]["accountId"], "a")
        self.assertEqual(self.events[1]["reasons"], [{"accountId": "a", "reason": "reserve"}])

    def test_weekly_boundary_alone_switches(self):
        self.usage.keep("a", windows(short=0, weekly=90), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")

    def test_all_reserved_and_latest_window_reset_per_account(self):
        self.usage.keep("a", windows(90, 95, 2000), self.now)
        self.usage.keep("b", windows(90, 95, 2500), self.now)
        p, refusal = self.choose()
        self.assertEqual(refusal.status, 429)
        self.assertEqual(json.loads(refusal.body)["error"]["resets_at"], 3000)
        self.assertIsNone(self.selector.snapshot()["pools"]["pool"]["selectedAccountId"])

    def test_unknown_stale_and_expired_are_not_zero_usage(self):
        self.now += 301
        p, refusal = self.choose()
        self.assertEqual(refusal.status, 503)
        self.assertEqual([r["reason"] for r in refusal.verdict["members"]], ["usage_unknown", "usage_unknown"])
        self.assertEqual(len(self.fetches), 2)
        self.choose()
        self.assertEqual(len(self.fetches), 2)
        self.usage.keep("a", windows(reset=900), self.now)
        self.assertIsNotNone(self.choose()[1])

    def test_manual_keeps_reserve_and_never_falls_back(self):
        self.pool.update(mode="manual", manualAccountId="a")
        self.usage.keep("a", windows(short=80), self.now)
        self.assertEqual(self.choose()[1].status, 429)
        self.pool["manualAccountId"] = "b"
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.pool["manualUntil"] = self.now - 1
        self.assertTrue(self.choose()[0]["poolAutomatic"])

    def test_disabled_and_manual_only(self):
        self.pool["members"][0]["automatic"] = False
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.pool.update(mode="manual", manualAccountId="a")
        self.assertEqual(self.choose()[0]["accountId"], "a")
        self.pool["members"][0]["enabled"] = False
        self.assertIsNotNone(self.choose()[1])

    def test_alias_routing_and_shared_reserve(self):
        self.pool["members"][1]["accountId"] = "a-test"
        self.pool["members"][0]["enabled"] = False
        self.assertEqual(self.choose()[0]["accountId"], "a-test")
        self.assertEqual(self.choose()[0]["credentialAccountId"], "a")
        self.usage.keep("a", windows(short=80), self.now)
        self.assertIsNotNone(self.choose()[1])

    def test_alias_cannot_retry_a_provider_quota_refusal(self):
        self.pool["members"][1]["accountId"] = "a-test"
        p = self.choose()[0]
        self.assertTrue(self.selector.failed(p, 429, {"Retry-After": "42"}))
        p, refusal = self.selector.resolve(self.source, excluded={"a"})
        self.assertIsNotNone(refusal)
        self.assertFalse(any(r["eligible"] for r in refusal.verdict["members"]))

    def test_rejected_account_then_backup_and_manual_no_retry(self):
        p = self.choose()[0]
        self.assertTrue(self.selector.failed(p, 401))
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.pool.update(mode="manual", manualAccountId="b")
        self.assertFalse(self.selector.failed(self.choose()[0], 429))

    def test_missing_login_or_model_selects_backup(self):
        self.selector.credential = lambda p: p["accountId"] != "a"
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.selector.credential = lambda p: True
        self.selector.listed = lambda a, m: a != "a"
        self.assertEqual(self.choose()[0]["accountId"], "b")

    def test_no_reserve_still_enforces_exhausted_quota(self):
        for p in self.accounts.values():
            p["usageReserve"] = {}
        self.usage.keep("a", windows(short=100), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")

    def test_missing_reset_is_unknown_even_with_a_fresh_reading(self):
        data = windows(short=90)
        data[0]["resetAt"] = None
        self.usage.keep("a", data, self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.selector.snapshot()["pools"]["pool"]["members"][0]["reason"], "usage_unknown")

    def test_unknown_refresh_can_recover(self):
        self.now += 301
        self.selector.fetch = lambda p: {"rate_limit": {"primary_window": {"limit_window_seconds": 18000, "used_percent": 3, "reset_at": 5000}}}
        self.assertEqual(self.choose()[0]["accountId"], "a")

    def test_account_bound_context_is_refused_before_selection(self):
        provider, refusal = self.selector.resolve(self.source, json.dumps({"previous_response_id": "response-a"}))
        self.assertEqual(refusal.status, 400)
        self.assertEqual(json.loads(refusal.body)["error"]["type"], "subscription_pool_context_required")
        self.assertEqual(self.fetches, [])
        self.assertEqual(self.events, [])


class Configuration(unittest.TestCase):
    def setUp(self):
        self.data = {"accounts": [{"id": "a", "accountType": "openai-subscription", "name": "A", "baseUrl": "https://chatgpt.com", "usageReserve": {"18000": 20}}],
                     "blocks": [{"id": "stable", "accountId": "a", "model": "m"}], "pools": []}
        self.desk = CloudPoolDesk(load=lambda: copy.deepcopy(self.data), save=self.save)

    def save(self, data):
        self.data = data

    def test_alias_has_no_separate_budget_and_is_idempotent(self):
        first = self.desk.clone_test("a")
        self.assertEqual(first, self.desk.clone_test("a"))
        self.assertNotIn("usageReserve", first)
        owner = CloudSources(self.data).source(first["id"])
        self.assertEqual((owner["credentialAccountId"], owner["usageAccountId"], owner["usageReserve"]), ("a", "a", {"18000": 20}))

    def test_two_registrations_of_same_quota_share_owner_and_reserve(self):
        self.data["accounts"].append({**self.data["accounts"][0], "id": "second-registration", "usageReserve": {}})
        payload = base64.urlsafe_b64encode(json.dumps({"https://api.openai.com/auth": {"chatgpt_account_id": "same-quota"}}).encode()).decode().rstrip("=")
        secrets = {i: {"oauth": {"accessToken": "header." + payload + ".signature"}} for i in ("a", "second-registration")}
        source = CloudSources(self.data, secrets).source("second-registration")
        self.assertEqual((source["credentialAccountId"], source["usageAccountId"], source["usageReserve"]), ("second-registration", "a", {"18000": 20}))
        self.data["accounts"].reverse()  # saving an account must not change quota ownership
        self.assertEqual(CloudSources(self.data, secrets).source("second-registration"), source)

    def test_adoption_preserves_model_id_and_usage_origin(self):
        self.desk.upsert({"id": "p", "name": "P", "members": [{"accountId": "a"}]}, "a")
        self.assertEqual(self.data["blocks"], [{"id": "stable", "accountId": "p", "model": "m", "usageOriginAccountId": "a"}])
        with self.assertRaises(AppError):
            self.desk.delete("p")

    def test_invalid_pool_does_not_write(self):
        before = copy.deepcopy(self.data)
        for pool in ({"id": "a", "members": [{"accountId": "a"}]}, {"id": "p", "members": []},
                     {"id": "p", "members": [{"accountId": "missing"}]}, {"id": "p", "members": [{"accountId": "a"}], "mode": "manual"}):
            with self.assertRaises(AppError):
                self.desk.upsert(pool)
            self.assertEqual(self.data, before)

    def test_background_refresh_knows_pool_and_does_not_recreate_member_blocks(self):
        from caravan.admin import cloud_api
        self.desk.upsert({"id": "p", "name": "P", "members": [{"accountId": "a"}]}, "a")
        with patch.object(cloud_api, "load_cloud_data", return_value=self.data), \
                patch.object(cloud_api, "fetch_subscription_models", return_value=[{"id": "m"}]), \
                patch.object(cloud_api.CLOUD_SYNC, "apply") as apply:
            self.assertEqual(cloud_api.refresh_account_models_cache("p"), [{"id": "m"}])
            apply.assert_called_once_with("p", [{"id": "m"}])
            apply.reset_mock()
            cloud_api.refresh_account_models_cache("a")
            apply.assert_not_called()


class AccountRemoval(unittest.TestCase):
    """Two separate logins of one identity must survive either deletion."""

    def setUp(self):
        self.path = Path(tempfile.mkdtemp(dir=TMP)) / "credentials.json"
        self.vault = CredentialVault(self.path)
        claim = base64.urlsafe_b64encode(json.dumps({"https://api.openai.com/auth": {
            "chatgpt_account_id": "same-quota"}}).encode()).decode().rstrip("=")
        self.credentials = {aid: {"oauth": {"accessToken": f"{aid}.{claim}.signature",
                                           "refreshToken": f"login-{aid}", "expiresAt": 9000}}
                            for aid in ("a", "b")}
        self.path.write_text(json.dumps(self.credentials))
        self.data = {"accounts": [{"id": aid, "name": aid, "accountType": "openai-subscription",
                                   "baseUrl": "https://chatgpt.com", "authMode": "oauth"} for aid in ("a", "b")],
                     "pools": [{"id": "pool", "mode": "manual", "manualAccountId": "a", "manualUntil": 5000,
                                "members": [{"accountId": aid, "enabled": True, "automatic": True} for aid in ("a", "b")]}],
                     "blocks": [{"id": "stable-model", "accountId": "pool", "model": "m"},
                                {"id": "model-a", "accountId": "a", "model": "m"},
                                {"id": "model-b", "accountId": "b", "model": "m"}]}
        self.desk = CloudPoolDesk(load=lambda: copy.deepcopy(self.data), save=self.save, vault=self.vault)

    def save(self, data):
        self.data = data

    def remaining_login(self, removed, remaining):
        self.desk.remove_account(removed)
        self.assertEqual([a["id"] for a in self.data["accounts"]], [remaining])
        self.assertEqual(self.vault.read(), {remaining: self.credentials[remaining]})
        self.assertEqual(self.data["pools"][0]["members"], [{"accountId": remaining, "enabled": True, "automatic": True}])
        self.assertEqual(self.data["blocks"], [{"id": "stable-model", "accountId": "pool", "model": "m"},
                                              {"id": f"model-{remaining}", "accountId": remaining, "model": "m"}])
        source = CloudSources(self.data, self.vault.read()).source(remaining)
        self.assertEqual((source["id"], source["credentialAccountId"], source["usageAccountId"]),
                         (remaining, remaining, remaining))
        self.assertNotIn("testAliasOf", source)

    def test_delete_first_keeps_second_login_and_pool_models(self):
        self.remaining_login("a", "b")
        self.assertEqual((self.data["pools"][0]["mode"], self.data["pools"][0]["manualAccountId"],
                          self.data["pools"][0]["manualUntil"]), ("auto", "", 0))

    def test_delete_second_keeps_first_login_and_manual_choice(self):
        self.remaining_login("b", "a")
        self.assertEqual((self.data["pools"][0]["mode"], self.data["pools"][0]["manualAccountId"]), ("manual", "a"))

    def test_last_member_is_refused_without_any_partial_changes(self):
        self.data["pools"].append({"id": "only-b", "mode": "auto", "members": [{"accountId": "b"}]})
        before = copy.deepcopy(self.data)
        with self.assertRaises(AppError) as raised:
            self.desk.remove_account("b")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.data, before)
        self.assertEqual(self.vault.read(), self.credentials)

    def test_deleting_legacy_alias_does_not_delete_owner_login(self):
        self.data["accounts"].append({**self.data["accounts"][0], "id": "old-test", "testAliasOf": "a"})
        self.data["pools"][0]["members"].append({"accountId": "old-test", "enabled": True, "automatic": True})
        self.desk.remove_account("old-test")
        self.assertEqual([a["id"] for a in self.data["accounts"]], ["a", "b"])
        self.assertEqual(self.vault.read(), self.credentials)
        self.assertEqual([m["accountId"] for m in self.data["pools"][0]["members"]], ["a", "b"])

    def test_connect_same_identity_is_an_independent_registration(self):
        third = self.desk.connect_account("pool", {"id": "third", "type": "openai-subscription", "name": "Third"})
        self.assertNotIn("testAliasOf", third)
        self.vault.put_oauth("third", {**self.credentials["a"]["oauth"], "refreshToken": "third-login"})
        self.desk.complete_login("third")
        self.desk.remove_account("a")
        self.desk.remove_account("b")
        self.assertEqual([a["id"] for a in self.data["accounts"]], ["third"])
        self.assertEqual(set(self.vault.read()), {"third"})
        self.assertEqual(self.data["pools"][0]["members"], [{"accountId": "third", "enabled": True, "automatic": True}])


class Renewal(unittest.TestCase):
    def test_deletion_preserves_another_login_updated_while_waiting(self):
        path = Path(tempfile.mkdtemp(dir=TMP)) / "credentials.json"
        path.write_text(json.dumps({"a": {"oauth": {"accessToken": "old-a"}},
                                    "b": {"oauth": {"accessToken": "old-b"}}}))
        vault = CredentialVault(path)
        started = threading.Event()

        def delete():
            started.set()
            return vault.delete("a")

        with ThreadPoolExecutor(max_workers=1) as executor:
            with vault.locked(".a"):
                deletion = executor.submit(delete)
                self.assertTrue(started.wait(2))
                vault.put_oauth("b", {"accessToken": "fresh-b", "refreshToken": "new-b"})
            self.assertTrue(deletion.result(timeout=2))
        self.assertEqual(vault.read(), {"b": {"oauth": {"accessToken": "fresh-b", "refreshToken": "new-b"}}})

    def test_parallel_renewal_rotates_once_and_preserves_other_account(self):
        path = TMP / "renewal.json"
        path.write_text(json.dumps({"a": {"oauth": {"accessToken": "old", "refreshToken": "old-refresh", "expiresAt": 900, "email": "owner@example.test"}}, "b": {"apiKey": "other"}}))
        calls = []
        def request(req, timeout):
            calls.append(req.data)
            return io.BytesIO(json.dumps({"access_token": "new", "refresh_token": "rotated", "expires_in": 3600}).encode())
        vault = CredentialVault(path, clock=lambda: 1000, request=request)
        with ThreadPoolExecutor(max_workers=8) as executor:
            tokens = list(executor.map(lambda _: vault.oauth("a", {"tokenUrl": "https://issuer.test/token", "clientId": "client"}), range(8)))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(t["accessToken"] == "new" and t["email"] == "owner@example.test" for t in tokens))
        self.assertEqual(vault.read()["b"], {"apiKey": "other"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
