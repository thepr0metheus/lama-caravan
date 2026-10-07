#!/usr/bin/env python3
"""Snapshot of the provider connection pool (caravan/proxy/upstream_pool.py):
the pool by itself, then through a real proxy port.

What is pinned, by value. A connection is kept only after its answer was read
to the end and nobody asked to close it; the next request to the same
provider takes it, and the provider sees one connection for two requests. A
connection the provider closed while it sat idle is not handed out; one it
closed in the instant before our request gets the request again on a fresh
connection, once. A client that vanished, a stop, a heartbeat still running,
an answer too long to finish reading — each closes the connection instead.
Every finished request carries its `latency` record.

The provider is a real HTTP/1.1 server on a free port that tells its
connections apart by the client's port.

Run: python3 scripts/test_upstream_pool.py
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-pool-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
sys.path.insert(0, str(ROOT))

import caravan.proxy.handler as handler_module  # noqa: E402
from caravan.proxy.handler import ProxyHandler  # noqa: E402
from caravan.proxy.upstream_pool import UpstreamPool, upstream_pool  # noqa: E402

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


# ── the provider ──────────────────────────────────────────────────────────
# Every request it got: (its connection's client port, the mode asked for).
seen = []
# Connections whose NEXT request is read and then hung up on, unanswered —
# the instant in which a provider drops an idle connection under a request.
hang_up_next = set()
SSE_EVENTS = [b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
              b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
              b"data: [DONE]\n\n"]


class _Provider(BaseHTTPRequestHandler):
    """Answers by the request's "mode": json | close | sse | sse-late-end | sse-stuck-end |
    slow-sse | big-error | fin-after | hang-up-next | hang-up-always."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _chunk(self, data):
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        conn_id = self.client_address[1]
        try:
            mode = json.loads(raw or b"{}").get("mode") or "json"
        except ValueError:
            mode = "json"
        seen.append((conn_id, mode))
        if conn_id in hang_up_next or mode == "hang-up-always":
            hang_up_next.discard(conn_id)
            self.close_connection = True
            return
        if mode in ("sse", "sse-late-end", "sse-stuck-end", "slow-sse"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for piece in SSE_EVENTS:
                    self._chunk(piece)
                    if mode == "slow-sse":
                        time.sleep(0.4)
                if mode == "sse-late-end":
                    time.sleep(0.5)      # the stream's closing bytes come late
                elif mode == "sse-stuck-end":
                    time.sleep(2.0)      # ... or later than the pool waits for them
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                self.close_connection = True
            return
        if mode == "big-error":
            payload = b'{"error":{"message":"' + b"x" * 200000 + b'"}}'
            self.send_response(500)
        else:
            payload = b'{"id":"x","object":"chat.completion","choices":[{"message":{"content":"hi"}}]}'
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if mode == "close":
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()
        if mode == "close":
            self.close_connection = True
        elif mode == "fin-after":
            # Keep-alive was promised, then the provider drops the idle
            # connection: the socket turns readable on our side (FIN).
            self.close_connection = True
        elif mode == "hang-up-next":
            hang_up_next.add(conn_id)


class _QuietServer(ThreadingHTTPServer):
    """A connection the proxy dropped on purpose is no error worth a traceback."""

    def handle_error(self, request, client_address):
        pass


class _Cell(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length) if length else b""
        payload = b'{"id":"c","choices":[{"message":{"content":"cell"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


PROVIDER, CELL, P_CLOUD, P_CELL = (free_port() for _ in range(4))
CONFIG = {
    "routes": [
        {"label": "cloudy", "port": P_CLOUD, "enabled": True, "routerId": "router:t",
         "upstreamHost": "127.0.0.1", "upstreamPort": CELL},
        {"label": "celly", "port": P_CELL, "enabled": True, "routerId": "router:t",
         "upstreamHost": "127.0.0.1", "upstreamPort": CELL},
    ],
    "routers": [{
        "id": "router:t",
        "outputs": [
            {"id": "out:cloud", "name": "cloud", "upstreamType": "cloud", "accountId": "acc:prov",
             "upstreamHost": "127.0.0.1", "upstreamPort": PROVIDER},
            {"id": "out:cell", "name": "cell", "upstreamHost": "127.0.0.1", "upstreamPort": CELL},
        ],
        "rules": {"bySource": [{"proxyId": f"skynet:proxy:{P_CLOUD}", "output": "out:cloud"}],
                  "default": "out:cell"},
    }],
}
Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps(CONFIG), encoding="utf-8")
Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({
    "accounts": [{"id": "acc:prov", "type": "openai", "baseUrl": f"http://127.0.0.1:{PROVIDER}/v1"}],
    "blocks": [],
}), encoding="utf-8")
Path(os.environ["PROVIDER_SECRETS_FILE"]).write_text(json.dumps({"acc:prov": {"apiKey": "sk-test"}}), encoding="utf-8")

