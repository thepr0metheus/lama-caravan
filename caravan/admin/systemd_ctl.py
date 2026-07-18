"""systemd --user service control: status, actions, diagnostics, unit repair."""
import datetime
import os
import re
import time
from pathlib import Path

from caravan.admin.paths import AGENT_PROXY_SERVICE_NAME, IS_CONTAINER, PROJECT_ROOT, SERVICE_NAME
from caravan.common.errors import AppError
from caravan.common.procs import run

# One message for every host-only operation hit inside the container: the
# controller image has no systemd, cells belong on caravan-scout hosts.
CONTAINER_CELLS_ERROR = ("the controller runs in a container without systemd — "
                         "serve models by adding a GPU host with caravan-scout")


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

def cell_service_name(port):
    return f"lama-cell@{int(port)}.service"

def ensure_cell_service_template():
    if IS_CONTAINER:
        raise AppError(CONTAINER_CELLS_ERROR, 400)
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

def systemd_ts_epoch(value):
    """systemd's 'Sun 2026-07-05 20:09:31 +04' → epoch seconds (0 if unset)."""
    s = str(value or "").strip()
    if not s or s in ("n/a", "0"):
        return 0
    m = re.match(r"^\w+ (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?: ([+-]\d{2})(\d{2})?)?", s)
    if not m:
        return 0
    date_s, time_s, tzh, tzm = m.groups()
    try:
        dt = datetime.datetime.fromisoformat(f"{date_s}T{time_s}")
        if tzh is not None:
            hours = int(tzh)
            minutes = int(tzm or 0)
            offset = datetime.timedelta(hours=hours,
                                        minutes=minutes if hours >= 0 else -minutes)
            dt = dt.replace(tzinfo=datetime.timezone(offset))
        else:
            dt = dt.astimezone()  # controller-local time, same box as systemd
        return int(dt.timestamp())
    except Exception:
        return 0


def cell_service_status(port):
    name = cell_service_name(port)
    show = systemctl("show", name, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
                     "-p", "MainPID", "-p", "ExecMainStartTimestamp", "-p", "UnitFileState",
                     "-p", "Result", "-p", "NRestarts", "-p", "ExecMainExitTimestamp", timeout=5)
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
    # oom BEFORE model: a card that cannot fit the weights always ends with
    # "error loading model" / "failed to load model" too, because that is how
    # llama.cpp reports the consequence — so matching model first told the user
    # the file was missing while it sat there, 22 GB and perfectly readable:
    #   cudaMalloc failed: out of memory
    #   alloc_tensor_range: failed to allocate CUDA0 buffer of size 22593124608
    #   llama_model_load: error loading model: unable to allocate CUDA0 buffer
    # The reverse mix-up cannot happen: a genuinely missing file fails at open,
    # before a single allocation is attempted, so its log has no oom wording.
    ("oom", ("out of memory", "cudamalloc", "failed to allocate", "unable to allocate",
             "erroroutofdevicememory", "not enough memory", "insufficient memory")),
    ("model", ("gguf_init_from_file", "error loading model", "failed to load model",
               "no such file or directory")),
    ("port", ("address already in use", "couldn't bind", "failed to bind")),
)
_cell_err_cache = {}

_cell_progress_cache = {}

# Ordered from latest phase to earliest: the LAST matching journal line wins,
# so the note follows the launch as it moves through the stages.
_CELL_PROGRESS_PATTERNS = (
    ("starting API",        ("starting vllm api server", "uvicorn running", "application startup complete")),
    ("capturing CUDA graphs", ("capturing cuda graph", "cudagraph", "graph capturing finished")),
    ("compiling kernels",   ("torch.compile", "dynamo bytecode", "compiling", "inductor")),
    ("loading weights",     ("loading safetensors", "model loading took", "loading weights", "load_tensors", "loading model")),
    ("downloading model",   ("downloading", "fetching ", "%|")),
    ("provisioning venv",   ("provisioning vllm venv",)),
    ("warming up",          ("warming up", "kv cache", "encoder cache")),
)


def cell_progress_note(port, lines=25, ttl=8):
    """One short line describing WHERE a starting cell currently is, derived
    from the unit journal (vLLM downloads/compiles for minutes — the board
    should say so instead of a bare spinner). Cached per port like
    cell_last_error; returns "" when nothing matches."""
    now = time.time()
    cached = _cell_progress_cache.get(port)
    if cached and now - cached[0] < ttl:
        return cached[1]
    res = run(["journalctl", "--user", "-u", cell_service_name(port), "-n", str(lines),
               "--no-pager", "-o", "cat"], timeout=6, env=user_systemd_env())
    note = ""
    for line in reversed((res.get("stdout") or "").splitlines()):
        low = line.lower()
        for label, needles in _CELL_PROGRESS_PATTERNS:
            if any(n in low for n in needles):
                note = label
                break
        if note:
            break
    _cell_progress_cache[port] = (now, note)
    return note


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

def cell_unit_pids(port):
    """Every PID in the cell unit's cgroup — engines that fork workers (vLLM)
    hold the GPU in a CHILD process, so matching only MainPID misclassifies
    the cell as CPU-only. Returns a set; empty when the unit isn't running."""
    show = systemctl("show", cell_service_name(port), "-p", "ControlGroup", timeout=5)
    cg = ""
    for line in (show.get("stdout") or "").splitlines():
        if line.startswith("ControlGroup="):
            cg = line.split("=", 1)[1].strip()
            break
    pids = set()
    if not cg:
        return pids
    root = Path("/sys/fs/cgroup") / cg.lstrip("/")
    try:
        for procs in [root / "cgroup.procs", *root.glob("*/cgroup.procs")]:
            if not procs.is_file():
                continue
            for tok in procs.read_text().split():
                try:
                    pids.add(int(tok))
                except ValueError:
                    pass
    except OSError:
        pass
    return pids


def cell_service_action(port, action):
    if IS_CONTAINER:
        raise AppError(CONTAINER_CELLS_ERROR, 400)
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        raise AppError("unsupported cell service action", 400)
    if action in {"start", "restart", "enable"}:
        ensure_cell_service_template()
        # A unit that tripped the start limit refuses `start` until the
        # failure state is cleared — a MANUAL start is exactly that consent.
        systemctl("reset-failed", cell_service_name(port), timeout=5)
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
