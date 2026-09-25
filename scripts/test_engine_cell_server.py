#!/usr/bin/env python3
"""Снимок cells/engine_cell_server.py — ячейка, чья модель живёт в Ollama или LM Studio.

Движок слушает только 127.0.0.1, и ячейка — единственный вход к нему (решение
оператора, 2026-09-25). Пинится ЗНАЧЕНИЯМИ, против поддельных движков на
loopback, без настоящих Ollama и LM Studio:

  * старт ждёт движок, проверяет модель и загружает её — нужными вызовами
    каждого движка; каждый отказ назван словами, а не «ошибкой»;
  * здоровье: пока движок держит модель — ok; выгрузили в обход ячейки или
    движок лёг — ошибка с причиной, не «ok» над пустым движком;
  * вход: модель в запросе подставляется ячейкой, /v1/models знает только её,
    поток ответа идёт насквозь, а не копится;
  * Ollama после запроса по OpenAI-пути снова держит модель (иначе через пять
    минут она выгрузилась бы сама из-под работающей ячейки);
  * стоп выгружает модель.

Время и сон подставные: снимок не ждёт настоящих 90 секунд.

Запуск: python3 scripts/test_engine_cell_server.py
"""
import http.client
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cells"))
import engine_cell_server as ecs  # noqa: E402
from cell_base import _Server  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Fake:
    """A pretend engine: what it holds, what it was asked, how it answers."""

    def __init__(self, kind, models, embed=()):
        self.kind = kind
        self.models = list(models)
        self.embed = set(embed)
        self.loaded = set()
        self.calls = []
        self.refuse_load = ""
        self.first_chunk_read = threading.Event()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def reply(self, code, body):
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    return json.loads(raw or b"null")
                except ValueError:
                    return raw.decode("utf-8", "replace")

            def do_GET(self):
                fake.calls.append(("GET", self.path, None))
                if fake.kind == "ollama":
                    if self.path == "/api/version":
                        return self.reply(200, {"version": "0.34.4"})
                    if self.path == "/api/tags":
                        return self.reply(200, {"models": [{"name": m} for m in fake.models]})
                    if self.path == "/api/ps":
                        return self.reply(200, {"models": [{"name": m} for m in sorted(fake.loaded)]})
                else:
                    if self.path == "/api/v1/models":
                        return self.reply(200, {"models": [
                            {"key": m, "type": "embedding" if m in fake.embed else "llm",
                             "loaded_instances": [{"id": f"{m}:1"}] if m in fake.loaded else []}
                            for m in fake.models]})
                self.reply(404, {"error": "no such path"})

            def do_POST(self):
                body = self.body()
                fake.calls.append(("POST", self.path, body))
                if self.path == "/v1/chat/completions" and isinstance(body, dict) and body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for i, part in enumerate((b"data: one\n\n", b"data: two\n\n", b"data: [DONE]\n\n")):
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
                        self.wfile.flush()
                        if i == 0:
                            # the rest waits until the caller has READ the first
                            # piece: a proxy that buffered the whole reply would
                            # never deliver it, and this waits out the timeout
                            fake.first_chunk_read.wait(5)
                    self.wfile.write(b"0\r\n\r\n")
                    return
                if self.path == "/v1/chat/completions":
                    return self.reply(200, {"model": body.get("model") if isinstance(body, dict) else None,
                                            "echo": body})
                if fake.kind == "ollama":
                    if self.path == "/api/show":
                        caps = ["embedding"] if body.get("model") in fake.embed else ["completion"]
                        return self.reply(200, {"capabilities": caps})
                    if self.path in ("/api/generate", "/api/embed"):
                        if fake.refuse_load and body.get("keep_alive") == -1 and body.get("model") not in fake.loaded:
                            return self.reply(500, {"error": fake.refuse_load})
                        if self.path == "/api/generate" and body.get("model") in fake.embed:
                            return self.reply(400, {"error": "does not support generate"})
                        if body.get("keep_alive") == 0:
                            fake.loaded.discard(body.get("model"))
                        else:
                            fake.loaded.add(body.get("model"))
                        return self.reply(200, {"done": True})
                else:
                    if self.path == "/api/v1/models/load":
                        if fake.refuse_load:
                            return self.reply(500, {"error": {"message": fake.refuse_load}})
                        fake.loaded.add(body.get("model"))
                        return self.reply(200, {"instance_id": body.get("model") + ":1"})
                    if self.path == "/api/v1/models/unload":
                        fake.loaded.discard(str(body.get("instance_id") or "").rsplit(":", 1)[0])
                        return self.reply(200, {})
                self.reply(404, {"error": "no such path"})

        return H


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def cell(engine, port, model, clock=None):
    clock = clock or Clock()
    return ecs.EngineCell([str(0), engine, str(port), model], clock=clock, sleep=clock.sleep), clock


