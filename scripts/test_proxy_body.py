#!/usr/bin/env python3
"""Value snapshot: a request's body as the proxy takes it off the connection (1.3.505).

A body comes by its Content-Length, or in chunks (`Transfer-Encoding: chunked` — curl uploading
a pipe, a client streaming a file it does not measure first). The proxy read the length alone:
a body in chunks went upstream as none, and a consumer of the entry was told its request was
neither JSON nor a form. Pinned, by value:

  * RequestBody: what it reads, what it leaves on the connection, and each way a body cannot
    be read;
  * through a port, to a real cell on 127.0.0.1: the body whole, with its own length and none
    of the client's framing; a body that cannot be read refused in the port's words, journaled,
    the connection closed, the cell never asked;
  * through the entry, for a consumer: the model found in a body sent in chunks, the body
    reaching the pool's cell whole, the refusal in OpenAI's shape.

Run: python3 scripts/test_proxy_body.py
"""
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-proxy-body-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
sys.path.insert(0, str(ROOT))

from caravan.proxy.entry import EntryHandler  # noqa: E402
from caravan.proxy.handler import ProxyHandler  # noqa: E402
from caravan.proxy.paths import HOP_HEADERS  # noqa: E402
from caravan.proxy.request_body import RequestBody  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def headers_of(raw):
    return http.client.parse_headers(io.BytesIO(raw))


def body_of(raw_headers, raw_body):
    """(what RequestBody read, what it left) — or (the refusal's words, None)."""
    rfile = io.BytesIO(raw_body)
    try:
        return RequestBody.read(headers_of(raw_headers), rfile), rfile.read()
    except RequestBody.Malformed as exc:
        return f"Malformed: {exc}", None


