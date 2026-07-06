"""Render launch artifacts: start-server.sh config block, server-cell start.sh
scripts (# BEGIN/END LLAMA COMMAND), snapshots and config save."""
import json
import re
import shlex
import shutil
import time
from datetime import datetime

from caravan.admin.config_builder import (
    CONFIG_BEGIN,
    CONFIG_END,
    CONFIG_FIELDS,
    _join_models_path,
    build_config_block,
    build_local_llama_command,
    is_command_cell,
    quote_shell_value,
)
from caravan.admin.paths import DEFAULT_MODELS_DIR, SERVER_CELLS_DIR, START_SCRIPT
from caravan.common.errors import AppError
from caravan.admin.runners import (
    VLLM_BOOTSTRAP_LINES,
    build_vllm_command,
    build_whisper_command,
    runner_id,
    uses_command_path,
)


LAUNCH_COMMAND_BEGIN = "# BEGIN LLAMA COMMAND"

LAUNCH_COMMAND_END = "# END LLAMA COMMAND"

def render_command_cell_script(config):
    """Generate start.sh for a generic command cell (CELL_KIND="command").

    Runs an arbitrary managed process (e.g. whisper-server) under the exact same
    cell lifecycle as a llama cell — systemd `lama-cell@PORT` on Skynet, or the
    route-agent on a client. COMMAND is one shell command line, may reference
    $PORT, and is exec'd so the cell process replaces the shell and systemd/the
    agent tracks the real PID. Set env inline (`env VAR=val …`) or point COMMAND
    at your own launcher script that exports what it needs.
    """
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    port = merged.get("PORT") or ""
    if not port.isdigit():
        raise AppError("PORT must be a number")
    is_vllm = runner_id(merged) == "vllm"
    is_whisper = runner_id(merged) == "whisper"
    if is_vllm:
        if not merged.get("VLLM_MODEL"):
            raise AppError("VLLM_MODEL is required for a vLLM cell")
        command = build_vllm_command(merged)
    elif is_whisper:
        # The command references ${LLAMA_MODELS_DIR} for the shared model root —
        # make sure the config block carries a concrete value on the controller.
        if not merged.get("LLAMA_MODELS_DIR"):
            merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
        command = build_whisper_command(merged)
    else:
        # Be forgiving: strip a leading `exec ` — we add our own.
        command = re.sub(r"^\s*exec\s+", "", merged.get("COMMAND") or "").strip()
        if not command:
            raise AppError("COMMAND is required for a command cell")
        merged["COMMAND"] = command  # keep the config block and the exec line in sync

    block_keys = ("RUNNER", "CELL_KIND", "PORT", "HEALTH_PATH", "WORKDIR", "COMMAND",
                  "VLLM_MODEL", "MAX_MODEL_LEN", "GPU_MEMORY_UTILIZATION",
                  "QUANTIZATION", "DTYPE", "TENSOR_PARALLEL", "WHISPER_MODEL",
                  "LLAMA_MODELS_DIR", "ALIAS")
    block_lines = [CONFIG_BEGIN]
    for key in block_keys:
        block_lines.append(f"{key}={quote_shell_value(merged.get(key, ''))}")
    block_lines.append(CONFIG_END)
    config_block = "\n".join(block_lines)

    # ENV: newline- or comma-separated KEY=VALUE, rendered as `export KEY="VALUE"`
    # (double-quoted so paths/spaces are safe but $VARS still expand).
    env_exports = []
    for raw in re.split(r"[\n,]", merged.get("ENV") or ""):
        item = raw.strip()
        if not item or item.startswith("#") or "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            continue
        v = v.strip().replace("\\", "\\\\").replace('"', '\\"')
        env_exports.append(f'export {k}="{v}"')

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        config_block,
        "",
        f"export PORT={shlex.quote(port)}",
        *env_exports,
    ]
    workdir = merged.get("WORKDIR") or ""
    if workdir:
        lines.append(f"cd {shlex.quote(workdir)}")
    if is_vllm:
        lines += ["", *VLLM_BOOTSTRAP_LINES]
    lines += [
        "",
        LAUNCH_COMMAND_BEGIN + " — generated command cell; edit via the admin UI, not by hand",
        f"exec {command}",
        LAUNCH_COMMAND_END,
        "",
    ]
    return "\n".join(lines)

