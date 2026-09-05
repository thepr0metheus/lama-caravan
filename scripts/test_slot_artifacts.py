#!/usr/bin/env python3
"""Only a controller cell has a start.sh here — pinned, because forgetting it cost a bug.

A cell configured on the CONTROLLER gets generated launch files on this machine:
start.sh (what systemd runs) and cell.json (the snapshot a human reads). A cell
on a CLIENT host gets none: the controller builds its command and hands it to
the scout at start, and there is no local file to write.

That asymmetry is written out three times in server_cells.py — once where a slot
is saved, once where its port is reassigned, once where two cells swap ports —
and it is exactly the fact whose absence produced a real defect: the cell modal
read the command from the artifact, so every client cell reported "not saved
yet" about a command it was serving traffic with.

So the rule is pinned per CASE, not per call site: controller vs client, across
all three writers, plus what happens to the files when a port moves.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The cases below run in child processes with their own environment, but the
# null-tolerance check calls into the module directly, so the parent needs the
# package on its path too.
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


def run(body, slots=None):
    script = ("import json, sys\n"
              "from caravan.admin import server_cells as sc\n"
              "from caravan.admin.state import topology as topo, save_admin_state\n"
              "from caravan.common.errors import AppError\n"
              "def attempt(fn, *a, **k):\n"
              "    try: return {'ok': fn(*a, **k)}\n"
              "    except AppError as exc: return {'refused': str(exc)}\n"
              + body)
    with tempfile.TemporaryDirectory() as tmp:
        admin = Path(tmp) / "admin.json"
        cells = Path(tmp) / "cells"
        if slots is not None:
            admin.write_text(json.dumps({"topology": {"serverSlots": slots}}), encoding="utf-8")
        env = dict(os.environ, LLAMA_ADMIN_STATE=str(admin),
                   LAMA_CARAVAN_SERVER_CELLS_DIR=str(cells),
                   LLAMA_MODELS_DIR=str(Path(tmp) / "models"),
                   HOME=tmp, PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                             capture_output=True, text=True)
        written = sorted(p.name for p in cells.glob("*")) if cells.exists() else []
        files = {}
        if cells.exists():
            for d in cells.iterdir():
                files[d.name] = sorted(f.name for f in d.iterdir())
        return out, written, files


CMD = {"RUNNER": "custom", "COMMAND": "bash ~/run_x.sh $PORT", "PORT": "22100"}


def null_tolerance():
    """A slot whose artifact is null must not take the board down with it.

    `.get("artifact", {})` supplies its default only when the key is ABSENT; a
    stored null sails past it and raises three frames away, inside the loop that
    builds every card. Nothing wraps that, so the whole board renders blank.
    Nothing WRITES a null — both writers guard with `if artifact:` — so this is
    about a document someone repaired by hand, which is precisely when the board
    has to keep working.
    """
    import importlib
    topo_mod = importlib.import_module("caravan.admin.topology")
    cases = [("ключа нет", {"config": {}}),
             ("значение null", {"artifact": None, "config": {}}),
             ("слота нет", None),
             ("пустой словарь", {"artifact": {}, "config": {}})]
    for name, slot in cases:
        try:
            got = topo_mod._saved_command(slot, (slot or {}).get("config") or {}, True)
            check(f"artifact — {name}: отвечает, а не падает", got == "", repr(got))
        except Exception as exc:  # noqa: BLE001
            check(f"artifact — {name}: отвечает, а не падает", False,
                  f"{type(exc).__name__}: {exc}")


def main():
    null_tolerance()
    # ── saving a slot ────────────────────────────────────────────────────────
    out, ports, files = run('''
sc.upsert_server_slot("controller", 22100, config=dict(%r), model="", label="c")
save_admin_state()
print(json.dumps({"artifact": bool(topo.slot("controller", 22100).get("artifact"))}))
''' % CMD)
    if out.returncode == 0:
        check("a controller cell is given launch files",
              json.loads(out.stdout)["artifact"] is True and ports == ["22100"], str(ports))
        check("both files are written: what runs it and what describes it",
              files.get("22100") == ["cell.json", "start.sh"], str(files))
    else:
        check("controller slot save", False, out.stderr.strip()[-400:])

    out, ports, _ = run('''
sc.upsert_server_slot("client-a", 22100, config=dict(%r), model="", label="c")
save_admin_state()
print(json.dumps({"artifact": bool(topo.slot("client-a", 22100).get("artifact"))}))
''' % CMD)
    if out.returncode == 0:
        check("a client cell is given none — there is nothing here to run it",
              json.loads(out.stdout)["artifact"] is False, out.stdout.strip())
        check("…and nothing is written to disk for it", ports == [], str(ports))
    else:
        check("client slot save", False, out.stderr.strip()[-400:])

    # ── moving a cell to another port ────────────────────────────────────────
    out, ports, files = run('''
sc.upsert_server_slot("controller", 22100, config=dict(%r), model="", label="c")
save_admin_state()
sc.reassign_server_slot_port({"hostId": "controller", "port": 22100, "newPort": 22101})
slot = topo.slot("controller", 22101)
print(json.dumps({"moved": bool(slot), "artifact": bool(slot.get("artifact")),
                  "old gone": not topo.find_slot("controller", 22100),
                  "port in config": (slot.get("config") or {}).get("PORT")}))
''' % CMD)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a reassigned controller cell keeps its slot", got["moved"] is True, str(got))
        check("…gets launch files for the NEW port", got["artifact"] is True, str(got))
        check("…and its config says the new port", got["port in config"] == "22101", str(got))
        check("the old key is gone, so one cell is not two", got["old gone"] is True, str(got))
        check("a start.sh exists for the new port", "22101" in files, str(sorted(files)))
    else:
        check("reassign", False, out.stderr.strip()[-400:])

    out, _, files = run('''
sc.upsert_server_slot("client-a", 22100, config=dict(%r), model="", label="c")
save_admin_state()
sc.reassign_server_slot_port({"hostId": "client-a", "port": 22100, "newPort": 22101})
slot = topo.slot("client-a", 22101)
print(json.dumps({"moved": bool(slot), "artifact": bool(slot.get("artifact")),
                  "port in config": (slot.get("config") or {}).get("PORT")}))
''' % CMD)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a reassigned client cell moves too", got["moved"] is True, str(got))
        check("…still without launch files", got["artifact"] is False, str(got))
        check("…and its config still follows the port", got["port in config"] == "22101", str(got))
        check("nothing is written for a client on reassign", files == {}, str(files))
    else:
        check("client reassign", False, out.stderr.strip()[-400:])

    # ── two cells trading ports ──────────────────────────────────────────────
    out, _, files = run('''
sc.upsert_server_slot("controller", 22100, config=dict(%r), model="", label="a")
sc.upsert_server_slot("controller", 22101, config=dict(%r), model="", label="b")
save_admin_state()
# The other cell is named by PORT alone: a cell port is unique fleet-wide,
# so a swap does not need to be told which host the partner is on.
sc.swap_server_slot_ports({"hostId": "controller", "port": 22100, "targetPort": 22101})
a, b = topo.slot("controller", 22100), topo.slot("controller", 22101)
print(json.dumps({"a label": a.get("label"), "b label": b.get("label"),
                  "a artifact": bool(a.get("artifact")), "b artifact": bool(b.get("artifact")),
                  "a port": (a.get("config") or {}).get("PORT"),
                  "b port": (b.get("config") or {}).get("PORT")}))
''' % (CMD, dict(CMD, PORT="22101")))
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("the two cells trade places", got["a label"] == "b" and got["b label"] == "a", str(got))
        check("each ends up with launch files again",
              got["a artifact"] is True and got["b artifact"] is True, str(got))
        check("each config carries the port it now sits on",
              got["a port"] == "22100" and got["b port"] == "22101", str(got))
    else:
        check("swap", False, out.stderr.strip()[-400:])

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
