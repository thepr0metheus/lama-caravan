#!/usr/bin/env python3
"""Value snapshot: a machine's model cache as its scout reports it, and what the board asks of it (1.3.576).

The owner, 2026-10-18, when the disk of a machine was 94 % full of model copies and a start died with "No space left on device": keep in
the cache only the last models, from 1 to 5 and 1 by default, with all their files; show the setting somewhere noticeable; delete everything
older by itself. The scout does it (caravan-scout 2.34, cache_keeper.py: the setting, what may go, the refusals) and reports `modelCache`;
this side keeps what it says for the board (ModelCacheFacts) and carries the operator's word back (ModelCache).

Pinned: the report's block as the machine's record keeps it — and "not said" apart from "zero"; what a part said in a form that cannot be
read does to the record (that part is unknown, never a number made up); the two calls, with a stand-in scout (what they send, what they
refuse before the scout is asked, what they store afterwards, what they do when the scout refuses or goes quiet); the record, the pull and the
node carrying the block; the two routes.

Each claim has a positive and a negative pin. The report's block comes from the scout's own sample (scripts/fixtures/scout-report-sample.json).

Run: python3 scripts/test_model_cache.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin import routes  # noqa: E402
from caravan.admin.model_cache import ModelCache, ModelCacheFacts  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SAMPLE = json.loads((ROOT / "scripts" / "fixtures" / "scout-report-sample.json").read_text(encoding="utf-8"))
REPORTED = SAMPLE["heartbeat"]["modelCache"]
KEPT = {"keep": 1, "managedBytes": 12_000_000_000,
        "foreign": {"files": 3, "bytes": 67_300_000_000,
                    "folders": [{"folder": "hand-copied", "files": 2, "bytes": 61_000_000_000},
                                {"folder": "speech", "files": 1, "bytes": 6_300_000_000}]},
        "disk": {"totalBytes": 915_000_000_000, "freeBytes": 412_000_000_000}}


def with_(**parts):
    return {**REPORTED, **parts}


def refused(call, status):
    """True when `call` is refused with this status."""
    try:
        call()
    except AppError as exc:
        return exc.status == status
    return False


def section_a_the_record():
    print("the report's block as the record keeps it:")
    check(ModelCacheFacts.clean(REPORTED) == KEPT,
          "the scout's sample block is kept whole: the setting, what it holds, the foreign files with their folders, the disk")
    check(all(ModelCacheFacts.clean(raw) is None for raw in (None, [], "keep 1", 7, True)),
          "negative: not a block (a scout older than 2.34 sends none) is None — never a block of zeros")
    zero = {"keep": 2, "managedBytes": 0, "foreign": {"files": 0, "bytes": 0, "folders": []},
            "disk": {"totalBytes": 100, "freeBytes": 0}}
    check(ModelCacheFacts.clean(zero) == zero,
          "boundary: a cache with nothing in it and a disk with nothing free say zeros, and zeros are kept — a full disk is a fact")
    check(all(ModelCacheFacts.clean(with_(keep=bad)) is None for bad in (0, -1, True, "3", 2.5, None, [])),
          "negative: a setting that is not a whole number of at least 1 makes the block unreadable — there is no cache that keeps no model")
    check(ModelCacheFacts.clean({k: v for k, v in REPORTED.items() if k != "keep"}) is None, "negative: no setting, no block")
    check(ModelCacheFacts.clean(with_(keep=5))["keep"] == 5,
          "the range of the setting is the scout's to refuse, not this side's: what it reports is kept")

    for bad in (-1, True, "12", 1.5, None):
        check(ModelCacheFacts.clean(with_(managedBytes=bad))["managedBytes"] is None,
              f"negative: what the scout holds said as {bad!r} is unknown, not a number — the rest of the block stays")
    check(ModelCacheFacts.clean({k: v for k, v in REPORTED.items() if k != "managedBytes"})["managedBytes"] is None,
          "negative: no figure for what it holds is unknown, not 0")

    check(ModelCacheFacts.clean({k: v for k, v in REPORTED.items() if k != "foreign"})["foreign"] is None
          and ModelCacheFacts.clean(with_(foreign="none"))["foreign"] is None,
          "negative: no foreign figures is unknown — 'nothing lies there' would be drawn as a clean folder")
    check(all(ModelCacheFacts.clean(with_(foreign={**REPORTED["foreign"], key: bad}))["foreign"] is None
              for key in ("files", "bytes") for bad in (-1, True, "3", None)),
          "negative: a count of foreign files or bytes that cannot be read makes the foreign figures unknown")

    rows = [{"folder": f"f{i}", "files": 1, "bytes": 10 + i} for i in range(12)]
    kept = ModelCacheFacts.clean(with_(foreign={"files": 12, "bytes": 999, "folders": rows}))["foreign"]["folders"]
    check(kept == rows[:8], "boundary: a record keeps the first 8 folders, in the scout's order (biggest first)")
    gaps = [{"folder": "", "files": 1, "bytes": 1}] * 3 + rows[:9]
    check(ModelCacheFacts.clean(with_(foreign={"files": 12, "bytes": 999, "folders": gaps}))["foreign"]["folders"] == rows[:8],
          "negative: rows that cannot be read do not take the places of the 8: three bad rows first, and 8 good ones are still kept")
    messy = [{"folder": "ok", "files": 1, "bytes": 5}, {"folder": "", "files": 1, "bytes": 5}, {"files": 1, "bytes": 5},
             {"folder": "no-size", "files": 1}, {"folder": "negative", "files": 1, "bytes": -5}, "text", None, 7,
             {"folder": "x" * 300, "files": 2, "bytes": 8}]
    got = ModelCacheFacts.clean(with_(foreign={"files": 4, "bytes": 13, "folders": messy}))["foreign"]["folders"]
    check(got == [{"folder": "ok", "files": 1, "bytes": 5}, {"folder": "x" * 200, "files": 2, "bytes": 8}],
          "negative: a folder row with no name, or a count that cannot be read, or not a row, is dropped; a long name is cut to 200")
    check(ModelCacheFacts.clean(with_(foreign={"files": 0, "bytes": 0, "folders": "none"}))["foreign"]["folders"] == [],
          "negative: folders that are not a list are no folders")

    check(ModelCacheFacts.clean(with_(disk=None))["disk"] is None
          and ModelCacheFacts.clean({k: v for k, v in REPORTED.items() if k != "disk"})["disk"] is None,
          "negative: the scout could not measure the disk (null) or said nothing: unknown, so the board draws no figure")
    check(all(ModelCacheFacts.clean(with_(disk=bad))["disk"] is None
              for bad in ({"totalBytes": 0, "freeBytes": 0}, {"totalBytes": 100}, {"freeBytes": 100}, {"totalBytes": "9", "freeBytes": 1},
                          {"totalBytes": 100, "freeBytes": -1}, {"totalBytes": True, "freeBytes": 1}, [100, 1])),
          "negative: a disk of no size, or with a figure missing or unreadable, is unknown")


class FakeScout:
    """A machine's scout: what it was asked, and what it answers by path (an exception is raised, as Scout does on a refusal)."""

    def __init__(self, answers, log):
        self.answers = answers
        self.log = log

    def post(self, path, payload=None, timeout=10):
        self.log.append(("post", path, payload, timeout))
        answer = self.answers[path]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def read(self, path, timeout=10):
        self.log.append(("read", path))
        return self.answers[path]


