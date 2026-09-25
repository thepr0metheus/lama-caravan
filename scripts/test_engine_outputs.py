#!/usr/bin/env python3
"""A model of an engine next to the cells as a router output (step 2).

caravan/admin/engine_outputs.py — which models the operator made outputs and
the outputs they become: an id that holds no ':' of the model's name and no
port; where the controller's proxy reaches the engine (the machine's address,
or 127.0.0.1 on the controller's own machine); an exposed model stays an
output while its machine is on the board, even when it cannot work — its
probe says so, and the router's default is not rewritten each time an engine
blinks. The router takes the new kind (router_dsl, proxies_config), and the
proxy names the engine's model in each request, keeps the caravan's key to
itself, narrows the engine's /v1/models to the one model and probes it with
a GET.

The proxy part runs for real: a ProxyHandler on a free port in front of a
stand-in engine that records what reached it.

Run: python3 scripts/test_engine_outputs.py
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-engine-out-"))
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
sys.path.insert(0, str(ROOT))

from caravan.admin.engine_outputs import EngineOutputs  # noqa: E402
from caravan.admin.proxies_config import sync_router_outputs  # noqa: E402
from caravan.admin.router_dsl import _valid_edge_ref, normalize_router_output  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.proxy.graph import _overlay_output  # noqa: E402
from caravan.proxy.handler import ProxyHandler, _engine_model_entry  # noqa: E402
from caravan.proxy.output_probe import probe_output  # noqa: E402
from caravan.proxy.translate import model_named  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def same(actual, expected, msg):
    check(actual == expected, msg if actual == expected else f"{msg}\n        got:  {actual!r}\n        want: {expected!r}")


def raises(fn):
    try:
        fn()
    except AppError as exc:
        return (exc.status, str(exc))
    return None


class Controller:
    """Stands in for ControllerMachine: the controller's machine by id."""

    def __init__(self, own=""):
        self.own = own

    def is_host(self, host):
        return str((host or {}).get("id") or "") == self.own


def engine(kind="ollama", label="Ollama", port=11434, listen="network", models=None):
    return {"kind": kind, "label": label, "port": port, "listen": listen, "state": "ok", "version": "",
            "models": models if models is not None else [{"name": "qwen3:8b"}, {"name": "gpt-oss:120b-cloud",
                                                                              "remote": True}]}


def host(hid="box-a", ip="10.0.0.5", engines=None):
    return {"id": hid, "ip": ip, "engines": engines if engines is not None else [engine()]}


def outputs_with(store, controller=None):
    saves = []
    return EngineOutputs(store=lambda: store, save=lambda: saves.append(1), controller=controller or Controller()), saves


def test_output_id():
    print("id выхода модели движка:")
    a = EngineOutputs.output_id("box-a", "ollama", "qwen3:8b")
    same((a[:4], len(a), ":" in a[4:], "/" in a[4:]), ("eng:", 16, False, False),
         "eng: и 12 знаков хэша — без ':' и '/' из имени модели (id читают по префиксу)")
    same(a, EngineOutputs.output_id("box-a", "ollama", "qwen3:8b"), "тот же — при каждом расчёте")
    same(len({a, EngineOutputs.output_id("box-b", "ollama", "qwen3:8b"),
              EngineOutputs.output_id("box-a", "lmstudio", "qwen3:8b"),
              EngineOutputs.output_id("box-a", "ollama", "qwen3:14b")}), 4,
         "negative: другая машина, другой движок, другая модель — другой id")


def test_set():
    print("сделать модель выходом и перестать:")
    store = {}
    eo, saves = outputs_with(store)
    got = eo.set([host()], "box-a", "ollama", "qwen3:8b", True)
    oid = EngineOutputs.output_id("box-a", "ollama", "qwen3:8b")
    same((got, store["engineOutputs"], len(saves)),
         ({"id": oid, "exposed": True}, {oid: {"hostId": "box-a", "kind": "ollama", "model": "qwen3:8b",
                                               "port": 11434}}, 1),
         "выход записан с портом движка на этот час; сохранено")
    same(eo.set([host()], "box-a", "ollama", "qwen3:8b", False), {"id": oid, "exposed": False},
         "перестать — запись снята")
    same(store["engineOutputs"], {}, "и её нет")
    same(raises(lambda: eo.set([host()], "box-a", "ollama", "llama3:8b", True)),
         (404, "llama3:8b is not a model of ollama on box-a"),
         "negative: модели нет в отчёте машины — 404, не выход в пустоту")
    same(raises(lambda: eo.set([host()], "box-a", "ollama", "gpt-oss:120b-cloud", True)),
         (400, "gpt-oss:120b-cloud runs on the engine's cloud, not on box-a"),
         "negative: облачная модель Ollama — не выход: её трафик ушёл бы из флота под именем местного движка")
    same(raises(lambda: eo.set([host()], "box-z", "ollama", "qwen3:8b", True))[0], 404,
         "negative: машины нет на доске — 404")
    same(raises(lambda: eo.set([host()], "box-a", "", "qwen3:8b", True)),
         (400, "hostId, kind and model are required"), "negative: без вида — 400")
    same(eo.set([host()], "box-z", "ollama", "x", False)["exposed"], False,
         "boundary: снять выход можно и без машины на доске — её могли забыть")


