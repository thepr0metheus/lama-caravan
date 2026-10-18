#!/usr/bin/env python3
"""A pool edited on the board is decided again by the proxy at once: caravan/proxy/pool_watch.py.

The owner, 2026-10-14, with two pictures of a pool: he carried the lower model above the upper one and
"did not see it become the active one" — the card went on saying "Serving now" on the model that served before.
The label is the proxy's word about its last choice, and a choice was made only when a request came (or when the
idle probe asked, every five minutes at most). An edit sends no request.

What is pinned. The watch alone, with its readings and its deciding injected: the first look writes the files down
and decides nothing; nothing is read while the files stand; a touched file that changed no pool decides nothing;
a pool carried, switched off or added is decided again, once, alone; one that cannot be decided leaves the others
and is not tried again until it changes; a look that fails is looked at again; the loop rewrites the proxy's state
only after a decision and outlives a bad look. Then the owner's case on the real selector: luna carried above sol
with no request — the word is luna, the event says sol → luna, and the request that follows is served by luna;
and negative: a first step below its switch level gives way, so the word stays on the one that would serve.
Last, the standard watch on real files: the stamp, and a pool carried in the file handed to the decision.

Nothing here reaches a provider: the quota readings, the clock and the network answers are injected.

Run: python3 scripts/test_pool_watch.py
"""
import contextlib
import copy
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-pool-watch-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from caravan.common.model_levels import ModelLevels  # noqa: E402
from caravan.proxy.pool_steps import PoolSteps  # noqa: E402
from caravan.proxy.pool_watch import PoolWatch  # noqa: E402
from caravan.proxy.subscription_usage import SubscriptionUsage  # noqa: E402

SUB = "openai-subscription"


class Stop(Exception):
    """Ends a loop that would run for ever."""


