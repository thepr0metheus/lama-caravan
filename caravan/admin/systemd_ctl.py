"""systemd --user service control: status, actions, diagnostics, unit repair."""
import os
import time
from pathlib import Path

from caravan.admin.paths import PROJECT_ROOT, SERVICE_NAME
from caravan.common.errors import AppError
from caravan.common.procs import run


def user_systemd_env():
    uid = os.getuid()
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    return {
        "XDG_RUNTIME_DIR": runtime_dir,
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime_dir}/bus",
    }

def systemctl(*args, timeout=20):
    return run(["systemctl", "--user", *args], timeout=timeout, env=user_systemd_env())

def cell_service_name(port):
    return f"lama-cell@{int(port)}.service"

def ensure_cell_service_template():
    src = PROJECT_ROOT / "systemd" / "lama-cell@.service"
    if not src.exists():
        raise AppError(f"cell service template not found: {src}", 500)
    target_dir = Path.home() / ".config/systemd/user"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "lama-cell@.service"
    # The repo template is deployment-agnostic; the unit must point at THIS
    # checkout, wherever it lives (~/lama-caravan, ~/projects/lama-caravan, …).
    rendered = src.read_text(encoding="utf-8").replace("__CARAVAN_ROOT__", str(PROJECT_ROOT))
    if not target.exists() or target.read_text(encoding="utf-8", errors="replace") != rendered:
        tmp = target.with_suffix(".service.tmp")
        tmp.write_text(rendered, encoding="utf-8")
        tmp.replace(target)
        systemctl("daemon-reload", timeout=15)
    return str(target)

def cell_service_status(port):
    name = cell_service_name(port)
    show = systemctl("show", name, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
                     "-p", "MainPID", "-p", "ExecMainStartTimestamp", "-p", "UnitFileState",
                     "-p", "Result", "-p", "NRestarts", timeout=5)
    status = {}
    for line in show["stdout"].splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            status[key] = value
    status["ok"] = show["ok"]
    status["error"] = show["stderr"]
    status["service"] = name
    return status

# Failure classification for a cell that won't start. Patterns are matched
# against the unit's journal tail, first hit wins — order matters (exec/model
# problems also mention memory-sounding words further down the log).
_CELL_ERR_PATTERNS = (
    ("exec", ("status=203", "203/exec", "failed to locate executable", "permission denied")),
    ("model", ("gguf_init_from_file", "error loading model", "failed to load model",
               "no such file or directory")),
    ("port", ("address already in use", "couldn't bind", "failed to bind")),
    ("oom", ("out of memory", "cudamalloc", "failed to allocate", "unable to allocate",
             "erroroutofdevicememory", "not enough memory", "insufficient memory")),
)
_cell_err_cache = {}

def cell_last_error(port, lines=60, ttl=10):
    """Tail the cell unit's journal and classify why it won't start.

    Returns {kind, detail, tail} or None when the journal is unreadable.
    Cached per port for `ttl` seconds — this runs inside the topology poll.
    """
    now = time.time()
    cached = _cell_err_cache.get(port)
    if cached and now - cached[0] < ttl:
        return cached[1]
    res = run(["journalctl", "--user", "-u", cell_service_name(port), "-n", str(lines),
               "--no-pager", "-o", "cat"], timeout=6, env=user_systemd_env())
    text = res.get("stdout") or ""
    result = None
    if text.strip():
        low = text.lower()
        kind = "crash"
        for name, needles in _CELL_ERR_PATTERNS:
            if any(n in low for n in needles):
                kind = name
                break
        tail_lines = [l for l in text.splitlines() if l.strip()][-8:]
        # The most telling line: last one matching the winning pattern, else the last line.
        detail = tail_lines[-1] if tail_lines else ""
        for line in reversed(text.splitlines()):
            if any(n in line.lower() for n in dict(_CELL_ERR_PATTERNS).get(kind, ())):
                detail = line.strip()
                break
        result = {"kind": kind, "detail": detail[:300], "tail": "\n".join(tail_lines)[-1500:]}
    _cell_err_cache[port] = (now, result)
    return result