class Rig:
    """A ModelCache over a stand-in scout and a stand-in store of one machine, `box`, that has a cache record of its own."""

    OLD = {"keep": 1, "managedBytes": 5, "foreign": None, "disk": None}

    def __init__(self, answers, host=True):
        self.log, self.saved = [], []
        self.store = {"hosts": {"box": {"id": "box", "modelCache": dict(self.OLD)}} if host else {}}

        def scout_of(host_id):
            if host_id != "box":
                raise AppError(f"no scout has reported for host {host_id}", 404)
            return FakeScout(answers, self.log)

        self.cache = ModelCache(scout_of, lambda: self.store, lambda: self.saved.append(json.dumps(self.store, sort_keys=True)))

    def record(self):
        return self.store["hosts"].get("box", {}).get("modelCache")


KEEP, DELETE, FACTS = "/api/llama-node/cache/keep", "/api/llama-node/cache/delete-foreign", "/api/llama-node/cache"
TRIMMED = {"ok": True, "keep": 3, "removed": 2, "freedBytes": 30_000_000_000, "waiting": False}


def section_b_the_calls():
    print("the two calls:")
    fresh = {"ok": True, **with_(keep=3, managedBytes=7)}
    rig = Rig({KEEP: TRIMMED, FACTS: fresh})
    got = rig.cache.keep(" box ", 3)
    check(rig.log == [("post", KEEP, {"keep": 3}, 60), ("read", FACTS)],
          "the setting goes to the scout as {keep} and nothing else; the figures are asked again right after (one call each, in this order)")
    check(got == {"ok": True, "hostId": "box", "result": TRIMMED, "modelCache": ModelCacheFacts.clean(fresh)},
          "the answer is the scout's own words (removed, freed, waiting) and the machine's figures now")
    check(rig.record() == ModelCacheFacts.clean(fresh) and rig.record()["keep"] == 3 and len(rig.saved) == 1,
          "the new figures are stored in the machine's record at once, and the state is written once — a board read a moment later shows them")

    rig = Rig({KEEP: {"ok": False, "error": "refused"}, FACTS: {"ok": True, **REPORTED}})
    check(rig.cache.keep("box", 2)["ok"] is False, "negative: the scout says it did not do it — ok is false, not true")

    for bad in ("3", True, None, 2.5, [3], {}):
        rig = Rig({KEEP: TRIMMED, FACTS: fresh})
        check(refused(lambda: rig.cache.keep("box", bad), 400) and rig.log == [] and rig.saved == [],
              f"negative: a setting of {bad!r} is refused with 400 before the scout is asked, and nothing is stored")

    rig = Rig({KEEP: TRIMMED, FACTS: fresh})
    check(refused(lambda: rig.cache.keep("ghost", 3), 404) and rig.log == [],
          "negative: a machine no scout has reported for is refused with 404, and nothing is sent")
    check(refused(lambda: rig.cache.keep("", 3), 404) and refused(lambda: rig.cache.keep(None, 3), 404),
          "negative: no machine named is not a machine")

    quiet = Rig({KEEP: TRIMMED, FACTS: {"ok": False, "error": "box unreachable: timed out"}})
    got = quiet.cache.keep("box", 3)
    check(got["ok"] is True and got["modelCache"] is None and quiet.record() == Rig.OLD and quiet.saved == [],
          "negative: the setting was set but the figures cannot be asked: the record keeps what its last report left, and the answer says it knows no figures")
    garbage = Rig({KEEP: TRIMMED, FACTS: {"ok": True, "keep": 0}})
    check(garbage.cache.keep("box", 3)["modelCache"] is None and garbage.record() == Rig.OLD and garbage.saved == [],
          "negative: figures the scout sent in a form that cannot be read are not stored")
    gone = Rig({KEEP: TRIMMED, FACTS: fresh}, host=False)
    gone.store["hosts"]["ghost"] = {}
    check(refused(lambda: gone.cache.keep("ghost", 3), 404), "a machine forgotten from the board is refused as unknown")

    rig = Rig({DELETE: {"ok": True, "removed": 3, "freedBytes": 67_300_000_000}, FACTS: {"ok": True, **with_(foreign={"files": 0, "bytes": 0, "folders": []})}})
    got = rig.cache.delete_foreign("box", 67_300_000_000)
    check(rig.log == [("post", DELETE, {"expectBytes": 67_300_000_000}, 120), ("read", FACTS)],
          "the deletion goes with the size the operator was shown and with nothing else; the figures are asked again after it")
    check(got["result"]["removed"] == 3 and got["modelCache"]["foreign"] == {"files": 0, "bytes": 0, "folders": []}
          and rig.record()["foreign"]["files"] == 0 and len(rig.saved) == 1,
          "the answer says what went, and the record shows no foreign files any more")

    for bad in ("100", True, None, 1.5, [1]):
        rig = Rig({DELETE: {"ok": True}, FACTS: fresh})
        check(refused(lambda: rig.cache.delete_foreign("box", bad), 400) and rig.log == [],
              f"negative: a size of {bad!r} is refused with 400 — the scout is not asked to delete without the size it was shown")
    rig = Rig({DELETE: {"ok": True}, FACTS: fresh})
    check(rig.cache.delete_foreign("box", 0)["ok"] is True and rig.log[0] == ("post", DELETE, {"expectBytes": 0}, 120),
          "boundary: 0 is a size (nothing was shown to lie there) and goes to the scout, which decides")

    words = "box: the cache changed since it was shown: 70,000,000,000 bytes of files this scout did not download, not 67,300,000,000 — nothing was deleted"
    rig = Rig({DELETE: AppError(words, 502), FACTS: fresh})
    try:
        rig.cache.delete_foreign("box", 67_300_000_000)
        said = None
    except AppError as exc:
        said = (exc.status, str(exc))
    check(said == (502, words) and rig.log == [("post", DELETE, {"expectBytes": 67_300_000_000}, 120)]
          and rig.record() == Rig.OLD and rig.saved == [],
          "negative: the scout refuses because the files changed — its words reach the caller as they are, nothing is asked after, nothing is stored")

    rig = Rig({KEEP: TRIMMED, FACTS: fresh}, host=False)
    rig.store["hosts"]["box"] = {"id": "box"}
    check(rig.cache.keep("box", 3)["modelCache"] == ModelCacheFacts.clean(fresh) and rig.record() == ModelCacheFacts.clean(fresh),
          "a record that had no cache block yet (an older report) gets one from the scout's answer")


