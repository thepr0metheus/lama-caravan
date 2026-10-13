#!/usr/bin/env python3
"""Value snapshot: a cell's names follow it (1.3.499) — caravan/admin/cell_outputs.py.

The defect, found 2026-10-12: a cell moved to another port, or two cells that
swapped their ports, took only the routers' cables along. The pools' rows kept
the old port — after a move a row named a port with no cell, and after a swap
the pool sent its requests to the other model, which nobody had cabled to it.

Pinned. A move, a swap and a start on another port rename the cell in the
routers, the pools' rows and the schedules at once; rows of other cells, account
rows and open rows stay as they were. A move onto a port that a deleted cell's
row or schedule still names takes those names away first. A deleted cell's rows
lose their cable — each row stays in its place, open — and its schedule goes;
the routers keep their names of it. A file that cannot be written is named in
the answer and in the log, and the other files still follow.

The files are temp files; no proxy is started.

Run: python3 scripts/test_cell_outputs.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-cell-outputs-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud as admin_cloud  # noqa: E402
from caravan.admin import proxies_config as pc  # noqa: E402
from caravan.admin import server_cells as sc  # noqa: E402
from caravan.admin.cell_outputs import CellOutputs  # noqa: E402
from caravan.admin.state import save_admin_state  # noqa: E402
from caravan.common.model_schedules import ModelSchedules  # noqa: E402

# A routers' save makes sure a proxy runs; here there is none to start.
pc.ensure_agent_proxy_running = lambda timeout=30: {"ok": True, "code": 0, "stdout": "", "stderr": ""}

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


NIGHTS = [{"days": [], "from": "19:00", "to": "09:00"}]
WEEKDAYS = [{"days": [0, 1, 2, 3, 4], "from": "09:00", "to": "19:00"}]


def out_row(rid, port):
    return {"id": rid, "kind": "output", "output": f"srv:{port}", "enabled": True}


def reset():
    """Two cells on a machine, two pools of rows naming them, schedules, a router — and a row and a
    schedule a cell deleted before 1.3.499 left on :22099."""
    admin_cloud.save_cloud_data({
        "accounts": [{"id": "or", "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1"}],
        "pools": [{"id": "chat", "name": "Chat", "steps": [out_row("r1", 22011), out_row("r2", 22013),
                                                         {"id": "or", "kind": "account", "accountId": "or", "model": "meta/llama", "enabled": True}]},
                  {"id": "code", "name": "Code", "steps": [out_row("r1", 22013), out_row("r2", 22099), {"id": "r3", "enabled": True}]}],
        "schedules": {"out:srv:22011": {"enabled": True, "windows": NIGHTS}, "out:srv:22099": {"enabled": True, "windows": WEEKDAYS}},
        "migrations": []})
    pc.save_agent_proxy_config([], [{"id": "router:default", "name": "Default",
                                     "outputs": [{"id": "srv:22011", "name": "Coder", "upstreamHost": "10.0.0.5", "upstreamPort": 22011},
                                                 {"id": "srv:22013", "name": "Gemma", "upstreamHost": "10.0.0.5", "upstreamPort": 22013}],
                                     "rules": {"default": "srv:22011"}}])
    slots = sc.topology_store().setdefault("serverSlots", {})
    slots.clear()
    for port in (22011, 22013):
        slots[f"box:{port}"] = {"id": f"box:{port}", "hostId": "box", "port": port, "kind": "serverCell", "config": {"PORT": str(port)}}
    save_admin_state()


def rows():
    """Each pool's rows as `srv:<port>`, `open`, or the account row's model."""
    return {p["name"]: [s.get("output") or s.get("model") or "open" for s in p["steps"]]
            for p in admin_cloud.load_cloud_data()["pools"]}


def schedules():
    return {key: entry["windows"] for key, entry in ModelSchedules(admin_cloud.load_cloud_data()).stored().items()}


def router():
    r = next(x for x in pc.load_agent_proxy_config()["routers"] if x["id"] == "router:default")
    return ({o["id"]: o.get("upstreamPort") for o in r["outputs"] if str(o["id"]).startswith("srv:")}, r["rules"].get("default"))


def section_move():
    print("ячейка переехала на другой порт — её имена везде вместе с ней:")
    reset()
    answer = sc.reassign_server_slot_port({"hostId": "box", "port": 22011, "newPort": 22031})
    check(rows() == {"Chat": ["srv:22031", "srv:22013", "meta/llama"], "Code": ["srv:22013", "srv:22099", "open"]},
          f"строка пула идёт за ячейкой; negative: строки других ячеек, строка аккаунта и открытая строка не тронуты (got {rows()})")
    check(schedules() == {"out:srv:22031": NIGHTS, "out:srv:22099": WEEKDAYS},
          f"расписание — на новом порту, на старом его нет; negative: чужое расписание не тронуто (got {schedules()})")
    check(router() == ({"srv:22031": 22031, "srv:22013": 22013}, "srv:22031"),
          f"роутеры — как раньше: выход и правило (got {router()})")
    check(answer["followed"] == {"routers": True, "pools": ["Chat"], "schedule": True, "notFollowed": []},
          f"ответ говорит, что пошло за ячейкой (got {answer.get('followed')})")


def section_swap():
    print("две ячейки поменялись портами — каждая со своими именами:")
    reset()
    answer = sc.swap_server_slot_ports({"hostId": "box", "port": 22011, "targetPort": 22013})
    check(rows() == {"Chat": ["srv:22013", "srv:22011", "meta/llama"], "Code": ["srv:22011", "srv:22099", "open"]},
          f"дефект: строки пулов поменялись вместе с ячейками — пул не шлёт запросы в чужую модель (got {rows()})")
    check(schedules() == {"out:srv:22013": NIGHTS, "out:srv:22099": WEEKDAYS},
          f"расписание ушло на порт своей ячейки (got {schedules()})")
    check(router() == ({"srv:22013": 22013, "srv:22011": 22011}, "srv:22013"),
          f"роутеры поменялись одним проходом, как раньше (got {router()})")
    check(answer["followed"]["pools"] == ["Chat", "Code"] and answer["followed"]["notFollowed"] == [],
          "ответ называет оба пула")


def section_stale():
    print("переезд на порт, где остались имена удалённой ячейки:")
    reset()
    sc.reassign_server_slot_port({"hostId": "box", "port": 22013, "newPort": 22099})
    check(rows() == {"Chat": ["srv:22011", "srv:22099", "meta/llama"], "Code": ["srv:22099", "open", "open"]},
          f"строка, что называла :22099 до переезда, — открыта: она звала удалённую ячейку, не эту; "
          f"строки переехавшей ячейки — на :22099 (got {rows()})")
    check(schedules() == {"out:srv:22011": NIGHTS},
          f"чужое старое расписание :22099 ушло, а не досталось переехавшей ячейке (got {schedules()})")


def section_restart_and_delete():
    print("запуск на другом порту и удаление ячейки:")
    reset()
    sc.move_server_cell("box", 22011, 22041, config={"PORT": "22011"})
    check(rows()["Chat"] == ["srv:22041", "srv:22013", "meta/llama"] and "out:srv:22041" in schedules()
          and router()[1] == "srv:22041",
          f"ячейку запустили на другом порту — строки, расписание и роутеры пошли за ней (до 1.3.499 — никто) (got {rows()['Chat']}, {router()[1]})")
    before = router()
    sc.delete_server_slot("box", 22041)
    data = admin_cloud.load_cloud_data()
    chat = next(p for p in data["pools"] if p["name"] == "Chat")
    check(rows()["Chat"] == ["open", "srv:22013", "meta/llama"] and chat["steps"][0] == {"id": "r1", "enabled": True}
          and "out:srv:22041" not in schedules(),
          f"ячейка удалена — её строка на месте, но без каната; расписание ушло: новая ячейка на этом порту — другая модель (got {chat['steps'][0]})")
    check(router() == before, "negative: роутеры при удалении держат своё, как раньше: их граф решает за порты агентов старого вида")
    reset()
    sc.delete_server_slot("box", 22077)
    check(rows()["Chat"] == ["srv:22011", "srv:22013", "meta/llama"], "negative: удаление ячейки, которой нет, ничего не трогает")


def section_failures():
    print("файл, который не записать, назван, а остальное идёт:")
    store = {"pools": [{"id": "chat", "name": "Chat", "steps": [out_row("r1", 22011), {"id": "e", "kind": "output", "output": "eng:abc", "enabled": True}]}],
             "schedules": {}}
    logs = []

    def boom(_data):
        raise OSError("disk full")

    moved = CellOutputs(load=lambda: json.loads(json.dumps(store)), save=boom, routers_move=lambda a, b: True,
                        log=lambda *a, **k: logs.append(" ".join(map(str, a)))).move(22011, 22031)
    check(moved == {"routers": True, "pools": [], "schedule": False, "notFollowed": ["pools and schedules: disk full"]}
          and logs == ["[cell-outputs] srv:22011 → srv:22031: did not follow — pools and schedules: disk full"],
          f"файл пулов не записался — назван в ответе и в журнале; роутеры пошли (got {moved}, {logs})")
    saved = []

    def refused(_a, _b):
        raise RuntimeError("proxy did not start")

    moved = CellOutputs(load=lambda: json.loads(json.dumps(store)), save=saved.append, routers_move=refused,
                        log=lambda *a, **k: None).move(22011, 22031)
    check(moved["notFollowed"] == ["routers: proxy did not start"] and moved["pools"] == ["Chat"]
          and saved and saved[0]["pools"][0]["steps"][0]["output"] == "srv:22031"
          and saved[0]["pools"][0]["steps"][1]["output"] == "eng:abc",
          "роутеры не записались — названы, а строки пулов всё равно пошли; negative: модель движка (eng:) по порту не названа и не тронута")
    untouched = CellOutputs(load=lambda: {"pools": [], "schedules": {}}, save=saved.append, routers_move=lambda a, b: False,
                            log=lambda *a, **k: None)
    count = len(saved)
    check(untouched.move(22011, 22031) == {"routers": False, "pools": [], "schedule": False, "notFollowed": []}
          and len(saved) == count, "negative: нечего переносить — файл пулов не пишется")


def main():
    for fn in (section_move, section_swap, section_stale, section_restart_and_delete, section_failures):
        fn()
    if _fail:
        print(f"\ncell outputs FAILED: {len(_fail)}")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\ncell outputs OK: ячейка меняет порт — роутеры, строки пулов и расписание идут за ней; удалена — уносит свои")
    return 0


if __name__ == "__main__":
    sys.exit(main())