def test_outputs():
    print("выходы из выбранных моделей:")
    oid = EngineOutputs.output_id("box-a", "ollama", "qwen3:8b")
    row = {"hostId": "box-a", "kind": "ollama", "model": "qwen3:8b", "port": 11434}
    eo, _ = outputs_with({"engineOutputs": {oid: dict(row)}})
    same(eo.outputs([host()]), [{
        "id": oid, "label": "qwen3:8b · Ollama", "target": "box-a:engine:ollama", "upstreamHost": "10.0.0.5",
        "upstreamPort": 11434, "upstreamType": "engine", "providerId": "", "upstreamModel": "qwen3:8b",
        "engine": "ollama", "hostId": "box-a"}],
         "движок слушает сеть — адрес машины и порт движка; имя модели в движке — в выходе")
    moved = host(engines=[engine(port=11500)])
    same(eo.outputs([moved])[0]["upstreamPort"], 11500, "порт — из свежего отчёта: движок переехал — выход за ним")
    same(eo.outputs([host(engines=[])])[0]["upstreamPort"], 11434,
         "движок не в отчёте (остановлен) — выход остаётся, с портом, что был; его проба скажет, что он мёртв")
    same(eo.outputs([host(engines=[engine(models=[])])])[0]["upstreamModel"], "qwen3:8b",
         "модель пропала из движка — выход тоже остаётся (не пропадает молча)")
    same(eo.outputs([]), [], "negative: машины нет на доске — выхода нет")
    loop = host(engines=[engine(listen="loopback")])
    same(eo.outputs([loop])[0]["upstreamHost"], "10.0.0.5",
         "движок на 127.0.0.1 чужой машины — адрес машины (он откажет, проба скажет), не 127.0.0.1 контроллера")
    own, _ = outputs_with({"engineOutputs": {oid: dict(row)}}, Controller(own="box-a"))
    same(own.outputs([loop])[0]["upstreamHost"], "127.0.0.1",
         "на машине контроллера движок на 127.0.0.1 достижим — прокси идёт по петле")
    same(own.outputs([host()])[0]["upstreamHost"], "10.0.0.5", "boundary: там же, но слушает сеть — адрес машины")
    same(own.outputs([host(ip="")]), [], "negative: у машины нет адреса — выхода нет")
    junk, _ = outputs_with({"engineOutputs": {"eng:x": "junk", oid: dict(row)}})
    same([o["id"] for o in junk.outputs([host()])], [oid], "negative: мусор в записи — пропущен, остальное цело")


def test_annotate():
    print("что доска знает о моделях движка:")
    oid = EngineOutputs.output_id("box-a", "ollama", "qwen3:8b")
    eo, _ = outputs_with({"engineOutputs": {oid: {"hostId": "box-a", "kind": "ollama", "model": "qwen3:8b"}}})
    got = eo.annotate(host(engines=[engine(listen="loopback")]))
    same([(m["name"], m["outputId"] == EngineOutputs.output_id("box-a", "ollama", m["name"]), m["exposed"])
          for m in got[0]["models"]],
         [("qwen3:8b", True, True), ("gpt-oss:120b-cloud", True, False)],
         "у каждой модели — id её выхода и сделана ли она им")
    same(got[0]["reachable"], False, "движок на 127.0.0.1 чужой машины — прокси до него не достанет")
    same(eo.annotate(host(engines=[engine()]))[0]["reachable"], True, "слушает сеть — достанет")
    same(eo.annotate({"id": "box-a", "engines": None}), None, "negative: старый скаут — None как было")
    same(eo.annotate(host(engines=[{**engine(), "models": None, "state": "auth"}]))[0]["models"], None,
         "negative: движок не назвал модели — None остаётся None")


