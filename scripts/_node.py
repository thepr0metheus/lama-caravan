"""Поиск node — там, где он на самом деле лежит.

Голого `node` недостаточно. На контроллере флота node установлен через nvm и
попадает в PATH только из интерактивного zsh, поэтому любая скриптовая сессия —
в том числе та, в которой идёт деплой или хук — не видит ничего, и вызывающий
честно печатает SKIPPED. Замер: там работает v22.22.2 по пути
~/.nvm/versions/node/<версия>/bin/node, тогда как `command -v node` в bash не
находит ничего, и `bash -lc` тоже, потому что nvm грузится из ~/.zshrc.

Проверка, которая стоит в стороне по НЕВЕРНОЙ причине, читается ровно как
пройденная. Поэтому смотрим ещё и туда, куда ставят менеджеры версий, а если
не нашли — говорим, где искали.
"""
import os
import shutil
from pathlib import Path

# Менеджеры версий, которые кладут node мимо системного PATH.
_VERSION_MANAGER_GLOBS = (
    ".nvm/versions/node/*/bin/node",
    ".fnm/node-versions/*/installation/bin/node",
    ".local/share/fnm/node-versions/*/installation/bin/node",
    ".volta/tools/image/node/*/bin/node",
    ".asdf/installs/nodejs/*/bin/node",
)


def node_search_paths():
    """Куда мы смотрим — в порядке предпочтения. Для сообщения об отказе."""
    places = ["PATH"]
    home = Path.home()
    places += [str(home / g) for g in _VERSION_MANAGER_GLOBS]
    return places


def find_node():
    """Путь к пригодному node, или None."""
    on_path = shutil.which("node")
    if on_path:
        return on_path
    home = Path.home()
    for pattern in _VERSION_MANAGER_GLOBS:
        # Самая свежая версия первой: сортировка по имени каталога версии.
        found = sorted(home.glob(pattern), key=lambda p: p.parts, reverse=True)
        for candidate in found:
            if os.access(candidate, os.X_OK):
                return str(candidate)
    return None