def calls(fake, since=0):
    return [(m, p) for m, p, _ in fake.calls[since:]]


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ── Ollama: start ────────────────────────────────────────────────────────
print("Ollama — старт:")
oll = Fake("ollama", ["qwen2.5:0.5b", "gemma3:270m", "nomic-embed-text"], embed=["nomic-embed-text"])
c, clk = cell("ollama", oll.port, "qwen2.5:0.5b")
c.load()
check(calls(oll) == [("GET", "/api/version"), ("GET", "/api/tags"), ("POST", "/api/show"), ("POST", "/api/generate")],
      "жив ли движок → есть ли модель → что она делает → загрузка /api/generate")
check(oll.calls[-1][2] == {"model": "qwen2.5:0.5b", "keep_alive": -1},
      "загрузка держит модель до выгрузки: keep_alive -1, без запроса-подсказки")
check(c.kinds == ["llm"] and c.engine == "ollama" and c.model_name == "qwen2.5:0.5b",
      "ячейка говорит о себе: движок ollama, её модель, работа llm")
e, _ = cell("ollama", oll.port, "nomic-embed-text")
e.load()
check(e.kinds == ["embed"] and oll.calls[-1][1] == "/api/embed" and oll.calls[-1][2].get("keep_alive") == -1,
      "модель векторов: работа embed, загрузка через /api/embed (generate она не умеет) с тем же keep_alive")

missing, _ = cell("ollama", oll.port, "llama3:8b")
try:
    missing.load()
    got = ""
except RuntimeError as exc:
    got = str(exc)
check(got == "Ollama has no model llama3:8b", "negative: модели нет в движке — так и сказано")

oll.refuse_load = "model requires more system memory (8.0 GiB) than is available (3.1 GiB)"
refused, _ = cell("ollama", oll.port, "gemma3:270m")
try:
    refused.load()
    got = ""
except RuntimeError as exc:
    got = str(exc)
check(got == oll.refuse_load, "negative: движок отказал в загрузке — причина его же словами")
oll.refuse_load = ""

dead_port = free_port()
down, dclk = cell("ollama", dead_port, "qwen2.5:0.5b")
t0 = dclk()
try:
    down.load()
    got = ""
except RuntimeError as exc:
    got = str(exc)
check(got == f"Ollama on 127.0.0.1:{dead_port} is not answering" and dclk() - t0 >= down.ENGINE_WAIT,
      "negative: движок не отвечает — ждём ENGINE_WAIT (машина могла поднимать его одновременно), потом называем")
check(down.ENGINE_WAIT == 90, "ожидание движка на старте — 90 с")

try:
    ecs.EngineCell(["0", "vllm", "1", "m"])
    unknown = ""
except SystemExit as exc:
    unknown = str(exc)
check(unknown.startswith("unknown engine 'vllm'"), "negative: неизвестный движок — отказ сразу, с перечнем знакомых")
try:
    ecs.EngineCell(["0", "ollama", "1", ""])
    nomodel = ""
except SystemExit as exc:
    nomodel = str(exc)
check(nomodel == "no model named: the cell has nothing to serve", "negative: модель не названа — отказ сразу")

