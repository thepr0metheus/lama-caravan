"""Remote node telemetry: port probes, health/modality checks, firewall state
and the in-memory GPU/CPU/TPS history rings for topology cards."""
import json
import socket
import threading
import time
import urllib.request

from caravan.common.jsonx import _INF
from caravan.common.ttl_cache import MISS, TtlCache
from caravan.common.procs import run


_remote_port_probe_cache = TtlCache(15)   # "ip:port" -> reachable

_remote_health_cache = TtlCache(3)        # "ip:port" -> state

_remote_modalities_cache = TtlCache(300)  # "ip:port" -> {vision,video,audio}

_firewall_cache = TtlCache(30)            # port -> {state, allowedFrom}

def firewall_port_access(port):
    """Who may reach `port` on this (controller) host per ufw. Cached 30s.
    {state: open|all|restricted|blocked|unknown, allowedFrom:[...]}."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"state": "unknown"}
    hit = _firewall_cache.get(port)
    if hit is not MISS:
        return hit
    result = {"state": "unknown"}
    out = run(["sudo", "-n", "ufw", "status"], timeout=4)
    if out.get("ok"):
        text = out["stdout"]
        if "status: inactive" in text.lower():
            result = {"state": "open", "allowedFrom": []}
        else:
            anywhere, allowed = False, []
            for line in text.splitlines():
                toks = line.split()
                if not toks:
                    continue
                to = toks[0].split("/")[0]
                if not to.isdigit() or int(to) != port:
                    continue
                if "ALLOW" not in line.upper():
                    continue
                frm = line.split("ALLOW", 1)[1].strip().replace("IN", "", 1).split("#")[0].strip()
                if not frm or frm.lower().startswith("anywhere"):
                    anywhere = True
                elif "(v6)" not in frm.lower():
                    allowed.append(frm)
            if anywhere:
                result = {"state": "all", "allowedFrom": ["Anywhere"]}
            elif allowed:
                seen, uniq = set(), []
                for a in allowed:
                    if a not in seen:
                        seen.add(a); uniq.append(a)
                result = {"state": "restricted", "allowedFrom": uniq}
            else:
                result = {"state": "blocked", "allowedFrom": []}
    _firewall_cache.put(port, result)
    return result

# Per-GPU telemetry history for sparklines, keyed by "nodeId:gpuIndex".
# Fed on every topology build (cadence = the view's poll rate). Compact rows:
# [t, memUsedMiB, utilPct, powerW].
_gpu_history: dict = {}

# Guards the three history rings below (append/trim from concurrent requests).
_history_lock = threading.Lock()

GPU_HISTORY_RETENTION_S = 600

GPU_HISTORY_MAX = 300

GPU_HISTORY_EMIT = 150

def _record_gpu_history(node_id, gpus):
    now = int(time.time())

    def num(v):
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return None

    with _history_lock:
        for g in gpus:
            idx = g.get("index")
            if idx is None:
                continue
            key = f"{node_id}:{idx}"
            buf = _gpu_history.setdefault(key, [])
            sample = [now, num(g.get("memoryUsedMiB")),
                      num(g.get("utilizationGpuPct")), num(g.get("powerDrawW"))]
            if buf and buf[-1][0] == now:
                buf[-1] = sample            # collapse multiple builds in the same second
            else:
                buf.append(sample)
            cutoff = now - GPU_HISTORY_RETENTION_S
            while buf and buf[0][0] < cutoff:
                buf.pop(0)
            if len(buf) > GPU_HISTORY_MAX:
                del buf[:len(buf) - GPU_HISTORY_MAX]
            g["history"] = buf[-GPU_HISTORY_EMIT:]

_cpu_history: dict = {}  # nodeId -> [[t, loadPct, ramUsedGb]]

def _record_cpu_history(node_id, cpu):
    """Per-node CPU%/RAM history for node-card sparklines. Returns last EMIT rows."""
    now = int(time.time())

    def num(v):
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return None

    ram = cpu.get("ram") or {}
    sample = [now, num(cpu.get("loadPct")), num(ram.get("usedGb"))]
    with _history_lock:
        buf = _cpu_history.setdefault(node_id, [])
        if buf and buf[-1][0] == now:
            buf[-1] = sample
        else:
            buf.append(sample)
        cutoff = now - GPU_HISTORY_RETENTION_S
        while buf and buf[0][0] < cutoff:
            buf.pop(0)
        if len(buf) > GPU_HISTORY_MAX:
            del buf[:len(buf) - GPU_HISTORY_MAX]
        return buf[-GPU_HISTORY_EMIT:]

_tps_history: dict = {}  # "nodeId:port" -> [[t, promptTps, genTps]]

def _record_tps_history(key, prompt_tps, gen_tps):
    """Per-server token-speed history (admin-side, accumulates for every node —
    including remote clients — so the GPU telemetry rows are universal). The
    current t/s already arrive in each heartbeat; we just keep a ring buffer."""
    now = int(time.time())

    def num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return round(f, 2) if (f == f and f != _INF and f != -_INF) else None

    sample = [now, num(prompt_tps), num(gen_tps)]
    with _history_lock:
        buf = _tps_history.setdefault(key, [])
        if buf and buf[-1][0] == now:
            buf[-1] = sample
        else:
            buf.append(sample)
        cutoff = now - GPU_HISTORY_RETENTION_S
        while buf and buf[0][0] < cutoff:
            buf.pop(0)
        if len(buf) > GPU_HISTORY_MAX:
            del buf[:len(buf) - GPU_HISTORY_MAX]
        return buf[-GPU_HISTORY_EMIT:]

def probe_remote_port(ip, port, timeout=0.6, ttl=15):
    """Best-effort TCP reachability check from the admin host to a remote
    llama-server, cached briefly. Reveals a host firewall blocking the port."""
    key = f"{ip}:{port}"
    hit = _remote_port_probe_cache.get(key, ttl=ttl)
    if hit is not MISS:
        return hit
    reachable = False
    try:
        with socket.create_connection((str(ip), int(port)), timeout=timeout):
            reachable = True
    except Exception:
        reachable = False
    _remote_port_probe_cache.put(key, reachable)
    return reachable

def remote_llama_health(ip, port, timeout=1.2, ttl=3):
    """llama-server /health state from the admin host, cached briefly:
      "ok"      — model loaded and ready (HTTP 200)
      "loading" — process up but model still loading into VRAM (HTTP 503)
      "down"    — unreachable / connection refused
    Lets the UI distinguish a freshly-started server that hasn't finished
    loading the model into VRAM from one that is actually serving."""
    key = f"{ip}:{port}"
    hit = _remote_health_cache.get(key, ttl=ttl)
    if hit is not MISS:
        return hit
    state = "down"
    try:
        with urllib.request.urlopen(f"http://{ip}:{int(port)}/health", timeout=timeout) as resp:
            state = "ok" if resp.getcode() == 200 else "loading"
    except urllib.error.HTTPError as exc:
        # llama.cpp returns 503 {"status":"loading model"} while warming up.
        state = "loading" if exc.code == 503 else "down"
    except Exception:
        state = "down"
    _remote_health_cache.put(key, state)
    return state

def command_cell_health(ip, port, health_path="", timeout=1.0):
    """Health + optional startup progress for a generic command cell.

    Returns {"status", "downloadedBytes", "totalBytes"} where status is:
      - "ok"          → listening / ready
      - "downloading" / "loading" → the server answered its health path with a JSON
        body {"status": "downloading"|"loading", "downloadedBytes", "totalBytes"}
        (e.g. whisper_server.py returns this with 503 while the model loads)
      - "down"        → not reachable
    HEALTH_PATH empty → a plain TCP port probe (ok/down, no progress)."""
    res = {"status": "down", "downloadedBytes": 0, "totalBytes": 0}
    path = str(health_path or "").strip()
    if not path:
        res["status"] = "ok" if probe_remote_port(ip, port) else "down"
        return res
    if not path.startswith("/"):
        path = "/" + path

    def _parse(code, raw):
        data = {}
        try:
            data = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        except Exception:
            data = {}
        st = str(data.get("status") or "").lower()
        if st in ("downloading", "resolving", "loading", "starting"):
            res["status"] = "downloading" if st in ("downloading", "resolving") else "loading"
            res["downloadedBytes"] = int(data.get("downloadedBytes") or 0)
            res["totalBytes"] = int(data.get("totalBytes") or 0)
        else:
            res["status"] = "ok"   # answered without a loading marker → listening
        return res

    try:
        with urllib.request.urlopen(f"http://{ip}:{int(port)}{path}", timeout=timeout) as resp:
            return _parse(resp.getcode(), resp.read(4096))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(4096)
        except Exception:
            raw = b""
        return _parse(e.code, raw)   # 503 while loading → parse the progress body
    except Exception:
        return res  # down

def remote_llama_modalities(ip, port, timeout=1.5, ttl=60):
    """Input modalities a running llama-server actually accepts, read from its
    /props endpoint and cached (modalities are fixed for the lifetime of a
    loaded model, so the TTL is generous). Returns a dict like
    {"vision": bool, "video": bool, "audio": bool} or None when unavailable.
    This is the authoritative source — it reflects the loaded mmproj, unlike
    the filename/path heuristics used elsewhere."""
    key = f"{ip}:{port}"
    hit = _remote_modalities_cache.get(key, ttl=ttl)
    if hit is not MISS:
        return hit
    mods = None
    try:
        with urllib.request.urlopen(f"http://{ip}:{int(port)}/props", timeout=timeout) as resp:
            if resp.getcode() == 200:
                data = json.loads(resp.read().decode("utf-8", "replace"))
                raw = data.get("modalities")
                if isinstance(raw, dict):
                    mods = {k: bool(v) for k, v in raw.items()
                            if k in ("vision", "video", "audio")}
    except Exception:
        mods = None
    _remote_modalities_cache.put(key, mods)
    return mods

def _normalize_modalities(raw):
    """Coerce a /props modalities object into {vision,video,audio} bools, or
    None when nothing usable is present."""
    if not isinstance(raw, dict):
        return None
    mods = {k: bool(v) for k, v in raw.items() if k in ("vision", "video", "audio")}
    return mods or None
