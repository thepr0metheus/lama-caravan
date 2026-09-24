#!/usr/bin/env python3
"""Автозапуск ячейки на машине со скаутом: ↟ на доске, скаут 2.4+.

Контроллер поднимает свои ячейки при загрузке через `systemctl enable`; у
ячеек скаута этого не было, и после перезагрузки машины они лежали, а ↟ на
их карточках был серым: «not supported for remote hosts». Теперь скаут
хранит запрос старта ячейки и поднимает её при загрузке машины; контроллер
отдаёт ему этот запрос (тот же, что при старте), видит список портов с
автозапуском в отчёте скаута и отдаёт новые настройки ячейки, когда их
сохраняют, — иначе следующая загрузка подняла бы старые.

Пинится значениями: как отчёт ложится в запись хоста по обоим путям (пульс
и опрос), что уходит скауту на ↟ и при сохранении настроек, и чего не
случается. Сеть и хранилище подменены.

Запуск: python3 scripts/test_cell_autostart.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import cell_ops, fleet_clients as fc  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(fn):
    try:
        fn()
    except AppError as exc:
        return getattr(exc, "status", None), str(exc)
    return None


class FakeScout:
    def __init__(self, answer):
        self.answer = answer
        self.sent = []

    def post(self, path, payload, timeout=0):
        self.sent.append((path, payload))
        return self.answer(payload) if callable(self.answer) else self.answer


class Topo:
    def __init__(self, slots):
        self.slots = slots

    def slot(self, host_id, port):
        return self.slots.get((host_id, int(port)), {})

    def put_slot(self, host_id, port, value):
        self.slots[(host_id, int(port))] = value

    def has_slot(self, host_id, port):
        return (host_id, int(port)) in self.slots


class Stubs:
    """Everything the calls under test reach beyond themselves, stood in for
    and put back."""

    def __init__(self, store, scout, slots):
        self.store, self.scout, self.slots = store, scout, slots
        self.saved = []

    def __enter__(self):
        self.keep = [(mod, name, getattr(mod, name)) for mod, name in (
            (fc, "_scout"), (fc, "topology_store"), (fc, "save_admin_state"), (fc, "current_locations"),
            (cell_ops, "topo"), (cell_ops, "is_controller_host"), (cell_ops, "topology_store"),
            (cell_ops, "save_admin_state"), (cell_ops, "upsert_server_slot"), (cell_ops, "state"))]
        fc._scout = lambda host_id: self.scout
        fc.topology_store = lambda: self.store
        fc.save_admin_state = lambda: self.saved.append("fc")
        fc.current_locations = lambda wait=False: Locations([])
        cell_ops.topo = Topo(self.slots)
        cell_ops.is_controller_host = lambda host_id: host_id == "controller"
        cell_ops.topology_store = lambda: self.store
        cell_ops.save_admin_state = lambda: self.saved.append("ops")
        cell_ops.upsert_server_slot = self.upsert
        cell_ops.state = lambda: {}
        return self

    def upsert(self, host_id, port, config=None, model=None, label=None):
        slot = dict(self.slots.get((host_id, int(port)), {}))
        slot.update({"hostId": host_id, "port": int(port), "config": config or {}, "model": model})
        self.slots[(host_id, int(port))] = slot
        return slot

    def __exit__(self, *exc):
        for mod, name, value in self.keep:
            setattr(mod, name, value)


LLAMA_CFG = {"MODEL_FILE": "org/model-q4.gguf", "PORT": "22021", "CTX_SIZE": "8192"}


def section_report_mapping():
    print("отчёт скаута ложится в запись хоста (оба пути):")
    base = {"host": {"id": "box-a", "name": "A"}}
    got = fc.host_from_report({**base, "autostart": [22024, "22001", "x", 22001]}).get("autostart")
    check(got == [22001, 22024], f"список портов с автозапуском — числа, без мусора и повторов, по возрастанию (got {got})")
    for payload, why in (({**base}, "поля нет"), ({**base, "autostart": "22001"}, "не список")):
        got = fc.host_from_report(payload)
        check("autostart" in got and got["autostart"] is None,
              f"negative: {why} (скаут старше 2.4) — None, а не пустой список: «не умеет» не рисуется как «ни одной» (got {got.get('autostart')!r})")
    state = {"host": {"id": "box-a"}, "autostart": [22001]}
    check(fc.scout_payload_from_state(state, "http://10.0.0.5:8092").get("autostart") == [22001]
          and fc.scout_payload_from_state({"host": {"id": "box-a"}}, "u").get("autostart") is None,
          "опрос /api/state несёт то же поле под тем же именем — иначе пульс и опрос стирали бы его друг у друга")


def section_the_boot_button():
    print("↟ на ячейке скаута:")
    answers = {"ok": True, "autostart": [22021]}
    scout = FakeScout(lambda payload: {**answers, "autostart": [22021] if payload["enabled"] else []})
    store = {"hosts": {"box-a": {"id": "box-a", "autostart": []}}}
    slots = {("box-a", 22021): {"config": dict(LLAMA_CFG), "model": "org/model-q4.gguf", "cacheModels": True},
             ("box-a", 22030): {"config": {"PORT": "22030"}}}
    with Stubs(store, scout, slots) as st:
        on = cell_ops.server_cell_action({"hostId": "box-a", "port": 22021, "action": "enable"})
        after_on = list(store["hosts"]["box-a"]["autostart"])
        off = cell_ops.server_cell_action({"hostId": "box-a", "port": 22021, "action": "disable"})
        after_off = list(store["hosts"]["box-a"]["autostart"])
        empty_off = refusal(lambda: cell_ops.server_cell_action({"hostId": "box-a", "port": 22030, "action": "disable"}))
        empty_on = refusal(lambda: cell_ops.server_cell_action({"hostId": "box-a", "port": 22030, "action": "enable"}))
    path, sent = scout.sent[0]
    check(on.get("ok") is True and path == "/api/llama-node/autostart" and sent["port"] == 22021
          and sent["enabled"] is True,
          "включить: скауту — порт и «включить»")
    payload = sent.get("payload") or {}
    check(payload.get("modelPath") == "org/model-q4.gguf" and payload.get("port") == 22021
          and payload.get("cacheModels") is True and payload.get("config") == LLAMA_CFG and "args" in payload
          and "inPlace" in payload,
          "и запрос старта — тот же, что уходит при старте (scout_start_payload): модель, порт, кэш, конфиг, "
          "аргументы, подсказки «на месте»")
    check(after_on == [22021] and after_off == [],
          "запись хоста сразу берёт ответ скаута — ↟ не ждёт следующего отчёта")
    check(scout.sent[1][1] == {"port": 22021, "enabled": False, "payload": None} and off.get("ok") is True,
          "выключить: без запроса старта")
    check(empty_off is None and scout.sent[2][1] == {"port": 22030, "enabled": False, "payload": None},
          "negative: выключить можно и у ячейки без модели — проверок старта для этого не нужно")
    check(empty_on == (400, "cell has no saved model — configure it first") and len(scout.sent) == 3,
          "negative: включить автозапуск ячейке, которую нечем запустить, — отказ, скауту ничего не ушло")


def section_saving_settings():
    print("сохранение настроек ячейки с автозапуском:")
    scout = FakeScout({"ok": True, "autostart": [22021]})
    store = {"hosts": {"box-a": {"id": "box-a", "autostart": [22021]}}}
    slots = {("box-a", 22021): {"config": dict(LLAMA_CFG), "model": "org/model-q4.gguf"}}
    newer = {**LLAMA_CFG, "CTX_SIZE": "16384"}
    with Stubs(store, scout, slots):
        doc = cell_ops.server_cell_save_config({"hostId": "box-a", "port": 22021, "config": newer, "cacheModels": True})
    sent = scout.sent[0][1] if scout.sent else {}
    check(doc.get("autostart") == {"ok": True} and sent.get("enabled") is True
          and (sent.get("payload") or {}).get("config") == newer,
          "новые настройки уходят скауту: следующая загрузка поднимет ячейку с ними, а не со старыми")
    scout = FakeScout({"ok": True})
    store = {"hosts": {"box-a": {"id": "box-a", "autostart": []}}}
    with Stubs(store, scout, dict(slots)):
        doc = cell_ops.server_cell_save_config({"hostId": "box-a", "port": 22021, "config": newer})
    check(scout.sent == [] and "autostart" not in doc,
          "negative: ячейка без автозапуска — скауту ничего, в ответе ничего лишнего")

    def refused(payload):
        raise AppError("scout at 10.0.0.5 did not answer", 502)
    scout = FakeScout(refused)
    store = {"hosts": {"box-a": {"id": "box-a", "autostart": [22021]}}}
    with Stubs(store, scout, dict(slots)):
        doc = cell_ops.server_cell_save_config({"hostId": "box-a", "port": 22021, "config": newer})
    check(doc.get("ok") is True and doc.get("autostart") == {"ok": False, "error": "scout at 10.0.0.5 did not answer"},
          "скаут не принял — настройки всё равно сохранены, а ответ говорит, что автозапуск остался со старыми")


def main():
    section_report_mapping()
    section_the_boot_button()
    section_saving_settings()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\ncell autostart OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
