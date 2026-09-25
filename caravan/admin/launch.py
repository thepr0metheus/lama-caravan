"""Render the launch script: the controller's start-server.sh (its config
block is what every new cell inherits), its snapshots, and the one line a
scout runs a command cell with. The per-cell start.sh scripts under
var/server-cells went with the controller's own cells in step 6.9: every cell
runs through the scout of its machine."""
import os
import re
import shlex

from caravan.admin.config_builder import (
    CONFIG_BEGIN,
    CONFIG_END,
    CONFIG_FIELDS,
    build_config_block,
    build_local_llama_command,
    model_paths,
    quote_shell_value,
)
from caravan.admin.model_stores import MARKER_NAME
from caravan.admin.paths import DEFAULT_MODELS_DIR, START_SCRIPT
from caravan.common.errors import AppError
from caravan.domain.runner import Runner, for_config
from caravan.admin.runners import (
    effective_command,
    uses_command_path,
)


LAUNCH_COMMAND_BEGIN = "# BEGIN LLAMA COMMAND"

LAUNCH_COMMAND_END = "# END LLAMA COMMAND"

def render_command_cell_script(config):
    """Generate a start script for a generic command cell (CELL_KIND="command").

    Runs an arbitrary managed process (e.g. whisper-server) under the same cell
    lifecycle as a llama cell. COMMAND is one shell command line, may reference
    $PORT, and is exec'd so the cell process replaces the shell and whoever
    started it tracks the real PID. Set env inline (`env VAR=val …`) or point
    COMMAND at your own launcher script that exports what it needs. A scout
    runs the same cell as one line (render_command_cell_shell_line).
    """
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    port = merged.get("PORT") or ""
    if not port.isdigit():
        raise AppError("PORT must be a number")
    runner = for_config(merged)
    # Each runner completes and validates the config block for itself: getting
    # this wrong produces a cell that starts and then cannot find its model.
    # It used to be a chain of `elif is_whisper:` here, which meant every new
    # runner was a branch someone had to remember to add.
    command = runner.prepare(merged)

    block_keys = ("RUNNER", "CELL_KIND", "PORT", "HEALTH_PATH", "WORKDIR", "COMMAND",
                  "VLLM_MODEL", "MAX_MODEL_LEN", "GPU_MEMORY_UTILIZATION",
                  "QUANTIZATION", "DTYPE", "TENSOR_PARALLEL", "WHISPER_MODEL",
                  "MOONSHINE_MODEL", "SEAMLESS_TGT_LANG",
                  "TRANSLATE_MODEL", "TRANSLATE_SRC_LANG", "TRANSLATE_TGT_LANG",
                  # transcribe is the one command-path runner with a real model
                  # file; the others leave this empty and the block says so.
                  "MODEL_FILE",
                  "LLAMA_MODELS_DIR", "ALIAS")
    block_lines = [CONFIG_BEGIN]
    # Path-valued keys go through shell_path_value so a configured `~/models`
    # survives as "$HOME/models". quote_shell_value alone would emit "~/models",
    # which bash reads literally — the cell would look for a directory actually
    # named "~". The block is also what the GUI parses back, and $HOME reads
    # correctly there too.
    _PATH_KEYS = ("LLAMA_MODELS_DIR", "WORKDIR")
    for key in block_keys:
        raw = merged.get(key, "")
        if key in _PATH_KEYS and str(raw).strip():
            block_lines.append(f'{key}="{shell_path_value(raw)}"')
        else:
            block_lines.append(f"{key}={quote_shell_value(raw)}")
    block_lines.append(CONFIG_END)
    config_block = "\n".join(block_lines)

    env_exports = command_cell_env_exports(merged.get("ENV"))

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        config_block,
        "",
        f"export PORT={shlex.quote(port)}",
        *env_exports,
    ]
    workdir = shell_path_value(merged.get("WORKDIR"))
    if workdir:
        lines.append(f'cd "{workdir}"')
    boot = runner.bootstrap_lines(merged)
    if boot:
        lines += ["", *boot]
    lines += [
        "",
        LAUNCH_COMMAND_BEGIN + " — generated command cell; edit via the admin UI, not by hand",
        f"exec {command}",
        LAUNCH_COMMAND_END,
        "",
    ]
    return "\n".join(lines)

