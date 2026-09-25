#!/usr/bin/env python3
"""Снимок значениями: какие адреса API ушли с одиночным сервером контроллера.

Классический вид страницы правил start-server.sh контроллера как одиночный
сервер: запускал и останавливал его службу (/api/action), делал именованные
снимки и резервные копии, откатывал последнюю (/api/revert, /api/backup,
/api/backup/delete, /api/config/snapshot), показывал сырой скрипт
(/api/raw/start-server) и подписывал клиентов llama в мониторе
(/api/system-monitor/client-label). С шага 6.9 у контроллера своих ячеек
нет, классический вид и эти панели ушли со страницы — и адреса, которые
только они звали, тоже.

Остаются адреса, которые страница зовёт: /api/config — каталог моделей и
умолчания новой ячейки живут в блоке конфига start-server.sh — и починка
user-сервиса на странице System.

Живой такт доски (раз в 1.5 с на каждую открытую вкладку) читал из целого
/api/state одну ветку git — а контроллер ради неё дважды запускал
llama-server, гонял десяток git/systemctl/journalctl и опрашивал отсутствующий
одиночный сервер. Остальное читал классический вид; теперь у такта свой
маленький адрес /api/project-git.

Запуск: python3 scripts/test_retired_routes.py
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import launch, monitoring, routes, status  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


RETIRED = {
    ("POST", "/api/action"), ("POST", "/api/revert"), ("GET", "/api/backup"),
    ("POST", "/api/backup/delete"), ("POST", "/api/config/snapshot"),
    ("GET", "/api/raw/start-server"), ("POST", "/api/system-monitor/client-label"),
}
KEPT = {("POST", "/api/config"), ("POST", "/api/repair/user-service"), ("GET", "/api/state"),
        ("POST", "/api/llama-command-preview"), ("GET", "/api/project-git")}


def table(method):
    return routes.GET_ROUTES if method == "GET" else routes.POST_ROUTES


def main():
    print("адреса одиночного сервера контроллера:")
    still = sorted(f"{m} {p}" for m, p in RETIRED if p in table(m))
    check(still == [], f"negative: ни одного из семи адресов классического вида больше нет (got {still})")
    kept = sorted(f"{m} {p}" for m, p in KEPT if p in table(m))
    check(kept == sorted(f"{m} {p}" for m, p in KEPT),
          f"остаются адреса, которые страница зовёт: конфиг контроллера, починка user-сервиса, состояние, "
          f"превью команды, ветка git для живого такта (got {kept})")
    print("реализации:")
    gone = [name for mod, name in ((status, "do_action"), (launch, "snapshot_config"),
                                   (monitoring, "set_client_label")) if hasattr(mod, name)]
    check(gone == [], f"negative: старт/стоп службы, именованный снимок и подпись клиента ушли вместе с адресами (got {gone})")
    try:
        importlib.import_module("caravan.admin.backups")
        backups_gone = False
    except ModuleNotFoundError:
        backups_gone = True
    check(backups_gone, "negative: модуля резервных копий start-server.sh больше нет")
    check(callable(launch.save_config) and callable(launch._sanitize_snapshot_name),
          "остаются запись конфига контроллера и имя снимка (его берут снимки ячеек на их слотах)")
    print("адрес живого такта доски:")
    heavy = []
    saved = {name: getattr(routes, name) for name in ("project_git_info", "state", "llama_cpp_info", "runtime_api")}
    routes.project_git_info = lambda: {"branch": "main", "head": "abc1234", "dirtyCount": 0, "ok": True, "error": ""}
    for name in ("state", "llama_cpp_info", "runtime_api"):
        setattr(routes, name, lambda *a, _n=name, **k: heavy.append(_n) or {})

    class _H:
        sent = None

        def send_json(self, body, status=200):
            _H.sent = body

    try:
        routes.GET_ROUTES["/api/project-git"](_H(), None)
    finally:
        for name, fn in saved.items():
            setattr(routes, name, fn)
    check(_H.sent == {"branch": "main", "head": "abc1234", "dirtyCount": 0, "ok": True, "error": ""},
          f"/api/project-git отдаёт ровно сведения о ветке проекта (got {_H.sent})")
    check(heavy == [], f"negative: ни целого состояния, ни запуска llama-server, ни опроса одиночного сервера (got {heavy})")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nretired routes OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
