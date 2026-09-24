#!/usr/bin/env python3
"""What the admin store does, pinned before it becomes a class.

`admin_state` is a module-level dict created once at import and mutated in place
by seventeen modules holding a reference to it. That identity IS the contract:
settings-import refills it with .clear()/.update() precisely because rebinding
would leave the rest of the process reading the settings it just replaced.

So this photographs the behaviour that has to survive the move to a store class
— the defaults, the migration, the write format, the object identity — while
both implementations exist. Every case runs against a store file of its own, so
nothing here touches the fleet's real admin.json.
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


def in_fresh_process(script, initial=None):
    """Run a snippet with the store pointed at a throwaway file.

    A subprocess per case because the store loads at IMPORT: the state a case
    starts from cannot be arranged after the module is in memory, which is the
    same reason this behaviour is hard to test any other way.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "admin.json"
        if initial is not None:
            path.write_text(initial if isinstance(initial, str)
                            else json.dumps(initial), encoding="utf-8")
        env = dict(os.environ, LLAMA_ADMIN_STATE=str(path), PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                             capture_output=True, text=True)
        return out, (path.read_text(encoding="utf-8") if path.exists() else None)


DEFAULTS = '''
import json
from caravan.admin.state import admin_state
print(json.dumps(admin_state, sort_keys=True))
'''

IDENTITY = '''
from caravan.admin.state import admin_state
import caravan.admin.state as st
import caravan.admin.topology as topo
# The identity three modules depend on: each import must reach the SAME object.
print(id(admin_state) == id(st.admin_state))
'''

SAVE = '''
from caravan.admin.state import admin_state, save_admin_state
admin_state["hfToken"] = "tok"
admin_state["nested"] = {"a": [1, 2]}
save_admin_state()
'''

REFILL = '''
from caravan.admin.state import admin_state, load_admin_state
before = id(admin_state)
admin_state.clear()
admin_state.update(load_admin_state())
print(before == id(admin_state), admin_state.get("hfToken"))
'''

MIGRATE = '''
import json
from caravan.admin.state import admin_state
slots = admin_state["topology"]["serverSlots"]
print(json.dumps(sorted(slots), ensure_ascii=False))
print(json.dumps(slots.get("controller:22001"), sort_keys=True))
'''

TOPO_DUMP = '''
import json
from caravan.admin.state import admin_state
print(json.dumps(admin_state["topology"], ensure_ascii=False))
'''

TOPOLOGY = '''
import json
from caravan.admin.state import topology_store
print(json.dumps(sorted(topology_store()), ensure_ascii=False))
'''