def test_blocked_by():
    print("почему прокси не достанет до движка:")
    eo = EngineOutputs(store=lambda: {}, save=lambda: None, controller=Controller(own="ctl"),
                       controller_ip="10.0.0.20")

    def why(listen="network", firewall=None, hid="box-a"):
        return eo.blocked_by({"id": hid}, {"listen": listen, "firewall": firewall})

    same(why(), "", "слушает сеть, о файрволе ничего не сказано — достанет (незнание — не вердикт)")
    same(why(listen="loopback"), "loopback", "127.0.0.1 чужой машины — петля")
    same(why(firewall={"state": "blocked", "allowedFrom": []}), "firewall", "ufw никого не пускает на порт — файрвол")
    same(why(firewall={"state": "restricted", "allowedFrom": ["10.0.0.0/24"]}), "",
         "ufw пускает сеть контроллера — достанет")
    same(why(firewall={"state": "restricted", "allowedFrom": ["10.0.0.20"]}), "", "и один адрес контроллера — тоже")
    same(why(firewall={"state": "restricted", "allowedFrom": ["10.9.0.0/24", "Anywhere on eth1"]}), "firewall",
         "negative: пускает других, а нечитаемый источник не в счёт — файрвол")
    same([why(firewall={"state": s}) for s in ("open", "all", "unknown")], ["", "", ""],
         "ufw выключен, пускает всех, не прочитан — не преграда")
    same(why(listen="loopback", firewall={"state": "blocked"}, hid="ctl"), "",
         "машина контроллера: ни петля, ни её файрвол прокси не мешают")
    for ip, name in (("", "адрес контроллера не задан"), ("127.0.0.1", "адрес контроллера — петля (по умолчанию)")):
        blind = EngineOutputs(store=lambda: {}, save=lambda: None, controller=Controller(), controller_ip=ip)
        same(blind.blocked_by({"id": "box-a"}, {"listen": "network",
                                                "firewall": {"state": "restricted", "allowedFrom": ["10.9.0.0/24"]}}),
             "", f"negative: {name} — чьи правила его пускают, не сказать: не вердикт")
    got = eo.annotate({"id": "box-a", "engines": [{"kind": "ollama", "listen": "network", "models": [],
                                                   "firewall": {"state": "blocked", "allowedFrom": []}}]})
    same((got[0]["blockedBy"], got[0]["reachable"]), ("firewall", False), "доска получает и причину, и итог")


def test_router_takes_engines():
    print("роутер знает выход движка:")
    out = normalize_router_output({"id": "eng:abc", "upstreamType": "engine", "upstreamHost": "10.0.0.5",
                                   "upstreamPort": 11434, "upstreamModel": "qwen3:8b" + "x" * 300,
                                   "engine": "ollama", "hostId": "box-a"})
    same((out["upstreamType"], len(out["upstreamModel"]), out["engine"], out["hostId"]),
         ("engine", 200, "ollama", "box-a"), "вид engine держится, имя модели — до 200 знаков")
    cell = normalize_router_output({"id": "srv:22001", "upstreamModel": "x", "upstreamType": "llama"})
    same("upstreamModel" in cell, False, "negative: у выхода ячейки имени модели нет, даже если его принесли")
    same(normalize_router_output({"upstreamType": "weird"})["upstreamType"], "llama",
         "negative: неизвестный вид — llama, как было")
    same(_valid_edge_ref("out:eng:abc", set(), set()), True,
         "ребро к выходу движка держится, пока выхода нет (как srv: и cb:): вернётся — кабель на месте")
    same(_valid_edge_ref("out:zzz:abc", set(), set()), False, "negative: неизвестный вид без выхода — нет")

    oid = EngineOutputs.output_id("box-a", "ollama", "qwen3:8b")
    eng = EngineOutputs(store=lambda: {"engineOutputs": {oid: {"hostId": "box-a", "kind": "ollama",
                                                               "model": "qwen3:8b", "port": 11434}}},
                        save=lambda: None, controller=Controller()).outputs([host()])
    server = {"llamaServers": [{"port": 22001, "clientIp": "10.0.0.5", "model": "m.gguf"}]}
    routers = [{"id": "router:default", "outputs": [], "rules": {"default": ""}}]
    same(sync_router_outputs(routers, server, [], [], eng), True, "выходы изменились — записать")
    same([o["id"] for o in routers[0]["outputs"]], ["srv:22001", oid], "ячейки, потом модели движков")
    same(routers[0]["rules"]["default"], "srv:22001", "по умолчанию — ячейка")
    same(sync_router_outputs(routers, server, [], [], eng), False, "negative: ничего не менялось — не писать")

    lonely = [{"id": "router:default", "outputs": [], "rules": {"default": ""}}]
    sync_router_outputs(lonely, {"llamaServers": []}, [], [], eng)
    same(lonely[0]["rules"]["default"], oid, "ячеек нет — по умолчанию модель движка (локальное прежде облака)")
    sync_router_outputs(lonely, {"llamaServers": []}, [], [], [])
    same((lonely[0]["rules"].get("dormantDefault"), lonely[0]["outputs"]), (oid, []),
         "выход движка пропал (машину забыли) — его место по умолчанию припрятано, как у srv:")
    sync_router_outputs(lonely, {"llamaServers": []}, [], [], eng)
    same((lonely[0]["rules"]["default"], "dormantDefault" in lonely[0]["rules"]), (oid, False),
         "вернулся — место по умолчанию снова его")


