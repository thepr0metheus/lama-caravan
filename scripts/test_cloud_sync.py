#!/usr/bin/env python3
"""Snapshot of CloudModelSync (caravan/admin/cloud_sync.py): one successful
model list applied to an account's blocks, by value.

The operator's word (2026-09-27): the lists keep themselves — new models
appear by themselves, a model the provider dropped that nothing points at goes
by itself, and one that something points at stays. Pinned: what a list adds
(hidden, stamped new — except on a first fill), what it counts, when a block
goes (two lists in a row, nothing pointing, not the operator's own), what is
not a verdict (an empty list, a list that drops more than half at once), the
removal kept for a day, and bringing one back.

Run: python3 scripts/test_cloud_sync.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-cloudsync-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
for sub in ("state", "config", "secrets"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud, model_catalog  # noqa: E402
from caravan.admin.cloud_sync import CloudModelSync  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class World:
    """An account's blocks in memory, what points at them, and a clock."""

    def __init__(self, blocks, used=()):
        self.data = {"accounts": [{"id": "acc"}], "blocks": [dict(b) for b in blocks]}
        self.used = set(used)
        self.saves = 0
        self.removed = []
        self.t = 1000

    def sync(self):
        refs = type("Refs", (), {"in_use": lambda _s, bid: bid in self.used})()
        return CloudModelSync(load=lambda: self.data, save=lambda d: self._save(d), refs=lambda: refs,
                              now=lambda: self.t, record_removed=lambda acc, bl, at: self.removed.extend(b["id"] for b in bl))

    def _save(self, data):
        self.saves += 1
        self.data = data

    def ids(self):
        return sorted(b["id"] for b in self.data["blocks"])

    def block(self, bid):
        return next((b for b in self.data["blocks"] if b["id"] == bid), None)


def listed(*ids):
    return [{"id": i} for i in ids]


