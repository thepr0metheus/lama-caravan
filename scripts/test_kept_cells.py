#!/usr/bin/env python3
"""Snapshot: the cells a scout keeps become records of a controller that lacks them (1.3.504).

The defect (2026-10-12). A stopped cell is drawn from the controller's own record of it: the
scout drops a stopped cell from its report. The controller moved to the NAS had no record of
a machine's cells — the old controller had started them — and every cell went off the board as it
was stopped: its row, its switch, and the kanban's cable to it ("no such model").

Pinned by value, against the real files in a scratch data directory: a record is made from each
kept start request (scout 2.26, `autostartRequests`) the controller lacks — the settings whole, an
empty value too, the model, the cache switch — and none that exists is touched; what is no request,
a number another record holds and the controller's own machine make none; the heartbeat and the
pull both bring it. A deletion takes the kept request away before the record goes, and a port move
takes it from the old port before the records move and gives it to the new one after; a refused
move puts it back. A scout out of reach is said in the answer, not hidden.

Run: python3 scripts/test_kept_cells.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-kept-cells-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
for sub in ("state", "config", "secrets", "logs"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

import caravan.admin.cell_ops as cell_ops  # noqa: E402
import caravan.admin.fleet_clients as fc  # noqa: E402
from caravan.admin.server_cells import KeptCells, upsert_server_slot  # noqa: E402
from caravan.admin.state import topology as topo  # noqa: E402
from caravan.admin.state import topology_store  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

SAMPLE = json.loads((ROOT / "scripts" / "fixtures" / "scout-report-sample.json").read_text(encoding="utf-8"))
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def clean():
    store = topology_store()
    store["serverSlots"] = {}
    store["hosts"] = {}


def kept(config, model="", cache=False):
    return {"config": config, "modelPath": model, "cacheModels": cache}


def test_adopt():
    print("a record of each cell the scout keeps and the controller lacks:")
    clean()
    upsert_server_slot("box", 22001, config={"PORT": "22001", "MODEL_FILE": "mine.gguf"}, model="mine.gguf")
    upsert_server_slot("other", 22005, config={"PORT": "22005"}, model="x.gguf")
    said = []
    desk = KeptCells(log=said.append)
    made = desk.adopt("box", {
        "22001": kept({"PORT": "22001", "MODEL_FILE": "theirs.gguf"}, "theirs.gguf"),
        "22003": kept({"PORT": "22003", "RUNNER": "transcribe", "EXTRA_ARGS": ""}, "gigaam.gguf", True),
        "22005": kept({"PORT": "22005"}, "y.gguf"),
        "junk": kept({"PORT": "1"}),
        "22030": {"modelPath": "no-settings.gguf"},
        "70000": kept({"PORT": "70000"}),
        "22031": "not a request",
    })
    slots = topo.slots()
    check(made == [22003], f"made only for the cell it lacked (got {made})")
    new = slots.get("box:22003") or {}
    check(new.get("config") == {"PORT": "22003", "RUNNER": "transcribe", "EXTRA_ARGS": ""} and new.get("model") == "gigaam.gguf"
          and new.get("cacheModels") is True and new.get("adoptedFrom") == "scout",
          "the settings whole — an empty value too, a flag taken off — the model, the cache switch, and where it came from")
    check(slots["box:22001"]["config"] == {"PORT": "22001", "MODEL_FILE": "mine.gguf"} and slots["box:22001"]["model"] == "mine.gguf"
          and not any("22001" in line for line in said),
          "negative: a record the controller has is not touched — it is the operator's, edited on the board — and not said: "
          "every report would write the line again")
    check("box:22005" not in slots and any("22005" in line and "taken" in line for line in said),
          "negative: a number another machine's cell holds makes no record, and the log says so")
    check(not {"box:22030", "box:22031", "box:70000"} & set(slots) and any("[22003]" in line for line in said),
          "negative: no settings, not a request, a number out of range — no record; the log names what was made")
    check(desk.adopt("box", {"22003": kept({"PORT": "22003"})}) == [] and slots["box:22003"]["config"]["RUNNER"] == "transcribe",
          "a second report makes nothing: the record is there now")
    check([desk.adopt("box", None), desk.adopt("box", ["22009"]), desk.adopt("", {"22009": kept({})}),
           desk.adopt("controller", {"22009": kept({"PORT": "22009"})})] == [[], [], [], []] and "box:22009" not in topo.slots(),
          "negative: no requests, a list, no machine, the controller's own machine — nothing")


def test_reports_bring_it():
    print("the heartbeat and the pull both bring them:")
    clean()
    beat = copy.deepcopy(SAMPLE["heartbeat"])
    fc.record_host_report(beat)
    slot = topo.slots().get("box-a:22001") or {}
    check(slot.get("adoptedFrom") == "scout" and slot.get("config") == beat["autostartRequests"]["22001"]["config"],
          f"a heartbeat with a kept request the controller lacks makes its record (got {sorted(topo.slots())})")
    check("autostartRequests" not in topology_store()["hosts"]["box-a"],
          "negative: the machine's record does not keep them — the cells' records are made from them")
    clean()
    pulled = fc.scout_payload_from_state(copy.deepcopy(SAMPLE["state"]), "http://10.0.0.5:8092")
    check(pulled.get("autostartRequests") == SAMPLE["state"]["autostartRequests"],
          "the pull carries them as the heartbeat does")
    fc.record_host_report(pulled, only_known=True)
    check(topo.slots() == {}, "negative: a pull of a machine the board does not hold makes nothing")
    clean()

    def broken(host_id, requests):
        raise ValueError("a kept request it cannot read")
    real, fc.KEPT_CELLS.adopt = fc.KEPT_CELLS.adopt, broken
    try:
        stored = fc.record_host_report(copy.deepcopy(SAMPLE["heartbeat"]))
    finally:
        fc.KEPT_CELLS.adopt = real
    check(stored is not None and topology_store()["hosts"].get("box-a", {}).get("id") == "box-a",
          "negative: the records of the cells failing to be made leaves the machine's report stored — it is the machine's word first")


class Scout:
    """The scout's autostart door as the controller calls it: what was asked, in order."""

    def __init__(self, fail=False):
        self.asked, self.fail = [], fail

    def __call__(self, body, enabled):
        self.asked.append((int(body["port"]), enabled, topo.has_slot(body["hostId"], body["port"])))
        if self.fail:
            raise AppError("scout box is unreachable", 502)
        return {"ok": True}