def test_proxy_pieces():
    print("прокси: имя модели движка в запросе:")
    body = json.dumps({"model": "agent-name", "messages": []}).encode()
    same(json.loads(model_named(body, "qwen3:8b"))["model"], "qwen3:8b", "имя клиента заменено именем в движке")
    same(json.loads(model_named(b'{"messages": []}', "qwen3:8b"))["model"], "qwen3:8b",
         "клиент имени не прислал — добавлено: движок без него не знает, какую модель")
    same_body = json.dumps({"model": "qwen3:8b"}).encode()
    for name, raw in (("то же имя", same_body), ("не JSON", b"--multipart--"), ("не объект", b"[1,2]"),
                      ("пусто", b""), ("None", None)):
        check(model_named(raw, "qwen3:8b") is raw, f"negative: {name} — те же байты, тот же объект")
    check(model_named(body, "") is body, "negative: выход без имени модели — тело как пришло")

    route = {"port": 23001, "upstreamHost": "127.0.0.1", "upstreamPort": 8080, "label": "r"}
    eng = {"id": "eng:abc", "upstreamType": "engine", "upstreamHost": "10.0.0.5", "upstreamPort": 11434,
           "upstreamModel": "qwen3:8b"}
    on_engine = _overlay_output(route, eng)
    same((on_engine["upstreamType"], on_engine["upstreamModel"], on_engine["routedOutputId"]),
         ("engine", "qwen3:8b", "eng:abc"), "маршрут на выход движка несёт имя модели")
    back = _overlay_output(on_engine, {"id": "srv:22001", "upstreamHost": "10.0.0.5", "upstreamPort": 22001})
    same("upstreamModel" in back, False,
         "negative: тот же маршрут, перерешённый на ячейку (перелив, запасной выход), имени движка не несёт")

    listing = json.dumps({"object": "list", "data": [{"id": "a:1", "object": "model"},
                                                     {"id": "qwen3:8b", "object": "model"}]}).encode()
    status, got = _engine_model_entry(listing, "qwen3:8b")
    same((status, json.loads(got)), (200, {"object": "list", "data": [{"id": "qwen3:8b", "object": "model"}]}),
         "/v1/models движка сужен до одной модели этого порта")
    status, got = _engine_model_entry(listing, "gone:1")
    same((status, json.loads(got)["error"]["type"]), (503, "model_unavailable"),
         "negative: движок модели не знает — 503 с причиной, а не пустой список")
    same(_engine_model_entry(b"<html>", "x")[0], 502, "negative: ответ не список моделей — 502")


# ── the proxy for real, in front of a stand-in engine ─────────────────────────

def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


ENGINE = free_port()
P_ENG = free_port()
P_GONE = free_port()
reached = []


class _Engine(BaseHTTPRequestHandler):
    """A stand-in Ollama: lists two models, answers a chat in the model's name."""

    protocol_version = "HTTP/1.1"
    status_for_models = 200

    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        reached.append(("GET", self.path, None, self.headers.get("Authorization"), self.headers.get("X-Api-Key")))
        if self.path == "/v1/models":
            if type(self).status_for_models != 200:
                return self._send(type(self).status_for_models, {"error": "down"})
            return self._send(200, {"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "llama3.2:3b"}]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        reached.append(("POST", self.path, body.get("model"), self.headers.get("Authorization"),
                        self.headers.get("X-Api-Key")))
        return self._send(200, {"id": "c", "model": body.get("model"),
                                "choices": [{"message": {"role": "assistant", "content": "ok"}}]})


def _route(port, output):
    return {"label": f"r{port}", "port": port, "enabled": True, "upstreamHost": "127.0.0.1",
            "upstreamPort": 8080, "routerId": "router:t", "_output": output}


EOUT = {"id": "eng:abc", "name": "eng", "upstreamType": "engine", "upstreamHost": "127.0.0.1",
        "upstreamPort": ENGINE, "upstreamModel": "qwen3:8b", "engine": "ollama", "hostId": "box-a"}
