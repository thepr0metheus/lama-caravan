#!/usr/bin/env python3
"""Pools of rows: the rule both readers share and the proxy's choice of a row.

The operator, 2026-10-10: a pool is a chain; the first row that fits serves,
always. The owner, 2026-10-12: a row is an account with ONE model, a local
model, or nothing yet; a subscription model's levels are the model's own, the
same in every pool (caravan/common/model_levels.py). A file of the old form
(model blocks, pools of subscription members) and steps that kept their own
levels are read the same way until the controller rewrites them.

All quotas, time and network answers are injected. Nothing reaches a provider.

Run: python3 scripts/test_pool_steps.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-pool-steps-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
sys.path.insert(0, str(ROOT))

from caravan.common.cloud_pools import CloudPools  # noqa: E402
from caravan.common.model_levels import ModelLevels  # noqa: E402
from caravan.proxy.pool_steps import PoolRefusal, PoolSteps  # noqa: E402
from caravan.proxy.subscription_usage import SubscriptionUsage  # noqa: E402

SUB = "openai-subscription"


def windows(short=10, weekly=10, reset=2000):
    return [{"seconds": 18000, "usedPct": short, "resetAt": reset},
            {"seconds": 604800, "usedPct": weekly, "resetAt": reset + 1000}]


def row(sid, account, model="m", **flags):
    """An account row as CloudPools reads it: no levels of its own since 1.3.486."""
    return {"id": sid, "kind": "account", "accountId": account, "model": model, "enabled": flags.get("enabled", True)}


def step(sid, account, model="m", switch=None, stop=None, **flags):
    """A step as a file before 1.3.486 kept it, with its own levels — what
    ModelLevels reads as its model's: the stop is the switch unless given."""
    levels = {"18000": 20, "604800": 10} if switch is None else switch
    out = {"id": sid, "accountId": account, "model": model, "switchAt": levels,
           "stopAt": dict(levels) if stop is None else stop, "enabled": flags.get("enabled", True)}
    if "automatic" in flags:                       # the flag of the form before 1.3.463
        out["automatic"] = flags["automatic"]
    return out


#: What a pool keeps since 1.3.463: no mode, no hand-picked step, no time for it.
POOL_KEYS = ["contextAuto", "id", "name", "steps"]


