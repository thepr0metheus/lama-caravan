#!/usr/bin/env python3
"""Характеризующий снимок ФАЗЫ 6: что отвечает POST через прокси-порт.

Пинит ЗНАЧЕНИЕ каждого исхода, до которого запрос доходит без очереди: режимы
paused и drain, порт без роутера, ключ API (нет/неверный/верный), обычная
пересылка к живому апстриму, пересылка его 4xx и 5xx вместе с телом, и апстрим,
который не слушает.

Зачем именно до переписывания: `ProxyHandler.proxy` — это 879 строк из 1170 в
файле, семь уровней вложенности и двадцать веток `except`, из которых пятнадцать
голые `except Exception`, а десять из них — `pass`. Десять мест, где любая беда
исчезает без следа: разбирать такой метод, не пришпилив исходы, нельзя.

Сервер настоящий: ProxyHandler на свободном порту с одноразовым конфигом.

Запуск: python3 scripts/test_proxy_forward.py
"""
import base64
import http.client
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
TMP = Path(tempfile.mkdtemp(prefix="caravan-fwd-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
sys.path.insert(0, str(ROOT))

from caravan.proxy.handler import ProxyHandler  # noqa: E402

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


# ── поддельный апстрим ───────────────────────────────────────────────────────
# Отвечает по пути: /ok обычным JSON, /bad400 и /bad503 — ошибкой с телом,
# чтобы проверить, что статус И причина доходят до клиента как есть.
seen = []
# Три события и терминатор — минимальный поток, который клиент считает полным.
SSE_CHUNKS = [
    b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
    b'data: [DONE]\n\n',
]


class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        seen.append((self.path, raw))
        if self.path.endswith("stream"):
            # Апстрим объявляет text/event-stream — по этому заголовку прокси и
            # решает, что ответ потоковый (handler.py:641).
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for piece in SSE_CHUNKS:
                self.wfile.write(piece)
                self.wfile.flush()
            self.close_connection = True
            return
        if self.path.endswith("bad400"):
            status, payload = 400, b'{"error":{"message":"upstream says no"}}'
        elif self.path.endswith("bad503"):
            status, payload = 503, b'{"error":{"message":"upstream is busy"}}'
        else:
            status, payload = 200, b'{"id":"x","choices":[{"message":{"content":"hi"}}]}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


BIGSLOW = free_port()
BIG_CHUNK = b"x" * 65536
BIG_CHUNKS = 12
big_seen = []


class _BigSlowCell(BaseHTTPRequestHandler):
    """Не-потоковый ответ в 12 кусков по 64 КБ с паузами — чтобы клиент успел уйти
    посреди ретрансляции, и следующая запись ЕМУ упала у прокси."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length) if length else b""
        big_seen.append(time.time())
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BIG_CHUNK) * BIG_CHUNKS))
        self.end_headers()
        try:
            for _ in range(BIG_CHUNKS):
                self.wfile.write(BIG_CHUNK)
                self.wfile.flush()
                time.sleep(0.15)
        except OSError:
            pass


FAILING = free_port()
BACKUP = free_port()
failing_hits = []
backup_hits = []


class _FailingCell(BaseHTTPRequestHandler):
    """Апстрим, который всегда отвечает ошибкой — но говорит, чем именно."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        failing_hits.append(self.rfile.read(length) if length else b"")
        payload = b'{"error":{"message":"primary is down"}}'
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _BackupCell(BaseHTTPRequestHandler):
    """Запасной выход: отвечает нормально и запоминает, что до него дошло."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        backup_hits.append(self.rfile.read(length) if length else b"")
        payload = b'{"id":"rescued","choices":[{"message":{"content":"saved"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


KA_SLOT = free_port()
KA_SECONDS = 3.0


class _KeepaliveCell(BaseHTTPRequestHandler):
    """Один слот, отвечает долго и потоком — чтобы ожидающий успел получить биения."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        payload = b'[{"id": 0}]'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length) if length else b""
        time.sleep(KA_SECONDS)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in SSE_CHUNKS:
            self.wfile.write(piece)
            self.wfile.flush()
        self.close_connection = True


ONE_SLOT = free_port()
TWO_SLOT = free_port()
SLOW_SECONDS = 1.5


def _make_slow_cell(slot_count):
    """Медленная ячейка, объявляющая ровно slot_count слотов.

    Число слотов прокси узнаёт САМ, спрашивая /slots у апстрима, — отсюда и
    берётся вместимость очереди. Поэтому давление в снимке настоящее, а не
    выставленное настройкой.
    """

    class _Slow(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            payload = json.dumps([{"id": i} for i in range(slot_count)]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length) if length else b""
            time.sleep(SLOW_SECONDS)
            payload = b'{"id":"slow","choices":[{"message":{"content":"ok"}}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return _Slow


LOADING = free_port()
OTHER503 = free_port()
# Сколько раз ячейка ответит "Loading model" прежде чем подняться.
loading_left = [1]
loading_hits = []


class _LoadingCell(BaseHTTPRequestHandler):
    """Ячейка, которая ещё грузит модель: 503 с телом llama.cpp, потом 200."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length) if length else b""
        loading_hits.append(time.time())
        if loading_left[0] > 0:
            loading_left[0] -= 1
            payload = b'{"error":{"code":503,"message":"Loading model","type":"unavailable_error"}}'
            self.send_response(503)
        else:
            payload = b'{"id":"loaded","choices":[{"message":{"content":"up"}}]}'
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _Other503(BaseHTTPRequestHandler):
    """503 БЕЗ слов про загрузку — такой ретраить нельзя, он про другое."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length) if length else b""
        payload = b'{"error":{"message":"no slots available"}}'
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


SUB = free_port()
# Токен подписки: chatgpt-account-id прокси достаёт из ПРЕТЕНЗИИ внутри JWT,
# а не из конфигурации, — поэтому в фикстуре настоящий (невалидно подписанный)
# токен с этой претензией.
_SUB_CLAIM = base64.urlsafe_b64encode(json.dumps(
    {"https://api.openai.com/auth": {"chatgpt_account_id": "acct-test-123"}}
).encode()).decode().rstrip("=")
SUB_TOKEN = "hdr." + _SUB_CLAIM + ".sig"
# События Responses-API в том порядке, в котором их ждёт
# _iter_responses_as_completions_sse.
SUB_EVENTS = [
    b'data: {"type":"response.output_text.delta","delta":"he"}\n\n',
    b'data: {"type":"response.output_text.delta","delta":"llo"}\n\n',
    # The codex backend sends each finished item as output_item.done and a
    # completed response WITHOUT `output` — seen live; a buffered Responses
    # client gets the items assembled from these.
    b'data: {"type":"response.output_item.done","item":{"type":"message","role":"assistant",'
    b'"content":[{"type":"output_text","text":"hello"}]}}\n\n',
    b'data: {"type":"response.completed","response":{"status":"completed",'
    b'"usage":{"input_tokens":3,"output_tokens":2}}}\n\n',
]
sub_seen = []


class _Subscription(BaseHTTPRequestHandler):
    """Отвечает так, как отвечает codex-эндпоинт подписки: потоком Responses-API."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        sub_seen.append((self.path, dict(self.headers), raw))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in SUB_EVENTS:
            self.wfile.write(piece)
            self.wfile.flush()
        self.close_connection = True


ANTHRO = free_port()
# События Anthropic в том порядке, в котором их ждёт _iter_anthropic_as_completions_sse.
ANTHRO_EVENTS = [
    b'event: content_block_start\ndata: {"type":"content_block_start","index":0,'
    b'"content_block":{"type":"text","text":""}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"he"}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"llo"}}\n\n',
    b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
    b'"usage":{"output_tokens":2}}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
]
anthro_seen = []


class _Anthropic(BaseHTTPRequestHandler):
    """Отвечает так, как отвечает настоящий Anthropic: своим потоком событий."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        anthro_seen.append((self.path, dict(self.headers), raw))
        try:
            asked = json.loads(raw)
        except Exception:
            asked = {}
        text = json.dumps(asked.get("messages") or "")
        if "LOADING503" in text:
            # Облако, отвечающее теми же словами, что и грузящаяся ячейка.
            # Ретраить ТАКОЕ нельзя: у провайдера 503 значит другое.
            payload = b'{"error":{"type":"overloaded_error","message":"Loading model"}}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if not asked.get("stream"):
            # Не-потоковый ответ Anthropic — одним документом.
            payload = json.dumps({"id": "msg_1", "type": "message", "role": "assistant",
                                  "model": "claude-test-model",
                                  "content": [{"type": "text", "text": "hello"}],
                                  "stop_reason": "end_turn",
                                  "usage": {"input_tokens": 3, "output_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ANTHRO_EVENTS:
            self.wfile.write(piece)
            self.wfile.flush()
        self.close_connection = True


UP = free_port()
DEAD = free_port()
RUDE = free_port()


def _rude_upstream():
    """Принимает соединение и молча закрывает — так ведёт себя умирающая ячейка."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", RUDE))
    srv.listen(8)
    while True:
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            return
(P_OK, P_DEAD, P_PAUSED, P_DRAIN, P_UNROUTED, P_KEYED, P_RUDE, P_ANTHRO, P_SUB,
 P_LOAD, P_OTHER503, P_Q1A, P_Q1B, P_Q2A, P_Q2B, P_KA_A, P_KA_B,
 P_RESCUE, P_NORESCUE, P_VANISH, P_VANISH2) = (free_port() for _ in range(21))


def _route(port, **extra):
    base = {"label": f"r{port}", "port": port, "enabled": True,
            "upstreamHost": "127.0.0.1", "upstreamPort": UP, "routerId": "router:t"}
    base.update(extra)
    return base


CONFIG = {
    "routes": [
        _route(P_OK), _route(P_DEAD), _route(P_PAUSED, mode="paused"),
        _route(P_DRAIN, mode="drain"), _route(P_UNROUTED, routerId=""),
        _route(P_KEYED, apiKey="s3cret"), _route(P_RUDE),
        _route(P_ANTHRO, upstreamType="cloud", providerId="blk:anthro"),
        # Маршрут в АККАУНТ, не в блок: только этот путь несёт accountType,
        # по которому и опознаётся подписка (у блока такого поля нет).
        _route(P_SUB),
        _route(P_LOAD), _route(P_OTHER503),
        _route(P_Q1A), _route(P_Q1B), _route(P_Q2A), _route(P_Q2B),
        _route(P_KA_A), _route(P_KA_B),
        _route(P_RESCUE), _route(P_NORESCUE), _route(P_VANISH), _route(P_VANISH2),
    ],
    "routers": [{
        "id": "router:t",
        "outputs": [
            {"id": "out:up", "name": "up", "upstreamHost": "127.0.0.1", "upstreamPort": UP},
            {"id": "out:dead", "name": "dead", "upstreamHost": "127.0.0.1", "upstreamPort": DEAD},
            {"id": "out:rude", "name": "rude", "upstreamHost": "127.0.0.1", "upstreamPort": RUDE},
            {"id": "out:sub", "name": "sub", "upstreamType": "cloud", "accountId": "acc:sub",
             "upstreamHost": "127.0.0.1", "upstreamPort": SUB},
            {"id": "out:load", "name": "load", "upstreamHost": "127.0.0.1", "upstreamPort": LOADING},
            {"id": "out:o503", "name": "o503", "upstreamHost": "127.0.0.1", "upstreamPort": OTHER503},
            {"id": "out:q1", "name": "q1", "upstreamHost": "127.0.0.1", "upstreamPort": ONE_SLOT},
            {"id": "out:q2", "name": "q2", "upstreamHost": "127.0.0.1", "upstreamPort": TWO_SLOT},
            # ВАЖНО: без префикса out:. resolve_graph отрезает его у ссылки в
            # ребре и ищет остаток среди outputs, тогда как pick_router_output
            # (правила bySource) сверяет полный id. У двух резолверов разные
            # соглашения, и на проде id выходов именно такие: srv:22001, cb:...
            {"id": "ka", "name": "ka", "upstreamHost": "127.0.0.1", "upstreamPort": KA_SLOT},
            {"id": "fail", "name": "fail", "upstreamHost": "127.0.0.1", "upstreamPort": FAILING},
            {"id": "out:bigslow", "name": "bigslow", "upstreamHost": "127.0.0.1", "upstreamPort": BIGSLOW},
            {"id": "backup", "name": "backup", "upstreamHost": "127.0.0.1", "upstreamPort": BACKUP},
        ],
        "graph": {
            "nodes": [
                {"id": "q1", "type": "queue", "config": {
                    "admitEdge": "ea", "spillEdge": "es", "maxSlots": 1, "keepaliveSec": 1}},
                {"id": "e1", "type": "onError", "config": {
                    "mainEdge": "emain", "rescueEdge": "eresc"}},
            ],
            "edges": [
                {"id": "ein_a", "from": f"in:skynet:proxy:{P_KA_A}", "to": "rule:q1"},
                {"id": "ein_b", "from": f"in:skynet:proxy:{P_KA_B}", "to": "rule:q1"},
                {"id": "ea", "from": "rule:q1", "to": "out:ka"},
                # Спасение: главное ребро ведёт в падающий выход, запасное — в
                # рабочий. Резолвер запасное лишь ЗАПИСЫВАЕТ; повтор делает
                # обработчик, и только после настоящего отказа.
                {"id": "ein_r", "from": f"in:skynet:proxy:{P_RESCUE}", "to": "rule:e1"},
                {"id": "emain", "from": "rule:e1", "to": "out:fail"},
                {"id": "eresc", "from": "rule:e1", "to": "out:backup"},
                {"id": "es", "from": "rule:q1", "to": "out:ka"},
            ],
        },
        "rules": {"bySource": [{"proxyId": f"skynet:proxy:{P_DEAD}", "output": "out:dead"},
                               {"proxyId": f"skynet:proxy:{P_RUDE}", "output": "out:rude"},
                               {"proxyId": f"skynet:proxy:{P_SUB}", "output": "out:sub"},
                               {"proxyId": f"skynet:proxy:{P_LOAD}", "output": "out:load"},
                               {"proxyId": f"skynet:proxy:{P_OTHER503}", "output": "out:o503"},
                               {"proxyId": f"skynet:proxy:{P_NORESCUE}", "output": "fail"},
                               {"proxyId": f"skynet:proxy:{P_VANISH}", "output": "out:bigslow"},
                               {"proxyId": f"skynet:proxy:{P_VANISH2}", "output": "out:q1"},
                               {"proxyId": f"skynet:proxy:{P_Q1A}", "output": "out:q1"},
                               {"proxyId": f"skynet:proxy:{P_Q1B}", "output": "out:q1"},
                               {"proxyId": f"skynet:proxy:{P_Q2A}", "output": "out:q2"},
                               {"proxyId": f"skynet:proxy:{P_Q2B}", "output": "out:q2"}],
                  "defaultOutput": "out:up"},
    }],
}
Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps(CONFIG), encoding="utf-8")
Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({
    "accounts": [{"id": "acc:anthro", "type": "anthropic",
                  "baseUrl": f"http://127.0.0.1:{ANTHRO}"},
                 {"id": "acc:sub", "type": "openai", "accountType": "openai-subscription",
                  "baseUrl": f"http://127.0.0.1:{SUB}"}],
    "blocks": [{"id": "blk:anthro", "accountId": "acc:anthro", "model": "claude-test-model"}],
}), encoding="utf-8")
# Без ключа маршрут отвечает "cloud provider not configured" и до перевода не доходит.
Path(os.environ["PROVIDER_SECRETS_FILE"]).write_text(
    json.dumps({"acc:anthro": {"apiKey": "sk-test"},
                "acc:sub": {"apiKey": SUB_TOKEN}}), encoding="utf-8")

for _r in CONFIG["routes"]:
    _s = ThreadingHTTPServer(("127.0.0.1", _r["port"]), ProxyHandler)
    _s.route = _r
    threading.Thread(target=_s.serve_forever, daemon=True).start()
for _srv_cls, _srv_port in ((_LoadingCell, LOADING), (_Other503, OTHER503),
                            (_make_slow_cell(1), ONE_SLOT), (_make_slow_cell(2), TWO_SLOT),
                            (_KeepaliveCell, KA_SLOT), (_FailingCell, FAILING),
                            (_BackupCell, BACKUP), (_BigSlowCell, BIGSLOW)):
    _s = ThreadingHTTPServer(("127.0.0.1", _srv_port), _srv_cls)
    threading.Thread(target=_s.serve_forever, daemon=True).start()
_sub = ThreadingHTTPServer(("127.0.0.1", SUB), _Subscription)
threading.Thread(target=_sub.serve_forever, daemon=True).start()
_anthro = ThreadingHTTPServer(("127.0.0.1", ANTHRO), _Anthropic)
threading.Thread(target=_anthro.serve_forever, daemon=True).start()
_up = ThreadingHTTPServer(("127.0.0.1", UP), _Upstream)
threading.Thread(target=_up.serve_forever, daemon=True).start()
threading.Thread(target=_rude_upstream, daemon=True).start()

BODY = json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}]}).encode()


# Ответа ждём недолго и НАМЕРЕННО: проверка, которая висит, хуже упавшей.
# Доказано на этом же файле — если снять условие про загрузку модели, любой 503
# начинает ретраиться до конца дедлайна, и прогон замирал вместо того, чтобы
# покраснеть. Таймаут превращается в обычный провал с внятными словами.
RESPONSE_TIMEOUT = 12


def post(port, path="/v1/chat/completions", headers=None, body=BODY, want_headers=False):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=RESPONSE_TIMEOUT)
    try:
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json", **(headers or {})})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
        got = {k.lower(): v for k, v in resp.getheaders()}
        status = resp.status
    except (TimeoutError, socket.timeout, OSError) as exc:
        status, raw, got = 0, f"НЕТ ОТВЕТА за {RESPONSE_TIMEOUT} с: {exc}", {}
    finally:
        conn.close()
    return (status, raw, got) if want_headers else (status, raw)


def test_response_headers():
    """Каждый отказ обязан закрывать соединение — и говорить об этом.

    Три пути ответа ошибкой написаны здесь от руки, почти одинаково, и в
    комментарии рядом с одним из них записано, чем это кончилось: копия без
    `Connection: close` оставляла поток слушателя припаркованным в readline()
    без таймаута, пока клиент держал сокет. Пинится ЗАГОЛОВОК, а не только тело.
    """
    print("заголовки ответов на отказ:")
    cases = (("не привязан к роутеру", P_UNROUTED), ("заблокирован", P_PAUSED),
             ("апстрим не слушает", P_DEAD), ("апстрим разорвал", P_RUDE),
             ("нет ключа", P_KEYED))
    for label, port in cases:
        status, raw, got = post(port, want_headers=True)
        check(got.get("connection") == "close",
              f"{label}: Connection: close (получено {got.get('connection')!r})")
        check(got.get("content-type") == "application/json",
              f"{label}: тип содержимого json (получено {got.get('content-type')!r})")
        check(got.get("content-length") == str(len(raw.encode())),
              f"{label}: длина совпадает с телом (заявлено {got.get('content-length')}, отдано {len(raw.encode())})")


def test_blocked_modes():
    print("режимы paused и drain:")
    for port, mode in ((P_PAUSED, "paused"), (P_DRAIN, "drain")):
        status, raw = post(port)
        doc = json.loads(raw)
        check(status == 503, f"{mode}: 503 (получено {status})")
        check(doc.get("kind") == "blocked", f"{mode}: kind=blocked")
        check(doc.get("error") == f"proxy route r{port} is {mode}",
              f"{mode}: сообщение называет маршрут и режим")


def test_unrouted():
    print("порт, не привязанный к роутеру:")
    status, raw = post(P_UNROUTED)
    doc = json.loads(raw)
    check(status == 503, f"503 (получено {status})")
    check((doc.get("error") or {}).get("type") == "unrouted", "type=unrouted")
    check("unassigned" in ((doc.get("error") or {}).get("message") or ""),
          "сообщение называет причину")


def test_api_key():
    print("ключ API:")
    status, raw = post(P_KEYED)
    check(status == 401, f"без ключа: 401 (получено {status})")
    check((json.loads(raw).get("error") or {}).get("type") == "unauthorized", "type=unauthorized")
    status, _ = post(P_KEYED, headers={"Authorization": "Bearer wrong"})
    check(status == 401, f"неверный ключ: 401 (получено {status})")
    status, _ = post(P_KEYED, headers={"Authorization": "Bearer s3cret"})
    check(status == 200, f"верный ключ: 200 (получено {status})")
    status, _ = post(P_KEYED, headers={"x-api-key": "s3cret"})
    check(status == 200, f"тот же ключ через x-api-key: 200 (получено {status})")


def test_forward():
    print("обычная пересылка к живому апстриму:")
    before = len(seen)
    status, raw = post(P_OK)
    check(status == 200, f"200 (получено {status})")
    check(json.loads(raw).get("id") == "x", "тело апстрима доходит как есть")
    check(len(seen) == before + 1, "апстрим получил ровно один запрос")
    path, body = seen[-1]
    check(path == "/v1/chat/completions", f"по тому же пути (получено {path})")
    check(json.loads(body).get("model") == "m", "и с тем же телом")


def test_upstream_errors():
    print("апстрим отвечает ошибкой:")
    for path, want in (("/v1/bad400", 400), ("/v1/bad503", 503)):
        status, raw = post(P_OK, path=path)
        check(status == want, f"{path}: статус апстрима сохранён (получено {status})")
        check("upstream" in raw, f"{path}: и его причина дошла до клиента — {raw[:60]!r}")


def test_upstream_down():
    print("апстрим не слушает:")
    status, raw = post(P_DEAD)
    check(status == 502, f"502 (получено {status})")
    check(raw.strip() != "", "с непустым телом, а не молча")
    # ЗАФИКСИРОВАНО КАК ЕСТЬ, НЕ КАК ХОРОШО: наружу уходит номер ошибки
    # операционной системы. Это то же семейство, что чинили в фазе 5 у тела
    # запроса, — внутренняя деталь в ответе клиенту. Снимок обязан записать
    # это до переписывания, чтобы правка была видна как правка.
    doc = json.loads(raw)
    check(isinstance(doc.get("error"), str) and "Errno" in doc["error"],
          f"текст системного отказа сохранён — {doc.get('error')!r}")
    check("Connection refused" in (doc.get("error") or ""), "и он про отказ в соединении")
    check(doc.get("kind") == "proxy_error",
          f"вид ошибки теперь есть, той же формой что у блокировок (получено {doc.get('kind')!r})")


def test_classifier_both_sides():
    """Один и тот же errno значит разное в зависимости от того, кто ещё на связи."""
    print("classify_proxy_error, обе стороны:")
    from caravan.proxy.translate import classify_proxy_error as cls
    reset = ConnectionResetError(54, "Connection reset by peer")
    check(cls(reset, client_present=False) == "client_disconnected",
          "клиент мог уйти — значит ушёл клиент")
    check(cls(reset, client_present=True) == "upstream_disconnected",
          "клиент на связи — значит разорвал апстрим")
    check(cls(BrokenPipeError(32, "Broken pipe"), client_present=True) == "upstream_disconnected",
          "то же для разорванного канала")
    check(cls(TimeoutError("timed out"), client_present=True) == "upstream_timeout",
          "таймаут остаётся таймаутом при любом клиенте")
    check(cls(TimeoutError("timed out"), client_present=False) == "upstream_timeout",
          "и при ушедшем тоже")
    check(cls(ValueError("boom"), client_present=True) == "proxy_error",
          "всё прочее — общая ошибка прокси")
    # Умолчание обязано остаться прежним: старый вызов без факта не должен
    # менять поведение молча.
    check(cls(reset) == "client_disconnected", "умолчание не изменилось")


def test_streaming_relay():
    """Потоковый путь: что видит клиент и что попадает в журнал.

    Самый горячий путь плоскости данных и до сих пор не пришпиленный: снимок
    покрывал не-потоковые ответы и отказы. Трогать его нельзя, пока исходы не
    записаны.
    """
    print("потоковая ретрансляция:")
    before = len(seen)
    conn = http.client.HTTPConnection("127.0.0.1", P_OK, timeout=30)
    conn.request("POST", "/v1/stream", body=BODY, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    got_headers = {k.lower(): v for k, v in resp.getheaders()}
    body = resp.read()
    conn.close()

    check(resp.status == 200, f"статус 200 (получено {resp.status})")
    check(got_headers.get("content-type", "").startswith("text/event-stream"),
          f"тип содержимого потоковый (получено {got_headers.get('content-type')!r})")
    check(got_headers.get("cache-control") == "no-cache",
          f"кеширование запрещено (получено {got_headers.get('cache-control')!r})")
    check(got_headers.get("connection") == "close",
          f"соединение закрывается (получено {got_headers.get('connection')!r})")
    check("content-length" not in got_headers,
          "длина НЕ объявляется — она неизвестна заранее")
    # Кадр SSE завершается ПУСТОЙ строкой. Ретранслятор выходит из цикла,
    # увидев `data: [DONE]`, и раньше оставлял эту строку непрочитанной в
    # сокете — клиент получал на байт меньше, а строгий разборщик последний
    # кадр не отдавал вовсе. Оба переводящих итератора терминатор отдают, и
    # _send_sse_error тоже: незавершённым кадр оставлял ровно один путь из трёх.
    expected_sent = b"".join(SSE_CHUNKS)
    check(body == expected_sent, f"поток дошёл байт в байт (хвост {body[-24:]!r})")
    check(body.endswith(b"data: [DONE]\n\n"),
          f"кадр [DONE] завершён пустой строкой (хвост {body[-16:]!r})")
    check(len(seen) == before + 1, "апстрим получил ровно один запрос")


def test_streaming_journal():
    """Учёт чанков в журнале — то, по чему доска считает активность."""
    print("учёт потока в журнале:")
    rows = {r.get("route"): r for r in _finished_events((f"r{P_OK}",))}
    row = rows.get(f"r{P_OK}") or {}
    item = row.get("item") or {}
    check(int(item.get("chunks") or 0) >= len(SSE_CHUNKS),
          f"посчитаны все события (chunks={item.get('chunks')}, послано {len(SSE_CHUNKS)})")
    check(int(item.get("bytes") or 0) == len(b"".join(SSE_CHUNKS)),
          f"журнал считает ровно то, что получил клиент "
          f"(bytes={item.get('bytes')}, послано {len(b''.join(SSE_CHUNKS))})")
    check(row.get("status") == 200, f"статус в журнале 200 (получено {row.get('status')})")
    check(not row.get("errorKind"), f"вида ошибки нет (получено {row.get('errorKind')!r})")


def test_anthropic_translation():
    """Перевод Anthropic → completions: что уходит наверх и что приходит вниз.

    Один из двух путей перевода. Оба цикла побайтно одинаковы кроме вызова
    итератора, но сводить их нельзя, пока исходы не пришпилены — снимок потока
    уже показал, чем это кончается.
    """
    print("перевод anthropic → completions:")
    before = len(anthro_seen)
    conn = http.client.HTTPConnection("127.0.0.1", P_ANTHRO, timeout=30)
    conn.request("POST", "/v1/chat/completions", body=STREAM_BODY,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    got_headers = {k.lower(): v for k, v in resp.getheaders()}
    body = resp.read()
    conn.close()

    # ── что ушло наверх ──────────────────────────────────────────────────────
    check(len(anthro_seen) == before + 1, f"апстрим получил один запрос (получено {len(anthro_seen)-before})")
    path, sent_headers, sent_body = anthro_seen[-1]
    low = {k.lower(): v for k, v in sent_headers.items()}
    check(path == "/messages", f"путь переписан на /messages (получено {path!r})")
    check(low.get("x-api-key") == "sk-test", f"ключ идёт заголовком x-api-key (получено {low.get('x-api-key')!r})")
    check("authorization" not in low, "и НЕ как Bearer — у anthropic своя схема")
    check(low.get("anthropic-version") == "2023-06-01",
          f"версия API проставлена (получено {low.get('anthropic-version')!r})")
    sent = json.loads(sent_body)
    check(sent.get("model") == "claude-test-model",
          f"модель переписана на модель блока (получено {sent.get('model')!r})")
    check(isinstance(sent.get("messages"), list) and sent["messages"],
          f"тело в форме anthropic (ключи {sorted(sent)})")
    check("max_tokens" in sent, "и с обязательным для anthropic max_tokens")

    # ── что пришло вниз ──────────────────────────────────────────────────────
    check(resp.status == 200, f"клиенту 200 (получено {resp.status})")
    check(got_headers.get("content-type", "").startswith("text/event-stream"),
          f"клиенту поток (получено {got_headers.get('content-type')!r})")
    check(body.endswith(b"data: [DONE]\n\n"),
          f"поток завершён терминатором (хвост {body[-20:]!r})")
    frames = [l for l in body.split(b"\n\n") if l.startswith(b"data: ") and b"[DONE]" not in l]
    check(len(frames) >= 2, f"кадров с дельтами не меньше двух (получено {len(frames)})")
    parsed_frames = [json.loads(f[6:]) for f in frames]
    check(all(f.get("object") == "chat.completion.chunk" for f in parsed_frames),
          "каждый кадр — chat.completion.chunk, а не событие anthropic")
    ids = {f.get("id") for f in parsed_frames}
    check(len(ids) == 1 and next(iter(ids)).startswith("chatcmpl-"),
          f"один id в форме completions на весь поток (получено {ids})")
    text = "".join(str((f.get("choices") or [{}])[0].get("delta", {}).get("content") or "")
                   for f in parsed_frames)
    check(text == "hello", f"текст собрался из дельт (получено {text!r})")
    check(any((f.get("choices") or [{}])[0].get("finish_reason") for f in parsed_frames),
          "причина остановки доехала")


def test_subscription_translation():
    """Перевод Responses-API → completions: вторая из двух переводящих веток.

    Опознаётся по `accountType`, которое несёт ТОЛЬКО маршрут в аккаунт: у блока
    такого поля нет, и подписка распознавалась бы лишь по домену в baseUrl.
    """
    print("перевод responses-api → completions:")
    before = len(sub_seen)
    conn = http.client.HTTPConnection("127.0.0.1", P_SUB, timeout=30)
    conn.request("POST", "/v1/chat/completions", body=BODY,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    got_headers = {k.lower(): v for k, v in resp.getheaders()}
    body = resp.read()
    conn.close()

    # ── что ушло наверх ──────────────────────────────────────────────────────
    check(len(sub_seen) == before + 1, f"апстрим получил один запрос (получено {len(sub_seen)-before})")
    path, sent_headers, sent_body = sub_seen[-1]
    low = {k.lower(): v for k, v in sent_headers.items()}
    check(path == "/backend-api/codex/responses", f"путь переписан (получено {path!r})")
    check(low.get("authorization") == f"Bearer {SUB_TOKEN}",
          "токен идёт как Bearer — у подписки своя схема, не x-api-key")
    check(low.get("chatgpt-account-id") == "acct-test-123",
          f"идентификатор аккаунта ИЗВЛЕЧЁН ИЗ ТОКЕНА, а не настроен "
          f"(получено {low.get('chatgpt-account-id')!r})")
    check(low.get("originator") == "pi", f"originator проставлен (получено {low.get('originator')!r})")
    check(low.get("openai-beta") == "responses=experimental",
          f"бета-заголовок проставлен (получено {low.get('openai-beta')!r})")
    check(low.get("accept") == "text/event-stream",
          f"запрошен поток (получено {low.get('accept')!r})")
    sent = json.loads(sent_body)
    check("input" in sent, f"тело в форме Responses-API, а не chat (ключи {sorted(sent)})")
    check("messages" not in sent, "поле messages не переехало как есть")

    # ── что пришло вниз ──────────────────────────────────────────────────────
    check(resp.status == 200, f"клиенту 200 (получено {resp.status})")
    check(got_headers.get("content-type", "").startswith("text/event-stream"),
          f"клиенту поток (получено {got_headers.get('content-type')!r})")
    check(body.endswith(b"data: [DONE]\n\n"),
          f"поток завершён терминатором (хвост {body[-20:]!r})")
    frames = [l for l in body.split(b"\n\n") if l.startswith(b"data: ") and b"[DONE]" not in l]
    parsed_frames = [json.loads(f[6:]) for f in frames]
    check(parsed_frames and all(f.get("object") == "chat.completion.chunk" for f in parsed_frames),
          f"каждый кадр — chat.completion.chunk (кадров {len(parsed_frames)})")
    ids = {f.get("id") for f in parsed_frames}
    check(len(ids) == 1 and next(iter(ids)).startswith("chatcmpl-"),
          f"один id в форме completions на весь поток (получено {ids})")
    text = "".join(str((f.get("choices") or [{}])[0].get("delta", {}).get("content") or "")
                   for f in parsed_frames)
    check(text == "hello", f"текст собрался из дельт (получено {text!r})")


def test_responses_passthrough():
    """Клиент, говорящий на Responses API (Codex CLI), проходит сквозь порт подписки.

    Переводчик chat→Responses брал только `messages`; тело с `input` уезжало
    наверх с пустым `input`, и codex-бэкенд отвечал «One of input… must be
    provided». Сквозной режим: тело как написано, поток — как пришёл.
    """
    from caravan.proxy.translate import is_responses_request
    print("сквозной responses-api через подписку:")
    check(is_responses_request("/v1/responses", b"{}") is True, "путь /v1/responses опознаётся сам по себе")
    check(is_responses_request("/v1/chat/completions", b'{"input":"hi"}') is True,
          "тело с input и без messages опознаётся на любом пути")
    check(is_responses_request("/v1/chat/completions", BODY) is False, "negative: chat-тело с messages — не Responses")
    check(is_responses_request("/v1/chat/completions", b"not json") is False, "negative: мусор — не Responses")

    req = {"model": "m", "instructions": "sys", "store": True, "stream": True,
           "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
           "tools": [{"type": "function", "name": "f", "parameters": {"type": "object"}}],
           "reasoning": {"effort": "low"}}
    before = len(sub_seen)
    conn = http.client.HTTPConnection("127.0.0.1", P_SUB, timeout=30)
    conn.request("POST", "/v1/responses", body=json.dumps(req).encode(),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    got_headers = {k.lower(): v for k, v in resp.getheaders()}
    body = resp.read()
    conn.close()

    check(len(sub_seen) == before + 1, f"апстрим получил один запрос (получено {len(sub_seen)-before})")
    path, sent_headers, sent_body = sub_seen[-1]
    low = {k.lower(): v for k, v in sent_headers.items()}
    check(path == "/backend-api/codex/responses", f"путь переписан на codex (получено {path!r})")
    check(low.get("authorization") == f"Bearer {SUB_TOKEN}" and low.get("chatgpt-account-id") == "acct-test-123",
          "токен и идентификатор аккаунта — как у переводящей ветки")
    sent = json.loads(sent_body)
    check(sent.get("input") == req["input"], f"input ушёл как написан (получено {sent.get('input')!r})")
    check(sent.get("instructions") == "sys" and sent.get("tools") == req["tools"] and sent.get("reasoning") == req["reasoning"],
          "instructions, tools и reasoning клиента не тронуты")
    check(sent.get("store") is False and sent.get("stream") is True,
          f"бэкенд подписки диктует store:false и stream:true (получено store={sent.get('store')!r}, stream={sent.get('stream')!r})")
    check(sent.get("model") == "m", f"без блока модель клиента остаётся (получено {sent.get('model')!r})")
    check("messages" not in sent, "negative: поле messages не появилось из ниоткуда")
    from caravan.proxy.translate import _responses_passthrough_body
    as_string, _, _ = _responses_passthrough_body(json.dumps({"model": "m", "input": "hi", "stream": True}).encode(), None)
    check(json.loads(as_string)["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
          "boundary: input строкой (публичный API разрешает) становится одним ходом пользователя — бэкенд подписки берёт только список")

    check(resp.status == 200, f"клиенту 200 (получено {resp.status})")
    check(got_headers.get("content-type", "").startswith("text/event-stream"),
          f"клиенту поток (получено {got_headers.get('content-type')!r})")
    check(body == b"".join(SUB_EVENTS),
          f"поток отдан БЕЗ перевода — события Responses как пришли (получено {body[:80]!r}…)")
    check(b"chat.completion.chunk" not in body and not body.endswith(b"data: [DONE]\n\n"),
          "negative: ни кадров completions, ни дописанного [DONE]")

    row = {r.get("route"): r for r in _finished_events((f"r{P_SUB}",))}.get(f"r{P_SUB}") or {}
    item = row.get("item") or {}
    check(int(item.get("chunks") or 0) >= len(SUB_EVENTS) and int(item.get("bytes") or 0) == len(b"".join(SUB_EVENTS)),
          f"журнал считает ровно отданные байты, чанков не меньше событий (chunks={item.get('chunks')}, bytes={item.get('bytes')})")
    usage = (item.get("stream") or {}).get("usage") or {}
    check(usage.get("prompt_tokens") == 3 and usage.get("completion_tokens") == 2,
          f"usage из response.completed учтён для счётчика расходов (получено {usage!r})")
    check("response" not in (item.get("stream") or {}), "negative: сам объект ответа в журнал не попал")
    req_summary = item.get("request") or {}
    check(req_summary.get("messages") == 1 and req_summary.get("roles") == ["user"] and req_summary.get("promptTextChars") == 2,
          f"сводка запроса читает input как сообщения — панель маршрута не покажет «запрос ни о чём» (получено {req_summary.get('messages')!r}, {req_summary.get('roles')!r}, {req_summary.get('promptTextChars')!r})")

    # Буферизованный ответ: клиент просит stream:false — наверх всё равно stream:true,
    # вниз — объект response из response.completed.
    req["stream"] = False
    conn = http.client.HTTPConnection("127.0.0.1", P_SUB, timeout=30)
    conn.request("POST", "/v1/responses", body=json.dumps(req).encode(),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    got_headers = {k.lower(): v for k, v in resp.getheaders()}
    body = resp.read()
    conn.close()
    sent = json.loads(sub_seen[-1][2])
    check(sent.get("stream") is True, f"наверх всё равно stream:true (получено {sent.get('stream')!r})")
    check(resp.status == 200 and got_headers.get("content-type", "").startswith("application/json"),
          f"клиенту 200 JSON (получено {resp.status} {got_headers.get('content-type')!r})")
    try:
        final = json.loads(body)
    except Exception:
        final = {}
    check(final.get("usage", {}).get("input_tokens") == 3 and final.get("status") == "completed",
          f"тело — объект response из response.completed (получено {body[:120]!r})")
    texts = [c.get("text") for it in final.get("output") or [] for c in (it.get("content") or []) if isinstance(c, dict)]
    check(texts == ["hello"],
          f"output собран из output_item.done — бэкенд подписки в completed его не отдаёт (получено {final.get('output')!r})")


def test_loading_model_retry():
    """Ячейка ещё грузит модель: 503 ретраится, любой другой 503 — нет.

    Условие узкое по трём осям сразу: НЕ облако, статус ровно 503, и в теле
    слова llama.cpp про загрузку. Негативный случай здесь обязателен — без него
    проверка не отличит «ретрай сработал» от «ретрая нет вовсе».
    """
    print("ретрай на загружающейся модели:")
    loading_left[0] = 1
    loading_hits.clear()
    began = time.time()
    status, raw = post(P_LOAD)
    took = time.time() - began

    check(status == 200, f"клиент дождался поднявшейся ячейки (получено {status})")
    check(json.loads(raw).get("id") == "loaded", "и получил её ответ, а не 503")
    check(len(loading_hits) == 2, f"апстрим опрошен дважды (получено {len(loading_hits)})")
    check(took >= 3.0, f"между попытками выдержана пауза (прошло {took:.1f} с)")
    gap = (loading_hits[1] - loading_hits[0]) if len(loading_hits) > 1 else 0
    check(2.5 <= gap <= 6.0, f"пауза около трёх секунд (получено {gap:.1f} с)")

    # Тот же статус, другое тело — ретраить нельзя: это не про загрузку.
    began = time.time()
    status, raw = post(P_OTHER503)
    took = time.time() - began
    check(status == 503, f"другой 503 доходит как есть (получено {status})")
    check("no slots" in raw, f"и с причиной апстрима (получено {raw[:60]!r})")
    check(took < 2.0, f"без всякой паузы (прошло {took:.1f} с)")


def test_loading_model_journal():
    """Ретрай обязан быть ВИДЕН: иначе ожидание выглядит как зависший запрос."""
    print("ретрай в журнале:")
    rows = []
    for path in sorted(Path(os.environ["AGENT_PROXY_LOG_DIR"]).glob("*")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("event") == "loading_model_retry":
                rows.append(row)
    check(len(rows) == 1, f"записана ровно одна попытка (получено {len(rows)})")
    row = rows[0] if rows else {}
    check(row.get("attempt") == 1, f"её номер (получено {row.get('attempt')!r})")
    check(row.get("retryDelaySec") == 3.0, f"и задержка (получено {row.get('retryDelaySec')!r})")
    check(isinstance(row.get("remainingSec"), (int, float)) and row.get("remainingSec") > 0,
          f"и сколько ещё готовы ждать (получено {row.get('remainingSec')!r})")


def _post_pair(port_a, port_b):
    """Два запроса разом, каждый со своего порта в один и тот же апстрим."""
    out = {}

    def _run(key, port):
        began = time.time()
        status, raw = post(port, body=BODY)
        out[key] = (status, raw, time.time() - began)

    threads = [threading.Thread(target=_run, args=(k, p)) for k, p in (("a", port_a), ("b", port_b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=RESPONSE_TIMEOUT + 10)
    return out


def test_queue_waits_for_a_free_slot():
    """Второй запрос ЖДЁТ, когда слот у апстрима один, и НЕ ждёт, когда их два.

    Вместимость прокси узнаёт сам, спрашивая /slots, поэтому обе половины —
    настоящие. Негативная здесь обязательна: без неё «оба дошли за две секунды»
    одинаково объясняется и работающей очередью, и её отсутствием.
    """
    print("очередь: ожидание свободного слота:")
    one = _post_pair(P_Q1A, P_Q1B)
    check(len(one) == 2, f"оба запроса вернулись (получено {len(one)})")
    check(all(v[0] == 200 for v in one.values()),
          f"и оба успешно (получено {[v[0] for v in one.values()]})")
    waits = sorted(v[2] for v in one.values())
    check(waits[0] < SLOW_SECONDS + 1.0,
          f"первый прошёл сразу ({waits[0]:.1f} с при работе апстрима {SLOW_SECONDS} с)")
    check(waits[1] >= SLOW_SECONDS * 1.6,
          f"второй дождался освобождения слота ({waits[1]:.1f} с)")

    two = _post_pair(P_Q2A, P_Q2B)
    check(all(v[0] == 200 for v in two.values()),
          f"на двух слотах оба успешны (получено {[v[0] for v in two.values()]})")
    both = sorted(v[2] for v in two.values())
    check(both[1] < SLOW_SECONDS * 1.6,
          f"и НИ ОДИН не ждал — оба обслужены разом ({both[1]:.1f} с)")


def test_queue_visible_in_journal():
    """Ожидание обязано быть ВИДНО: иначе очередь неотличима от медленного апстрима."""
    print("очередь в журнале:")
    rows = {}
    for row in _finished_events((f"r{P_Q1A}", f"r{P_Q1B}")):
        rows[row.get("route")] = row
    queued = []
    for name in (f"r{P_Q1A}", f"r{P_Q1B}"):
        item = (rows.get(name) or {}).get("item") or {}
        queued.append(int((item.get("queue") or {}).get("queuedMs") or 0))
    check(len(queued) == 2, f"обе записи найдены (получено {len(queued)})")
    # Не «ровно ноль»: у прошедшего сразу набегает единица-другая миллисекунд,
    # и первая версия этой проверки от них краснела. Пинится РАЗНИЦА — она и
    # есть смысл очереди, — а не точное значение быстрой половины.
    check(max(queued) >= SLOW_SECONDS * 1000 * 0.6,
          f"у ждавшего записано время в очереди, сравнимое с работой апстрима (получено {queued})")
    check(min(queued) < 200, f"у прошедшего сразу — почти ноль (получено {queued})")
    check(max(queued) > min(queued) * 10 + 100,
          f"и разница между ними на порядок (получено {queued})")


STREAM_BODY = json.dumps({"model": "m", "stream": True,
                          "messages": [{"role": "user", "content": "hi"}]}).encode()


def test_keepalive_holds_a_queued_client():
    """Пока запрос ждёт слот, клиенту идут биения — иначе он отвалится по таймауту.

    Биение — не комментарий SSE, а НАСТОЯЩИЙ кадр с дельтой в канале мышления.
    Так и записано в docstring keepalive_sse_bytes: клиенты сбрасывают свой
    таймаут чтения только на кадрах с текстом токена, а `: comment` и пустую
    дельту игнорируют. Пинится именно это — форма кадра, а не факт записи.
    """
    print("сердцебиение очереди:")
    out = {}

    def _run(key, port):
        began = time.time()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=RESPONSE_TIMEOUT + 15)
        try:
            conn.request("POST", "/v1/chat/completions", body=STREAM_BODY,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            head = {k.lower(): v for k, v in resp.getheaders()}
            data = resp.read()
            out[key] = (resp.status, head, data, time.time() - began)
        except Exception as exc:
            out[key] = (0, {}, f"НЕТ ОТВЕТА: {exc}".encode(), time.time() - began)
        finally:
            conn.close()

    # Оба клиента — на ОДИН порт: так ходит настоящий агент, и так не срабатывает
    # липкая резервация слота, которая держится за портом (два разных порта в один
    # апстрим добавляли к ожиданию два десятка секунд — это отдельный шов).
    threads = [threading.Thread(target=_run, args=(k, P_KA_A))
               for k in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=RESPONSE_TIMEOUT + 25)

    check(len(out) == 2, f"оба запроса вернулись (получено {len(out)})")
    check(all(v[0] == 200 for v in out.values()),
          f"и оба успешно (получено {[v[0] for v in out.values()]})")
    check(all(v[1].get("content-type", "").startswith("text/event-stream") for v in out.values()),
          "обоим сразу отданы потоковые заголовки, ещё до похода к апстриму")

    waiter = max(out.values(), key=lambda v: v[3])
    fast = min(out.values(), key=lambda v: v[3])
    beats = waiter[2].count(b'"chatcmpl-keepalive"')
    check(beats >= 1, f"ждавший получил биения, пока стоял в очереди (получено {beats})")
    check(b'"reasoning_content"' in waiter[2],
          "биение несёт дельту в канале мышления, а не пустую и не комментарий")
    check(b'": keepalive"' not in waiter[2], "и это НЕ комментарий SSE — его клиенты игнорируют")
    check(fast[2].count(b'"chatcmpl-keepalive"') == 0,
          f"прошедшему сразу биения не нужны и не шлются (получено "
          f"{fast[2].count(b'"chatcmpl-keepalive"')})")
    check(waiter[2].endswith(b"data: [DONE]\n\n"),
          f"и настоящий ответ дошёл следом (хвост {waiter[2][-20:]!r})")
    check(waiter[3] > fast[3] + KA_SECONDS * 0.5,
          f"ждавший провёл в очереди примерно работу первого "
          f"({waiter[3]:.1f} с против {fast[3]:.1f} с)")


def test_keepalive_not_sent_without_streaming():
    """Негативный случай: непотоковый запрос ранних заголовков не получает.

    Условие узкое — только потоковый и только не-облако. Без этой половины
    проверка не отличит работающее сердцебиение от того, что оно шлётся всем.
    """
    print("сердцебиение: непотоковый запрос:")
    status, raw, head = post(P_Q1A, want_headers=True)
    check(status == 200, f"обычный запрос успешен (получено {status})")
    check(head.get("content-type", "").startswith("application/json"),
          f"и получает свой тип, а не поток (получено {head.get('content-type')!r})")
    check("chatcmpl-keepalive" not in raw, "никаких биений в непотоковом ответе")


def test_rescue_replays_on_a_backup_exit():
    """Отказ главного выхода не доходит до клиента, если есть запасной.

    Повтор делает обработчик, а не резолвер: узел лишь ЗАПИСЫВАЕТ запасное
    ребро, и оно используется только после настоящего отказа — и только пока
    клиенту не отдано ни байта.
    """
    print("спасение через запасной выход:")
    f_before, b_before = len(failing_hits), len(backup_hits)
    status, raw = post(P_RESCUE)

    check(status == 200, f"клиент получил успех, а не отказ главного (получено {status})")
    check(json.loads(raw).get("id") == "rescued", f"и ответ ЗАПАСНОГО выхода (получено {raw[:60]!r})")
    check(len(failing_hits) == f_before + 1, "главный выход был опрошен ровно раз")
    check(len(backup_hits) == b_before + 1, "и запасной ровно раз")
    check(failing_hits[-1] == backup_hits[-1],
          "на запасной ушло ТО ЖЕ тело — это повтор, а не новый запрос")

    # Негативная половина: без запасного выхода отказ доходит как есть.
    f2 = len(failing_hits)
    status, raw = post(P_NORESCUE)
    check(status == 500, f"без запасного выхода отказ доходит до клиента (получено {status})")
    check("primary is down" in raw, f"и с причиной главного (получено {raw[:60]!r})")
    check(len(failing_hits) == f2 + 1, "и повтора не было — опрос ровно один")


def test_rescue_visible_in_journal():
    """Спасение обязано быть ВИДНО: молчаливая подмена выхода — худший вид магии."""
    print("спасение в журнале:")
    retries, finished = [], None
    for path in sorted(Path(os.environ["AGENT_PROXY_LOG_DIR"]).glob("*")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("event") == "rescue_retry":
                retries.append(row)
            elif row.get("event") == "finished" and row.get("route") == f"r{P_RESCUE}":
                finished = row
    check(len(retries) == 1, f"записан ровно один повтор (получено {len(retries)})")
    row = retries[0] if retries else {}
    check(row.get("hop") == 1, f"его номер (получено {row.get('hop')!r})")
    check(row.get("status") == 500, f"и статус, из-за которого спасали (получено {row.get('status')!r})")
    check("primary is down" in str(row.get("upstreamErrorBody") or ""),
          f"и слова упавшего апстрима (получено {str(row.get('upstreamErrorBody'))[:50]!r})")

    resc = ((finished or {}).get("item") or {}).get("rescued") or {}
    check(resc.get("hops") == 1, f"итоговая запись сознаётся в спасении (получено {resc!r})")
    trail = resc.get("trail") or []
    check(len(trail) == 1 and trail[0].get("status") == 500,
          f"и хранит след: откуда и с каким отказом ушли (получено {trail})")


def test_error_inside_an_open_stream():
    """Отказ ПОСЛЕ того, как заголовки уже ушли, приходит кадром SSE.

    Для потокового запроса прокси отдаёт 200 и заголовки СРАЗУ, ещё не сходив к
    апстриму, — чтобы держать клиента биениями. Значит статус уже потрачен, и
    единственный способ сообщить об отказе — событие error и следом [DONE]: без
    терминатора клиент досидит до собственного таймаута вместо того, чтобы
    упасть сразу.

    Эта ветка (_send_sse_error) была введена в фазе 6 и не выполнялась НИ ОДНОЙ
    проверкой — дыру нашло состязательное ревью, и я подтвердил её счётчиком:
    ноль вызовов на весь снимок.
    """
    print("отказ внутри уже открытого потока:")
    conn = http.client.HTTPConnection("127.0.0.1", P_RUDE, timeout=RESPONSE_TIMEOUT)
    try:
        conn.request("POST", "/v1/chat/completions", body=STREAM_BODY,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        head = {k.lower(): v for k, v in resp.getheaders()}
        body = resp.read()
        status = resp.status
    finally:
        conn.close()

    check(status == 200, f"статус уже потрачен на заголовки — 200 (получено {status})")
    check(head.get("content-type", "").startswith("text/event-stream"),
          f"и это поток (получено {head.get('content-type')!r})")
    check(b"event: error" in body, f"отказ пришёл СОБЫТИЕМ, а не телом (получено {body[:80]!r})")
    check(body.endswith(b"data: [DONE]\n\n"),
          f"и поток закрыт терминатором (хвост {body[-20:]!r})")

    frame = body.split(b"event: error\ndata: ", 1)[-1].split(b"\n\n", 1)[0]
    doc = json.loads(frame)
    check(doc.get("kind") == "upstream_disconnected",
          f"вид ошибки доехал и не свален на клиента (получено {doc.get('kind')!r})")
    check(str(doc.get("error") or "").strip() != "", f"с непустой причиной (получено {doc.get('error')!r})")


def test_client_vanishes_mid_response():
    """Клиент уходит САМ посреди не-потокового ответа. Кого винит журнал?

    Флаг `_client_gone` ставил только поток сердцебиения,
    а он стартует лишь для потоковых запросов — у обычного POST на плече
    пересылки детекции ухода клиента не было. Падала запись КЛИЕНТУ (EPIPE),
    флаг оставался ложным, и classify_proxy_error(client_present=True)
    списывал это на апстрим — та же подмена, которую фаза 6 чинила в другую
    сторону. Теперь провал записи клиенту помечается в самой _client_write.
    Нашло состязательное ревью, воспроизвели трое скептиков A/B против
    дерева до фазы 6.
    """
    print("клиент уходит посреди не-потокового ответа:")
    import socket as _socket
    import struct as _struct
    before = len(big_seen)
    payload = BODY  # stream не задан → сердцебиения и детекции ухода нет
    req = (b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
           b"Content-Type: application/json\r\nContent-Length: " + str(len(payload)).encode()
           + b"\r\n\r\n" + payload)
    sock = _socket.create_connection(("127.0.0.1", P_VANISH), timeout=RESPONSE_TIMEOUT)
    sock.sendall(req)
    got = sock.recv(4096)          # заголовки и начало тела — прокси уже пишет нам
    # Уходим ГРУБО: RST, а не FIN — так падает агент, которого убили.
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER, _struct.pack("ii", 1, 0))
    sock.close()
    check(got.startswith(b"HTTP/1.1 200"), f"ответ начал приходить (получено {got[:24]!r})")
    check(len(big_seen) == before + 1, "апстрим начал отдавать тело")

    rows = {r.get("route"): r for r in _finished_events((f"r{P_VANISH}",), tries=120)}
    row = rows.get(f"r{P_VANISH}") or {}
    kind = row.get("errorKind")
    check(row != {}, "запрос завершился и попал в журнал")
    # Ушёл КЛИЕНТ — и записан клиент. Провал записи ему отмечается в
    # _client_write там, где наблюдается, тем же путём, что и сердцебиение.
    check(kind == "client_disconnected",
          f"уход клиента записан на клиента (получено {kind!r})")
    check(kind != "upstream_disconnected", "и НЕ свален на апстрим")
    check("client disconnected" in str(row.get("error") or ""),
          f"и текст называет клиента (получено {str(row.get('error'))[:60]!r})")


def test_client_vanishes_before_first_byte():
    """Клиент уходит ДО первого байта ответа — самый частый случай в бою.

    Убитый агент обычно умирает, пока ячейка ещё
    считает, то есть раньше заголовков. Тогда первое, что прокси пишет
    исчезнувшему клиенту, — ЗАГОЛОВКИ через send_response/end_headers, а не
    тело через _client_write. Первая починка помечала провал записи только в
    _client_write и этот путь не видела: живая проверка на проде показала
    upstream_disconnected для ушедшего клиента. Теперь и заголовки, и тело идут
    через один _on_client. Медленная ячейка на один слот отвечает через 1.5 с —
    как раз после того, как клиент ушёл.
    """
    print("клиент уходит до первого байта ответа:")
    import socket as _socket
    import struct as _struct
    payload = BODY
    req = (b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
           b"Content-Type: application/json\r\nContent-Length: " + str(len(payload)).encode()
           + b"\r\n\r\n" + payload)
    # Свой порт: медленная ячейка делится с тестом очереди, и по общему порту
    # можно было взять ЕГО старую запись — первая версия так и сделала.
    sock = _socket.create_connection(("127.0.0.1", P_VANISH2), timeout=RESPONSE_TIMEOUT)
    sock.sendall(req)
    time.sleep(0.3)   # запрос дошёл до апстрима; ответа ещё нет — уходим
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER, _struct.pack("ii", 1, 0))
    sock.close()

    rows = {r.get("route"): r for r in _finished_events((f"r{P_VANISH2}",), tries=160)}
    row = rows.get(f"r{P_VANISH2}") or {}
    check(row != {}, "запрос завершился и попал в журнал")
    kind = row.get("errorKind")
    check(kind == "client_disconnected",
          f"уход клиента ДО заголовков записан на клиента (получено {kind!r})")
    check(kind != "upstream_disconnected", "и НЕ свален на апстрим")
    check(int((row.get("item") or {}).get("bytes") or 0) == 0,
          "клиенту не ушло НИ БАЙТА — упала именно запись заголовков")


def test_keepalive_not_sent_to_cloud():
    """Вторая ось условия — НЕ облако. Раньше пинилась только первая.

    Ранние SSE-заголовки и биения — только для потокового запроса И только к
    локальной ячейке. Ревью показало: замена `and not route_is_cloud` на
    `or route_is_cloud` оставляла весь снимок зелёным — облачная ось не была
    пришпилена. Не-потоковый запрос в облако обязан получить свой JSON, а не
    поток с биениями.
    """
    print("сердцебиение: облачный не-потоковый запрос:")
    status, raw, head = post(P_ANTHRO, want_headers=True)
    check(status == 200, f"облачный не-потоковый запрос успешен (получено {status})")
    check(head.get("content-type", "").startswith("application/json"),
          f"и получает JSON, а не ранние потоковые заголовки (получено {head.get('content-type')!r})")
    check("chatcmpl-keepalive" not in raw, "и никаких биений")
    doc = json.loads(raw)
    check(doc.get("object") == "chat.completion",
          f"ответ переведён в форму completions (получено {doc.get('object')!r})")


def test_loading_model_retry_not_for_cloud():
    """Третья ось условия — НЕ облако. Раньше пинились только статус и тело.

    У провайдера 503 со словами «Loading model» значит не то, что у llama.cpp,
    и ретраить его три секунды до дедлайна нельзя. Ревью показало: удаление
    `not is_cloud and` оставляло снимок зелёным (157 ok, 0 FAIL).
    """
    print("ретрай на загрузке: облако:")
    before = len(anthro_seen)
    body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "LOADING503"}]}).encode()
    began = time.time()
    status, raw = post(P_ANTHRO, body=body)
    took = time.time() - began
    check(status == 503, f"облачный 503 доходит как есть (получено {status})")
    check("Loading model" in raw, f"с телом провайдера (получено {raw[:60]!r})")
    check(len(anthro_seen) == before + 1,
          f"облако опрошено ровно раз — ретрая нет (получено {len(anthro_seen) - before})")
    check(took < 2.0, f"и без пауз ретрая (прошло {took:.1f} с)")


def _finished_events(expect_routes=(), tries=40):
    """Записи finished из журнала событий — то, что читает доска.

    Журнал пишется после того, как ответ уже ушёл клиенту, поэтому читать его
    сразу после запроса — гонка: первая версия этой проверки падала на `None`,
    и это была ошибка проверки, а не кода. Ждём появления нужных маршрутов.
    """
    for _ in range(tries):
        rows = _read_finished()
        seen = {r.get("route") for r in rows}
        if all(name in seen for name in expect_routes):
            return rows
        time.sleep(0.05)
    return _read_finished()


def _read_finished():
    rows = []
    for path in sorted(Path(os.environ["AGENT_PROXY_LOG_DIR"]).glob("*")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("event") == "finished":
                rows.append(row)
    return rows


def test_error_kind_reaching_the_client():
    """ЗАФИКСИРОВАНО КАК ЕСТЬ, НЕ КАК ХОРОШО.

    На одном порту живут две формы конверта ошибки: блокировка отдаёт
    {error, kind}, а провал пересылки — только строку, хотя вид ошибки
    вычислен на строку выше и выброшен. И для разрыва со стороны АПСТРИМА
    этот вид получается неверным.
    """
    print("вид ошибки, доходящий до клиента:")
    status, raw = post(P_PAUSED)
    check("kind" in json.loads(raw), "у блокировки вид ошибки ЕСТЬ")

    status, raw = post(P_DEAD)
    doc = json.loads(raw)
    check(doc.get("kind") == "proxy_error",
          f"у провала пересылки вид ошибки ТОЖЕ есть (получено {doc.get('kind')!r})")

    status, raw = post(P_RUDE)
    doc = json.loads(raw)
    check(status == 502, f"апстрим разорвал соединение: 502 (получено {status})")
    # Один и тот же сценарий даёт РАЗНЫЕ тексты в зависимости от того, где именно
    # оборвалось соединение: "Connection reset by peer", "Remote end closed
    # connection without response", а под нагрузкой ещё и "Broken pipe" — на
    # загруженной машине последний выпадает почти в половине попыток, и полный
    # прогон краснел четыре раза из восьми. На простое его не видно вовсе,
    # поэтому шесть моих проверок подряд ничего не показали: замер был верен, а
    # условия — нет.
    # Отсюда и пин: строго ВИД ошибки (он одинаков во всех трёх случаях), а текст
    # только на непустоту. Ровно то, что сказано выше в этом же файле — по тексту
    # клиент ветвиться не может.
    text = str(doc.get("error") or "")
    check(text.strip() != "", f"слова апстрима не потеряны (получено {text!r})")
    check(doc.get("kind") == "upstream_disconnected",
          f"а ветвиться клиенту есть по чему — вид ошибки устойчив (получено {doc.get('kind')!r})")
    check(doc.get("kind") == "upstream_disconnected",
          f"и вина не переложена на клиента (получено {doc.get('kind')!r})")
    check(doc.get("kind") != "client_disconnected", "клиент здесь ни при чём")


def test_error_kind_in_the_journal():
    """Вид ошибки, который читает доска. Здесь он уже НЕВЕРЕН."""
    print("вид ошибки в журнале событий:")
    by_route = {}
    for row in _finished_events((f"r{P_DEAD}", f"r{P_RUDE}")):
        by_route[row.get("route")] = row
    dead = by_route.get(f"r{P_DEAD}") or {}
    rude = by_route.get(f"r{P_RUDE}") or {}
    check(dead.get("errorKind") == "proxy_error",
          f"неслушающий апстрим: proxy_error (получено {dead.get('errorKind')!r})")
    # Разорвал АПСТРИМ, а записано, что ушёл КЛИЕНТ. На доске это даёт заголовок
    # "client disconnected", причину "client closed connection while proxy was
    # still streaming" и здоровье degraded вместо failed.
    check(rude.get("errorKind") == "upstream_disconnected",
          f"разрыв со стороны апстрима записан на апстрим (получено {rude.get('errorKind')!r})")
    check(rude.get("errorKind") != "client_disconnected",
          "и доска больше не скажет оператору, что ушёл его агент")


for fn in (test_blocked_modes, test_unrouted, test_api_key,
           test_forward, test_upstream_errors, test_upstream_down,
           test_error_kind_reaching_the_client, test_error_kind_in_the_journal,
           test_classifier_both_sides, test_response_headers,
           test_streaming_relay, test_streaming_journal, test_anthropic_translation,
           test_subscription_translation, test_responses_passthrough, test_loading_model_retry,
           test_loading_model_journal, test_queue_waits_for_a_free_slot,
           test_queue_visible_in_journal, test_keepalive_holds_a_queued_client,
           test_keepalive_not_sent_without_streaming,
           test_rescue_replays_on_a_backup_exit, test_rescue_visible_in_journal,
           test_error_inside_an_open_stream, test_client_vanishes_mid_response,
           test_client_vanishes_before_first_byte, test_keepalive_not_sent_to_cloud,
           test_loading_model_retry_not_for_cloud):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all proxy-forward snapshots hold")
