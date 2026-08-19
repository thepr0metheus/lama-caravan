#!/usr/bin/env python3
"""Every launch-config field must have a home the operator can be sent to.

The config editor has eleven tabs. Finding a setting in it depends on one
promise: that each field belongs to exactly one group, and each group to a tab.
The search box and the hover-a-flag-find-its-input link both resolve through
that map, so a field with no group is a field the search can name but never
point at — and to the operator it looks identical to a setting that does not
exist. This is the codebase's recurring defect: absence rendered as normality.

A list cannot enforce itself, so this runs in CI. Adding a field to
CONFIG_FIELDS now forces one of two deliberate acts: give it a group in
advancedGroups, or record here why it has no tab. Forgetting is no longer
one of the options.

Also checks the reverse: a group naming a field that no longer exists renders
an empty slot, and a field in two groups makes "where is it?" ambiguous.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.config_builder import CONFIG_FIELDS  # noqa: E402

# Fields deliberately rendered outside the tabbed area. Each is still findable
# by the search (it indexes any field with a live input, wherever it sits) and
# still highlightable on hover; it simply has no tab to light up. Adding to
# this list is a claim that the field is rendered somewhere else — make it only
# when that is true.
NO_TAB = {
    # Model pickers in the editor's top pane, above the tabs.
    "LLAMA_MODELS_DIR": "models-dir picker, top pane",
    "MODEL_FILE": "model picker, top pane",
    "MMPROJ_FILE": "mmproj companion row, top pane",
    "SPEC_DRAFT_MODEL_FILE": "draft-model picker, top pane",
    "OFFLOAD_MMPROJ": "checkbox inside the mmproj companion row",
    "CHAT_TEMPLATE_FILE": "chat-template panel, transplanted into a tab body",
    "EXTRA_ARGS": "pinned to the top of the Favorites tab",
    # Non-llama runners: their panels replace the llama tabs entirely.
    "RUNNER": "runner selector, above the tabs",
    "CELL_KIND": "legacy mirror of RUNNER, not rendered",
    "COMMAND": "command-cell panel",
    "HEALTH_PATH": "command-cell panel",
    "ENV": "command-cell panel",
    "WORKDIR": "command-cell panel",
    "VLLM_MODEL": "vLLM runner panel",
    "MAX_MODEL_LEN": "vLLM runner panel",
    "GPU_MEMORY_UTILIZATION": "vLLM runner panel",
    "QUANTIZATION": "vLLM runner panel",
    "DTYPE": "vLLM runner panel",
    "TENSOR_PARALLEL": "vLLM runner panel",
    "WHISPER_MODEL": "whisper runner panel",
    "MOONSHINE_MODEL": "moonshine runner panel",
    "SEAMLESS_TGT_LANG": "seamless runner panel",
    "TRANSLATE_MODEL": "translate runner panel",
    "TRANSLATE_SRC_LANG": "translate runner panel",
    "TRANSLATE_TGT_LANG": "translate runner panel",
}

CONSTANTS = ROOT / "static/js/constants.js"


def parse_groups(text):
    """[(groupKey, [FIELD, ...]), ...] from the advancedGroups literal."""
    start = text.index("export const advancedGroups")
    end = text.index("export const advancedTabDefs")
    out = []
    for line in text[start:end].splitlines():
        key = re.search(r'titleKey:\s*"([^"]+)"', line)
        if not key:
            continue
        fields = re.findall(r'"([A-Z][A-Z0-9_]*)"', line)
        out.append((key.group(1), fields))
    return out


def parse_tabs(text):
    """[(tabKey, [groupKey, ...]), ...] from the advancedTabDefs literal."""
    start = text.index("export const advancedTabDefs")
    out = []
    for line in text[start:].splitlines():
        key = re.search(r'key:\s*"([^"]+)"', line)
        if not key:
            if line.strip().startswith("];"):
                break
            continue
        groups = re.findall(r'"(grp[A-Za-z0-9]+|advanced[A-Za-z0-9]+)"', line)
        out.append((key.group(1), [g for g in groups if g != key.group(1)]))
    return out


INDEX_HTML = ROOT / "static/index.html"
EDIT_JS = ROOT / "static/js/llama-edit.js"

# Panels the editor populates from the saved config, by field id. Anything a
# runner renders must sit inside one of them or it never gets its saved value.
PANEL_IDS = ["commandFields", "vllmFields", "whisperFields", "moonshineFields",
             "seamlessFields", "translateFields"]


def check_runner_panel_fields():
    """A runner-panel field must live inside a panel the loader walks.

    The loader used to name its fields one by one, and the seamless and
    translate panels were never added — so a cell saved with SEAMLESS_TGT_LANG
    = eng opened showing the select's default "rus". The form presented its own
    default as the cell's setting, which is indistinguishable from the cell
    really being set that way, and Apply then wrote the default back.

    Two things are checked: the loader still walks every panel that exists in
    the markup, and each NO_TAB field claiming a runner panel is really inside
    one.
    """
    errors = []
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = EDIT_JS.read_text(encoding="utf-8")

    # The loader's own array, not merely a mention of the name elsewhere in the
    # file — the first version of this check passed while the panel was removed
    # from the loader, because applyCellKindUI names it too.
    m_loader = re.search(r'\[([^\]]*?Fields"[^\]]*)\]\.forEach\(\(panel\)', js, re.S)
    loader_panels = set(re.findall(r'"([a-zA-Z]+Fields)"', m_loader.group(1))) if m_loader else set()
    if not loader_panels:
        errors.append("could not find the runner-panel loader array in llama-edit.js")

    for panel in re.findall(r'id="te-([a-zA-Z]+Fields)"', html):
        if panel in ("llamaFields", "dynamicFields"):
            continue                      # llama fields load through their own path
        if panel not in PANEL_IDS:
            errors.append(f"panel {panel} exists in index.html but is not in PANEL_IDS here")
        if panel not in loader_panels:
            errors.append(f"panel {panel} is not in the loader's list in llama-edit.js — "
                          f"its fields would open showing defaults, not saved values")

    # Which ids sit inside each panel: crude but enough — panels are flat blocks.
    inside = set()
    for panel in PANEL_IDS:
        m = re.search(rf'id="te-{panel}"', html)
        if not m:
            continue
        chunk = html[m.end():m.end() + 6000]
        inside.update(re.findall(r'id="te-([A-Z][A-Z0-9_]*)"', chunk))

    for field, where in NO_TAB.items():
        if "runner panel" not in where and "vLLM runner" not in where:
            continue
        if field not in inside:
            errors.append(f"{field} says it is rendered in a runner panel, but no "
                          f'id="te-{field}" appears inside one — the loader cannot reach it')
    return errors


def main():
    text = CONSTANTS.read_text(encoding="utf-8")
    groups = parse_groups(text)
    tabs = parse_tabs(text)

    homes = {}
    duplicates = []
    for group_key, fields in groups:
        for field in fields:
            if field in homes:
                duplicates.append((field, homes[field], group_key))
            else:
                homes[field] = group_key

    errors = []

    # 1. Groups must be reachable from a tab, or their fields are unreachable.
    tabbed_groups = {g for _key, gs in tabs for g in gs}
    for group_key, _fields in groups:
        if group_key not in tabbed_groups:
            errors.append(f"group {group_key} is on no tab — its fields cannot be reached")
    for tab_key, group_keys in tabs:
        for group_key in group_keys:
            if group_key not in {g for g, _f in groups}:
                errors.append(f"tab {tab_key} names group {group_key}, which does not exist")

    # 2. Every field either has a group or a recorded reason not to.
    for field in CONFIG_FIELDS:
        if field in homes or field in NO_TAB:
            continue
        errors.append(
            f"{field} has no group in advancedGroups and no entry in NO_TAB.\n"
            f"        Give it a group (it then becomes searchable and highlightable\n"
            f"        automatically), or add it to NO_TAB in {Path(__file__).name}\n"
            f"        stating where it IS rendered.")

    # 3. No field claimed twice, and none claimed that no longer exists.
    for field, first, second in duplicates:
        errors.append(f"{field} is in two groups ({first}, {second}) — its location is ambiguous")
    for field in sorted(set(homes) - set(CONFIG_FIELDS)):
        errors.append(f"group {homes[field]} names {field}, which is not a CONFIG_FIELDS entry")
    for field in sorted(set(NO_TAB) - set(CONFIG_FIELDS)):
        errors.append(f"NO_TAB names {field}, which is not a CONFIG_FIELDS entry — stale entry")

    errors.extend(check_runner_panel_fields())

    if errors:
        print("field homes: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"field homes OK: {len(homes)} fields across {len(groups)} groups / "
          f"{len(tabs)} tabs, {len(NO_TAB)} rendered outside the tabs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
