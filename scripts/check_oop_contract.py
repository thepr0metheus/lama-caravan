#!/usr/bin/env python3
"""Guard of the OOP contract: every cell server subclasses CellServer and defines
each member the base leaves abstract; every runner subclasses Runner and sits in
the registry; in static/js the logic lives in classes, except for the modules on
an explicit whitelist.

Why a guard and not an agreement: phases 1-8 rewrote the backend and the kanban
into classes, and without a rule the next cell server gets a forty-line `main()`
with `if kind == ...` again, and the next JS module a thousand lines of
functions. The rule is checked the way it was written: by reading the code, not
the docstrings.

Rules.
1. Python. `cells/*_server.py` (and any `*_server.py` under caravan/) holds a
   class based on `CellServer`; the "abstract" members of the base are those
   whose body is `raise NotImplementedError`, and the subclass must define each
   of them (a method, a property or a class attribute — or an intermediate
   parent in the same file). A forgotten member is a cell that dies on its first
   request, not at start-up.
2. Python. In caravan/domain/runner.py every `*Runner` class except the base
   inherits Runner; every REGISTRY element is a call of such a class; every such
   class (except the UnknownRunner stand-in) is in REGISTRY.
3. JS. static/js modules outside the FUNCTION_MODULES whitelist are class
   modules: at least one `class`, and no top-level function longer than
   FACE_LINES lines (a face is a one-liner delegating to a class). The whitelist
   holds the modules left as functions, each with a REASON: a phase-7 snapshot
   (the file exists and imports the module) or a "not building" decision in the
   journal (naming the module). The list is a ratchet: a module that already
   satisfies rule 3 must leave it, or the rule stops watching it and the list
   lies. An entry naming a missing file is an error.

Fails on: a missing abstract member; a runner outside the registry or not a
subclass; a module outside the list without classes or with logic in functions;
a whitelist entry whose reason does not hold; a class module still on the list.
Negative self-test: scripts/test_guards_fail.py.

Run: python3 scripts/check_oop_contract.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELL_BASE = ROOT / "cells" / "cell_base.py"
RUNNER_MODULE = ROOT / "caravan" / "domain" / "runner.py"
JS_DIR = ROOT / "static" / "js"
FACE_LINES = 3

# Modules left as functions, each with its REASON: the phase-7 snapshot that pins
# its behaviour, or the "not building" decision recorded in the journal. Reasons
# are checked: a snapshot must exist and import the module, a decision must be in
# docs/oop-rewrite.md with the module's name. The list is a ratchet: a module that
# has become class-based (a class, functions <= FACE_LINES lines) must leave it,
# or the list lies and rule 3 no longer sees it.
FUNCTION_MODULES = {
    "cables.js": "scripts/test_js_cables.py",
    "charts.js": "scripts/test_js_charts.py",
    "cloud.js": "scripts/test_js_cloud.py",
    "command-preview.js": "scripts/test_js_command_preview.py",
    "config-locator.js": "scripts/test_js_config_locator.py",
    "constants.js": "scripts/test_js_data_modules.py",
    "dialog-llamas.js": "docs/oop-rewrite.md: решение «не строю» №19",
    "dialogs.js": "scripts/test_js_dialogs.py",
    "favorites.js": "scripts/test_js_favorites.py",
    "form.js": "scripts/test_js_form.py",
    "history.js": "scripts/test_js_history.py",
    "i18n-data.js": "scripts/test_js_data_modules.py",
    "i18n.js": "scripts/test_js_i18n.py",
    "llama-edit.js": "scripts/test_js_llama_edit.py",
    "main.js": "scripts/test_js_main.py",
    "memory.js": "scripts/test_js_memory.py",
    "model-meta.js": "scripts/test_js_model_meta.py",
    "models-page.js": "scripts/test_js_models_page.py",
    "onboarding-strings.js": "scripts/test_js_onboarding_tours.py",
    "onboarding-tours.js": "scripts/test_js_onboarding_tours.py",
    "onboarding.js": "scripts/test_js_onboarding.py",
    "polling.js": "scripts/test_js_polling.py",
    "remote-cells.js": "scripts/test_js_remote_cells.py",
    "routers.js": "scripts/test_js_routers.py",
    "state.js": "scripts/test_js_data_modules.py",
    "system-page.js": "scripts/test_js_system_page.py",
    "system-panels.js": "scripts/test_js_system_panels.py",
    "topology-activity.js": "scripts/test_js_topology_activity.py",
    "topology-dnd.js": "scripts/test_js_topology_dnd.py",
    "topology-modals.js": "scripts/test_js_topology_modals.py",
    "topology-nodes.js": "scripts/test_js_topology_nodes.py",
    "topology-proxies.js": "scripts/test_js_client_proxies.py",
    "topology-render.js": "scripts/test_js_topology_render.py",
    "usage-stats.js": "scripts/test_js_usage_stats.py",
    "utils.js": "scripts/test_js_utils.py",
}

problems = []


def _raises_not_implemented(fn):
    body = [n for n in fn.body if not isinstance(n, ast.Expr) or not isinstance(getattr(n, "value", None), ast.Constant)]
    return len(body) == 1 and isinstance(body[0], ast.Raise) and (
        (isinstance(body[0].exc, ast.Name) and body[0].exc.id == "NotImplementedError")
        or (isinstance(body[0].exc, ast.Call) and getattr(body[0].exc.func, "id", "") == "NotImplementedError"))


def _class_defs(tree):
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


def _base_names(cls):
    out = []
    for b in cls.bases:
        out.append(b.id if isinstance(b, ast.Name) else getattr(b, "attr", ""))
    return out


def _members(cls):
    """Names the class defines itself: methods, properties and class attributes —
    `engine = "whisper"` satisfies the abstract property `engine` as well as a method."""
    names = set()
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


def check_cells():
    if not CELL_BASE.exists():
        problems.append("cells/cell_base.py не найден — контракт ячеек проверять не по чему")
        return
    base_tree = ast.parse(CELL_BASE.read_text(encoding="utf-8"))
    base = _class_defs(base_tree).get("CellServer")
    if base is None:
        problems.append("cells/cell_base.py: класса CellServer нет")
        return
    required = sorted(n.name for n in base.body
                      if isinstance(n, ast.FunctionDef) and _raises_not_implemented(n))
    if not required:
        problems.append("CellServer: ни одного члена с `raise NotImplementedError` — контракт пуст")
        return
    servers = sorted(list(ROOT.glob("cells/*_server.py")) + list(ROOT.glob("caravan/**/*_server.py")))
    if not servers:
        problems.append("ни одного *_server.py — охранять нечего")
    for path in servers:
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = _class_defs(tree)
        def inherits(cls, seen=()):
            for b in _base_names(cls):
                if b == "CellServer":
                    return True
                if b in classes and b not in seen and inherits(classes[b], seen + (b,)):
                    return True
            return False
        cells = [c for c in classes.values() if inherits(c)]
        if not cells:
            problems.append(f"{rel}: нет класса-подкласса CellServer")
            continue
        for cls in cells:
            have = set(_members(cls))
            # an intermediate parent in the same file counts too
            for b in _base_names(cls):
                if b in classes:
                    have |= _members(classes[b])
            missing = [m for m in required if m not in have]
            if missing:
                problems.append(f"{rel}: {cls.name} не определяет {', '.join(missing)} — "
                                f"ячейка упадёт на первом запросе, а не при старте")
    return required, [s.relative_to(ROOT).as_posix() for s in servers]


def check_runners():
    if not RUNNER_MODULE.exists():
        problems.append("caravan/domain/runner.py не найден")
        return 0
    tree = ast.parse(RUNNER_MODULE.read_text(encoding="utf-8"))
    classes = _class_defs(tree)
    if "Runner" not in classes:
        problems.append("runner.py: базового класса Runner нет")
        return 0
    runners = {n: c for n, c in classes.items() if n.endswith("Runner") and n != "Runner"}
    for name, cls in runners.items():
        bases = _base_names(cls)
        if not any(b == "Runner" or b in runners for b in bases):
            problems.append(f"runner.py: {name} не наследует Runner (базы: {bases or 'нет'})")
    registry = None
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "REGISTRY" for t in n.targets):
            registry = n.value
    if registry is None or not isinstance(registry, (ast.Tuple, ast.List)):
        problems.append("runner.py: REGISTRY не найден или не кортеж")
        return len(runners)
    listed = []
    for el in registry.elts:
        if isinstance(el, ast.Call) and isinstance(el.func, ast.Name):
            listed.append(el.func.id)
            if el.func.id not in runners:
                problems.append(f"runner.py: в REGISTRY стоит {el.func.id}, а это не класс *Runner из этого файла")
        else:
            problems.append("runner.py: элемент REGISTRY — не вызов класса раннера")
    for name in runners:
        if name == "UnknownRunner":
            continue
        if name not in listed:
            problems.append(f"runner.py: {name} объявлен, но в REGISTRY его нет — конфиг с таким RUNNER получит UnknownRunner")
    return len(runners)


_FN_RE = re.compile(r"^(?:export )?(?:async )?function\s+(\w+)\s*\(|^(?:export )?const\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>\s*\{|^(?:export )?const\s+(\w+)\s*=\s*(?:async\s+)?function")


def _top_level_functions(text):
    """(name, line count) for every top-level function; a body ends at a `}` in column 0."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        m = _FN_RE.match(line)
        if not m:
            continue
        name = next(g for g in m.groups() if g)
        if line.rstrip().endswith("}") or line.rstrip().endswith("};"):
            out.append((name, 1))
            continue
        j = i
        while j < len(lines) and lines[j].rstrip() not in ("}", "};"):
            j += 1
        out.append((name, j - i + 1))
    return out


