#!/usr/bin/env python3
"""Value snapshot: the entry for keys in a running proxy (caravan/proxy/entry.py).

Real servers on 127.0.0.1: the proxy's listeners as reconcile_listeners opens
them from agent-proxies.json, and two fake upstreams that say which one
answered. Pinned: a key names its route — a closed port's too — and the
request is that route's; no key, a stranger's key and a key two routes share
are refused before anything else; a closed port is not bound; the entry
moves with the config; a stream says nginx must not buffer it.

Run: python3 scripts/test_proxy_entry.py
"""
import http.client
import itertools
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
TMP = Path(tempfile.mkdtemp(prefix="caravan-proxy-entry-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
os.environ["AGENT_PROXY_HOST"] = "127.0.0.1"
sys.path.insert(0, str(ROOT))

from caravan.proxy import listeners  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


from _ports import free_port  # noqa: E402


def make_upstream(name):
    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status, body, ctype="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(200, json.dumps({"object": "list", "data": [{"id": f"model-{name}", "object": "model"}]}).encode())

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if body.get("stream"):
                chunks = b'data: {"choices":[{"delta":{"content":"' + name.encode() + b'"}}]}\n\ndata: [DONE]\n\n'
                self._send(200, chunks, "text/event-stream")
            else:
                self._send(200, json.dumps({"upstream": name}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", free_port()), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


UP_A, UP_B = make_upstream("A"), make_upstream("B")
PORT_A, PORT_B, ENTRY, ENTRY2 = free_port(), free_port(), free_port(), free_port()
KEY_A = "lcv1_" + "a" * 48
KEY_B = "lcv1_" + "b" * 48
KEY_C, KEY_D = "lcv1_" + "c" * 48, "lcv1_" + "d" * 48
PORT_C, PORT_D, PORT_E = free_port(), free_port(), free_port()


def write_config(routes, entry_port, extra_entry=None):
    # An edge names its output as `out:<id>` and the output's own id has no prefix
    # (resolve_graph strips it): with the prefix on both, the graph found nothing and
    # the router fell back to its FIRST output — route A answered for every key.
    # A client of the entry has no upstream of its own: its pool serves it, not the graph.
    outputs = [{"id": f"o{r['port']}", "name": f"up-{r['port']}", "upstreamHost": "127.0.0.1",
                "upstreamPort": r["upstreamPort"]} for r in routes if "upstreamPort" in r]
    edges = [{"id": f"e{r['port']}", "from": f"in:skynet:proxy:{r['port']}", "to": f"out:o{r['port']}"}
             for r in routes if "upstreamPort" in r]
    payload = {"routes": routes, "routers": [{"id": "router:t", "outputs": outputs, "graph": {"nodes": [], "edges": edges}}],
               "entry": {"port": entry_port, **(extra_entry or {})} if entry_port else {}}
    path = Path(os.environ["AGENT_PROXY_CONFIG_FILE"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    stamp = time.time() + len(routes) + (entry_port or 0) % 7   # a new mtime each write: the cache reads by mtime
    os.utime(path, (stamp, stamp))
    listeners.reconcile_listeners()


def route(port, upstream, **extra):
    return {"label": f"agent-{port}", "port": port, "enabled": True, "upstreamHost": "127.0.0.1",
            "upstreamPort": upstream, "routerId": "router:t", **extra}


def ask(port, headers=None, body=None, path="/v1/chat/completions", method="POST"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=12)
    try:
        payload = json.dumps(body if body is not None else {"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        conn.request(method, path, body=payload if method == "POST" else None,
                     headers={"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        raw = response.read()
        return response.status, raw, dict(response.getheaders())
    except OSError as exc:
        return None, str(exc).encode(), {}
    finally:
        conn.close()


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def settles(condition, seconds=3.0):
    """A listener is stopped in the background (shutdown waits for its loop): poll a moment."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def answer_of(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:120].decode("utf-8", "replace")}


def test_entry_serves_by_key():
    print("вход находит маршрут по ключу:")
    write_config([route(PORT_A, UP_A, apiKey=KEY_A), route(PORT_B, UP_B, apiKey=KEY_B, portClosed=True)], ENTRY)
    check(listening(ENTRY), f"вход слушает свой порт {ENTRY}")
    check(listening(PORT_A) and not listening(PORT_B), "порт A открыт, закрытый порт B не слушается")
    status, raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_A}"})
    check((status, answer_of(raw)) == (200, {"upstream": "A"}), f"ключ A — ответ модели маршрута A (got {status} {raw[:80]})")
    status, raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_B}"})
    check((status, answer_of(raw)) == (200, {"upstream": "B"}), "ключ B — маршрут B, хотя его порт закрыт")
    status, raw, _ = ask(ENTRY, {"x-api-key": KEY_B})
    check((status, answer_of(raw)) == (200, {"upstream": "B"}), "ключ в x-api-key — тот же маршрут")
    status, raw, _ = ask(PORT_A, {"Authorization": f"Bearer {KEY_A}"})
    check((status, answer_of(raw)) == (200, {"upstream": "A"}), "старый порт A с тем же ключом работает, как раньше")
    status, raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_A}"}, path="/v1/models", method="GET")
    ids = [m.get("id") for m in answer_of(raw).get("data", [])]
    check(status == 200 and ids == ["model-A"], f"список моделей через вход — список маршрута A (got {status} {ids})")
    status, raw, headers = ask(ENTRY, {"Authorization": f"Bearer {KEY_A}"},
                               body={"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
    check(status == 200 and headers.get("X-Accel-Buffering") == "no" and b"[DONE]" in raw,
          f"поток через вход: nginx DSM просят не копить токены (got {status} {headers.get('X-Accel-Buffering')})")


def test_entry_refuses():
    print("вход отказывает (в форме OpenAI: status, error.message/type/param/code):")
    status, raw, _ = ask(ENTRY)
    error = answer_of(raw).get("error", {})
    check(status == 401 and "didn't provide an API key" in error.get("message", "")
          and (error.get("type"), error.get("param"), error.get("code")) == ("invalid_request_error", None, None),
          f"без ключа — 401 и что нужно (got {status} {error})")
    status, raw, _ = ask(ENTRY, {"Authorization": "Bearer lcv1_nobody"})
    error = answer_of(raw).get("error", {})
    check(status == 401 and error.get("code") == "invalid_api_key" and "provided: …body." in error.get("message", "")
          and "lcv1_nobody" not in error.get("message", ""),
          f"чужой ключ — 401 invalid_api_key, ключ назван четырьмя последними знаками (got {status} {error})")
    status, _raw, _ = ask(ENTRY, {"Authorization": f"Basic {KEY_A}"})
    check(status == 401, "negative: ключ не в Bearer и не в x-api-key — не ключ")
    log_dir = Path(os.environ["AGENT_PROXY_LOG_DIR"])
    lines = "".join(p.read_text(encoding="utf-8") for p in log_dir.rglob("*.jsonl")) if log_dir.exists() else ""
    check('"entry:no-key"' in lines and '"entry:unknown-key"' in lines, "отказы записаны в журнал прокси с причиной")
    write_config([route(PORT_A, UP_A, apiKey=KEY_A), route(PORT_B, UP_B, apiKey=KEY_A)], ENTRY)
    status, raw, headers = ask(ENTRY, {"Authorization": f"Bearer {KEY_A}"})
    error = answer_of(raw).get("error", {})
    check(status == 401 and "more than one consumer" in error.get("message", "") and error.get("code") == "invalid_api_key",
          f"один ключ у двух маршрутов (файл правили руками) — 401, ни один не выбран: 409 клиент OpenAI повторял бы (got {status})")
    check(headers.get("X-Request-Id", "").count("-") == 1, "у отказа есть X-Request-Id — по нему отказ находят в журнале")


def test_refusal_goes_no_further():
    print("отказ дальше не идёт:")
    from caravan.proxy.entry import EntryHandler
    sent = []
    handler = EntryHandler.__new__(EntryHandler)
    handler.client_address = ("127.0.0.1", 1)
    handler._send_bytes = lambda status, body, ctype="application/json", headers=(): sent.append(status)
    handler._entry_route = {"port": PORT_A, "label": "left from an earlier request"}
    handler.path = "/v1/chat/completions"
    handler.headers = {"Authorization": "Bearer lcv1_nobody"}
    check(handler._find_route() is False and sent == [401], "чужой ключ: ответ 401 — и обработка останавливается")
    check(handler.route is None, "negative: маршрут прошлого запроса не остаётся следующему")
    handler.headers = {"x-api-key": KEY_A}
    write_config([route(PORT_A, UP_A, apiKey=KEY_A)], ENTRY)
    check(handler._find_route() is True and handler.route["port"] == PORT_A and sent == [401],
          "свой ключ: маршрут найден, ничего не отправлено раньше времени")


def test_asked_as_a_client():
    print("ссылки карточки клиента: контроллер спрашивает вход ключом клиента (caravan/admin/proxy_entry.py AsConsumer):")
    from caravan.admin.proxy_entry import AsConsumer
    from caravan.common.errors import AppError
    Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({"accounts": [], "pools": [
        {"id": "std", "name": "Standart", "contextLength": 300000, "steps": []}]}), encoding="utf-8")
    hermes = {"label": "Hermes", "port": PORT_C, "kind": "consumer", "apiKey": KEY_C, "pool": "std", "portClosed": True, "enabled": True}
    lonely = {"label": "Bot", "port": PORT_D, "kind": "consumer", "apiKey": KEY_D, "pool": "", "portClosed": True, "enabled": True}
    keyless = {"label": "Keyless", "port": PORT_E, "kind": "consumer", "pool": "std", "portClosed": True, "enabled": True}
    write_config([route(PORT_A, UP_A, apiKey=KEY_A), hermes, lonely, keyless], ENTRY)
    config = json.loads(Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).read_text(encoding="utf-8"))
    asker = AsConsumer(config=config)
    status, kind, body = asker.ask(PORT_C, "/v1/models")
    mine, _raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_C}"}, path="/v1/models", method="GET")
    drop_time = lambda doc: [{k: v for k, v in m.items() if k != "created"} for m in doc.get("data", [])]
    check(status == 200 and "json" in kind and drop_time(answer_of(body)) == drop_time(answer_of(_raw)) == [
          {"id": "Standart", "object": "model", "owned_by": "caravan", "context_length": 300000, "max_model_len": 300000}],
          f"список моделей — тот же, что вход отвечает самому клиенту: его пул под своим именем и окном из «Pool settings» "
          f"(got {status} {body[:160]!r})")
    status, kind, body = asker.ask(str(PORT_C), "/v1/models/Standart")
    check(status == 200 and answer_of(body).get("id") == "Standart", f"одна модель клиента — по её имени (got {status} {body[:100]!r})")
    status, kind, body = asker.ask(PORT_C, "/v1/models/Nope")
    check(status == 404 and answer_of(body).get("error", {}).get("code") == "model_not_found",
          "отказ входа — тоже ответ клиенту: 404 model_not_found передан как есть")
    status, kind, body = asker.ask(PORT_D, "/v1/models/")
    check(status == 200 and answer_of(body).get("data") == [], "у клиента без каната пустой список — так ему и отвечают")
    said = []
    for args, why in (((PORT_C, "/v1/chat/completions"), "вопрос не GET клиента"), ((PORT_C, "/v1"), "сам адрес — не вопрос"),
                      ((PORT_C, "/admin"), "чужой путь"), ((PORT_A, "/v1/models"), "маршрут не клиент входа"),
                      ((free_port(), "/v1/models"), "клиента нет"), (("x", "/v1/models"), "порт не число"),
                      ((PORT_E, "/v1/models"), "клиент без ключа"), ((PORT_C, "/v1/models"), "вход выключен"),
                      ((PORT_C, "/v1/models"), "вход не отвечает")):
        one = asker if why not in ("вход выключен", "вход не отвечает") else AsConsumer(
            config={**config, "entry": {} if why == "вход выключен" else {"port": free_port()}})
        try:
            one.ask(*args)
            said.append((why, None, ""))
        except AppError as err:
            said.append((why, err.status, str(err)))
    check([(why, code) for why, code, _ in said] == [("вопрос не GET клиента", 400), ("сам адрес — не вопрос", 400), ("чужой путь", 400),
          ("маршрут не клиент входа", 404), ("клиента нет", 404), ("порт не число", 400), ("клиент без ключа", 409),
          ("вход выключен", 409), ("вход не отвечает", 502)],
          f"negative: ссылка — не дверь в прокси: только GET клиента; нет клиента, ключа, входа — сказано кодом (got {said})")
    check(not any(KEY_C in text or KEY_D in text for _w, _c, text in said), "ключ клиента не попадает ни в один отказ")
    check([AsConsumer.path_of(p) for p in ("/v1/models", "/v1/models/", "/v1/models/a b", "/v1/models/a/b", "/v1/modelsX", "", None)]
          == ["/v1/models", "/v1/models", "/v1/models/a%20b", "/v1/models/a%2Fb", "", "", ""],
          "имя модели уходит экранированным целиком, как его шлёт клиент; negative: похожий путь — не вопрос")
    check([AsConsumer.shown_as(k) for k in ("application/json", "application/json; charset=utf-8", "text/html", "", None)]
          == ["application/json; charset=utf-8"] * 2 + ["text/plain; charset=utf-8"] * 3,
          "ответ отдаётся JSON-ом или простым текстом — никогда страницей в адресе доски")


def test_show_and_probes():
    print("Ollama's /api/show for Hermes, and a client's tests by POST (AsConsumer.probe):")
    from caravan.admin.proxy_entry import AsConsumer, ClientProbe, ConsumerAddress
    from caravan.common.errors import AppError
    cloud = Path(os.environ["CLOUD_PROVIDERS_FILE"])
    cloud.write_text(json.dumps({"accounts": [], "pools": [
        {"id": "std", "name": "Standart", "contextLength": 300000, "steps": []},
        {"id": "eco", "name": "Econom", "steps": []}]}), encoding="utf-8")
    hermes = {"label": "Hermes", "port": PORT_C, "kind": "consumer", "apiKey": KEY_C, "pool": "std", "portClosed": True, "enabled": True}
    bot = {"label": "Bot", "port": PORT_D, "kind": "consumer", "apiKey": KEY_D, "pool": "eco", "portClosed": True, "enabled": True}
    write_config([route(PORT_A, UP_A, apiKey=KEY_A), hermes, bot], ENTRY)
    status, raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_C}"}, body={"model": "Standart"}, path="/api/show")
    doc = answer_of(raw)
    check(status == 200 and doc.get("model_info") == {"general.architecture": "caravan", "caravan.context_length": 300000}
          and doc.get("parameters") == "num_ctx 300000" and doc.get("details", {}).get("family") == "caravan",
          f"the pool's window in Ollama's shape: under model_info and as num_ctx — the figure /v1/models states (got {status} {doc})")
    status, raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_D}"}, body={"model": "Econom"}, path="/api/show")
    doc = answer_of(raw)
    check(status == 200 and doc.get("model_info") == {"general.architecture": "caravan"} and doc.get("parameters") == "",
          f"negative: a pool that states no window answers without one — not a guess (got {doc})")
    status, raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_C}"}, path="/api/show", method="GET")
    check(status == 404, "negative: Ollama asks it by POST; a GET is a path the entry has not")
    log_dir = Path(os.environ["AGENT_PROXY_LOG_DIR"])
    rows = [json.loads(line) for p in log_dir.rglob("*.jsonl") for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    refused = [r["item"] for r in rows if r.get("event") == "blocked" and (r.get("item") or {}).get("path") == "/api/show"]
    check(refused and refused[-1].get("method") == "GET" and refused[-1].get("port") == PORT_C,
          f"a refusal says its method and the client's port in the journal — the card's errors list reads them (got {refused[-1:]})")

    config = json.loads(Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).read_text(encoding="utf-8"))
    ticks = itertools.cycle([10.0, 10.25])
    asker = AsConsumer(config=config, clock=lambda: next(ticks))
    seen = {}
    for path in AsConsumer.PROBES:
        out = asker.probe(PORT_C, path, "Standart")
        seen[path] = (out["status"], out["request"]["model"], out["ms"], "text" in out)
    check(set(seen) == {"/v1/chat/completions", "/v1/responses", "/v1/audio/transcriptions", "/v1/audio/speech",
                        "/v1/images/generations", "/v1/embeddings"} and all(v[1:] == ("Standart", 250, True) for v in seen.values()),
          f"each of the five kinds of work is sent as the client, naming the model it calls; the time is the probe's own (got {seen})")
    stt = asker.probe(PORT_C, "/v1/audio/transcriptions", "Standart")
    check(stt["status"] == 503 and "`Standart` cannot serve now" in stt["text"] and "probe.wav" in stt["request"]["sent"],
          "a recogniser's file goes as a form, and the entry reads the model from it (1.3.501; it read JSON only and "
          "answered 400): the form reaches its pool — here one with no row, so the pool itself answers")
    chat = asker.probe(PORT_C, "/v1/chat/completions", "Standart")
    check(chat["status"] >= 400 and "error" in json.loads(chat["text"]) and json.loads(chat["request"]["sent"])["messages"][0]["content"] == ClientProbe.PROMPT
          and json.loads(chat["request"]["sent"])["model"] == "Standart" and "model=Standart" in stt["request"]["sent"],
          f"the pool with no row refuses the client in OpenAI's shape, and the test shows that refusal (got {chat['status']} {chat['text'][:80]!r})")
    rows = [json.loads(line) for p in log_dir.rglob("*.jsonl") for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    tested = [r["item"] for r in rows if r.get("event") == "blocked" and (r.get("item") or {}).get("path") == "/v1/images/generations"]
    status, _raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_C}", "X-Caravan-Probe": "x", "X-Forwarded-For": "192.0.2.7"},
                          path="/api/show", method="GET")
    rows = [json.loads(line) for p in log_dir.rglob("*.jsonl") for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    forwarded = [r["item"] for r in rows if r.get("event") == "blocked" and (r.get("item") or {}).get("path") == "/api/show"][-1]
    check(tested and all(t.get("client") == "routing-probe" for t in tested) and forwarded.get("client") not in ("routing-probe", "")
          and status == 404,
          f"Routing's test is journaled as the test — the client's errors list leaves it out; negative: the header from "
          f"behind the DSM's proxy is a client's own request (got {[t.get('client') for t in tested]}, {forwarded.get('client')!r})")
    body, kind, sent = AsConsumer.PROBES["/v1/audio/transcriptions"].request("Standart")
    wav = ClientProbe.silence_wav()
    check(kind == "multipart/form-data; boundary=caravan-probe" and body.startswith(b'--caravan-probe\r\nContent-Disposition: form-data; name="model"\r\n\r\nStandart\r\n')
          and body.endswith(b"--caravan-probe--\r\n") and wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and len(wav) == 44 + 16000,
          "the recogniser's test is a form with half a second of silence, 16 kHz — the same bytes every time")
    refusals = []
    for args in ((PORT_C, "/v1/models"), (PORT_C, "/admin"), (free_port(), "/v1/embeddings")):
        try:
            asker.probe(*args)
            refusals.append(None)
        except AppError as err:
            refusals.append(err.status)
    check(refusals == [400, 400, 404], f"negative: only the five POST questions, and only a client's (got {refusals})")
    probes = AsConsumer.probes()
    check([p["path"] for p in probes] == list(AsConsumer.PROBES) and [p["path"] for p in probes if p["paid"]] == ["/v1/images/generations"]
          and "probes" not in ConsumerAddress(config, "192.0.2.10").entry(),
          "the board is handed the tests from the one table that sends them; only a picture may cost money")


def test_sets_at_the_entry():
    print("a client of a set: its models listed, a request's model picks the pool (OpenAI's way):")
    cloud = Path(os.environ["CLOUD_PROVIDERS_FILE"])
    cloud.write_text(json.dumps({"accounts": [], "pools": [
        {"id": "std", "name": "Standart", "contextLength": 300000, "steps": []},
        {"id": "voice", "name": "Voice", "contextLength": 8000, "steps": []}],
        "sets": [{"id": "chat-voice", "name": "Chat and voice", "pools": ["voice", "std"]}]}), encoding="utf-8")
    hermes = {"label": "Hermes", "port": PORT_C, "kind": "consumer", "apiKey": KEY_C, "set": "chat-voice", "portClosed": True, "enabled": True}
    bot = {"label": "Bot", "port": PORT_D, "kind": "consumer", "apiKey": KEY_D, "set": "", "portClosed": True, "enabled": True}
    write_config([route(PORT_A, UP_A, apiKey=KEY_A), hermes, bot], ENTRY)
    auth = {"Authorization": f"Bearer {KEY_C}"}
    status, raw, _ = ask(ENTRY, auth, path="/v1/models", method="GET")
    listed = [(m["id"], m.get("context_length")) for m in answer_of(raw).get("data", [])]
    check(status == 200 and listed == [("Voice", 8000), ("Standart", 300000)],
          f"/v1/models lists the set's pools in its order, each with its own window (got {status} {listed})")
    status, raw, _ = ask(ENTRY, auth, path="/v1/models/Voice", method="GET")
    check(status == 200 and answer_of(raw).get("id") == "Voice", "one model of the set by its name")
    picked = {}
    for name in ("Standart", "Voice", "standart", None):
        body = {"messages": [{"role": "user", "content": "hi"}], **({"model": name} if name is not None else {})}
        status, raw, _ = ask(ENTRY, auth, body=body)
        picked[str(name)] = (status, answer_of(raw).get("error", {}).get("code"), answer_of(raw).get("error", {}).get("message", "")[:40])
    check(picked["Standart"][0] not in (400, 404) and picked["Voice"][0] not in (400, 404),
          f"a model of the set reaches its pool — the pools have no rows, so the pool itself answers (got {picked})")
    check(picked["standart"][:2] == (404, "model_not_found") and picked["None"][0] == 400
          and picked["None"][2].startswith("you must provide a model"),
          f"negative: a name the set has not — 404 model_not_found; no model — 400, OpenAI's own words (got {picked})")
    status, raw, _ = ask(ENTRY, auth, body={"model": "Voice"}, path="/api/show")
    shown = answer_of(raw)
    status2, _raw2, _ = ask(ENTRY, auth, body={"name": "Nope"}, path="/api/show")
    check(status == 200 and shown.get("model_info", {}).get("caravan.context_length") == 8000 and status2 == 404,
          f"/api/show answers the model the body names, among the set's; negative: one it has not — 404 (got {status} {shown}, {status2})")
    status, raw, _ = ask(ENTRY, {"Authorization": f"Bearer {KEY_D}"}, body={"model": "Standart", "messages": []})
    check(status == 404 and "no model yet" in answer_of(raw).get("error", {}).get("message", ""),
          "negative: a client with no set — no model yet, whatever it names")


def test_entry_follows_the_config():
    print("вход следует за конфигом:")
    write_config([route(PORT_A, UP_A, apiKey=KEY_A)], ENTRY2)
    check(settles(lambda: listening(ENTRY2) and not listening(ENTRY)), f"порт входа сменился: {ENTRY} закрыт, {ENTRY2} слушает")
    check(settles(lambda: not listening(PORT_B)), "маршрут B убран — его порт закрылся")
    write_config([route(PORT_A, UP_A, apiKey=KEY_A), route(PORT_B, UP_B, apiKey=KEY_B)], ENTRY2)
    check(settles(lambda: listening(PORT_B)), "порт B снова слушается, когда флаг снят")
    write_config([route(PORT_A, UP_A, apiKey=KEY_A)], PORT_A)
    check(settles(lambda: not listening(ENTRY2)) and listening(PORT_A),
          "negative: вход на порту маршрута — вход закрыт, маршрут слушает свой порт")
    status, raw, _ = ask(PORT_A, {"Authorization": f"Bearer {KEY_A}"})
    check(status == 200 and answer_of(raw) == {"upstream": "A"}, "на этом порту отвечает маршрут, а не вход")
    write_config([route(PORT_A, UP_A, apiKey=KEY_A)], 0)
    check(listeners.entry_listener.port == 0 and listeners.entry_listener.server is None, "вход выключен — слушателя нет")


for fn in (test_entry_serves_by_key, test_entry_refuses, test_refusal_goes_no_further, test_asked_as_a_client,
           test_show_and_probes, test_sets_at_the_entry, test_entry_follows_the_config):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("proxy entry snapshot holds")
