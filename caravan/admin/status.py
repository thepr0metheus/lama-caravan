"""Composite dashboard state (/api/state), service actions and llama.cpp
version/update handling."""
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from caravan.admin.backups import backups
from caravan.admin.runners import RUNNERS
from caravan.admin.config_builder import (
    CONFIG_FIELDS,
    FIELD_HELP,
    models_dir_from_config,
    parse_config,
)
from caravan.admin.llama_metrics import runtime_phase
from caravan.admin.models import list_chat_templates, list_models, list_st_artifacts, list_whisper_sizes
from caravan.admin.monitoring import cpu_state, gpu_state, memory_state, runtime_api
from caravan.admin.openclaw import notify_openclaw_config_managers, openclaw_config_manager_state
from caravan.admin.paths import ADMIN_SERVICE_NAME, AGENT_PROXY_SERVICE_NAME, IS_CONTAINER, LLAMA_HOME, PROJECT_ROOT, SERVER_CELLS_DIR, SERVICE_NAME, START_SCRIPT
from caravan.admin.state import admin_state
from caravan.admin.systemd_ctl import logs, service_status, systemctl, user_service_diagnostics
from caravan import __version__ as APP_VERSION
from caravan.common.errors import AppError
from caravan.common.procs import run, run_in


def project_git_info():
    head = run_in(["git", "rev-parse", "--short", "HEAD"], timeout=3, cwd=PROJECT_ROOT)
    branch = run_in(["git", "branch", "--show-current"], timeout=3, cwd=PROJECT_ROOT)
    dirty = run_in(["git", "status", "--porcelain"], timeout=3, cwd=PROJECT_ROOT)
    if not head["ok"]:
        # The Docker image ships without .git — the build bakes the commit in.
        baked = os.environ.get("CARAVAN_GIT_HEAD", "").strip()
        if baked:
            return {"branch": "docker", "head": baked, "dirtyCount": 0, "ok": True, "error": ""}
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

def _container_briefs():
    """Container substitutes for the two service chips: the admin is this very
    process, the proxy is the supervised child — same keys as _unit_brief."""
    from caravan.admin import proxy_supervisor
    stamp = lambda epoch: datetime.fromtimestamp(epoch).strftime("%a %Y-%m-%d %H:%M:%S") if epoch else ""
    proxy = proxy_supervisor.status()
    return [
        {"unit": "lama-caravan (container)", "ok": True, "active": "active", "sub": "running",
         "pid": str(os.getpid()), "since": stamp(_ADMIN_STARTED_AT)},
        {"unit": "agent-proxies (child)", "ok": True,
         "active": proxy["activeState"], "sub": proxy["subState"],
         "pid": str(proxy["pid"]), "since": stamp(proxy["sinceEpoch"])},
    ]

_ADMIN_STARTED_AT = int(time.time())

def _unit_brief(unit):
    show = systemctl("show", unit, "-p", "ActiveState", "-p", "SubState",
                     "-p", "MainPID", "-p", "ExecMainStartTimestamp", timeout=5)
    props = {}
    for line in show["stdout"].splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key] = value
    return {
        "unit": unit,
        "ok": show["ok"],
        "active": props.get("ActiveState", ""),
        "sub": props.get("SubState", ""),
        "pid": props.get("MainPID", "0"),
        "since": props.get("ExecMainStartTimestamp", ""),
    }

def models_disk():
    """Cheap disk headroom for the models dir (the /hf page badge + the
    pre-download check) — no systemctl calls, unlike controller_info()."""
    import shutil
    config = parse_config()
    models_dir = models_dir_from_config(config)
    try:
        usage = shutil.disk_usage(str(models_dir))
        return {"ok": True, "path": str(models_dir),
                "totalGb": round(usage.total / 2**30, 1),
                "freeGb": round(usage.free / 2**30, 1)}
    except OSError as exc:
        return {"ok": False, "path": str(models_dir), "error": str(exc)}

