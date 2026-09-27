#!/usr/bin/env python3
"""The "new model" window's two answers, through their routes:
POST /api/cloud-blocks/move-cables and POST /api/cloud-blocks/announced.

Moving the cables shows the new model on the kanban, marks the window as
answered for it, gives every router the new model's output (or saving would
drop the rules that name it) and rewires in place. Refused before anything
changes: the same model twice, a model that does not exist, models of two
providers. Pinned by value against a scratch data directory; the proxy
config is a stand-in and nothing reaches the firewall or systemd.

Run: python3 scripts/test_cloud_move_cables.py
"""
import copy
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
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROXY = {
    "routes": [{"port": 23101, "label": "agent", "cloudFallbackProviderId": "old"}],
    "routers": [{
        "id": "router:default",
        "outputs": [{"id": "srv:22011"}, {"id": "cb:old"}],
        "rules": {"default": "cb:old", "failover": ["cb:old"]},
        "graph": {"nodes": [], "edges": [{"id": "e1", "from": "in:p", "to": "out:cb:old"}]},
    }],
}


class _H:
    def __init__(self):
        self.sent = []

    def send_json(self, doc, *a, **kw):
        self.sent.append(doc)


def seed():
    cloud.save_cloud_data({
        "accounts": [{"id": "acc", "name": "OpenAI", "type": "openai"}, {"id": "acc2", "name": "Other", "type": "openai"}],
        "blocks": [
            {"id": "old", "accountId": "acc", "model": "gpt-6-sol", "exposed": True},
            {"id": "new", "accountId": "acc", "model": "gpt-6.1-sol", "exposed": False, "newSince": 1000},
            {"id": "far", "accountId": "acc2", "model": "other-model", "exposed": False},
        ],
    })


def post(handler, body, proxy):
    saved = []
    real = routes.load_agent_proxy_config, routes.save_agent_proxy_config, routes.topology_state
    routes.load_agent_proxy_config = lambda: proxy
    routes.save_agent_proxy_config = lambda r, s=None: saved.append((copy.deepcopy(r), copy.deepcopy(s)))
    routes.topology_state = lambda **kw: {"board": True, **kw}
    h = _H()
    try:
        handler(h, types.SimpleNamespace(path=""), body)
        return h.sent, saved, None
    except AppError as err:
        return h.sent, saved, err
    finally:
        routes.load_agent_proxy_config, routes.save_agent_proxy_config, routes.topology_state = real


def blocks():
    return {b["id"]: b for b in cloud.load_cloud_data()["blocks"]}


def main():
    move = routes._post_api_cloud_blocks_move_cables
    print("отказ — до любых изменений:")
    for body, why in (({"from": "old", "to": "old"}, "одна и та же модель"),
                      ({"from": "old", "to": "nope"}, "модели нет"),
                      ({"from": "old", "to": "far"}, "модели разных провайдеров")):
        seed()
        sent, saved, err = post(move, body, copy.deepcopy(PROXY))
        check(err is not None and err.status == 400 and sent == [] and saved == []
              and not blocks()["new"].get("announced") and not blocks()["far"].get("exposed"),
              f"negative: {why} — 400, ничего не сохранено и не отмечено")

    print("перенос канатов:")
    seed()
    sent, saved, err = post(move, {"from": "old", "to": "new"}, copy.deepcopy(PROXY))
    b = blocks()["new"]
    check(err is None and b.get("announced") is True and b.get("exposed") is True,
          "новая модель на канбане, окно для неё отвечено")
    check(blocks()["old"].get("exposed") is True, "старая модель остаётся на канбане — её скрывает оператор, если хочет")
    check(len(saved) == 1, "сохранено один раз")
    routes_saved, routers_saved = saved[0]
    r = routers_saved[0]
    check([o["id"] for o in r["outputs"]] == ["srv:22011", "cb:old", "cb:new"] and r["outputs"][2]["label"] == "☁ gpt-6.1-sol",
          "у маршрутизатора появился выход новой модели")
    check(r["rules"] == {"default": "cb:new", "failover": ["cb:new"]} and r["graph"]["edges"][0] == {"id": "e1", "from": "in:p", "to": "out:cb:new"},
          "правила и канат — на новую модель, канат тот же (id e1)")
    check(routes_saved[0]["cloudFallbackProviderId"] == "new", "↑☁ запасной агента — на новую")
    check(sent == [{"ok": True, "moved": 4, "topology": {"board": True, "refresh_hosts": False}}],
          f"ответ: сколько перенесено и доска без опроса машин (got {sent})")

    seed()
    idle = copy.deepcopy(PROXY)
    idle["routers"][0]["rules"] = {"default": "srv:22011"}
    idle["routers"][0]["graph"]["edges"] = []
    idle["routes"][0].pop("cloudFallbackProviderId")
    sent, saved, err = post(move, {"from": "old", "to": "new"}, idle)
    check(saved == [] and sent[0]["moved"] == 0 and blocks()["new"].get("exposed") is True,
          "negative: у старой переносить нечего — конфиг не пишется, новая всё равно показана")

    print("«не сейчас» и «просто добавить»:")
    ann = routes._post_api_cloud_blocks_announced
    seed()
    sent, saved, err = post(ann, {"ids": ["new"]}, copy.deepcopy(PROXY))
    check(blocks()["new"].get("announced") is True and not blocks()["new"].get("exposed") and saved == [],
          "«не сейчас»: окно больше не спросит, модель остаётся скрытой")
    seed()
    post(ann, {"ids": ["new"], "expose": True}, copy.deepcopy(PROXY))
    check(blocks()["new"].get("announced") is True and blocks()["new"].get("exposed") is True,
          "«просто добавить»: отвечено и на канбане")
    seed()
    post(ann, {"ids": []}, copy.deepcopy(PROXY))
    check(not any(b.get("announced") for b in blocks().values()), "negative: пустой список — никто не отмечен")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cloud move cables OK: окно «новая модель» — ответы через маршруты")
    return 0


if __name__ == "__main__":
    sys.exit(main())