def section_c_the_record_the_pull_and_the_node():
    print("the record, the pull and the node:")
    beat = {"host": {"id": "box", "ip": "10.0.0.5"}, "agentUrl": "http://10.0.0.5:8092", "modelCache": REPORTED}
    check(fc.host_from_report(beat)["modelCache"] == KEPT,
          "the heartbeat's block is cleaned into the record")
    check(fc.host_from_report({"host": {"id": "box"}})["modelCache"] is None
          and fc.host_from_report({"host": {"id": "box"}, "modelCache": {"keep": 0}})["modelCache"] is None,
          "negative: a scout that says none, or one that says nothing readable, leaves the record with None — not with zeros")
    pulled = fc.scout_payload_from_state({"host": {"id": "box"}, "modelCache": REPORTED}, "http://10.0.0.5:8092")
    check(pulled["modelCache"] == REPORTED and fc.host_from_report(pulled)["modelCache"] == KEPT,
          "the pull (/api/state) carries the block as the beat does: the two make one record, and the figures do not blink")
    check(fc.scout_payload_from_state({"host": {"id": "box"}}, "x")["modelCache"] is None
          and fc.scout_payload_from_state({"host": {"id": "box"}, "modelCache": "x"}, "x")["modelCache"] is None,
          "negative: a state with no block, or one that is not a block, pulls None")

    import caravan.admin.topology as topology
    saved = topology.topo.power_schedules
    topology.topo.power_schedules = lambda: {}
    try:
        host = {"id": "box", "name": "Box", "ip": "10.0.0.5", "modelCache": KEPT}
        nodes = topology.topology_nodes({}, {"llamaServers": []}, [host, {**host, "id": "old", "modelCache": None},
                                                                     {k: v for k, v in host.items() if k != "modelCache"} | {"id": "bare"}])
    finally:
        topology.topo.power_schedules = saved
    check([n["modelCache"] for n in nodes] == [KEPT, None, None],
          "the machine's node carries the block the board draws the setting from; an older scout's machine — None")


