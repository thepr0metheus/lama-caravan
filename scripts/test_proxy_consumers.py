#!/usr/bin/env python3
"""Value snapshot: a consumer of the entry, served as an OpenAI client is (caravan/proxy/entry.py).

Real servers on 127.0.0.1: the proxy's listeners as reconcile_listeners opens
them, a fake subscription that speaks the Codex backend (A), a fake key
provider that speaks chat completions and names itself in its headers (R),
and a fake cell behind an old agent's port (L). Pinned: a key calls the pools
of the set its consumer is cabled to, the model list is those pools by their
names in the set's order — or empty for a key no cable reaches yet, whose
requests are refused — and a request's `model` picks one of them: a name the
set has not is 404, no name at all is 400; a recording to transcribe comes as a
form, its `model` a field of it, and goes to the cell byte for byte, a
subscription's row passing it by and a pool of subscriptions alone refusing it
400 (1.3.501); a chat's reasoning effort and verbosity reach a subscription the
Responses way and "no thinking" reaches a cell the template's way; the list
says what each model does — OpenRouter's architecture and the caravan's jobs,
an ear's languages and longest recording — a pool's window counts its cell's,
and a request for work the model does not do is refused before it is sent
(1.3.502); a consumer of an older form (one
`pool`, or the `models` it might call) calls its one pool until the controller
rewrites it, and no router ever decides for a consumer; the pool serves with
its own step's model and credential; the
consumer reads one JSON answer when it asked for no stream; every refusal is
in OpenAI's shape, with the caravan's words and nothing of the provider behind
the pool; an old agent's key still finds its port's route.

Only loopback sockets are used. No production quota is contacted.

Run: python3 scripts/test_proxy_consumers.py
"""
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
TMP = Path(tempfile.mkdtemp(prefix="caravan-consumers-"))
for env, filename in (("AGENT_PROXY_CONFIG_FILE", "routes.json"), ("AGENT_PROXY_STATE_FILE", "state.json"),
                      ("CLOUD_PROVIDERS_FILE", "cloud.json"), ("PROVIDER_SECRETS_FILE", "keys.json"),
                      ("MODEL_CATALOG_FILE", "models.json"), ("AGENT_PROXY_LOG_DIR", "logs")):
    os.environ[env] = str(TMP / filename)
os.environ["AGENT_PROXY_HOST"] = "127.0.0.1"
sys.path.insert(0, str(ROOT))

from caravan.proxy import handler, listeners, state  # noqa: E402
from caravan.proxy.pool_steps import PoolSteps  # noqa: E402
from caravan.proxy.subscription_usage import subscription_usage  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


from _ports import free_port  # noqa: E402


class Backend(BaseHTTPRequestHandler):
    """A (Codex backend), R (chat completions) or L (a cell): which one answered is in the answer."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def send(self, status, body, content_type="application/json", extra=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/backend-api/wham/usage":
            now = int(time.time())
            self.send(200, json.dumps({"rate_limit": {
                "primary_window": {"used_percent": self.server.short, "limit_window_seconds": 18000, "reset_at": now + 7200},
                "secondary_window": {"used_percent": 10, "limit_window_seconds": 604800, "reset_at": now + 604800}}}).encode())
            return
        self.send(200, json.dumps({"object": "list", "data": [{"id": f"model-{self.server.name}", "object": "model"}]}).encode())

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        sent = json.loads(raw or b"{}")
        self.server.seen.append((self.path, self.headers.get("Authorization"), sent))
        # The provider names itself, its organisation and its limits: none of it is the consumer's.
        own = (("openai-organization", "org-secret"), ("x-ratelimit-remaining-requests", "7"), ("Set-Cookie", "cf=1"))
        if self.server.fail_once:
            status, self.server.fail_once = self.server.fail_once, 0
            # A 400 is about the request; any other failure may name the account behind it.
            words = b"maximum context length is 8192 tokens" if status == 400 else b"failure at org-secret"
            code = b',"code":"context_length_exceeded"' if status == 400 else b""
            self.send(status, b'{"error":{"message":"' + words + b'"' + code + b'}}', extra=own)
            return
        if self.server.name == "L":
            self.send(200, json.dumps({"upstream": "L"}).encode())
            return
        if self.path.endswith("/chat/completions"):
            if sent.get("stream"):
                chunk = {"id": "c1", "object": "chat.completion.chunk", "model": sent.get("model"),
                         "choices": [{"index": 0, "delta": {"content": "R"}, "finish_reason": None}]}
                self.send(200, b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n", "text/event-stream", own)
                return
            self.send(200, json.dumps({"id": "c1", "object": "chat.completion", "model": sent.get("model"),
                                       "choices": [{"index": 0, "message": {"role": "assistant", "content": "R"},
                                                    "finish_reason": "stop"}],
                                       "usage": {"prompt_tokens": 3, "completion_tokens": 1}}).encode(), extra=own)
            return
        events = [{"type": "response.output_text.delta", "delta": "A"},
                  {"type": "response.output_item.added", "output_index": 1,
                   "item": {"type": "function_call", "call_id": "call_1", "name": "look"}},
                  {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"q":'},
                  {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '"x"}'},
                  {"type": "response.completed", "response": {"status": "completed", "output": [{"type": "function_call"}],
                                                              "usage": {"input_tokens": 3, "output_tokens": 1}}}]
        if self.server.cut:
            events = events[:1]   # the stream ends before its last word
        body = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)
        self.send(200, body, "text/event-stream")


def backend(name):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    server.name, server.short, server.fail_once, server.cut, server.seen = name, 10, 0, False, []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


#: What a robot cell answers a request it refuses, by the robot schema the request names: a word
#: for a code, a number (what llama.cpp puts there), and a "code" that is a sentence naming a secret.
REFUSALS = {
    "other-robot": (422, {"error": {"code": "unsupported_robot_schema", "message": "this cell serves another robot"}}),
    "numeric-code": (400, {"error": {"code": 400, "message": "a number is no code"}}),
    "odd-code": (400, {"error": {"code": "refused: org-secret at 10.0.0.9", "message": "an odd code"}}),
}


class Cell(BaseHTTPRequestHandler):
    """A cell of a machine behind a pool's row: an ear (S) answers a recording, a chat cell (G)
    a chat, a robot policy (P) a chunk of actions. It keeps what came exactly: the path, the
    type, the bytes, the key if any."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def do_GET(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.seen.append((self.path, self.headers.get("Content-Type"), raw, self.headers.get("Authorization")))
        answers = {"S": {"text": "привет"},
                   "P": {"object": "robot.actions", "robot_schema": "gr00t:oxe_droid_relative_eef_relative_joint",
                         "actions": {"gripper_position": [[0.5]] * 40}},
                   "G": {"id": "c2", "object": "chat.completion", "model": "gemma-4-12b-it",
                         "choices": [{"index": 0, "message": {"role": "assistant", "content": "G"}, "finish_reason": "stop"}]}}
        status, answer = 200, answers[self.server.name]
        try:
            asked = json.loads(raw).get("robot_schema")
        except (ValueError, AttributeError):
            asked = None
        if self.server.name == "P" and asked in REFUSALS:
            status, answer = REFUSALS[asked]
        body = json.dumps(answer).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def cell(name):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Cell)
    server.name, server.seen = name, []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