class Sweeping(unittest.TestCase):
    """The watch alone: what it reads, when, and what it decides."""

    def setUp(self):
        self.stamp, self.reads, self.decided = 1, 0, []
        self.world = {"p": {"id": "p", "pool": {"steps": ["a", "b"]}, "levels": {}},
                      "q": {"id": "q", "pool": {"steps": ["x"]}, "levels": {}}}
        self.watch = PoolWatch(self.read, self.decide, lambda: self.stamp)

    def read(self):
        self.reads += 1
        return copy.deepcopy(self.world)

    def decide(self, source):
        self.decided.append(source)

    def touch(self):
        """The controller wrote a file: the stamp moves."""
        self.stamp += 1

    def ids(self):
        return [source["id"] for source in self.decided]

    def test_the_first_look_decides_nothing_and_writes_down_what_is_there(self):
        self.assertEqual(self.watch.sweep(), [])
        self.assertEqual((self.decided, self.reads), ([], 1))
        self.assertEqual(sorted(self.watch.seen), ["p", "q"])

    def test_nothing_is_read_while_the_files_stand(self):
        self.watch.sweep()
        self.assertEqual((self.watch.sweep(), self.watch.sweep()), ([], []))
        self.assertEqual(self.reads, 1)

    def test_a_touched_file_that_changed_no_pool_decides_nothing(self):
        self.watch.sweep()
        self.touch()
        self.assertEqual(self.watch.sweep(), [])
        self.assertEqual((self.reads, self.decided), (2, []))

    def test_a_pool_carried_is_decided_again_alone_and_once(self):
        self.watch.sweep()
        self.world["p"]["pool"]["steps"].reverse()           # the same steps, the other way round
        self.touch()
        self.assertEqual(self.watch.sweep(), ["p"])
        self.assertEqual(self.ids(), ["p"])
        self.assertEqual(self.decided[0]["pool"]["steps"], ["b", "a"], "the decision is made on the reading now, not the one before")
        self.touch()                                          # negative: the file moved again, the pools did not
        self.assertEqual(self.watch.sweep(), [])
        self.assertEqual(self.ids(), ["p"])

    def test_what_a_pool_is_decided_by_counts_not_only_its_steps(self):
        self.watch.sweep()
        self.world["q"]["levels"] = {"m": {"18000": 10}}      # a level moved: a step of this pool may give way now
        self.touch()
        self.assertEqual(self.watch.sweep(), ["q"], "the levels are part of a pool's reading, and only the pool that carries them is decided again")
        for pool in self.world.values():                      # in the files the levels are every pool's: then every pool is
            pool["levels"] = {"m": {"18000": 20}}
        self.touch()
        self.assertEqual(self.watch.sweep(), ["p", "q"])

    def test_a_new_pool_is_decided_and_one_that_is_gone_is_forgotten(self):
        self.watch.sweep()
        self.world["r"] = {"id": "r", "pool": {"steps": ["z"]}, "levels": {}}
        gone = self.world.pop("q")
        self.touch()
        self.assertEqual(self.watch.sweep(), ["r"])
        self.assertEqual(sorted(self.watch.seen), ["p", "r"])
        self.world["q"] = gone                                # it comes back unchanged: it is new again
        self.touch()
        self.assertEqual(self.watch.sweep(), ["q"])

    def test_a_pool_that_cannot_be_decided_leaves_the_others_and_is_not_tried_again(self):
        self.watch.sweep()
        for pool in ("p", "q"):
            self.world[pool]["pool"]["steps"].append("new")
        self.touch()
        tried = []

        def decide(source):
            tried.append(source["id"])
            if source["id"] == "p":
                raise RuntimeError("no such account")
            self.decided.append(source)

        self.watch.decide = decide
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            decided = self.watch.sweep()
        self.assertEqual(decided, ["q"])
        self.assertEqual(tried, ["p", "q"])
        self.assertIn("pool p not decided again", said.getvalue())
        self.assertIn("no such account", said.getvalue())
        self.touch()                                          # negative: nothing changed since, so p is not tried again
        self.assertEqual(self.watch.sweep(), [])
        self.assertEqual(tried, ["p", "q"])

    def test_a_look_that_fails_is_looked_at_again(self):
        self.watch.sweep()
        self.world["p"]["pool"]["steps"].reverse()
        self.touch()
        real, calls = self.read, []

        def read():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("file half written")
            return real()

        self.watch.read = read
        with self.assertRaises(RuntimeError):
            self.watch.sweep()
        self.assertEqual(self.watch.sweep(), ["p"], "the stamp was not kept for a reading that failed")

    def test_the_loop_rewrites_the_state_only_after_a_decision_and_outlives_a_bad_look(self):
        writes, passes, slept = [], [], []

        def sleep(seconds):
            slept.append(seconds)
            passes.append(1)
            if len(passes) == 1:
                self.world["p"]["pool"]["steps"].reverse()    # between the first look and the second: an edit
                self.touch()
            elif len(passes) == 2:
                self.touch()                                  # nothing changed
            elif len(passes) == 3:
                self.world["q"]["pool"]["steps"].append("w")
                self.touch()
                real = self.watch.read
                self.watch.read = lambda: (_ for _ in ()).throw(RuntimeError("bad look"))   # this look fails
                self.restore = real
            elif len(passes) == 4:
                self.watch.read = self.restore                # and the next one works
            elif len(passes) == 5:
                raise Stop()

        said = io.StringIO()
        with contextlib.redirect_stdout(said), self.assertRaises(Stop):
            self.watch.run(lambda: writes.append(len(self.decided)), sleep)
        self.assertEqual(writes, [1, 2], "one write per pass that decided something, none for the first look or an idle pass")
        self.assertIn("pool watch look failed: bad look", said.getvalue())
        self.assertEqual(self.ids(), ["p", "q"])
        self.assertEqual(set(slept), {1}, "a look every second, not a busy loop and not a minute")

    def test_a_look_that_keeps_failing_for_one_reason_says_so_once(self):
        self.watch.sweep()
        self.touch()
        passes = []

        def read():
            raise RuntimeError("cloud file unreadable")

        self.watch.read = read

        def sleep(_):
            passes.append(1)
            if len(passes) == 4:
                self.watch.read = lambda: (_ for _ in ()).throw(RuntimeError("another reason"))
            if len(passes) == 6:
                raise Stop()

        said = io.StringIO()
        with contextlib.redirect_stdout(said), self.assertRaises(Stop):
            self.watch.run(lambda: None, sleep)
        lines = [line for line in said.getvalue().splitlines() if "look failed" in line]
        self.assertEqual(len(lines), 2, "one line for each reason, not one for each second")
        self.assertIn("cloud file unreadable", lines[0])
        self.assertIn("another reason", lines[1])

    def test_the_mtime_of_a_file_that_is_not_there_is_zero_and_a_file_that_appears_is_a_change(self):
        path = TMP / "mtime-probe.json"
        self.assertEqual(PoolWatch.mtime(path), 0)
        path.write_text("{}", encoding="utf-8")
        os.utime(path, ns=(5_000_000_000, 5_000_000_000))
        self.assertEqual(PoolWatch.mtime(path), 5_000_000_000)
        os.utime(path, ns=(6_000_000_000, 6_000_000_000))
        self.assertNotEqual(PoolWatch.mtime(path), 5_000_000_000)
        path.unlink()