class Handler:
    def __init__(self):
        self.sent = []

    def send_json(self, payload, status=200):
        self.sent.append(payload)


class StubCache:
    def __init__(self):
        self.calls = []

    def keep(self, host_id, keep):
        self.calls.append(("keep", host_id, keep))
        return {"ok": True, "via": "keep"}

    def delete_foreign(self, host_id, expect_bytes):
        self.calls.append(("delete", host_id, expect_bytes))
        return {"ok": True, "via": "delete"}


def section_d_the_routes():
    print("the routes:")
    check(isinstance(fc.MODEL_CACHE, ModelCache) and fc.MODEL_CACHE.scout_of is fc._scout,
          "the controller's cache calls ask the scout of the machine named, as the other client calls do")
    keep_path, delete_path = "/api/topology/client-llama/cache-keep", "/api/topology/client-llama/cache-delete-foreign"
    check(keep_path in routes.POST_ROUTES and delete_path in routes.POST_ROUTES
          and keep_path not in routes.GET_ROUTES and delete_path not in routes.GET_ROUTES,
          "both are POST routes (a viewer account may not call them)")
    stub, real = StubCache(), routes.MODEL_CACHE
    routes.MODEL_CACHE = stub
    try:
        h = Handler()
        routes.POST_ROUTES[keep_path](h, None, {"hostId": "box", "keep": 4, "ignored": 1})
        routes.POST_ROUTES[delete_path](h, None, {"hostId": "box", "expectBytes": 9})
        routes.POST_ROUTES[keep_path](h, None, {})
    finally:
        routes.MODEL_CACHE = real
    check(stub.calls == [("keep", "box", 4), ("delete", "box", 9), ("keep", None, None)] and [s["via"] for s in h.sent] == ["keep", "delete", "keep"],
          "each route hands the body's fields to the call and sends its answer; a body with none hands none, and the call refuses it")


for section in (section_a_the_record, section_b_the_calls, section_c_the_record_the_pull_and_the_node, section_d_the_routes):
    try:
        section()
    except Exception as exc:  # noqa: BLE001 — a crash is a red pin; the rest still runs
        check(False, f"{section.__name__} crashed: {exc!r}")

if _fail:
    print(f"\nFAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("\nmodel cache OK")
