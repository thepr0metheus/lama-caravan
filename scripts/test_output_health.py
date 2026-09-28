#!/usr/bin/env python3
"""Snapshot of the backup node's memory: output verdicts, their expiry, the idle probe.

Pins by VALUE what caravan/proxy/output_health.py decides from an answer (a
429 kills an output for the TTL, a 400 does not), when a verdict expires, which
exit a backup node takes next — and what caravan/proxy/output_probe.py learns
from real sockets: a cell's /health, a cloud block's one-token completion,
a closed port. The cloud here is a fake HTTP server on loopback; the files the
proxy reads (providers, secrets) live in a temp tree set BEFORE the import.

Run: python3 scripts/test_output_health.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-health-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "agent-proxy-state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
sys.path.insert(0, str(ROOT))

from caravan.proxy.output_health import (  # noqa: E402
    DEAD_STATUSES, OutputHealth, VERDICT_TTL_SECONDS, output_health, output_id_of_ref,
)
from caravan.proxy.graph import PLAIN_REQUEST_CTX, chain_exit, resolve_graph  # noqa: E402
from caravan.proxy.output_probe import (  # noqa: E402
    onerror_exits, onerror_next_map, probe_output, probe_pass,
)

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ── fakes ──────────────────────────────────────────────────────────────
class _Healthy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hits = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        _Healthy.hits.append(self.path)
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Loading(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'{"error":{"code":503,"message":"Loading model","type":"unavailable_error"}}'
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Cloud(BaseHTTPRequestHandler):
    """An API-key cloud that either serves or says its quota is gone."""
    protocol_version = "HTTP/1.1"
    quota_gone = True
    hits = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        _Cloud.hits.append({"path": self.path, "model": payload.get("model"),
                            "max_tokens": payload.get("max_tokens"),
                            "auth": self.headers.get("Authorization")})
        if _Cloud.quota_gone:
            body = b'{"error":{"message":"You exceeded your current quota","type":"insufficient_quota","code":"insufficient_quota"}}'
            status = 429
        else:
            body = b'{"id":"p","choices":[{"message":{"role":"assistant","content":"h"}}]}'
            status = 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _SubCloud(BaseHTTPRequestHandler):
    """A subscription's codex endpoint: answers, and states the five-hour window in its headers.
    Its usage page says the window was reset."""
    protocol_version = "HTTP/1.1"
    hits = []
    pages = []
    used = "85"

    def do_GET(self):
        _SubCloud.pages.append(self.path)
        body = json.dumps({"rate_limit": {"primary_window": {
            "used_percent": 0, "limit_window_seconds": 18000, "reset_at": int(time.time()) + 18000}}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        _SubCloud.hits.append(self.path)
        body = b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("x-codex-primary-used-percent", _SubCloud.used)
        self.send_header("x-codex-primary-window-minutes", "300")
        self.send_header("x-codex-primary-reset-at", str(int(time.time()) + 3600))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HEALTHY, LOADING, CLOUD, CLOSED, SUBC = free_port(), free_port(), free_port(), free_port(), free_port()
for port, handler in ((HEALTHY, _Healthy), (LOADING, _Loading), (CLOUD, _Cloud), (SUBC, _SubCloud)):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({
    "accounts": [{"id": "acc:c", "type": "custom", "baseUrl": f"http://127.0.0.1:{CLOUD}/v1", "authMode": "apiKey"},
                 # A subscription keeping 20% of its five-hour window for the operator.
                 {"id": "acc:s", "type": "openai", "accountType": "openai-subscription",
                  "baseUrl": f"http://127.0.0.1:{SUBC}", "authMode": "apiKey", "usageReserve": {"18000": 20}}],
    "blocks": [{"id": "blk:c", "accountId": "acc:c", "model": "cloud-model"},
               {"id": "blk:s", "accountId": "acc:s", "model": "sub-model"}],
}), encoding="utf-8")
Path(os.environ["PROVIDER_SECRETS_FILE"]).write_text(json.dumps({"acc:c": {"apiKey": "sk-probe"},
                                                                 "acc:s": {"apiKey": "sk-sub"}}), encoding="utf-8")

OUT_HEALTHY = {"id": "cell:ok", "upstreamHost": "127.0.0.1", "upstreamPort": HEALTHY}
OUT_LOADING = {"id": "cell:load", "upstreamHost": "127.0.0.1", "upstreamPort": LOADING}
OUT_CLOSED = {"id": "cell:closed", "upstreamHost": "127.0.0.1", "upstreamPort": CLOSED}
OUT_CLOUD = {"id": "cb:c", "upstreamType": "cloud", "providerId": "blk:c", "accountId": "acc:c"}
OUT_ACCOUNT = {"id": "ca:c", "upstreamType": "cloud", "providerId": "", "accountId": "acc:c"}

CONFIG = {
    "policy": {},
    "routes": [],
    "routers": [{
        "id": "router:h",
        "outputs": [OUT_HEALTHY, OUT_LOADING, OUT_CLOSED, OUT_CLOUD, OUT_ACCOUNT],
        "graph": {
            "nodes": [
                {"id": "b1", "type": "onError", "config": {"mainEdge": "m1", "rescueEdge": "r1"}},
                {"id": "b2", "type": "onError", "config": {"mainEdge": "m2", "rescueEdge": "r2"}},
                {"id": "b3", "type": "onError", "config": {"mainEdge": "m3"}},
                # The main output leads into a QUEUE, not straight to an
                # output: that's how it stands in production, and before
                # 2026-09-06 a fork shaped like this had no health, no
                # countdown, and no skipping a dead main.
                {"id": "b4", "type": "onError", "config": {"mainEdge": "m4", "rescueEdge": "r4"}},
                {"id": "q1", "type": "queue", "config": {"admitEdge": "a1", "spillEdge": "s1"}},
                # And here the chain runs into a node whose choice can't be
                # predicted from the request: the board must say "don't
                # know", not make something up.
                {"id": "b5", "type": "onError", "config": {"mainEdge": "m5", "rescueEdge": "r5"}},
                {"id": "rr1", "type": "roundRobin", "config": {}},
            ],
            "edges": [
                {"id": "m1", "from": "rule:b1", "to": "out:cb:c"},
                {"id": "r1", "from": "rule:b1", "to": "out:cell:ok"},
                {"id": "m2", "from": "rule:b2", "to": "out:cell:load"},
                {"id": "r2", "from": "rule:b2", "to": "rule:b1"},
                {"id": "m3", "from": "rule:b3", "to": "out:cell:closed"},
                {"id": "m4", "from": "rule:b4", "to": "rule:q1"},
                {"id": "r4", "from": "rule:b4", "to": "out:cell:ok"},
                {"id": "a1", "from": "rule:q1", "to": "out:cell:closed"},
                {"id": "s1", "from": "rule:q1", "to": "out:cb:c"},
                {"id": "m5", "from": "rule:b5", "to": "rule:rr1"},
                {"id": "r5", "from": "rule:b5", "to": "out:cell:ok"},
                {"id": "rr-a", "from": "rule:rr1", "to": "out:cell:ok"},
                {"id": "rr-b", "from": "rule:rr1", "to": "out:cell:load"},
            ],
        },
    }],
}


def test_verdicts():
    print("verdicts from answers:")
    h = OutputHealth(ttl_seconds=300)
    h.note_status("a", 200, now=1000)
    check(h.row("a")["state"] == "ok" and not h.is_dead("a", 1000), "200 → alive")
    h.note_status("a", 429, message="quota", now=1000)
    check(h.is_dead("a", 1000) and h.row("a")["kind"] == "http 429", "429 → dead, the kind names the status")
    check(h.row("a")["message"] == "quota", "and the reason is kept")
    h.note_status("b", 400, now=1000)
    check(not h.is_dead("b", 1000) and h.row("b")["state"] == "ok",
          "400 is this request's problem: the output answered — alive")
    check(all(s in DEAD_STATUSES for s in (401, 403, 404, 429, 500, 502, 503, 504)),
          "no credentials, no model, no quota, every server failure: dead")
    check(400 not in DEAD_STATUSES and 413 not in DEAD_STATUSES and 422 not in DEAD_STATUSES,
          "oversized or malformed requests do not kill an output")
    h.note_error("c", kind="connect", message="refused", now=1000)
    check(h.is_dead("c", 1000) and h.row("c")["kind"] == "connect", "a connect failure is dead with kind connect")
    h.note_status("d", "not a number", now=1000)
    check(h.row("d") is None, "rubbish for a status writes nothing")
    h.note_ok("", now=1000)
    check(h.row("") is None, "an empty id writes nothing")

    print("expiry — a verdict is a memory after the TTL:")
    check(h.is_dead("a", 1000 + 299), "at 299s the dead verdict still holds")
    check(not h.is_dead("a", 1000 + 300), "at 300s it has expired: not dead, only remembered")
    check(h.row("a")["state"] == "error", "the row itself stays — the board shows the last verdict")
    check(h.stale_ids(["a", "b", "zzz"], 1000 + 10) == ["zzz"], "stale = missing or expired; fresh ones are skipped")
    check(h.stale_ids(["a", "b", "zzz"], 1000 + 300) == ["a", "b", "zzz"], "after the TTL every verdict is stale")
    snap = h.snapshot(1000 + 30)
    check(snap["a"]["fresh"] and snap["a"]["ageSec"] == 30 and snap["a"]["retryInSec"] == 270,
          f"snapshot carries age, freshness and the seconds until re-check (got {snap['a']})")
    check(snap["a"]["source"] == "traffic", "and where the verdict came from")

    print("next exit of a backup node:")
    h2 = OutputHealth(ttl_seconds=300)
    check(h2.next_exit("m", "b", 1000) == ("main", ""), "nothing known → main")
    h2.note_status("m", 429, now=1000)
    nxt = h2.next_exit("m", "b", 1000)
    check(nxt[0] == "backup" and "429" in nxt[1], f"main dead, backup unknown → backup, with the reason (got {nxt})")
    h2.note_status("b", 500, now=1000)
    check(h2.next_exit("m", "b", 1000) == ("main", ""), "both dead → main, the original order")
    check(h2.next_exit("m", "b", 1000 + 300)[0] == "main", "main's verdict expired → main again")
    h2.note_status("m", 429, now=2000)
    check(h2.next_exit("m", None, 2000) == ("main", ""), "no backup wired → main, dead or not")
    check(h2.next_exit(None, "b", 2000) == ("main", ""), "main behind a rule node (no id) → main")
    print("a snapshot mirrored into another process:")
    h3 = OutputHealth(ttl_seconds=300)
    h3.note_ok("stale-local", now=1000)
    h3.load_snapshot({"m": {"state": "error", "status": 429, "kind": "http 429", "message": "quota", "checkedAt": 5000, "source": "traffic"},
                      "old": {"state": "error", "status": 500, "checkedAt": 5000 - 400},
                      "junk": "no", "empty": {"state": "error"}, "later": {"state": "ok", "checkedAt": "x"}})
    check(h3.is_dead("m", 5000 + 10) and h3.row("m")["source"] == "traffic", "a fresh dead verdict from the file is dead here too, its source kept")
    check(not h3.is_dead("old", 5000 + 10) and h3.row("old")["state"] == "error", "an old one is a memory, not a verdict")
    check(h3.row("junk") is None and h3.row("empty") is None and h3.row("later") is None, "rubbish rows are skipped")
    check(h3.row("stale-local") is None, "the mirror REPLACES local rows — this process never noted anything real")
    check(h3.next_exit("m", "b", 5000 + 10)[0] == "backup", "and the next exit follows the proxy's verdict")
    check(output_id_of_ref("out:cb:x") == "cb:x" and output_id_of_ref("rule:q1") is None
          and output_id_of_ref("out:") is None and output_id_of_ref(None) is None,
          "output_id_of_ref: out: refs only")


def test_probe():
    print("the probe against real sockets:")
    ok, status, kind, msg = probe_output(OUT_HEALTHY)
    check((ok, status) == (True, 200) and _Healthy.hits[-1] == "/health", "a cell: GET /health 200 → alive")
    ok, status, kind, msg = probe_output(OUT_LOADING)
    check((ok, status, kind) == (False, 503, "loading") and "Loading model" in msg,
          f"a loading cell: 503 → dead, kind loading, the cell's words kept (got {msg!r})")
    ok, status, kind, msg = probe_output(OUT_CLOSED)
    check(ok is False and status is None and kind == "connect", f"a closed port → dead, kind connect (got {kind} {msg!r})")
    _Cloud.quota_gone = True
    ok, status, kind, msg = probe_output(OUT_CLOUD)
    check((ok, status) == (False, 429) and "quota" in msg, f"a cloud block out of quota: 429 → dead with the provider's words (got {msg!r})")
    hit = _Cloud.hits[-1]
    check(hit["path"] == "/v1/chat/completions" and hit["model"] == "cloud-model" and hit["max_tokens"] == 1,
          f"the probe is one token to the block's model through the same path (got {hit})")
    check(hit["auth"] == "Bearer sk-probe", "with the account's credential")
    _Cloud.quota_gone = False
    ok, status, kind, msg = probe_output(OUT_CLOUD)
    check((ok, status) == (True, 200), "the same block serving → alive")
    check(probe_output(OUT_ACCOUNT)[0] is None, "an account passthrough pins no model: nothing to prove, no verdict")
    check(probe_output(None)[0] is False and probe_output({"id": "x", "upstreamType": "cloud", "providerId": "blk:nope"})[2] == "config",
          "unknown outputs and unconfigured blocks are dead with kind config")


def test_pass_and_next():
    print("one idle pass over every backup exit:")
    output_health.clear()
    exits = onerror_exits(CONFIG)
    check([e["node"] for e in exits] == ["b1", "b2", "b3", "b4", "b5"], "every backup node is listed")
    check(exits[0]["main"] == "cb:c" and exits[0]["backup"] == "cell:ok", "exits resolve to output ids")
    check(exits[2]["backup"] is None, "an unwired backup is None")

    # Chain: the output leads to a node, and "is it alive" is a question
    # about the model at the far end.
    by_node = {e["node"]: e for e in exits}
    check(by_node["b2"]["backup"] == "cb:c" and by_node["b2"]["backupChain"] == ["b1"],
          f"positive: выход в узел разрешается до КОНЕЧНОГО выхода, цепочка названа (got {by_node['b2']})")
    check(by_node["b2"]["backupRef"] == "rule:b1",
          "само ребро не меняется: канат по-прежнему идёт в узел")
    check(by_node["b4"]["main"] == "cell:closed" and by_node["b4"]["mainChain"] == ["q1"],
          f"positive: главный выход через очередь — это её ветка допуска (got {by_node['b4']})")
    check(by_node["b5"]["main"] is None and by_node["b5"]["mainChain"] == ["rr1"],
          f"negative: цепочка через узел, чей выбор не предсказать, остаётся неразрешённой (got {by_node['b5']})")
    check(by_node["b5"]["backup"] == "cell:ok",
          "и это не мешает второму выходу той же развилки")
    _Cloud.quota_gone = True
    probed = probe_pass(CONFIG, now=5000)
    check(sorted(probed) == ["cb:c", "cell:closed", "cell:load", "cell:ok"], f"every output with a stale verdict is probed once (got {sorted(probed)})")
    nxt = onerror_next_map(CONFIG, now=5000)
    check(nxt["b1"]["next"] == "backup" and "429" in nxt["b1"]["reason"],
          f"b1: main (cloud, quota gone) dead, backup alive → next is backup (got {nxt['b1']})")
    check(nxt["b2"]["next"] == "main", "b2: main loading is dead but the backup is unknown-by-design → main")
    check(nxt["b3"]["next"] == "main" and nxt["b3"]["backup"] is None, "b3: no backup → main")
    check(nxt["b2"]["backup"] == "cb:c", "b2: цепочка разрешена и в карте следующего выхода")
    check(nxt["b4"]["next"] == "backup" and "connect" in nxt["b4"]["reason"],
          f"b4: за очередью мёртвая ячейка → следующий запрос идёт в запасной (got {nxt['b4']})")
    check(nxt["b5"]["next"] == "main",
          "b5: конец цепочки неизвестен — судить не о чем, идём главным, как и раньше")
    check(probe_pass(CONFIG, now=5000 + 100) == [], "within the TTL nothing is probed again")
    _Cloud.quota_gone = False
    hits_before = len(_Cloud.hits)
    probed = probe_pass(CONFIG, now=5000 + VERDICT_TTL_SECONDS)
    check("cb:c" in probed and len(_Cloud.hits) == hits_before + 1, "after the TTL the cloud is asked again — once")
    check(onerror_next_map(CONFIG, now=5000 + VERDICT_TTL_SECONDS)["b1"]["next"] == "main",
          "quota back → main is next again")
    output_health.clear()
    off = dict(CONFIG); off["policy"] = {"outputProbeSeconds": 0}
    check(probe_pass(off, now=9000) == [], "policy outputProbeSeconds 0 switches the probe off")
    output_health.ttl_seconds = VERDICT_TTL_SECONDS
    output_health.clear()


def test_request_follows_the_chain():
    """What the board sees and what a request does are one decision.

    A fork whose main output leads into a queue must skip a dead end of the
    chain the same way it skips a dead output directly: before 2026-09-06 the
    skip never fired at all, because the edge into a node carries no output id.
    """
    print("запрос идёт по разрешённой цепочке:")
    router = CONFIG["routers"][0]
    route = {"port": 1}
    ctx = dict(PLAIN_REQUEST_CTX)
    output_health.clear()
    got = resolve_graph(router, route, ctx=ctx, input_ref="rule:b4", now=6000)
    check((got or {}).get("id") == "cell:closed",
          f"вердиктов нет — идём главным, то есть в очередь и дальше (got {(got or {}).get('id')})")
    output_health.note_error("cell:closed", kind="connect", message="refused", now=6000)
    got = resolve_graph(router, route, ctx=ctx, input_ref="rule:b4", now=6000)
    check((got or {}).get("id") == "cell:ok",
          f"positive: конец цепочки мёртв — запрос сразу уходит в запасной (got {(got or {}).get('id')})")
    output_health.note_ok("cell:closed", now=6100)
    got = resolve_graph(router, route, ctx=ctx, input_ref="rule:b4", now=6100)
    check((got or {}).get("id") == "cell:closed",
          "ожил — главный снова главный")
    # NEGATIVE: a chain through an unpredictable node gives no cause to jump.
    output_health.clear()
    output_health.note_error("cell:ok", kind="connect", message="refused", now=6200)
    seen = {(resolve_graph(router, route, ctx=ctx, input_ref="rule:b5", now=6200) or {}).get("id")
            for _ in range(4)}
    check(seen <= {"cell:ok", "cell:load"},
          f"negative: конец не назван — идём главным (round-robin решает сам), запасной не подставляется (got {seen})")
    check(chain_exit(router["graph"], "out:cell:ok")[0] == "out:cell:ok",
          "прямой выход — сам себе конец цепочки")
    check(chain_exit(router["graph"], "rule:nope")[0] is None,
          "negative: ссылка в несуществующий узел концом цепочки не притворяется")
    check(chain_exit(router["graph"], "")[0] is None, "negative: пустая ссылка — тоже None")
    output_health.clear()


def test_questions_go_where_answers_come_from():
    """A client's QUESTION takes the exit that answers (discovery_exit).

    2026-09-28, 03:34: a client restarting after its update asked the port ten
    questions in one second (/props, /api/tags, /api/show …). The backup node's
    main led through a queue to a cell off for seventeen days, the backup was a
    cloud block the probe kept finding alive — and all ten went to the cell:
    a question is never replayed, and next_exit keeps main until a FRESH
    verdict says otherwise.
    """
    print("вопрос клиента идёт к выходу, который отвечает:")

    def table(main_row, backup_row):
        h = OutputHealth(ttl_seconds=300)
        for oid, row in (("m", main_row), ("b", backup_row)):
            if row == "ok":
                h.note_ok(oid, now=1000)
            elif row == "err":
                h.note_error(oid, kind="connect", message="refused", now=1000)
            elif isinstance(row, tuple):   # (answered at, failed at)
                h.note_ok(oid, now=row[0])
                h.note_error(oid, kind="connect", message="refused", now=row[1])
        return h.discovery_exit("m", "b")

    check(table(None, None) == ("main", ""), "positive: ничего не известно → главный, как и у запроса")
    check(table(None, "ok") == ("backup", "main has not answered yet"),
          "главный ещё молчит, запасной отвечает → запасной")
    check(table("err", None) == ("backup", "main is not answering: connect"),
          "последнее слово главного — отказ, запасной молчит → запасной, с причиной")
    check(table("err", "ok")[0] == "backup", "главный отказал, запасной отвечает → запасной")
    check(table("ok", "err") == ("main", ""), "negative: главный отвечает, запасной нет → главный")
    check(table("ok", "ok") == ("main", ""),
          "negative: оба отвечают → главный, туда же, куда запросы (а не «кто ответил позже»)")
    check(table((500, 1000), (800, 1000)) == ("backup", "backup answered more recently"),
          "оба отказывают → тот, кто отвечал позже (запасной, 800 > 500)")
    check(table((800, 1000), (500, 1000)) == ("main", ""), "negative: позже отвечал главный → главный")
    check(table("err", "err") == ("main", ""), "negative: оба отказывают и ни один не отвечал → главный, прежний порядок")
    check(table((800, 1000), "err") == ("main", ""), "главный хоть когда-то отвечал, запасной никогда → главный")
    h = OutputHealth(ttl_seconds=300)
    h.note_ok("b", now=1000)
    check(h.discovery_exit("m", None) == ("main", "") and h.discovery_exit(None, "b") == ("main", ""),
          "negative: запасного нет или конец главной цепочки не назван → главный")

    print("вопрос и запрос при ИСТЁКШИХ вердиктах — случай 03:34:")
    h = OutputHealth(ttl_seconds=300)
    h.note_error("m", kind="connect", message="refused", now=1000)
    h.note_ok("b", now=1000)
    check(h.next_exit("m", "b", 1000 + 400) == ("main", ""),
          "as-is: запрос идёт главным — истёкший «мёртв» проверяется, спасение переиграет")
    check(h.discovery_exit("m", "b") == ("backup", "main is not answering: connect"),
          "а вопрос — в запасной: последнее слово главного отказ, хоть и старый")

    print("когда выход отвечал в последний раз:")
    h = OutputHealth(ttl_seconds=300)
    h.note_ok("x", now=500)
    h.note_error("x", status=502, message="down", now=900)
    check(h.row("x")["state"] == "error" and h.row("x")["lastOkAt"] == 500,
          "отказ не стирает, когда выход отвечал")
    h.note_ok("x", now=1000)
    check(h.row("x")["lastOkAt"] == 1000, "новый ответ — новое время")
    h.note_error("y", kind="connect", now=900)
    check(h.row("y")["lastOkAt"] is None, "negative: не отвечал ни разу — None, а не ноль")
    check(h.snapshot(1000)["x"]["lastOkAt"] == 1000, "снимок для доски несёт время ответа")
    h2 = OutputHealth(ttl_seconds=300)
    h2.load_snapshot({"a": {"state": "error", "checkedAt": 900, "lastOkAt": 500},
                      "b": {"state": "ok", "checkedAt": 900},
                      "c": {"state": "error", "checkedAt": 900},
                      "d": {"state": "error", "checkedAt": 900, "lastOkAt": "x"},
                      "e": {"state": "error", "checkedAt": 900, "lastOkAt": -5}})
    check(h2.row("a")["lastOkAt"] == 500, "зеркало в другом процессе несёт время ответа")
    check(h2.row("b")["lastOkAt"] == 900, "файл старого прокси без поля: «жив» — это ответ в checkedAt")
    check(h2.row("c")["lastOkAt"] is None and h2.row("d")["lastOkAt"] is None and h2.row("e")["lastOkAt"] is None,
          "negative: отказ без поля, мусор и отрицательное — None, не выдуманное время")

    print("граф: вопрос и запрос через одну развилку (главный → очередь → ячейка):")
    from caravan.proxy.graph import PORT_QUESTION_CTX
    router = CONFIG["routers"][0]
    output_health.clear()
    output_health.note_error("cell:closed", kind="connect", message="refused", now=7000)
    output_health.note_ok("cell:ok", now=7000)
    ask = resolve_graph(router, {"port": 1}, ctx=dict(PORT_QUESTION_CTX), input_ref="rule:b4", now=7400)
    req = resolve_graph(router, {"port": 1}, ctx=dict(PLAIN_REQUEST_CTX), input_ref="rule:b4", now=7400)
    check((ask or {}).get("id") == "cell:ok",
          f"positive: вопрос при истёкшем «мёртв» главного уходит в запасной (got {(ask or {}).get('id')})")
    check((req or {}).get("id") == "cell:closed",
          f"as-is: запрос в том же состоянии идёт главным (got {(req or {}).get('id')})")
    output_health.clear()
    ask = resolve_graph(router, {"port": 1}, ctx=dict(PORT_QUESTION_CTX), input_ref="rule:b4", now=7400)
    check((ask or {}).get("id") == "cell:closed", "negative: вердиктов нет — вопрос тоже идёт главным")
    output_health.clear()


def test_first_pass_at_start():
    """The probe asks at once when the proxy starts, not half a minute later.

    2026-09-28: right after a deploy the proxy knew nothing about its exits
    for thirty seconds, and a question in that window went down main into a
    cell switched off weeks before.
    """
    print("первая проверка выходов — сразу при старте:")
    import caravan.proxy.output_probe as op
    import caravan.proxy.state as st

    class Stop(Exception):
        pass

    def run(passes):
        calls = []
        script = list(passes)

        def fake_pass():
            outcome = script.pop(0)
            calls.append("pass")
            if outcome == "boom":
                raise RuntimeError("probe failed")
            return outcome

        def fake_sleep(seconds):
            calls.append(("sleep", seconds))
            if not script:
                raise Stop()

        saved_pass, saved_write = op.probe_pass, st.write_state
        op.probe_pass = fake_pass
        st.write_state = lambda: calls.append("write")
        try:
            op.probe_loop(sleep=fake_sleep)
        except Stop:
            pass
        except Exception as exc:   # the loop itself died: a pin says so, not a crash
            calls.append(("died", type(exc).__name__))
        finally:
            op.probe_pass, st.write_state = saved_pass, saved_write
        return calls

    calls = run([["cell:ok"], []])
    check(calls == ["pass", "write", ("sleep", op.PROBE_INTERVAL_SECONDS), "pass", ("sleep", op.PROBE_INTERVAL_SECONDS)],
          f"positive: сначала проход и запись, потом пауза; negative: пустой проход файл не переписывает (got {calls})")
    calls = run(["boom", ["cell:ok"]])
    check(calls[:3] == ["pass", ("sleep", op.PROBE_INTERVAL_SECONDS), "pass"] and "write" in calls,
          f"negative: упавший проход не останавливает цикл — следующий идёт по расписанию (got {calls})")


def test_probe_keeps_the_reserve():
    """The probe of a subscription exit: it reads the windows off the answer, and
    while the operator's reserve is reached it spends nothing of it — the exit
    refuses, and the probe says so without asking the provider."""
    print("проверка выхода подписки и запас оператора:")
    import time as _t
    from caravan.proxy.subscription_usage import subscription_usage
    out = {"id": "cb:s", "upstreamType": "cloud", "providerId": "blk:s", "accountId": "acc:s"}
    subscription_usage.clear()
    before = len(_SubCloud.hits)
    ok, status, kind, msg = probe_output(out)
    check((ok, status) == (True, 200) and len(_SubCloud.hits) == before + 1,
          f"показаний нет — проба спрашивает провайдера (got {ok}, {status})")
    check([(w["seconds"], w["usedPct"]) for w in subscription_usage.windows("acc:s")] == [(18000, 85)],
          "и оставляет показания из заголовков ответа")
    ok, status, kind, msg = probe_output(out)
    check((ok, status, kind) == (False, 429, "usage_reserve") and len(_SubCloud.hits) == before + 1,
          f"positive: осталось 15% при запасе 20% — выход отказывает, провайдера не спрашивают (got {ok}, {status}, {kind})")
    check(msg.startswith("The caravan keeps your reserve"), "причина называет караван")
    subscription_usage.note("acc:s", {"x-codex-primary-used-percent": "85", "x-codex-primary-window-minutes": "300",
                                      "x-codex-primary-reset-at": str(int(_t.time()) - 5)})
    ok, status, kind, msg = probe_output(out)
    check((ok, status) == (True, 200) and len(_SubCloud.hits) == before + 2,
          "negative: окно сбросилось — проба снова спрашивает провайдера")
    from caravan.proxy.subscription_usage import reserve_gate
    subscription_usage.note("acc:s", {"x-codex-primary-used-percent": "85", "x-codex-primary-window-minutes": "300",
                                      "x-codex-primary-reset-at": str(int(_t.time()) + 3600)}, now=_t.time() - 400)
    reserve_gate.clear()
    pages = len(_SubCloud.pages)
    ok, status, kind, msg = probe_output(out)
    check((ok, status) == (True, 200) and _SubCloud.pages[pages:] == ["/backend-api/wham/usage"]
          and len(_SubCloud.hits) == before + 3,
          f"досрочный сброс: показания старые — проба спрашивает страницу использования, и выход снова жив (got {ok}, {status})")
    subscription_usage.clear()
    reserve_gate.clear()


def main():
    test_verdicts()
    test_probe()
    test_pass_and_next()
    test_request_follows_the_chain()
    test_questions_go_where_answers_come_from()
    test_first_pass_at_start()
    test_probe_keeps_the_reserve()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("all output-health snapshots hold")


if __name__ == "__main__":
    main()
