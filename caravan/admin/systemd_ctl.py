"""systemd --user service control: the proxy daemon, the legacy single-server
unit's status and repair, and who listens on a port. The controller's own cell
units (lama-cell@) went with its cells in step 6.9."""
import os
import re
from pathlib import Path

from caravan.admin.paths import AGENT_PROXY_SERVICE_NAME, IS_CONTAINER, SERVICE_NAME
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

def restart_agent_proxy(timeout=30):
    """Bounce the proxy daemon after a routes/cabling save. Native deployments
    restart its systemd --user unit; in the container it's a supervised child."""
    if IS_CONTAINER:
        from caravan.admin import proxy_supervisor
        return proxy_supervisor.restart()
    return systemctl("restart", AGENT_PROXY_SERVICE_NAME, timeout=timeout)

def listening_pid(port):
    """(pid, comm) of whoever LISTENs on the port; (0, "") when free. Only the
    caller's own processes reveal a pid without root — an unknown pid with a
    known-busy port still comes back as (0, "?")."""
    res = run(["ss", "-ltnp"], timeout=5)
    want = str(int(port))
    for line in (res.get("stdout") or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3].rsplit(":", 1)[-1] == want:
            m = re.search(r"pid=(\d+)", line)
            c = re.search(r'\("([^"]+)"', line)
            return (int(m.group(1)) if m else 0, c.group(1) if c else "?")
    return (0, "")


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
    if IS_CONTAINER:
        from caravan.admin import proxy_supervisor
        from caravan.admin.paths import DATA_DIR
        proxy = proxy_supervisor.status()
        data_writable = bool(DATA_DIR) and os.access(DATA_DIR, os.W_OK)
        return {
            "summary": "Controller runs in a Docker container; cells are served by caravan-scout hosts.",
            "fix": "If something is stuck, restart the container: docker restart <name>.",
            "checks": [
                {"kind": "good", "title": "container mode",
                 "detail": f"data dir {DATA_DIR or 'not set'}"},
                {"kind": "good" if data_writable else "bad", "title": "data dir writable",
                 "detail": "ok" if data_writable else "mount a writable volume at the data dir"},
                {"kind": "good" if proxy["active"] else "bad", "title": "proxy child",
                 "detail": f"pid {proxy['pid']}, respawns {proxy['respawns']}" if proxy["active"]
                           else "dead — watchdog respawns it within seconds"},
            ],
            "legacyActive": False,
        }
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
        # The single-server unit is LEGACY: with server cells on the scouts'
        # machines doing the serving, this unit being off is the normal state —
        # report it muted, not as a problem.
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
    if IS_CONTAINER:
        raise AppError("no systemd inside the container — restart the container itself "
                       "(docker restart <name>)", 400)
    steps = []
    for args in [("daemon-reload",), ("restart", SERVICE_NAME)]:
        result = systemctl(*args, timeout=30)
        steps.append({"cmd": "systemctl --user " + " ".join(args), **result})
        if not result["ok"]:
            raise AppError(result["stderr"] or f"systemctl --user {' '.join(args)} failed", 500)
    return {"steps": steps}