A, R, L = backend("A"), backend("R"), backend("L")
S, G, P = cell("S"), cell("G"), cell("P")
ENTRY, OLD = free_port(), free_port()
C1, C2, C3, C4, C5, C6, C7, C8, C9 = 23101, 23102, 23103, 23104, 23105, 23106, 23107, 23108, 23109
KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_OLD, KEY_6, KEY_7, KEY_8, KEY_9 = ("lcv1_" + c * 48 for c in "123456789a")
SUB = "openai-subscription"


def url(server):
    return f"http://127.0.0.1:{server.server_address[1]}"


def write_cloud(pools, sets):
    (TMP / "cloud.json").write_text(json.dumps({"accounts": [
        {"id": "a", "name": "a", "type": SUB, "accountType": SUB, "baseUrl": url(A), "authMode": "oauth"},
        {"id": "r", "name": "R", "type": "openrouter", "baseUrl": url(R) + "/v1", "authMode": "apiKey"}],
        "pools": pools, "sets": sets}))


def pool(pid, name, account, model, levels=None, **extra):
    return {"id": pid, "name": name, "steps": [{"id": account, "accountId": account, "model": model,
                                                 "switchAt": levels or {}, "stopAt": levels or {}, "enabled": True}], **extra}


def local_row(rid, output):
    return {"id": rid, "kind": "output", "output": output, "enabled": True}


POOLS = [pool("standart", "Standart", "a", "gpt-sol", {"18000": 20}),
         pool("econom", "Econom", "r", "small", contextLength=32768),
         pool("hidden", "Hidden", "r", "small"),
         pool("big", "Big Brain", "r", "small"),
         pool("twin-1", "Twin", "r", "small"),
         pool("twin-2", "twin", "r", "small"),
         # sinapse's ears and chat cell (1.3.501): a pool of one cell each, and a pool whose
         # subscription comes first and its ear second.
         {"id": "ears", "name": "Ears", "steps": [local_row("r1", "srv:31001")]},
         {"id": "gemma", "name": "Gemma", "steps": [local_row("r1", "srv:31002")], "contextAuto": True},
         {"id": "mixed", "name": "Mixed", "steps": [pool("x", "x", "a", "gpt-sol")["steps"][0], local_row("r2", "srv:31001")]},
         # SpiderMonkey's robot policy (GR00T, 2026-10-13): a pool of one robot cell.
         {"id": "arm", "name": "Arm", "steps": [local_row("r1", "srv:31003")]}]
# "Main" names a pool that is gone: the list leaves it out, the order of the rest is the set's.
SETS = [{"id": "main", "name": "Main", "pools": ["econom", "gone", "standart"]},
        {"id": "paid", "name": "Paid", "pools": ["standart"]},
        {"id": "voice", "name": "Voice", "pools": ["ears", "gemma", "mixed", "standart"]},
        {"id": "robot", "name": "Robot", "pools": ["gemma", "arm"]}]


