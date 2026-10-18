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
    # The public mirror refuses a machine's name or address and the home network's domain: an
    # address written into a document, and a fleet machine's name in a fixture, must turn this red.
    # Both are put together here from halves: whole, they would be a leak in this public file.
    "check_public_leaks": [
        ([], "docs/security.md", "# Security: accounts, sessions and the fleet token\n",
         "# Security: accounts, sessions and the fleet token\n\nThe controller answers at " + "192." + "168.30.20.\n"),
        ([], "scripts/test_scout_scan.py", 'known=("alpha",)', 'known=("' + "at" + 'las",)'),
    ],
    # Every program the controller runs needs a container decision, and a
    # module running a machine program must ask first: a new program without a
    # decision, and a module that stopped asking, must turn this red.
    "check_container_answers": [
        ([], "caravan/admin/host_power.py",
         'ACTIONS = ("reboot", "poweroff")\n',
         'ACTIONS = ("reboot", "poweroff")\n\n\ndef _disks():\n'
         '    return subprocess.run(["lsblk", "-J"], capture_output=True)\n'),
        ([], "caravan/admin/gpu_driver.py",
         "FACTS_TIMEOUT = 90\n",
         "FACTS_TIMEOUT = 90\n\n\ndef _cards():\n"
         "    return run([\"nvidia-smi\", \"-L\"], timeout=5)\n"),
    ],
    # The image must carry what the running code reads: a folder the COPY list
    # leaves out, or that .dockerignore drops, must turn this red.
    "check_image_contents": [
        ([], "Dockerfile", "COPY --chown=caravan:caravan cells/ cells/\n", ""),
        ([], ".dockerignore", "docs/\n", "docs/\ncells/\n"),
    ],
    # The firewall is the operator's (one rule for the proxy range): a ufw call
    # in either shape — an argv list, a command string — must turn this red.
    "check_firewall_untouched": [
        ([], "caravan/admin/proxies_config.py",
         "from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, CONTROLLER_HOST_ID, PROXY_PORTS\n",
         "from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, CONTROLLER_HOST_ID, PROXY_PORTS\n"
         "_DOOR_ARGV = [\"sudo\", \"-n\", \"ufw\", \"allow\"]\n"),
        ([], "caravan/admin/proxies_config.py",
         "from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, CONTROLLER_HOST_ID, PROXY_PORTS\n",
         "from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, CONTROLLER_HOST_ID, PROXY_PORTS\n"
         "_DOOR_SHELL = \"sudo ufw allow 23001\"\n"),
    ],
    # The deploy keeps the proxy running when none of ITS files changed — so the
    # list of its files must cover everything it imports, the release number
    # must stay a number, and the list itself must not shrink.
    "check_proxy_sources": [
        ([], "caravan/proxy/main.py",
         "from caravan.proxy.paths import STATE_FILE\n",
         "from caravan.proxy.paths import STATE_FILE\nfrom caravan.admin.paths import PROJECT_ROOT as _ADMIN_ROOT  # noqa: F401\n"),
        ([], "scripts/proxy_restart.py",
         'SOURCES = ("agent-proxies.py", "caravan/proxy/", "caravan/common/")',
         'SOURCES = ("agent-proxies.py", "caravan/proxy/")'),
        ([], "caravan/__init__.py",
         '"""LAMA CARAVAN — fleet control plane for llama.cpp servers and AI agents."""\n',
         '"""LAMA CARAVAN — fleet control plane for llama.cpp servers and AI agents."""\nRELEASED_ON = "2026-10-07"\n'),
        # The same reach, hidden inside a function — imported only when called.
        ([], "caravan/proxy/main.py",
         "    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)\n",
         "    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)\n"
         "    from caravan.admin.paths import PROJECT_ROOT as _ADMIN_ROOT  # noqa: F401\n"),
        # A module named by a string, which no walk of imports can follow.
        ([], "caravan/proxy/main.py",
         "import threading\n", "import importlib\nimport threading\n"),
        # The release number read by the proxy: then bumping it changes the proxy.
        ([], "caravan/proxy/main.py",
         "import threading\n", "import threading\nfrom caravan import __version__ as _RELEASE  # noqa: F401\n"),
        # The walk starting nowhere near the proxy: it must say so, not pass.
        ([], "agent-proxies.py",
         "from caravan.proxy.main import main  # noqa: E402\n", "main = None  # noqa: E402\n"),
    ],
    "check_subscription_resets": [
        ([], "caravan/proxy/cloud_auth.py", 'CLOUD_PROVIDER_AUTH = {',
         '_automatic_reset = SubscriptionResetDesk().consume("a", "credit", "key", True)\nCLOUD_PROVIDER_AUTH = {'),
        ([], "static/js/pools.js", 'import { t } from "./i18n.js";',
         'const _automaticReset = "/api/cloud-accounts/subscription-reset";\nimport { t } from "./i18n.js";'),
    ],
    "check_oauth_owner": [
        ([], "caravan/proxy/cloud_auth.py", 'CLOUD_PROVIDER_AUTH = {',
         '_duplicate_refresh = {"grant_type": "refresh_token"}\nCLOUD_PROVIDER_AUTH = {'),
        # The writer that put a spent refresh token back (until 2026-10-07): the
        # whole document written through the admin's cached store…
        ([], "caravan/admin/cloud.py", "def load_provider_secrets():",
         "def save_provider_secrets(secrets):\n    _secrets.write(secrets, chmod=0o600)\n\n\n"
         "def load_provider_secrets():"),
        # …the proxy's own whole-file writer, which sat unused…
        ([], "caravan/proxy/cloud_auth.py", 'CLOUD_PROVIDER_AUTH = {',
         'def _write_provider_secrets(secrets):\n    atomic_write_text(PROVIDER_SECRETS_FILE, json.dumps(secrets))\n\n\n'
         'CLOUD_PROVIDER_AUTH = {'),
        # …and the same fault spelled as a method of the path, and as open().
        ([], "caravan/admin/settings_bundle.py", 'def apply_bundle(bundle, passphrase=""):',
         'def _wipe():\n    PROVIDER_SECRETS_FILE.write_text("{}")\n\n\ndef apply_bundle(bundle, passphrase=""):'),
        ([], "caravan/admin/cloud_api.py", "def set_account_key(account_id, key):",
         'def _dump(doc):\n    with open(PROVIDER_SECRETS_FILE, "w") as handle:\n        json.dump(doc, handle)\n\n'
         "def set_account_key(account_id, key):"),
        ([], "caravan/admin/oauth.py", "_oauth_sessions = {}",
         "def _save(doc):\n    CachedJsonStore(PROVIDER_SECRETS_FILE).write(doc)\n\n\n_oauth_sessions = {}"),
    ],
    "check_models_dir_source": [
        # serve_model_file derives the directory itself again, as it did when a container
        # answered 404 for every file the picker had just listed…
        ([], "caravan/admin/models.py",
         '    models_dir = models_dir_from_config(parse_config())\n    try:\n        target = (models_dir / rel).resolve()',
         '    models_dir = LLAMA_HOME / "models"\n    try:\n        target = (models_dir / rel).resolve()'),
        # …and the same fault in another spelling, in the listing.
        ([], "caravan/admin/models.py",
         '    models_dir = models_dir_from_config(parse_config())\n    if not models_dir.is_dir():',
         '    models_dir = Path(f"{LLAMA_HOME}/models")\n    if not models_dir.is_dir():'),
    ],
    "check_messages_i18n": [
        ([], "static/js/i18n/ru.js",
         '  grpSampling:', '  grpSamplingRENAMED:'),
        # A Russian value left standing in another language's table — neither the
        # en-copy nor the english-phrase check sees it, which is how
        # `computeAuto: "авто"` sat in the Chinese one.
        ([], "static/js/i18n/zh.js",
         'computeAuto: "\u81ea\u52a8",', 'computeAuto: "\u0430\u0432\u0442\u043e",'),
        # An English sentence left in a non-latin table. The english-phrase rule
        # could not see one until 2026-10-07: under one re.IGNORECASE the ALLCAPS
        # identifier alternative stripped every latin word before it looked.
        ([], "static/js/i18n/zh.js",
         'computeAuto: "\u81ea\u52a8",', 'computeAuto: "Pick the size automatically",'),
        # A key written twice: the later line silently wins, so the loaded table
        # looks whole and only the file's text shows it (2026-10-07, a new key
        # took a name Routing already used).
        ([], "static/js/i18n/de.js",
         '  deleteAction: "L\u00f6schen",', '  deleteAction: "L\u00f6schen",\n  deleteAction: "Entfernen",'),
        # Words written without their diacritics, in the three shapes of the 2026-08 batches (found
        # 2026-10-13): German spelled out, French dropped, Vietnamese every mark. The file is the
        # witness — it writes «für» and «modèle» right a hundred times beside the plain one.
        ([], "static/js/i18n/de.js",
         "g\u00fcnstig genug f\u00fcr Massen", "g\u00fcnstig genug fuer Massen"),
        ([], "static/js/i18n/fr.js",
         "ce n'est pas un mod\u00e8le de chat", "ce n'est pas un modele de chat"),
        ([], "static/js/i18n/vi.js",
         "Giấy phép phi thương mại (CC-BY-NC-4.0). Chỉ tạo ngôn ngữ đích. Không có kernel SDPA/FlashAttention nên chậm hơn whisper.",
         "Giay phep phi thuong mai (CC-BY-NC-4.0). Chi tao ngon ngu dich. Khong co kernel SDPA/FlashAttention nen cham hon whisper."),
    ],
    "check_i18n_calls": [
        ([], "static/js/system-page.js",
         'function bindSettingsBundle() {',
         'function bindSettingsBundle() {\n  const _leak = t("keyThatWasNeverDefined");'),
        # The /hf modules ask their own table, not the shared one.
        ([], "static/js/hf-page.js",
         'this.toast(hfT("networkError"));', 'this.toast(hfT("networkErrorNeverDefined"));'),
        # A language of the /hf table left in English: the key is there, so only
        # the translation rule can see it.
        ([], "static/js/hf-text.js",
         '    diskFitTitle: "Espace insuffisant sur le disque des modèles",',
         '    diskFitTitle: "Not enough space on the models disk",'),
        # …and in a non-latin language, where only the english-phrase rule looks.
        ([], "static/js/hf-text.js",
         '    diskFitTitle: "模型磁盘空间不足",',
         '    diskFitTitle: "Not enough space on the models disk",'),
        # A word of the /hf table written without its accent beside the same word written right
        # (the table's own witness): the shared rule of check_messages_i18n looks here too.
        ([], "static/js/hf-text.js",
         '    aaTop: "au-dessus de tous les modèles de référence de la liste",',
         '    aaTop: "au-dessus de tous les modeles de référence de la liste",'),
        # A phrase of the one rule of "time left" worded otherwise on /hf than on the board: the same wait reads two ways on two
        # screens. The key is there, in every language, with its placeholders: only the mirror rule sees it.
        ([], "static/js/hf-text.js",
         '    moveEtaMinutes: "~{n} min left",',
         '    moveEtaMinutes: "≈{n} min left",'),
        # The rule learns a phrase no table has: the label would show the key itself, and neither t("…") nor hfT("…") names it.
        ([], "static/js/pace-rule.js",
         'if (minutes < 60) return say("moveEtaMinutes", { n: String(minutes) });',
         'if (minutes < 60) return say("moveEtaMinutesAndABit", { n: String(minutes) });'),
    ],
    "check_cell_form_text": [
        # A label written as plain text again: the cache switch's stood in English on every
        # other language's page (2026-10-13), and no other guard could see a sentence that
        # asks for no key.
        ([], "static/index.html",
         '<strong data-i18n="cacheModelsTitle">Cache model on host disk</strong>',
         '<strong>Cache model on host disk</strong>'),
        # The CSS rule that hides a field's descriptions goes: they show now, and the guard's
        # exemption for them is no longer true.
        ([], "static/css/monitor.css",
         '.topo-edit-form .field p:not(.field-note) {\n  display: none;\n}',
         '.topo-edit-form .field p:not(.field-note) {\n  display: block;\n}'),
        # …and the bare rule is back beside it: every note of every panel hidden again, as from
        # 2026-05-31 to 1.3.518, and nobody saw it.
        ([], "static/css/monitor.css",
         '.topo-edit-form .field p:not(.field-note) {\n  display: none;\n}',
         '.topo-edit-form .field p:not(.field-note) {\n  display: none;\n}\n.topo-edit-form .field p {\n  display: none;\n}'),
        # MODEL_NAME's only help was a hidden line under a field with no tip.
        ([], "static/js/llama-edit.js",
         'const _STATIC_TIP_FIELDS = ["MODEL_NAME", "COMMAND",', 'const _STATIC_TIP_FIELDS = ["COMMAND",'),
        # A note written as a plain paragraph of a field: the editor's CSS hides it.
        ([], "static/index.html",
         '<p class="field-note" data-i18n="vllmPanelNote">', '<p data-i18n="vllmPanelNote">'),
        # A note that is shown but never asked for a key: English on every other page.
        ([], "static/index.html",
         '<p class="field-note" data-i18n="strataPanelNote">', '<p class="field-note">'),
        # The NLLB model carrier without a `.field` of its own: hidden, it takes the languages with it.
        ([], "static/index.html",
         '<div class="field" id="tr-translateModelField">', '<div id="tr-translateModelField">'),
        # An exception that outlived its cause: an entry for an element that holds no untranslated prose
        # (the guard has none today; the entry is written into it here).
        ([], "scripts/check_cell_form_text.py",
         "EXCEPTIONS = {}", 'EXCEPTIONS = {"tr-purgeCacheNote": "an excuse that nothing needs any more"}'),
        # The model-cache note in English again, with no key: the words that stood here untranslated for
        # two months (until 1.3.525) must turn the guard red when they come back.
        ([], "static/index.html",
         '<span data-i18n="purgeCacheNoteBefore">Deletes downloaded .gguf files from</span>',
         '<span>Deletes downloaded .gguf files from</span>'),
        # A paragraph OUTSIDE a field is shown — the CSS hides only a field's paragraphs — so prose
        # in it needs its key like any other.
        ([], "static/index.html",
         '<div style="font-size:10px;opacity:.6;margin-bottom:4px" data-i18n="remoteCmdPathsHint">Binary and model paths resolved on remote host</div>',
         '<p style="font-size:10px;opacity:.6;margin-bottom:4px">Binary and model paths resolved on remote host</p>'),
    ],
    "check_tour_i18n": [
        ([], "static/js/onboarding-strings.js",
         '  tourCfgFieldsB:', '  tourCfgFieldsBRENAMED:'),
        # A step of the /hf tour still in English in another language.
        ([], "static/js/hf-text.js",
         '       "Ce qui est sélectionné, où il sera placé, si cela tient et si quelque chose serait écrasé — avant que vous cliquiez sur Télécharger. Les téléchargements en cours (avec Annuler) et les téléchargements interrompus (avec Reprendre) se trouvent ici aussi."],',
         '       "What is selected, where it lands, whether it fits and whether anything would be written over — before you press Download. Running downloads (with Cancel) and interrupted ones (with Resume) live here too."],'),
    ],
    "testability_names": (
        ["--check"], "static/index.html",
        '<div id="tr-offloadPlan"',
        '<div data-t="hook-nobody-registered"></div>\n            <div id="tr-offloadPlan"'),
    "check_boot_guard": [
        ([], "static/system.html", 'data-t-state', 'data-t-state-DRIFTED'),
        # The boot's first word must be the first module that runs: moved down, a graph that never loads leaves nothing.
        ([], "static/js/main.js", 'import { BootStep } from "./boot-step.js";\nimport { initDialogLlamas } from "./dialog-llamas.js";',
         'import { initDialogLlamas } from "./dialog-llamas.js";\nimport { BootStep } from "./boot-step.js";'),
        # The writer and the reader of the step name must agree.
        ([], "static/js/boot-step.js", "window.__bootWaiting = what;", "window.__bootStep = what;"),
        # A step the banner can name, dropped from the boot.
        ([], "static/js/main.js", 'BootStep.waitsFor("/api/state");', ''),
    ],
    # The bar of every page is the template's, and the way back to the main board is in it (1.3.552): a page edited by hand, the
    # machine's window without its link (the defect that started this), a second bar, a stylesheet that takes the link away
    # elsewhere, the rule keyed on a word Routing shares with the board, a page with no row, and the views' words changed.
    "check_header": [
        ([], "static/routing.html", 'data-t="header-back" href="/board"', 'data-t="header-back" href="/boards"'),
        ([], "static/index.html",
         '      <a class="sys-back topbar-back" data-t="header-back" data-view-only="machine" href="/board"><span aria-hidden="true">←</span> <span data-i18n="boardPageName">Main board</span></a>\n',
         ''),
        ([], "static/models.html", '<!-- header:end -->\n', '<!-- header:end -->\n  <header class="topbar" data-t="header"></header>\n'),
        ([], "static/css/topology-board.css", 'html[data-board-view="machine"] body .topbar { min-width: 0; }\n',
         'html[data-board-view="machine"] body .topbar { min-width: 0; }\nhtml[data-board-view="machine"] .topbar-back { display: none; }\n'),
        ([], "static/css/base.css", 'html:not([data-board-view="machine"]) .topbar-back[data-view-only="machine"] { display: none; }',
         'html[data-board-view="main"] .topbar-back { display: none; }'),
        ([], "scripts/gen_header.py",
         '        "system": Page(file="system.html", title="System &amp; settings", title_key="systemSubtitleBrand",\n                       tour=False),\n', ''),
        ([], "static/js/board-view.js", 'return this.isMachine ? "machine" : "main";', 'return this.isMachine ? "machine" : "home";'),
    ],
    # A machine-level action that the board cannot take back must ask the name TYPED: each of the three, put back to
    # a dialog a click answers (or one whose suggestion Tab takes), must turn the guard red.
    "check_typed_machine_actions": [
        ([], "static/js/topology-render.js",
         'const ok = await appConfirmTyped(\n        t(hostPowerTextKey(hostId, "reboot"))',
         'const ok = await appConfirm(\n        t(hostPowerTextKey(hostId, "reboot"))'),
        ([], "static/js/topology-render.js",
         'const ok = await appConfirmTyped(\n        t(hostPowerTextKey(hostId, "poweroff"))',
         'const ok = await appPrompt(\n        t(hostPowerTextKey(hostId, "poweroff"))'),
        ([], "static/js/remote-cells.js",
         'if (!(await appConfirmTyped(question, name,', 'if (!(await appConfirm(question, name,'),
        # Typed, but not the machine's name: the words asked for are something else.
        ([], "static/js/topology-render.js",
         'hostId,\n        { confirmLabel: t("hostRebootOk")', '"reboot",\n        { confirmLabel: t("hostRebootOk")'),
    ],
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
         '_liveSet(nodeEl, "[data-live-hostage]", hostAgeText(n));',
         '_liveSet(nodeEl, "[data-live-hostage]", t("nodeScoutLastReport", { ago: `${n.ageSeconds}s` }));'),
        # The single source stops building it — nothing left to protect.
        ([], "static/js/topology-nodes.js",
         't("nodeScoutLastReport", { ago: _ageShort(age) })', '`${_ageShort(age)} ago`'),
        # 1.3.588: the patch reads a cell's request count itself — the line's work has two rules again, and the ring and `last` can disagree.
        ([], "static/js/topology-render.js",
         "const speed = new CellSpeed(s, running);", "const speed = new CellSpeed(s, running); const busyNow = s.requestsProcessing > 0;"),
        # The class stops reading the count — nothing left to protect.
        ([], "static/js/cell-speed.js",
         "this.requests = CellSpeed.count(s.requestsProcessing);", "this.requests = CellSpeed.count(s.requests);"),
        # The class goes away (renamed) — the guard says there is nothing to check, instead of staying green.
        ([], "static/js/cell-speed.js", "export class CellSpeed {", "export class CellSpeeds {"),
        # 1.3.589: the machine's token speed panel reads the count itself — a second place that says who works.
        ([], "static/js/charts.js",
         "this.running().filter((s) => new CellSpeed(s, true).working)", "this.running().filter((s) => s.requestsProcessing > 0)"),
    ],
    "check_carried_fields": [
        # A boundary stops naming a carried field — the classic silent drop.
        ([], "caravan/proxy/config.py",
         '"contextLength": int(route["contextLength"])', '"ctxLen": int(route["ctxLen"])'),
        # A writer goes back to building an assignment from scratch. The rebuild
        # from a live report did exactly that (the fifth boundary the list never
        # saw); it is gone, and the bind is the writer left to break.
        ([], "caravan/admin/topology.py",
         "    assignment = AgentAssignment.from_raw(entry)\n"
         "    assignment.set_route(ProxyRoute.for_port(role, port, TOPOLOGY_SERVER_IP))",
         "    assignment = AgentAssignment(agent_id)\n"
         "    assignment.set_route(ProxyRoute.for_port(role, port, TOPOLOGY_SERVER_IP))"),
    ],
    "check_proxy_id_namespace": (
        # Building the id moved to caravan/domain/client_proxy.py: three
        # places used to build the same shape, and one of them dropped
        # unnamed fields.
        [], "caravan/domain/client_proxy.py",
        'PROXY_ID_PREFIX = "skynet:proxy:"', 'PROXY_ID_PREFIX = "controller:proxy:"'),
    "check_cell_card_keys": (
        [], "caravan/admin/topology.py",
        '            "savedCommand": _saved_command(_r_slot, _r_cfg) if slot_is_command else "",\n', ''),
    "check_cell_self_capture": (
        [], "cells/whisper_server.py",
        '                    state["downloaded"]', '                    self.state["downloaded"]'),
    # A provider's refusal sent as the board's own 401: the page goes to /login.
    "check_board_401": (
        [], "caravan/admin/cloud_api.py",
        'sign in again in the account\'s ⚙", 502)', 'sign in again in the account\'s ⚙", 401)'),
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
        '        self.send_header("Connection", "close")\n        for name, value in headers:',
        '        for name, value in headers:'),
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
    "check_test_ports": [
        # A test writes the eight lines again — bind to port 0, read the number, close, return it — and asks for ports the old way,
        # one number twice: the race that killed a server of test_proxy_forward.py with "Address already in use".
        ([], "scripts/test_upstream_pool.py",
         "from _ports import free_port  # noqa: E402\n",
         "def free_port():\n    sock = socket.socket()\n    sock.bind((\"127.0.0.1\", 0))\n    port = sock.getsockname()[1]\n    sock.close()\n    return port\n"),
        # The same ask written the other way round — the empty host, as a socket is made for every address — is still a free port asked
        # of the kernel by the test itself.
        ([], "scripts/test_first_run.py", "PORT = free_port()\n",
         "_sock = socket.socket()\n_sock.bind((\"\", 0))\nPORT = _sock.getsockname()[1]\n_sock.close()\n"),
        # And in single quotes: the style of the quotes does not make the ask a different one.
        ([], "scripts/test_cloud_context.py", "    port = free_port()\n",
         "    _sock = socket.socket()\n    _sock.bind(('127.0.0.1', 0))\n    port = _sock.getsockname()[1]\n    _sock.close()\n"),
        # A `free_port` of its own that binds nothing (a fixed number, a counter) is no pool either: it gives the same port to two servers.
        ([], "scripts/test_request_body.py", "from _ports import free_port  # noqa: E402\n", "def free_port():\n    return 5000\n"),
        # The list of scripts that bind port 0 on purpose names one that no longer does: it would go on saying what is not so.
        ([], "scripts/test_machine_scout.py",
         "    with socket.socket() as sock:\n        sock.bind((\"127.0.0.1\", 0))\n        return sock.getsockname()[1]\n",
         "    with socket.socket() as sock:\n        sock.bind((\"127.0.0.1\", 9))\n        return sock.getsockname()[1]\n"),
    ],
    "check_context_window": (
        # A reader of the TRAINED context appears outside the vocabulary — the
        # number that is 131072 where the truth is 60160.
        [], "caravan/admin/monitoring.py",
        'def gpu_state():',
        'def gpu_state():\n    _trained = {}.get("n_ctx_train")'),
    "check_why_refs": (
        [], "docs/why.md",
        "`caravan/admin/cell_ops.py` (`client_server_slot_delete`)", "`caravan/admin/gone.py` (`client_server_slot_delete`)"),
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
    # The boot smoke must see a controller that does not start, and a fresh one
    # that is open again before its first account (the door be41edff closed).
    "check_boot_smoke": [
        ([], "app.py", "    main()\n", "    raise SystemExit(\"broken on purpose\")\n"),
        ([], "caravan/admin/routes.py", "    if kind == RouteAccess.PUBLIC:\n        return True\n",
         "    if kind == RouteAccess.PUBLIC or first_run:\n        return True\n"),
    ],
    "check_cell_kinds": (
        [], "cells/whisper_server.py",
        'kinds = ["asr", "stt.whisper"]', 'kinds = ["stt.whisper"]'),
    "check_cell_health_contract": (
        [], "cells/whisper_server.py",
        '    engine = "faster-whisper"\n', ''),
    # A route that cannot say what it does: /openapi.json would carry an empty
    # summary, a draft left UNSURE, and the page for people that drifted from
    # the code — the hand-written list had fallen 16 paths behind.
    "check_api_spec": [
        ([], "caravan/admin/routes.py",
         '        """This API as OpenAPI 3.1: every route, what it does, what it reads, who may call it\n\n'
         "        Built from the route tables and the handlers' docstrings and code when the controller\n"
         "        starts; `info.version` is the commit `/healthz` names (\"unknown\" when none is known) and\n"
         "        `info.x-release` the controller's version.\n"
         '        """\n', ''),
        ([], "caravan/admin/routes.py",
         '"""This API as OpenAPI 3.1: every route', '"""UNSURE: This API as OpenAPI 3.1: every route'),
        ([], "docs/http-api.md", "| `GET /openapi.json` | open |", "| `GET /openapi.json` | admin |"),
    ],
    # Everything of the caravan opens in the tab the operator is in (the owner, 2026-10-17): a link of the board that asks
    # for a window of its own, a script that opens a new tab, and a page that leaves its tab through window.open in a
    # place that used to be an exception must each turn this red.
    "check_same_tab_links": [
        ([], "static/index.html", 'href="/models"\n', 'href="/models" target="caravan-models"\n'),
        ([], "static/js/topology-dnd.js", 'window.location.assign("/routing");', 'window.open("/routing", "_blank");'),
        ([], "static/js/hf-downloads.js", "this.go = go || ((url) => globalThis.location.assign(url));", 'this.go = go || ((url) => globalThis.open(url, "_blank"));'),
    ],
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