class OldForm(unittest.TestCase):
    """A file of the old form read as pools of steps — what the proxy does
    before the controller rewrites it."""

    def setUp(self):
        self.data = {
            "accounts": [
                {"id": "a", "accountType": SUB, "baseUrl": "https://chatgpt.com/backend-api", "usageReserve": {"18000": 20, "604800": 10}},
                {"id": "b", "accountType": SUB, "baseUrl": "https://chatgpt.com/backend-api", "usageReserve": {"18000": 30}},
                {"id": "or", "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1"},
            ],
            "pools": [{"id": "openai-pool", "name": "OpenAI pool", "mode": "manual", "manualAccountId": "b", "manualUntil": 0,
                       "returnToPrimary": False,
                       "members": [{"accountId": "a", "enabled": True, "automatic": True},
                                   {"accountId": "b", "enabled": True, "automatic": False}]}],
            "blocks": [{"id": "gpt-6-sol", "accountId": "openai-pool", "name": "gpt-6-sol", "model": "gpt-6-sol",
                        "contextLength": 272000, "contextAuto": True},
                       {"id": "llama", "accountId": "or", "name": "Llama on OR", "model": "meta/llama"},
                       {"id": "", "accountId": "or", "model": "x"},
                       {"accountId": "or", "model": "y"},
                       "rubbish"],
        }

    def test_a_pool_block_becomes_a_pool_of_its_members(self):
        pools = CloudPools(self.data)
        sol = pools.get("gpt-6-sol")
        self.assertEqual([(s["id"], s["accountId"], s["model"]) for s in sol["steps"]],
                         [("a", "a", "gpt-6-sol"), ("b", "b", "gpt-6-sol")])
        # The levels are the reserve each account kept, its model's now.
        levels = ModelLevels({"pools": [{"steps": pools.legacy_steps}]})
        self.assertEqual([levels.of(a, "gpt-6-sol")[0] for a in ("a", "b")], [{"18000": 20, "604800": 10}, {"18000": 30}])
        self.assertTrue(all(not {"switchAt", "stopAt"} & set(s) for s in sol["steps"]))
        # b was "manual only": the order passed it by, so it comes out switched off.
        self.assertEqual([s["enabled"] for s in sol["steps"]], [True, False])
        self.assertTrue(all("automatic" not in s for s in sol["steps"]))
        # The old pool's hand pick (mode manual, b) is not carried: the pool goes by its order.
        self.assertEqual(sorted(sol), sorted(POOL_KEYS + ["contextLength"]))
        self.assertEqual((sol["contextLength"], sol["contextAuto"], sol["name"]), (272000, True, "gpt-6-sol"))

    def test_negative_a_member_in_the_automatic_order_stays_on(self):
        self.data["pools"][0]["members"][1]["automatic"] = True
        self.assertEqual([s["enabled"] for s in CloudPools(self.data).get("gpt-6-sol")["steps"]], [True, True])
        self.data["pools"][0]["members"][0]["enabled"] = False      # switched off stays off
        self.assertEqual([s["enabled"] for s in CloudPools(self.data).get("gpt-6-sol")["steps"]], [False, True])

    def test_an_account_block_becomes_a_pool_of_one_step(self):
        llama = CloudPools(self.data).get("llama")
        self.assertEqual(llama["steps"], [row("or", "or", "meta/llama")])
        self.assertEqual((llama["name"], sorted(llama)), ("Llama on OR", POOL_KEYS))

    def test_negative_rubbish_is_no_pool(self):
        self.assertEqual(sorted(CloudPools(self.data).pools), ["gpt-6-sol", "llama"])

    def test_an_id_the_old_writers_allowed_is_read(self):
        # A reader stricter than the writers were would lose a pool a port names.
        self.data["blocks"].append({"id": "blk:test", "accountId": "or", "model": "m"})
        self.assertEqual(CloudPools(self.data).get("blk:test")["steps"][0]["model"], "m")


    def test_the_old_pool_is_no_source_of_the_new_form(self):
        # In the old form the members' pool stands where an account does; in the
        # new form a pool is no account.
        self.assertIn("openai-pool", CloudPools(self.data).sources.pools)
        new = {"accounts": self.data["accounts"], "pools": [{"id": "p", "name": "P", "steps": [step("a", "a")]}]}
        self.assertEqual(CloudPools(new).sources.pools, {})
        self.assertFalse(CloudPools.legacy(new))
        self.assertTrue(CloudPools.legacy(self.data))
        self.assertTrue(CloudPools.legacy({"pools": [{"id": "x", "members": []}]}))