# ── health ───────────────────────────────────────────────────────────────
print("здоровье:")
c.state["ready"] = True
c.state["phase"] = "ok"
code, payload = c.health()
check(code == 200 and payload["status"] == "ok" and payload["engine"] == "ollama" and payload["kinds"] == ["llm"],
      "модель держится — 200 ok с движком и работой")
oll.loaded.discard("qwen2.5:0.5b")
code2, _ = c.health()
check(code2 == 200, "между опросами движок не дёргается: ответ живёт CHECK_EVERY секунд")
clk.sleep(c.CHECK_EVERY)
code3, payload3 = c.health()
check(code3 == 500 and payload3["status"] == "error"
      and payload3["error"] == "qwen2.5:0.5b is no longer loaded in Ollama",
      "negative: модель выгрузили в обход ячейки — ошибка с причиной, а не ok над пустым движком")
oll.loaded.add("qwen2.5:0.5b")
clk.sleep(c.CHECK_EVERY)
check(c.health()[0] == 200, "модель снова в движке — снова ok")
check(c.CHECK_EVERY == 5, "движок спрашивается не чаще раза в 5 с")

# ── the way in: a real listener in front of the fake ─────────────────────
print("вход:")
srv = _Server(("127.0.0.1", 0), c.handler_class())
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]


