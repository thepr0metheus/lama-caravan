#!/usr/bin/env python3
"""Value snapshot: what a port answers on `GET /v1/models`, through the operator's eyes.

A client reads the model's name and window size from there — and lives with
what it read. When its numbers disagree with the board, there's one
question: "what does the port ACTUALLY report?". What's pinned is the parsed
response (which window names were found, which one a client would actually
read, nested facts about the running server) and that an error also comes
back as an answer, not as an empty field: "the port didn't answer" is
information about the route.

The CONTROLLER does the asking with the route key; it never appears in the response.

Run: python3 scripts/test_model_card.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-card-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
os.environ["LLAMA_TOPOLOGY_SERVER_IP"] = "127.0.0.1"
sys.path.insert(0, str(ROOT))

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


PORT_OK = free_port()
PORT_KEYED = free_port()
PORT_BAD = free_port()      # answers 503
PORT_DEAD = free_port()     # nothing listens
PORT_TEXT = free_port()     # answers something that is not JSON

BODY = {"object": "list", "data": [{
    "id": "muse-glimmer-30b", "object": "model", "created": 111, "owned_by": "llamacpp",
    "aliases": ["muse"],
    "context_length": 128000, "max_model_len": 128000,
    "meta": {"n_ctx": 60160, "n_ctx_train": 131072},
}]}
seen_auth = []


def _server(port, handler):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _Ok(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        seen_auth.append(self.headers.get("Authorization") or "")
        body = json.dumps(BODY).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Bad(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"error": {"message": "proxy route is not routed", "type": "unrouted"}}).encode()
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Text(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = b"not json at all"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_server(PORT_OK, _Ok)
_server(PORT_KEYED, _Ok)
_server(PORT_BAD, _Bad)
_server(PORT_TEXT, _Text)

Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps({"routes": [
    {"port": PORT_OK, "label": "open route", "enabled": True,
     "upstreamHost": "127.0.0.1", "upstreamPort": 1},
    {"port": PORT_KEYED, "label": "keyed route", "enabled": True, "apiKey": "s3cret",
     "upstreamHost": "127.0.0.1", "upstreamPort": 1},
    {"port": PORT_BAD, "label": "unrouted", "enabled": True,
     "upstreamHost": "127.0.0.1", "upstreamPort": 1},
    {"port": PORT_DEAD, "label": "dead", "enabled": True,
     "upstreamHost": "127.0.0.1", "upstreamPort": 1},
    {"port": PORT_TEXT, "label": "chatty", "enabled": True,
     "upstreamHost": "127.0.0.1", "upstreamPort": 1},
]}), encoding="utf-8")

from caravan.admin.model_card import proxy_model_card  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402


def test_parsed_answer():
    print("разобранный ответ порта:")
    card = proxy_model_card(PORT_OK)
    entry = (card.get("entries") or [{}])[0]
    check(card["ok"] and card["status"] == 200, f"порт ответил 200 (got {card['status']} {card.get('error')!r})")
    check(card["url"] == f"http://127.0.0.1:{PORT_OK}/v1/models",
          f"адрес назван целиком — по нему клиент и ходит (got {card['url']})")
    check(card["label"] == "open route", "подпись маршрута рядом с адресом")
    check(entry["id"] == "muse-glimmer-30b", f"id — то самое имя, которое ищет клиент (got {entry['id']!r})")
    check(entry["windows"] == {"context_length": 128000, "max_model_len": 128000},
          f"перечислены ВСЕ имена окна, найденные в записи (got {entry['windows']})")
    check(entry["window"] == 128000, "и то, что прочитает клиент — первое из известных ему имён")
    check(entry["servedWindow"] == 60160,
          f"вложенное meta.n_ctx показано ОТДЕЛЬНО: сервер запущен с 60160, а объявлено 128000 (got {entry['servedWindow']})")
    check(entry["trainedWindow"] == 131072, "обученное окно — рядом, как факт о модели")
    check(entry["ownedBy"] == "llamacpp" and entry["aliases"] == ["muse"], "владелец и псевдонимы сохранены")
    check(card["raw"].startswith("{") and "muse-glimmer-30b" in card["raw"],
          "сырое тело возвращается как есть — разбору доверяют, но проверить можно")
    check("apiKey" not in json.dumps(card) and "s3cret" not in json.dumps(card),
          "ключа маршрута в ответе нет")
    check(card["keyed"] is False, "открытый порт помечен как беcключевой")

    keyed = proxy_model_card(PORT_KEYED)
    check(keyed["keyed"] is True and "s3cret" not in json.dumps(keyed),
          "порт с ключом помечен — но сам ключ не отдан: ссылка в интерфейсе предупредит про 401")

    seen_auth.clear()
    proxy_model_card(PORT_KEYED)
    check(seen_auth and seen_auth[-1] == "Bearer s3cret",
          f"порт с ключом спрашивается С ключом — иначе он ответит 401 самому себе (got {seen_auth[-1]!r})")


def test_failures_are_answers():
    print("отказ — тоже ответ:")
    card = proxy_model_card(PORT_BAD)
    check(card["ok"] is False and card["status"] == 503 and "503" in card["error"],
          f"503 от порта: ok=false, статус и текст на месте (got {card['status']} {card['error']!r})")
    check("unrouted" in card["raw"], "и тело с причиной — оператору читать именно его")
    check(card["entries"] == [], "записей нет — пустой список, а не выдуманная модель")

    card = proxy_model_card(PORT_DEAD)
    check(card["ok"] is False and card["status"] == 0 and card["error"],
          f"мёртвый порт: статуса нет, ошибка названа (got {card['status']} {card['error']!r})")

    card = proxy_model_card(PORT_TEXT)
    check(card["ok"] is False and card["status"] == 200 and "JSON" in card["error"],
          f"ответ не JSON: статус 200, но разбора нет — и это сказано (got {card['error']!r})")
    check(card["raw"] == "not json at all", "сырое тело всё равно показано")

    for bad, why in ((0, "ноль"), ("", "пусто"), ("abc", "не число")):
        try:
            proxy_model_card(bad)
            check(False, f"{why} — должен быть отказ")
        except AppError as exc:
            check(exc.status == 400, f"{why} — отказ 400 (got {exc.status})")
    try:
        proxy_model_card(PORT_OK + 40000)
        check(False, "порт без маршрута — должен быть отказ")
    except AppError as exc:
        check(exc.status == 404, f"порт, которого нет в конфиге — 404 (got {exc.status})")


test_parsed_answer()
test_failures_are_answers()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all model-card snapshots hold")
