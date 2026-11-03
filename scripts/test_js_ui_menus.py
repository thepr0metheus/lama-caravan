#!/usr/bin/env python3
"""Value snapshot: the parts' "⋯" menus come alive (static/js/ui-menus.js, UiMenus, 1.3.630).

A menu opens by its button and closes by its button again, by Escape (the focus back on its button, and that Escape is the
menu's — no listener after it sees it), by a click outside it, and when one of its items is chosen; one menu is open at a time.
Pinned on a document of stand-ins, each claim with its negative: a click inside the open list that is no item keeps it open,
Escape with nothing open is nobody's, binding twice listens once. And the cell window stands aside for an open menu
(card-fold.js, FoldPeek.LAYERS): Escape closes the menu over a window before the window.

Run: python3 scripts/test_js_ui_menus.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r'''
import "./_js_globals.mjs";
const { UiMenus } = await import("../static/js/ui-menus.js");
const { FoldPeek } = await import("../static/js/card-fold.js");
const out = {};
// A node of a stand-in document: a selector is one class (".x") or one attribute ("[x]"); closest() walks up to the document.
class El {
  constructor(name, { cls = [], attrs = {}, parent = null } = {}) {
    this.name = name; this.cls = cls; this.attrs = { ...attrs }; this.parent = parent; this.kids = []; this.hidden = false; this.focused = false;
    if (parent) parent.kids.push(this);
  }
  matches(sel) {
    const one = sel.trim();
    if (one.startsWith(".")) return this.cls.includes(one.slice(1).split(":")[0]);
    if (one.startsWith("[")) return Object.prototype.hasOwnProperty.call(this.attrs, one.slice(1, -1));
    return false;
  }
  closest(sel) { for (let n = this; n; n = n.parent) if (n.matches?.(sel)) return n; return null; }
  all() { return [this, ...this.kids.flatMap((k) => k.all())]; }
  querySelector(sel) { return this.all().slice(1).find((n) => n.matches(sel)) || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  focus() { this.focused = true; }
  getClientRects() { return this.hidden ? [] : [{}]; }
}
const listeners = {};
const page = new El("page");
const doc = {
  addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
  querySelectorAll: (sel) => page.all().filter((n) => (sel.includes(":not([hidden])") ? n.matches(".ui-menu-list") && !n.hidden
    : sel.split(",").some((s) => n.matches(s)))),
};
const menu = (id) => {
  const box = new El(`menu-${id}`, { cls: ["ui-menu"], parent: page });
  const toggle = new El(`toggle-${id}`, { cls: ["ui-btn"], attrs: { "data-ui-menu-toggle": "", "aria-expanded": "false" }, parent: box });
  const list = new El(`list-${id}`, { cls: ["ui-menu-list"], parent: box });
  list.hidden = true;
  const item = new El(`item-${id}`, { cls: ["ui-menu-item"], parent: list });
  const gap = new El(`gap-${id}`, { cls: ["ui-menu-sep"], parent: list });
  return { box, toggle, list, item, gap };
};
const a = menu("a"), b = menu("b");
const outside = new El("outside", { parent: page });
const menus = new UiMenus(doc);
menus.bind();
menus.bind();
out.listeners = { click: (listeners.click || []).length, keydown: (listeners.keydown || []).length };
const click = (target) => listeners.click.forEach((fn) => fn({ target }));
const key = (k) => { const e = { key: k, stopped: false, stopImmediatePropagation() { this.stopped = true; } }; listeners.keydown.forEach((fn) => fn(e)); return e.stopped; };
const state = () => ({ a: !a.list.hidden, aExpanded: a.toggle.attrs["aria-expanded"], b: !b.list.hidden, bExpanded: b.toggle.attrs["aria-expanded"] });

click(a.toggle); out.open = state();
click(a.toggle); out.again = state();
click(a.toggle); click(b.toggle); out.second = state();
click(b.gap); out.insideGap = state();
click(b.item); out.item = state();
click(a.toggle); click(outside); out.outside = state();
click(a.toggle); a.toggle.focused = false;
out.escape = { stopped: key("Escape"), ...state(), focused: a.toggle.focused };
out.escapeNothing = key("Escape");
out.otherKey = (() => { click(a.toggle); const stopped = key("Enter"); return { stopped, ...state() }; })();
click(outside);
// The cell window stands aside for an open menu: FoldPeek.layerAbove sees it.
const wdoc = { querySelectorAll: (sel) => page.all().filter((n) => sel.split(",").some((s) => n.matches(s.trim()))) };
out.layerClosed = FoldPeek.layerAbove(wdoc);
click(a.toggle);
out.layerOpen = FoldPeek.layerAbove(wdoc);
console.log(JSON.stringify(out));
'''


def main():
    node = find_node()
    if node is None:
        print("js ui-menus: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_ui_menus.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "i18n,topology-render,cables,canvas,polling,state",
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js ui-menus: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:2000])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])

    check(got["listeners"] == {"click": 1, "keydown": 1}, "привязан дважды — слушает один раз: один щелчок, одна клавиша")
    check(got["open"] == {"a": True, "aExpanded": "true", "b": False, "bExpanded": "false"},
          "кнопка «⋯» открывает свой список и говорит об этом (aria-expanded)")
    check(got["again"] == {"a": False, "aExpanded": "false", "b": False, "bExpanded": "false"}, "та же кнопка ещё раз — закрывает")
    check(got["second"] == {"a": False, "aExpanded": "false", "b": True, "bExpanded": "true"},
          "открыто одно меню за раз: второе закрывает первое")
    check(got["insideGap"]["b"] is True, "negative: щелчок внутри открытого списка мимо пункта (черта) — список остаётся")
    check(got["item"]["b"] is False, "пункт выбран — меню отходит в сторону (сам пункт слушает доска)")
    check(got["outside"]["a"] is False, "щелчок мимо меню — закрывает")
    check(got["escape"] == {"stopped": True, "a": False, "aExpanded": "false", "b": False, "bExpanded": "false", "focused": True},
          "Escape закрывает меню, возвращает фокус на его кнопку, и дальше этот Escape не идёт")
    check(got["escapeNothing"] is False, "negative: Escape, когда ничего не открыто, — не меню: идёт дальше (окну, диалогу)")
    check(got["otherKey"] == {"stopped": False, "a": True, "aExpanded": "true", "b": False, "bExpanded": "false"},
          "negative: другая клавиша меню не трогает")
    check(got["layerClosed"] is False and got["layerOpen"] is True,
          "открытое меню — слой над окном ячейки (FoldPeek.LAYERS): Escape сначала закрывает меню, окно остаётся; закрытое — не слой")

    print()
    if _fail:
        print(f"js ui-menus FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js ui-menus OK: открыть, закрыть кнопкой, Escape, щелчком мимо и пунктом; одно открыто; слой над окном")
    return 0


if __name__ == "__main__":
    sys.exit(main())