def consumer(port, key, set_id, **extra):
    return {"label": f"consumer {port}", "port": port, "kind": "consumer", "apiKey": key, "portClosed": True,
            "set": set_id, "upstreamType": "cloud", "routerId": "", **extra}


def pool_form(port, key, pool_id):
    """A consumer as a file written by 1.3.486–1.3.496 keeps it: one pool, no set."""
    route = consumer(port, key, "")
    del route["set"]
    return {**route, "pool": pool_id}


def old_form(port, key, models):
    """A consumer as a file written before 1.3.486 keeps it: the pools it might call, no pool of its own."""
    route = consumer(port, key, "")
    del route["set"]
    return {**route, "models": models}


def write_routes(routes):
    old = {"label": "old agent", "port": OLD, "apiKey": KEY_OLD, "routerId": "router:t",
           "upstreamHost": "127.0.0.1", "upstreamPort": L.server_address[1]}
    payload = {"routes": [old, *routes], "entry": {"port": ENTRY},
               "routers": [{"id": "router:t", "outputs": [{"id": "cell", "name": "cell", "upstreamHost": "127.0.0.1",
                                                           "upstreamPort": L.server_address[1]},
                                                          {"id": "srv:31001", "name": "ear", "upstreamType": "llama",
                                                           "upstreamHost": "127.0.0.1", "upstreamPort": S.server_address[1],
                                                           "jobs": ["asr"], "languages": ["ru"], "maxAudioMs": 25000},
                                                          {"id": "srv:31002", "name": "gemma", "upstreamType": "llama",
                                                           "upstreamHost": "127.0.0.1", "upstreamPort": G.server_address[1],
                                                           "jobs": ["llm"], "inputs": ["text", "image"], "contextLength": 60160},
                                                          {"id": "srv:31003", "name": "arm", "upstreamType": "llama",
                                                           "upstreamHost": "127.0.0.1", "upstreamPort": P.server_address[1],
                                                           "jobs": ["robot-policy"]}],
                            "graph": {"nodes": [], "edges": [{"id": "e", "from": f"in:skynet:proxy:{OLD}", "to": "out:cell"}]}}]}
    path = TMP / "routes.json"
    path.write_text(json.dumps(payload))
    stamp = time.time() + len(json.dumps(payload)) % 97   # a new mtime each write: the cache reads by mtime
    os.utime(path, (stamp, stamp))
    listeners.reconcile_listeners()


def reset():
    for server in (A, R, L):
        server.short, server.fail_once, server.cut, server.seen = 10, 0, False, []
    S.seen, G.seen, P.seen = [], [], []
    (TMP / "keys.json").write_text(json.dumps({"a": {"oauth": {"accessToken": "token-a"}}, "r": {"apiKey": "key-r"}}))
    (TMP / "models.json").write_text(json.dumps({"accounts": {i: {"models": [{"id": "gpt-sol"}, {"id": "small"}]} for i in "ar"}}))
    write_cloud(POOLS, SETS)
    write_routes([consumer(C1, KEY_1, "main"), consumer(C2, KEY_2, "paid"),
                  consumer(C3, KEY_3, "paid", mode="paused"), consumer(C4, KEY_4, ""),
                  old_form(C5, KEY_5, ["gone", "big", "econom"]), pool_form(C6, KEY_6, "econom"),
                  consumer(C7, KEY_7, "deleted-set"), consumer(C8, KEY_8, "voice"), consumer(C9, KEY_9, "robot")])
    subscription_usage.clear()
    manager = PoolSteps()
    handler.pool_steps = state.pool_steps = manager
    import caravan.proxy.output_probe as probe
    probe.pool_steps = manager


def ask(key, path="/v1/chat/completions", body=None, method="POST", raw=None, ctype="application/json", extra=None):
    conn = http.client.HTTPConnection("127.0.0.1", ENTRY, timeout=12)
    try:
        payload = raw if raw is not None else json.dumps(body if body is not None else
                                                          {"model": "Econom", "messages": [{"role": "user", "content": "hi"}]}).encode()
        conn.request(method, path, body=payload if method == "POST" else None,
                     headers={"Content-Type": ctype, **({"Authorization": f"Bearer {key}"} if key else {}), **(extra or {})})
        response = conn.getresponse()
        data = response.read()
        return response.status, data, {k.lower(): v for k, v in response.getheaders()}
    finally:
        conn.close()


def as_json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:160].decode("utf-8", "replace")}


def chat(model, stream=None):
    body = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    if stream is not None:
        body["stream"] = stream
    return body


