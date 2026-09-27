"""Container-mode supervision of the proxy daemon (agent-proxies.py).

Native deployments run the proxy as its own systemd --user unit and the admin
restarts it with `systemctl --user`. Inside the Docker image there is no
systemd, so the admin process owns the proxy as a child instead: spawned at
startup and respawned by a watchdog when it dies. A config save only makes
sure it runs (systemd_ctl.ensure_agent_proxy_running branches here): the
child reads its config file by itself, and a bounce would cut every request
in flight.

The child's stdout/stderr append to logs/proxy.log under the data dir so
`docker logs` stays the admin's own story; status() feeds the System modal
the same fields _unit_brief extracts from systemctl show.
"""
import subprocess
import sys
import threading
import time

from caravan.admin.paths import AGENT_PROXY_LOG_DIR, PROJECT_ROOT

PROXY_ENTRY = PROJECT_ROOT / "agent-proxies.py"
# Sibling of proxy-events/ so every proxy artifact lives under logs/.
PROXY_LOG_FILE = AGENT_PROXY_LOG_DIR.parent / "proxy.log"
_RESPAWN_DELAY_SEC = 3

_lock = threading.Lock()
_proc = None
_started_at = 0.0
_respawns = -1  # first start() bumps it to 0
_watchdog_started = False


def _spawn_locked():
    global _proc, _started_at, _respawns
    PROXY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(PROXY_LOG_FILE, "ab", buffering=0)
    try:
        _proc = subprocess.Popen(
            [sys.executable, str(PROXY_ENTRY)],
            stdout=log, stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT), start_new_session=True,
        )
    finally:
        log.close()  # the child holds its own descriptor
    _started_at = time.time()
    _respawns += 1


def _watchdog():
    while True:
        time.sleep(_RESPAWN_DELAY_SEC)
        with _lock:
            if _proc is not None and _proc.poll() is not None:
                _spawn_locked()


def start():
    """Spawn the proxy child and the respawn watchdog (idempotent)."""
    global _watchdog_started
    with _lock:
        if _proc is None or _proc.poll() is not None:
            _spawn_locked()
        if not _watchdog_started:
            threading.Thread(target=_watchdog, name="proxy-watchdog", daemon=True).start()
            _watchdog_started = True


def status():
    """Unit-brief-shaped snapshot for the System modal services list."""
    with _lock:
        alive = _proc is not None and _proc.poll() is None
        return {
            "active": alive,
            "activeState": "active" if alive else "failed",
            "subState": "running" if alive else "dead",
            "pid": _proc.pid if alive else 0,
            "sinceEpoch": int(_started_at) if alive else 0,
            "respawns": max(_respawns, 0),
        }


def tail(lines=160):
    try:
        text = PROXY_LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])
