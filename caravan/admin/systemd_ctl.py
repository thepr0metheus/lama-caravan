"""systemd --user service control: status, actions, diagnostics, unit repair."""
import os
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
    src_text = src.read_text(encoding="utf-8")
    if not target.exists() or target.read_text(encoding="utf-8", errors="replace") != src_text:
        tmp = target.with_suffix(".service.tmp")
        tmp.write_text(src_text, encoding="utf-8")
        tmp.replace(target)
        systemctl("daemon-reload", timeout=15)
    return str(target)

def cell_service_status(port):
    name = cell_service_name(port)
    show = systemctl("show", name, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
                     "-p", "MainPID", "-p", "ExecMainStartTimestamp", "-p", "UnitFileState", timeout=5)
    status = {}
    for line in show["stdout"].splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            status[key] = value
    status["ok"] = show["ok"]
    status["error"] = show["stderr"]
    status["service"] = name
    return status

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