def test_model_list():
    print("список моделей — пулы набора, к которому ведёт канат ключа, по именам:")
    reset()
    status, raw, _ = ask(KEY_1, "/v1/models", method="GET")
    data = as_json(raw)
    check(status == 200 and data.get("object") == "list" and [m["id"] for m in data["data"]] == ["Econom", "Standart"],
          f"ключ видит пулы своего набора в порядке набора, пропавший пул пропущен (got {status} {data})")
    model = data["data"][0]
    check(model["object"] == "model" and model["owned_by"] == "caravan" and isinstance(model["created"], int),
          "у модели форма OpenAI: object, created, owned_by")
    check(model.get("context_length") == 32768 and model.get("max_model_len") == 32768,
          "окно пула — под двумя именами")
    check("context_length" not in data["data"][1] and "max_model_len" not in data["data"][1],
          "negative: у пула без окна окна нет, а не выдумано")
    status, raw, _ = ask(KEY_2, "/v1/models", method="GET")
    check([m["id"] for m in as_json(raw).get("data", [])] == ["Standart"],
          "negative: другой набор — другой список, пулы чужого набора не видны")
    for key, who in ((KEY_4, "ключ без каната"), (KEY_7, "набор удалён")):
        status, raw, _ = ask(key, "/v1/models", method="GET")
        check((status, as_json(raw)) == (200, {"object": "list", "data": []}),
              f"{who} — пустой список, а не все пулы (got {status} {raw[:80]})")
    status, raw, _ = ask(KEY_5, "/v1/models", method="GET")
    check([m["id"] for m in as_json(raw).get("data", [])] == ["Big Brain"],
          "клиент старого вида — первый живой пул его списка, пока контроллер его не перепишет")
    status, raw, _ = ask(KEY_6, "/v1/models", method="GET")
    check([m["id"] for m in as_json(raw).get("data", [])] == ["Econom"],
          "клиент с одним пулом (1.3.486–1.3.496) — этот пул, пока контроллер не даст ему набор")
    for name in ("Econom", "Standart"):
        status, raw, _ = ask(KEY_1, f"/v1/models/{name}", method="GET")
        check(status == 200 and as_json(raw).get("id") == name, f"одна модель набора по имени: {name}")
    status, raw, _ = ask(KEY_5, "/v1/models/Big%20Brain", method="GET")
    check(status == 200 and as_json(raw).get("id") == "Big Brain", "имя с пробелом сравнивается раскодированным")
    for key, name in ((KEY_2, "Econom"), (KEY_1, "Hidden"), (KEY_1, "econom"), (KEY_4, "Econom")):
        status, raw, _ = ask(key, f"/v1/models/{name}", method="GET")
        error = as_json(raw).get("error", {})
        check(status == 404 and error.get("code") == "model_not_found" and name in error.get("message", ""),
              f"negative: {name} — 404 model_not_found (не в наборе ключа, пул вне набора, другой регистр, ключ без каната)")
    status, raw, _ = ask(KEY_3, "/v1/models", method="GET")
    check(status == 503 and "paused" in as_json(raw).get("error", {}).get("message", ""),
          "negative: клиент на паузе — 503")


