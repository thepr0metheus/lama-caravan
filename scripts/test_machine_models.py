#!/usr/bin/env python3
"""Value snapshot: the models of a machine's entry as router outputs and pool rows (1.3.506).

Step 2 of the owner's plan of 2026-10-12 (visumap caravan-scout-openai): the machine is a provider,
and a pool's row names "machine + model". The scout lists the machine's models (scout 2.28,
`entryModels`) with their places (scout 2.29); the controller makes an output of each, `mm:<hash>`,
and the proxy sends a request to the machine's entry with the model's name in it. Pinned, by value:

  * the report's list as the machine's record keeps it — and "not said" apart from "none";
  * the outputs: an id with no port in it, the entry's address, the copies' facts;
  * the router's outputs and a pool's rows naming them;
  * through a real proxy to a fake scout on 127.0.0.1: the model named in the request, a queue of
    its own, its places as the scout says them, a model with no running copy giving way to the
    pool's next row, the port's /v1/models, the probe.

Run: python3 scripts/test_machine_models.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-machine-models-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
os.environ["CARAVAN_DATA_DIR"] = str(TMP / "data")
sys.path.insert(0, str(ROOT))

from caravan.admin.fleet_clients import host_from_report, scout_payload_from_state  # noqa: E402
from caravan.admin.machine_models import MachineModels, MachineOutputs  # noqa: E402
from caravan.admin.proxies_config import sync_router_outputs  # noqa: E402
from caravan.admin.router_dsl import normalize_router_output  # noqa: E402
from caravan.common.cloud_pools import CloudPools  # noqa: E402
from caravan.common.upstream_types import UpstreamType  # noqa: E402
from caravan.proxy.capacity import (MachinePlaces, llama_processing_count, output_has_capacity,  # noqa: E402
                                    route_group_key, upstream_slot_total)
from caravan.proxy.entry import EntryHandler  # noqa: E402
from caravan.proxy.handler import ProxyHandler  # noqa: E402
from caravan.proxy.output_health import output_health  # noqa: E402
from caravan.proxy.output_probe import probe_output  # noqa: E402
from caravan.proxy.outputs import overlay_output  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


REPORTED = [
    {"id": "gemma", "object": "model", "created": 900, "owned_by": "box",
     "caravan": {"state": "running", "slots": 6, "busy": 1,
                 "copies": [{"port": 22001, "state": "running", "slots": 4, "busy": 1},
                            {"port": 22002, "state": "running", "slots": 2, "busy": 0}]}},
    {"id": "ear", "object": "model", "created": 0, "owned_by": "box",
     "caravan": {"state": "stopped", "slots": 0, "busy": 0, "copies": [{"port": 22005, "state": "stopped", "slots": None, "busy": None}]}},
]


def test_record():
    print("модели машины в её записи:")
    clean = MachineModels.clean(REPORTED)
    check(clean == [{"id": "gemma", "state": "running", "slots": 6, "busy": 1,
                     "copies": [{"port": 22001, "state": "running", "slots": 4, "busy": 1},
                                {"port": 22002, "state": "running", "slots": 2, "busy": 0}]},
                    {"id": "ear", "state": "stopped", "slots": 0, "busy": 0,
                     "copies": [{"port": 22005, "state": "stopped", "slots": None, "busy": None}]}],
          "список отчёта — имя, состояние, места и копии; обёртка OpenAI (object, created, owned_by) не хранится")
    check(MachineModels.clean(None) is None and MachineModels.clean({"x": 1}) is None and MachineModels.clean([]) == [],
          "старый скаут не говорит — None («не знаю»), пустой список — [] («моделей нет»): два разных ответа")
    odd = MachineModels.clean([{"id": " "}, "x", {"id": "m", "caravan": {"state": "melting", "slots": True, "busy": -1,
                                                                          "copies": [{"port": 0}, {"port": "22001"}, "y"]}}])
    check(odd == [{"id": "m", "state": "unknown", "slots": None, "busy": None, "copies": []}],
          "negative: модель без имени, незнакомое состояние, флаг вместо числа, порт не числом — не выдумываются")
    payload = {"host": {"id": "box", "ip": "10.0.0.5"}, "agentUrl": "http://10.0.0.5:8092", "entryModels": REPORTED}
    check(host_from_report(payload)["entryModels"] == clean and host_from_report({"host": {"id": "box"}})["entryModels"] is None,
          "пульс скаута: запись машины хранит список (entryModels); у старого скаута — None")
    pulled = scout_payload_from_state({"host": {"id": "box"}, "entryModels": REPORTED}, "http://10.0.0.5:8092")
    check(pulled["entryModels"] == REPORTED and scout_payload_from_state({}, "x")["entryModels"] is None,
          "опрос /api/state несёт то же поле под тем же именем — пульс и опрос не стирают друг друга")


SERVER_OBJ = {"llamaServers": [
    {"clientId": "box", "port": 22001, "clientIp": "10.0.0.5", "ctxServed": 32768, "modalities": {"vision": True},
     "slotConfig": {"RUNNER": "llama-server"}},
    {"clientId": "box", "port": 22002, "clientIp": "10.0.0.5", "ctxServed": 16384, "slotConfig": {"RUNNER": "llama-server"}},
    {"clientId": "other", "port": 22005, "clientIp": "10.0.0.9", "ctxServed": 4096},
]}


def test_outputs():
    print("модель машины — выход роутера:")
    host = {"id": "box", "agentUrl": "http://10.0.0.5:8092", "entryModels": MachineModels.clean(REPORTED)}
    outs = MachineOutputs().outputs([host], SERVER_OBJ)
    gemma = outs[0] if outs else {}
    check([o["id"] for o in outs] == [MachineOutputs.output_id("box", "gemma"), MachineOutputs.output_id("box", "ear")]
          and gemma.get("id", "").startswith("mm:") and len(gemma["id"]) == 15,
          "по выходу на модель, в порядке списка; id — mm: и 12 знаков хэша машины и имени")
    check(MachineOutputs.output_id("box", "gemma") == MachineOutputs.output_id("box", "gemma")
          and MachineOutputs.output_id("box", "gemma") != MachineOutputs.output_id("other", "gemma"),
          "id не зависит от портов копий: перенос ячейки на другой порт строки пулов не трогает; у другой машины — свой")
    check({k: gemma.get(k) for k in ("upstreamHost", "upstreamPort", "upstreamType", "upstreamModel", "hostId", "label")}
          == {"upstreamHost": "10.0.0.5", "upstreamPort": 8092, "upstreamType": "machine", "upstreamModel": "gemma",
              "hostId": "box", "label": "gemma"},
          "адрес — вход машины (agentUrl скаута), имя модели — то, что прокси поставит в запрос")
    check(gemma.get("jobs") == ["llm"] and gemma.get("inputs") == ["text", "image"] and gemma.get("contextLength") == 16384,
          "что делает модель — сведения первой копии; окно — наименьшее из копий: запрос может попасть в любую")
    check("jobs" not in outs[1] and "contextLength" not in outs[1],
          "negative: копии, о которой контроллер не знает, нечего сказать — у модели нет сведений, а не выдуманные")
    check(MachineOutputs().outputs([{"id": "box", "entryModels": host["entryModels"]}], SERVER_OBJ) == []
          and MachineOutputs().outputs([{"id": "box", "agentUrl": "http://10.0.0.5:8092", "entryModels": None}], SERVER_OBJ) == [],
          "negative: без адреса входа или без списка (старый скаут) выходов нет — ячейки служат как раньше")
    routers = [{"id": "router:default", "outputs": [], "rules": {}}]
    sync_router_outputs(routers, SERVER_OBJ, [], [], outs)
    stored = [o for o in routers[0]["outputs"] if o["upstreamType"] == "machine"]
    check(len(stored) == 2 and stored[0] == normalize_router_output(gemma) and stored[0]["upstreamModel"] == "gemma"
          and stored[0]["contextLength"] == 16384 and routers[0]["rules"]["default"].startswith("srv:"),
          "выходы моделей — в роутере вместе с ячейками; имя модели, машина и сведения сохраняются; по умолчанию — ячейка")
    check(UpstreamType.of({"upstreamType": "Machine"}) == "machine" and UpstreamType.of({"upstreamType": "x"}) == "llama"
          and UpstreamType.named({"upstreamType": "machine"}) and not UpstreamType.named({}),
          "вид выхода — из одной таблицы; незнакомый вид читается как ячейка, как всегда")
    row = CloudPools.step({"id": "r1", "output": MachineOutputs.output_id("box", "gemma")})
    check(row and row["kind"] == "output" and CloudPools.step({"id": "r2", "output": "mm:bad id!"})["kind"] == "open",
          "строка пула может вести на модель машины (mm:); negative: id не по форме — строка без каната")


# ── a fake scout on 127.0.0.1 ───────────────────────────────────────────────
MODELS = {"gemma": {"state": "running", "slots": 2, "busy": 1}, "sleepy": {"state": "stopped", "slots": 0, "busy": 0},
          "gr00t-n1.7-droid": {"state": "running", "slots": 1, "busy": 0}}
seen = []


class _Scout(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            self.send(200, {"object": "list", "data": [{"id": n, "object": "model", "caravan": m} for n, m in MODELS.items()]})
            return
        name = unquote(self.path[len("/v1/models/"):]) if self.path.startswith("/v1/models/") else ""
        if name in MODELS:
            self.send(200, {"id": name, "object": "model", "caravan": MODELS[name]})
        else:
            self.send(404, {"error": {"message": "no such model", "code": "model_not_found"}})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        asked = json.loads(raw or b"{}")
        seen.append({"path": self.path, "model": asked.get("model"), "auth": self.headers.get("Authorization"),
                     "length": self.headers.get("Content-Length"), "body": raw})
        if MODELS.get(asked.get("model"), {}).get("state") != "running":
            self.send(503, {"error": {"message": "not running", "code": "model_not_running"}})
            return
        if self.path.endswith("/robot/predict") and asked.get("robot_schema") == "other-robot":
            self.send(422, {"error": {"code": "unsupported_robot_schema", "message": "this cell serves another robot"}})
            return
        if self.path.endswith("/robot/predict"):
            self.send(200, {"object": "robot.actions", "model": asked.get("model"), "actions": {"gripper_position": [[0.5]] * 40}})
            return
        self.send(200, {"id": "c1", "object": "chat.completion", "model": asked.get("model"),
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "from the machine"},
                                     "finish_reason": "stop"}]})


class _Cell(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        data = json.dumps({"id": "c2", "object": "chat.completion",
                           "choices": [{"index": 0, "message": {"role": "assistant", "content": "from the cell"},
                                        "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(handler_class):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


SCOUT, CELL = serve(_Scout), serve(_Cell)
SCOUT_PORT = SCOUT.server_address[1]
GEMMA = {"id": MachineOutputs.output_id("box", "gemma"), "label": "gemma", "upstreamHost": "127.0.0.1",
         "upstreamPort": SCOUT_PORT, "upstreamType": "machine", "providerId": "", "upstreamModel": "gemma", "hostId": "box",
         "jobs": ["llm"], "contextLength": 16384}
SLEEPY = {**GEMMA, "id": MachineOutputs.output_id("box", "sleepy"), "label": "sleepy", "upstreamModel": "sleepy"}
# SpiderMonkey's robot policy (GR00T, 2026-10-13) as the machine's entry serves it: no window, its own job.
ROBOT = {**{k: v for k, v in GEMMA.items() if k != "contextLength"}, "id": MachineOutputs.output_id("box", "gr00t-n1.7-droid"),
         "label": "gr00t-n1.7-droid", "upstreamModel": "gr00t-n1.7-droid", "jobs": ["robot-policy"]}
CELL_OUT = {"id": "srv:1", "label": "cell", "upstreamHost": "127.0.0.1", "upstreamPort": CELL.server_address[1],
            "upstreamType": "llama", "providerId": ""}
KEY_A, KEY_B, KEY_C = ("lcv1_" + c * 48 for c in "abc")
Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps({
    "routes": [{"label": "Hermes", "port": 1, "kind": "consumer", "apiKey": KEY_A, "pool": "machine", "portClosed": True, "enabled": True},
               {"label": "Bot", "port": 2, "kind": "consumer", "apiKey": KEY_B, "pool": "sleepy-first", "portClosed": True, "enabled": True},
               {"label": "Spider", "port": 3, "kind": "consumer", "apiKey": KEY_C, "pool": "arm", "portClosed": True, "enabled": True}],
    "routers": [{"id": "router:default", "outputs": [GEMMA, SLEEPY, ROBOT, CELL_OUT], "rules": {"default": "srv:1"},
                 "graph": {"nodes": [], "edges": []}},
                {"id": "router:mm", "outputs": [GEMMA, SLEEPY, ROBOT, CELL_OUT], "rules": {"default": GEMMA["id"]},
                 "graph": {"nodes": [], "edges": []}}],
    "policy": {"maxSlots": 1}}), encoding="utf-8")
Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({"accounts": [], "pools": [
    {"id": "machine", "name": "Machine", "steps": [{"id": "r1", "output": GEMMA["id"]}]},
    {"id": "sleepy-first", "name": "Sleepy", "steps": [{"id": "r1", "output": SLEEPY["id"]}, {"id": "r2", "output": "srv:1"}]},
    {"id": "arm", "name": "Arm", "steps": [{"id": "r1", "output": ROBOT["id"]}]}]}),
    encoding="utf-8")
ENTRY = serve(EntryHandler)
ENTRY.route = None
PORT = serve(ProxyHandler)
PORT.route = {"label": "agent-mm", "port": PORT.server_address[1], "enabled": True, "upstreamHost": "127.0.0.1",
              "upstreamPort": CELL.server_address[1], "routerId": "router:mm"}


def ask(key, model, path="/v1/chat/completions", body=None):
    conn = http.client.HTTPConnection("127.0.0.1", ENTRY.server_address[1], timeout=15)
    body = json.dumps(body or {"model": model, "messages": [{"role": "user", "content": "hi"}]}).encode()
    conn.request("POST", path, body=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def journal_items(at_least=1, seconds=3.0):
    """The journal's finished rows — waited for a moment: the proxy writes one after the answer."""
    deadline = time.time() + seconds
    while True:
        rows = [json.loads(line) for p in Path(os.environ["AGENT_PROXY_LOG_DIR"]).rglob("*.jsonl")
                for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        items = [r.get("item") or {} for r in rows if r.get("event") == "finished"]
        if len(items) >= at_least or time.time() > deadline:
            return items
        time.sleep(0.05)


def test_node():
    print("модели машины на узле доски:")
    import caravan.admin.topology as topology
    saved = topology.topo.power_schedules
    topology.topo.power_schedules = lambda: {}
    try:
        host = {"id": "box", "name": "Box", "ip": "10.0.0.5", "entryModels": MachineModels.clean(REPORTED)}
        nodes = topology.topology_nodes({}, {"llamaServers": []}, [host, {**host, "id": "old", "entryModels": None}])
    finally:
        topology.topo.power_schedules = saved
    check([n["entryModels"] for n in nodes] == [MachineModels.clean(REPORTED), None],
          "узел машины несёт её модели, как их хранит запись, — доска читает там состояние и копии; старый скаут — None")


def test_proxy():
    print("прокси — во вход машины:")
    route = overlay_output({"label": "x", "port": 1}, GEMMA)
    check(route["upstreamModel"] == "gemma" and route_group_key(route) == f"127.0.0.1:{SCOUT_PORT}/gemma"
          and route_group_key(overlay_output(route, CELL_OUT)) == f"127.0.0.1:{CELL.server_address[1]}"
          and "upstreamModel" not in overlay_output(route, CELL_OUT),
          "маршрут на модель машины несёт её имя и свою очередь «адрес:порт/модель»; negative: тот же маршрут на ячейку "
          "имени не уносит")
    check(MachinePlaces.read(route) == (2, 1) and upstream_slot_total(route) == 2 and llama_processing_count(route) == 1,
          "места модели — слова скаута: 2 места, 1 занято")
    asleep = overlay_output({"label": "x", "port": 1}, SLEEPY)
    gone = overlay_output({"label": "x", "port": 1}, {**GEMMA, "upstreamModel": "nope"})
    check(MachinePlaces.read(asleep) == (None, 0) and MachinePlaces.read(gone) == (None, None),
          "0 мест (ни одна копия не работает) — не число для ожидания, None; модели нет — ничего не известно")
    check(output_has_capacity(GEMMA, {"maxSlots": 1}) is True,
          "у модели 2 места и ни одного своего запроса — место есть (не по политике в 1 место)")

    seen.clear()
    status, data = ask(KEY_A, "Machine")
    got = seen[-1] if seen else {}
    check(status == 200 and json.loads(data)["choices"][0]["message"]["content"] == "from the machine"
          and got.get("model") == "gemma" and got.get("path") == "/v1/chat/completions"
          and got.get("auth") is None and got.get("length") == str(len(got.get("body") or b"")),
          f"клиент зовёт пул, пул — модель машины: во вход машины уходит имя модели, без ключа клиента, со своей длиной "
          f"(got {status} {got.get('model')})")
    items = journal_items()
    check(items and items[-1].get("upstream") == f"127.0.0.1:{SCOUT_PORT}/gemma"
          and items[-1].get("upstreamType") == "machine" and items[-1].get("poolStepId") == "r1",
          "в журнале запрос стоит в очереди модели — «адрес:порт/модель», вид machine, строка пула r1")

    seen.clear()
    status, data = ask(KEY_B, "Sleepy")
    check(status == 200 and json.loads(data)["choices"][0]["message"]["content"] == "from the cell"
          and [s.get("model") for s in seen] == ["sleepy"],
          "модель без работающей копии отвечает 503 — пул уходит к следующей строке, к ячейке")
    check(output_health.is_dead(SLEEPY["id"]) and not output_health.is_dead(GEMMA["id"]),
          "выход неработающей модели помечен мёртвым — 5 минут пул его не спрашивает; работающий — нет")

    conn = http.client.HTTPConnection("127.0.0.1", PORT.server_address[1], timeout=10)
    conn.request("GET", "/v1/models")
    resp = conn.getresponse()
    listed = json.loads(resp.read() or b"{}")
    conn.close()
    check(resp.status == 200 and [m.get("id") for m in listed.get("data") or []] == ["gemma"],
          "GET /v1/models порта, что ведёт на модель машины, — список входа машины, сужённый до этой модели; negative: "
          "соседняя модель машины (sleepy) в нём не названа")
    check(probe_output(GEMMA) == (True, 200, "", "") and probe_output(SLEEPY)[:3] == (False, 503, "model_not_running")
          and probe_output({**GEMMA, "upstreamModel": "nope"})[:3] == (False, 404, "model"),
          "проба выхода: работает — да; остановлена — 503 со словами; нет у машины — 404")


def test_robot():
    print("политика робота на машине (GR00T, 2026-10-13) — тот же путь к входу машины:")
    sent = {"model": "Arm", "robot_schema": "gr00t:oxe_droid_relative_eef_relative_joint", "task": "pick the cup",
            "state": {"gripper_position": [0.1]}, "images": {"wrist_image_left": {"frames": []}}}
    seen.clear()
    status, data = ask(KEY_C, "Arm", "/v1/robot/predict", sent)
    got = seen[-1] if seen else {}
    body = json.loads(got.get("body") or b"{}")
    check(status == 200 and json.loads(data).get("object") == "robot.actions"
          and got.get("path") == "/v1/robot/predict" and got.get("auth") is None
          and body == {**sent, "model": "gr00t-n1.7-droid"} and got.get("length") == str(len(got.get("body") or b"")),
          f"POST /v1/robot/predict пула Arm — во вход машины тот же путь, имя модели машины вместо имени пула, остальное "
          f"тело как было, без ключа клиента (got {status} {got.get('path')} {body.get('model')})")
    seen.clear()
    status, data = ask(KEY_C, "Arm")
    check(status == 400 and "does not serve POST /v1/chat/completions" in json.loads(data).get("error", {}).get("message", "")
          and seen == [],
          f"negative: чат к роботу — 400 входа, машину не спрашивали (got {status})")
    status, data = ask(KEY_A, "Machine", "/v1/robot/predict", {**sent, "model": "Machine"})
    check(status == 400 and seen == [], f"negative: предсказание к чату машины — 400, машину не спрашивали (got {status})")
    status, data = ask(KEY_C, "Arm", "/v1/robot/predict", {**sent, "robot_schema": "other-robot"})
    error = json.loads(data).get("error", {})
    check((status, error.get("code"), error.get("message")) == (422, "unsupported_robot_schema", "this cell serves another robot"),
          f"отказ ячейки через вход машины — слова и код идут клиенту (got {status} {error})")


if __name__ == "__main__":
    for test in (test_record, test_outputs, test_node, test_proxy, test_robot):
        try:
            test()
        except Exception as exc:  # noqa: BLE001 — a crash is a red line, not the end of the file
            check(False, f"{test.__name__} упал: {exc!r}")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        sys.exit(1)
    print("\nmachine models snapshot holds")
