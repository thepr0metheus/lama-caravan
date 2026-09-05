#!/usr/bin/env python3
"""When a client refuses, the operator is told what the client said.

The controller drives every client host over HTTP. Two failures look alike from
here and are nothing alike in the world:

  * the host is UNREACHABLE — nothing answered, and the thing to check is the
    network, the scout process, the firewall;
  * the host ANSWERED and REFUSED — it is perfectly reachable and it has a
    reason: the port is busy, the model is missing, the venv is not built.

Six call sites forward work to a scout. Until caravan/service/scout.py, exactly
one of them unwrapped the refusal and showed the agent's own words; the others
called an HTTP error "client unreachable" or let it out as a bare 500 — a
confident, specific, wrong diagnosis that sends an operator to check a network
that is fine, and indistinguishable from the host really being gone.

This drives every path against a real HTTP server rather than a mock, in BOTH
worlds, and that pairing is the point: the first version of the fix made the
refusal read correctly while quietly breaking the outage, because a socket
timeout is not a URLError and only the discarded bare `except Exception` had
been catching it.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


class Truncated(BaseHTTPRequestHandler):
    """Answers, then stops mid-sentence — a scout restarted during a long call.

    Neither a refusal (it has no reason to give) nor an outage (the link was up).
    The third world, and the one the snapshot did not have: covering only the
    first two let a narrowed exception catch leak IncompleteRead and
    JSONDecodeError as raw exceptions, which is a bare 500 naming no host.
    """
    body = b"<html>not our json</html>"

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    do_GET = do_POST


class Scout(BaseHTTPRequestHandler):
    """A scout that refuses everything, the way a real one refuses: with a reason."""
    refusal = {"error": "port 22001 is already in use by llama-server"}
    status = 409

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        body = json.dumps(self.refusal).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST


def serving():
    srv = HTTPServer(("127.0.0.1", 0), Scout)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def call(fn, *args, **kwargs):
    from caravan.common.errors import AppError
    try:
        return {"ok": fn(*args, **kwargs)}
    except AppError as exc:
        return {"refused": str(exc), "status": getattr(exc, "status", None)}
    except Exception as exc:  # noqa: BLE001
        return {"raised": f"{type(exc).__name__}: {exc}"}


def main():
    from caravan.admin import fleet_clients as fc
    from caravan.common.fetch import post_json as _post

    srv, url = serving()

    # Every entry point that forwards to a scout, driven against a scout that
    # answers 409 with a reason. `_client_agent_url` is stubbed so the test does
    # not need a registered client — the question here is error handling, not
    # registry lookup.
    fc._client_agent_url = lambda host_id: url
    fc._scout_headers = lambda: {}
    # client_llama_stop does NOT go through _client_agent_url — it repeats the
    # whole lookup inline, which is why stubbing the helper does not reach it.
    # Registering a client is what drives the real path; discovering that was
    # the test being wrong, and it found a second copy of the resolution.
    from caravan.admin.state import topology as topo
    topo.clients()["h"] = {"id": "h", "agentUrl": url}

    cases = [
        ("update",      lambda: fc.client_llama_update({"hostId": "h"})),
        ("restore",     lambda: fc.client_llama_restore({"hostId": "h", "id": "x"})),
        ("stop",        lambda: fc.client_llama_stop({"hostId": "h", "port": 22001})),
        ("purge-cache", lambda: fc.client_llama_purge_cache({"hostId": "h"})),
    ]
    reason = Scout.refusal["error"]
    told = []
    for name, fn in cases:
        got = call(fn)
        text = str(got.get("refused") or got.get("raised") or got.get("ok"))
        says_reason = reason in text
        says_unreachable = "unreachable" in text.lower()
        told.append((name, says_reason, says_unreachable, text[:110]))

    print("  ── что видит оператор, когда клиент ОТВЕТИЛ и отказал:")
    for name, reason_shown, unreachable, text in told:
        verdict = "причина агента" if reason_shown else ("«недоступен» — неправда" if unreachable else "ни то ни другое")
        print(f"    {name:12} {verdict}")
        print(f"                 {text}")

    # Every forwarding path quotes the client. Before caravan/service/scout.py
    # this read: four of four LOSE the client's words, three of them calling a
    # host that answered "unreachable" and one leaking a raw exception. The
    # snapshot is inverted here on purpose — that is what the fix changed.
    lost = [n for n, r, _, _ in told if not r]
    check("каждый путь доносит слова клиента", not lost, f"теряют: {lost}")
    misdiagnosed = [n for n, r, u, _ in told if u and not r]
    check("ни один не зовёт ответивший клиент «недоступным»",
          not misdiagnosed, f"зовут: {misdiagnosed}")

    # ── and the other failure: nothing is listening at all ───────────────────
    # ── the GET side, which loses even more ──────────────────────────────────
    # fetch_json does not raise: it catches everything itself and answers
    # {"ok": False, "error": str(exc)}. So the `except Exception` wrapped around
    # these calls almost never fires — it LOOKS like error handling and is not —
    # and the agent's words are destroyed one level lower than on the POST side,
    # because the body of an HTTPError is never read at all.
    reads = [
        ("update-status", lambda: fc.client_llama_update_status("h")),
        ("builds",        lambda: fc.client_llama_builds("h")),
        # list-cache wraps its read and used to hardcode ok:True with an empty
        # model list, so a host that could not be asked was shown as a host with
        # nothing cached.
        ("list-cache",    lambda: fc.client_llama_list_cache("h")),
    ]
    print("\n  ── что видит оператор на ЧИТАЮЩИХ путях, когда клиент отказал:")
    read_told = []
    for name, fn in reads:
        got = call(fn)
        text = str(got.get("refused") or got.get("raised") or got.get("ok"))
        read_told.append((name, reason in text, text[:110]))
        print(f"    {name:14} {'причина агента' if reason in text else 'причина потеряна'}")
        print(f"                   {text}")
    lost_reads = [n for n, r, _ in read_told if not r]
    check("читающие пути тоже доносят слова клиента", not lost_reads,
          f"теряют: {lost_reads}")
    # The shape is deliberately unchanged: these answers go to the browser as
    # 200 with ok=false, and only the wording of `error` was ever wrong.
    empty_ok = [n for n, _, t in read_told if "'ok': True" in t]
    check("и ни один не выдаёт отказ за успешный пустой ответ",
          not empty_ok, f"выдают: {empty_ok}")
    check("и делают это не меняя форму ответа",
          all(t.startswith("{") and "'ok': False" in t for _, _, t in read_told),
          str([t[:60] for _, _, t in read_told]))


    srv.shutdown()
    dead = url
    fc._client_agent_url = lambda host_id: dead
    # A dead server means every call waits out its own timeout; the real ones are
    # 10-30s and four of them make this file take minutes. The question here is
    # WHAT is reported, not how long we waited for it.
    fc.post_json = lambda u, p, timeout=5, headers=None: _post(u, p, timeout=1, headers=headers)
    print("\n  ── что видит оператор, когда клиента ДЕЙСТВИТЕЛЬНО нет:")
    for name, fn in cases:
        got = call(fn)
        print(f"    {name:12} "
              f"{str(got.get('refused') or got.get('raised') or got.get('ok'))[:100]}")
    # ── the third world: answered, and the answer is unusable ────────────────
    srv3 = HTTPServer(("127.0.0.1", 0), Truncated)
    threading.Thread(target=srv3.serve_forever, daemon=True).start()
    url3 = f"http://127.0.0.1:{srv3.server_port}"
    fc._client_agent_url = lambda host_id: url3
    topo.clients()["h"] = {"id": "h", "agentUrl": url3}
    print("\n  ── что видит оператор, когда ответ ПРИШЁЛ, но его не разобрать:")
    unusable = []
    for name, fn in cases:
        got = call(fn)
        text = str(got.get("refused") or got.get("raised") or got.get("ok"))
        unusable.append((name, "raised" in got, "unusable" in text, text[:100]))
        print(f"    {name:12} {text[:95]}")
    raw_out = [n for n, r, _, _ in unusable if r]
    check("неразборчивый ответ не роняет сырое исключение", not raw_out,
          f"роняют: {raw_out}")
    named = [n for n, _, u, _ in unusable if not u]
    check("и называется собой, а не «недоступен»", not named, f"не называют: {named}")
    srv3.shutdown()
    fc._client_agent_url = lambda host_id: url
    topo.clients()["h"] = {"id": "h", "agentUrl": url}

    # The other half, and the half that caught the fix's own regression: a host
    # that never answered must still read as unreachable, and must NOT surface a
    # raw exception name. Only checking the refusal would have let that through.
    gone = []
    for name, fn in cases:
        got = call(fn)
        text = str(got.get("refused") or got.get("raised") or got.get("ok"))
        gone.append((name, "unreachable" in text.lower(),
                     "Error:" in text or "error:" in text.split(":")[0]))
    bad = [n for n, ok, _ in gone if not ok]
    check("недоступный клиент называется недоступным на всех путях",
          not bad, f"не называют: {bad}")
    leaked = [n for n, _, raw in gone if raw]
    check("и ни один не роняет сырое исключение наружу", not leaked, f"роняют: {leaked}")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