class NewForm(unittest.TestCase):
    def test_steps_kept_as_written_and_rubbish_dropped(self):
        pools = CloudPools({"accounts": [], "pools": [{"id": "p", "name": " Smart ", "mode": "manual", "manualStepId": "a-2",
                                                       "manualUntil": 4102444800, "contextLength": "100",
                                                       "steps": [step("a", "a", "sol", {"18000": 50}),
                                                                 step("a-2", "a", "luna", {"18000": 10, "604800": 95}),
                                                                 step("a", "a", "dup"),
                                                                 {"id": "z", "accountId": "a"},
                                                                 {"id": "z", "accountId": "", "model": "m"}, 7]}]})
        p = pools.get("p")
        # A row naming half of an account and a model names nothing: it reads as open.
        self.assertEqual([(s["id"], s["kind"], s.get("model")) for s in p["steps"]],
                         [("a", "account", "sol"), ("a-2", "account", "luna"), ("z", "open", None)])
        levels = ModelLevels({"pools": [{"steps": [step("a", "a", "sol", {"18000": 50}),
                                                   step("a-2", "a", "luna", {"18000": 10, "604800": 95})]}]})
        self.assertEqual((levels.of("a", "sol")[1], levels.of("a", "luna")[1]),
                         ({"18000": 50}, {"18000": 10, "604800": 90}))
        # A hand pick kept before 1.3.463 — even one whose time is still ahead — is not read.
        self.assertEqual((p["name"], p["contextLength"], sorted(p)), ("Smart", 100, sorted(POOL_KEYS + ["contextLength"])))

    def test_levels_of_a_model(self):
        pair = lambda raw: (ModelLevels.clean(raw)["stopAt"], ModelLevels.clean(raw)["switchAt"])  # noqa: E731
        # The operator, 2026-10-11: a stop (the model does not serve) and a switch (it gives way).
        self.assertEqual(pair({"switchAt": {"18000": 40}, "stopAt": {"18000": 10}}), ({"18000": 10}, {"18000": 40}))
        # A pair of one level, kept before 1.3.463: that level stopped it — it is the stop, and the switch.
        self.assertEqual(pair({"switchAt": {"18000": 20, "604800": 10}}),
                         ({"18000": 20, "604800": 10}, {"18000": 20, "604800": 10}))
        # A switch below the stop would never be reached: it rests on the stop; a window only one names gets both.
        self.assertEqual(pair({"switchAt": {"18000": 5, "604800": 30}, "stopAt": {"18000": 30}}),
                         ({"18000": 30}, {"18000": 30, "604800": 30}))
        # negative: no stop said out loud is no stop, not the switch; rubbish drops out
        self.assertEqual(pair({"switchAt": {"18000": 40}, "stopAt": {}}), ({}, {"18000": 40}))
        self.assertEqual(pair({"switchAt": {"x": 5, "18000": True}, "stopAt": "rubbish"}), ({}, {}))

    def test_a_model_keeps_one_pair_for_every_pool(self):
        # The owner, 2026-10-12: the levels stand on the model, not in a pool.
        data = {"levels": {"a": {"sol": {"stopAt": {"18000": 30}, "switchAt": {"18000": 40}}, "luna": {"stopAt": {}, "switchAt": {}}}},
                "pools": [{"steps": [step("a", "a", "sol", {"18000": 5})]}]}
        levels = ModelLevels(data)
        self.assertEqual(levels.of("a", "sol"), ({"18000": 30}, {"18000": 40}))   # the model's own outranks a step's
        self.assertEqual(levels.of("a", "luna"), ({}, {}))                        # lifted is a choice, kept
        new = {"18000": 10, "604800": 10}
        self.assertEqual(levels.of("a", "terra"), (new, new))                      # nobody set it: 10%, as a new model
        self.assertFalse(levels.is_set("a", "terra"))
        # Two steps of one model with different levels: the stricter of each.
        both = ModelLevels({"pools": [{"steps": [step("x", "b", "m", {"18000": 40}, {"18000": 10})]},
                                      {"steps": [step("y", "b", "m", {"18000": 20, "604800": 50}, {"18000": 25})]}]})
        self.assertEqual(both.of("b", "m"), ({"18000": 25}, {"18000": 40, "604800": 50}))
        self.assertEqual(ModelLevels(data).stored()["a"]["sol"], {"stopAt": {"18000": 30}, "switchAt": {"18000": 40}})

    def test_three_kinds_of_row(self):
        # The owner, 2026-10-12: "+ row" adds an open row; its output is cabled to a model.
        self.assertEqual(CloudPools.step({"id": "r1"}), {"id": "r1", "kind": "open", "enabled": True})
        self.assertEqual(CloudPools.step({"id": "r2", "output": "srv:22008"}),
                         {"id": "r2", "kind": "output", "output": "srv:22008", "enabled": True})
        self.assertEqual(CloudPools.step({"id": "r3", "output": "eng:0a1b2c3d4e5f", "enabled": False})["enabled"], False)
        # negative: an output that is no local model's id names nothing; no id is no row
        self.assertEqual(CloudPools.step({"id": "r4", "output": "http://elsewhere:80"})["kind"], "open")
        self.assertIsNone(CloudPools.step({"output": "srv:1"}))
        self.assertEqual(CloudPools.row_id({"r1", "r2", "sub"}), "r3")

    def test_window_with_a_local_row_is_not_known(self):
        named = lambda account, model: 200000  # noqa: E731
        pool = {"contextAuto": True, "steps": [row("a", "a"), {"id": "r1", "kind": "open", "enabled": True}]}
        self.assertEqual(CloudPools.window(pool, named), 200000)     # an open row names nothing and asks nothing
        pool["steps"].append({"id": "r2", "kind": "output", "output": "srv:1", "enabled": True})
        self.assertIsNone(CloudPools.window(pool, named))           # negative: a cell's window is not known here

    def test_a_manual_only_step_reads_as_switched_off(self):
        read = lambda **flags: CloudPools.step(step("a", "a", **flags))  # noqa: E731
        self.assertEqual(read(automatic=False), row("a", "a", enabled=False))
        self.assertEqual(read(enabled=False, automatic=True), row("a", "a", enabled=False))
        # negative: in the automatic order, or a step written after 1.3.463 (no flag), it stays on
        self.assertEqual(read(automatic=True), row("a", "a"))
        self.assertEqual(read(), row("a", "a"))

    def test_negative_empty_pool_is_a_pool(self):
        self.assertEqual(CloudPools({"pools": [{"id": "p"}]}).get("p")["steps"], [])

    def test_step_ids_for_one_account_twice(self):
        self.assertEqual(CloudPools.step_id("a", set()), "a")
        self.assertEqual(CloudPools.step_id("a", {"a"}), "a-2")
        self.assertEqual(CloudPools.step_id("a", {"a", "a-2"}), "a-3")

    def test_window_declared_or_smallest_step(self):
        pool = {"contextLength": 100000, "contextAuto": False,
                "steps": [step("a", "a", "sol"), step("b", "b", "opus"), step("c", "c", "off", enabled=False)]}
        named = {("a", "sol"): 400000, ("b", "opus"): 200000}
        catalogue = lambda account, model: named.get((account, model))
        self.assertEqual(CloudPools.window(pool, catalogue), 100000)
        pool["contextAuto"] = True
        self.assertEqual(CloudPools.window(pool, catalogue), 200000)   # a switched-off step is not asked
        named.pop(("b", "opus"))
        # negative: a step that names no window makes the pool name none of its own
        self.assertEqual(CloudPools.window(pool, catalogue), 100000)
        pool.pop("contextLength")
        self.assertIsNone(CloudPools.window(pool, catalogue))