def render_launch_script(config):
    """Generate a complete, self-contained start script.

    Layout:
      header (exports) + the KEY="value" config block (kept so the GUI can
      reload values via parse_config) + a generated `exec llama-server …` block.
    The command block is regenerated from the config block by build_llama_args —
    do not hand-edit it.
    """
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    if uses_command_path(merged):
        return render_command_cell_script(merged)
    if not merged.get("LLAMA_MODELS_DIR"):
        merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
    # build_config_block validates MODEL_FILE / PORT / numeric fields.
    config_block = build_config_block(merged).rstrip("\n")
    cmd = build_local_llama_command(merged)
    if len(cmd) < 2 or "llama-server" not in cmd[0]:
        raise AppError("generated launch command looks invalid", 500)

    models_dir = merged["LLAMA_MODELS_DIR"]
    model_abs = _join_models_path(models_dir, merged.get("MODEL_FILE"))
    mmproj_abs = _join_models_path(models_dir, merged.get("MMPROJ_FILE"))
    spec_abs = _join_models_path(models_dir, merged.get("SPEC_DRAFT_MODEL_FILE"))

    guards = [f'[ -f {shlex.quote(model_abs)} ] || {{ echo "Model not found: {model_abs}" >&2; exit 1; }}']
    if mmproj_abs:
        guards.append(f'[ -f {shlex.quote(mmproj_abs)} ] || {{ echo "MMProj not found: {mmproj_abs}" >&2; exit 1; }}')
    if spec_abs:
        guards.append(f'[ -f {shlex.quote(spec_abs)} ] || {{ echo "Spec draft not found: {spec_abs}" >&2; exit 1; }}')

    # Quote the binary as a shell var so $LLAMA_HOME stays expandable; quote the
    # rest of the tokens literally.
    exec_line = ('exec "$LLAMA_HOME/build/bin/llama-server" '
                 + " ".join(shlex.quote(x) for x in cmd[1:]) + ' "$@"')

    # CPU mode (n-gpu-layers 0): hide GPUs entirely. A CUDA-enabled llama.cpp build
    # still initializes the CUDA backend and queries device memory even with -ngl 0
    # (in common_params_print_info), which ABORTS with "CUDA error: out of memory"
    # when the GPU is already full — e.g. an embeddings cell on CPU on a host whose
    # GPU runs another model. Empty CUDA_VISIBLE_DEVICES makes CUDA report no devices,
    # so it falls back to CPU cleanly. (--device none is NOT enough: it stops
    # offloading but the backend still inits and OOMs.)
    cpu_only_env = ['export CUDA_VISIBLE_DEVICES=""'] \
        if str(merged.get("N_GPU_LAYERS") or "").strip() == "0" else []
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'LLAMA_HOME="$HOME/llama.cpp"',
        'export LD_LIBRARY_PATH="$LLAMA_HOME/build/bin:$LLAMA_HOME/build/lib:${LD_LIBRARY_PATH:-}"',
        'export PATH="$LLAMA_HOME/build/bin:$PATH"',
        *cpu_only_env,
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

def server_cell_dir(port):
    return SERVER_CELLS_DIR / str(int(port))

def render_server_cell_script(config):
    return render_launch_script(config)

def write_server_cell_artifacts(host_id, port, config):
    """Write the generated launch files for a configured server cell.

    cell.json is the structured source snapshot for humans/tools; start.sh is the
    executable artifact a future lama-cell@PORT.service can run directly.
    """
    if not isinstance(config, dict):
        return {}
    if not uses_command_path(config) and not str(config.get("MODEL_FILE") or "").strip():
        return {}
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    merged["PORT"] = str(port)
    if not merged.get("LLAMA_MODELS_DIR"):
        merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
    script = render_server_cell_script(merged)
    cell_dir = server_cell_dir(port)
    cell_dir.mkdir(parents=True, exist_ok=True)
    start_path = cell_dir / "start.sh"
    json_path = cell_dir / "cell.json"
    tmp_start = start_path.with_suffix(".sh.tmp")
    tmp_json = json_path.with_suffix(".json.tmp")
    tmp_start.write_text(script, encoding="utf-8")
    tmp_start.chmod(0o755)
    tmp_start.replace(start_path)
    cell_payload = {
        "hostId": str(host_id),
        "port": int(port),
        "config": merged,
        "generatedAt": int(time.time()),
        "startScript": str(start_path),
    }
    tmp_json.write_text(json.dumps(cell_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_json.replace(json_path)
    return {
        "dir": str(cell_dir),
        "startScript": str(start_path),
        "cellJson": str(json_path),
        "generatedAt": cell_payload["generatedAt"],
    }

def _sanitize_snapshot_name(name):
    # \w is unicode in py3, so Cyrillic and friends survive; the old ASCII-only
    # class reduced e.g. "тест" to an empty string and the save failed with 400.
    safe = re.sub(r"[^\w.-]+", "-", str(name or "").strip()).strip("-.")
    return safe[:60]

def snapshot_config(name, config=None):
    """Save a NAMED snapshot of a launcher config.

    Manual-only — replaces the old save-on-every-write auto-backup.

    When `config` (the live form values) is supplied we render a fresh
    start-server.sh from it, so the snapshot captures exactly what the user is
    looking at — including a server cell's own CTX_SIZE / model / port, which are
    NOT in the controller's start-server.sh. Without a config (legacy callers) we
    fall back to copying the controller's current start-server.sh.
    """
    safe = _sanitize_snapshot_name(name)
    if not safe:
        raise AppError("Snapshot name is required")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = START_SCRIPT.with_name(f"{START_SCRIPT.name}.bak.{stamp}-{safe}")
    if isinstance(config, dict) and str(config.get("MODEL_FILE") or "").strip():
        script = render_launch_script(config)
        target.write_text(script, encoding="utf-8")
        target.chmod(0o755)
    else:
        shutil.copy2(START_SCRIPT, target)
    return str(target)

def save_config(config):
    # Variant 2: regenerate the whole script from the single command builder so
    # the config block (for GUI reload) and the exec command never drift.
    # No auto-backup: snapshots are explicit via snapshot_config().
    script = render_launch_script(config)
    START_SCRIPT.write_text(script, encoding="utf-8")
    START_SCRIPT.chmod(0o755)
    return None