def shell_path_value(raw) -> str:
    """A configured path as it must appear inside DOUBLE quotes in a start line.

    A leading `~` becomes `$HOME` because quoting defeats tilde expansion: bash
    expands `~/models` but not `"~/models"` or `'~/models'`, and the quotes are
    not optional — a path may contain spaces. Written as `"$HOME/models"` it
    both survives spaces and resolves, including on a client whose home differs
    from the controller's, which is exactly why the controller must not resolve
    it itself.

    Returns "" for an empty value so callers can skip the line entirely.
    """
    v = str(raw or "").strip()
    if not v:
        return ""
    if v == "~":
        v = "$HOME"
    elif v.startswith("~/"):
        v = "$HOME/" + v[2:]
    return v.replace("\\", "\\\\").replace('"', '\\"')


def command_cell_env_exports(env_raw) -> list:
    """`export KEY="VALUE"` lines from the ENV field (newline- or comma-separated).

    Shared by both renderers below, because the agent used to reimplement this
    parser and the two copies were already drifting apart.
    """
    return export_lines(Runner.env_pairs(env_raw))


def export_lines(pairs) -> list:
    """`export KEY="VALUE"` for each (KEY, VALUE) pair — the one way a start
    line exports anything. Double-quoted so paths and spaces survive while
    $VARS still expand."""
    out = []
    for k, v in pairs:
        v = str(v).replace("\\", "\\\\").replace('"', '\\"')
        out.append(f'export {k}="{v}"')
    return out


def one_line_statements(lines):
    """Script lines as the statements of one `;`-joined line. A line that
    opens a block (`… then`, `… do`, `else`) runs on into the next without a
    `;` — `then;` is a syntax error in bash. Blank lines drop out."""
    statements = []
    for raw in lines:
        line = str(raw).strip()
        if not line:
            continue
        if statements and re.search(r"(^|[\s;])(then|do|else)$", statements[-1]):
            statements[-1] += " " + line
        else:
            statements.append(line)
    return statements


def render_command_cell_shell_line(config, port=None) -> str:
    """The same command cell as one `bash -lc` line — how a scout runs it, as
    a child process.

    The client agent used to assemble this itself, mirroring the script renderer
    above — and the mirror had already lost `set -euo pipefail`, so an identical
    config behaved differently depending on which host ran it. The controller is
    the one place that knows how a cell starts; it now says so in full and the
    agent only executes the sentence.

    The runner's bootstrap comes from the same lines as the script's, joined
    into one line. It had a one-line copy of its own, and the copy drifted: it
    installed an unpinned vLLM, and the `exec` in front of the command landed
    in front of the whole chain — bash was replaced by `[`, and a vLLM cell on
    a scout never served.
    """
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    if port is not None:
        merged["PORT"] = str(port)
    resolved_port = merged.get("PORT") or ""
    if not resolved_port.isdigit():
        raise AppError("PORT must be a number")
    command = effective_command(merged)
    if not command:
        raise AppError("command is required for a command cell")
    parts = ["set -euo pipefail", f"export PORT={shlex.quote(resolved_port)}"]
    # The script renderer puts LLAMA_MODELS_DIR in its config block, where the
    # command's ${LLAMA_MODELS_DIR:-…} finds it. A one-line start has no such
    # block, so a client silently fell back to the default while the controller
    # honoured the configured path — the same cell, two model roots.
    models_dir = shell_path_value(merged.get("LLAMA_MODELS_DIR"))
    if models_dir:
        parts.append(f'export LLAMA_MODELS_DIR="{models_dir}"')
    parts += command_cell_env_exports(merged.get("ENV"))
    workdir = shell_path_value(merged.get("WORKDIR"))
    if workdir:
        parts.append(f'cd "{workdir}"')
    parts += one_line_statements(for_config(merged).bootstrap_lines(merged))
    parts.append(f"exec {command}")
    return "; ".join(parts)


