"""Composite dashboard state (/api/state), service actions and llama.cpp
version/update handling."""
import os
import time
from datetime import datetime

from caravan.admin.backups import backups
from caravan.admin.config_builder import (
    CONFIG_FIELDS,
    FIELD_HELP,
    models_dir_from_config,
    parse_config,
)
from caravan.admin.llama_metrics import runtime_phase
from caravan.admin.models import list_chat_templates, list_models
from caravan.admin.monitoring import cpu_state, gpu_state, memory_state, runtime_api
from caravan.admin.openclaw import notify_openclaw_config_managers, openclaw_config_manager_state
from caravan.admin.paths import LLAMA_HOME, PROJECT_ROOT, SERVER_CELLS_DIR, SERVICE_NAME, START_SCRIPT
from caravan.admin.state import admin_state
from caravan.admin.systemd_ctl import logs, service_status, systemctl, user_service_diagnostics
from caravan.common.errors import AppError
from caravan.common.procs import run, run_in


def project_git_info():
    head = run_in(["git", "rev-parse", "--short", "HEAD"], timeout=3, cwd=PROJECT_ROOT)
    branch = run_in(["git", "branch", "--show-current"], timeout=3, cwd=PROJECT_ROOT)
    dirty = run_in(["git", "status", "--porcelain"], timeout=3, cwd=PROJECT_ROOT)
    branch_name = branch["stdout"].strip()
    if not branch_name:
        branch_name = "detached"
    return {
        "branch": branch_name if branch["ok"] else "",
        "head": head["stdout"].strip() if head["ok"] else "",
        "dirtyCount": len([line for line in dirty["stdout"].splitlines() if line.strip()]) if dirty["ok"] else 0,
        "ok": head["ok"] and branch["ok"],
        "error": "" if head["ok"] and branch["ok"] else (head["stderr"] or branch["stderr"]),
    }

def state():
    config = parse_config()
    service = service_status()
    runtime = runtime_api(config)
    runtime["status"] = runtime_phase(service, runtime)
    return {
        "config": config,
        "fields": CONFIG_FIELDS,
        "help": FIELD_HELP,
        "favFields": [f for f in admin_state.get("favFields", []) if f in CONFIG_FIELDS],
        "paths": {
            "llamaHome": str(LLAMA_HOME),
            "startScript": str(START_SCRIPT),
            "serverCellsDir": str(SERVER_CELLS_DIR),
            "modelsDir": str(models_dir_from_config(config)),
            "service": SERVICE_NAME,
        },
        "models": list_models(config),
        "chatTemplates": list_chat_templates(config),
        "service": service,
        "runtime": runtime,
        "diagnostics": user_service_diagnostics(service, runtime),
        "cpu": cpu_state(),
        "gpu": gpu_state(),
        "memory": memory_state(),
        "llamaCpp": llama_cpp_info(fetch_remote=False),
        "logs": logs(),
        "backups": backups(),
        "openclawConfigManagers": openclaw_config_manager_state(),
        "projectGit": project_git_info(),
        "time": int(time.time()),
    }

def do_action(action):
    if action not in {"start", "stop", "restart"}:
        raise AppError("Unsupported action")
    result = systemctl(action, SERVICE_NAME, timeout=30)
    if not result["ok"]:
        raise AppError(result["stderr"] or f"systemctl {action} failed", 500)
    if action in {"start", "restart"}:
        result["openclawConfigManagers"] = notify_openclaw_config_managers()
    return result

def llama_server_path():
    return LLAMA_HOME / "build" / "bin" / "llama-server"

def llama_cpp_info(fetch_remote=False):
    binary = llama_server_path()
    version = run([str(binary), "--version"], timeout=5) if binary.exists() else {"ok": False, "stdout": "", "stderr": "llama-server binary not found"}
    help_text = run([str(binary), "--help"], timeout=5) if binary.exists() else {"ok": False, "stdout": "", "stderr": "llama-server binary not found"}
    head = run_in(["git", "rev-parse", "--short", "HEAD"], timeout=5, cwd=LLAMA_HOME)
    branch = run_in(["git", "branch", "--show-current"], timeout=5, cwd=LLAMA_HOME)
    remote = run_in(["git", "config", "--get", "remote.origin.url"], timeout=5, cwd=LLAMA_HOME)
    dirty = run_in(["git", "status", "--porcelain"], timeout=5, cwd=LLAMA_HOME)
    tracked_dirty = run_in(["git", "status", "--porcelain", "--untracked-files=no"], timeout=5, cwd=LLAMA_HOME)
    upstream = {"ok": False, "stdout": "", "stderr": "Not checked"}
    upstream_tags = {"ok": False, "stdout": "", "stderr": "Not checked"}
    if fetch_remote:
        upstream = run_in(["git", "ls-remote", "origin", "HEAD"], timeout=30, cwd=LLAMA_HOME)
        upstream_tags = run_in(["git", "ls-remote", "--tags", "origin", "refs/tags/b[0-9]*"], timeout=30, cwd=LLAMA_HOME)
    binary_stat = binary.stat() if binary.exists() else None
    # Parse highest bXXXX build number from remote tags
    upstream_build = 0
    if upstream_tags["ok"] and upstream_tags["stdout"].strip():
        import re as _re
        for line in upstream_tags["stdout"].splitlines():
            m = _re.search(r"refs/tags/b(\d+)$", line.strip())
            if m:
                upstream_build = max(upstream_build, int(m.group(1)))
    return {
        "binary": str(binary),
        "binaryExists": binary.exists(),
        "binaryMtime": datetime.fromtimestamp(binary_stat.st_mtime).isoformat(timespec="seconds") if binary_stat else "",
        "version": (version["stdout"] or version["stderr"]).strip(),
        "supportsChatTemplateFile": "--chat-template-file" in (help_text["stdout"] + help_text["stderr"]),
        "git": {
            "branch": branch["stdout"].strip(),
            "head": head["stdout"].strip(),
            "remote": remote["stdout"].strip(),
            "dirtyCount": len([line for line in dirty["stdout"].splitlines() if line.strip()]),
            "trackedDirtyCount": len([line for line in tracked_dirty["stdout"].splitlines() if line.strip()]),
            "trackedDirtySample": tracked_dirty["stdout"].splitlines()[:12],
            "upstreamHead": upstream["stdout"].split()[0][:12] if upstream["ok"] and upstream["stdout"].strip() else "",
            "upstreamBuild": upstream_build,
            "upstreamChecked": fetch_remote,
            "upstreamError": "" if upstream["ok"] else upstream["stderr"],
        },
    }

def update_llama_cpp():
    info = llama_cpp_info(fetch_remote=True)
    if info["git"]["trackedDirtyCount"]:
        sample = "\n".join(info["git"]["trackedDirtySample"])
        raise AppError(f"llama.cpp has tracked local changes. Clean or review them before update.\n{sample}", 409)
    steps = []

    def step(label, cmd, timeout=60):
        result = run_in(cmd, timeout=timeout, cwd=LLAMA_HOME)
        steps.append({"label": label, "cmd": " ".join(cmd), **result})
        if not result["ok"]:
            raise AppError(f"{label} failed:\n{result['stderr'] or result['stdout']}", 500)
        return result

    branch = info["git"]["branch"] or "master"
    step("fetch", ["git", "fetch", "origin"], timeout=120)
    step("merge", ["git", "merge", "--ff-only", f"origin/{branch}"], timeout=120)
    step("build", ["cmake", "--build", "build", "--target", "llama-server", "-j", str(os.cpu_count() or 4)], timeout=3600)
    return {"steps": steps, "info": llama_cpp_info(fetch_remote=True)}