def test_reading():
    print("RequestBody — по длине или частями:")
    check(body_of(b"Content-Length: 5\r\n\r\n", b"hello, and the next request") == (b"hello", b", and the next request"),
          "по длине — ровно столько; остальное на соединении не тронуто")
    check(body_of(b"\r\n", b"x") == (None, b"x") and body_of(b"Content-Length: 0\r\n\r\n", b"x") == (None, b"x"),
          "без длины и с длиной 0 — тела нет (None, как прокси читал и раньше)")
    chunked = b"4;ext=1\r\nWiki\r\n6\r\npedia \r\nE\r\n in\r\n\r\nchunks.\r\n0\r\nX-Sum: 1\r\n\r\nNEXT"
    check(body_of(b"Transfer-Encoding: chunked\r\n\r\n", chunked) == (b"Wikipedia  in\r\n\r\nchunks.", b"NEXT"),
          "частями — части склеены, расширения и хвост (trailers) пропущены, следующего не прочитано")
    check(body_of(b"Transfer-Encoding: Chunked\r\nContent-Length: 3\r\n\r\n", b"5\r\nhello\r\n0\r\n\r\n") == (b"hello", b""),
          "частями и с длиной — читаются части: длина клиента не в счёт (RFC 9112)")
    check(body_of(b"Transfer-Encoding: chunked\r\n\r\n", b"0\r\n\r\n") == (b"", b"")
          and body_of(b"Transfer-Encoding: chunked\r\n\r\n", b"0\r\n") == (b"", b""),
          "boundary: ни одной части — пустое тело; клиент, закрывший после последней части, тело закончил")
    check(body_of(b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n", b"ok") == (b"ok", b""),
          "длина дважды, одинаково — читается")
    cases = (
        (b"Transfer-Encoding: gzip, chunked\r\n\r\n", b"0\r\n\r\n",
         "Transfer-Encoding gzip, chunked is not read: send the body by its length or in chunks"),
        (b"Content-Length: 2\r\nContent-Length: 3\r\n\r\n", b"abc", "Content-Length is given twice, differently"),
        (b"Content-Length: abc\r\n\r\n", b"", "Content-Length is not a number"),
        (b"Content-Length: -1\r\n\r\n", b"", "Content-Length is not a number"),
        (b"Content-Length: 10\r\n\r\n", b"short", "the body ended after 5 of its 10 bytes"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"zz\r\n", "a chunk's size is not a hex number"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"-5\r\n", "a chunk's size is not a hex number"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"5" * 5000 + b"\r\n", "a chunk's size line is too long"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"5\r\nhel", "the body ended inside a chunk"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"5\r\nhello", "a chunk does not end where its size says"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"5\r\nhelloXX\r\n", "a chunk does not end where its size says"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"5\r\nhello\r\n", "the body ended inside its chunks"),
        (b"Transfer-Encoding: chunked\r\n\r\n", b"0\r\n" + b"X: 1\r\n" * 65 + b"\r\n", "more than 64 trailer lines"),
    )
    for raw_headers, raw_body, why in cases:
        got = body_of(raw_headers, raw_body)
        check(got == (f"Malformed: {why}", None), f"negative: {why} (got {got[0]!r})")
    check("transfer-encoding" in HOP_HEADERS and "trailer" in HOP_HEADERS and "trailers" not in HOP_HEADERS,
          "Transfer-Encoding и Trailer — заголовки одного перехода, дальше не идут (было «trailers» — такого заголовка нет)")


# ── a cell on 127.0.0.1 that says what reached it ────────────────────────────
seen = []


class _Cell(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": raw})
        payload = json.dumps({"id": "c1", "object": "chat.completion", "got": len(raw),
                              "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                           "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(handler_class):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


CELL = serve(_Cell)
KEY = "lcv1_" + "k" * 48
PORT = serve(ProxyHandler)
PORT.route = {"label": "agent-body", "port": PORT.server_address[1], "enabled": True, "upstreamHost": "127.0.0.1",
              "upstreamPort": CELL.server_address[1], "routerId": "router:t"}
ENTRY = serve(EntryHandler)
ENTRY.route = None
CONSUMER = {"label": "Hermes", "port": 1, "kind": "consumer", "apiKey": KEY, "pool": "std", "portClosed": True,
            "enabled": True}
Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps({
    "routes": [PORT.route, CONSUMER],
    "routers": [{"id": "router:t", "outputs": [
        {"id": "srv:1", "name": "cell", "upstreamHost": "127.0.0.1", "upstreamPort": CELL.server_address[1],
         "upstreamType": "llama"}],
        "rules": {"defaultOutput": "srv:1"}, "graph": {"nodes": [], "edges": []}}],
    "policy": {"maxSlots": 2}}), encoding="utf-8")
Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({
    "accounts": [], "pools": [{"id": "std", "name": "Standart", "contextLength": 32000,
                               "steps": [{"id": "r1", "output": "srv:1"}]}]}), encoding="utf-8")

CHAT = json.dumps({"model": "m", "messages": [{"role": "user", "content": "x" * 70000}]}).encode()


def pieces(body, size=4096):
    return [body[i:i + size] for i in range(0, len(body), size)]


def send(server, body_parts=None, headers=None, path="/v1/chat/completions", length=None):
    """A request through http.client: in chunks when `body_parts` is a list, by length when bytes."""
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=15)
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if isinstance(body_parts, list):
        conn.request("POST", path, body=iter(body_parts), headers=hdrs, encode_chunked=True)
    else:
        conn.request("POST", path, body=body_parts, headers=hdrs)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data


def raw_send(server, head, body, shut=False):
    """Bytes as a client might send them, then everything the proxy answers, to the end of the
    connection: (status line, the answer's body, whether the proxy closed the connection)."""
    sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=15)
    sock.sendall(head + body)
    if shut:
        sock.shutdown(socket.SHUT_WR)
    chunks = []
    closed = False
    try:
        while True:
            data = sock.recv(65536)
            if not data:
                closed = True
                break
            chunks.append(data)
    except socket.timeout:
        pass
    sock.close()
    raw = b"".join(chunks)
    head_part, _, rest = raw.partition(b"\r\n\r\n")
    return head_part.split(b"\r\n", 1)[0].decode("latin-1"), rest, closed, head_part.decode("latin-1")


def journal(reason):
    rows = [json.loads(line) for p in Path(os.environ["AGENT_PROXY_LOG_DIR"]).rglob("*.jsonl")
            for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r["item"] for r in rows if r.get("event") == "blocked" and (r.get("item") or {}).get("reason") == reason]