def test_requests():
    print("model запроса выбирает пул набора ключа, и пул отвечает:")
    reset()
    status, raw, headers = ask(KEY_1, body=chat("Econom"))
    answer = as_json(raw)
    path, auth, sent = R.seen[-1] if R.seen else (None, None, {})
    check(status == 200 and answer["choices"][0]["message"]["content"] == "R",
          f"Econom — ответ провайдера шага (got {status} {answer})")
    check((path, auth, sent.get("model")) == ("/v1/chat/completions", "Bearer key-r", "small"),
          f"провайдеру ушли модель шага и ключ каравана, не ключ клиента (got {path} {auth} {sent.get('model')})")
    check(not {"openai-organization", "x-ratelimit-remaining-requests", "set-cookie"} & set(headers)
          and headers.get("x-request-id", "").count("-") == 1 and headers.get("content-type") == "application/json",
          f"заголовки провайдера клиенту не идут; свой X-Request-Id идёт (got {sorted(headers)})")
    before = len(R.seen)
    status, raw, _ = ask(KEY_1, body=chat("Standart"))
    check(status == 200 and A.seen and A.seen[-1][2].get("model") == "gpt-sol" and len(R.seen) == before,
          f"тот же ключ, model Standart — ответил другой пул набора, подписка (got {status} {raw[:80]})")
    for model, why in (("gpt-sol", "модель шага — не имя модели"), ("Hidden", "пул вне набора"),
                       ("econom", "имя пишется, как в списке"), ("Big Brain", "пул чужого клиента")):
        seen = (len(A.seen), len(R.seen))
        status, raw, _ = ask(KEY_1, body=chat(model))
        error = as_json(raw).get("error", {})
        check(status == 404 and error.get("code") == "model_not_found" and model in error.get("message", "")
              and (len(A.seen), len(R.seen)) == seen,
              f"negative: model {model!r} — 404 model_not_found, до провайдера не дошло: {why} (got {status} {raw[:80]})")
    status, raw, _ = ask(KEY_1, body={"messages": [{"role": "user", "content": "hi"}]})
    error = as_json(raw).get("error", {})
    check(status == 400 and error.get("message") == "you must provide a model parameter" and error.get("param") == "model",
          f"negative: запрос без model — 400, как отвечает OpenAI, а не первый пул набора (got {status} {error})")
    status, raw, headers = ask(KEY_1, body=chat("Econom", stream=True))
    check(status == 200 and headers.get("content-type") == "text/event-stream" and b"[DONE]" in raw
          and headers.get("x-accel-buffering") == "no" and "openai-organization" not in headers,
          "поток идёт как поток, nginx его не копит, заголовков провайдера нет")
    status, raw, headers = ask(KEY_2, body=chat("Standart"))
    answer = as_json(raw)
    message = answer.get("choices", [{}])[0].get("message", {})
    check(status == 200 and headers.get("content-type") == "application/json" and answer.get("object") == "chat.completion",
          f"подписка без stream — один ответ JSON, а не поток (got {status} {headers.get('content-type')})")
    check(message.get("content") == "A" and message.get("tool_calls") == [
        {"id": "call_1", "type": "function", "function": {"name": "look", "arguments": '{"q":"x"}'}}]
          and answer["choices"][0]["finish_reason"] == "tool_calls"
          and answer.get("usage") == {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
          f"в ответе текст, вызов функции с собранными аргументами, причина конца и расход (got {answer})")
    check(A.seen and A.seen[-1][1] == "Bearer token-a" and A.seen[-1][2].get("model") == "gpt-sol",
          "подписке ушли модель шага и вход каравана")
    status, raw, headers = ask(KEY_2, body=chat("Standart", stream=True))
    check(status == 200 and headers.get("content-type", "").startswith("text/event-stream") and b'"content":"A"' in raw,
          "подписка с stream: true — поток кусков chat.completion.chunk")
    status, raw, _ = ask(KEY_5, body=chat("Big Brain"))
    check(status == 200 and R.seen[-1][2].get("model") == "small",
          f"клиент старого вида служит первым живым пулом своего списка (got {status} {raw[:80]})")
    status, raw, _ = ask(KEY_5, body=chat("Econom"))
    check(status == 404 and as_json(raw).get("error", {}).get("code") == "model_not_found",
          f"negative: другой пул его старого списка — 404: клиент старого вида зовёт один пул (got {status} {raw[:80]})")
    status, raw, _ = ask(KEY_6, body=chat("Econom"))
    check(status == 200 and R.seen[-1][2].get("model") == "small",
          f"клиент с одним пулом служит этим пулом (got {status} {raw[:80]})")
    A.cut = True
    status, raw, _ = ask(KEY_2, body=chat("Standart"))
    error = as_json(raw).get("error", {})
    check(status == 502 and error.get("type") == "server_error" and "Standart" in error.get("message", ""),
          f"negative: поток оборвался до конца — 502, а не половина ответа как целый (got {status} {error})")


def test_refusals():
    print("отказы — в форме OpenAI и словами каравана:")
    reset()
    status, raw, _ = ask(KEY_4, body=chat("Econom"))
    error = as_json(raw).get("error", {})
    check(status == 404 and error.get("code") == "model_not_found" and "connect it to a set of models" in error.get("message", ""),
          f"ключ без каната — 404 model_not_found, и сказано, кто даёт модель (got {status} {error})")
    check(not R.seen and not A.seen, "до провайдеров такой запрос не доходит")
    status, raw, _ = ask(KEY_1, raw=b"model=Econom", ctype="application/x-www-form-urlencoded")
    check(status == 400 and "JSON" in as_json(raw).get("error", {}).get("message", ""), "negative: тело не JSON — 400")
    status, raw, _ = ask(KEY_1, "/v1/files")
    check(status == 404 and as_json(raw)["error"]["message"] == "Invalid URL (POST /v1/files)", "путь, которого нет, — 404 Invalid URL")
    status, raw, _ = ask(KEY_1, "/props", method="GET")
    check(status == 404 and "Invalid URL (GET /props)" in as_json(raw)["error"]["message"], "negative: вопрос сервера ячейки — 404")
    status, raw, _ = ask(KEY_3, body=chat("Standart"))
    check(status == 503 and "paused" in as_json(raw)["error"]["message"], "клиент на паузе — 503 до провайдера")
    log_dir = TMP / "logs"
    lines = "".join(p.read_text(encoding="utf-8") for p in log_dir.rglob("*.jsonl")) if log_dir.exists() else ""
    check('"entry:no-pool"' in lines and f'"consumer {C4}"' in lines,
          "отказ записан в журнал под именем клиента и с причиной")


def test_provider_failures():
    print("отказы провайдера — словами каравана:")
    reset()
    R.fail_once = 400
    status, raw, headers = ask(KEY_1, body=chat("Econom"))
    error = as_json(raw).get("error", {})
    check(status == 400 and error.get("message") == "maximum context length is 8192 tokens" and "openai-organization" not in headers,
          f"400 провайдера — о самом запросе: его слова клиенту нужны (got {status} {error})")
    check(error.get("code") is None and b"context_length_exceeded" not in raw,
          f"negative: код провайдера остаётся у провайдера — клиенту идут слова, code null (got {error})")
    R.fail_once = 500
    status, raw, _ = ask(KEY_1, body=chat("Econom"))
    error = as_json(raw).get("error", {})
    check(status == 502 and error.get("message") == "The model `Econom` failed (HTTP 500)." and b"org-secret" not in raw,
          f"500 провайдера — 502 словами каравана, без слов провайдера (got {status} {error})")
    A.short = 90
    status, raw, headers = ask(KEY_2, body=chat("Standart"))
    error = as_json(raw).get("error", {})
    check(status == 429 and error.get("code") == "rate_limit_exceeded" and "Standart" in error.get("message", "")
          and int(headers.get("retry-after", 0)) > 3600 and headers.get("x-should-retry") == "false",
          f"пул на стопе — 429 с Retry-After и x-should-retry: false (got {status} {error} {headers.get('retry-after')})")
    check(b'"steps"' not in raw and b"token-a" not in raw and b'"a"' not in raw,
          "в отказе пула нет его шагов и аккаунтов")


def test_old_agent_still_served():
    print("агент старого вида с ключом своего порта:")
    reset()
    conn = http.client.HTTPConnection("127.0.0.1", ENTRY, timeout=12)
    conn.request("POST", "/v1/chat/completions", body=json.dumps(chat("whatever")),
                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY_OLD}"})
    response = conn.getresponse()
    status, raw = response.status, response.read()
    conn.close()
    check((status, as_json(raw)) == (200, {"upstream": "L"}),
          f"его запрос идёт по Маршрутизации его порта, model не выбирает (got {status} {raw[:80]})")


def test_no_router_for_a_consumer():
    print("клиента не решает роутер, даже если файл его называет (2026-10-12):")
    reset()
    taken = consumer(C2, KEY_2, "paid", routerId="router:k")
    path = TMP / "routes.json"
    payload = json.loads(path.read_text())
    payload["routes"] = [r for r in payload["routes"] if r["port"] != C2] + [taken]
    payload["routers"].append({"id": "router:k", "outputs": [
        {"id": "cb:econom", "name": "Econom", "upstreamType": "cloud", "providerId": "econom"}],
        "graph": {"nodes": [], "edges": [{"id": "k", "from": f"in:skynet:proxy:{C2}", "to": "out:cb:econom"}]}})
    path.write_text(json.dumps(payload))
    stamp = time.time() + 7
    os.utime(path, (stamp, stamp))
    status, raw, headers = ask(KEY_2, body=chat("Standart"))
    answer = as_json(raw)
    check(status == 200 and answer.get("choices", [{}])[0].get("message", {}).get("content") == "A" and not R.seen,
          f"узел Маршрутизации ведёт в Econom, а ответил пул набора клиента, Standart (got {status} {answer})")
    check(headers.get("x-request-id", "").count("-") == 1 and "openai-organization" not in headers,
          "ответ — в форме OpenAI: свой X-Request-Id, заголовков провайдера нет")
    status, raw, _ = ask(KEY_2, body=chat("Econom"))
    check(status == 404 and as_json(raw).get("error", {}).get("code") == "model_not_found" and not R.seen,
          f"negative: Econom, куда ведёт узел, — не модель набора клиента: 404 (got {status} {raw[:80]})")


def form_body(fields, audio, boundary="sinapse-ear"):
    """A recording to transcribe as sinapse sends it: its fields, then the file."""
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode() for n, v in fields]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n".encode() + audio + b"\r\n")
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