def windows(short=10, weekly=10, reset=2000):
    return [{"seconds": 18000, "usedPct": short, "resetAt": reset},
            {"seconds": 604800, "usedPct": weekly, "resetAt": reset + 1000}]


def step(sid, account, model="m", switch=None, stop=None):
    """A step as a file before 1.3.486 kept it, with its own levels — what ModelLevels reads as its model's."""
    levels = {"18000": 20, "604800": 10} if switch is None else switch
    return {"id": sid, "accountId": account, "model": model, "switchAt": levels,
            "stopAt": dict(levels) if stop is None else stop, "enabled": True}


class TheOwnersCase(unittest.TestCase):
    """Sol and luna on one subscription each, and nothing asking: the word the board reads follows the edit."""

    def setUp(self):
        self.now, self.stamp, self.events, self.fetches = 1000, 1, [], []
        self.usage = SubscriptionUsage()
        self.accounts = {i: {"id": i, "accountId": i, "usageAccountId": i, "credentialAccountId": i,
                             "accountType": SUB, "type": SUB, "baseUrl": "https://chatgpt.com/backend-api"} for i in ("a", "b")}
        self.usage.keep("a", windows(), self.now)
        self.usage.keep("b", windows(), self.now)
        self.pool = {"id": "pool", "name": "Work", "steps": [step("sol", "a", "sol"), step("luna", "b", "luna")]}
        self.selector = PoolSteps(self.usage, self.fetch, self.accounts.get, lambda p: True, lambda: self.now,
                                  listed=lambda a, m: True, event=self.events.append)
        self.watch = PoolWatch(self.read, self.selector.resolve, lambda: self.stamp)

    def fetch(self, provider):
        self.fetches.append(provider["accountId"])
        return None

    def source(self):
        """What load_cloud_provider hands the proxy: the pool and the levels its steps keep."""
        return {"id": "stable-model", "name": "Work", "model": "", "modelMode": "rewrite", "contextLength": 128000,
                "pool": copy.deepcopy(self.pool), "levels": ModelLevels({"levels": {}, "pools": [self.pool]}).stored()}

    def read(self):
        return {"pool": self.source()}

    def word(self):
        return self.selector.snapshot()["pools"]["pool"]["selectedStepId"]

    def carry_luna_up(self):
        self.pool["steps"].reverse()
        self.stamp += 1
        self.now += 5

    def test_luna_carried_above_sol_is_the_word_with_no_request(self):
        self.assertEqual(self.selector.resolve(self.source())[0]["poolStepId"], "sol")     # the last request
        self.assertEqual(self.watch.sweep(), [])                                           # the first look
        self.carry_luna_up()
        self.assertEqual(self.watch.sweep(), ["pool"])
        self.assertEqual(self.word(), "luna")
        state = self.selector.snapshot()["pools"]["pool"]
        self.assertEqual(state["decidedAt"], self.now)
        self.assertEqual([(r["stepId"], r["reason"]) for r in state["steps"]], [("luna", "ready"), ("sol", "ready")])
        self.assertEqual([(e["from"], e["to"], e["reasons"]) for e in self.events], [(None, "sol", []), ("sol", "luna", [])])
        self.assertEqual(self.fetches, [], "a decision with fresh readings asks no provider anything")
        # The word is true: the request that comes next is served by the step it names.
        self.assertEqual(self.selector.resolve(self.source())[0]["poolStepId"], "luna")
        self.assertEqual(len(self.events), 2, "the request made no new switch: the word was already right")

    def test_a_first_step_below_its_switch_level_gives_way_and_the_word_says_so(self):
        # Luna first, but 30% left of its window is below its switch level (40%): sol would serve the next request.
        self.pool["steps"] = [step("sol", "a", "sol"), step("luna", "b", "luna", switch={"18000": 40}, stop={"18000": 10})]
        self.usage.keep("b", windows(short=70), self.now)
        self.selector.resolve(self.source())
        self.watch.sweep()
        self.carry_luna_up()
        self.assertEqual(self.watch.sweep(), ["pool"])
        state = self.selector.snapshot()["pools"]["pool"]
        self.assertEqual(state["selectedStepId"], "sol", "carried first, but giving way: the word stays on the step that would serve")
        self.assertEqual([(r["stepId"], r["reason"]) for r in state["steps"]], [("luna", "switch"), ("sol", "ready")])
        self.assertEqual(self.selector.resolve(self.source())[0]["poolStepId"], "sol")

    def test_a_step_switched_off_moves_the_word_to_the_next(self):
        self.selector.resolve(self.source())
        self.watch.sweep()
        self.pool["steps"][0]["enabled"] = False
        self.stamp += 1
        self.assertEqual(self.watch.sweep(), ["pool"])
        self.assertEqual(self.word(), "luna")
        self.assertEqual(self.events[-1]["reasons"], [{"stepId": "sol", "reason": "disabled"}])

    def test_a_pool_nothing_has_decided_gets_its_word_at_its_first_edit(self):
        self.watch.sweep()                                    # a proxy that has just started: no word
        self.assertNotIn("pool", self.selector.snapshot()["pools"])
        self.carry_luna_up()
        self.assertEqual(self.watch.sweep(), ["pool"])
        self.assertEqual(self.word(), "luna")


