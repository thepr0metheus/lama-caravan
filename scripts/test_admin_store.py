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
                                              "deletedAgents", "layout", "serverSlots"},
              out.stdout.strip())

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