def cell_service_action(port, action):
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        raise AppError("unsupported cell service action", 400)
    if action in {"start", "restart", "enable"}:
        ensure_cell_service_template()
        # Open the port in ufw so clients on other hosts can reach the cell.
        try:
            run(["sudo", "-n", "ufw", "allow", str(port)], timeout=5)
        except Exception:
            pass
    result = systemctl(action, cell_service_name(port), timeout=30)
    if not result["ok"]:
        raise AppError(result["stderr"] or f"systemctl --user {action} {cell_service_name(port)} failed", 500)
    return result

def service_status():
    show = systemctl("show", SERVICE_NAME, "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "ExecMainStartTimestamp", timeout=5)
    status = {}
    for line in show["stdout"].splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            status[key] = value
    status["ok"] = show["ok"]
    status["error"] = show["stderr"]
    pid = status.get("MainPID", "0")
    status["cmdline"] = read_cmdline(pid)
    return status

def user_service_diagnostics(service=None, runtime=None):
    service = service or service_status()
    runtime = runtime or {}
    env = user_systemd_env()
    bus_path = Path(env["XDG_RUNTIME_DIR"]) / "bus"
    checks = []
    checks.append({
        "kind": "good" if bus_path.exists() else "bad",
        "title": "systemd user bus",
        "detail": f"{bus_path} exists" if bus_path.exists() else f"{bus_path} is missing",
    })
    legacy_active = service.get("ok") and service.get("ActiveState") == "active"
    if service.get("ok"):
        # The single-server unit is LEGACY: with server cells (lama-cell@<port>)
        # doing the serving, this unit being off is the normal state — report
        # it muted, not as a problem.
        checks.append({
            "kind": "good" if legacy_active else "muted",
            "title": "llamacpp-current.service (legacy)",
            "detail": f"{service.get('ActiveState', 'unknown')} / {service.get('SubState', 'unknown')}, PID {service.get('MainPID', '0')}"
                      + ("" if legacy_active else " — off is normal when serving via cells"),
        })
    else:
        checks.append({
            "kind": "bad",
            "title": "llamacpp-current.service (legacy)",
            "detail": (service.get("error") or "systemctl --user failed").strip(),
        })
    props = runtime.get("props") if isinstance(runtime, dict) else {}
    ready = isinstance(props, dict) and props.get("ok") is not False and "error" not in props
    if legacy_active or ready:
        checks.append({
            "kind": "good" if ready else "warn",
            "title": "llama.cpp HTTP (legacy port)",
            "detail": "ready on configured port" if ready else str((props or {}).get("error") or "not ready yet"),
        })
    else:
        checks.append({
            "kind": "muted",
            "title": "llama.cpp HTTP (legacy port)",
            "detail": "legacy single-server not running — check skipped",
        })
    return {
        "summary": "Admin uses systemctl --user, so the system service must talk to the service user's bus.",
        "fix": "Use Repair user service, or restart lama-caravan after ensuring /run/user/<uid>/bus exists.",
        "checks": checks,
        "legacyActive": bool(legacy_active),
    }

def read_cmdline(pid):
    if not pid or pid == "0":
        return ""
    path = Path("/proc") / pid / "cmdline"
    try:
        return path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""

def logs():
    result = run(["journalctl", "--user", "-u", SERVICE_NAME, "-n", "160", "--no-pager"], timeout=8)
    return result["stdout"] if result["ok"] else result["stderr"]

def repair_user_service():
    steps = []
    for args in [("daemon-reload",), ("restart", SERVICE_NAME)]:
        result = systemctl(*args, timeout=30)
        steps.append({"cmd": "systemctl --user " + " ".join(args), **result})
        if not result["ok"]:
            raise AppError(result["stderr"] or f"systemctl --user {' '.join(args)} failed", 500)
    return {"steps": steps}