AUDIO = b"RIFF" + bytes(range(256)) * 64 + b"\r\n--sinapse\r\n\r\nname=\"model\"\r\n"


def test_speech_forms():
    print("уши через вход (1.3.501): запись формой, model — поле формы, ячейке — те же байты:")
    reset()
    body, ctype = form_body([("model", "Ears"), ("response_format", "verbose_json"), ("timestamp_granularities[]", "word"),
                             ("language", "ru")], AUDIO)
    status, raw, headers = ask(KEY_8, "/v1/audio/transcriptions", raw=body, ctype=ctype)
    check(status == 200 and as_json(raw) == {"text": "привет"} and headers.get("content-type") == "application/json",
          f"форма с model Ears — ответ уха (got {status} {raw[:80]})")
    check(S.seen[-1:] == [("/v1/audio/transcriptions", ctype, body, None)],
          "ячейке ушли тот же путь, тот же тип с границей и те же байты; ключ клиента остался у каравана")
    before = len(A.seen)
    mixed, _ = form_body([("model", "Mixed")], AUDIO)
    status, raw, _ = ask(KEY_8, "/v1/audio/transcriptions", raw=mixed, ctype=ctype)
    check(status == 200 and len(A.seen) == before and S.seen[-1][2] == mixed,
          f"пул, где подписка первая, — запись проходит мимо подписки к уху (got {status} {raw[:80]})")
    status, raw, _ = ask(KEY_8, body=chat("Mixed"))
    check(status == 200 and len(A.seen) == before + 1, "negative: чат того же пула — подписке, как раньше")
    for fields, ctype2, want, why in (
            ([("language", "ru")], ctype, (400, None, "you must provide a model parameter"), "в форме нет model"),
            ([("model", "Hidden")], ctype, (404, "model_not_found", None), "модель не из набора"),
            ([("model", "Ears")], "multipart/form-data", (400, None, None), "граница не названа — форма не читается")):
        seen = len(S.seen)
        status, raw, _ = ask(KEY_8, "/v1/audio/transcriptions", raw=form_body(fields, AUDIO)[0], ctype=ctype2)
        error = as_json(raw).get("error", {})
        check((status, error.get("code")) == want[:2] and (want[2] is None or error.get("message") == want[2])
              and len(S.seen) == seen, f"negative: {why} — {want[0]}, до ячейки не дошло (got {status} {error})")
    status, raw, _ = ask(KEY_8, "/v1/audio/transcriptions", raw=b"model=Ears", ctype="application/x-www-form-urlencoded")
    check(status == 400 and "multipart/form-data" in as_json(raw).get("error", {}).get("message", ""),
          "negative: тело ни JSON, ни форма — 400, и сказано, что вход читает")
    before = len(A.seen)
    status, raw, headers = ask(KEY_8, "/v1/audio/transcriptions", raw=form_body([("model", "Standart")], AUDIO)[0], ctype=ctype)
    error = as_json(raw).get("error", {})
    check(status == 400 and error.get("message", "").startswith("The model `Standart` does not serve POST /v1/audio/transcriptions")
          and "retry-after" not in headers and len(A.seen) == before,
          f"запись модели из одних подписок — 400 о запросе, без ожидания, подписке не ушла (got {status} {error})")