def _is_class_module(text):
    """Rule 3 for one module: a class exists and the top-level functions are faces."""
    if not re.search(r"^(?:export )?class \w+", text, re.M):
        return False, "классов нет"
    fat = [(n, k) for n, k in _top_level_functions(text) if k > FACE_LINES]
    if fat:
        return False, "; ".join(f"функция {n} на {k} строк вне класса" for n, k in fat)
    return True, ""


def _reason_holds(name, reason):
    """A whitelist reason is verified, not taken on trust."""
    if reason.startswith("scripts/test_js_"):
        path = ROOT / reason
        if not path.exists():
            return f"снимок {reason} не существует"
        if f'"/{name}"' not in path.read_text(encoding="utf-8"):
            return f"снимок {reason} не импортирует {name}"
        return ""
    if reason.startswith("docs/"):
        doc = ROOT / reason.split(":")[0]
        if not doc.exists():
            return f"{doc.name} не существует"
        text = doc.read_text(encoding="utf-8")
        stem = name[:-3]
        if stem not in text or "не строю" not in text:
            return f"в {doc.name} нет решения «не строю» про {stem}"
        return ""
    return f"причина «{reason}» — ни снимок, ни решение в журнале"


def check_js():
    if not JS_DIR.is_dir():
        problems.append("static/js не найден")
        return 0
    modules = sorted(p.name for p in JS_DIR.glob("*.js"))
    if not modules:
        problems.append("static/js пуст — охранять нечего")
        return 0
    for stale in sorted(set(FUNCTION_MODULES) - set(modules)):
        problems.append(f"белый список называет static/js/{stale}, которого нет — список врёт")
    for name, reason in sorted(FUNCTION_MODULES.items()):
        if name not in modules:
            continue
        why_not = _reason_holds(name, str(reason or ""))
        if why_not:
            problems.append(f"static/js/{name}: запись белого списка не подтверждается — {why_not}")
        ok, _ = _is_class_module((JS_DIR / name).read_text(encoding="utf-8"))
        if ok:
            problems.append(f"static/js/{name}: уже классовый модуль — уберите его из FUNCTION_MODULES, "
                            f"иначе правило 3 его больше не охраняет")
    class_modules = [m for m in modules if m not in FUNCTION_MODULES]
    if not class_modules:
        problems.append("ни одного классового модуля вне белого списка — правило 3 ничего не проверяет")
    for name in class_modules:
        ok, why = _is_class_module((JS_DIR / name).read_text(encoding="utf-8"))
        if not ok:
            problems.append(f"static/js/{name}: вне белого списка, а {why} — либо классы, "
                            f"либо запись в FUNCTION_MODULES с причиной (снимок или решение)")
    return len(class_modules)


def main():
    cells = check_cells() or ([], [])
    n_runners = check_runners()
    n_js = check_js()
    if problems:
        print("oop contract: FAILED")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"oop contract: OK — {len(cells[1])} серверов ячеек с членами {', '.join(cells[0])}; "
          f"{n_runners} раннеров в реестре; {n_js} классовых JS-модулей, {len(FUNCTION_MODULES)} в белом списке")
    return 0


if __name__ == "__main__":
    sys.exit(main())
