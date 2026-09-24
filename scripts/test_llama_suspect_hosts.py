#!/usr/bin/env python3
"""Баннер «свежая сборка llama.cpp роняет ячейки» для машин со скаутом.

Контроллер судил только о своей машине. Скаут 2.6 судит о своей и шлёт
вердикт в обоих отчётах (llamaSuspect); контроллер держит его в записи
машины, отдаёт доске строкой на машину (hostSuspects) и передаёт скауту
«скрыть» (POST /api/fleet/llama-suspect-dismiss). Откат — прежний путь
/api/fleet/llama-restore, после подтверждения на доске.

Пинится значениями: что остаётся в записи машины из отчёта и опроса, чего
не выдумывается у скаута старше 2.6, что уходит скауту на «скрыть» и как
сразу меняется запись, какие строки получает доска и что ответ доски их
несёт. Сеть и хранилище подменены.

Запуск: python3 scripts/test_llama_suspect_hosts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin import topology as T  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


CAND = {"id": "20260920-090000-def5678", "commit": "def5678", "version": "version: 9900 (def5678)",
        "builtAt": 1789600000, "sizeMb": 87}
VERDICT = {"suspect": True, "crashes15m": 3, "builtAt": 1789996400, "currentCommit": "abc1234",
           "firstSeenAt": 1789999100, "lastSeenAt": 1789999880, "restoreCandidate": CAND}


def section_the_record():
    print("запись машины:")
    base = {"host": {"id": "box-a", "name": "Box A"}}
    check(fc.host_from_report({**base, "llamaSuspect": VERDICT})["llamaSuspect"] == VERDICT,
          "скаут 2.6+ говорит «подозреваю» — запись держит вердикт целиком: сколько, какая сборка, когда, что откатить")
    check(fc.host_from_report({**base, "llamaSuspect": {"suspect": False, "junk": 1}})["llamaSuspect"] == {"suspect": False},
          "«не подозреваю» — так и записано, без лишнего")
    got = fc.host_from_report(base)
    check("llamaSuspect" in got and got["llamaSuspect"] is None,
          "negative: скаут старше 2.6 молчит — None: «не умеет судить», а не «проверено, всё хорошо»")
    odd = fc.host_from_report({**base, "llamaSuspect": {"suspect": True, "crashes15m": "x", "builtAt": None,
                                                        "currentCommit": "a" * 90, "restoreCandidate": {"commit": "d"}}})
    check(odd["llamaSuspect"] == {"suspect": True, "crashes15m": 0, "builtAt": 0, "currentCommit": "a" * 40,
                                  "firstSeenAt": 0, "lastSeenAt": 0, "restoreCandidate": None},
          "boundary: мусор в числах — 0, длинный коммит обрезан, кандидат без id — «откатывать не на что»")
    check(fc.host_from_report({**base, "llamaSuspect": {"suspect": "yes"}})["llamaSuspect"] == {"suspect": False},
          "negative: «да» строкой — не True: баннер поднимает только настоящее «да»")
    state = {"host": {"id": "box-a"}, "llamaSuspect": VERDICT}
    check(fc.scout_payload_from_state(state, "u").get("llamaSuspect") == VERDICT
          and fc.scout_payload_from_state({"host": {"id": "box-a"}}, "u").get("llamaSuspect") is None,
          "опрос /api/state несёт то же поле под тем же именем — пульс и опрос не стирают его друг у друга")


class FakeScout:
    def __init__(self, answer):
        self.answer = answer
        self.sent = []

    def post(self, path, payload, timeout=0):
        self.sent.append((path, payload))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def dismissed(answer):
    scout = FakeScout(answer)
    store = {"hosts": {"box-a": {"id": "box-a", "llamaSuspect": dict(VERDICT)}}}
    saved = []
    keep = fc._scout, fc.topology_store, fc.save_admin_state
    fc._scout = lambda host_id: scout
    fc.topology_store = lambda: store
    fc.save_admin_state = lambda: saved.append(1)
    try:
        try:
            result = fc.client_llama_suspect_dismiss({"hostId": "box-a"})
        except AppError as exc:
            result = ("refused", str(exc))
    finally:
        fc._scout, fc.topology_store, fc.save_admin_state = keep
    return result, scout.sent, store["hosts"]["box-a"]["llamaSuspect"], saved


def section_dismiss():
    print("«скрыть» у машины:")
    result, sent, record, saved = dismissed({"ok": True, "dismissed": "abc1234:1789996400"})
    check(sent == [("/api/llama-node/suspect-dismiss", {})] and result == {"ok": True, "dismissed": "abc1234:1789996400"},
          "уходит её скауту — он помнит «скрыто» для этой сборки; ответ скаута — как есть")
    check(record == {"suspect": False} and saved == [1],
          "запись машины сразу «не подозреваю» — строка не вернётся со следующим опросом доски до нового отчёта")
    result, sent, record, saved = dismissed(AppError("scout at 10.0.0.5 did not answer", 502))
    check(result == ("refused", "scout at 10.0.0.5 did not answer") and record == VERDICT and saved == [],
          "negative: скаут не ответил — отказ с причиной, запись не тронута: баннер честно остаётся")


def section_board_rows():
    print("строки для доски:")
    hosts = [{"id": "box-a", "name": "Box A", "llamaBinaryVersion": "version: 9947 (abc1234)", "llamaSuspect": VERDICT},
             {"id": "box-b", "name": "", "llamaSuspect": dict(VERDICT, crashes15m=5)},
             {"id": "box-c", "name": "C", "llamaSuspect": {"suspect": False}},
             {"id": "box-d", "name": "D", "llamaSuspect": None},
             {"id": "box-e", "name": "E"}]
    rows = T.host_suspects(hosts)
    check(rows == [{**VERDICT, "hostId": "box-a", "name": "Box A", "llamaBinaryVersion": "version: 9947 (abc1234)"},
                   {**VERDICT, "crashes15m": 5, "hostId": "box-b", "name": "box-b", "llamaBinaryVersion": ""}],
          "строка на машину с подозрением: вердикт, id, имя как на доске (нет имени — id) и сборка, что стоит сейчас — "
          "для окна подтверждения")
    check(T.host_suspects([]) == [], "negative: машин нет — строк нет")


def section_the_answer():
    print("ответ доски несёт строки:")
    import caravan.admin.cloud_api as cloud_api
    import caravan.admin.status as status
    hosts = [{"id": "box-a", "name": "Box A", "state": "online", "llamaSuspect": VERDICT}]
    patch = {
        "parse_config": lambda: {},
        "topology_store": lambda: {"assignments": {}, "serverSlots": {}, "clientAliases": {}, "layout": {}},
        "load_agent_proxy_config": lambda: {"routes": [], "routers": [], "policy": {"maxSlots": 1}},
        "_llama_total_slots": lambda: 0,
        "proxy_ports_last_seen": lambda: {},
        "_port_holders": lambda: {},
        "topology_server": lambda _config: {"id": "controller", "name": "Ctl", "llamaServers": []},
        "sync_router_outputs": lambda *a: False,
        "cloud_accounts_state": lambda: [],
        "cloud_blocks_state": lambda: [],
        "topology_clients": lambda: [],
        "topology_hosts": lambda: [dict(h) for h in hosts],
        "annotate_route_windows": lambda *a: None,
        "topology_nodes": lambda *a: [],
        "cloud_provider_presets_public": lambda: [],
    }
    saved = {k: getattr(T, k) for k in patch}
    keep = cloud_api.annotate_cloud_topology, status.llama_crash_suspect
    try:
        for k, v in patch.items():
            setattr(T, k, v)
        cloud_api.annotate_cloud_topology = lambda *a: {"endpoints": {}, "codexClientVersion": {}}
        status.llama_crash_suspect = lambda: {"suspect": False}
        payload = T.topology_state(refresh_hosts=False)
    finally:
        for k, v in saved.items():
            setattr(T, k, v)
        cloud_api.annotate_cloud_topology, status.llama_crash_suspect = keep
    check([r["hostId"] for r in payload.get("hostSuspects", [])] == ["box-a"]
          and payload.get("llamaSuspect") == {"suspect": False},
          "/api/topology: своя строка контроллера (llamaSuspect) и строки машин (hostSuspects) — рядом, порознь")


def main():
    section_the_record()
    section_dismiss()
    section_board_rows()
    section_the_answer()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nllama suspect hosts OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