def autostart_on(host_id, *ports):
    topology_store()["hosts"][host_id] = {"id": host_id, "autostart": list(ports)}


def test_delete_takes_the_request():
    print("a deleted cell's request goes first:")
    clean()
    autostart_on("box", 22003)
    upsert_server_slot("box", 22003, config={"PORT": "22003", "MODEL_FILE": "m.gguf"}, model="m.gguf")
    scout, stops = Scout(), []
    real_stop, real_auto = cell_ops.client_llama_stop, cell_ops.CELL_AUTOSTART.autostart
    cell_ops.client_llama_stop, cell_ops.CELL_AUTOSTART.autostart = (lambda b: stops.append(b["port"])), scout
    try:
        answer = cell_ops.client_server_slot_delete({"hostId": "box", "port": 22003})
        check(scout.asked == [(22003, False, True)] and answer.get("autostart") == {"port": 22003, "enabled": False, "ok": True}
              and answer["removed"] is True and stops == [22003] and not topo.has_slot("box", 22003),
              "off at the scout while the record still stood, then the record, then the stop; the answer says it")
        upsert_server_slot("box", 22004, config={"PORT": "22004"}, model="m.gguf")
        quiet = cell_ops.client_server_slot_delete({"hostId": "box", "port": 22004})
        check(len(scout.asked) == 1 and "autostart" not in quiet, "negative: a cell its scout keeps no request for — nothing asked")
        upsert_server_slot("box", 22003, config={"PORT": "22003"}, model="m.gguf")
        cell_ops.CELL_AUTOSTART.autostart = Scout(fail=True)
        failed = cell_ops.client_server_slot_delete({"hostId": "box", "port": 22003})
        check(failed["removed"] is True and failed.get("autostart", {}).get("ok") is False
              and "unreachable" in failed["autostart"].get("error", ""),
              "a scout out of reach: the record goes as asked, and the answer says the request stayed")
    finally:
        cell_ops.client_llama_stop, cell_ops.CELL_AUTOSTART.autostart = real_stop, real_auto


def test_moves_take_the_request():
    print("a moved cell's request moves with it:")
    clean()
    autostart_on("box", 22003, 22004)
    for port in (22003, 22004, 22006):
        upsert_server_slot("box", port, config={"PORT": str(port), "MODEL_FILE": f"m{port}.gguf"}, model=f"m{port}.gguf")
    scout = Scout()
    desk = cell_ops.CellAutostart(autostart=scout)

    def move(old, new):
        store = topology_store()["serverSlots"]
        slot = store.pop(f"box:{old}")
        slot.update({"id": f"box:{new}", "port": new})
        store[f"box:{new}"] = slot
        return {"ok": True}

    result, said = desk.moved([("box", 22003, 22009)], lambda: move(22003, 22009))
    check(result == {"ok": True} and scout.asked == [(22003, False, True), (22009, True, True)]
          and [s["ok"] for s in said] == [True, True],
          "off on the old port while its record still stood there, the move, then on at the new one — from the record there")
    scout.asked.clear()
    desk.moved([("box", 22006, 22010)], lambda: move(22006, 22010))
    check(scout.asked == [], "negative: a cell its scout keeps no request for — nothing asked")

    def refused():
        raise AppError("server cell port 22004 is already reserved", 409)
    scout.asked.clear()
    try:
        desk.moved([("box", 22004, 22011)], refused)
        raised = None
    except AppError as exc:
        raised = exc.status
    check(raised == 409 and scout.asked == [(22004, False, True), (22004, True, True)],
          "a refused move puts the request back on its port, and the refusal stands")
    scout.asked.clear()
    autostart_on("box", 22009, 22004)

    def swap():
        store = topology_store()["serverSlots"]
        a, b = store.pop("box:22009"), store.pop("box:22004")
        a.update({"id": "box:22004", "port": 22004})
        b.update({"id": "box:22009", "port": 22009})
        store["box:22004"], store["box:22009"] = a, b
        return {"ok": True}
    desk.moved([("box", 22009, 22004), ("box", 22004, 22009)], swap)
    check(scout.asked == [(22009, False, True), (22004, False, True), (22004, True, True), (22009, True, True)],
          "two cells trading ports: both off first — else one would take the other's new request away — then both on")


def main():
    for fn in (test_adopt, test_reports_bring_it, test_delete_takes_the_request, test_moves_take_the_request):
        fn()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("kept cells OK: a record of each cell the scout keeps and the controller lacks; deletions and moves take the request along")
    return 0


if __name__ == "__main__":
    sys.exit(main())