def test_model_kinds():
    print("список говорит, что делает модель, а вход держится этого (1.3.502):")
    reset()
    status, raw, _ = ask(KEY_8, "/v1/models", method="GET")
    listed = {m["id"]: m for m in as_json(raw).get("data", [])}
    check(status == 200 and listed["Ears"].get("architecture") == {"modality": "audio->text", "input_modalities": ["audio"],
                                                                   "output_modalities": ["text"]}
          and listed["Ears"].get("caravan") == {"jobs": ["asr"], "languages": ["ru"], "max_audio_ms": 25000},
          f"ухо — audio->text, работа asr, язык и самая длинная запись (got {listed.get('Ears')})")
    check(listed["Gemma"].get("architecture", {}).get("modality") == "text+image->text"
          and listed["Gemma"].get("context_length") == 60160,
          f"чат ячейки — с картинками по её слову, окно — окно ячейки (got {listed.get('Gemma')})")
    check(listed["Standart"].get("architecture", {}).get("input_modalities") == ["text", "image"]
          and listed["Standart"].get("caravan") == {"jobs": ["llm"]},
          "подписка — чат с картинками")
    check("architecture" not in listed["Mixed"] and "caravan" not in listed["Mixed"],
          "negative: пул из чата и уха — вида в списке нет: обещать нечего")
    seen = len(S.seen)
    status, raw, headers = ask(KEY_8, body=chat("Ears"))
    error = as_json(raw).get("error", {})
    check(status == 400 and error.get("message", "").startswith("The model `Ears` does not serve POST /v1/chat/completions")
          and len(S.seen) == seen and "retry-after" not in headers,
          f"чат к уху — 400 до отправки: ухо не спрашивали (got {status} {error})")
    seen = len(G.seen)
    status, raw, _ = ask(KEY_8, "/v1/audio/transcriptions", raw=form_body([("model", "Gemma")], AUDIO)[0],
                         ctype="multipart/form-data; boundary=sinapse-ear")
    check(status == 400 and len(G.seen) == seen, f"запись к чату — 400, ячейку чата не спрашивали (got {status})")


def test_robot_policy():
    print("политика робота через вход (GR00T, 2026-10-13): свой путь, те же байты, чужая работа — отказ:")
    reset()
    status, raw, _ = ask(KEY_9, "/v1/models", method="GET")
    listed = {m["id"]: m for m in as_json(raw).get("data", [])}
    check(status == 200 and list(listed) == ["Gemma", "Arm"]
          and listed["Arm"].get("architecture") == {"modality": "image+text->actions", "input_modalities": ["image", "text"],
                                                    "output_modalities": ["actions"]}
          and listed["Arm"].get("caravan") == {"jobs": ["robot-policy"]},
          f"робот в списке — image+text->actions, работа robot-policy, рядом зрение набора (got {listed.get('Arm')})")
    body = json.dumps({"model": "Arm", "robot_schema": "gr00t:oxe_droid_relative_eef_relative_joint", "task": "pick",
                       "state": {"gripper_position": [0.1]}, "images": {}}).encode()
    status, raw, headers = ask(KEY_9, "/v1/robot/predict", raw=body)
    check(status == 200 and as_json(raw).get("object") == "robot.actions" and len(as_json(raw)["actions"]["gripper_position"]) == 40,
          f"POST /v1/robot/predict с model Arm — ответ ячейки робота (got {status} {raw[:80]})")
    check(P.seen[-1:] == [("/v1/robot/predict", "application/json", body, None)],
          "ячейке ушли тот же путь и те же байты: model клиента не переписан, ключ клиента остался у каравана")
    for path, model, cell_, why in (("/v1/chat/completions", "Arm", P, "чат к роботу"),
                                    ("/v1/robot/predict", "Gemma", G, "предсказание к чату")):
        seen = len(cell_.seen)
        status, raw, headers = ask(KEY_9, path, body={**chat(model), "robot_schema": "x"})
        error = as_json(raw).get("error", {})
        check(status == 400 and error.get("message", "").startswith(f"The model `{model}` does not serve POST {path}")
              and len(cell_.seen) == seen and "retry-after" not in headers,
              f"negative: {why} — 400 до отправки, ячейку не спрашивали (got {status} {error})")
    status, raw, _ = ask(KEY_8, "/v1/robot/predict", raw=body)
    check(status == 404 and as_json(raw).get("error", {}).get("code") == "model_not_found" and len(P.seen) == 1,
          "negative: ключ другого набора — 404 model_not_found, робота не спрашивали")
    for schema, want, why in (
            ("other-robot", (422, "unsupported_robot_schema", "this cell serves another robot"),
             "отказ ячейки — слова и код идут клиенту, и он ветвится по коду, как по коду OpenAI"),
            ("numeric-code", (400, None, "a number is no code"), "negative: код числом, как у llama.cpp, — слова идут, code null"),
            ("odd-code", (400, None, "an odd code"), "negative: «код» из слов с адресом и именем аккаунта — code null, в ответе его нет")):
        status, raw, _ = ask(KEY_9, "/v1/robot/predict", raw=json.dumps({**json.loads(body), "robot_schema": schema}).encode())
        error = as_json(raw).get("error", {})
        check((status, error.get("code"), error.get("message")) == want and error.get("type") == "invalid_request_error"
              and b"org-secret" not in raw and b"10.0.0.9" not in raw, f"{why} (got {status} {error})")


