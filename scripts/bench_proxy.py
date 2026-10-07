#!/usr/bin/env python3
"""Load test of the proxy: N parallel token streams from a fake provider.

The question it answers: how many streams a machine's processor carries and
what the caravan adds to each, measured the same way on the controller's
machine and on the NAS before the caravan moves there.

Three processes, so that nobody's work is counted as the proxy's: a fake
provider, the proxy itself (a real ProxyHandler on a temporary config, one
fresh process per level), and this driver with the clients. For each level
of parallel streams it reports:

  - the client's view: time to the first event and the whole stream, through
    the proxy and straight from the provider at the same parallelism — the
    difference is what the proxy adds;
  - the proxy's journal: prepMs, cpuMs and the kept-connection share, the
    figures the route window shows (caravan/proxy/request_clock.py);
  - the proxy process's processor time per request, all its threads, read
    from the process itself after the level.

Kinds: `openai` relays a chat-completions stream as it is, `subscription`
translates a Responses stream (the subscription's path, the heavier one),
`cell` goes to a local server without a pool.

Run:  python3 scripts/bench_proxy.py --kind subscription --streams 1,8,32
      python3 scripts/bench_proxy.py --quick     (a small run that must pass; CI runs it)
"""
import argparse
import base64
import http.client
import json
import math
import os
import resource
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_listening(port, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return True
        except OSError:
            time.sleep(0.05)
    return False


def cpu_seconds():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


# ── role: the fake provider ───────────────────────────────────────────────

def run_provider(port, events, gap_ms):
    """Answers a stream of `events` events, `gap_ms` apart, chunked and kept alive:
    chat-completions frames on /v1/..., Responses-API events on /backend-api/codex/responses."""
    gap = gap_ms / 1000.0

    class Provider(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _chunk(self, data):
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()

        def do_GET(self):
            # A cell's slots: enough that no stream waits in the proxy's queue —
            # the bench measures the proxy, not the queue.
            payload = json.dumps([{"id": i} for i in range(256)]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length) if length else b""
            responses = self.path.endswith("/responses")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for index in range(events):
                    if responses:
                        frame = {"type": "response.output_text.delta", "delta": f"tok{index} "}
                    else:
                        frame = {"id": "chatcmpl-bench", "object": "chat.completion.chunk",
                                 "choices": [{"index": 0, "delta": {"content": f"tok{index} "}}]}
                    self._chunk(b"data: " + json.dumps(frame).encode() + b"\n\n")
                    if gap:
                        time.sleep(gap)
                if responses:
                    done = {"type": "response.completed", "response": {
                        "status": "completed", "usage": {"input_tokens": 50, "output_tokens": events}}}
                    self._chunk(b"data: " + json.dumps(done).encode() + b"\n\n")
                else:
                    self._chunk(b"data: [DONE]\n\n")
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                self.close_connection = True

    class Quiet(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 256

        def handle_error(self, request, client_address):
            pass

    Quiet(("127.0.0.1", port), Provider).serve_forever()


# ── role: the proxy ───────────────────────────────────────────────────────

def run_proxy(port, workdir):
    """A real ProxyHandler on `port`, configured from `workdir`. Prints its own
    processor time when ready and again when told to stop (SIGTERM)."""
    work = Path(workdir)
    os.environ["AGENT_PROXY_CONFIG_FILE"] = str(work / "agent-proxies.json")
    os.environ["AGENT_PROXY_LOG_DIR"] = str(work / "logs")
    os.environ["AGENT_PROXY_STATE_FILE"] = str(work / "state.json")
    os.environ["CLOUD_PROVIDERS_FILE"] = str(work / "cloud-providers.json")
    os.environ["MODEL_CATALOG_FILE"] = str(work / "model-catalog.json")
    os.environ["PROVIDER_SECRETS_FILE"] = str(work / "provider-secrets.json")
    sys.path.insert(0, str(ROOT))
    from caravan.proxy.handler import ProxyHandler

    route = json.loads((work / "agent-proxies.json").read_text())["routes"][0]

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 256

    server = Server(("127.0.0.1", port), ProxyHandler)
    server.route = route
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def stop(*_args):
        print(json.dumps({"stopped": cpu_seconds()}), flush=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    print(json.dumps({"ready": cpu_seconds()}), flush=True)
    while True:
        time.sleep(3600)


# ── the driver ────────────────────────────────────────────────────────────

def write_config(workdir, kind, proxy_port, provider_port):
    work = Path(workdir)
    (work / "logs").mkdir(parents=True, exist_ok=True)
    route = {"label": "bench", "port": proxy_port, "enabled": True, "routerId": "router:bench",
             "upstreamHost": "127.0.0.1", "upstreamPort": provider_port}
    outputs = {
        "openai": {"id": "out:bench", "name": "bench", "upstreamType": "cloud", "accountId": "acc:openai",
                   "upstreamHost": "127.0.0.1", "upstreamPort": provider_port},
        "subscription": {"id": "out:bench", "name": "bench", "upstreamType": "cloud", "accountId": "acc:sub",
                         "upstreamHost": "127.0.0.1", "upstreamPort": provider_port},
        "cell": {"id": "out:bench", "name": "bench", "upstreamHost": "127.0.0.1", "upstreamPort": provider_port},
    }
    config = {"routes": [route], "routers": [{"id": "router:bench", "outputs": [outputs[kind]],
                                              "rules": {"default": "out:bench"}}]}
    (work / "agent-proxies.json").write_text(json.dumps(config))
    claim = base64.urlsafe_b64encode(json.dumps(
        {"https://api.openai.com/auth": {"chatgpt_account_id": "acct-bench"}}).encode()).decode().rstrip("=")
    (work / "cloud-providers.json").write_text(json.dumps({"accounts": [
        {"id": "acc:openai", "type": "openai", "baseUrl": f"http://127.0.0.1:{provider_port}/v1"},
        {"id": "acc:sub", "type": "openai", "accountType": "openai-subscription",
         "baseUrl": f"http://127.0.0.1:{provider_port}"},
    ], "blocks": []}))
    (work / "provider-secrets.json").write_text(json.dumps({
        "acc:openai": {"apiKey": "sk-bench"}, "acc:sub": {"apiKey": "hdr." + claim + ".sig"}}))


DIRECT_PATHS = {"openai": "/v1/chat/completions", "subscription": "/backend-api/codex/responses",
                "cell": "/v1/chat/completions"}


def one_stream(port, path, timeout):
    """One streaming request: (whole, seconds to the first event, seconds in all).

    Whole means the stream ended the way its client expects: [DONE] for a
    chat-completions stream, response.completed for a Responses one.
    """
    body = json.dumps({"model": "bench", "stream": True,
                       "messages": [{"role": "user", "content": "count to a hundred"}]}).encode()
    began = time.monotonic()
    first = None
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            resp.read()
            return False, None, time.monotonic() - began
        while True:
            line = resp.readline()
            if not line:
                return False, first, time.monotonic() - began
            if line.startswith(b"data:"):
                if first is None:
                    first = time.monotonic() - began
                if b"[DONE]" in line or b'"response.completed"' in line:
                    return True, first, time.monotonic() - began
    except OSError:
        return False, first, time.monotonic() - began
    finally:
        conn.close()


def load(port, path, streams, requests, timeout):
    """`requests` streams, `streams` at a time: (results, seconds of wall time)."""
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=streams) as pool:
        results = list(pool.map(lambda _: one_stream(port, path, timeout), range(requests)))
    return results, time.monotonic() - began


def ms_spread(results):
    return spread([r[2] * 1000 for r in results if r[0]])


def spread(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return {"p50": values[max(0, math.ceil(0.5 * len(values)) - 1)],
            "p90": values[max(0, math.ceil(0.9 * len(values)) - 1)]}


def journal_latency(workdir):
    rows = []
    for path in sorted((Path(workdir) / "logs").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"event":"finished"' not in line:
                continue
            try:
                item = json.loads(line).get("item") or {}
            except ValueError:
                continue
            if isinstance(item.get("latency"), dict):
                rows.append(item)
    return rows


def run_level(args, kind, streams, provider_port):
    workdir = tempfile.mkdtemp(prefix="caravan-bench-")
    proxy_port = free_port()
    write_config(workdir, kind, proxy_port, provider_port)
    proxy = subprocess.Popen([sys.executable, __file__, "--role", "proxy", "--port", str(proxy_port),
                              "--workdir", workdir], stdout=subprocess.PIPE, text=True)
    requests = max(args.requests, streams * 2)
    direct, _ = load(provider_port, DIRECT_PATHS[kind], streams, requests, args.timeout)
    try:
        ready = json.loads(proxy.stdout.readline())["ready"]
        if not wait_listening(proxy_port):
            raise SystemExit("the proxy did not start")
        results, wall = load(proxy_port, "/v1/chat/completions", streams, requests, args.timeout)
        time.sleep(0.3)        # the journal is written after the client's answer
        proxy.send_signal(signal.SIGTERM)
        stopped = json.loads(proxy.stdout.readline())["stopped"]
    finally:
        if proxy.poll() is None:
            proxy.kill()
    ok = [r for r in results if r[0]]
    through, straight = ms_spread(results), ms_spread(direct)
    journal = journal_latency(workdir)
    reused = [item["latency"].get("connReused") for item in journal
              if isinstance(item["latency"].get("connReused"), bool)]
    return {
        "kind": kind, "streams": streams, "requests": requests, "ok": len(ok),
        "directOk": sum(1 for r in direct if r[0]),
        "wallSec": round(wall, 2), "perSec": round(len(ok) / wall, 1) if wall else None,
        "firstMs": spread([r[1] * 1000 for r in ok]),
        "directMs": straight, "proxyMs": through,
        "addedMs": {"p50": through["p50"] - straight["p50"], "p90": through["p90"] - straight["p90"]}
        if through and straight else None,
        "journaled": len(journal),
        "prepMs": spread([item["latency"].get("prepMs") for item in journal]),
        "cpuMs": spread([item["latency"].get("cpuMs") for item in journal]),
        "reused": f"{sum(reused)}/{len(reused)}" if reused else "-",
        "processCpuMsPerRequest": round((stopped - ready) * 1000 / max(1, len(ok)), 1),
    }


def show(row):
    def fmt(value):
        return "-" if not value else f"{value['p50']:.1f}/{value['p90']:.1f}"
    return (f"{row['kind']:>12} {row['streams']:>7} {row['ok']:>4}/{row['requests']:<4} {row['perSec']:>7}"
            f" {fmt(row['directMs']):>15} {fmt(row['proxyMs']):>15} {fmt(row['addedMs']):>11}"
            f" {fmt(row['firstMs']):>11} {fmt(row['prepMs']):>11} {fmt(row['cpuMs']):>11}"
            f" {row['processCpuMsPerRequest']:>9} {row['reused']:>8}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--role", choices=("driver", "provider", "proxy"), default="driver")
    parser.add_argument("--port", type=int)
    parser.add_argument("--workdir")
    parser.add_argument("--kind", choices=("openai", "subscription", "cell"), default="subscription")
    parser.add_argument("--streams", default="1,4,16,32", help="parallel streams per level, comma-separated")
    parser.add_argument("--requests", type=int, default=40, help="requests per level (at least 2 per stream)")
    parser.add_argument("--events", type=int, default=200, help="events in one stream")
    parser.add_argument("--gap-ms", type=float, default=10.0, help="the provider's pause between events")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--quick", action="store_true", help="a small run that must pass")
    args = parser.parse_args()
    if args.role == "provider":
        return run_provider(args.port, args.events, args.gap_ms)
    if args.role == "proxy":
        return run_proxy(args.port, args.workdir)
    if args.quick:
        args.streams, args.requests, args.events, args.gap_ms = "3", 6, 20, 2.0
    kinds = ("openai", "subscription", "cell") if args.quick else (args.kind,)
    provider_port = free_port()
    provider = subprocess.Popen([sys.executable, __file__, "--role", "provider", "--port", str(provider_port),
                                 "--events", str(args.events), "--gap-ms", str(args.gap_ms)])
    try:
        if not wait_listening(provider_port):
            raise SystemExit("the fake provider did not start")
        print(f"{args.events} events per stream, {args.gap_ms} ms apart. Figures are p50/p90 in ms: "
              f"the whole stream straight from the provider and through the proxy, the difference, "
              f"the first event through the proxy, the journal's prepMs and cpuMs, the proxy "
              f"process's processor time per request, kept connections taken.")
        print(f"{'kind':>12} {'streams':>7} {'ok':>9} {'req/s':>7} {'direct':>15} {'proxy':>15} {'added':>11}"
              f" {'first':>11} {'prep':>11} {'cpu':>11} {'proc cpu':>9} {'reused':>8}")
        rows = []
        for kind in kinds:
            for streams in [int(x) for x in str(args.streams).split(",") if x.strip()]:
                row = run_level(args, kind, streams, provider_port)
                rows.append(row)
                print(show(row), flush=True)
    finally:
        provider.terminate()
    if args.quick:
        bad = [row for row in rows if row["ok"] != row["requests"] or row["directOk"] != row["requests"]
               or row["journaled"] != row["requests"] or row["prepMs"] is None or row["cpuMs"] is None]
        pooled = [row for row in rows if row["kind"] != "cell" and not row["reused"].startswith(("0/", "-"))]
        if bad or len(pooled) != 2:
            print("bench FAILED: every stream must arrive whole and be journaled with its latency, "
                  "and the provider kinds must reuse kept connections")
            return 1
        print("bench OK: every stream whole, every request journaled with its latency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
