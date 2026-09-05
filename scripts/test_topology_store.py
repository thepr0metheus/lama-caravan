#!/usr/bin/env python3
"""How a cell slot is addressed, pinned before the addressing moves into a class.

A slot is stored under `"<hostId>:<port>"`, and that string is the whole
invariant: the controller answers to two spellings of its id (the machine name it
used to have, and the role sentinel it has now), a port arrives as a string from
one caller and an int from another, and a lookup that builds the key differently
from the write does not fail — it silently addresses a slot that is not there.
Which reads as the cell having no config.

Fifty-two call sites reach into the topology document. The ones that matter are
the ones that build this key, so those are what this photographs: the
canonicalisation, the lookup, the write, the "is this key mine" test the
port-availability check depends on, and the allocator that must never hand out a
port something else already holds.

Every case runs against its own store file; nothing here touches the fleet's.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


def run(script, initial=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "admin.json"
        if initial is not None:
            path.write_text(json.dumps(initial), encoding="utf-8")
        env = dict(os.environ, LLAMA_ADMIN_STATE=str(path), PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                             capture_output=True, text=True)
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return out, stored


KEYS = '''
import json
from caravan.admin.server_cells import server_slot_key
print(json.dumps([
    server_slot_key("controller", 22001),
    server_slot_key("skynet", 22001),      # the id the controller used to have
    server_slot_key("controller", "22001"),
    server_slot_key("client-a", 8012),     # a client id passes through untouched
]))
'''

LOOKUP = '''
import json
from caravan.admin.state import topology_store
from caravan.admin.server_cells import server_slot_key
slots = topology_store().get("serverSlots", {})
print(json.dumps({
    "legacy spelling finds it": slots.get(server_slot_key("skynet", 22001), {}).get("model"),
    "port as a string finds it": slots.get(server_slot_key("controller", "22001"), {}).get("model"),
    "a slot that is not there": slots.get(server_slot_key("controller", 65000)) or {},
    "key membership": server_slot_key("skynet", 22001) in slots,
}, sort_keys=True))
'''

WRITE = '''
from caravan.admin.server_cells import upsert_server_slot
from caravan.admin.state import save_admin_state
upsert_server_slot("skynet", "22007", config={"RUNNER": "whisper"}, model="m.gguf", label="L")
save_admin_state()
'''

PORTS = '''
import json
from caravan.admin.server_cells import used_server_cell_ports, next_server_cell_port
used = used_server_cell_ports()
print(json.dumps({
    "slot ports are used": sorted(p for p in used if 22000 < p < 23000),
    "excluding a slot frees its port": 22001 not in used_server_cell_ports(
        exclude_key="controller:22001"),
    "the next free one": next_server_cell_port(),
}, sort_keys=True))
'''

REFUSE = '''
from caravan.admin.server_cells import assert_server_cell_port_available
from caravan.common.errors import AppError
for label, args in (("taken", (22001, None)),
                    ("taken but excluded", (22001, "controller:22001")),
                    ("out of range", (70000, None)),
                    ("free", (22999, None))):
    try:
        assert_server_cell_port_available(args[0], exclude_key=args[1])
        print(label, "-> ok")
    except AppError as exc:
        print(label, "->", exc)
'''

FIXTURE = {"topology": {"serverSlots": {
    "controller:22001": {"id": "controller:22001", "hostId": "controller",
                         "port": 22001, "model": "gemma.gguf"},
    "controller:22002": {"id": "controller:22002", "hostId": "controller",
                         "port": 22002, "model": "qwen.gguf"},
    "client-a:22050": {"id": "client-a:22050", "hostId": "client-a",
                       "port": 22050, "model": "x.gguf"},
}}}


def main():
    out, _ = run(KEYS)
    if out.returncode == 0:
        keys = json.loads(out.stdout)
        check("the controller's two spellings make one key", keys[0] == keys[1], str(keys))
        check("a port is a port whether it arrived as text or a number",
              keys[0] == keys[2], str(keys))
        check("a client id passes through", keys[3] == "client-a:8012", str(keys))
    else:
        check("slot keys build", False, out.stderr.strip()[-300:])

    out, _ = run(LOOKUP, FIXTURE)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a legacy spelling finds the canonical record",
              got["legacy spelling finds it"] == "gemma.gguf", str(got))
        check("a port given as text finds the same record",
              got["port as a string finds it"] == "gemma.gguf", str(got))
        check("a slot that is not there is empty, not an error",
              got["a slot that is not there"] == {}, str(got))
        check("membership answers for the legacy spelling too",
              got["key membership"] is True, str(got))
    else:
        check("slot lookup", False, out.stderr.strip()[-300:])

    out, stored = run(WRITE, FIXTURE)
    if out.returncode == 0 and stored:
        slots = stored["topology"]["serverSlots"]
        check("a write under the old spelling lands on the canonical key",
              "controller:22007" in slots and "skynet:22007" not in slots,
              str(sorted(slots)))
        slot = slots.get("controller:22007", {})
        check("the record carries its own key and host",
              slot.get("id") == "controller:22007" and slot.get("hostId") == "controller",
              str(slot))
        check("the port is stored as a number",
              isinstance(slot.get("port"), int), repr(slot.get("port")))
        check("what was passed is what was stored",
              slot.get("model") == "m.gguf" and (slot.get("config") or {}).get("RUNNER") == "whisper",
              str(slot))
    else:
        check("slot write", False, out.stderr.strip()[-300:])

    out, _ = run(PORTS, FIXTURE)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("every slot's port counts as taken",
              got["slot ports are used"] == [22001, 22002, 22050], str(got))
        check("a cell does not block its own port",
              got["excluding a slot frees its port"] is True, str(got))
        check("the allocator hands out a free number",
              got["the next free one"] not in (22001, 22002, 22050), str(got))
    else:
        check("port bookkeeping", False, out.stderr.strip()[-300:])

    out, _ = run(REFUSE, FIXTURE)
    if out.returncode == 0:
        lines = dict(line.split(" -> ") for line in out.stdout.strip().split("\n"))
        check("a taken port is refused with its number",
              "22001" in lines["taken"] and "reserved" in lines["taken"], str(lines))
        check("the cell's own port is not refused to it",
              lines["taken but excluded"] == "ok", str(lines))
        check("a port outside the range is refused",
              "between 1 and 65535" in lines["out of range"], str(lines))
        check("a free port is allowed", lines["free"] == "ok", str(lines))
    else:
        check("port refusals", False, out.stderr.strip()[-300:])

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