for _route in CONFIG["routes"]:
    _srv = ThreadingHTTPServer(("127.0.0.1", _route["port"]), ProxyHandler)
    _srv.route = _route
    threading.Thread(target=_srv.serve_forever, daemon=True).start()
for _cls, _port in ((_Provider, PROVIDER), (_Cell, CELL)):
    _srv = _QuietServer(("127.0.0.1", _port), _cls)
    threading.Thread(target=_srv.serve_forever, daemon=True).start()


def post(port, mode="json", stream=False, timeout=10):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    body = json.dumps({"model": "m", "mode": mode, "stream": stream,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    try:
        conn.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def events(kind):
    rows = []
    for path in sorted(Path(os.environ["AGENT_PROXY_LOG_DIR"]).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event") == kind:
                rows.append(row)
    return rows


def last_finished(route, after):
    """The newest finished record of `route` past the first `after` ones — the
    journal is written after the client got its answer, so it is waited for."""
    for _ in range(60):
        rows = [r for r in events("finished") if r.get("route") == route]
        if len(rows) > after:
            return rows[-1].get("item") or {}
        time.sleep(0.05)
    return {}


def settle():
    """The connection goes back to the pool after the journal: wait for it."""
    time.sleep(0.15)


def finished_count(route):
    return len([r for r in events("finished") if r.get("route") == route])


# ── the pool by itself ────────────────────────────────────────────────────

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _ask(conn, mode="json"):
    conn.request("POST", "/v1/chat/completions", body=json.dumps({"mode": mode}).encode(),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp.read()
    return resp


def test_pool_keeps_and_hands_out():
    print("пул: вернуть и взять снова:")
    pool = UpstreamPool()
    conn, reused = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    check(reused is False, "первое соединение — новое")
    check(conn.sock is None, "и ещё не открыто: его откроет запрос")
    before = len(seen)
    resp = _ask(conn)
    check(pool.give_back(conn, resp) is True, "ответ прочитан до конца — соединение оставлено")
    again, reused = pool.take(False, "127.0.0.1", PROVIDER, timeout=7)
    check(again is conn and reused is True, "следующее взятие отдаёт его же")
    check(again.timeout == 7 and again.sock.gettimeout() == 7, "с таймаутом нового запроса")
    _ask(again)
    ids = {conn_id for conn_id, _ in seen[before:]}
    check(len(seen) - before == 2 and len(ids) == 1, f"провайдер видел 2 запроса в 1 соединении (соединений {len(ids)})")
    again.close()


def test_pool_refuses_what_cannot_be_reused():
    print("пул: чего не оставляет:")
    pool = UpstreamPool()
    fresh, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    check(pool.give_back(fresh, None) is False, "неоткрытое соединение не оставляется")
    conn, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    resp = _ask(conn, "close")
    check(pool.give_back(conn, resp) is False, "провайдер сказал Connection: close — закрыто")
    check(conn.sock is None, "и закрыто на самом деле")
    conn, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    conn.request("POST", "/v1/chat/completions", body=b'{"mode":"big-error"}',
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp.read(4096)
    check(pool.give_back(conn, resp) is False, "недочитанный длинный ответ не дочитывается до конца — закрыто")
    check(pool.idle_count() == 0, f"в пуле пусто (получено {pool.idle_count()})")


def test_pool_drains_the_tail():
    print("пул: дочитывает хвост потока:")
    pool = UpstreamPool()
    conn, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    conn.request("POST", "/v1/chat/completions", body=b'{"mode":"sse"}',
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    lines = []
    while True:
        line = resp.readline()
        lines.append(line)
        if b"[DONE]" in line:
            break
    check(not resp.isclosed(), "после [DONE] поток ещё не дочитан")
    check(pool.give_back(conn, resp) is True, "хвост дочитан — соединение оставлено")
    check(resp.isclosed(), "ответ закрыт как положено")
    conn.close()


def test_pool_release_does_not_wait():
    print("пул: release не ждёт хвоста потока:")
    pool = UpstreamPool()
    conn, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    resp = _ask(conn)
    pool.release(conn, resp)
    check(pool.idle_count() == 1, "дочитанный ответ — соединение в пуле сразу")
    conn, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    conn.request("POST", "/v1/chat/completions", body=b'{"mode":"sse-late-end"}',
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    while b"[DONE]" not in resp.readline():
        pass
    began = time.monotonic()
    pool.release(conn, resp)
    took = time.monotonic() - began
    check(took < 0.2, f"хвост ещё в пути — release вернулся сразу (прошло {took:.2f} с)")
    check(pool.idle_count() == 0, "соединение ещё не в пуле")
    time.sleep(0.8)
    check(pool.idle_count() == 1, "хвост дочитан — соединение в пуле")
    conn.close()


def test_pool_drops_closed_and_expired():
    print("пул: закрытое провайдером и простоявшее не отдаёт:")
    clock = _Clock()
    pool = UpstreamPool(idle_sec=60, clock=clock)
    conn, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    resp = _ask(conn, "fin-after")
    check(pool.give_back(conn, resp) is True, "ответ полный, закрыть не просили — оставлено")
    time.sleep(0.2)                 # the provider's FIN arrives
    other, reused = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    check(other is not conn and reused is False, "закрытое провайдером не отдано — новое")
    check(conn.sock is None, "а закрытое закрыто и у нас")
    resp = _ask(other)
    pool.give_back(other, resp)
    clock.now += 61
    third, reused = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    check(third is not other and reused is False, "простоявшее дольше idle_sec не отдано")
    check(other.sock is None, "и закрыто")
    third.close()


def test_pool_per_host_cap():
    print("пул: не больше per_host на провайдера:")
    pool = UpstreamPool(per_host=2)
    conns = []
    for _ in range(3):
        conn = pool._open(("http", "127.0.0.1", PROVIDER), 5)
        conns.append((conn, _ask(conn)))
    for conn, resp in conns:
        pool.give_back(conn, resp)
    check(pool.idle_count() == 2, f"в пуле два (получено {pool.idle_count()})")
    check(conns[0][0].sock is None, "самое старое закрыто")
    taken, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    check(taken is conns[2][0], "отдаётся самое свежее")
    for conn, _ in conns:
        conn.close()


def test_pool_reopen_and_stale():
    print("пул: новое соединение туда же и какие ошибки — «устарело»:")
    pool = UpstreamPool()
    conn, _ = pool.take(False, "127.0.0.1", PROVIDER, timeout=5)
    _ask(conn)
    new = pool.reopen(conn, timeout=9)
    check(conn.sock is None, "старое закрыто")
    check((new.host, new.port, new.timeout) == ("127.0.0.1", PROVIDER, 9), "новое — туда же, с таймаутом")
    check(new.sock is None, "и ещё не открыто")
    for exc, want in ((http.client.RemoteDisconnected("x"), True), (BrokenPipeError(), True),
                      (ConnectionResetError(), True), (TimeoutError(), False),
                      (http.client.BadStatusLine("x"), False), (ConnectionRefusedError(), False)):
        check(UpstreamPool.is_stale(exc) is want, f"{type(exc).__name__}: {'устарело' if want else 'не устарело'}")


# ── through a proxy port ──────────────────────────────────────────────────

def test_second_request_takes_the_kept_connection():
    print("через порт: второй запрос идёт по оставленному соединению:")
    before, n = len(seen), finished_count("cloudy")
    status1, _ = post(P_CLOUD)
    first = last_finished("cloudy", n)
    settle()
    status2, body2 = post(P_CLOUD)
    second = last_finished("cloudy", n + 1)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(status1 == 200 and status2 == 200, f"оба ответа 200 (получено {status1}, {status2})")
    check(b'"hi"' in body2, "второй ответ — ответ провайдера")
    check(len(ids) == 2 and ids[0] == ids[1], f"провайдер видел одно соединение на два запроса ({ids})")
    lat1, lat2 = first.get("latency") or {}, second.get("latency") or {}
    check(lat1.get("connReused") is False, f"первый: соединение новое (получено {lat1.get('connReused')!r})")
    check(isinstance(lat1.get("connectMs"), float), f"и время подключения измерено (получено {lat1.get('connectMs')!r})")
    check(lat2.get("connReused") is True, f"второй: соединение взято из пула (получено {lat2.get('connReused')!r})")
    check(lat2.get("connectMs") == 0.0, f"и подключения не было (получено {lat2.get('connectMs')!r})")
    for key in ("prepMs", "headersMs", "firstChunkMs", "cpuMs"):
        check(isinstance(lat2.get(key), float), f"{key} — число (получено {lat2.get(key)!r})")


def test_provider_asks_to_close():
    print("через порт: провайдер просит закрыть:")
    post(P_CLOUD)
    settle()
    before = len(seen)
    post(P_CLOUD, "close")
    settle()
    post(P_CLOUD)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(len(ids) == 2 and ids[0] != ids[1], f"после Connection: close — новое соединение ({ids})")


def test_stream_tail_drained_in_the_background():
    print("через порт: поток, хвост которого приходит поздно:")
    post(P_CLOUD)
    settle()
    before, n = len(seen), finished_count("cloudy")
    began = time.monotonic()
    status, body = post(P_CLOUD, "sse-late-end", stream=True)
    took = time.monotonic() - began
    item = last_finished("cloudy", n)
    check(status == 200 and body.rstrip().endswith(b"data: [DONE]"), f"клиент получил поток до [DONE] (статус {status})")
    check(took < 0.4, f"и не ждал хвоста провайдера (прошло {took:.2f} с)")
    check((item.get("durationMs") or 0) < 400,
          f"в журнале время запроса без хвоста (получено {item.get('durationMs')} мс)")
    time.sleep(0.7)                 # the tail arrives, the connection goes back
    post(P_CLOUD)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(len(ids) == 2 and ids[0] == ids[1], f"дочитанное соединение досталось следующему ({ids})")


def test_provider_hangs_up_under_a_request():
    print("через порт: провайдер обрывает оставленное соединение под запросом:")
    post(P_CLOUD, "hang-up-next")
    settle()
    before, n = len(seen), finished_count("cloudy")
    reconnects = len(events("upstream_reconnect"))
    status, body = post(P_CLOUD)
    item = last_finished("cloudy", n)
    settle()
    asked = seen[before:]
    check(status == 200 and b'"hi"' in body, f"клиент получил ответ (статус {status})")
    check(len(asked) == 2 and asked[0][0] != asked[1][0],
          f"запрос ушёл ещё раз, по новому соединению ({asked})")
    rows = events("upstream_reconnect")
    check(len(rows) == reconnects + 1, f"повтор записан в журнал (новых {len(rows) - reconnects})")
    check(rows and rows[-1].get("requestId") == item.get("id"), "с id этого запроса")
    check((item.get("latency") or {}).get("connReused") is False,
          f"ответило новое соединение (получено {(item.get('latency') or {}).get('connReused')!r})")


def test_provider_hangs_up_on_the_fresh_one_too():
    print("через порт: провайдер обрывает и новое соединение:")
    post(P_CLOUD)
    settle()
    before, n = len(seen), finished_count("cloudy")
    status, _ = post(P_CLOUD, "hang-up-always")
    item = last_finished("cloudy", n)
    settle()
    check(status == 502, f"клиенту 502 (получено {status})")
    check(len(seen) - before == 2, f"повтор ровно один: провайдер видел 2 попытки (получено {len(seen) - before})")
    check(item.get("errorKind") == "upstream_disconnected",
          f"обрыв записан на провайдера (получено {item.get('errorKind')!r})")


def test_provider_closed_while_idle():
    print("через порт: провайдер закрыл простаивающее соединение:")
    post(P_CLOUD, "fin-after")
    settle()
    time.sleep(0.2)
    before = len(seen)
    reconnects = len(events("upstream_reconnect"))
    status, _ = post(P_CLOUD)
    settle()
    check(status == 200, f"ответ 200 (получено {status})")
    check(len(seen) - before == 1, f"один запрос — закрытое не взято (получено {len(seen) - before})")
    check(len(events("upstream_reconnect")) == reconnects, "и повтора не понадобилось")


def test_long_error_relayed_whole():
    print("через порт: длинная ошибка провайдера:")
    post(P_CLOUD)
    settle()
    before = len(seen)
    status, body = post(P_CLOUD, "big-error")
    settle()
    post(P_CLOUD)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(status == 500, f"ошибка провайдера доходит (получено {status})")
    # The relay reads the error's first 4096 bytes for the journal and then
    # the rest of the body for the client: the answer is read to the end, so
    # the connection is clean and is kept.
    check(len(ids) == 2 and ids[0] == ids[1], f"ответ прочитан до конца — соединение оставлено ({ids})")


def test_tail_that_never_comes():
    print("через порт: хвост потока не приходит вовремя:")
    post(P_CLOUD)
    settle()
    before = len(seen)
    status, _ = post(P_CLOUD, "sse-stuck-end", stream=True)
    time.sleep(2.5)                 # the pool gave up after drain_sec; the tail came at 2 s
    post(P_CLOUD)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(status == 200, f"клиент получил поток (статус {status})")
    check(len(ids) == 2 and ids[0] != ids[1], f"недочитанное соединение закрыто, следующему — новое ({ids})")


def test_client_vanishes():
    print("через порт: клиент ушёл посреди потока:")
    post(P_CLOUD)
    settle()
    before, n = len(seen), finished_count("cloudy")
    sock = socket.create_connection(("127.0.0.1", P_CLOUD), timeout=5)
    body = json.dumps({"model": "m", "mode": "slow-sse", "stream": True,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    sock.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                 b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
    sock.recv(64)
    sock.close()
    item = last_finished("cloudy", n)
    settle()
    post(P_CLOUD)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(item.get("errorKind") == "client_disconnected", f"уход записан на клиента (получено {item.get('errorKind')!r})")
    check(len(ids) == 2 and ids[0] != ids[1], f"брошенное соединение не досталось следующему ({ids})")


def test_stop_reached_the_control():
    print("через порт: стоп с доски успел к соединению:")
    from caravan.proxy.queue_admission import close_active_request, register_active_control, unregister_active_control

    class _Conn:
        sock = None

        def close(self):
            pass

    register_active_control("pool-stop", "cloudy", _Conn())
    close_active_request("pool-stop", reason="stopped")
    got = unregister_active_control("pool-stop")
    check((got or {}).get("stopReason") == "stopped", f"снятая запись отдаёт причину стопа (получено {got!r})")
    check(unregister_active_control("pool-stop") is None, "снятая второй раз — None")
    post(P_CLOUD)
    settle()
    before = len(seen)
    real = handler_module.unregister_active_control
    handler_module.unregister_active_control = lambda request_id: dict(real(request_id) or {}, stopReason="stopped")
    try:
        post(P_CLOUD)
        settle()
    finally:
        handler_module.unregister_active_control = real
    post(P_CLOUD)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(len(ids) == 2 and ids[0] != ids[1], f"соединение, к которому шёл стоп, закрыто ({ids})")


class _StuckThread:
    """A heartbeat that does not stop when asked: join returns, the thread lives on."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return True


def test_heartbeat_still_running():
    print("через порт: сердцебиение ещё живо:")
    post(P_CLOUD)
    settle()
    before = len(seen)
    real = handler_module.threading
    handler_module.threading = types.SimpleNamespace(
        Thread=_StuckThread, Lock=real.Lock, Event=real.Event, get_ident=real.get_ident)
    try:
        post(P_CLOUD, stream=True)
        settle()
    finally:
        handler_module.threading = real
    post(P_CLOUD)
    settle()
    ids = [conn_id for conn_id, _ in seen[before:]]
    check(len(ids) == 2 and ids[0] != ids[1], f"соединение, до которого может дотянуться сердцебиение, закрыто ({ids})")


def test_cell_is_not_pooled():
    print("через порт: ячейка — без пула:")
    n = finished_count("celly")
    status, _ = post(P_CELL)
    lat = last_finished("celly", n).get("latency") or {}
    check(status == 200, f"ответ 200 (получено {status})")
    check(lat.get("connReused") is None, f"«из пула или нет» не утверждается (получено {lat.get('connReused')!r})")
    check(isinstance(lat.get("connectMs"), float), f"время подключения измерено (получено {lat.get('connectMs')!r})")
    check(isinstance(lat.get("prepMs"), float) and lat["prepMs"] >= 0, f"своя работа — число (получено {lat.get('prepMs')!r})")


for fn in (test_pool_keeps_and_hands_out, test_pool_refuses_what_cannot_be_reused, test_pool_drains_the_tail,
           test_pool_release_does_not_wait, test_pool_drops_closed_and_expired, test_pool_per_host_cap,
           test_pool_reopen_and_stale,
           test_second_request_takes_the_kept_connection, test_provider_asks_to_close,
           test_stream_tail_drained_in_the_background, test_provider_hangs_up_under_a_request,
           test_provider_hangs_up_on_the_fresh_one_too,
           test_provider_closed_while_idle, test_long_error_relayed_whole, test_tail_that_never_comes,
           test_client_vanishes,
           test_stop_reached_the_control, test_heartbeat_still_running, test_cell_is_not_pooled):
    fn()

print()
print(f"(в пуле прокси сейчас {upstream_pool.idle_count()} соединений)")
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all upstream-pool snapshots hold")