def post(path, body, ctype="application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    conn.request("POST", path, body=data, headers={"Content-Type": ctype})
    resp = conn.getresponse()
    out = resp.read()
    conn.close()
    return resp.status, out, dict(resp.getheaders())


def get(path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    out = resp.read()
    conn.close()
    return resp.status, out


before = len(oll.calls)
st, out, hdrs = post("/v1/chat/completions", {"model": "whatever-the-caller-thinks", "messages": [{"role": "user", "content": "hi"}]})
seen = next(b for m, p, b in oll.calls[before:] if p == "/v1/chat/completions")
check(st == 200 and seen["model"] == "qwen2.5:0.5b" and seen["messages"] == [{"role": "user", "content": "hi"}],
      "запрос дошёл до движка с моделью ячейки, остальное как было: вызывающему не нужно знать имя модели")
deadline = time.time() + 3
while time.time() < deadline and not any(p == "/api/generate" and b.get("keep_alive") == -1
                                         for m, p, b in oll.calls[before:] if isinstance(b, dict)):
    time.sleep(0.02)
check(any(p == "/api/generate" and b.get("keep_alive") == -1 for m, p, b in oll.calls[before:] if isinstance(b, dict)),
      "после запроса по OpenAI-пути Ollama снова держит модель: keep_alive -1 (иначе через 5 минут выгрузит сама)")

st, raw, _ = post("/v1/chat/completions", b"not json at all", ctype="text/plain")
seen = next(b for m, p, b in reversed(oll.calls) if p == "/v1/chat/completions")
check(seen == "not json at all", "не-JSON тело уходит как есть — подставлять модель некуда")

st, out = get("/v1/models")
check(st == 200 and json.loads(out)["data"] == [{"id": "qwen2.5:0.5b", "object": "model", "owned_by": "ollama"}],
      "/v1/models через ячейку — только её модель: другую через этот вход не достать")
st, out = get("/api/tags")
check(st == 200 and "gemma3:270m" in out.decode(), "прочие GET — движку как есть (его собственный ответ)")
st, out = get("/health")
check(st == 200 and json.loads(out)["status"] == "ok", "/health отвечает сама ячейка")

# streaming: the first piece must arrive before the engine sends the rest
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
conn.request("POST", "/v1/chat/completions", body=json.dumps({"model": "x", "stream": True}).encode(),
             headers={"Content-Type": "application/json"})
resp = conn.getresponse()
first = resp.read1(65536)
oll.first_chunk_read.set()
t_first = time.time()
rest = resp.read()
conn.close()
stream = first + rest
check(first == b"data: one\n\n",
      "поток идёт насквозь: первый кусок у вызывающего ровно один — до того, как движок прислал остальное "
      "(копящий прокси отдал бы всё разом, после паузы движка)")
check(stream == b"data: one\n\ndata: two\n\ndata: [DONE]\n\n", "поток целиком, по порядку, без обёртки chunked")
check(resp.getheader("Content-Length") is None and resp.getheader("Content-Type") == "text/event-stream",
      "у потока нет длины (конец — закрытие соединения), тип ответа движка сохранён")

c.state["ready"] = False
c.state["phase"] = "loading"
st, raw, _ = post("/v1/chat/completions", {"messages": []})
check(st == 503 and json.loads(raw)["error"] == "loading qwen2.5:0.5b into Ollama",
      "пока модель грузится — 503 со словами, запрос не уходит")
c.state["phase"] = "waiting"
code_w, payload_w = c.health()
st, raw, _ = post("/v1/chat/completions", {"messages": []})
check(code_w == 503 and payload_w["detail"] == f"waiting for Ollama on 127.0.0.1:{oll.port} to answer"
      and json.loads(raw)["error"] == payload_w["detail"],
      "пока ждёт движок — /health и отказ говорят, чего ждут (detail), а не голое «waiting»")
c.state["phase"] = "ok"
c.state["ready"] = True
srv.shutdown()
srv.server_close()

# ── stop ─────────────────────────────────────────────────────────────────
print("стоп:")
before = len(oll.calls)
reason = c.stop()
check(reason == "" and oll.calls[before:] == [("POST", "/api/generate", {"model": "qwen2.5:0.5b", "keep_alive": 0})]
      and "qwen2.5:0.5b" not in oll.loaded, "стоп выгружает модель: keep_alive 0")
oll.stop()

# ── LM Studio ────────────────────────────────────────────────────────────
print("LM Studio:")
lms = Fake("lmstudio", ["qwen/qwen3-0.6b", "text-embedding-nomic-embed-text-v1.5"],
           embed=["text-embedding-nomic-embed-text-v1.5"])
l, lclk = cell("lmstudio", lms.port, "qwen/qwen3-0.6b")
l.load()
check(calls(lms) == [("GET", "/api/v1/models"), ("GET", "/api/v1/models"), ("GET", "/api/v1/models"),
                     ("POST", "/api/v1/models/load")],
      "LM Studio: список моделей (жив? есть ли? что делает?) → REST-загрузка")
check(lms.calls[-1][2] == {"model": "qwen/qwen3-0.6b"}, "REST-загрузка без срока — держит до выгрузки")
emb, _ = cell("lmstudio", lms.port, "text-embedding-nomic-embed-text-v1.5")
emb.load()
check(emb.kinds == ["embed"], "модель векторов LM Studio — работа embed")
l.state["ready"] = True
check(l.health()[0] == 200, "LM Studio держит модель — ok")
lms.loaded.discard("qwen/qwen3-0.6b")
lclk.sleep(l.CHECK_EVERY)
code, payload = l.health()
check(code == 500 and payload["error"] == "qwen/qwen3-0.6b is no longer loaded in LM Studio",
      "negative: выгрузили в обход — ошибка с причиной")
lms.loaded.add("qwen/qwen3-0.6b")
before = len(lms.calls)
check(l.stop() == "" and ("POST", "/api/v1/models/unload", {"instance_id": "qwen/qwen3-0.6b:1"}) in lms.calls[before:]
      and "qwen/qwen3-0.6b" not in lms.loaded, "стоп выгружает каждый экземпляр модели по id, который даёт движок")
lms.refuse_load = "Insufficient system resources"
r2, _ = cell("lmstudio", lms.port, "qwen/qwen3-0.6b")
try:
    r2.load()
    got = ""
except RuntimeError as exc:
    got = str(exc)
check(got == "Insufficient system resources", "negative: отказ LM Studio — его словами (error.message)")
lms.stop()
check(ecs.LmStudio(1).hold("m") == "", "LM Studio держит модель без подсказок: REST-загрузка не знает срока")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m_ in _fail:
        print("  - " + m_)
    sys.exit(1)
print("engine cell OK: старт, здоровье, вход с подменой модели, поток насквозь, стоп — против поддельных движков")