GONE = {**EOUT, "id": "eng:gone", "upstreamModel": "gone:1"}
CONFIG = {
    "routes": [_route(P_ENG, "eng:abc"), _route(P_GONE, "eng:gone")],
    "routers": [{"id": "router:t", "outputs": [EOUT, GONE],
                 "rules": {"bySource": [{"proxyId": f"skynet:proxy:{P_ENG}", "output": "eng:abc"},
                                        {"proxyId": f"skynet:proxy:{P_GONE}", "output": "eng:gone"}]}}],
}
Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps(CONFIG), encoding="utf-8")
for _r in CONFIG["routes"]:
    _s = ThreadingHTTPServer(("127.0.0.1", _r["port"]), ProxyHandler)
    _s.route = _r
    threading.Thread(target=_s.serve_forever, daemon=True).start()
_e = ThreadingHTTPServer(("127.0.0.1", ENGINE), _Engine)
threading.Thread(target=_e.serve_forever, daemon=True).start()


def ask(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=12)
    try:
        conn.request(method, path, body=body, headers={"Content-Type": "application/json", **(headers or {})})
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", "replace")
    except OSError as exc:
        return 0, str(exc)
    finally:
        conn.close()


def test_proxy_forward():
    print("прокси перед движком — по-настоящему:")
    before = len(reached)
    status, raw = ask(P_ENG, "POST", "/v1/chat/completions",
                      json.dumps({"model": "what-the-agent-calls-it", "messages": [{"role": "user", "content": "hi"}]}),
                      {"Authorization": "Bearer lcv1_route_key", "X-Api-Key": "lcv1_route_key"})
    got = reached[before:]
    same((status, json.loads(raw).get("model")), (200, "qwen3:8b"), "ответ движка дошёл; движок ответил моделью выхода")
    same([(m, p, model) for m, p, model, _a, _k in got], [("POST", "/v1/chat/completions", "qwen3:8b")],
         "в движок ушло имя модели выхода, а не то, как её зовёт агент")
    same([(a, k) for *_x, a, k in got], [(None, None)],
         "ключ маршрута каравана движку не отдан — ни Authorization, ни X-Api-Key")
    before = len(reached)
    status, raw = ask(P_ENG, "POST", "/api/chat", json.dumps({"messages": []}))
    same((status, reached[before:][0][2] if reached[before:] else None), (200, "qwen3:8b"),
         "родной путь движка (/api/chat) без имени модели — имя добавлено")
    status, raw = ask(P_ENG, "GET", "/v1/models")
    same((status, [e.get("id") for e in json.loads(raw).get("data") or []]), (200, ["qwen3:8b"]),
         "/v1/models порта — одна его модель из списка движка")
    status, raw = ask(P_GONE, "GET", "/v1/models")
    same((status, json.loads(raw)["error"]["type"]), (503, "model_unavailable"),
         "negative: модели нет в движке — порт говорит 503 с причиной")


def test_probe():
    print("проба выхода движка — GET, не запрос к модели:")
    before = len(reached)
    same(probe_output(dict(EOUT), timeout=5), (True, 200, "", ""), "движок перечисляет модель — жив")
    same(probe_output(dict(GONE), timeout=5), (False, 404, "model", "the engine does not list gone:1"),
         "negative: модели нет — мёртв с причиной")
    same({m for m, *_x in reached[before:]}, {"GET"}, "проба спрашивает только GET: completion загрузил бы модель")
    _Engine.status_for_models = 500
    try:
        same(probe_output(dict(EOUT), timeout=5)[:3], (False, 500, "http 500"), "движок отвечает 500 — мёртв")
    finally:
        _Engine.status_for_models = 200
    closed = {**EOUT, "upstreamPort": free_port()}
    same(probe_output(closed, timeout=2)[2], "connect", "порт молчит — connect")
    same(probe_output({**EOUT, "upstreamModel": ""}, timeout=2), (False, None, "config", "no engine address or model"),
         "negative: у выхода нет имени модели — ошибка настройки, а не «жив»")


for test in (test_output_id, test_set, test_outputs, test_annotate, test_blocked_by, test_router_takes_engines,
             test_proxy_pieces,
             test_proxy_forward, test_probe):
    try:
        test()
    except Exception as exc:  # noqa: BLE001 — a crash is a red pin; the rest still runs
        check(False, f"{test.__name__} упал: {exc!r}")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for f in _fail:
        print("  - " + f.splitlines()[0])
    sys.exit(1)
print("engine outputs OK")
