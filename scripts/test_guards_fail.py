#!/usr/bin/env python3
"""Every guard must be able to fail.

Two guards were found in one day that could not. The runner-panel check passed
while the panel it guards was deleted, because the panel's name appears
elsewhere in the same file. The cell-health check passed while a required field
was deleted, because every cell server documents its own payload in a docstring
and the check was grepping the promise instead of the code.

A guard that cannot fail is worse than no guard: it reports green, so the thing
it was written to catch goes uncaught AND unlooked-for. Both of those were found
by hand, by breaking the tree on purpose and watching. This does that on
purpose, every time.

Each guard gets a breakage aimed at the exact thing it exists to catch, applied
to a COPY of the tree. Two assertions per guard: green before the breakage, red
after. The first half matters as much as the second — a guard that fails on
everything would otherwise "pass" its own negative test.

When a breakage no longer applies — the anchor text moved — that is reported as
a failure, not skipped. A silently inapplicable breakage is how this test would
itself become a guard that cannot fail.

One thing IS skipped, loudly and counted separately: a guard whose tooling the
host does not have. check_messages_i18n shells out to node, which the controller
has no reason to install. "Cannot run here" is not "cannot fail", and printing
it as a failure would teach the reader to scroll past a red line that sometimes
means something real.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PASS, FAIL, SKIP = [], [], []


def _missing_tool(output):
    """The name of an executable the guard needed and the host does not have.

    Two shapes, because a guard may either crash on the missing binary or —
    better — notice and stand aside. The second one exits 0, so this has to
    recognise it BEFORE the caller concludes the guard "did not notice" its
    breakage: a clean skip that reads as a silent pass is the failure mode this
    whole test exists to prevent.
    """
    m = re.search(r"No such file or directory: '([^']+)'", output or "")
    if m:
        return m.group(1)
    m = re.search(r"SKIPPED[^\n]*нет (\w+)", output or "")
    return m.group(1) if m else ""

# guard → (args, file to break, find, replace)
# The breakage is chosen to be the failure the guard is FOR, not any old syntax
# error: anything can be broken by deleting a brace.
BREAKAGES = {
    "check_messages_i18n": [
        ([], "static/js/i18n/ru.js",
         '  grpSampling:', '  grpSamplingRENAMED:'),
        # A Russian value left standing in another language's table — neither the
        # en-copy nor the english-phrase check sees it, which is how
        # `computeAuto: "авто"` sat in the Chinese one.
        ([], "static/js/i18n/zh.js",
         'computeAuto: "\u81ea\u52a8",', 'computeAuto: "\u0430\u0432\u0442\u043e",'),
    ],
    "check_i18n_calls": (
        [], "static/js/system-page.js",
        'function bindSettingsBundle() {',
        'function bindSettingsBundle() {\n  const _leak = t("keyThatWasNeverDefined");'),
    "check_tour_i18n": (
        [], "static/js/onboarding-strings.js",
        '  tourCfgFieldsB:', '  tourCfgFieldsBRENAMED:'),
    "testability_names": (
        ["--check"], "static/index.html",
        '<div id="te-offloadPlan"',
        '<div data-t="hook-nobody-registered"></div>\n            <div id="te-offloadPlan"'),
    "check_boot_guard": (
        [], "static/system.html",
        'data-t-state', 'data-t-state-DRIFTED'),
    "check_field_homes": (
        [], "static/js/constants.js",
        '"TEMPERATURE", "TOP_K", "TOP_P", "MIN_P"] }',
        '"TOP_K", "TOP_P", "MIN_P"] }'),
    "check_runner_model_fields": (
        [], "caravan/domain/runner.py",
        '    model_field = "TRANSLATE_MODEL"\n', ''),
    "check_command_mirrors": (
        [], "static/js/llama-edit.js",
        'llama-model-cache}/translate"', 'llama-model-cache}/NOWHERE"'),
    # A field riding through rebuilds must be named in every one: drop the
    # name at one boundary — the guard must name EXACTLY that one.
    "check_static_modules": [
        # The exact defect that shipped: an import list with a doubled comma.
        # `node --check` passes this file; the board dies at parse.
        ([], "static/js/topology-render.js",
         "  submitLlamaStop,\n", "  submitLlamaStop,,\n"),
        # Nothing left to parse — a check that checks nothing must say so.
        ([], "scripts/check_static_modules.py",
         'JS_DIRS = ("static/js", "static/js/i18n")', 'JS_DIRS = ("static/nowhere",)'),
    ],
    "check_board_live_patch": [
        # The live patcher restates a fact the builder already owns — the
        # shape that let a fixed line last exactly one poll tick.
        ([], "static/js/topology-render.js",
         '_liveSet(card, "[data-live-age]", clientAgeText(client));',
         '_liveSet(card, "[data-live-age]", `${client.ageSeconds ?? "?"}s ago`);'),
        # The single source stops building it — nothing left to protect.
        ([], "static/js/topology-activity.js",
         '`${age}s ago`', 't("clientAnsweredAgo", { age })'),
    ],
    "check_carried_fields": [
        # A boundary stops naming a carried field — the classic silent drop.
        ([], "caravan/proxy/config.py",
         '"contextLength": int(route["contextLength"])', '"ctxLen": int(route["ctxLen"])'),
        # A rebuild goes back to building an assignment from the live report
        # alone. This is the fifth boundary the hand-written list never saw.
        ([], "caravan/admin/proxy_ops.py",
         "AgentAssignment.rewired(\n                aid, existing.get(aid),\n"
         "                ProxyRoute.for_port(\"primary\", port, server_ip)).to_dict())",
         "AgentAssignment(\n                aid,\n"
         "                [ProxyRoute.for_port(\"primary\", port, server_ip)]).to_dict())"),
    ],
    "check_proxy_id_namespace": (
        # Building the id moved to caravan/domain/client_proxy.py: three
        # places used to build the same shape, and one of them dropped
        # unnamed fields.
        [], "caravan/domain/client_proxy.py",
        'PROXY_ID_PREFIX = "skynet:proxy:"', 'PROXY_ID_PREFIX = "controller:proxy:"'),
    "check_cell_card_keys": (
        [], "caravan/admin/topology.py",
        '            "savedCommand": (_saved_command(_r_slot, _r_cfg, False)\n'
        '                             if slot_is_command else ""),\n', ''),
    "check_cell_self_capture": (
        [], "cells/whisper_server.py",
        '                    state["downloaded"]', '                    self.state["downloaded"]'),
    "check_cell_python_floor": (
        [], "cells/tts_server.py",
        "from __future__ import annotations\n", ""),
    "check_installer_assets": (
        [], "scripts/install-seamless.sh",
        'install -m 0644 "${SRC}/cell_base.py"      "${HOME}/cell_base.py"\n', ''),
    "check_undefined_names": (
        [], "cells/moonshine_server.py", "import wave\n", ""),
    "check_proxy_response_paths": (
        # The header whose absence parked a listener thread in readline().
        [], "caravan/proxy/handler.py",
        '        self.send_header("Connection", "close")\n        self.end_headers()\n        self.wfile.write(body)',
        '        self.end_headers()\n        self.wfile.write(body)'),
    "check_ci_coverage": [
        # A script exists on disk but the gate never calls it — green on the
        # author's machine, run nowhere else.
        ([], ".github/workflows/ci.yml",
         "          python3 scripts/test_request_body.py\n", ""),
        # A script IS named, but in a second `run:` of a step that already has
        # one. YAML keeps a single key, so the line never runs — and the guard
        # used to see the name and call it covered.
        ([], ".github/workflows/ci.yml",
         "        run: python3 scripts/test_queue_node.py\n",
         "        run: python3 scripts/test_queue_node.py\n"
         "        run: python3 scripts/test_request_body.py\n"),
    ],
    "check_context_window": (
        # A reader of the TRAINED context appears outside the vocabulary — the
        # number that is 131072 where the truth is 60160.
        [], "caravan/admin/monitoring.py",
        'def runtime_api(config):',
        'def runtime_api(config):\n    _trained = (config or {}).get("n_ctx_train")'),
    "check_why_refs": (
        [], "docs/why.md",
        "`caravan/admin/cell_ops.py:105`", "`caravan/admin/gone.py:105`"),
    "check_oop_contract": [
        # A cell forgets a member the base declares abstract: it starts fine and
        # dies on the first request. The guard must name the member.
        ([], "cells/tts_server.py", "    def handle(self, body, headers, path):", "    def handle_work(self, body, headers, path):"),
        # Logic creeps back into a class module as a fat top-level function.
        ([], "static/js/canvas.js", "export const board = new Board();",
         "export const board = new Board();\nfunction strayLogic(a) {\n  if (a) {\n    return 1;\n  }\n  return 2;\n}"),
        # A runner class nobody registered: configs naming it get UnknownRunner.
        ([], "caravan/domain/runner.py", "class UnknownRunner(Runner):", "class GhostRunner(Runner):\n    id = \"ghost\"\n\n\nclass UnknownRunner(Runner):"),
        # The ratchet: a module that is already class-based stays on the list —
        # the list lies and rule 3 stops watching it.
        ([], "scripts/check_oop_contract.py", '    "cables.js": "scripts/test_js_cables.py",',
         '    "cables.js": "scripts/test_js_cables.py",\n    "canvas.js": "scripts/test_js_canvas.py",'),
        # A reason that names a snapshot which does not pin this module.
        ([], "scripts/check_oop_contract.py", '    "cables.js": "scripts/test_js_cables.py",', '    "cables.js": "scripts/test_js_charts.py",'),
        # The recorded decision disappears from the public module reference.
        ([], "docs/frontend.md", "- Kept as functions by decision (OOP rewrite, decision 19, 2026-09-05):", "- Was once kept as-is (OOP rewrite, decision 19, 2026-09-05):"),
    ],
    # The vocabulary itself: a cell that names its job in a word nobody else
    # uses is findable only by whoever already knows its engine.
    "check_cell_kinds": (
        [], "cells/whisper_server.py",
        'kinds = ["asr", "stt.whisper"]', 'kinds = ["stt.whisper"]'),
    "check_cell_health_contract": (
        [], "cells/whisper_server.py",
        '    engine = "faster-whisper"\n', ''),
}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  — ' + str(detail)[:200]}")


def run_guard(tree, guard, args):
    proc = subprocess.run([sys.executable, f"scripts/{guard}.py", *args],
                          cwd=tree, capture_output=True, text=True, timeout=180)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def tracked_files():
    """Tracked files AND untracked ones git is not ignoring.

    `git ls-files` alone misses a file that exists but has never been staged —
    which is the normal state of a tree mid-sync, and of any tree where a new
    guard was just written. The copy then lacked the very script under test and
    the failure read as "the guard is broken" rather than "the guard is not in
    the copy".
    """
    out = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def main():
    files = tracked_files()
    guards = sorted(p.stem for p in (ROOT / "scripts").glob("check_*.py"))
    guards.append("testability_names")

    unlisted = sorted(set(guards) - set(BREAKAGES))
    if unlisted:
        print(f"guard self-test: FAILED — no breakage defined for {unlisted}\n"
              f"  a guard with no negative test is a guard nobody has seen fail.",
              file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="caravan-guards-") as tmp:
        tree = Path(tmp) / "tree"
        for rel in files:
            src = ROOT / rel
            if not src.is_file():
                continue
            dst = tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        for guard in guards:
            # A guard is required to fail two ways, but this harness used to try
            # only one of them — so the second way was never watched fail. A
            # value may now be a LIST of breakages; each is applied to the clean
            # tree in turn.
            spec = BREAKAGES[guard]
            breakages = spec if isinstance(spec, list) else [spec]
            args = breakages[0][0]

            code, out = run_guard(tree, guard, args)
            missing = _missing_tool(out)
            if missing:
                # "cannot run here" is not "cannot fail". check_messages_i18n
                # shells out to node, which the controller does not have; calling
                # that a guard failure would teach the reader to ignore a red
                # line that sometimes means something. Said out loud, and
                # counted apart, so a skip can never pass for a pass.
                SKIP.append(f"{guard} (нет {missing})")
                print(f"  skip {guard}: не запускается здесь — нет {missing}")
                continue
            check(f"{guard}: green on an intact tree", code == 0, out)
            if code != 0:
                continue                      # a red baseline makes the next check meaningless

            for index, (args, rel, find, replace) in enumerate(breakages):
                label = guard if len(breakages) == 1 else f"{guard} [{index + 1}]"
                target = tree / rel
                original = target.read_text(encoding="utf-8")
                if find not in original:
                    check(f"{label}: its breakage still applies", False,
                          f"{rel} no longer contains the anchor {find!r} — update BREAKAGES")
                    continue
                check(f"{label}: its breakage still applies", True)

                target.write_text(original.replace(find, replace, 1), encoding="utf-8")
                code, out = run_guard(tree, guard, args)
                check(f"{label}: RED once broken", code != 0,
                      f"exit 0 — it did not notice. Output: {out[:160]}")
                target.write_text(original, encoding="utf-8")

    tail = f", {len(SKIP)} skipped ({'; '.join(SKIP)})" if SKIP else ""
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed{tail}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
