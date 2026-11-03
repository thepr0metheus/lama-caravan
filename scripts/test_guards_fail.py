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
    # The rules of the caravan's Rust: each breakage is a defect it exists to catch, in code that looks ordinary (docs/rust-code.md).
    "check_rust_contract": [
        # A comment pointing at the tree that left: a reader takes it for a place to look.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "// See `caravan/common/request_kind.py`.\n/// One answer for the fleet"),
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "// The twin of `RequestKind`.\n/// One answer for the fleet"),
        # A function outside an impl.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "pub fn loose(path: &str) -> bool {\n    path.is_empty()\n}\n\n/// One answer for the fleet"),
        # A `#[cfg(test)]` on one item hides nothing after it.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "#[cfg(test)]\nconst X: u32 = 1;\n\npub fn loose(path: &str) -> bool {\n    path.is_empty()\n}\n\n/// One answer for the fleet"),
        # A God function: one that has grown past the limit.
        ([], "rust/crates/rules/src/request_kind.rs", "    /// True for a chat's path.\n", "    fn long() -> u32 {\n" + "        let _x = 1;\n" * 70 + "        1\n    }\n\n    /// True for a chat's path.\n"),
        # A God file.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "/// One.\n" * 450 + "/// One answer for the fleet"),
        # State at module level: a marker that outlives what set it.
        ([], "rust/crates/proxy/src/queue.rs", "/// One request waiting.", "static BUSY: Mutex<u32> = Mutex::new(0);\n\n/// One request waiting."),
        ([], "rust/crates/proxy/src/queue.rs", "/// One request waiting.", "static mut BUSY: u32 = 0;\n\n/// One request waiting."),
        # A rule that reads the clock, a file, the environment: a snapshot then depends on when it runs.
        ([], "rust/crates/rules/src/policy.rs", "use serde_json::Value;", "use serde_json::Value;\nuse std::fs;"),
        ([], "rust/crates/rules/src/policy.rs", "use serde_json::Value;", "use serde_json::Value;\nuse std::env;"),
        ([], "rust/crates/proxy/src/watch.rs", "let now = proxy.clock.epoch();", "let now = std::time::SystemTime::now();"),
        # A socket type in the crate that reads through `Read`.
        ([], "rust/crates/wire/src/lines.rs", "use std::io::{self, Read};", "use std::io::{self, Read};\nuse std::net::TcpStream;"),
        # TLS outside its crate: a second idea of what a provider's certificate must be.
        ([], "rust/crates/proxy/src/provider_call.rs", "use net::{Dial, Stream};", "use net::{Dial, Stream};\nuse rustls::ClientConfig;"),
        # Absence drawn as a value, with no word on why: the defect that cost the most here.
        ([], "rust/crates/proxy/src/record.rs", 'put("firstByteMs", json!(facts.first_byte_ms));', 'put("firstByteMs", json!(facts.first_byte_ms.unwrap_or(0)));'),
        ([], "rust/crates/proxy/src/config.rs", "// absent-ok: \"\" is \"not known\" in the state file's `sourceCommit`, as in `StartRecord`: never a guess.\n", ""),
        # unsafe outside its one crate, and an allow that does not say why.
        ([], "rust/crates/rules/src/coerce.rs", "/// How Python's `bool`, `str` and `int` read a JSON value.", "/// x\npub unsafe trait Loose {}\n\n/// How Python's `bool`, `str` and `int` read a JSON value."),
        ([], "rust/crates/proxy/src/log.rs", '#[allow(clippy::print_stderr, reason = "this is the one place the proxy prints")]', "#[allow(clippy::print_stderr)]"),
        # A new package with no reason; a listed one that is gone: the list lies either way.
        ([], "rust/Cargo.lock", 'name = "httparse"', 'name = "left-pad"'),
        # A lint taken away, and a crate that does not take them.
        ([], "rust/Cargo.toml", 'unwrap_used = "deny"', 'unwrap_used = "allow"'),
        ([], "rust/crates/wire/Cargo.toml", "[lints]\nworkspace = true\n", ""),
        # A table one language does not run.
        ([], "rust/crates/rules/tests/contract.rs", 'table("levers")', 'table("other")'),
        # Two compilers.
        ([], ".gitlab-ci.yml", "image: rust:1.99.1-slim-bookworm", "image: rust:1.98.0-slim-bookworm"),
        ([], "deploy/nas/release_ship.py", 'IMAGE = "rust:1.99.1-slim-bookworm"', 'IMAGE = "rust:1.98.0-slim-bookworm"'),
        ([], "rust/rust-toolchain.toml", 'channel = "1.99.1"', 'channel = "stable"'),
    ],
    # The public mirror refuses a machine's name or address and the home network's domain: an
    # address written into a document, and a fleet machine's name in a fixture, must turn this red.
    # Both are put together here from halves: whole, they would be a leak in this public file.
    "check_public_leaks": [
        ([], "docs/security.md", "# Security: accounts, sessions and the fleet token\n",
         "# Security: accounts, sessions and the fleet token\n\nThe controller answers at " + "192." + "168.30.20.\n"),
        ([], "scripts/test_stand.py", 'print("сам стенд:")', 'print("' + "at" + 'las")'),
    ],
    # Every program the controller runs needs a container decision, and a
    # module running a machine program must ask first: a new program without a
    # decision, and a module that stopped asking, must turn this red.
    "check_container_answers": [
        ([], "rust/crates/admin/src/fleet/host_power.rs", "use ", 'const _DISKS: fn() = || drop(std::process::Command::new("lsblk"));\nuse '),
        ([], "scripts/check_container_answers.py", '    "status.rs": "git over the checkout', '    "fleet/host_power.rs": "named here and running nothing",\n    "status.rs": "git over the checkout'),
    ],
    # The image must carry what the running code reads: a folder the COPY list
    # leaves out, or that .dockerignore drops, must turn this red.
    "check_image_contents": [
        ([], "deploy/nas/release_ship.py", '"archive", "origin/main", "static", "cells", "VERSION"', '"archive", "origin/main", "static", "VERSION"'),
        ([], "deploy/nas/release_ship.py", '"archive", "origin/main", "static", "cells", "VERSION"', '"archive", "origin/main", "cells", "VERSION"'),
        ([], "Dockerfile", "COPY cells/ cells/\n", ""),
        ([], "Dockerfile", "COPY VERSION ./\n", ""),
    ],
    # The firewall is the operator's (one rule for the proxy range): a ufw call
    # in either shape — an argv list, a command string — must turn this red.
    "check_firewall_untouched": [
        ([], "rust/crates/admin/src/proxies/config.rs", "    /// The phases of a cell that stands", '    const DOOR: [&str; 2] = ["sudo", "ufw"];\n\n    /// The phases of a cell that stands'),
        ([], "rust/crates/admin/src/proxies/config.rs", "    /// The phases of a cell that stands", '    const DOOR: &str = "sudo -n ufw allow 23001";\n\n    /// The phases of a cell that stands'),
    ],
    "check_subscription_resets": [
        ([], "rust/crates/admin/src/routes/system.rs", "    const OPENAPI:", '    fn spend(app: &App) { drop(SubscriptionResetDesk::of(app).consume("a", "credit", "key", true)); }\n\n    const OPENAPI:'),
        ([], "static/js/pools.js", 'import { t } from "./i18n.js";', 'const _automaticReset = "/api/cloud-accounts/subscription-reset";\nimport { t } from "./i18n.js";'),
    ],
    "check_oauth_owner": [
        ([], "rust/crates/proxy/src/connection.rs", "/// A client's connection.", 'const _DUPLICATE: [(&str, &str); 1] = [("grant_type", "refresh_token")];\n\n/// A client\'s connection.'),
        ([], "rust/crates/admin/src/cloud/data.rs", "        CredentialVault::new(self.app.paths.provider_secrets_file.clone())", '        drop(std::fs::write(&self.app.paths.provider_secrets_file, "{}"));\n        CredentialVault::new(self.app.paths.provider_secrets_file.clone())'),
    ],
    "check_models_dir_source": [
        ([], "rust/crates/admin/src/fleet/launch.rs", "    /// A complete, self-contained start script.", '    fn models(llama_home: &std::path::Path) -> std::path::PathBuf { llama_home.join("models") }\n\n    /// A complete, self-contained start script.'),
        ([], "rust/crates/admin/src/fleet/launch.rs", "    /// A complete, self-contained start script.", '    fn models(llama_home: &str) -> String { format!("{llama_home}/models") }\n\n    /// A complete, self-contained start script.'),
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
        # Words written without their diacritics (found 2026-10-13): German spelled out, Spanish dropped.
        # The file is the witness: it writes «für» and «sesión» right many times beside the plain one.
        # French and Vietnamese left with their tables on 2026-11-01; their shapes stay on samples
        # (test_i18n_untranslated.py).
        ([], "static/js/i18n/de.js",
         "g\u00fcnstig genug f\u00fcr Massen", "g\u00fcnstig genug fuer Massen"),
        ([], "static/js/i18n/es.js",
         "Se requiere iniciar sesi\u00f3n", "Se requiere iniciar sesion"),
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
         '    diskFitTitle: "No hay suficiente espacio en el disco de modelos",',
         '    diskFitTitle: "Not enough space on the models disk",'),
        # …and in a non-latin language, where only the english-phrase rule looks.
        ([], "static/js/hf-text.js",
         '    diskFitTitle: "模型磁盘空间不足",',
         '    diskFitTitle: "Not enough space on the models disk",'),
        # A word of the /hf table written without its accent beside the same word written right
        # (the table's own witness): the shared rule of check_messages_i18n looks here too.
        ([], "static/js/hf-text.js",
         '    sortDesc: "Absteigend — klicken für aufsteigend",',
         '    sortDesc: "Absteigend — klicken fuer aufsteigend",'),
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
         '       "Was ausgew\u00e4hlt ist, wohin es kommt, ob es passt und ob etwas \u00fcberschrieben w\u00fcrde \u2014 bevor Sie auf Download klicken. Laufende Downloads (mit Abbrechen) und unterbrochene (mit Fortsetzen) sind ebenfalls hier zu finden."],',
         '       "What is selected, where it lands, whether it fits and whether anything would be written over \u2014 before you press Download. Running downloads (with Cancel) and interrupted ones (with Resume) live here too."],'),
        # The sign-in page's own list drifting from the app's: a label, and a language left in its table.
        ([], "rust/crates/admin/src/web/page_shell.html", '["de","\U0001F968 Deutsch"]', '["de","\U0001F37A Deutsch"]'),
        ([], "rust/crates/admin/src/web/page_shell.html", '    de:{langLabel:', '    nl:{langLabel:'),
    ],
    "testability_names": (
        ["--check"], "static/index.html",
        '<div id="tr-placementMap"',
        '<div data-t="hook-nobody-registered"></div>\n            <div id="tr-placementMap"'),
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
    "check_field_homes": [
        ([], "static/js/constants.js",
         '"TEMPERATURE", "TOP_K", "TOP_P", "MIN_P"] }',
         '"TOP_K", "TOP_P", "MIN_P"] }'),
        # A runner panel renamed in the markup: the loader walks nothing, and the page's address had no panel to show in.
        ([], "static/index.html", 'id="tr-pageFields"', 'id="tr-pageFieldz"'),
    ],
    "check_runner_model_fields": ([], "contract/controller.json", '"modelField": "TRANSLATE_MODEL"', '"modelField": "NO_SUCH_FIELD"'),
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
    "check_proxy_id_namespace": ([], "static/js/topology-dnd.js", "skynet:proxy:", "controller:proxy:"),
    # `grep -q` on a pipe under pipefail: a machine with two cards read "no NVIDIA GPU" (2026-11-02).
    "check_shell_pipes": (
        [], "rust/crates/scout/scripts/install-llama.sh",
        'grep -i "nvidia" >/dev/null', 'grep -qi "nvidia"'),
    # A flag llama.cpp took away: a cell with it says "invalid argument" and does not start (2026-11-03).
    "check_llama_flags": (
        [], "rust/crates/admin/src/config/args/switches.rs",
        'self.push(&["--load-mode", &load_mode]);', 'self.push(&["--no-mmap", &load_mode]);'),
    "check_cell_self_capture": (
        [], "cells/whisper_server.py",
        '                    state["downloaded"]', '                    self.state["downloaded"]'),
    # A provider's refusal sent as the board's own 401: the page goes to /login.
    "check_board_401": ([], "rust/crates/admin/src/cloud/subscription.rs", "sign in again in the account's ⚙\"),\n                        502,", "sign in again in the account's ⚙\"),\n                        401,"),
    "check_cell_python_floor": (
        # moonshine's signatures carry `str | None`: without the deferral the cell dies on 3.9 at import.
        [], "cells/moonshine_server.py",
        "from __future__ import annotations\n", ""),
    "check_installer_assets": (
        [], "scripts/install-seamless.sh",
        'install -m 0644 "${SRC}/cell_base.py"      "${HOME}/cell_base.py"\n', ''),
    "check_undefined_names": (
        [], "cells/moonshine_server.py", "import wave\n", ""),
    "check_ci_coverage": [
        # A script exists on disk but the gate never calls it — green on the
        # author's machine, run nowhere else.
        ([], ".github/workflows/ci.yml",
         "          python3 scripts/test_engine_cell_server.py\n", ""),
        # A script IS named, but in a second `run:` of a step that already has
        # one. YAML keeps a single key, so the line never runs — and the guard
        # used to see the name and call it covered.
        ([], ".github/workflows/ci.yml",
         "        run: python3 scripts/check_boot_smoke.py\n",
         "        run: python3 scripts/check_boot_smoke.py\n"
         "        run: python3 scripts/test_engine_cell_server.py\n"),
    ],
    "check_test_ports": [
        # A test writes the eight lines again — bind to port 0, read the number, close, return it — and asks for ports the old way,
        # one number twice: the race that killed a server of test_proxy_forward.py with "Address already in use".
        ([], "scripts/test_engine_cell_server.py",
         "from _ports import free_port  # noqa: E402\n",
         "def free_port():\n    sock = socket.socket()\n    sock.bind((\"127.0.0.1\", 0))\n    port = sock.getsockname()[1]\n    sock.close()\n    return port\n"),
        # The same ask written the other way round — the empty host, as a socket is made for every address — is still a free port asked
        # of the kernel by the test itself.
        ([], "scripts/test_engine_cell_server.py", "dead_port = free_port()\n",
         "_sock = socket.socket()\n_sock.bind((\"\", 0))\ndead_port = _sock.getsockname()[1]\n_sock.close()\n"),
        # And in single quotes: the style of the quotes does not make the ask a different one.
        ([], "scripts/test_engine_cell_server.py", "dead_port = free_port()\n",
         "_sock = socket.socket()\n_sock.bind(('127.0.0.1', 0))\ndead_port = _sock.getsockname()[1]\n_sock.close()\n"),
        # A `free_port` of its own that binds nothing (a fixed number, a counter) is no pool either: it gives the same port to two servers.
        ([], "scripts/test_gr00t_server.py", "from _ports import free_port  # noqa: E402\n", "def free_port():\n    return 5000\n"),
    ],
    "check_context_window": ([], "rust/crates/admin/src/fleet/launch.rs", "    /// A complete, self-contained start script.", '    const TRAINED: &str = "n_ctx_train";\n\n    /// A complete, self-contained start script.'),
    "check_why_refs": (
        [], "docs/why.md",
        "`rust/crates/admin/src/fleet/cell_ops.rs` (`client_server_slot_delete`)", "`rust/crates/admin/src/fleet/gone.rs` (`client_server_slot_delete`)"),
    "check_oop_contract": [
        # A cell forgets a member the base declares abstract: it starts fine and
        # dies on the first request. The guard must name the member.
        ([], "cells/tts_server.py", "    def handle(self, body, headers, path):", "    def handle_work(self, body, headers, path):"),
        # Logic creeps back into a class module as a fat top-level function.
        ([], "static/js/canvas.js", "export const board = new Board();",
         "export const board = new Board();\nfunction strayLogic(a) {\n  if (a) {\n    return 1;\n  }\n  return 2;\n}"),
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
        ([], "scripts/check_boot_smoke.py", "self.signed_in(self.first_account())", "self.signed_in(self.first_account()); self.failures.append('a guard that cannot fail')"),
    ],
    "check_cell_kinds": (
        [], "cells/whisper_server.py",
        'kinds = ["asr", "stt.whisper"]', 'kinds = ["stt.whisper"]'),
    # A cell server reads a form with cell_base.Form and with nothing of its own (sinapse's ears, 2026-10-19: two of five copies of
    # the reader cut the last bytes of a recording): a copied reader, and a strip of a form's own bytes, must each turn this red.
    "check_cell_forms": [
        ([], "cells/tts_server.py", "from cell_base import CellServer, Form, Recording, Refusal   # noqa: E402\n",
         "from cell_base import CellServer, Form, Recording, Refusal   # noqa: E402\n\n\ndef _extract_file(body, ctype):\n    return None\n"),
        ([], "cells/moonshine_server.py", 'raw = Form(body, headers.get("Content-Type", "")).file()',
         'raw = Form(body, headers.get("Content-Type", "")).file().rstrip(b"\\r\\n-")'),
    ],
    "check_cell_health_contract": (
        [], "cells/whisper_server.py",
        '    engine = "faster-whisper"\n', ''),
    # A route that cannot say what it does: /openapi.json would carry an empty
    # summary, a draft left UNSURE, and the page for people that drifted from
    # the code — the hand-written list had fallen 16 paths behind.
    "check_api_spec": [
        ([], "rust/crates/admin/src/routes/openapi.json", '"summary": "This API as OpenAPI 3.1: every route, what it does, what it reads, who may call it",', '"summary": "",'),
        ([], "rust/crates/admin/src/routes/openapi.json", '"summary": "This API as OpenAPI 3.1: every route', '"summary": "UNSURE: This API as OpenAPI 3.1: every route'),
        ([], "docs/http-api.md", '| `GET /openapi.json` | open |', '| `GET /openapi.json` | admin |'),
    ],
    # Everything of the caravan opens in the tab the operator is in (the owner, 2026-10-17): a link of the board that asks
    # for a window of its own, a script that opens a new tab, and a page that leaves its tab through window.open in a
    # place that used to be an exception must each turn this red.
    # Every node a test starts gets NODE_FLAGS from scripts/_node.py (--single-threaded: node hung in process.exit,
    # 2026-10-21): a runner that builds its own command line again, a NODE_FLAGS without the flag, and a script that finds
    # node by itself must each turn this red. The hook is put together from halves: whole, it would be a hook written by
    # hand in this file.
    # The parts take their colours, font sizes and radii from ui.css's tokens, and the stylesheet styles every class the
    # parts draw: a raw colour in a part's rule, and a class a part draws that nothing styles, must turn this red.
    "check_ui_tokens": [
        ([], "static/css/ui.css",
         ".ui-row--live { background: color-mix(in srgb, var(--ui-good) 6%, transparent); }",
         ".ui-row--live { background: #12301f; }"),
        ([], "static/js/ui-parts.js",
         'quiet: "ui-btn ui-btn--quiet"',
         'quiet: "ui-btn ui-btn--hush"'),
    ],
    "check_node_start": [
        ([], "scripts/_js_pins.py", "probe_args(node, harness, path), capture_output=True",
         "[node, \"--import\", f\"data:text/javascript," + "import {{ register }} from 'node:module'; "
         "register('{harness.as_uri()}');\", str(path)], capture_output=True"),
        ([], "scripts/_node.py", 'NODE_FLAGS = ("--single-threaded",)', "NODE_FLAGS = ()"),
        ([], "scripts/check_static_modules.py", "    node = find_node()\n", '    node = shutil.which("node")\n'),
    ],
    "check_same_tab_links": [
        ([], "static/index.html", 'href="/models" data-t="header-models"', 'href="/models" target="caravan-models" data-t="header-models"'),
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
                if not target.is_file():
                    # The public mirror leaves the private deployment out (deploy/nas/): a breakage of a file this tree
                    # does not have cannot be made here. Said and counted apart, so a skip never passes for a pass.
                    SKIP.append(f"{label} (нет {rel})")
                    print(f"  skip {label}: в этом дереве нет {rel}")
                    continue
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