def main():
    print("что добавляет список:")
    w = World([])
    rep = w.sync().apply("acc", listed("gpt-6-sol", "text-embedding-3-small", "gpt-6-luna"))
    check(w.ids() == ["gpt-6-luna", "gpt-6-sol"] and rep["skipped"] == 1,
          "чат-модели — блоками, эмбеддинги пропущены")
    check(all("newSince" not in b and not b.get("exposed") for b in w.data["blocks"]),
          "первое наполнение — не «новое», и на канбане не показано")
    rep = w.sync().apply("acc", listed("gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol"))
    check(rep["created"] == ["gpt-6-1-sol"] and w.block("gpt-6-1-sol").get("newSince") == 1000
          and not w.block("gpt-6-1-sol").get("exposed"),
          "появилась модель у аккаунта с блоками — новый блок, скрытый, с отметкой «новая»")

    print("что считает и что убирает:")
    w = World([{"id": "a", "accountId": "acc", "model": "a"}, {"id": "b", "accountId": "acc", "model": "b"},
               {"id": "c", "accountId": "acc", "model": "c"}, {"id": "m", "accountId": "acc", "model": "m", "manual": True},
               {"id": "x", "accountId": "other", "model": "x"}], used={"b"})
    rep = w.sync().apply("acc", listed("a", "new-one"))
    check(sorted(rep["gone"]) == ["b", "c", "m"] and rep["removed"] == [] and w.block("c")["goneCount"] == 1,
          "первый список без модели — счёт 1, никто не убран")
    rep = w.sync().apply("acc", listed("a", "new-one"))
    check(rep["removed"] == ["c"] and "c" not in w.ids() and w.removed == ["c"],
          "defect-history (просьба оператора): второй список подряд без модели, на неё ничего не указывает — "
          f"блок убран сам, и уборка записана (got {rep['removed']}, {w.removed})")
    check(w.block("b")["goneCount"] == 2 and w.block("m")["goneCount"] == 2,
          "negative: на модель указывают — остаётся; добавленная руками — остаётся, сколько бы её ни не было")
    check(w.block("x").get("goneCount") is None, "negative: блоки чужого аккаунта не трогаются")
    rep = w.sync().apply("acc", listed("a", "b", "new-one"))
    check(w.block("b").get("goneCount") is None, "модель вернулась в список — счёт снят")
    w = World([{"id": "emb", "accountId": "acc", "model": "text-embedding-3-small"}, {"id": "a", "accountId": "acc", "model": "a"}])
    for _ in range(3):
        rep = w.sync().apply("acc", listed("a", "text-embedding-3-small"))
    check("emb" in w.ids() and w.block("emb").get("goneCount") is None and rep["created"] == [],
          "блок модели эмбеддингов, которую провайдер отдаёт, не «ушёл»: фильтр чата решает, чему дать блок, а не что пропало")

    print("что не вердикт:")
    w = World([{"id": i, "accountId": "acc", "model": i} for i in "abcdefgh"])
    before = w.saves
    rep = w.sync().apply("acc", [])
    check(rep["believed"] is False and w.saves == before and all("goneCount" not in b for b in w.data["blocks"]),
          "пустой список — не «все модели ушли»: ничего не посчитано и не записано")
    small = World([{"id": i, "accountId": "acc", "model": i} for i in "abc"])
    rep = small.sync().apply("acc", [])
    check(rep["believed"] is False and all("goneCount" not in b for b in small.data["blocks"]),
          "пустой список у маленького аккаунта (3 блока, порог массовой пропажи не сработал бы) — тоже не вердикт")
    rep = w.sync().apply("acc", listed("a", "b", "z"))
    check(rep["believed"] is False and rep["created"] == ["z"] and rep["removed"] == []
          and w.block("c")["goneCount"] == 1,
          "список потерял больше половины (6 из 8) разом — может быть частичным ответом: новое добавлено, ушедшее "
          "посчитано, но не убрано")
    for _ in range(4):
        rep = w.sync().apply("acc", listed("a", "b", "z"))
    check(rep["removed"] == [] and w.block("c")["goneCount"] == 5,
          "boundary: пять таких ответов подряд — ещё никто не убран")
    rep = w.sync().apply("acc", listed("a", "b", "z"))
    check(sorted(rep["removed"]) == ["c", "d", "e", "f", "g", "h"],
          "defect-history (Ollama, 2026-09-27: провайдер сменил названия — 17 моделей в списке, 31 из 39 старых ушли): "
          f"шестой одинаковый ответ — это не сбой, ушедшие без ссылок убраны; раньше не убирались никогда (got {rep['removed']})")
    w = World([{"id": i, "accountId": "acc", "model": i} for i in "abcd"])
    rep = w.sync().apply("acc", listed("a"))
    check(rep["believed"] is True and sorted(rep["gone"]) == ["b", "c", "d"],
          "boundary: у маленького аккаунта (4 блока) три ушедших — верим: порог «больше пяти и больше половины»")

    print("день на возврат и возврат:")
    model_catalog.record_removed_blocks("acc", [{"id": "c", "accountId": "acc", "model": "c", "goneCount": 2}], 1000)
    check([r["block"]["id"] for r in model_catalog.removed_blocks(now=1000 + 86399)["acc"]] == ["c"]
          and model_catalog.removed_blocks(now=1000 + 86400)["acc"] == [],
          "убранное помнится сутки (граница: 86399 с — да, 86400 — нет)")
    cloud.save_cloud_data({"accounts": [{"id": "acc", "type": "openrouter", "baseUrl": "https://example.invalid"}],
                           "blocks": [{"id": "c", "accountId": "acc", "model": "other"}]})
    back = CloudModelSync(now=lambda: 1000).restore("acc", "c")
    got = {b["id"]: b for b in cloud.load_cloud_data()["blocks"]}
    check(back and back["id"] == "c-1" and got["c-1"].get("manual") is True and "goneCount" not in got["c-1"]
          and got["c-1"]["model"] == "c",
          "↶ возвращает блок как добавленный руками (иначе следующий список убрал бы снова); id занят — новый")
    check(CloudModelSync().restore("acc", "c") is None, "negative: второй раз возвращать нечего")

    print("метки блока переживают правку:")
    cloud.save_cloud_data({"accounts": [{"id": "acc", "type": "openrouter", "baseUrl": "https://example.invalid"}],
                           "blocks": [{"id": "s", "accountId": "acc", "model": "s", "newSince": 1000, "goneCount": 1}]})
    edited = cloud.upsert_cloud_block({"id": "s", "accountId": "acc", "model": "s", "modelMode": "passthrough",
                                       "contextLength": "", "contextAuto": False})
    check(edited.get("newSince") == 1000 and edited.get("goneCount") == 1 and not edited.get("manual"),
          "правка в окне модели не стирает метки синхронизации и не делает блок «ручным»")
    made = cloud.upsert_cloud_block({"id": "hand", "accountId": "acc", "model": "private-model"})
    check(made.get("manual") is True, "блок, которого не было, — добавлен руками: синхронизация его не уберёт")
    cloud.mark_cloud_blocks_announced(["s"], expose=True)
    again = cloud.upsert_cloud_block({"id": "s", "accountId": "acc", "model": "s", "modelMode": "rewrite",
                                      "contextLength": "", "contextAuto": False})
    check(again.get("announced") is True and again.get("exposed") is True,
          "окно «новая модель» отвечено («просто добавить» — ещё и на канбан); правка отметку не стирает")
    rows = {r["id"]: r for r in cloud.cloud_blocks_state()}
    check(rows["s"]["newSince"] == 1000 and rows["s"]["manual"] is False and rows["hand"]["manual"] is True
          and rows["hand"]["newSince"] is None and rows["s"]["announced"] is True and rows["hand"]["announced"] is False,
          "доска получает «новая с …» и «руками»; нет отметки — None, а не 0")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cloud sync OK: списки моделей ведут блоки сами")
    return 0


if __name__ == "__main__":
    sys.exit(main())