def test_levers():
    print("рычаги стандарта: подписке — словами Responses, ячейке — словами шаблона (1.3.501):")
    reset()
    status, raw, _ = ask(KEY_8, body={**chat("Standart"), "reasoning_effort": "high", "verbosity": "medium"})
    sent = A.seen[-1][2] if A.seen else {}
    check(status == 200 and sent.get("reasoning") == {"effort": "high"} and sent.get("text") == {"verbosity": "medium"},
          f"подписке ушли reasoning.effort и text.verbosity клиента (got {sent.get('reasoning')} {sent.get('text')})")
    status, raw, _ = ask(KEY_8, body={**chat("Gemma"), "reasoning_effort": "none"})
    sent = json.loads(G.seen[-1][2]) if G.seen else {}
    check(status == 200 and sent.get("chat_template_kwargs") == {"enable_thinking": False}
          and as_json(raw)["choices"][0]["message"]["content"] == "G",
          f"ячейке ушло «не думай» словами её шаблона (got {status} {sent.get('chat_template_kwargs')})")
    status, raw, _ = ask(KEY_8, body={**chat("Gemma"), "reasoning_effort": "low"})
    check(status == 200 and "chat_template_kwargs" not in json.loads(G.seen[-1][2]),
          "negative: усилие, при котором думать можно, — ячейке не сказано ничего")


def journal():
    """Every record the proxy wrote, oldest first."""
    rows = []
    for path in sorted((TMP / "logs").glob("*.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def test_sender_behind_the_proxy():
    print("отправитель за прокси DSM (2026-10-11: в журнале был 127.0.0.1 у всех):")
    reset()
    ask(None, extra={"X-Forwarded-For": "198.51.100.7, 192.0.2.44"})
    status, _raw, _ = ask(KEY_1, body=chat("Econom"), extra={"X-Forwarded-For": "192.0.2.45"})
    ask(None, extra={"X-Real-IP": "192.0.2.46"})
    conn = http.client.HTTPConnection("127.0.0.1", OLD, timeout=12)
    conn.request("POST", "/v1/chat/completions", body=json.dumps(chat("x")),
                 headers={"Content-Type": "application/json", "Authorization": "Bearer wrong", "X-Forwarded-For": "192.0.2.47"})
    conn.getresponse().read()
    conn.close()
    # The proxy writes a record after its answer has left: wait for the four, a little.
    deadline = time.time() + 5
    while True:
        rows = journal()
        refused = [r["item"].get("client") for r in rows if r.get("event") == "blocked" and r["item"].get("reason") == "entry:no-key"]
        served = [r["item"].get("client") for r in rows if r.get("event") == "finished" and r["item"].get("port") == C1]
        bad_key = [{k: r["item"].get(k) for k in ("status", "path", "client")} for r in rows
                   if r.get("event") == "blocked" and r["item"].get("reason") == "unauthorized:bad-api-key"]
        if (refused[-2:] == ["192.0.2.44", "192.0.2.46"] and served[-1:] == ["192.0.2.45"] and bad_key) or time.time() > deadline:
            break
        time.sleep(0.05)
    check(refused[-2:] == ["192.0.2.44", "192.0.2.46"],
          f"отказ входа записан с адресом, который назвал прокси: последний в X-Forwarded-For, или X-Real-IP (got {refused[-2:]})")
    check(status == 200 and served[-1:] == ["192.0.2.45"],
          f"обслуженный запрос клиента — тоже с его адресом (got {status} {served[-1:]})")
    check(bad_key[-1:] == [{"status": 401, "path": "/v1/chat/completions", "client": "192.0.2.47"}],
          f"отказ порта по неверному ключу записан с кодом 401 и путём — история запросов показывает его строкой (got {bad_key[-1:]})")


for fn in (test_model_list, test_requests, test_refusals, test_provider_failures, test_old_agent_still_served,
           test_no_router_for_a_consumer, test_sender_behind_the_proxy, test_speech_forms, test_model_kinds, test_robot_policy,
           test_levers):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("consumers of the entry snapshot holds")
