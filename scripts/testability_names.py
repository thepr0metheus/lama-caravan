#!/usr/bin/env python3
"""Every `data-t` value the UI can emit — the list docs/testability.md publishes.

WHY THIS IS NOT A GREP. Most hooks are literals in the markup and a grep finds
them. Some are composed at runtime and a grep finds NOTHING:

    trigger.dataset.t = `${selectEl.dataset.t}-picker`   → cell-remote-model-picker
    `data-t="${tHook}"`                                  → cell-remote-compute
    mbadge(type, text, title, "cell-source-stale")       → cell-source-stale

Counting only the literals undercounts by eleven, and a reader who greps, gets a
smaller number than the doc, and concludes the doc has drifted will "fix" it in
the wrong direction. So the composed names are declared here, next to the rule
that composes them, and the doc's count comes from this script.

    python3 scripts/testability_names.py            # the list
    python3 scripts/testability_names.py --check    # non-zero if the doc disagrees
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("static", "rust/crates/admin/src/web")

# Hooks assembled at runtime, with the site that assembles each. Add here when
# you add one — the guard below is what will otherwise catch you.
COMPOSED = {
    # static/js/model-disk.js — the machine page's model disk (2026-11-03): a row's and a button's data-t handed to the part by name
    "node-cache-dir-remove": "model-disk.js: removeButton(\"node-cache-dir-remove\", …)",
    "node-cache-work": "model-disk.js: row({ testName: \"node-cache-work\" })",
    "node-cache-work-set": "model-disk.js: button(…, \"node-cache-work-set\", …)",
    "node-cache-work-remove": "model-disk.js: removeButton(\"node-cache-work-remove\", …)",
    # static/js/form.js — the visible widget above a hidden native <select>
    "cell-remote-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-remote-vllm-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-remote-whisper-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-remote-moonshine-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    # static/js/llama-edit.js — one per runner, carrying data-t-id
    "cell-remote-runner-tab": "llama-edit.js: data-t on each runner tab",
    # static/js/memory.js — the CPU/GPU/auto tiles, data-t-id cpu|gpu|auto
    "cell-remote-compute": "memory.js: tHook",
    # static/js/usage-stats.js — a pool step's two level handles on a limit bar: data-t="pool-${level}"
    "pool-switch": "usage-stats.js: subscriptionLimitRowHtml, handle(level)",
    "pool-stop": "usage-stats.js: subscriptionLimitRowHtml, handle(level)",
    # static/js/card-rows.js — a folded card's control: 📌 keeps it open, ▴ folds it back
    "fold-pin": "card-rows.js: FoldSlot.control() by mode",
    "fold-unpin": "card-rows.js: FoldSlot.control() by mode",
    # static/js/cell-memory.js — the two badges of the memory a cell holds, data-t="${CellMemory.HOOKS[which]}" (ram | gpu), data-t-state held|expected|none|unknown|idle
    "cell-ram": "cell-memory.js: CellMemory.badge",
    "cell-gpu": "cell-memory.js: CellMemory.badge",
    # static/js/pool-board.js — the input dot of a card, the handle of a cable pulled from the right: data-t="${hook}" of PoolBoard.PULL
    "pb-pull-model": "pool-board.js: PoolBoard.pullHtml",
    # static/js/card-rows.js — a cell line's switch: its hook says what flipping it does
    "cell-row-start": "card-rows.js: CellRow.lead() by the switch's state",
    "cell-row-stop": "card-rows.js: CellRow.lead() by the switch's state",
    # static/js/split-mode.js — split across cards, data-t-id layer|row|tensor; under it the chosen mode's three lines
    # (data-t-id = the mode) and the fold that compares all three: SplitMode.HOOKS
    "cell-remote-split": "memory.js: SplitMode.html(hook)",
    "cell-remote-split-about": "split-mode.js: SplitMode.HOOKS.about",
    "cell-remote-split-compare": "split-mode.js: SplitMode.HOOKS.compare",
    # static/js/machine-head.js — the parts of the side column of a machine's page (1.3.636): MachineSide.HOOKS.
    "machine-side-engines": "machine-head.js: MachineSide.HOOKS.engines",
    "machine-side-disk": "machine-head.js: MachineSide.HOOKS.disk",
    "machine-side-incidents": "machine-head.js: MachineSide.HOOKS.incidents",
    "machine-side-activity": "machine-head.js: MachineSide.HOOKS.activity",
    # static/js/add-model.js — the fields of the wizard's third step, each drawn by one helper (segs, switchHtml, textHtml) that
    # takes its hook (1.3.638); the star of a row of the cell window's editor of the settings (cell-settings.js).
    "add-model-ctx": "add-model.js: ctxHtml → segs(..., \"add-model-ctx\")",
    "add-model-parallel": "add-model.js: parallelHtml → segs",
    "add-model-cache": "add-model.js: cacheHtml → segs",
    "add-model-where": "add-model.js: whereHtml → segs",
    "add-model-flash": "add-model.js: mainHtml → switchHtml",
    "add-model-thinking": "add-model.js: mainHtml → switchHtml",
    "add-model-temp": "add-model.js: mainHtml → textHtml",
    "add-model-name": "add-model.js: mainHtml → textHtml",
    "cell-settings-star": "cell-settings.js: CellSettings.HOOKS.star",
    "models-job-filter": "model-facts.js: ModelFacts.HOOKS.job",
    "models-window-filter": "model-facts.js: ModelFacts.HOOKS.window",
    "models-row-jobs": "model-facts.js: ModelFacts.HOOKS.jobs",
    "models-row-window": "model-facts.js: ModelFacts.HOOKS.ctx",
    # static/js/placement.js — where the model lives (it replaced the auto/all/manual tiles and their slider): PlacementPanel.HOOKS.
    # data-t-id = a card's index (card, limit, all, none) or cards|ram (kv); data-t-state on the panel fitted|held|tensor|unknown,
    # on the verdict fits|spill|kvRam|ramShort|over|unknown, on the held note off|layers|split|moe
    "cell-remote-placement": "placement.js: PlacementPanel.HOOKS.panel",
    "cell-remote-placement-card": "placement.js: PlacementPanel.HOOKS.card",
    "cell-remote-placement-limit": "placement.js: PlacementPanel.HOOKS.limit",
    "cell-remote-placement-all": "placement.js: PlacementPanel.HOOKS.all",
    "cell-remote-placement-none": "placement.js: PlacementPanel.HOOKS.none",
    "cell-remote-placement-ram": "placement.js: PlacementPanel.HOOKS.ram",
    "cell-remote-placement-kv": "placement.js: PlacementPanel.HOOKS.kv",
    "cell-remote-placement-verdict": "placement.js: PlacementPanel.HOOKS.verdict",
    "cell-remote-placement-held": "placement.js: PlacementPanel.HOOKS.held",
    "cell-remote-placement-fit": "placement.js: PlacementPanel.HOOKS.fit",
    "cell-remote-placement-threads": "placement.js: PlacementPanel.HOOKS.threads (the RAM lane's «Use N»)",
    # static/js/cell-window.js — a cell's window, variant Г (2026-10-24): CellWindow.HOOKS, data-t-id = the cell's key
    # (host:port), a tab, panel, item, tile or button adds ":<its id>"; the band and its main button say their state.
    "cell-window": "cell-window.js: CellWindow.HOOKS.window (the dialog)",
    "cell-window-close": "cell-window.js: CellWindow.HOOKS.close (the ✕)",
    "cell-window-via": "cell-window.js: CellWindow.HOOKS.via (an engine cell's 127.0.0.1 port)",
    "cell-window-band": "cell-window.js: CellWindow.HOOKS.band, data-t-state = the cell's state",
    "cell-window-action": "cell-window.js: CellWindow.HOOKS.action, data-t-state start|stop|configure|busy|shut",
    "cell-window-tab": "cell-window.js: CellWindow.HOOKS.tab, data-t-id key:overview|memory|settings|log|talk",
    "cell-window-panel": "cell-window.js: CellWindow.HOOKS.panel, data-t-id key:<tab>",
    "cell-window-more": "cell-window.js: CellWindow.HOOKS.more (the ⋯ button)",
    "cell-window-menu": "cell-window.js: CellWindow.HOOKS.menu (the ⋯ menu)",
    "cell-window-item": "cell-window.js: CellWindow.HOOKS.item, data-t-id key:boot|copy|port|detail|delete",
    "cell-window-copy": "cell-window.js: CellWindow.HOOKS.copy (the address that copies itself)",
    "cell-window-tile": "cell-window.js: CellWindow.HOOKS.tile, data-t-id key:speed|context|window|gpu|ram",
    "cell-window-button": "cell-window.js: CellWindow.HOOKS.button, data-t-id key:placement|configure|port|detail",
    # static/js/cell-log.js — the server's own log in a cell window's Log tab (1.3.623): CellLog.HOOKS, data-t-id = the cell's
    # key; the section's data-t-state idle|loading|ok|error.
    "cell-log": "cell-log.js: CellLog.HOOKS.view (the section)",
    "cell-log-show": "cell-log.js: CellLog.HOOKS.show (read the log, or read it again after a refusal)",
    "cell-log-refresh": "cell-log.js: CellLog.HOOKS.refresh (read the chosen run again)",
    "cell-log-run": "cell-log.js: CellLog.HOOKS.run (the choice of a run)",
    "cell-log-lines": "cell-log.js: CellLog.HOOKS.lines (the lines)",
    # static/js/cell-chat.js — the text chat of a chat cell in its window's Talk tab (1.3.624): CellChat.HOOKS, data-t-id = the
    # cell's key; the section's data-t-state idle|busy|off, a message's user|answer|error.
    "cell-chat": "cell-chat.js: CellChat.HOOKS.view (the section)",
    "cell-chat-draft": "cell-chat.js: CellChat.HOOKS.draft (the message box)",
    "cell-chat-send": "cell-chat.js: CellChat.HOOKS.send",
    "cell-chat-clear": "cell-chat.js: CellChat.HOOKS.clear",
    "cell-chat-turn": "cell-chat.js: CellChat.HOOKS.turn (a message)",
    # static/js/cell-settings.js — a llama.cpp cell's settings edited in its window (1.3.625): CellSettings.HOOKS, data-t-id = the
    # cell's key, a group, a field or the Memory tab's open button adds ":<its id>"; the editor's data-t-state idle|open, the
    # map's idle|open|none, a field's set|unset|changed, the foot's dirty|busy.
    "cell-settings": "cell-settings.js: CellSettings.HOOKS.view (the Settings tab's editor)",
    "cell-settings-open": "cell-settings.js: CellSettings.HOOKS.open (fill the form for this cell here)",
    "cell-settings-query": "cell-settings.js: CellSettings.HOOKS.query (the search)",
    "cell-settings-only": "cell-settings.js: CellSettings.HOOKS.only (only those set)",
    "cell-settings-group": "cell-settings.js: CellSettings.HOOKS.group, data-t-id key:<the dialog's tab>",
    "cell-settings-field": "cell-settings.js: CellSettings.HOOKS.field, data-t-id key:<FIELD>",
    "cell-window-dirty": "cell-settings.js: CellSettings.HOOKS.dirty (the foot: what is not applied)",
    "cell-window-apply": "cell-settings.js: CellSettings.HOOKS.apply",
    "cell-window-discard": "cell-settings.js: CellSettings.HOOKS.discard",
    "cell-window-place": "cell-settings.js: CellSettings.HOOKS.place (the Memory tab's map)",
    # static/js/topology-nodes.js — passed to mbadge() as its testId argument
    "cell-source-stale": "topology-nodes.js: mbadge(..., 'cell-source-stale')",
    "cell-crashed": "topology-nodes.js: mbadge(..., 'cell-crashed')",
    "cell-model-stale": "topology-nodes.js: mbadge(..., 'cell-model-stale')",
    "cell-model-disk-newer": "topology-nodes.js: mbadge(..., 'cell-model-disk-newer')",
    "cell-model-in-library": "topology-nodes.js: mbadge(..., 'cell-model-in-library')",
    # static/js/form.js — ⇪ on a file's row in the model picker: the card
    # names the file's ROLE, and which file exactly has diverged is only
    # visible here.
    "model-file-stale": "form.js: mbadge(..., 'model-file-stale') on the picker row",
    # static/js/form.js — 📚 on the row of a file only a library holds
    "model-in-library": "form.js: mbadge(..., 'model-in-library') on the picker row",
    # static/js/model-moves.js — the short list of libraries a ⇢ opens, set
    # through dataset.t on the element it builds
    "models-move-menu": "model-moves.js: showMenu sets menu.dataset.t",
    # static/js/hf-page.js — the page's question dialog, set through
    # setAttribute on the overlay it builds
    "hf-confirm": "hf-page.js: HfDialog.confirm sets data-t on the overlay",
    # static/js/form.js — one per config tab, set on the constructed button
    "cell-config-tab": "form.js: renderFields sets data-t on each tab button",
    "agent-proxy-bind": "topology-activity.js: the clickable primary port chip",
    "agent-bind-menu": "topology-activity.js: the proxy-port picker it opens",
    "cell-remote-translate-model": "index.html: NLLB model field (remote form)",
    "cell-remote-translate-src": "index.html: NLLB source language (remote form)",
    "cell-remote-translate-tgt": "index.html: NLLB target language (remote form)",
    "cell-remote-seamless-lang": "index.html: seamless target-language select (remote form)",
    # What the model DOES — one per job, on the picker row and on the cell card.
    # The suffix is the job id from contract/model_jobs.json, so the two
    # surfaces are found by the same five names.
    "model-job-llm": "form.js: jobChips() on the picker row",
    "model-job-asr": "form.js: jobChips() on the picker row",
    "model-job-embed": "form.js: jobChips() on the picker row",
    "model-job-tts": "form.js: jobChips() on the picker row",
    "model-job-translate": "form.js: jobChips() on the picker row",
    "model-job-speech-translate": "form.js: jobChips() on the picker row",
    "model-job-voice-chat": "form.js: jobChips() on the picker row",
    "model-job-robot-policy": "form.js: jobChips() on the picker row",
    "cell-job-llm": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-job-asr": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-job-embed": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-job-tts": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-job-translate": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-job-speech-translate": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-job-voice-chat": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-job-robot-policy": "topology-nodes.js: jobChipsHtml() on the cell card",
    "cell-config-search": "config-locator.js: the settings search input above the tabs",
    # The switch on an engine's strip starts or stops its server — one of the two.
    "node-engine-start": "topology-nodes.js: engineLeverHtml() on an engine's strip",
    "node-engine-stop": "topology-nodes.js: engineLeverHtml() on an engine's strip",
    "cell-config-search-results": "config-locator.js: the search suggestion list",
    # The caravan's strip over the chips is an EngineStrip with its own hook.
    "node-caravan": "topology-nodes.js: nodeCaravanGroupHtml() passes EngineStrip its hook",
    # Routing's "＋" rows that start a new cable from any point of them: one helper draws both. They stand in the
    # strip below the board (1.3.533), and on the card of a pool or a set that has nothing yet.
    "pb-add-row": "pool-board.js: newOutHtml() in a pool's strip, and on a pool with no row",
    # A cell's context — the window set and the most its model was trained for — is one chip with two places (1.3.648).
    "cell-row-ctx": "card-rows.js: CellContext.html() on a cell's line, its default name",
    "machine-model-ctx": "machine-models.js: launchHtml() names CellContext's chip on a saved launch",
}

LITERAL = re.compile(r'data-t="([a-z][a-z0-9-]*)"')


def names():
    out = subprocess.run(
        ["grep", "-rhoE", r'data-t="[a-z][a-z0-9-]*"', *SCAN],
        cwd=ROOT, capture_output=True, text=True).stdout
    return sorted(set(LITERAL.findall(out)) | set(COMPOSED))


def unbacked_composed():
    """Composed names that nothing in the source can produce any more.

    COMPOSED is declared by hand, so it can outlive the code it describes:
    delete the line that builds a hook and this list still claims it, the doc
    still publishes it, and --check still passes — the doc is generated FROM
    this file, so it cannot notice. A suite then locates a name the page never
    emits and reads the empty result as a broken application. Reported from
    outside, exactly that way, on follow-up 5.

    A name is backed either by its literal appearing in the source
    (`const tHook = "cell-remote-compute"`) or by being the
    ONE derivation the code actually performs: `${selectEl.dataset.t}-picker`,
    over a base that is itself a literal hook.

    Only that suffix, deliberately. Accepting any `<literal>-<word>` would let
    `models-tree-toggle` pass on the strength of `models-tree` — which is the
    precise name that was reported as declared-but-absent, so a rule that waves
    it through is a rule that does nothing.
    """
    blob = subprocess.run(["grep", "-rhoE", r'"[a-z][a-z0-9-]*"', *SCAN],
                          cwd=ROOT, capture_output=True, text=True).stdout
    literals = set(re.findall(r'"([a-z][a-z0-9-]*)"', blob))
    bad = []
    for name in sorted(COMPOSED):
        if name in literals:
            continue
        if name.endswith("-picker") and name[:-len("-picker")] in literals:
            continue
        bad.append(name)
    return bad


def main():
    all_names = names()
    if "--check" not in sys.argv:
        for n in all_names:
            print(n)
        print(f"\n{len(all_names)} values "
              f"({len(all_names) - len(COMPOSED)} literal + {len(COMPOSED)} composed)",
              file=sys.stderr)
        return 0

    doc_path = os.path.join(ROOT, "docs", "testability.md")
    with open(doc_path, encoding="utf-8") as fh:
        doc = fh.read()
    m = re.search(r"Generated from the source, not from memory — (\d+) values", doc)
    if not m:
        print("testability.md: the generated-names header is missing", file=sys.stderr)
        return 1
    listed = set(re.findall(r'`([a-z][a-z0-9-]*)`',
                            doc.split("Generated from the source")[1]
                               .split("Repeated elements carry")[0]))
    problems = []
    for name in unbacked_composed():
        problems.append(f"COMPOSED declares {name}, but nothing in the source "
                        f"builds it — the doc would publish a hook the page never emits")
    if int(m.group(1)) != len(all_names):
        problems.append(f"header says {m.group(1)} values, source has {len(all_names)}")
    for n in sorted(set(all_names) - listed):
        problems.append(f"in the source but not in the doc: {n}")
    for n in sorted(listed - set(all_names)):
        problems.append(f"in the doc but no longer in the source: {n}")
    for p in problems:
        print(f"testability.md: {p}", file=sys.stderr)
    if problems:
        print("\nregenerate with: python3 scripts/testability_names.py", file=sys.stderr)
        return 1
    print(f"testability contract OK: {len(all_names)} data-t values, doc matches source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