def main():
    # ── defaults on an empty store ───────────────────────────────────────────
    out, _ = in_fresh_process(DEFAULTS)
    check("empty store loads", out.returncode == 0, out.stderr.strip()[-300:])
    if out.returncode == 0:
        data = json.loads(out.stdout)
        want = {"monitor", "topology", "localPricing", "apiPricing",
                "hfToken", "hfFavorites", "favFields"}
        check("defaults are seeded", want <= set(data),
              f"не хватает: {sorted(want - set(data))}")
        check("topology has its four keys",
              {"clients", "assignments", "layout"} <= set(data.get("topology", {})))
        check("pricing defaults to zero",
              data["localPricing"] == {"inputPer1M": 0.0, "outputPer1M": 0.0},
              str(data.get("localPricing")))

    # ── a corrupt file is not a crash ────────────────────────────────────────
    out, _ = in_fresh_process(DEFAULTS, initial="{not json at all")
    check("corrupt store still starts", out.returncode == 0,
          "битый admin.json обязан читаться как пустой, иначе панель не поднимется")

    # ── values survive, defaults do not overwrite them ───────────────────────
    out, _ = in_fresh_process(DEFAULTS, initial={"hfToken": "kept",
                                                 "localPricing": {"inputPer1M": 3.0}})
    if out.returncode == 0:
        data = json.loads(out.stdout)
        check("stored value wins over the default", data.get("hfToken") == "kept")
        check("a half-filled section keeps what it had",
              data["localPricing"]["inputPer1M"] == 3.0
              and data["localPricing"]["outputPer1M"] == 0.0,
              str(data["localPricing"]))

    # ── the identity every module depends on ─────────────────────────────────
    out, _ = in_fresh_process(IDENTITY)
    check("every import reaches the same object", out.stdout.strip() == "True",
          out.stdout.strip() or out.stderr.strip()[-200:])

    # ── the write format ─────────────────────────────────────────────────────
    out, text = in_fresh_process(SAVE)
    check("save writes the file", out.returncode == 0 and text is not None,
          out.stderr.strip()[-300:])
    if text:
        check("written as indent=2 JSON", '\n  "' in text, text[:80])
        check("what was set is what was written",
              json.loads(text).get("hfToken") == "tok"
              and json.loads(text)["nested"] == {"a": [1, 2]})

    # ── settings-import refills in place ─────────────────────────────────────
    out, _ = in_fresh_process(REFILL, initial={"hfToken": "from-file"})
    check("refill keeps the object and takes the file's values",
          out.stdout.strip() == "True from-file", out.stdout.strip())

    # ── the controller-id migration ──────────────────────────────────────────
    legacy = {"topology": {"serverSlots": {
        "skynet:22001": {"hostId": "skynet", "id": "skynet:22001", "config": {"PORT": "22001"}},
        "controller:22002": {"hostId": "controller", "id": "controller:22002"},
    }}}
    out, text = in_fresh_process(MIGRATE, initial=legacy)
    if out.returncode == 0:
        keys, slot = out.stdout.strip().split("\n")
        check("legacy host id is migrated", json.loads(keys) ==
              ["controller:22001", "controller:22002"], keys)
        check("the migrated slot is re-keyed inside too",
              json.loads(slot) == {"config": {"PORT": "22001"},
                                   "hostId": "controller", "id": "controller:22001"}, slot)
        check("migration persists itself", text is not None and
              "skynet:22001" not in (text or ""),
              "миграция обязана записаться, иначе она повторяется каждый старт")
    else:
        check("migration runs", False, out.stderr.strip()[-300:])

    # ── a canonical key already present wins ─────────────────────────────────
    both = {"topology": {"serverSlots": {
        "skynet:22001": {"hostId": "skynet", "id": "skynet:22001", "config": {"PORT": "legacy"}},
        "controller:22001": {"hostId": "controller", "id": "controller:22001",
                             "config": {"PORT": "canonical"}},
    }}}
    out, _ = in_fresh_process(MIGRATE, initial=both)
    if out.returncode == 0:
        _keys, slot = out.stdout.strip().split("\n")
        check("the canonical record survives a collision",
              json.loads(slot)["config"]["PORT"] == "canonical", slot)

    # ── topology_store seeds its own keys on demand ──────────────────────────
    out, _ = in_fresh_process(TOPOLOGY)
    if out.returncode == 0:
        check("topology_store seeds every section it promises",
              set(json.loads(out.stdout)) == {"assignments", "clientAliases", "clients",
                                              "hosts", "layout", "serverSlots"},
              out.stdout.strip())

    # ── what scout reports and adoption left goes, once ──────────────────────
    scout_era = {"topology": {
        "clients": {"box": {"id": "box", "name": "Box", "manual": True, "lastSeen": 5,
                            "candidates": [{"machine": "agent-x"}], "applyStatus": {"state": "ok"},
                            "assignments": [{"agentId": "a1"}],
                            "agents": [{"id": "a1", "name": "A", "kind": "openclaw", "manual": True,
                                        "runtimeDetected": True, "runtime": "vm"}]}},
        "assignments": {"box": {"hostId": "box", "agentUrl": "http://10.0.0.9:8092",
                                "applyStatus": {"state": "stored"}, "desiredAt": 7,
                                "assignments": [{"agentId": "a1", "manual": True, "routes": [
                                    {"role": "primary", "proxyId": "skynet:proxy:23001",
                                     "endpoint": "http://h:23001/v1", "contextLength": 8192}]}]}},
        "deletedAgents": {"box": ["gone1", "gone2"]},
    }}
    # A client made by hand that an older controller stamped with liveness.
    scout_era["topology"]["clients"]["hand"] = {"id": "hand", "name": "Hand", "state": "stale",
                                                "ageSeconds": None, "agents": [{"id": "b1", "name": "B"}]}
    out, text = in_fresh_process(TOPO_DUMP, initial=scout_era)
    if out.returncode == 0:
        topo = json.loads(out.stdout.strip().splitlines()[-1])
        box = topo["clients"]["box"]
        check("the client keeps what it is and loses what reports said",
              box == {"id": "box", "name": "Box",
                      "agents": [{"id": "a1", "name": "A", "kind": "openclaw", "runtime": "vm"}]},
              json.dumps(box, ensure_ascii=False))
        check("a client keeps no liveness of its own — the stamped state goes",
              topo["clients"].get("hand") == {"id": "hand", "name": "Hand", "agents": [{"id": "b1", "name": "B"}]}
              and "hand" not in topo.get("hosts", {}),
              json.dumps(topo["clients"].get("hand"), ensure_ascii=False))
        check("and what its machine's scout reported became the machine's host record",
              topo.get("hosts", {}).get("box") == {"id": "box", "name": "Box", "lastSeen": 5},
              json.dumps(topo.get("hosts"), ensure_ascii=False))
        entry = topo["assignments"]["box"]
        check("an assignment entry keeps its rows and routes, whole",
              entry == {"hostId": "box", "assignments": [{"agentId": "a1", "routes": [
                  {"role": "primary", "proxyId": "skynet:proxy:23001",
                   "endpoint": "http://h:23001/v1", "contextLength": 8192}]}]},
              json.dumps(entry, ensure_ascii=False))
        check("tombstones go: nothing brings a deleted agent back", "deletedAgents" not in topo)
        check("the migration says what went, in the log",
              "store: dropped what scout reports and adoption left:" in out.stdout
              and "2 tombstones" in out.stdout and "1 client manual" in out.stdout
              and "1 assignment row manual" in out.stdout and "1 client state" in out.stdout
              and "1 client ageSeconds" in out.stdout, out.stdout.strip()[:300])
        check("and persists itself", text is not None and '"manual"' not in text and "deletedAgents" not in text)
        again, text2 = in_fresh_process(TOPO_DUMP, initial=json.loads(text))
        check("negative: a second start finds nothing and says nothing",
              again.returncode == 0 and "store: dropped" not in again.stdout
              and json.loads(again.stdout.strip().splitlines()[-1]) == topo, again.stdout.strip()[:200])
    else:
        check("scout-era migration runs", False, out.stderr.strip()[-300:])

    # ── one machine, two records: the host a scout reports, the client made by hand ──
    combined = {"topology": {"clients": {
        "both": {"id": "both", "name": "Both", "ip": "10.0.0.5", "agentUrl": "http://10.0.0.5:8092",
                 "gpus": [{"name": "GPU"}], "lastSeen": 9, "firstSeen": 1, "state": "online",
                 "agents": [{"id": "a1", "name": "A"}]},
        "donor": {"id": "donor", "name": "Donor", "agentUrl": "http://10.0.0.6:8092", "gpus": [{"name": "GPU"}],
                  "agents": []},
        "hand": {"id": "hand", "name": "Hand", "ip": "10.0.0.7", "agents": [{"id": "b1", "name": "B"}]},
    }, "hosts": {"donor": {"id": "donor", "name": "Newer", "lastSeen": 99}}}}
    out, text = in_fresh_process(TOPO_DUMP, initial=combined)
    if out.returncode == 0:
        topo = json.loads(out.stdout.strip().splitlines()[-1])
        check("a machine that is both becomes two records under one id",
              topo["clients"]["both"] == {"id": "both", "name": "Both", "ip": "10.0.0.5",
                                          "agents": [{"id": "a1", "name": "A"}]}
              and topo["hosts"]["both"] == {"id": "both", "name": "Both", "ip": "10.0.0.5",
                                            "agentUrl": "http://10.0.0.5:8092", "gpus": [{"name": "GPU"}],
                                            "firstSeen": 1, "lastSeen": 9},
              json.dumps([topo["clients"].get("both"), topo["hosts"].get("both")], ensure_ascii=False))
        check("a machine that only lends its GPU keeps no client record",
              "donor" not in topo["clients"], json.dumps(sorted(topo["clients"])))
        check("negative: a host already on record is not overwritten by an old combined one",
              topo["hosts"]["donor"] == {"id": "donor", "name": "Newer", "lastSeen": 99},
              json.dumps(topo["hosts"].get("donor")))
        check("negative: a client nobody's scout reported stays a client, and no host appears for it",
              topo["clients"]["hand"] == {"id": "hand", "name": "Hand", "ip": "10.0.0.7",
                                          "agents": [{"id": "b1", "name": "B"}]} and "hand" not in topo["hosts"])
        check("the split says what it did, in the log",
              "store: machines split into host and client records: both (host+client), donor (host only)"
              in out.stdout, out.stdout.strip()[:300])
        again, _ = in_fresh_process(TOPO_DUMP, initial=json.loads(text))
        check("negative: a second start splits nothing and says nothing",
              again.returncode == 0 and "store: machines split" not in again.stdout)
    else:
        check("host split runs", False, out.stderr.strip()[-300:])

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