class OnRealFiles(unittest.TestCase):
    """The standard watch: the files the proxy reads its pools from, and the way a pool is handed to a decision."""

    def setUp(self):
        self.cloud = TMP / "config" / "cloud-providers.json"
        self.secrets = TMP / "secrets" / "provider-secrets.json"
        for path in (self.cloud, self.secrets):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.ticks = 1_000_000_000
        self.steps = [{"id": "s1", "kind": "account", "accountId": "or", "model": "m1", "enabled": True},
                      {"id": "s2", "kind": "account", "accountId": "or", "model": "m2", "enabled": True}]
        self.write_cloud()
        self.secrets.write_text("{}", encoding="utf-8")
        self.decided = []
        self.watch = PoolWatch.standard()
        self.watch.decide = self.decided.append

    def write_cloud(self):
        data = {"accounts": [{"id": "or", "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1", "name": "OR"}],
                "pools": [{"id": "p1", "name": "One", "steps": self.steps}]}
        self.cloud.write_text(json.dumps(data), encoding="utf-8")
        self.ticks += 1_000_000_000
        os.utime(self.cloud, ns=(self.ticks, self.ticks))     # a file written twice in one tick of the clock still moves

    def test_a_pool_carried_in_the_file_is_handed_to_the_decision(self):
        self.assertEqual(self.watch.sweep(), [])
        self.steps.reverse()
        self.write_cloud()
        self.assertEqual(self.watch.sweep(), ["p1"])
        self.assertEqual([s["id"] for s in self.decided[0]["pool"]["steps"]], ["s2", "s1"])
        self.assertEqual(self.decided[0]["id"], "p1")

    def test_a_file_written_again_unchanged_decides_nothing(self):
        self.watch.sweep()
        self.write_cloud()
        self.assertEqual(self.watch.sweep(), [])
        self.assertEqual(self.decided, [])

    def test_the_standard_watch_decides_with_the_proxys_own_selector(self):
        from caravan.proxy.pool_steps import pool_steps
        self.assertEqual(PoolWatch.standard().decide, pool_steps.resolve)

    def test_start_runs_the_standard_watch_in_a_daemon_thread_of_its_own(self):
        import threading
        from caravan.proxy.state import write_state
        started = []

        class Recorder:
            def __init__(self, target=None, args=(), name="", daemon=False):
                self.target, self.args, self.name, self.daemon = target, args, name, daemon

            def start(self):
                started.append(self)

        real, threading.Thread = threading.Thread, Recorder
        try:
            watch = PoolWatch.start()
        finally:
            threading.Thread = real
        self.assertEqual(len(started), 1)
        thread = started[0]
        self.assertEqual((thread.name, thread.daemon, thread.args), ("pool-watch", True, (write_state,)))
        self.assertEqual(thread.target, watch.run)

    def test_the_proxys_main_starts_the_watch_after_the_probe(self):
        text = (ROOT / "caravan" / "proxy" / "main.py").read_text(encoding="utf-8")
        self.assertIn("PoolWatch.start()", text)
        self.assertLess(text.index("start_probe_thread()"), text.index("PoolWatch.start()"))
        self.assertLess(text.index("PoolWatch.start()"), text.index("time.sleep(3600)"))

    def test_the_secrets_file_is_looked_at_too(self):
        self.watch.sweep()
        before = self.watch.stamped
        self.ticks += 1_000_000_000
        os.utime(self.secrets, ns=(self.ticks, self.ticks))
        self.watch.sweep()
        self.assertNotEqual(self.watch.stamped, before, "a sign-in written to the vault is a change the watch must see")


if __name__ == "__main__":
    unittest.main(verbosity=1)