class Selection(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.usage = SubscriptionUsage()
        self.accounts = {i: {"id": i, "accountId": i, "usageAccountId": i, "credentialAccountId": i,
                             "accountType": SUB, "type": SUB, "baseUrl": "https://chatgpt.com/backend-api"}
                         for i in ("a", "b")}
        self.accounts["a-test"] = {**self.accounts["a"], "id": "a-test", "accountId": "a-test", "credentialAccountId": "a", "usageAccountId": "a"}
        self.accounts["or"] = {"id": "or", "accountId": "or", "usageAccountId": "or", "credentialAccountId": "or",
                               "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1"}
        self.accounts["ant"] = {"id": "ant", "accountId": "ant", "usageAccountId": "ant", "credentialAccountId": "ant",
                                "type": "anthropic", "baseUrl": "https://api.anthropic.com/v1"}
        self.pool = {"id": "pool", "name": "Work", "steps": [step("a", "a"), step("b", "b")]}
        self.levels = {}
        self.source = {"id": "stable-model", "name": "Work", "model": "", "modelMode": "rewrite",
                       "contextLength": 128000, "pool": self.pool}
        self.usage.keep("a", windows(), self.now)
        self.usage.keep("b", windows(), self.now)
        self.fetches, self.events = [], []
        self.selector = PoolSteps(self.usage, self.fetch, self.accounts.get,
                                  lambda p: True, lambda: self.now, listed=lambda a, m: True,
                                  event=self.events.append)

    def fetch(self, provider):
        self.fetches.append(provider["accountId"])
        return None

    def choose(self, **kw):
        # What load_cloud_provider hands the proxy: the models' levels, here the
        # ones the fixture's steps keep (ModelLevels reads a step's as its model's).
        self.source["levels"] = ModelLevels({"levels": self.levels, "pools": [self.pool]}).stored()
        return self.selector.resolve(self.source, **kw)

    def rows(self):
        return [(r["stepId"], r["reason"]) for r in self.selector.snapshot()["pools"]["pool"]["steps"]]

    def test_first_step_serves_with_its_own_model(self):
        self.pool["steps"] = [step("a", "a", "sol"), step("b", "b", "luna")]
        p, refusal = self.choose()
        self.assertIsNone(refusal)
        self.assertEqual((p["accountId"], p["id"], p["model"], p["modelMode"], p["poolStepId"], p["contextLength"]),
                         ("a", "stable-model", "sol", "rewrite", "a", 128000))
        self.assertNotIn("pool", p)
        self.assertEqual(self.fetches, [])
        self.usage.keep("a", windows(short=80), self.now)
        p, _ = self.choose()
        self.assertEqual((p["accountId"], p["model"], p["poolStepId"]), ("b", "luna", "b"))

    def test_always_back_to_the_first_step(self):
        # The operator, 2026-10-10: a later step serves only while an earlier one cannot.
        self.choose()
        self.usage.keep("a", windows(short=80), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.usage.keep("a", windows(), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "a")
        self.assertEqual([(e["from"], e["to"]) for e in self.events], [(None, "a"), ("a", "b"), ("b", "a")])
        self.assertEqual(self.events[1]["reasons"], [{"stepId": "a", "reason": "reserve"}])

    def test_one_account_twice_by_its_own_levels(self):
        # sol down to 50%, then luna of the same subscription down to 10%.
        self.pool["steps"] = [step("a", "a", "sol", {"18000": 50}), step("a-2", "a", "luna", {"18000": 10})]
        self.usage.keep("a", windows(short=60), self.now)        # 40% left
        p, refusal = self.choose()
        self.assertIsNone(refusal)
        self.assertEqual((p["poolStepId"], p["model"]), ("a-2", "luna"))
        self.assertEqual(self.rows(), [("a", "reserve"), ("a-2", "ready")])
        self.usage.keep("a", windows(short=92), self.now)        # 8% left: both levels reached
        self.assertEqual(self.choose()[1].status, 429)
        self.usage.keep("a", windows(short=40), self.now)        # negative: 60% left, sol again
        self.assertEqual(self.choose()[0]["model"], "sol")

    def test_weekly_level_alone_moves_on(self):
        self.usage.keep("a", windows(short=0, weekly=90), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")

    def test_a_model_nobody_set_levels_for_stops_at_ten_percent(self):
        # The owner, 2026-10-12: a model cabled into a pool in Routing has no
        # levels written; it stops — and switches — where a new subscription does.
        self.pool["steps"] = [row("a", "a", "new"), row("b", "b", "new")]
        self.usage.keep("a", windows(short=88), self.now)       # 12% left
        self.assertEqual(self.choose()[0]["accountId"], "a")
        self.usage.keep("a", windows(short=91), self.now)       # 9% left: at its 10% stop
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.rows()[0], ("a", "reserve"))

    def test_an_open_row_serves_nothing(self):
        self.pool["steps"].insert(0, {"id": "r1", "kind": "open", "enabled": True})
        p, refusal = self.choose()
        self.assertIsNone(refusal)
        self.assertEqual(p["poolStepId"], "a")
        self.assertEqual(self.rows()[0], ("r1", "not_connected"))
        self.pool["steps"] = [{"id": "r1", "kind": "open", "enabled": True}]
        self.assertEqual(self.choose()[1].status, 503)           # negative: no row cabled — no limit to wait for

    def test_a_step_without_levels_still_stops_at_a_spent_window(self):
        self.pool["steps"][0].update(switchAt={}, stopAt={})
        self.usage.keep("a", windows(short=99), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "a")     # negative: 1% left and no level
        self.usage.keep("a", windows(short=100), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")

    def test_every_step_at_its_level_is_429_until_the_latest_reset(self):
        self.usage.keep("a", windows(90, 95, 2000), self.now)
        self.usage.keep("b", windows(90, 95, 2500), self.now)
        p, refusal = self.choose()
        self.assertIsInstance(refusal, PoolRefusal)
        self.assertEqual((refusal.status, refusal.KIND), (429, "pool_unavailable"))
        self.assertEqual(json.loads(refusal.body)["error"]["resets_at"], 3000)
        self.assertIn("Pool Work has no step that fits now: a (reserve); b (reserve)", refusal.message)
        self.assertIsNone(self.selector.snapshot()["pools"]["pool"]["selectedStepId"])

    def test_unknown_stale_and_expired_are_not_zero_usage(self):
        self.now += 301
        p, refusal = self.choose()
        self.assertEqual(refusal.status, 503)
        self.assertEqual([r["reason"] for r in refusal.verdict["steps"]], ["usage_unknown", "usage_unknown"])
        self.assertEqual(len(self.fetches), 2)
        self.choose()
        self.assertEqual(len(self.fetches), 2)                   # asked again only after FAILED_REFRESH_SEC
        self.usage.keep("a", windows(reset=900), self.now)
        self.assertIsNotNone(self.choose()[1])

    def test_an_early_reset_reopens_a_step_held_at_its_level(self):
        # A step held at its level gets no traffic, so no answer brings a
        # reading: a banked or bought reset would stay unseen until the old
        # reset time — up to a week. A stale reading is refreshed from the page.
        page = {"rate_limit": {"primary_window": {"used_percent": 0, "limit_window_seconds": 18000, "reset_at": 9000}}}
        self.selector.fetch = lambda p: (self.fetches.append(p["accountId"]), page)[1]
        self.usage.keep("a", windows(short=85, reset=5000), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.now += 299
        self.assertEqual((self.choose()[0]["accountId"], self.fetches), ("b", []))    # still fresh: the page is not asked
        self.now += 1
        self.assertEqual(self.choose()[0]["accountId"], "a")                           # stale: asked, reset seen
        self.assertEqual(self.fetches, ["a", "b"])
        self.assertEqual(self.usage.windows("a"), [{"seconds": 18000, "usedPct": 0, "resetAt": 9000}])

    def test_unknown_refresh_can_recover(self):
        self.now += 301
        self.selector.fetch = lambda p: {"rate_limit": {"primary_window": {"limit_window_seconds": 18000, "used_percent": 3, "reset_at": 5000}}}
        self.assertEqual(self.choose()[0]["accountId"], "a")

    def test_missing_reset_is_unknown_even_with_a_fresh_reading(self):
        data = windows(short=90)
        data[0]["resetAt"] = None
        self.usage.keep("a", data, self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.rows()[0], ("a", "usage_unknown"))

    def test_a_stored_hand_pick_is_not_obeyed(self):
        # The operator, 2026-10-11: the pool always goes by the order set. A pool
        # kept before 1.3.463 with b picked by hand, its time still ahead, serves
        # a first, b only while a cannot, and back.
        self.pool.update(mode="manual", manualStepId="b", manualUntil=self.now + 3600)
        p, refusal = self.choose()
        self.assertIsNone(refusal)
        self.assertEqual(p["accountId"], "a")
        self.assertNotIn("poolAutomatic", p)
        self.usage.keep("a", windows(short=80), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.usage.keep("a", windows(), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "a")
        state = self.selector.snapshot()["pools"]["pool"]
        self.assertEqual(sorted(state), ["decidedAt", "selectedStepId", "steps"])
        self.assertTrue(all(sorted(e) == ["at", "from", "poolId", "reasons", "to"] for e in self.events))

    def test_negative_a_picked_step_at_its_level_is_passed_by(self):
        # Under the old rule this pool refused (b picked, b at its level); now it serves a.
        self.pool.update(mode="manual", manualStepId="b")
        self.usage.keep("b", windows(short=80), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "a")
        self.assertEqual(self.rows(), [("a", "ready"), ("b", "reserve")])

    def test_a_step_below_its_switch_gives_way(self):
        # a: switch at 40%, stop at 10%; b: one level, 20%.
        self.pool["steps"] = [step("a", "a", switch={"18000": 40}, stop={"18000": 10}), step("b", "b", switch={"18000": 20})]
        self.usage.keep("a", windows(short=70), self.now)            # 30% left: below a's switch, above its stop
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.rows(), [("a", "switch"), ("b", "ready")])
        self.assertEqual(self.events[-1]["reasons"], [{"stepId": "a", "reason": "switch"}])
        self.usage.keep("b", windows(short=85), self.now)            # b at its stop: a still serves, giving way to nobody
        p, refusal = self.choose()
        self.assertIsNone(refusal)
        self.assertEqual(p["accountId"], "a")
        self.assertEqual(self.rows(), [("a", "switch"), ("b", "reserve")])
        self.usage.keep("a", windows(short=92), self.now)            # 8% left: a at its stop too — the pool refuses
        refusal = self.choose()[1]
        self.assertEqual((refusal.status, self.rows()), (429, [("a", "reserve"), ("b", "reserve")]))
        self.usage.keep("a", windows(short=50), self.now)            # 50% left: a above its switch — first again
        self.usage.keep("b", windows(), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "a")
        self.assertEqual(self.rows(), [("a", "ready"), ("b", "ready")])

    def test_steps_giving_way_keep_their_order(self):
        both = {"18000": 40}
        self.pool["steps"] = [step("a", "a", switch=both, stop={"18000": 10}), step("b", "b", switch=both, stop={"18000": 10})]
        self.usage.keep("a", windows(short=70), self.now)
        self.usage.keep("b", windows(short=70), self.now)
        self.assertEqual(self.choose()[0]["accountId"], "a", "with none above its switch, the first one giving way serves")
        # negative: a step with no windows (a key) is never giving way — it is ready, and goes first
        self.pool["steps"].append(step("or", "or", switch={}))
        self.assertEqual(self.choose()[0]["accountId"], "or")
        self.assertEqual(self.rows()[-1], ("or", "ready"))

    def test_disabled_step_is_passed_by(self):
        self.pool["steps"][0]["enabled"] = False
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.rows()[0], ("a", "disabled"))
        # A step the order passed by before 1.3.463 ("manual only") arrives switched off.
        self.pool = CloudPools.pool({**self.pool, "steps": [step("a", "a", automatic=False), step("b", "b")]})
        self.source["pool"] = self.pool
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.rows()[0], ("a", "disabled"))
        self.pool["steps"][1]["enabled"] = False
        self.assertEqual(self.choose()[1].status, 429)                # every step switched off

    def test_alias_routing_and_shared_level(self):
        self.pool["steps"] = [step("a", "a", enabled=False), step("a-test", "a-test")]
        self.assertEqual(self.choose()[0]["accountId"], "a-test")
        self.assertEqual(self.choose()[0]["credentialAccountId"], "a")
        self.usage.keep("a", windows(short=80), self.now)
        self.assertIsNotNone(self.choose()[1])

    def test_alias_cannot_retry_a_provider_quota_refusal(self):
        self.pool["steps"][1] = step("a-test", "a-test")
        p = self.choose()[0]
        self.assertTrue(self.selector.failed(p, 429, {"Retry-After": "42"}))
        p, refusal = self.selector.resolve(self.source, excluded={"a"})
        self.assertIsNotNone(refusal)
        self.assertFalse(any(r["eligible"] for r in refusal.verdict["steps"]))

    def test_refusals_rest_the_account_by_their_kind(self):
        p = self.choose()[0]
        self.assertTrue(self.selector.failed(p, 429, {"Retry-After": "42"}))
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.selector._blocked["a"], {"reason": "quota", "at": 1000, "until": 1042})
        self.assertTrue(self.selector.failed(self.choose()[0], 402))
        self.assertEqual(self.selector._blocked["b"]["reason"], "payment")
        self.assertEqual(self.selector._blocked["b"]["until"], 1300)
        self.assertEqual(self.choose()[1].status, 429)           # every step held by a limit
        self.now = 1043
        self.assertEqual(self.choose()[0]["accountId"], "a")

    def test_negative_errors_that_are_not_limits_do_not_move_the_pool(self):
        p = self.choose()[0]
        for status in (400, 404, 500, 502, 503):
            self.assertFalse(self.selector.failed(p, status))
        self.assertEqual(self.selector._blocked, {})
        self.assertEqual(self.choose()[0]["accountId"], "a")
        self.assertFalse(self.selector.failed({"accountId": "a"}, 429))   # an account routed to directly has no pool

    def test_rejected_sign_in_then_next(self):
        p = self.choose()[0]
        self.assertTrue(self.selector.failed(p, 401))
        self.assertEqual(self.selector._blocked["a"]["until"], 1300)
        self.assertEqual(self.choose()[0]["accountId"], "b")
        # Every step of a pool may send the request on — a stored hand pick changes nothing.
        self.pool.update(mode="manual", manualStepId="b")
        self.assertTrue(self.selector.failed(self.choose()[0], 429))

    def test_missing_login_or_model_selects_next(self):
        self.selector.credential = lambda p: p["accountId"] != "a"
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.rows()[0], ("a", "credential_missing"))
        self.selector.credential = lambda p: True
        self.selector.listed = lambda a, m: a != "a"
        self.assertEqual(self.choose()[0]["accountId"], "b")
        self.assertEqual(self.rows()[0], ("a", "model_unavailable"))

    def test_another_provider_is_held_only_by_its_refusals(self):
        self.pool["steps"] = [step("or", "or", "meta/llama", switch={}), step("a", "a")]
        p, _ = self.choose()
        self.assertEqual((p["accountId"], p["model"], p["type"]), ("or", "meta/llama", "openrouter"))
        self.assertEqual(self.fetches, [])                       # no usage page is asked for it
        self.assertTrue(self.selector.failed(p, 402))
        self.assertEqual(self.choose()[0]["accountId"], "a")

    def test_a_responses_request_skips_a_step_that_speaks_chat_only(self):
        self.pool["steps"] = [step("ant", "ant", "claude", switch={}), step("or", "or", "x", switch={}), step("a", "a")]
        body = json.dumps({"model": "x", "input": "hi"})
        self.assertEqual(self.choose(body=body, path="/v1/responses")[0]["accountId"], "a")
        self.assertEqual(self.rows()[:2], [("ant", "format_unsupported"), ("or", "format_unsupported")])
        self.assertEqual(self.choose(body=json.dumps({"model": "x", "messages": []}), path="/v1/chat/completions")[0]["accountId"], "ant")
        self.accounts["or"]["type"] = "openai"                   # api.openai.com speaks Responses
        self.assertEqual(self.choose(body=body, path="/v1/responses")[0]["accountId"], "or")

    def test_a_subscription_serves_a_chat_alone(self):
        # 1.3.501: a recording to transcribe has no translation into the subscription's Responses
        # API — its row passes, and the pool's cell serves.
        cell = {"id": "srv:22003", "upstreamHost": "10.0.0.5", "upstreamPort": 22003}
        self.selector.local = lambda oid: dict(cell) if oid == "srv:22003" else None
        self.selector.dead = lambda oid: False
        self.selector.free = lambda out: True
        self.pool["steps"] = [step("a", "a"), {"id": "ear", "kind": "output", "output": "srv:22003", "enabled": True}]
        p, refusal = self.choose(path="/v1/audio/transcriptions")
        self.assertIsNone(refusal)
        self.assertEqual((p["poolStepId"], p["localOutput"]["upstreamPort"]), ("ear", 22003))
        self.assertEqual(self.rows()[0], ("a", "format_unsupported"))
        for path in ("/v1/chat/completions", "/v1/responses?stream=1", ""):
            self.assertEqual(self.choose(path=path)[0]["poolStepId"], "a")   # negative: a chat is the subscription's

    def test_a_pool_of_subscriptions_refuses_a_recording_as_the_callers_to_fix(self):
        provider, refusal = self.choose(path="/v1/audio/transcriptions")
        self.assertIs(provider, self.source)
        self.assertEqual((refusal.status, refusal.unsupported, refusal.path), (400, True, "/v1/audio/transcriptions"))
        self.assertNotIn("Retry-After", dict(refusal.getheaders()))
        self.assertEqual(self.rows(), [("a", "format_unsupported"), ("b", "format_unsupported")])
        self.assertFalse(self.selector.can_go_on(self.source, path="/v1/embeddings"))
        self.assertTrue(self.selector.can_go_on(self.source, path="/v1/chat/completions"))
        # negative: a pool held by its limits is a wait, not the caller's to fix
        self.usage.keep("a", windows(short=95), self.now)
        self.usage.keep("b", windows(short=95), self.now)
        provider, refusal = self.choose(path="/v1/chat/completions")
        self.assertEqual((refusal.status, refusal.unsupported), (429, False))

    def test_empty_pool_names_its_cause(self):
        self.pool["steps"] = []
        provider, refusal = self.choose()
        self.assertIs(provider, self.source)
        self.assertEqual(refusal.status, 503)
        self.assertEqual(refusal.message, "Pool Work has no step: add one on the board")
        self.assertEqual(json.loads(refusal.body)["error"]["steps"], [])

    def test_account_bound_context_is_refused_only_where_a_switch_is_possible(self):
        body = json.dumps({"previous_response_id": "response-a"})
        provider, refusal = self.selector.resolve(self.source, body)
        self.assertEqual(refusal.status, 400)
        self.assertEqual(json.loads(refusal.body)["error"]["type"], "pool_context_required")
        self.assertEqual((self.fetches, self.events), ([], []))
        self.pool["steps"][1]["enabled"] = False
        # negative: one step cannot switch — the context goes with it
        self.assertIsNone(self.selector.resolve(self.source, body)[1])

    def test_a_source_without_a_pool_passes(self):
        direct = {"id": "acc", "accountId": "acc", "model": ""}
        self.assertEqual(self.selector.resolve(direct), (direct, None))

    def test_refusal_reads_like_an_answer(self):
        self.pool["steps"] = []
        refusal = self.choose()[1]
        self.assertEqual(refusal.getheader("retry-after"), "30")
        self.assertEqual(json.loads(refusal.read())["error"]["type"], "pool_unavailable")
        self.assertEqual(refusal.read(), b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
