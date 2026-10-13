#!/usr/bin/env python3
"""Value snapshot: what a consumer of the entry calls (caravan/common/entry_models.py).

Pinned: a consumer's route keeps one pool id (`pool`), "" for none; a pool
that is gone is none; a route of the old form (`models`, before 1.3.486) calls
the first of the pools it might — of "all" the first pool, of a list the first
id a pool still has — and of anything else none; both normalizers keep `pool`,
or `models` on a route of the old form; a pool is called by its name; a name
is "taken" by another pool only; the callers of a pool are the consumers
cabled to it. The sets that came after (1.3.497) are pinned in
scripts/test_model_sets.py; here, the older forms they still read.

Run: python3 scripts/test_entry_models.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from caravan.common.entry_models import ConsumerPool, EntryModels, ModelAccess  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


POOLS = [{"id": "std", "name": "Standart"}, {"id": "eco", "name": "Econom"}, {"id": "t1", "name": "Twin"},
         {"id": "t2", "name": " twin "}, {"id": "bare", "name": ""}, {"id": "", "name": "No id"}, "not a pool"]


def test_access():
    print("доступ клиента старого вида, как его хранил маршрут:")
    check(ModelAccess.clean("all") == "all", '"all" — все пулы, и новые тоже')
    check(ModelAccess.clean([" std ", "eco", "std", "", None, 7, True]) == ["std", "eco", "7"],
          "список — ids без пробелов и повторов; пустое, None и True выпадают, число становится строкой")
    for raw in (None, "ALL", "std", {"std": 1}, 3):
        check(ModelAccess.clean(raw) == [], f"negative: {raw!r} — ни одного пула, а не «все»")
    check(len(ModelAccess.clean([str(i) for i in range(100)])) == ModelAccess.MAX, "список обрезан до 64")


def test_pool_field():
    print("пул клиента, как его хранит маршрут (2026-10-12: один канат от клиента):")
    check(ConsumerPool.clean(" std ") == "std" and ConsumerPool.clean(7) == "7", "id без пробелов; число — строкой")
    for raw in (None, True, ["std"], {"id": "std"}, 2.5):
        check(ConsumerPool.clean(raw) == "", f"negative: {raw!r} — не id, значит пула нет")
    check(len(ConsumerPool.clean("x" * 200)) == ConsumerPool.MAX, "id обрезан до 80")
    check(ConsumerPool.fields({"pool": " eco ", "models": "all"}) == {"pool": "eco"},
          "маршрут с пулом хранит пул — старое поле models уходит")
    check(ConsumerPool.fields({"pool": None}) == {"pool": ""}, "пул, названный пустым, — пусто, а не старое поле")
    check(ConsumerPool.fields({"models": ["eco", "eco"]}) == {"models": ["eco"]},
          "negative: маршрут старого вида хранит models, пока контроллер его не перепишет")
    check(ConsumerPool.fields({}) == {"models": []}, "negative: маршрут без обоих полей — старый вид без пулов")


def test_pool_of():
    print("какой пул зовёт клиент:")
    check(ConsumerPool.of({"pool": "eco"}, POOLS) == "eco", "свой пул — его id")
    check(ConsumerPool.of({"pool": "gone"}, POOLS) == "", "negative: пропавший пул — пула нет, а не догадка")
    check(ConsumerPool.of({"pool": ""}, POOLS) == "", "negative: без каната — пула нет")
    check(ConsumerPool.of({"pool": "", "models": "all"}, POOLS) == "",
          "negative: поле pool решает, даже пустое: старое поле рядом не читается")
    check(ConsumerPool.of({"models": "all"}, POOLS) == "std", "старый вид «все пулы» — первый пул доски")
    check(ConsumerPool.of({"models": ["gone", "eco", "std"]}, POOLS) == "eco",
          "старый вид со списком — первый id, который пул ещё носит, в порядке списка")
    check(ConsumerPool.of({"models": "all"}, []) == "", "negative: «все пулы» без единого пула — пула нет")
    for old in ({"models": []}, {"models": ["gone"]}, {"models": "ALL"}, {}):
        check(ConsumerPool.of(old, POOLS) == "", f"negative: {old!r} — пула нет")


def test_names():
    print("пул вызывают по имени:")
    models = EntryModels(POOLS)
    check(EntryModels.name({"id": "bare", "name": "  "}) == "bare", "пул без имени зовут по id")
    check(EntryModels.name({"id": "std", "name": " Standart "}) == "Standart", "имя — без пробелов вокруг")
    check(models.taken("standart") and models.taken(" ECONOM ") and not models.taken("Spare"),
          "имя занято без учёта регистра и пробелов; свободное — свободно")
    check(not models.taken("Standart", but="std") and models.taken("Econom", but="std"),
          "negative: своё имя пулу не мешает, чужое — мешает")
    check([p["id"] for p in models.models({"pool": "t2"})] == ["t2"] and models.pick({"pool": "t2"}, "twin")["id"] == "t2",
          "пул под общим с другим пулом именем всё равно находится — канат ведёт по id, не по имени")
    check(models.models({"pool": ""}) == [] and models.models(None) == [] and models.models({"pool": "gone"}) == [],
          "negative: без каната, без маршрута и с пропавшим пулом — ни одной модели")


def test_callers():
    print("кто зовёт пул (окно удаления пула):")
    routes = [{"label": "Hermes", "kind": "consumer", "pool": "eco"}, {"label": "Bot", "kind": "consumer", "models": "all"},
              {"label": "Old", "kind": "consumer", "models": ["eco"]}, {"label": "Zed", "kind": "consumer", "pool": "std"},
              {"label": "old agent", "port": 23001, "pool": "eco"}, {"label": "Dead", "kind": "consumer", "pool": ""}, "junk"]
    names = EntryModels(POOLS)
    check(names.callers(routes, "eco") == ["Hermes", "Old"],
          "пул зовут клиенты с канатом к нему и клиенты старого вида, чей первый пул — он")
    check(names.callers(routes, "std") == ["Bot", "Zed"], "клиент старого вида «все пулы» зовёт первый пул")
    check(names.callers(routes, "gone") == [] and names.callers(routes, "") == [],
          "negative: пула нет или id пуст — никто, а не клиенты без каната")
    check("old agent" not in names.callers(routes, "eco"), "negative: порт агента старого вида — не клиент входа")


for fn in (test_access, test_pool_field, test_pool_of, test_names, test_callers):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("entry models snapshot holds")