def controller_info():
    """The Controller card in the System modal: what THIS host runs (admin +
    proxy services, cell units, app git, python) and whether the models disk
    has room — the questions asked before/after every deploy or download."""
    import shutil
    import sys
    config = parse_config()
    models_dir = models_dir_from_config(config)
    info = {
        "ok": True,
        "appVersion": APP_VERSION,
        "python": sys.version.split()[0],
        "container": IS_CONTAINER,
        "projectGit": project_git_info(),
        "services": _container_briefs() if IS_CONTAINER
                    else [_unit_brief(ADMIN_SERVICE_NAME), _unit_brief(AGENT_PROXY_SERVICE_NAME)],
        "cells": {},
        "disk": {},
        "models": {},
        "time": int(time.time()),
    }
    cells = systemctl("list-units", "lama-cell@*", "--no-legend", "--plain", timeout=5)
    if cells["ok"]:
        lines = [line for line in cells["stdout"].splitlines() if line.strip()]
        info["cells"] = {
            "total": len(lines),
            "running": sum(1 for line in lines if " running " in f" {line} "),
        }
    try:
        usage = shutil.disk_usage(str(models_dir))
        info["disk"] = {
            "path": str(models_dir),
            "totalGb": round(usage.total / 2**30, 1),
            "freeGb": round(usage.free / 2**30, 1),
            "usedGb": round((usage.total - usage.free) / 2**30, 1),
        }
    except OSError as exc:
        info["disk"] = {"path": str(models_dir), "error": str(exc)}
    try:
        sizes = [f.stat().st_size for f in models_dir.rglob("*.gguf")]
        info["models"] = {"count": len(sizes), "totalGb": round(sum(sizes) / 2**30, 1)}
    except OSError:
        pass
    return info

def state():
    config = parse_config()
    service = service_status()
    runtime = runtime_api(config)
    runtime["status"] = runtime_phase(service, runtime)
    return {
        "appVersion": APP_VERSION,
        "container": IS_CONTAINER,
        "runners": RUNNERS,
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
        "artifacts": list_st_artifacts(config),
        "whisperOnDisk": list_whisper_sizes(config),
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
    if IS_CONTAINER:
        raise AppError("the legacy single-server unit does not exist in container mode — "
                       "serve models from caravan-scout hosts", 400)
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
    # Parse the highest bXXXX build number from remote tags — AND its commit.
    # Local clones report a clone-local commit COUNT as their build number
    # (a shallow clone undercounts massively), so "local 731 < upstream 9947"
    # says nothing; identity is the commit sha. Annotated tags list twice
    # (refs/tags/bN and refs/tags/bN^{}); the peeled ^{} sha is the commit.
    upstream_build, upstream_build_commit = 0, ""
    if upstream_tags["ok"] and upstream_tags["stdout"].strip():
        best = {}
        for line in upstream_tags["stdout"].splitlines():
            m = re.match(r"^([0-9a-f]{7,40})\s+refs/tags/b(\d+)(\^\{\})?$", line.strip())
            if not m:
                continue
            sha, num, peeled = m.group(1), int(m.group(2)), bool(m.group(3))
            if peeled or num not in best:
                best[num] = sha
        if best:
            upstream_build = max(best)
            upstream_build_commit = best[upstream_build][:12]
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
            "upstreamBuildCommit": upstream_build_commit,
            "upstreamChecked": fetch_remote,
            "upstreamError": "" if upstream["ok"] else upstream["stderr"],
        },
    }

# ── llama.cpp update job ──────────────────────────────────────────────────────
# The update runs scripts/install-llama.sh (--force --no-restart): the script
# owns the whole pipeline — fetch/checkout the release tag, the probe-gated
# Blackwell workaround, cmake build, UI-asset fallback. A build takes 10-20
# minutes, far beyond an HTTP request, so it runs as a background thread whose
# output streams into a ring buffer the UI polls. Running cells keep serving
# the OLD binary (they hold its inode) until restarted by hand — deliberate.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_llama_update_lock = threading.Lock()
_llama_update_job = {"running": False, "startedAt": 0, "tag": "", "lines": [],
                     "done": False, "rc": None, "error": ""}

def llama_update_status():
    with _llama_update_lock:
        snap = dict(_llama_update_job)
        snap["lines"] = list(_llama_update_job["lines"])[-200:]
        return snap

LLAMA_BUILDS_DIR = Path(os.environ.get("LLAMA_BUILDS_DIR")
                        or Path.home() / ".local" / "share" / "lama-caravan" / "llama-builds")

def llama_builds_list():
    """Archived build snapshots (newest first) — install-llama.sh writes one
    per successful build and prunes to LLAMA_BUILDS_KEEP (default 5)."""
    import json as _json
    rows = []
    if LLAMA_BUILDS_DIR.is_dir():
        for entry in sorted(LLAMA_BUILDS_DIR.iterdir(), reverse=True):
            meta = entry / "meta.json"
            if not meta.is_file():
                continue
            try:
                row = _json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                continue
            row["id"] = entry.name
            rows.append(row)
    return {"ok": True, "builds": rows, "keep": int(os.environ.get("LLAMA_BUILDS_KEEP") or 5)}

