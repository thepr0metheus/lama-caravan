"""Remote node telemetry: port probes, health/modality checks and the
in-memory GPU/CPU/TPS history rings for topology cards."""
import json
import socket
import threading
import time
import urllib.request

from caravan.admin.cell_health import carry
from caravan.common.jsonx import _INF
from caravan.common.ttl_cache import MISS, TtlCache


_remote_port_probe_cache = TtlCache(15)   # "ip:port" -> reachable

_remote_health_cache = TtlCache(3)        # "ip:port" -> state

_remote_modalities_cache = TtlCache(300)  # "ip:port" -> {vision,video,audio}
_remote_about_cache = TtlCache(30)        # "ip:port" -> what the cell says it is

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


class TokenRates:
    """The token rates a cell has NOW, as the history of the machine's token speed records them.

    A scout keeps the last request's rates while its cell is idle (the cell's line says `last` before them, cell-speed.js). A history that
    took them for the cell's own would draw a plateau at the last speed through every idle minute, and the machine's graph would say the
    cell generates when it does not. A cell that says it answers no request does nothing now: its rates are 0, a measurement and not a
    gap. A cell that does not say — an older scout, a server without the number — is taken as it reports: nothing tells idle from held.

    `count` is the same rule as `CellSpeed.count` (static/js/cell-speed.js), in the other language; both are run against one table of cases
    (scripts/cell_speed_cases.py, COUNTS), so they cannot drift apart.
    """

    @staticmethod
    def count(value):
        """How many requests a cell says it answers: a whole number from 0. None for anything else — not told, never a 0 in its place."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if value != value or value in (_INF, -_INF) or value < 0 or value != int(value):
            return None
        return int(value)

    @classmethod
    def now(cls, prompt, gen, requests):
        """(prompt, gen) as the history records them: zeros for a cell that says it answers no request, else as reported."""
        return (0, 0) if cls.count(requests) == 0 else (prompt, gen)


def _record_tps_history(key, prompt_tps, gen_tps, requests=None):
    """Per-server token-speed history (admin-side, accumulates for every node —
    including remote clients — so the GPU telemetry rows are universal). The
    current t/s already arrive in each heartbeat; we just keep a ring buffer.
    `requests` is how many requests the cell answers now, as its scout says it
    (None: not told): a cell that answers none records zeros, not the rates it holds."""
    now = int(time.time())
    prompt_tps, gen_tps = TokenRates.now(prompt_tps, gen_tps, requests)

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

def remote_cell_about(ip, port, timeout=1.0, ttl=30):
    """What a cell says it is on its /health, for a cell this controller holds no settings for
    (made by another controller, say): `{"engine", "model", "kinds"}`, and — what the entry tells
    its clients of a model since 1.3.502 — the languages it hears or writes (`langs`), the
    longest recording it takes (`maxAudioMs`) and the language a translating cell writes
    (`targetLang`): only what it said. The caravan's own cell servers say the first three
    (faster-whisper: "large-v3-turbo", ["asr"]; transcribe: also ["ru"] and 25000); a
    llama-server says only its status, and is answered {}. Nothing said is {} — never a guess."""
    key = f"{ip}:{port}"
    hit = _remote_about_cache.get(key, ttl=ttl)
    if hit is not MISS:
        return hit
    about = {}
    try:
        with urllib.request.urlopen(f"http://{ip}:{int(port)}/health", timeout=timeout) as resp:
            body = json.loads(resp.read(65536).decode("utf-8", errors="replace"))
        if isinstance(body, dict):
            for name in ("engine", "model"):
                if isinstance(body.get(name), str) and body[name].strip():
                    about[name] = body[name].strip()[:120]
            if isinstance(body.get("kinds"), list):
                kinds = [str(k).strip() for k in body["kinds"] if isinstance(k, str) and k.strip()]
                if kinds:
                    about["kinds"] = kinds[:16]
            if isinstance(body.get("langs"), list):
                langs = [str(k).strip()[:32] for k in body["langs"] if isinstance(k, str) and k.strip()]
                if langs:
                    about["langs"] = langs[:400]
            if isinstance(body.get("maxAudioMs"), int) and not isinstance(body["maxAudioMs"], bool) and body["maxAudioMs"] > 0:
                about["maxAudioMs"] = body["maxAudioMs"]
            if isinstance(body.get("targetLang"), str) and body["targetLang"].strip():
                about["targetLang"] = body["targetLang"].strip()[:32]
    except Exception:
        about = {}
    _remote_about_cache.put(key, about)
    return about

def command_cell_health(ip, port, health_path="", timeout=1.0):
    """Health + optional startup progress for a generic command cell.

    Returns {"status", "downloadedBytes", "totalBytes"} where status is:
      - "ok"          → listening / ready
      - "downloading" / "loading" → the server answered its health path with a JSON
        body {"status": "downloading"|"loading", "downloadedBytes", "totalBytes"}
        (e.g. whisper_server.py returns this with 503 while the model loads)
      - "broken"      → answered with {"status": "error", ...} or a 5xx that
        carries no loading marker; "error" holds the cell's own diagnosis. The
        process is up, the engine is not — distinct from "down" on purpose.
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
        if code in (401, 403):
            # The cell is up and asks for a key the caravan does not have (a
            # server started with its own --api-key): the proxy's requests
            # meet the same refusal. It used to fall into the "ok" arm below —
            # a refusal painted as a listening cell.
            res["status"] = "broken"
            res["error"] = f"the cell refuses the caravan (HTTP {code} on {path})"
            return res
        if st in ("downloading", "resolving", "loading", "starting"):
            res["status"] = "downloading" if st in ("downloading", "resolving") else "loading"
            res["downloadedBytes"] = int(data.get("downloadedBytes") or 0)
            res["totalBytes"] = int(data.get("totalBytes") or 0)
        elif st == "error" or code >= 500:
            # The cell is up and ANSWERING — with a diagnosis. This used to fall
            # into the "ok" arm below, which painted a dead-on-arrival engine as
            # a healthy green cell: the wrapper process lives and serves /health,
            # the engine inside it never initialised (a CosyVoice cell spent a
            # day green while every request would have failed — its ONNX runtime
            # could not get GPU memory at startup). Same defect class as the
            # unlit cable: an error response rendered as normality.
            res["status"] = "broken"
            res["error"] = str(data.get("error") or f"HTTP {code} on {path}")[:300]
        else:
            res["status"] = "ok"   # answered without a loading marker → listening
        # A cell may describe itself on its health path, and what it says about
        # ITSELF beats anything inferred from its config: a transcribe cell's
        # real limit is an audio window in milliseconds, while the config it
        # inherited still carries a llama CTX_SIZE in tokens. Whitelisted, so a
        # cell cannot push arbitrary keys onto the board.
        # From the contract, not from a list kept here. The list kept here had
        # drifted from what the cells actually report: it copied "languages"
        # while they emit "langs", and it never copied "targetLang" at all, so
        # the board's language chip fell back to config for every cell and the
        # live value it was written to show never arrived.
        meta = carry(data)
        if meta:
            res["meta"] = meta
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