def _start_guards(found):
    """What the script checks before it starts: every library it reads from is
    really mounted, and then every file is there.

    The mark comes first, and once per library however many of its files this
    cell reads. Without the mark the share did not mount, and what sits under
    the mount point is the local disk — the file test alone would report the
    model missing and send whoever reads the log looking for a deleted file
    instead of a mount.
    """
    marks, files = [], []
    seen = set()
    for key, what in (("MODEL_FILE", "Model"), ("MMPROJ_FILE", "MMProj"), ("SPEC_DRAFT_MODEL_FILE", "Spec draft")):
        at = found.get(key)
        if not at:
            continue
        if at.in_library and at.store["root"] not in seen:
            seen.add(at.store["root"])
            mark = os.path.join(at.store["root"], MARKER_NAME)
            name = at.store["name"] or at.store["id"]
            marks.append(f'[ -f {shlex.quote(mark)} ] || {{ echo "The library {name} is not mounted at '
                         f'{at.store["root"]} — the model stays there" >&2; exit 1; }}')
        files.append(f'[ -f {shlex.quote(at.path)} ] || {{ echo "{what} not found: {at.path}" >&2; exit 1; }}')
    return marks + files


def render_launch_script(config, locations=None):
    """Generate a complete, self-contained start script.

    Layout:
      header (exports) + the KEY="value" config block (kept so the GUI can
      reload values via parse_config) + a generated `exec llama-server …` block.
    The command block is regenerated from the config block by build_llama_args —
    do not hand-edit it.

    `locations` says where each model file lives right now. A start passes a
    fresh one, so the script points at the library when that is where the file
    is; without it every file is taken to be on the models disk.
    """
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    if uses_command_path(merged):
        return render_command_cell_script(merged)
    if not merged.get("LLAMA_MODELS_DIR"):
        merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
    # build_config_block validates MODEL_FILE / PORT / numeric fields.
    config_block = build_config_block(merged).rstrip("\n")
    cmd = build_local_llama_command(merged, locations=locations)
    if len(cmd) < 2 or "llama-server" not in cmd[0]:
        raise AppError("generated launch command looks invalid", 500)

    guards = _start_guards(model_paths(merged, locations))

    # Quote the binary as a shell var so $LLAMA_HOME stays expandable; quote the
    # rest of the tokens literally.
    exec_line = ('exec "$LLAMA_HOME/build/bin/llama-server" '
                 + " ".join(shlex.quote(x) for x in cmd[1:]) + ' "$@"')

    # What the engine must start with (a CPU-only cell sees no GPU) — the
    # runner's rule, which a scout's start carries too.
    engine_env = export_lines(for_config(merged).launch_env(merged).items())
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'LLAMA_HOME="$HOME/llama.cpp"',
        'export LD_LIBRARY_PATH="$LLAMA_HOME/build/bin:$LLAMA_HOME/build/lib:${LD_LIBRARY_PATH:-}"',
        'export PATH="$LLAMA_HOME/build/bin:$PATH"',
        *engine_env,
        "",
        config_block,
        "",
        LAUNCH_COMMAND_BEGIN + " — generated from the config above by the admin UI; edit via the UI, not by hand",
        *guards,
        exec_line,
        LAUNCH_COMMAND_END,
        "",
    ]
    return "\n".join(lines)

def _sanitize_snapshot_name(name):
    # \w is unicode in py3, so Cyrillic and friends survive; the old ASCII-only
    # class reduced e.g. "тест" to an empty string and the save failed with 400.
    safe = re.sub(r"[^\w.-]+", "-", str(name or "").strip()).strip("-.")
    return safe[:60]

def save_config(config):
    # Variant 2: regenerate the whole script from the single command builder so
    # the config block (for GUI reload) and the exec command never drift. (Its
    # named snapshots, backups and revert went with the controller's own cells
    # in step 6.9 — the cells' own snapshots live on their slots.)
    script = render_launch_script(config)
    START_SCRIPT.write_text(script, encoding="utf-8")
    START_SCRIPT.chmod(0o755)
    return None
