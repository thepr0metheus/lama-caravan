#!/usr/bin/env python3
"""The proxy config's read and write, pinned before either moves.

agent-proxies.json is the file the board is drawn from: routes, routers, and the
GRAPH — the nodes and cables an operator dragged into place. Its write path is
not a write. It:

  * recomputes cloud-fallback eligibility from the current connections;
  * re-normalises routers against the routes;
  * takes a timestamped backup whenever the file on disk still has graph nodes;
  * and, if the payload being written has NO graph nodes while the file on disk
    does, copies the old graph into the new payload rather than writing the loss.

That last one is a guard against a caller that rebuilds the payload from a
narrower source and does not know about the graph. It has no test, no version,
and its only description is a comment — so if a rewrite drops it, the cables
disappear from the board and the file that could prove what they were has just
been overwritten.

This photographs all of it. Each case gets its own config file; the fleet's is
never touched.
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
    """A snippet with the proxy config pointed at a throwaway file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "agent-proxies.json"
        if initial is not None:
            path.write_text(initial if isinstance(initial, str) else json.dumps(initial),
                            encoding="utf-8")
        env = dict(os.environ, AGENT_PROXY_CONFIG_FILE=str(path),
                   LLAMA_ADMIN_STATE=str(Path(tmp) / "admin.json"), PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                             capture_output=True, text=True)
        written = None
        if path.exists():
            try:
                written = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                # The corrupt-input case leaves its own bad JSON on disk when
                # nothing wrote over it; that is the input, not a failure.
                written = "не JSON"
        backups = sorted(p.name for p in Path(tmp).glob("*.bak-graph-*"))
        kept = sorted(p.name for p in Path(tmp).glob("*.unreadable-*"))
        return out, written, backups, kept


READ = '''
import json
from caravan.admin.proxies_config import read_agent_proxy_payload
print(json.dumps(read_agent_proxy_payload(), sort_keys=True))
'''

LOAD = '''
import json
from caravan.admin.proxies_config import load_agent_proxy_config
cfg = load_agent_proxy_config()
print(json.dumps({"ports": [r["port"] for r in cfg["routes"]],
                  "routers": [r.get("id") for r in cfg["routers"]],
                  "keys": sorted(cfg)}, sort_keys=True))
'''

WRITE_LOSES_GRAPH = '''
from caravan.admin.proxies_config import write_agent_proxy_payload
# A caller that rebuilt the payload from a narrower source and knows nothing
# about the graph the operator dragged into place.
write_agent_proxy_payload({"routes": [{"label": "a", "port": 23001,
                                       "upstreamHost": "127.0.0.1",
                                       "upstreamPort": 8080, "enabled": True}],
                           "routers": [{"id": "router:default", "graph": {}}]})
'''

# A node with a real type: normalize_router_graph drops anything else, and a
# fixture of typeless nodes would test the dropping, not the guard.
WRITE_KEEPS_ITS_OWN = '''
from caravan.admin.proxies_config import write_agent_proxy_payload
write_agent_proxy_payload({"routes": [], "routers": [
    {"id": "router:default",
     "graph": {"nodes": [{"id": "new", "type": "byModel", "x": 1, "y": 2}], "edges": []}}]})
'''

WITH_GRAPH = {"routes": [{"label": "a", "port": 23001, "upstreamHost": "127.0.0.1",
                          "upstreamPort": 8080, "enabled": True}],
              "routers": [{"id": "router:default",
                           "graph": {"nodes": [{"id": "n1", "type": "byModel", "x": 0, "y": 0},
                                               {"id": "n2", "type": "failover", "x": 9, "y": 9}],
                                     "edges": [{"id": "e1", "from": "rule:n1", "to": "rule:n2"}]}}]}

LEGACY = {"switchboards": [{"id": "sb:default",
                            "graph": {"nodes": [{"id": "n1", "type": "byModel", "x": 0, "y": 0}]}}],
          "routes": [{"label": "a", "port": 23001, "switchboardId": "sb:default",
                      "upstreamHost": "127.0.0.1", "upstreamPort": 8080, "enabled": True}]}


