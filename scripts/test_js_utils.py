#!/usr/bin/env python3
"""Snapshot of static/js/utils.js — the basic stateless, i18n-free helpers.

What's pinned by value. `escapeHtml` — all five characters, and non-strings.
`api` — an object body gets serialized (three settings calls once sent
"[object Object]" and restore had been dead on arrival), a string and a Blob
go through as-is, the JSON header, a failure throws `data.error` or
statusText, a 401 outside /api/auth/ and not on /login redirects to /login,
but not on auth paths or on the sign-in page itself. `toast` — text, class, a
3.2s timer. `copyText` — the clipboard, otherwise textarea+execCommand with
an honest false. Memory and boolean formats. `positionTooltip` — clamped to
the window's edges and repositioned under the trigger. `markPageState` — a
single flag on body: state, details capped at 200 characters, aria-busy only
while loading. `inferSpecType` — a draft's type from the FIRST token of the
filename. `fillVersionChipFromHealth` — the version from /health, only where
a git branch hasn't already been written.

The DOM is the `globalThis.__fields` dict, plus minimal body/clipboard stubs.

Run: python3 scripts/test_js_utils.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ""

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.env.JS_ROOT + "/utils.js").href);
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), has: (c) => s.has(c) } };
const mkEl = (props = {}) => ({ textContent: "", title: "", value: "", classList: cls(), style: { props: {}, setProperty(k, v) { this.props[k] = v; } }, dataset: {}, appended: 0, removed: 0, selected: 0, ...props });
globalThis.__timers = []; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push(ms); return 0; };
const F = () => globalThis.__fields;
const rawCalls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body }));
// fetch харнесса записывает body как есть — здесь важно именно ЧТО ушло: строка или объект.
const reset = () => { globalThis.__fields = { toast: mkEl() }; globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__timers.length = 0;
  globalThis.location = { pathname: "/board", search: "", hash: "", href: "http://ctl/board" }; globalThis.window = globalThis;
  document.body = { dataset: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, appendChild(el) { el.appended += 1; } };
  globalThis.__exec = true; document.execCommand = () => globalThis.__exec; document.createElement = () => mkEl({ select() { this.selected += 1; }, remove() { this.removed += 1; } });
  Object.defineProperty(globalThis, "navigator", { value: { language: "en", clipboard: null }, configurable: true }); };
reset();
const out = {};
"""

