#!/usr/bin/env python3
"""The routes that put a cloud model on the kanban and take it off, now that
"on the kanban" means "has a port of its own" (cloud_ports.py, 2026-09-27):
POST /api/cloud-blocks/move-cables, /announced, /expose, /save and
/api/cloud-accounts/bridge-port-delete.

Moving the cables marks the window answered for the new model and opens its
port if it had none. The kanban's tick opens a port; unticking closes them,
and the ✕ beside a port closes that one — the last one asks where the
cables and rules that hold the model go, and says 409 without an answer.
Refused before anything changes: the same model twice, a model that does not
exist, models of two providers.

Run against the real files in a scratch data directory; the firewall door,
systemd and the board's topology are stand-ins. Nothing reaches the machine.

Run: python3 scripts/test_cloud_move_cables.py
"""
import copy
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-movecables-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP / "data")
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "data" / "admin.json")
for sub in ("state", "config", "secrets"):
    (TMP / "data" / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud, routes  # noqa: E402
import caravan.admin.proxies_config as pc  # noqa: E402
import caravan.admin.systemd_ctl as sc  # noqa: E402
from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class _Door:
    def __init__(self):
        self.calls = []

    def open(self, port):
        self.calls.append(("open", port))

    def close(self, port):
        self.calls.append(("close", port))


pc.PORT_DOOR = _Door()
sc.IS_CONTAINER = False
sc.systemctl = lambda *a, **kw: {"ok": True, "stderr": ""}
routes.topology_state = lambda **kw: {"board": True, **kw}

OUT_OLD = {"id": "cb:old", "label": "☁ gpt-6-sol", "target": "cloud:acc", "upstreamHost": "", "upstreamPort": 0,
           "upstreamType": "cloud", "providerId": "old", "accountId": "acc"}
PROXY = {
    "routes": [{"port": 23101, "label": "agent", "routerId": "router:default"},
               {"port": 23004, "label": "bridge gpt-6-sol", "kind": "service", "upstreamType": "cloud",
                "providerId": "old", "routerId": "", "mode": "open"}],
    "routers": [{
        "id": "router:default", "name": "Default",
        "outputs": [{"id": "srv:22011", "label": "cell", "upstreamHost": "10.0.0.5", "upstreamPort": 22011,
                     "upstreamType": "llama"}, OUT_OLD],
        "rules": {"default": "cb:old", "schedule": [], "bySource": [], "failover": ["cb:old"]},
        "graph": {"nodes": [], "edges": [{"id": "e1", "from": "in:skynet:proxy:23101", "to": "out:cb:old"}]},
    }],
}


class _H:
    def __init__(self):
        self.sent = []

    def send_json(self, doc, *a, **kw):
        self.sent.append(doc)


def seed(proxy=None):
    cloud.save_cloud_data({
        "accounts": [{"id": "acc", "name": "OpenAI", "type": "openai"}, {"id": "acc2", "name": "Other", "type": "openai"}],
        "blocks": [
            {"id": "old", "accountId": "acc", "model": "gpt-6-sol"},
            {"id": "new", "accountId": "acc", "model": "gpt-6.1-sol", "newSince": 1000},
            {"id": "far", "accountId": "acc2", "model": "other-model"},
        ],
    })
    Path(AGENT_PROXY_CONFIG_FILE).write_text(json.dumps(proxy or PROXY))


def post(handler, body):
    h = _H()
    try:
        handler(h, types.SimpleNamespace(path=""), body)
        return h.sent, None
    except AppError as err:
        return h.sent, err


def cfg():
    return pc.load_agent_proxy_config()


def ports(block_id):
    return [r["port"] for r in cfg()["routes"] if r.get("kind") == "service" and r.get("providerId") == block_id]


def blocks():
    return {b["id"]: b for b in cloud.load_cloud_data()["blocks"]}


def main():
    move = routes._post_api_cloud_blocks_move_cables
    print("перенос канатов — отказ до любых изменений:")
    for body, why in (({"from": "old", "to": "old"}, "одна и та же модель"),
                      ({"from": "old", "to": "nope"}, "модели нет"),
                      ({"from": "old", "to": "far"}, "модели разных провайдеров")):
        seed()
        before = cfg()
        sent, err = post(move, body)
        check(err is not None and err.status == 400 and sent == [] and cfg() == before
              and ports("new") == [] and ports("far") == [] and not blocks()["new"].get("announced"),
              f"negative: {why} — 400, ни порта, ни отметки")

    print("перенос канатов:")
    seed()
    sent, err = post(move, {"from": "old", "to": "new"})
    r = cfg()["routers"][0]
    check(err is None and len(ports("new")) == 1 and blocks()["new"].get("announced") is True,
          "у новой модели открылся свой порт — она на канбане; окно для неё отвечено")
    check(ports("old") == [23004], "старая модель остаётся со своим портом — закрывает его оператор, если хочет")
    check(r["rules"]["default"] == "cb:new" and r["rules"]["failover"] == ["cb:new"]
          and r["graph"]["edges"] == [{"id": "e1", "from": "in:skynet:proxy:23101", "to": "out:cb:new"}],
          "правила и канат — на новую модель, канат тот же (id e1)")
    check(sent == [{"ok": True, "moved": 3, "topology": {"board": True, "refresh_hosts": False}}],
          f"ответ: сколько перенесено и доска без опроса машин (got {sent})")

    print("«не сейчас» и «просто добавить»:")
    ann = routes._post_api_cloud_blocks_announced
    seed()
    post(ann, {"ids": ["new"]})
    check(blocks()["new"].get("announced") is True and ports("new") == [],
          "«не сейчас»: окно больше не спросит, порта нет — на канбане модели нет")
    seed()
    post(ann, {"ids": ["new"], "expose": True})
    check(blocks()["new"].get("announced") is True and len(ports("new")) == 1,
          "«просто добавить»: отвечено и открыт свой порт — модель на канбане")
    seed()
    post(ann, {"ids": []})
    check(not any(b.get("announced") for b in blocks().values()), "negative: пустой список — никто не отмечен")

    print("галочка на канбане:")
    expose = routes._post_api_cloud_blocks_expose
    seed()
    sent, err = post(expose, {"id": "new", "exposed": True})
    check(err is None and ports("new") == [sent[0]["port"]], "поставить — открыть свой порт, ответ называет его")
    seed()
    before = cfg()
    sent, err = post(expose, {"id": "old", "exposed": False})
    check(err is not None and err.status == 409 and cfg() == before,
          "снять модель, которую держат канат, «по умолчанию» и failover, без ответа — 409, ничего не тронуто")
    seed()
    sent, err = post(expose, {"id": "old", "exposed": False, "resolution": {"moveTo": "new"}})
    check(err is None and ports("old") == [] and len(ports("new")) == 1 and cfg()["routers"][0]["rules"]["default"] == "cb:new",
          "снять с ответом «перецепить»: порт закрыт, канат и правила на новой модели, у неё свой порт")
    seed()
    sent, err = post(expose, {"id": "old", "exposed": False, "resolution": {"cut": True}})
    r = cfg()["routers"][0]
    check(err is None and ports("old") == [] and r["graph"]["edges"] == [] and r["rules"]["default"] == "srv:22011",
          "снять с ответом «отсоединить»: порт закрыт, каната нет, «по умолчанию» — первый выход")

    print("✕ у порта:")
    delete = routes._post_api_cloud_bridge_port_delete
    seed()
    sent, err = post(delete, {"port": 23004})
    check(err is not None and err.status == 409 and ports("old") == [23004], "последний порт держимой модели — 409, порт на месте")
    seed()
    sent, err = post(delete, {"port": 23004, "resolution": {"cut": True}})
    check(err is None and ports("old") == [] and sent[0]["deleted"] == 23004 and sent[0]["leaves"] is True
          and sent[0]["topology"] == {"board": True, "refresh_hosts": False},
          "с ответом — закрыт; ответ говорит, что модель ушла с канбана, и приносит доску")

    print("список ссылок модели говорит и то, что держит канбан:")
    refs = routes._get_api_cloud_blocks_refs
    seed()
    h = _H()
    refs(h, types.SimpleNamespace(query="id=old"))
    got = h.sent[0]
    check(got["held"] == {"cables": 1, "rules": ["default", "failover"]} and got["ports"] == [23004]
          and len(got["refs"]["edges"]) == 1,
          "ответ для окна закрытия: канат и правила, что держат модель, и её порты — одним вызовом")
    h = _H()
    refs(h, types.SimpleNamespace(query="id=new"))
    check(h.sent[0]["held"] == {"cables": 0, "rules": []} and h.sent[0]["ports"] == [],
          "negative: модель без порта и ссылок — пусто, а не отказ")

    print("новая модель из окна модели:")
    save = routes._post_api_cloud_blocks_save
    seed()
    sent, err = post(save, {"block": {"id": "hand", "accountId": "acc", "model": "private-model", "exposed": True}})
    check(err is None and ports("hand") == [sent[0]["port"]] and "exposed" not in blocks()["hand"],
          "галочка «на канбан» у новой модели — это её свой порт; флага в модели нет")
    seed()
    sent, err = post(save, {"block": {"id": "hand2", "accountId": "acc", "model": "m2"}})
    check(err is None and sent[0]["port"] is None and ports("hand2") == [], "negative: без галочки — порта нет")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cloud move cables OK: канбан и порты моделей — через маршруты")
    return 0


if __name__ == "__main__":
    sys.exit(main())