# ── crash watchdog: a fresh build + crashing cells ⇒ offer a rollback ────────
# Cheap and stateless: only when the on-disk binary is younger than
# LLAMA_SUSPECT_BUILD_AGE_H (default 6h) scan the last 15 min of lama-cell@*
# journal for crash markers; at ≥ LLAMA_SUSPECT_MIN_CRASHES (default 3) the
# board shows a prominent banner offering to restore the previous archived
# build — restore itself always waits for the user's confirmation.
_suspect_cache = {"t": 0.0, "data": {"suspect": False}}

def llama_crash_suspect():
    now = time.time()
    if now - _suspect_cache["t"] < 60:
        return _suspect_cache["data"]
    data = {"suspect": False}
    try:
        min_crashes = int(os.environ.get("LLAMA_SUSPECT_MIN_CRASHES") or 3)
        max_age_h = float(os.environ.get("LLAMA_SUSPECT_BUILD_AGE_H") or 6)
        binary = llama_server_path()
        built_at = binary.stat().st_mtime if binary.exists() else 0
        if built_at and (now - built_at) < max_age_h * 3600:
            out = run(["journalctl", "--user", "-u", "lama-cell@*",
                       "--since", "-15 minutes", "--no-pager", "-o", "cat"], timeout=10)
            text = out.get("stdout") or ""
            crashes = len(re.findall(
                r"CUDA error|GGML_ABORT|SIGSEGV|SIGABRT|Aborted \(core dumped\)", text))
            if crashes >= min_crashes:
                head = run_in(["git", "rev-parse", "--short", "HEAD"],
                              timeout=5, cwd=LLAMA_HOME)["stdout"].strip()
                prev = next((b for b in llama_builds_list()["builds"]
                             if b.get("commit") and head
                             and not head.startswith(b["commit"])
                             and not b["commit"].startswith(head)), None)
                data = {"suspect": True, "crashes15m": crashes,
                        "builtAt": int(built_at), "currentCommit": head,
                        "restoreCandidate": prev}
    except Exception:
        data = {"suspect": False}
    _suspect_cache.update(t=now, data=data)
    return data

def start_llama_restore(build_id):
    """Restore an archived build (copy back + checkout its commit) as the same
    background job the update uses — one shared runner, one status endpoint."""
    build_id = str(build_id or "").strip()
    if not build_id:
        raise AppError("build id is required", 400)
    return start_llama_update(restore_id=build_id)

def start_llama_update(tag="", restore_id=""):
    """Kick off the background update (or an archive restore when restore_id
    is set). Empty tag → the script resolves the latest upstream release tag
    itself. 409 while a job is still running; finished jobs are replaced."""
    if IS_CONTAINER:
        raise AppError("the container image has no llama.cpp build environment — "
                       "update llama.cpp on caravan-scout hosts instead", 400)
    script = PROJECT_ROOT / "scripts" / "install-llama.sh"
    if not script.exists():
        raise AppError(f"install script not found: {script}", 500)
    tag = str(tag or "").strip()
    restore_id = str(restore_id or "").strip()
    if restore_id:
        cmd = ["bash", str(script), "--restore", restore_id]
        tag = f"restore:{restore_id}"
    else:
        cmd = ["bash", str(script), "--force", "--no-restart"]
        if tag:
            cmd += ["--llama-tag", tag]
    with _llama_update_lock:
        if _llama_update_job["running"]:
            raise AppError("a llama.cpp update is already running", 409)
        _llama_update_job.update({"running": True, "startedAt": int(time.time()),
                                  "tag": tag, "lines": [], "done": False,
                                  "rc": None, "error": ""})
    # systemd user services get a minimal PATH without the CUDA toolchain; the
    # script hard-requires nvcc, so prepend the standard toolkit location.
    env = dict(os.environ)
    env["PATH"] = "/usr/local/cuda/bin:" + env.get("PATH", "/usr/bin:/bin")

    def _run():
        rc, error = -1, ""
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    cwd=str(PROJECT_ROOT), env=env)
            for line in proc.stdout:
                clean = _ANSI_RE.sub("", line.rstrip())
                with _llama_update_lock:
                    _llama_update_job["lines"].append(clean)
                    if len(_llama_update_job["lines"]) > 500:
                        del _llama_update_job["lines"][:100]
            rc = proc.wait()
        except Exception as exc:
            error = str(exc)
        finally:
            with _llama_update_lock:
                _llama_update_job.update({"running": False, "done": True,
                                          "rc": rc, "error": error})

    threading.Thread(target=_run, daemon=True, name="llama-update").start()
    return llama_update_status()
