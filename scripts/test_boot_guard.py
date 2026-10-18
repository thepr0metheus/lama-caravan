#!/usr/bin/env python3
"""Behaviour of the inline boot guard: what a page that did not boot says, and when it stops saying it.

check_boot_guard.py holds the five copies equal; this runs one of them — the guard of static/index.html, taken out of the
page as it stands — in node, against a stand-in for the window, and pins by value:

  - a script that fails to load names itself (at once for /js/main.js, at the timer for any other);
  - a script that runs and throws, or a promise nobody caught, is named in the banner with its first words (the first of
    several, with how many more) — a page that "did not initialise" with no word of why cost an afternoon, 2026-10-14;
  - a module that cannot be linked fails the page at once while the boot has reported nothing, and does not once it has:
    a SyntaxError of a JSON.parse in a page that is booting is not the end of it;
  - after 20 s still "loading" the banner says what the boot was last waiting for (window.__bootWaiting, boot-step.js),
    or that none was reported;
  - a page that was slow and not dead takes its banner away when it says "ready"; a page that is ready in time never gets one;
  - the banner's Reload reloads.

Run: python3 scripts/test_boot_guard.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import fs from "node:fs";
import vm from "node:vm";
const html = fs.readFileSync(process.env.PAGE, "utf8");
const found = html.match(/<script>\s*\/\* Inline ON PURPOSE[\s\S]*?<\/script>/);
if (!found) { console.log(JSON.stringify({ missing: true })); process.exit(0); }
const code = found[0].replace(/^<script>/, "").replace(/<\/script>$/, "");

// One run of the guard against a stand-in window: `go(w)` plays what happens to the page, then the report.
function run(go) {
  const listeners = {}, timers = [];
  let banner = null, observe = null, reloads = 0;
  const element = (tag) => ({ tagName: tag.toUpperCase(), style: {}, children: [], attrs: {}, text: "",
    setAttribute(k, v) { this.attrs[k] = v; }, appendChild(c) { this.children.push(c); }, remove() { if (banner === this) banner = null; },
    set textContent(v) { this.text = v; }, get textContent() { return this.text; } });
  const body = { dataset: { tState: "loading" }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, appendChild(el) { banner = el; } };
  const w = {
    window: {}, document: { body, createElement: element, querySelector: (sel) => (sel.includes("boot-error") ? banner : null) },
    location: { origin: "http://caravan", reload() { reloads += 1; } },
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    MutationObserver: class { constructor(cb) { observe = cb; } observe() {} },
  };
  w.window = w;
  vm.runInNewContext(code, vm.createContext(w));
  const api = {
    error: (e) => listeners.error.forEach((fn) => fn(e)), reject: (e) => (listeners.unhandledrejection || []).forEach((fn) => fn(e)),
    timer: () => timers.filter((t) => t.ms === 20000).forEach((t) => t.fn()), ready: () => { body.dataset.tState = "ready"; observe && observe(); },
    waiting: (what) => { w.window.__bootWaiting = what; }, change: () => observe && observe(), body, w,
  };
  go(api);
  return { state: body.dataset.tState, detail: body.dataset.tStateDetail || null, banner: banner ? banner.text : null,
    reload: banner && banner.children[0] && banner.children[0].onclick ? (banner.children[0].onclick(), reloads) : null,
    timers: timers.map((t) => t.ms), listeners: Object.keys(listeners).sort() };
}
const err = (name, message) => { const e = new Error(message); e.name = name; return e; };
const win = {};   // a window error: its target is the window, which has no tagName
const out = {
  wiring: run(() => {}),
  quiet: run((g) => g.timer()),
  waiting: run((g) => { g.waiting("/api/state"); g.timer(); }),
  main_lost: run((g) => g.error({ target: { tagName: "SCRIPT", src: "http://caravan/js/main.js" } })),
  other_lost: run((g) => { g.error({ target: { tagName: "LINK", href: "http://caravan/css/x.css" } }); g.error({ target: { tagName: "SCRIPT", src: "http://caravan/js/b.js" } }); g.timer(); }),
  other_lost_early: run((g) => g.error({ target: { tagName: "SCRIPT", src: "http://caravan/js/b.js" } })),
  threw: run((g) => { g.waiting("the page's own setup"); g.error({ target: win, message: "x is not a function", error: err("TypeError", "x is not a function") }); g.timer(); }),
  threw_twice: run((g) => { g.error({ target: win, error: err("TypeError", "first") }); g.error({ target: win, error: err("TypeError", "second") }); g.error({ target: win, message: "third" }); g.timer(); }),
  rejected: run((g) => { g.reject({ reason: err("Error", "api said no") }); g.timer(); }),
  rejected_text: run((g) => { g.reject({ reason: "plain words" }); g.timer(); }),
  link: run((g) => g.error({ target: win, error: err("SyntaxError", "The requested module './usage-stats.js' does not provide an export named 'x'"), message: "ignored" })),
  link_late: run((g) => { g.waiting("/api/state"); g.error({ target: win, error: err("SyntaxError", "Unexpected token < in JSON") }); }),
  link_late_timer: run((g) => { g.waiting("/api/state"); g.error({ target: win, error: err("SyntaxError", "Unexpected token < in JSON") }); g.timer(); }),
  silent_error: run((g) => { g.error({ target: win }); g.timer(); }),
  long: run((g) => { g.error({ target: win, error: err("Error", "y".repeat(400)) }); g.timer(); }),
  early_ready: run((g) => { g.ready(); g.timer(); }),
  healed: run((g) => { g.timer(); g.ready(); }),
  healed_twice: run((g) => { g.timer(); g.ready(); g.timer(); }),
  still_error: run((g) => { g.timer(); g.change(); }),
  still_loading_when_it_changes: run((g) => { g.timer(); g.body.dataset.tState = "loading"; g.change(); }),
  dead_and_thrown: run((g) => { g.error({ target: win, error: err("Error", "boom") }); g.error({ target: { tagName: "SCRIPT", src: "http://caravan/js/a.js" } }); g.timer(); }),
  errored_by_the_app: run((g) => { g.body.dataset.tState = "error"; g.timer(); }),
};
console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if node is None:
        print("boot guard behaviour: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_boot_guard.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        proc = subprocess.run([node, str(probe)], capture_output=True, text=True, cwd=ROOT, env={"PAGE": str(ROOT / "static" / "index.html"), "PATH": "/usr/bin:/bin"}, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("boot guard behaviour: FAILED — the probe did not run")
        print(proc.stderr.strip()[:800])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    if got.get("missing"):
        print("boot guard behaviour: FAILED — no inline guard in static/index.html")
        return 1

    P = "This page did not finish loading — "
    print("a page that is only waiting:")
    check(got["wiring"]["state"] == "loading" and got["wiring"]["banner"] is None and got["wiring"]["timers"] == [20000],
          "nothing happened yet: still loading, no banner, one timer of 20 s")
    check(got["wiring"]["listeners"] == ["error", "unhandledrejection"],
          "it listens to errors (a script that failed to load AND a script that threw: both reach the window's `error`) and to rejections")
    q = got["quiet"]
    check(q["state"] == "error" and q["detail"] == "scripts did not initialise (no step reported)" and q["banner"] == P + "scripts did not initialise (no step reported). ",
          f"20 s, nothing reported: the page is `error`, and the banner says that no step of the boot was reported (got {q['banner']!r})")
    check(got["waiting"]["detail"] == "scripts did not initialise (the boot was waiting for: /api/state)",
          "20 s with a step reported: the banner names what the boot was waiting for")
    check(got["quiet"]["reload"] == 1, "the banner's Reload reloads the page")
    print("a script that did not load:")
    check(got["main_lost"]["state"] == "error" and got["main_lost"]["detail"] == "assets did not load: /js/main.js",
          "main.js lost: the page fails at once and names the file, without the origin")
    check(got["other_lost_early"]["state"] == "loading" and got["other_lost_early"]["banner"] is None,
          "negative: another script lost does not fail the page by itself — the page may boot without it; the timer decides")
    check(got["other_lost"]["detail"] == "assets did not load: /css/x.css, /js/b.js", "at the timer every lost file is named, in the order they were lost")
    print("a script that threw:")
    t = got["threw"]
    check(t["detail"] == "scripts did not initialise: x is not a function (the boot was waiting for: the page's own setup)",
          f"a throw is named with its words and where the boot stood (got {t['detail']!r})")
    check(got["threw_twice"]["detail"] == "scripts did not initialise: first (+2 more) (no step reported)",
          "the first of several is named, with how many more there were (a message-only event counts too)")
    check(got["rejected"]["detail"] == "scripts did not initialise: api said no (no step reported)",
          "a promise nobody caught is named by its reason's message")
    check(got["rejected_text"]["detail"] == "scripts did not initialise: plain words (no step reported)", "a reason that is only words is named by them")
    check(got["silent_error"]["detail"] == "scripts did not initialise (no step reported)",
          "negative: an event that says nothing (no message, no error) adds no words and no \"+ more\"")
    check(got["long"]["detail"].startswith("scripts did not initialise: " + "y" * 160 + " (no step") and "y" * 161 not in got["long"]["detail"],
          "the words are cut at 160 characters: a banner is not a stack trace")
    check(got["dead_and_thrown"]["detail"] == "assets did not load: /js/a.js",
          "a lost file is named before a throw: it is the likelier cause, and the throw may come of it")
    print("a module that cannot be linked:")
    check(got["link"]["state"] == "error" and got["link"]["detail"] == "scripts did not initialise: The requested module './usage-stats.js' does not provide an export named 'x' (no step reported)",
          "nothing of the page ran (no step reported) and a SyntaxError came: the page fails at once, with the words")
    check(got["link_late"]["state"] == "loading" and got["link_late"]["banner"] is None,
          "negative: a SyntaxError once the boot has reported a step (a JSON that was not JSON) is not the end of the page: the timer decides")
    check(got["link_late_timer"]["detail"] == "scripts did not initialise: Unexpected token < in JSON (the boot was waiting for: /api/state)",
          "and if the timer does decide, the words are there")
    print("a page that was slow, not dead:")
    check(got["early_ready"]["state"] == "ready" and got["early_ready"]["banner"] is None,
          "negative: ready before 20 s: the timer finds nothing to say")
    check(got["healed"]["state"] == "ready" and got["healed"]["banner"] is None,
          "ready after the banner: the banner goes (it stayed over a board that worked until 1.3.542)")
    check(got["healed_twice"]["banner"] is None and got["healed_twice"]["state"] == "ready", "the banner does not come back")
    check(got["still_error"]["banner"] is not None and got["still_error"]["state"] == "error",
          "negative: another change of the page's state, to anything but `ready`, keeps the banner (it goes only for `ready`)")
    check(got["still_loading_when_it_changes"]["banner"] is not None,
          "negative: the page back to `loading` keeps the banner too")
    check(got["errored_by_the_app"]["banner"] is None and got["errored_by_the_app"]["state"] == "error",
          "negative: a page the app itself marked `error` says its own thing: no second banner over it")

    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("boot guard behaviour OK: the inline guard of static/index.html, run in node, by value")
    return 0


sys.exit(main())
