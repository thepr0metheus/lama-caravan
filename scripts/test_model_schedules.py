#!/usr/bin/env python3
"""Value snapshot: when each model is open — its schedule, the same in every pool (1.3.498).

The owner, 2026-10-12 (visumap scheme caravan-model-schedule, step 1): a schedule
belongs to the model; a pool passes over the row of a model closed now; a pool with
no row left answers 503 and the time it opens.

Pinned. caravan/common/model_schedules.py — a model's key as Routing spells it
(an account's model, a machine's cell); the schedules as the file keeps them, a
schedule switched off keeping its windows; what one says at a moment.
caravan/admin/model_schedules.py — the door's reading (what is refused and why), a
cell's schedule following its port, swapping with it, leaving with it; what the board
is told. caravan/common/cloud_file_keys.py — one table of the kept keys, so the
controller writes the schedules back and the proxy reads them. caravan/admin/pools.py
— an account deleted takes its models' schedules, a model taken out of Routing keeps
its. caravan/proxy/pool_steps.py — a closed row passed over, with when it opens; a
pool of closed rows refused 503 with Retry-After to the first opening. The entry's
answer to a client, in OpenAI's shape with the time.

The files are temp files; time and zone are injected. Nothing reaches a provider.

Run: python3 scripts/test_model_schedules.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-model-schedules-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud as admin_cloud  # noqa: E402
from caravan.admin import server_cells as sc  # noqa: E402
from caravan.admin.model_schedules import ModelScheduleDesk  # noqa: E402
from caravan.admin.pools import PoolDesk  # noqa: E402
from caravan.common.caravan_zone import CaravanZone  # noqa: E402
from caravan.common.cloud_file_keys import CloudFileKeys  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.common.model_schedules import ModelKey, ModelSchedules  # noqa: E402
from caravan.proxy import cloud_auth  # noqa: E402
from caravan.proxy.dialect import OpenAIDialect  # noqa: E402
from caravan.proxy.pool_steps import PoolRefusal, PoolSteps  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn):
    try:
        fn()
    except AppError as exc:
        return exc.status, str(exc)
    return None


TBILISI = CaravanZone.named("Asia/Tbilisi")


def at(text):
    return TBILISI.epoch(datetime.fromisoformat(text))


MON_NOON, MON_EVENING, SAT_NOON = at("2026-10-12 12:00"), at("2026-10-12 20:00"), at("2026-10-17 12:00")
WEEKDAYS = [{"days": [0, 1, 2, 3, 4], "from": "09:00", "to": "19:00"}]
NIGHTS = [{"days": [], "from": "19:00", "to": "09:00"}]
LLAMA, CELL = "acc:or/meta/llama", "out:srv:22011"


def section_keys():
    print("ключ модели — как его пишет Маршрутизация:")
    check(ModelKey.account("or", "meta/llama") == LLAMA and ModelKey.output("srv:22011") == CELL
          and ModelKey.output("eng:abc123") == "out:eng:abc123",
          "модель аккаунта — acc:<аккаунт>/<модель> (в имени модели может быть /), ячейка — out:srv:<порт>, модель движка — out:eng:<id>")
    check([ModelKey.of_row(r) for r in ({"kind": "account", "accountId": "or", "model": "meta/llama"},
                                        {"kind": "output", "output": "srv:22011"}, {"kind": "open"}, None)]
          == [LLAMA, CELL, "", ""], "ключ модели строки пула; у строки без каната ключа нет")
    check([ModelKey.parse(k) for k in (LLAMA, CELL, "acc:/m", "acc:or", "acc:or/", "out:cb:std", "out:srv:", "srv:22011", "", None)]
          == [("account", "or", "meta/llama"), ("output", "srv:22011"), None, None, None, None, None, None, None, None],
          "negative: без аккаунта, без модели, выход пула (cb:), пустой номер, ключ без приставки — не модель")


def section_schedules():
    print("расписания в файле и что говорит одно из них:")
    s = ModelSchedules({"schedules": {LLAMA: {"enabled": True, "windows": WEEKDAYS + [{"days": [9], "from": "x", "to": "y"}]},
                                      CELL: {"enabled": "yes", "windows": NIGHTS}, "pool:std": {"enabled": True, "windows": WEEKDAYS},
                                      "out:srv:22012": "junk"}})
    check(s.stored() == {LLAMA: {"enabled": True, "windows": WEEKDAYS}, CELL: {"enabled": False, "windows": NIGHTS}},
          "чтение файла: окно, которое не читается, выпало; «yes» — не включено; ключ не модели и запись не объект — выпали")
    check(s.state(LLAMA, MON_NOON, TBILISI) == {"enabled": True, "windows": WEEKDAYS, "open": True,
                                                 "until": at("2026-10-12 19:00"), "opensAt": None},
          "включено, внутри окна — открыта до конца окна")
    check(s.state(CELL, MON_NOON, TBILISI)["open"] is True and s.closed(CELL, MON_NOON, TBILISI) is None,
          "выключено — модель открыта в любое время, окна при ней")
    s.put(CELL, True, NIGHTS)
    check(s.closed(CELL, MON_NOON, TBILISI) == {"opensAt": at("2026-10-12 19:00")}, "включено, вне окна — закрыта, сказано, когда откроется")
    check(s.state("acc:or/other", MON_NOON, TBILISI) is None and s.closed("acc:or/other", MON_NOON, TBILISI) is None,
          "absence: у модели нет расписания — None, и закрытой она не считается")
    check(s.follow("srv:22011", "srv:22031") and CELL not in s.kept and "out:srv:22031" in s.kept,
          "ячейка сменила порт — расписание пошло с ней")
    s.put("out:srv:22032", True, WEEKDAYS)
    check(s.swap("srv:22031", "srv:22032") and s.of("out:srv:22031")["windows"] == WEEKDAYS
          and s.of("out:srv:22032")["windows"] == NIGHTS, "две ячейки поменялись портами — и расписаниями")
    check(not s.follow("srv:22099", "srv:22098") and not s.swap("srv:22097", "srv:22098"),
          "negative: у ячейки без расписания переносить нечего")
    s.forget_account("or")
    check(LLAMA not in s.kept and s.forget("out:srv:22031") and not s.forget("out:srv:22031"),
          "аккаунт удалён — расписания его моделей ушли; забыть можно один раз")


class Store:
    def __init__(self, data):
        self.data, self.saves = data, 0

    def load(self):
        return json.loads(json.dumps(self.data))

    def save(self, data):
        self.data, self.saves = json.loads(json.dumps(data)), self.saves + 1


def section_desk():
    print("дверь расписания модели:")
    store = Store({"accounts": [{"id": "or", "type": "openrouter"}], "pools": []})
    desk = ModelScheduleDesk(load=store.load, save=store.save, clock=lambda: MON_NOON, zone=TBILISI)
    said = desk.set(LLAMA, {"enabled": True, "windows": [{"days": [4, 0, 1, 2, 3], "from": "9:00", "to": "19:00"}]})
    check(said == {"enabled": True, "windows": WEEKDAYS, "open": True, "until": at("2026-10-12 19:00"), "opensAt": None}
          and store.data["schedules"] == {LLAMA: {"enabled": True, "windows": WEEKDAYS}},
          "окна прочитаны (дни по порядку, ЧЧ:ММ), записаны; ответ — что расписание говорит сейчас")
    check(desk.set(CELL, {"enabled": False, "windows": []})["open"] is True,
          "выключенное расписание без окон — можно: модель открыта всегда")
    saves = store.saves
    for key, schedule, status, said_start, why in (
            ("pool:std", {"enabled": True, "windows": WEEKDAYS}, 400, "not a model", "ключ — не модель"),
            ("acc:gone/m", {"enabled": True, "windows": WEEKDAYS}, 404, "unknown account: gone", "аккаунта нет"),
            (LLAMA, {"enabled": True, "windows": []}, 400, "a schedule switched on needs a window", "включено без окон — закрыло бы навсегда"),
            (LLAMA, {"enabled": True, "windows": [{"days": [8], "from": "09:00", "to": "10:00"}]}, 400, "window 1: days", "день 8"),
            (LLAMA, "on", 400, "schedule must be an object", "расписание не объект")):
        got = refused(lambda: desk.set(key, schedule))
        check(got is not None and got[0] == status and got[1].startswith(said_start),
              f"negative: {why} — {status}, и сказано, что не так (got {got})")
    check(store.saves == saves, "negative: отказ ничего не пишет")
    state = desk.state()
    check(state == {"zone": {"name": "Asia/Tbilisi", "known": True, "offsetMinutes": 240}, "now": MON_NOON,
                    "models": {LLAMA: {"enabled": True, "windows": WEEKDAYS, "open": True, "until": at("2026-10-12 19:00"), "opensAt": None},
                               CELL: {"enabled": False, "windows": [], "open": True, "until": None, "opensAt": None}}},
          f"доске — зона каравана, миг и каждая модель с тем, что говорит её расписание (got {state})")


def section_file():
    print("одна таблица ключей файла — запись контроллера и чтение прокси:")
    check(CloudFileKeys.read({"levels": {}, "sets": [1], "schedules": {"k": 1}, "addedModels": [], "other": {"x": 1}})
          == {"sets": [1], "schedules": {"k": 1}},
          "читаются только известные ключи нужного вида и не пустые")
    check(set(CloudFileKeys.read_all({})) == set(CloudFileKeys.KEPT) and CloudFileKeys.read_all({})["schedules"] == {},
          "чтение прокси — каждый ключ, пустой своего вида, где файла нет")
    admin_cloud.save_cloud_data({"accounts": [{"id": "or", "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1"}],
                                 "pools": [{"id": "chat", "name": "Chat", "steps": [
                                     {"id": "r1", "kind": "output", "output": "srv:22011", "enabled": True},
                                     {"id": "or", "kind": "account", "accountId": "or", "model": "meta/llama", "enabled": True}]}],
                                 "schedules": {CELL: {"enabled": True, "windows": NIGHTS}}, "migrations": []})
    on_disk = json.loads(Path(os.environ["CLOUD_PROVIDERS_FILE"]).read_text())
    check(on_disk.get("schedules") == {CELL: {"enabled": True, "windows": NIGHTS}}
          and admin_cloud.load_cloud_data().get("schedules") == on_disk["schedules"],
          "контроллер пишет расписания и читает их назад (до 1.3.498 ключ, которого нет в списке, пропадал)")
    source = cloud_auth.load_cloud_provider("chat")
    check(source and source.get("schedules") == {CELL: {"enabled": True, "windows": NIGHTS}},
          "прокси получает расписания вместе с пулом — одно чтение файла на запрос")


def section_pools():
    print("аккаунт удалён — его расписания тоже; модель снята из Маршрутизации — расписание при ней:")
    data = {"accounts": [{"id": "or", "type": "openrouter"}, {"id": "ant", "type": "anthropic"}], "pools": [],
            "addedModels": {"or": ["meta/llama", "x"]},
            "schedules": {LLAMA: {"enabled": True, "windows": WEEKDAYS}, "acc:or/x": {"enabled": True, "windows": WEEKDAYS},
                          "acc:ant/claude": {"enabled": True, "windows": NIGHTS}}}
    store = Store(data)

    class Vault:
        def delete(self, account_id):
            return None

    desk = PoolDesk(load=store.load, save=store.save, vault=Vault())
    desk.remove_model("or", "x")
    check("acc:or/x" in store.data["schedules"], "модель снята из Маршрутизации — расписание осталось: вернётся с ним, как уровни")
    desk.remove_account("or")
    check(store.data["schedules"] == {"acc:ant/claude": {"enabled": True, "windows": NIGHTS}},
          "аккаунт удалён — расписания его моделей ушли; чужие не тронуты")


def section_cells():
    print("ячейка сменила порт, поменялась портами, удалена — расписание следует:")
    desk = ModelScheduleDesk()
    desk.set("out:srv:22041", {"enabled": True, "windows": NIGHTS})
    desk.set("out:srv:22042", {"enabled": True, "windows": WEEKDAYS})
    slots = sc.topology_store().setdefault("serverSlots", {})
    for port in (22041, 22042, 22043):
        slots[f"box:{port}"] = {"id": f"box:{port}", "hostId": "box", "port": port, "kind": "serverCell", "config": {"PORT": str(port)}}
    sc.reassign_server_slot_port({"hostId": "box", "port": 22041, "newPort": 22051})
    kept = ModelSchedules(admin_cloud.load_cloud_data())
    check(kept.of("out:srv:22051") == {"enabled": True, "windows": NIGHTS} and kept.of("out:srv:22041") is None,
          "перенос на свободный порт — расписание на новом порту, на старом его нет")
    sc.swap_server_slot_ports({"hostId": "box", "port": 22051, "targetPort": 22042})
    kept = ModelSchedules(admin_cloud.load_cloud_data())
    check(kept.of("out:srv:22042")["windows"] == NIGHTS and kept.of("out:srv:22051")["windows"] == WEEKDAYS,
          "обмен портами — расписания поменялись местами вместе с ячейками")
    sc.move_server_cell("box", 22051, 22061, config={"PORT": "22051"})
    kept = ModelSchedules(admin_cloud.load_cloud_data())
    check(kept.of("out:srv:22061") is not None and kept.of("out:srv:22051") is None,
          "ячейка перезапущена на другом порту (move_server_cell) — расписание пошло с ней")
    sc.move_server_cell("box", 22061, 22051, config={"PORT": "22061"})
    sc.delete_server_slot("box", 22042)
    kept = ModelSchedules(admin_cloud.load_cloud_data())
    check(kept.of("out:srv:22042") is None and kept.of("out:srv:22051") is not None,
          "ячейка удалена — её расписание ушло: новая ячейка на этом порту — другая модель")
    sc.delete_server_slot("box", 22043)
    check(ModelSchedules(admin_cloud.load_cloud_data()).of("out:srv:22051") is not None,
          "negative: удалена ячейка без расписания — чужие расписания не тронуты")


class Selector:
    """PoolSteps with every answer injected: an OpenRouter account, a cell on srv:22011."""

    def __init__(self, now):
        self.now = now
        self.steps = PoolSteps(account=lambda a: {"id": a, "accountId": a, "usageAccountId": a, "credentialAccountId": a,
                                                  "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1"},
                               credential=lambda p: True, clock=lambda: self.now, listed=lambda a, m: True,
                               event=lambda e: None, local=lambda out: {"id": out, "upstreamHost": "127.0.0.1", "upstreamPort": 22011},
                               dead=lambda out: False, free=lambda out: True, zone=TBILISI)

    def choose(self, schedules):
        pool = {"id": "chat", "name": "Chat", "steps": [{"id": "r1", "kind": "output", "output": "srv:22011", "enabled": True},
                                                       {"id": "or", "kind": "account", "accountId": "or", "model": "meta/llama", "enabled": True}]}
        source = {"id": "chat", "name": "Chat", "model": "", "modelMode": "rewrite", "pool": pool, "levels": {}, "schedules": schedules}
        provider, refusal = self.steps.resolve(source)
        rows = {r["stepId"]: r for r in self.steps.snapshot()["pools"]["chat"]["steps"]}
        return provider, refusal, rows


def section_proxy():
    print("пул проходит мимо закрытой модели, а без строк отвечает 503 и время открытия:")
    both = {CELL: {"enabled": True, "windows": NIGHTS}, LLAMA: {"enabled": True, "windows": WEEKDAYS}}
    provider, refusal, rows = Selector(MON_NOON).choose(both)
    check(refusal is None and provider.get("poolStepId") == "or" and rows["r1"]["reason"] == "closed"
          and rows["r1"]["opensAt"] == at("2026-10-12 19:00"),
          "днём ячейка закрыта (откроется в 19:00) — отвечает аккаунт, следующая строка")
    provider, refusal, rows = Selector(MON_EVENING).choose(both)
    check(refusal is None and provider.get("poolStepId") == "r1" and rows["or"]["reason"] == "closed"
          and rows["or"]["opensAt"] == at("2026-10-13 09:00"),
          "вечером открыта ячейка — она и отвечает; аккаунт закрыт до утра")
    provider, refusal, rows = Selector(SAT_NOON).choose(both)
    check(isinstance(refusal, PoolRefusal) and refusal.status == 503 and refusal.closed
          and refusal.opens_at == at("2026-10-17 19:00") and refusal.retry_after == 7 * 3600
          and refusal.opens_text == "2026-10-17 19:00 UTC+04:00"
          and json.loads(refusal.body)["error"]["opens_at"] == at("2026-10-17 19:00"),
          "в субботу днём закрыто всё — 503 (не 429: это не лимит), Retry-After до первого открытия, время словами с поясом")
    off = {CELL: {"enabled": False, "windows": NIGHTS}, LLAMA: {"enabled": True, "windows": WEEKDAYS}}
    provider, refusal, rows = Selector(SAT_NOON).choose(off)
    check(refusal is None and provider.get("poolStepId") == "r1" and rows["r1"]["reason"] == "ready",
          "расписание выключено — модель открыта в любое время")
    provider, refusal, rows = Selector(SAT_NOON).choose({})
    check(refusal is None and provider.get("poolStepId") == "r1", "absence: расписаний нет — пул ведёт себя как до 1.3.498")
    mixed = PoolRefusal({"id": "chat", "name": "Chat"}, [{"stepId": "r1", "reason": "closed", "opensAt": SAT_NOON + 7200},
                                                         {"stepId": "or", "reason": "quota", "resetAt": SAT_NOON + 600}], SAT_NOON, zone=TBILISI)
    check(mixed.status == 503 and not mixed.closed and mixed.retry_after == 600,
          "negative: закрыта одна строка, другая на лимите — это не «закрыто расписанием»; Retry-After — до первого, что освободится")


def section_answer():
    print("ответ клиенту входа — в форме OpenAI, со временем открытия:")
    _provider, refusal, _rows = Selector(SAT_NOON).choose({CELL: {"enabled": True, "windows": NIGHTS},
                                                           LLAMA: {"enabled": True, "windows": WEEKDAYS}})
    status, body, headers = OpenAIDialect({"id": "chat", "name": "Chat"}).answer_error(503, "", refusal)
    error = json.loads(body)["error"]
    check(status == 503 and error["code"] == "model_unavailable" and error["type"] == "server_error"
          and error["message"] == "The model `Chat` is closed by its schedule until 2026-10-17 19:00 UTC+04:00. Try again in 7 h."
          and ("Retry-After", str(7 * 3600)) in headers and ("x-should-retry", "false") in headers,
          f"503, когда откроется — с поясом, через сколько, Retry-After; ждать дольше минуты клиенту не советуют (got {status} {error} {headers})")
    never = PoolRefusal({"id": "chat", "name": "Chat"}, [{"stepId": "r1", "reason": "closed", "opensAt": None}], SAT_NOON, zone=TBILISI)
    status, body, headers = OpenAIDialect({"id": "chat", "name": "Chat"}).answer_error(503, "", never)
    check(json.loads(body)["error"]["message"] == "The model `Chat` is closed by its schedule, and no window of it opens."
          and not any(k == "Retry-After" for k, _v in headers),
          "absence: окна не открываются никогда — так и сказано, без выдуманного Retry-After")


def section_door():
    print("дверь страницы:")
    import caravan.admin.routes as routes
    sent = []

    class Page:
        def send_json(self, payload, *args, **kwargs):
            sent.append(payload)

    real, routes.topology_state = routes.topology_state, lambda **kw: {"drawn": True}
    try:
        routes.POST_ROUTES["/api/models/schedule"](Page(), None, {"model": "acc:or/meta/llama",
                                                                   "schedule": {"enabled": False, "windows": WEEKDAYS}})
        got = refused(lambda: routes.POST_ROUTES["/api/models/schedule"](Page(), None, {"model": "nope", "schedule": {}}))
    finally:
        routes.topology_state = real
    check(len(sent) == 1 and sent[0]["ok"] is True and sent[0]["model"] == LLAMA and sent[0]["schedule"]["enabled"] is False
          and sent[0]["schedule"]["windows"] == WEEKDAYS and sent[0]["topology"] == {"drawn": True},
          f"POST /api/models/schedule — ответ: модель, её расписание и доска (got {sent})")
    check(got is not None and got[0] == 400, f"negative: ключ не модели — 400 (got {got})")
    from caravan.admin.topology import topology_state
    drawn = topology_state(refresh_hosts=False).get("modelSchedules") or {}
    check(drawn.get("models", {}).get(LLAMA, {}).get("enabled") is False and drawn.get("zone", {}).get("known") is not None
          and isinstance(drawn.get("now"), int),
          f"доска получает расписания моделей с зоной каравана и мигом — в том же ответе /api/topology (got {drawn})")


def main():
    for fn in (section_keys, section_schedules, section_desk, section_file, section_pools, section_cells,
               section_proxy, section_answer, section_door):
        fn()
    if _fail:
        print(f"\nmodel schedules FAILED: {len(_fail)}")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nmodel schedules OK: расписание — у модели, пул проходит мимо закрытой, клиент узнаёт, когда она откроется")
    return 0


if __name__ == "__main__":
    sys.exit(main())