def test_port():
    print("через порт — до ячейки и обратно:")
    seen.clear()
    status, _h, data = send(PORT, pieces(CHAT), {"Trailer": "X-Sum"})
    got = seen[-1] if seen else {"headers": {}, "body": b""}
    check(status == 200 and json.loads(data).get("got") == len(CHAT),
          f"тело частями (70 КБ кусками по 4 КБ) — ячейке целиком, её ответ — клиенту (got {status} {data[:80]!r})")
    check(got["body"] == CHAT and got["headers"].get("content-length") == str(len(CHAT))
          and "transfer-encoding" not in got["headers"] and "trailer" not in got["headers"],
          "ячейке — те же байты со своей длиной; negative: ни chunked, ни Trailer клиента дальше не идут")

    seen.clear()
    head = (b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\ncontent-length: 3\r\nConnection: close\r\n\r\n")
    body = b"".join(b"%x\r\n%s\r\n" % (len(p), p) for p in pieces(CHAT, 9000)) + b"0\r\n\r\n"
    line, _rest, _closed, _head = raw_send(PORT, head, body)
    got = seen[-1] if seen else {"headers": {}, "body": b""}
    check(line.endswith("200 OK") and got["body"] == CHAT and got["headers"].get("content-length") == str(len(CHAT)),
          "частями и с ложной длиной 3 — ячейке тело целиком и его настоящая длина: ложная длина клиента дальше не идёт")

    seen.clear()
    status, _h, data = send(PORT, CHAT)
    check(status == 200 and seen and seen[-1]["body"] == CHAT and seen[-1]["headers"].get("content-length") == str(len(CHAT)),
          "по длине — как было: те же байты, та же длина")
    seen.clear()
    lever = json.dumps({"model": "m", "reasoning_effort": "none", "messages": [{"role": "user", "content": "hi"}]}).encode()
    status, _h, _d = send(PORT, pieces(lever, 7))
    got = seen[-1] if seen else {"headers": {}, "body": b""}
    check(status == 200 and got["body"] != lever and json.loads(got["body"]).get("chat_template_kwargs") == {"enable_thinking": False}
          and got["headers"].get("content-length") == str(len(got["body"])),
          "тело, которое караван переписал для ячейки («без размышлений»), — с длиной нового тела")

    seen.clear()
    head = b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"
    line, rest, closed, head_text = raw_send(PORT, head, b"zz\r\nhello\r\n0\r\n\r\n")
    check(line.endswith("400 Bad Request") and json.loads(rest) == {
        "error": "the request body cannot be read: a chunk's size is not a hex number", "kind": "bad_request"},
        f"кривая часть — 400 словами порта, с причиной (got {line!r} {rest[:120]!r})")
    check(closed and "Connection: close" in head_text and not seen,
          "соединение закрыто с ответом — остаток тела не читается как запрос; negative: ячейку не спросили")
    blocked = journal("unreadable-body")
    check(blocked and blocked[-1].get("status") == 400 and blocked[-1].get("port") == PORT.route["port"]
          and blocked[-1].get("path") == "/v1/chat/completions",
          "отказ — в журнале, как любой отказ до ячейки: blocked, unreadable-body, порт и путь")

    head = b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n"
    line, rest, closed, _h = raw_send(PORT, head, b"0123456789", shut=True)
    check(line.endswith("400 Bad Request") and json.loads(rest).get("error")
          == "the request body cannot be read: the body ended after 10 of its 100 bytes" and closed and not seen,
          "тело короче своей длины (клиент закрыл на 10 байтах из 100) — 400; negative: обрезок ячейке не ушёл")


def test_entry():
    print("через вход — клиент с ключом:")
    auth = {"Authorization": f"Bearer {KEY}"}
    seen.clear()
    status, _h, data = send(ENTRY, pieces(json.dumps({"model": "Standart", "messages": [{"role": "user", "content": "y" * 20000}]}).encode()), auth)
    got = seen[-1] if seen else {"headers": {}, "body": b""}
    sent = json.loads(got["body"] or b"{}")
    check(status == 200 and sent.get("messages") == [{"role": "user", "content": "y" * 20000}]
          and got["headers"].get("content-length") == str(len(got["body"])) and "transfer-encoding" not in got["headers"],
          f"тело частями: модель найдена, запрос дошёл до ячейки пула целым и со своей длиной (got {status} {data[:100]!r})")
    status, _h, data = send(ENTRY, [b'{"model": ', b'"Standart"}'], auth, path="/api/show")
    check(status == 200 and json.loads(data).get("model_info", {}).get("caravan.context_length") == 32000,
          "Ollama /api/show частями — окно пула, как по длине")
    head = (b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + KEY.encode()
            + b"\r\nTransfer-Encoding: chunked\r\n\r\n")
    seen.clear()
    line, rest, closed, _h = raw_send(ENTRY, head, b"5\r\nhelloXX\r\n0\r\n\r\n")
    check(line.endswith("400 Bad Request") and json.loads(rest)["error"] == {
        "message": "The request body cannot be read: a chunk does not end where its size says.",
        "type": "invalid_request_error", "param": None, "code": None} and closed and not seen,
        f"кривое тело — 400 в форме OpenAI; negative: ячейку не спросили (got {line!r} {rest[:160]!r})")
    blocked = journal("entry:broken-body")
    check(blocked and blocked[-1].get("route") == "Hermes" and blocked[-1].get("status") == 400,
          "отказ — в журнале под именем клиента")


test_reading()
test_port()
test_entry()
if _fail:
    print(f"\nFAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("\nproxy body snapshot holds")
