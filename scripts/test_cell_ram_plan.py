#!/usr/bin/env python3
"""Value snapshot: what a cell of a launch config keeps in its machine's memory, for the cell form's RAM scale (1.3.574).

The owner, 2026-10-18, looking at the form of a Strata cell: "I do not see the planned amount of RAM on the scale on the right" — the VRAM scale
said "≈ 31.4 GB", the RAM scale only what was in use. The figure is the runner's own promise (Runner.ram_reservation), the one a start sends the
scout, which refuses a start by it; the form asks the controller (POST /api/cell-ram-plan, CellRamPlan), so the rule has one copy.

Pinned: the answer for a Strata pack by the library's size, by Strata's own table when nobody can size the file, and for the runners that promise
nothing; that only the runner that overrides ram_reservation says `keepsRam` in the registry (a new one is named here, to be decided); the room the
scout leaves the system; that a config that cannot be read answers nothing and does not fail; and the route.

Each claim has a positive and a negative pin.

Run: python3 scripts/test_cell_ram_plan.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin import routes  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.domain.runner import registry_json  # noqa: E402

_fail = []
GIB = 2 ** 30


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SWIFT = "Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ukisai/IQ3_S/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf"
ISTA = "Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ISTA-DASLab/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf"
UD = "Qwen3.8-Flash-Next-GGUF/unsloth/UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf"
TMP = Path(tempfile.mkdtemp(prefix="caravan-ram-plan-"))


def listing(path, size):
    return [{"id": "lib", "name": "NAS", "state": "ok", "path": "/mnt/lib", "files": [{"path": path, "size": size, "mtime": 1}]}]


def plan(config, libraries=()):
    keep = fc.current_locations, fc.controller_models_dir
    fc.current_locations = lambda wait=False: Locations(list(libraries))
    fc.controller_models_dir = lambda: TMP
    try:
        return fc.CellRamPlan.of(config)
    finally:
        fc.current_locations, fc.controller_models_dir = keep


def section_a_strata_pack():
    print("a Strata pack:")
    swift = plan({"RUNNER": "strata", "MODEL_FILE": SWIFT}, listing(SWIFT, 44900816736))
    check(swift == {"runner": "strata", "headroomMiB": 2048,
                    "ram": {"reserveMiB": 51507 + 1024, "who": "Strata", "why": "its experts stay in memory: 50.3 GiB (Strata's table for this pack)",
                            "lower": "nothing — stop another cell"}},
          "Swift 1.5's IQ3_S, the library says its first part is 41.8 GiB: the answer is Strata's own 50.3 GiB of experts plus a GiB — the figure the start sends the scout, "
          "not the first part's 42.8 GiB that let a start in and had systemd-oomd kill the cell four times (2026-10-18)")
    table = plan({"RUNNER": "strata", "MODEL_FILE": SWIFT})
    check(table["ram"] == swift["ram"], "no library, no file on the disk: the same figure — the table needs no size, so a form that cannot reach the library still says it")
    ista = plan({"RUNNER": "strata", "MODEL_FILE": ISTA}, listing(ISTA, 51 * GIB + 100 * 2 ** 20))
    check(ista["ram"]["reserveMiB"] == 51 * 1024 + 100 + 1024 and ista["ram"]["why"] == "its weights stay in memory: 51.1 GiB",
          "negative: ISTA-DASLab's own IQ3_S holds all its experts in its first part, more than the table's 50.3 GiB: the first part's size, as before")
    ud = plan({"RUNNER": "strata", "MODEL_FILE": UD}, listing(UD, 10 * 2 ** 20))
    check(ud["ram"]["reserveMiB"] == 48 * 1024 and "a budget of its experts" in ud["ram"]["why"],
          "an Unsloth ~4-bit pack keeps a budget of its experts: 48 GiB, whatever its 10 MB header weighs")
    check(plan({"RUNNER": "strata", "MODEL_FILE": "org/Unknown-Quant/Some-Pack-00001-of-00002.gguf"})["ram"] is None
          and plan({"RUNNER": "strata"})["ram"] is None,
          "negative: a pack the table does not know and nobody can size, and a Strata cell with no model yet — no promise, and none made up from a guess")


def section_runners_that_promise_nothing():
    print("runners that promise nothing:")
    llama = plan({"MODEL_FILE": "org/m.gguf"}, listing("org/m.gguf", 9 * GIB))
    check(llama == {"runner": "llama-server", "ram": None, "headroomMiB": 2048},
          "llama.cpp maps its file and pages it as it is read: no promise, whatever the file weighs — the form draws the RAM scale as before")
    check(plan({})["ram"] is None and plan({"RUNNER": "whisper", "MODEL_FILE": "left.gguf"})["ram"] is None and plan({"RUNNER": "no-such-runner"})["ram"] is None,
          "negative: an empty config, whisper, a runner nobody knows — no promise, and no failure")
    check(plan({"RUNNER": "strata", "MODEL_FILE": ["not", "a", "name"]})["ram"] is None and plan({"RUNNER": "strata", "MODEL_FILE": None})["ram"] is None,
          "negative: a model field that is not a name answers nothing; it does not fail the form")


def section_the_registry_and_the_policy():
    print("the registry and the room for the system:")
    keeps = sorted(row["id"] for row in registry_json() if row["keepsRam"])
    check(keeps == ["strata"],
          f"only the runner that overrides ram_reservation says keepsRam — Strata (got {keeps}): a new one is named here, and the form starts asking for it only once someone decided it should")
    check(all(isinstance(row["keepsRam"], bool) for row in registry_json()), "negative: every row says it, as a flag — the form reads it, never a missing key")
    check(fc.CellRamPlan.HEADROOM_MIB == 2048,
          "the room the scout leaves the system is its MemoryLedger.HEADROOM_MIB (caravan-scout 2.32+): 2 GiB — the form counts the same cut the scout makes")


def section_the_route():
    print("the route:")
    sent = []

    class Handler:
        def send_json(self, body, status=200):
            sent.append(body)

    handler = Handler()
    keep = fc.current_locations, fc.controller_models_dir
    fc.current_locations = lambda wait=False: Locations([])
    fc.controller_models_dir = lambda: TMP
    try:
        routes._post_api_cell_ram_plan(handler, None, {"config": {"RUNNER": "strata", "MODEL_FILE": SWIFT}})
        routes._post_api_cell_ram_plan(handler, None, {"config": "nope"})
        routes._post_api_cell_ram_plan(handler, None, {})
    finally:
        fc.current_locations, fc.controller_models_dir = keep
    check(sent[0]["ok"] is True and sent[0]["runner"] == "strata" and sent[0]["ram"]["reserveMiB"] == 52531 and sent[0]["headroomMiB"] == 2048,
          "the route answers ok with the runner, the promise and the room for the system")
    check(sent[1] == {"ok": True, "runner": "llama-server", "ram": None, "headroomMiB": 2048} and sent[2] == sent[1],
          "negative: a config that is not an object, or no config — answered as an empty config, no promise, no error")
    check("/api/cell-ram-plan" in routes.POST_ROUTES and "/api/cell-ram-plan" not in routes.GET_ROUTES,
          "the route is a POST (the config travels in the body): in the table of POST routes, not in the GET table")


section_a_strata_pack()
section_runners_that_promise_nothing()
section_the_registry_and_the_policy()
section_the_route()
print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("cell ram plan OK: the promise by library size and by Strata's table, the registry flag, the room for the system, the route")
