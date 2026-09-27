#!/usr/bin/env python3
"""Snapshot of the admin's own questions to a cell (caravan/admin/telemetry.py):
a command cell's health — what the board paints it by — and a llama cell's
modalities from /props — its vision and audio chips.

Pinned by value against a real local server that answers what each pin
sets and writes down what reached it: the states a health answer maps to
(ok, loading, downloading, broken, down) and what they carry, the as-is
arms, the modalities kept and dropped, and a refusal (401/403) said as
what it is.

Run: python3 scripts/test_cell_requests.py
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="cell-requests-"))
sys.path.insert(0, str(ROOT))

from caravan.admin import telemetry  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PORT = 0          # the local cell's port, set when it listens
ANSWERS = {}      # path -> (status, body)
asked = []        # (path, Authorization)


class _Cell(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        asked.append((self.path, self.headers.get("Authorization")))
        status, body = ANSWERS.get(self.path, (404, {"error": "no such path"}))
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def health(path, status, body):
    ANSWERS[path] = (status, body)
    return telemetry.command_cell_health("127.0.0.1", PORT, path)


def main():
    global PORT
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Cell)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    PORT = server.server_address[1]

    print("здоровье командной ячейки — во что превращается ответ:")
    check(health("/health", 200, {"status": "ok"}) == {"status": "ok", "downloadedBytes": 0, "totalBytes": 0,
                                                       "meta": {"status": "ok"}},
          "200 — ok; что ячейка говорит о себе по контракту (cell_health.carry), едет как meta")
    check(health("/h0", 200, {"x": 1}) == {"status": "ok", "downloadedBytes": 0, "totalBytes": 0},
          "negative: ничего из контракта в ответе — meta нет вовсе")
    got = health("/h1", 503, {"status": "loading", "downloadedBytes": 5, "totalBytes": 9})
    check({k: got.get(k) for k in ("status", "downloadedBytes", "totalBytes")}
          == {"status": "loading", "downloadedBytes": 5, "totalBytes": 9},
          "503 с маркером загрузки — loading, с байтами")
    check(health("/h2", 200, {"status": "downloading", "downloadedBytes": 1, "totalBytes": 4})["status"] == "downloading",
          "downloading — так и сказано, даже при 200")
    got = health("/h3", 200, {"status": "error", "error": "CUDA out of memory"})
    check(got["status"] == "broken" and got["error"] == "CUDA out of memory",
          "ячейка отвечает, но сама говорит об ошибке — broken с её диагнозом")
    got = health("/h4", 500, b"")
    check(got["status"] == "broken" and got["error"] == "HTTP 500 on /h4", "5xx без маркера — broken, с кодом и путём")
    check(health("/h5", 404, {"error": "no"})["status"] == "ok",
          "as-is: 404 без маркера — ok (ответил — значит слушает); путь здоровья сверяется при старте, не здесь")
    ANSWERS["/h6"] = (200, {"status": "ok"})
    check(telemetry.command_cell_health("127.0.0.1", PORT, "h6")["status"] == "ok"
          and asked[-1][0] == "/h6", "путь без / — дополняется")
    free = ThreadingHTTPServer(("127.0.0.1", 0), _Cell)
    dead_port = free.server_address[1]
    free.server_close()
    check(telemetry.command_cell_health("127.0.0.1", dead_port, "/health")["status"] == "down",
          "негатив: порт не отвечает — down")

    print("модальности llama-ячейки из /props:")
    ANSWERS["/props"] = (200, {"modalities": {"vision": True, "audio": 0, "video": 1, "telepathy": True}})
    telemetry._remote_modalities_cache.clear()
    check(telemetry.remote_llama_modalities("127.0.0.1", PORT) == {"vision": True, "audio": False, "video": True},
          "зрение, звук, видео — булевыми; чужие ключи отброшены")
    ANSWERS["/props"] = (200, {"modalities": ["vision"]})
    telemetry._remote_modalities_cache.clear()
    check(telemetry.remote_llama_modalities("127.0.0.1", PORT) is None, "негатив: не словарь — None, а не «ничего не умеет»")

    print("отказ ячейки (2026-09-26):")
    got = health("/v1/models", 401, {"error": {"message": "Invalid API Key"}})
    check(got["status"] == "broken" and got["error"] == "the cell refuses the caravan (HTTP 401 on /v1/models)",
          "401 — не ok: ячейка просит ключ, которого у каравана нет (свой --api-key), и доска так и говорит "
          "(раньше 401 читался как «слушает»)")
    check(health("/v1/models", 403, {})["error"] == "the cell refuses the caravan (HTTP 403 on /v1/models)",
          "403 — то же")
    before = len(asked)
    health("/v1/models", 200, {"data": []})
    check([a for _p, a in asked[before:]] == [None], "negative: вопросы контроллера к ячейке идут без ключа")
    server.shutdown()

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("cell requests OK: здоровье, модальности и отказ ячейки — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