def main():
    # ── reading ──────────────────────────────────────────────────────────────
    out, _, _, _ = run(READ)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a missing file still gives a usable shape",
              isinstance(got.get("routes"), list) and "policy" in got and "routers" in got,
              str(got)[:200])
        # The value, not just the type. This used to be four routes named after
        # agents retired long ago, on ports that now belong to other things — so
        # a caravan with no config came up looking like a working four-route
        # setup. A test that only asked "is it a list" could not tell.
        check("a caravan with no proxy config has no routes",
              got.get("routes") == [], str(got.get("routes"))[:200])
    else:
        check("read on a missing file", False, out.stderr.strip()[-300:])

    out, _, _, kept = run(READ, initial="{ not json")
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a corrupt file does not crash the read",
              isinstance(got.get("routes"), list))
        check("…and does not invent routes either", got.get("routes") == [],
              str(got.get("routes"))[:200])
        check("a file we could not parse is kept aside before anything overwrites it",
              len(kept) == 1, str(kept))
    else:
        check("read on a corrupt file", False, out.stderr.strip()[-300:])

    # A file that PARSES but is unusable — null, a list, a string — is just as
    # lost as a truncated one, and the docstring promises a copy for both. It
    # only kept one: this branch returned the default and let the next write
    # replace the original.
    for shape, text in (("null", "null"), ("список", "[1,2,3]"), ("строка", '"hi"')):
        out, _, _, kept = run(READ, initial=text)
        check(f"непригодная форма ({shape}) тоже откладывается в сторону",
              out.returncode == 0 and len(kept) == 1, f"{shape}: {kept}")

    # Reading a broken file repeatedly must not fill the directory with copies.
    out, _, _, kept = run(READ + READ + READ, initial="{ not json")
    check("the unreadable copy is kept once, not once per read",
          out.returncode == 0 and len(kept) == 1, str(kept))

    out, _, _, _ = run(READ, initial=LEGACY)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        rid = (got.get("routers") or [{}])[0].get("id")
        route = (got.get("routes") or [{}])[0]
        check("the pre-rename schema is upgraded on read",
              "switchboards" not in got and rid == "router:default", str(got)[:200])
        check("a route's router reference is upgraded with it",
              route.get("routerId") == "router:default" and "switchboardId" not in route,
              str(route))
        check("the upgraded router keeps its graph",
              [n.get("id") for n in
               (((got.get("routers") or [{}])[0].get("graph") or {}).get("nodes") or [])] == ["n1"],
              str(got.get("routers"))[:200])
    else:
        check("legacy read", False, out.stderr.strip()[-300:])

    # ── loading (normalised view) ────────────────────────────────────────────
    dupes = {"routes": [
        {"label": "a", "port": 23001, "upstreamHost": "127.0.0.1", "upstreamPort": 8080, "enabled": True},
        {"label": "b", "port": 23001, "upstreamHost": "127.0.0.1", "upstreamPort": 8081, "enabled": True},
        {"label": "c", "port": 23002, "upstreamHost": "127.0.0.1", "upstreamPort": 8082, "enabled": True},
    ]}
    out, _, _, _ = run(LOAD, dupes)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("one port means one route", got["ports"] == [23001, 23002], str(got))
        check("the loaded view always has its four sections",
              got["keys"] == ["policy", "routers", "routes", "stopRequests"], str(got))
    else:
        check("load", False, out.stderr.strip()[-300:])

    # ── THE guard: a write that would lose the graph ─────────────────────────
    out, written, backups, _ = run(WRITE_LOSES_GRAPH, WITH_GRAPH)
    if out.returncode == 0 and written:
        graph = ((written.get("routers") or [{}])[0].get("graph") or {})
        check("a write with no graph does not erase the one on disk",
              [n.get("id") for n in (graph.get("nodes") or [])] == ["n1", "n2"], str(graph)[:200])
        check("the edges come back too",
              [(e.get("from"), e.get("to")) for e in (graph.get("edges") or [])]
              == [("rule:n1", "rule:n2")], str(graph)[:200])
        check("a backup is taken before overwriting a file that has a graph",
              len(backups) == 1, str(backups))
    else:
        check("graph guard", False, out.stderr.strip()[-300:])

    # ── a caller that DOES bring a graph must win ────────────────────────────
    out, written, _, _ = run(WRITE_KEEPS_ITS_OWN, WITH_GRAPH)
    if out.returncode == 0 and written:
        nodes = ((written.get("routers") or [{}])[0].get("graph") or {}).get("nodes")
        check("a caller's own graph is not overwritten by the old one",
              [n.get("id") for n in (nodes or [])] == ["new"], str(nodes))
    else:
        check("graph precedence", False, out.stderr.strip()[-300:])

    # ── the file format ──────────────────────────────────────────────────────
    out, _, _, _ = run(WRITE_KEEPS_ITS_OWN)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "agent-proxies.json"
        env = dict(os.environ, AGENT_PROXY_CONFIG_FILE=str(path),
                   LLAMA_ADMIN_STATE=str(Path(tmp) / "admin.json"), PYTHONPATH=str(ROOT))
        subprocess.run([sys.executable, "-c", WRITE_KEEPS_ITS_OWN], env=env, cwd=ROOT,
                       capture_output=True, text=True)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    check("written as indented JSON with a trailing newline",
          text.endswith("\n") and '\n  "' in text, repr(text[:60]))
    check("non-ASCII is written as itself, not escaped",
          "ensure_ascii" not in text and "\\u" not in text, repr(text[:120]))

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