PINS = [
    ("dollar_is_dictionary_lookup", 'globalThis.__fields.x = { id: "x" };', '[m.$("x").id, m.$("nope")]', '["x",null]', "$(id): элемент словаря или null"),
    ("escape_html_all_five", '', '[m.escapeHtml(`<a href="x" title=\'y\'>&</a>`), m.escapeHtml(5), m.escapeHtml(null), m.escapeHtml("plain")]', '["&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;","5","null","plain"]',
     "экранируются все пять символов; не-строки приводятся к строке (null — «null», не пусто)"),
    ("api_serialises_object_body", 'globalThis.__fetchReply["/x"] = { ok: true };', 'await (async () => { await m.api("/x", { method: "POST", body: { a: 1, b: "two" } }); return rawCalls()[0]; })()', '{"path":"/x","method":"POST","body":"{\\"a\\":1,\\"b\\":\\"two\\"}"}',
     "defect-class: тело-объект уходит строкой JSON (иначе на провод шло «[object Object]» и восстановление настроек было мёртвым)"),
    ("api_passes_string_and_null_as_is", 'globalThis.__fetchReply["/x"] = { ok: true };', 'await (async () => { await m.api("/x", { method: "POST", body: "{\\"raw\\":1}" }); await m.api("/x"); return [rawCalls()[0].body, rawCalls()[1].body, rawCalls()[1].method]; })()', '["{\\"raw\\":1}",null,"GET"]', "строка — как есть, без тела — null и GET"),
    ("api_blob_body_untouched", 'globalThis.__fetchReply["/x"] = { ok: true };', 'await (async () => { const b = new Blob(["z"]); await m.api("/x", { method: "POST", body: b }); return rawCalls()[0].body === b; })()', 'true', "Blob — провод понимает сам, не сериализуется"),
    ("api_error_message_from_body_or_status", '', 'await (async () => { globalThis.__fetchReply["/x"] = { __status: 500, error: "disk full" }; let a = ""; try { await m.api("/x"); } catch (e) { a = e.message; } globalThis.__fetchReply["/x"] = { __status: 503 }; let b = ""; try { await m.api("/x"); } catch (e) { b = e.message; } return [a, b]; })()', '["disk full",""]',
     "отказ: текст из тела, иначе statusText — а он пуст у Response без текста (и у браузера под HTTP/2): отказ без error в теле показывается пустой строкой (as-is)"),
    ("api_401_redirects_to_login", 'globalThis.__fetchReply["/api/x"] = { __status: 401, error: "no session" };', 'await (async () => { let msg = ""; try { await m.api("/api/x"); } catch (e) { msg = e.message; } return [globalThis.location, msg]; })()', '["/login","no session"]', "401 вне авторизации — уход на /login, и ошибка всё равно брошена"),
    ("api_401_no_redirect_on_auth_paths_or_login_page", '', 'await (async () => { globalThis.__fetchReply["/api/auth/login"] = { __status: 401, error: "bad password" }; try { await m.api("/api/auth/login"); } catch {} const a = globalThis.location.pathname; globalThis.location.pathname = "/login"; globalThis.__fetchReply["/api/x"] = { __status: 401, error: "x" }; try { await m.api("/api/x"); } catch {} return [a, globalThis.location.pathname]; })()', '["/board","/login"]',
     "negative: на путях авторизации и на самой странице входа 401 не уводит никуда"),
    ("toast", '', '(() => { m.toast("hi"); return [F().toast.textContent, F().toast.classList.has("show"), [...globalThis.__timers]]; })()', '["hi",true,[3200]]', "тост: текст, класс show, снятие через 3.2 с"),
    ("pill", '', '[m.pill("ok", "good"), m.pill("x")]', '["<span class=\\"pill good\\">ok</span>","<span class=\\"pill \\">x</span>"]', "пилюля с видом; без вида — пустой класс"),
    ("copy_text_clipboard", '', 'await (async () => { let got = ""; Object.defineProperty(globalThis, "navigator", { value: { language: "en", clipboard: { writeText: async (t) => { got = t; } } }, configurable: true }); const ok = await m.copyText("abc"); return [ok, got]; })()', '[true,"abc"]', "буфер обмена доступен — текст ушёл, true"),
    ("copy_text_fallback_and_failure", '', 'await (async () => { const ok = await m.copyText("abc"); const el = globalThis.__created; globalThis.__exec = false; const bad = await m.copyText("abc"); return [ok, bad]; })()', '[true,false]', "без clipboard — textarea+execCommand; execCommand false — честный false"),
    ("copy_text_fallback_cleans_up", '', 'await (async () => { let made = null; document.createElement = () => { made = mkEl({ select() { this.selected += 1; }, remove() { this.removed += 1; } }); return made; }; await m.copyText("abc"); return [made.value, made.appended, made.selected, made.removed, made.style.props["position"] ?? made.style.position]; })()', '["abc",1,1,1,"fixed"]',
     "запасной путь: textarea с текстом добавлена, выделена, удалена; позиционирована вне потока"),
    ("format_bool", '', '["1", "true", "YES", "on", "0", "false", "", null].map(m.formatBool)', '[true,true,true,true,false,false,false,false]', "булево из строк: 1/true/yes/on без учёта регистра"),
    ("format_bytes_mib", '', '[m.formatBytesMiB(1023.6), m.formatBytesMiB("512"), m.formatBytesMiB("x"), m.formatBytesMiB(undefined)]', '["1024 MiB","512 MiB","x",""]', "MiB с округлением; мусор — как есть, пусто — пусто"),
    ("format_memory_mib", '', '[m.formatMemoryMiB(512), m.formatMemoryMiB(1024), m.formatMemoryMiB(1536), m.formatMemoryMiB(10240), m.formatMemoryMiB(24576), m.formatMemoryMiB("n/a")]', '["512 MiB","1.00 GB","1.50 GB","10.0 GB","24.0 GB","n/a"]',
     "память: до 1 GiB — MiB, дальше GB с двумя десятичными, от 10 GiB — с одной"),
    ("position_tooltip_clamps", '', '(() => { const tip = mkEl({ offsetWidth: 320, offsetHeight: 80 }); const trig = { querySelector: (s) => (s === ".tooltip" ? tip : null), getBoundingClientRect: () => ({ left: 10, width: 20, top: 30, bottom: 50 }) }; globalThis.innerWidth = 1000; m.positionTooltip(trig); return [tip.style.props["--tooltip-left"], tip.style.props["--tooltip-top"], tip.classList.has("below")]; })()', '["172px","58px",true]',
     "подсказка у левого края: центр зажат до 12+ширина/2; сверху не помещается — уходит под триггер"),
    ("position_tooltip_above_when_room", '', '(() => { const tip = mkEl({ offsetWidth: 100, offsetHeight: 40 }); const trig = { querySelector: () => tip, getBoundingClientRect: () => ({ left: 400, width: 20, top: 300, bottom: 320 }) }; globalThis.innerWidth = 1000; m.positionTooltip(trig); return [tip.style.props["--tooltip-left"], tip.style.props["--tooltip-top"], tip.classList.has("below")]; })()', '["410px","292px",false]',
     "места сверху хватает — подсказка над триггером по центру"),
    ("position_tooltip_without_tooltip", '', '(() => { m.positionTooltip({ querySelector: () => null }); m.positionTooltip(null); return true; })()', 'true', "negative: без .tooltip или триггера — без исключения"),
    ("mark_page_state", '', '(() => { m.markPageState("loading"); const a = [document.body.dataset.tState, document.body.attrs["aria-busy"]]; m.markPageState("error", "x".repeat(300)); const b = [document.body.dataset.tState, document.body.dataset.tStateDetail.length, document.body.attrs["aria-busy"]]; m.markPageState("ready"); return [...a, ...b, document.body.dataset.tState, "tStateDetail" in document.body.dataset]; })()', '["loading","true","error",200,"false","ready",false]',
     "флаг готовности: loading = aria-busy, error с деталью не длиннее 200, ready снимает деталь"),
    ("mark_page_state_without_body", 'document.body = null;', '(() => { m.markPageState("ready"); return true; })()', 'true', "negative: без body — без исключения"),
    ("infer_spec_type", '', '["/m/dflash-qwen.gguf", "DSPARK_x.gguf", "eagle3.head.gguf", "mtp-draft.gguf", "my-dflash-lookalike.gguf", "plain.gguf", ""].map(m.inferSpecType)', '["draft-dflash","draft-dspark","draft-eagle3","draft-mtp","draft-simple","draft-simple","draft-simple"]',
     "тип черновика по ПЕРВОМУ токену имени файла без учёта регистра; похожее имя дальше по строке не считается; иначе draft-simple"),
    ("version_chip_from_health", 'globalThis.__fetchReply["/health"] = { version: "1.3.306", commit: "abc" }; globalThis.__fields.projectGitBranch = mkEl();', 'await (async () => { m.fillVersionChipFromHealth(); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r)); const el = F().projectGitBranch; return [el.textContent, el.title]; })()', '["v1.3.306","lama-caravan v1.3.306 @ abc"]',
     "чип версии из /health на страницах без state"),
    ("version_chip_not_over_git_label", 'globalThis.__fetchReply["/health"] = { version: "1.3.306" }; globalThis.__fields.projectGitBranch = mkEl({ textContent: "v1 · git: main" });', 'await (async () => { m.fillVersionChipFromHealth(); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r)); return F().projectGitBranch.textContent; })()', '"v1 · git: main"', "negative: где ветка git уже написана, чип не перезаписывается"),
    ("version_chip_without_element_or_version", 'globalThis.__fetchReply["/health"] = {};', 'await (async () => { m.fillVersionChipFromHealth(); const a = rawCalls().length; globalThis.__fields.projectGitBranch = mkEl(); m.fillVersionChipFromHealth(); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r)); return [a, F().projectGitBranch.textContent]; })()', '[0,""]', "negative: без элемента запроса нет; без версии в ответе — пусто"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 22:
        print(f"js utils FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js utils: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Pins don't depend on each other: the same set run in reverse order
    # must give the same values.
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_utils.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            [node, "--import",
             f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js utils FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("utils: экранирование, api, тост, форматы, готовность страницы:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:200]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:200]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js utils OK: настоящий модуль в node, {len(PINS)} пинов utils значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
