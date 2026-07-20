"""Readers over the proxy daemon\'s artifacts: agent-proxy-state.json and
logs/proxy-events/*.jsonl (the admin never writes these — the proxy owns them)."""
import json
import re
import time
from datetime import datetime

from caravan.admin.paths import AGENT_PROXY_LOG_DIR, AGENT_PROXY_STATE_FILE
from caravan.common.errors import AppError


def requests_by_client(recent_requests, timing_events, context_events):
    grouped = {}
    for request in recent_requests[-20:]:
        key = request.get("clientIp") or request.get("clientName") or "unknown"
        row = grouped.setdefault(key, {
            "clientIp": request.get("clientIp"),
            "clientName": request.get("clientName") or request.get("clientIp") or "unknown",
            "count": 0,
            "lastTime": "",
            "lastStatus": "",
            "lastPath": "",
            "lastTiming": {},
            "lastContext": {},
        })
        row["count"] += 1
        row["lastTime"] = request.get("time") or row["lastTime"]
        row["lastStatus"] = request.get("status") or row["lastStatus"]
        row["lastPath"] = request.get("path") or row["lastPath"]
        request_ts = iso_seconds(request.get("time"))
        timing = nearest_event(timing_events, request_ts)
        context = nearest_event(context_events, request_ts)
        if timing:
            row["lastTiming"] = timing
        if context:
            row["lastContext"] = context
    return sorted(grouped.values(), key=lambda row: row.get("lastTime") or "", reverse=True)[:8]

def proxy_item_timestamp(item):
    if not isinstance(item, dict):
        return None
    for key in ("finishedAt", "startedAt"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return iso_seconds(item.get("time"))

def proxy_usage_tokens(item):
    if not isinstance(item, dict):
        return 0
    response = item.get("response") if isinstance(item.get("response"), dict) else {}
    stream = item.get("stream") if isinstance(item.get("stream"), dict) else {}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    if not usage:
        usage = stream.get("usage") if isinstance(stream.get("usage"), dict) else {}
    return int(usage.get("total_tokens") or usage.get("totalTokens") or 0)

def summarize_proxy_item(label, row, item, state):
    port = item.get("port") or row.get("port")
    upstream = item.get("upstream") or row.get("upstream") or ""
    upstream_host = item.get("upstreamHost")
    upstream_port = item.get("upstreamPort")
    if upstream and (not upstream_host or not upstream_port):
        host_port = str(upstream).removeprefix("http://").removeprefix("https://")
        if ":" in host_port:
            upstream_host, upstream_port_text = host_port.rsplit(":", 1)
            try:
                upstream_port = int(upstream_port_text)
            except Exception:
                pass
    return {
        "id": item.get("id") or f"{label}:{port}:{item.get('startedAt') or item.get('finishedAt') or ''}",
        "state": state,
        "label": label,
        "port": port,
        "upstream": upstream,
        "upstreamHost": upstream_host or "127.0.0.1",
        "upstreamPort": upstream_port or 8080,
        # Realized upstream TYPE for THIS request: a local ("llama") entry port may
        # have been routed to a cloud output by the router graph (schedule/byModel/
        # queue), so the item's own type wins over the port's static type. Fall back
        # to the port row when an item predates this stamp.
        "upstreamType": str(item.get("upstreamType") or row.get("upstreamType") or "llama"),
        "providerId": str(item.get("providerId") or row.get("providerId") or ""),
        "client": item.get("client") or "",
        "method": item.get("method") or "POST",
        "path": item.get("path") or "",
        "status": item.get("status"),
        "phase": item.get("phase") or state,
        "startedAt": item.get("startedAt"),
        "finishedAt": item.get("finishedAt"),
        "durationMs": item.get("durationMs") or item.get("elapsedMs"),
        "elapsedMs": item.get("elapsedMs") or item.get("durationMs"),
        "bytes": item.get("bytes") or 0,
        "chunks": item.get("chunks") or 0,
        "firstByteMs": item.get("firstByteMs"),
        "request": item.get("request") if isinstance(item.get("request"), dict) else {},
        "response": item.get("response") if isinstance(item.get("response"), dict) else {},
        "stream": item.get("stream") if isinstance(item.get("stream"), dict) else {},
        "error": item.get("error") or "",
        "usageTokens": proxy_usage_tokens(item),
    }

def agent_proxy_sample():
    try:
        if not AGENT_PROXY_STATE_FILE.exists():
            return {"ok": False, "error": "agent proxy state missing", "agents": {}}
        payload = json.loads(AGENT_PROXY_STATE_FILE.read_text(encoding="utf-8"))
        payload["ok"] = True
        return payload
    except Exception as exc:
        return {"ok": False, "error": str(exc), "agents": {}}

def list_agent_proxy_log_dates():
    if not AGENT_PROXY_LOG_DIR.exists():
        return []
    dates = []
    for path in AGENT_PROXY_LOG_DIR.glob("*.jsonl"):
        if re.match(r"^\d{4}-\d{2}-\d{2}$", path.stem):
            dates.append(path.stem)
    return sorted(dates, reverse=True)

# {date: {"size": bytes already parsed, "ports": {port: last epoch}}}
_PORTS_SEEN_CACHE: dict = {}
_PORT_RE = re.compile(r'"port":(\d+)')
_TIME_RE = re.compile(r'"time":(\d+)')

def proxy_ports_last_seen(days=7):
    """{proxy port: epoch of its most recent logged request} over the recent days.

    Traffic through a proxy is the strongest available evidence that its route is
    really in use — stronger than reading an agent's config, which most agents
    never expose (a VM keeps its openclaw config where the host cannot read it).
    The board leans on this to promote a route from "unverified" to "confirmed".

    Cost is kept low by parsing each day file once: a finished day never changes,
    so it is read once per process; today's file grows, and only its appended
    bytes are re-read. A regex avoids json.loads on every line — "port": matches
    the exact key, never upstreamPort.
    """
    out: dict = {}
    cutoff = time.time() - max(1, int(days)) * 86400
    for date_text in list_agent_proxy_log_dates()[:max(1, int(days))]:
        path = AGENT_PROXY_LOG_DIR / f"{date_text}.jsonl"
        try:
            size = path.stat().st_size
        except OSError:
            continue
        cached = _PORTS_SEEN_CACHE.get(date_text)
        if cached and cached["size"] == size:
            ports = cached["ports"]
        else:
            ports = dict(cached["ports"]) if cached else {}
            start = cached["size"] if (cached and cached["size"] <= size) else 0
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(start)
                    for line in fh:
                        m = _PORT_RE.search(line)
                        if not m:
                            continue
                        t = _TIME_RE.search(line)
                        if not t:
                            continue
                        port, when = int(m.group(1)), int(t.group(1))
                        if when > ports.get(port, 0):
                            ports[port] = when
            except OSError:
                continue
            _PORTS_SEEN_CACHE[date_text] = {"size": size, "ports": ports}
        for port, when in ports.items():
            if when > out.get(port, 0):
                out[port] = when
    return {port: when for port, when in out.items() if when >= cutoff}

def load_agent_proxy_logs(date_text="", limit=200, event_filter="",
                          port="", route="", client="", errors=False, slim=False,
                          summary=False, since=""):
    """Filtered view over one day of proxy events.

    Beyond the original date/limit/event filters this understands:
      port    — proxy route port (the stable per-agent identifier),
      route   — case-insensitive substring of the route label,
      client  — exact client IP,
      errors  — only rows whose item carries error/errorKind,
      slim    — drop the bulky per-row queue/active snapshots (the per-request
                `item` keeps its own queue timings), for curl/agent diagnostics.
      summary — instead of rows, return per-port terminal-event counters
                {total, errors, byKind} — the cheap "how is my route doing
                today" answer for agents/CLI.
      since   — minutes: only rows newer than now-N minutes (within the selected
                day's file — a window spanning midnight misses the previous
                day's tail). Powers the per-hour error badges on the board.
    """
    dates = list_agent_proxy_log_dates()
    date_text = str(date_text or "").strip()
    if not date_text:
        date_text = dates[0] if dates else datetime.now().strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_text):
        raise AppError("invalid log date", 400)
    try:
        limit = max(1, min(2000, int(limit or 200)))
    except Exception:
        limit = 200
    event_filter = str(event_filter or "").strip()
    port_num = None
    if str(port or "").strip():
        try:
            port_num = int(str(port).strip())
        except Exception:
            raise AppError("invalid port", 400)
    route_sub = str(route or "").strip().lower()
    client_ip = str(client or "").strip()
    path = AGENT_PROXY_LOG_DIR / f"{date_text}.jsonl"
    rows = []
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rows.append(json.loads(line))
        except Exception as exc:
            raise AppError(f"failed to read proxy log: {exc}", 500)
    since_min = 0
    if str(since or "").strip():
        try:
            since_min = max(0, int(str(since).strip()))
        except (TypeError, ValueError):
            raise AppError("invalid since", 400)
    if since_min:
        cutoff = time.time() - since_min * 60
        rows = [r for r in rows if (r.get("time") or 0) >= cutoff]
    if event_filter:
        rows = [r for r in rows if r.get("event") == event_filter]
    if port_num is not None:
        rows = [r for r in rows if (r.get("item") or {}).get("port") == port_num]
    if route_sub:
        rows = [r for r in rows if route_sub in str(r.get("route") or "").lower()]
    if client_ip:
        rows = [r for r in rows if (r.get("item") or {}).get("client") == client_ip]
    if errors:
        rows = [r for r in rows
                if (r.get("item") or {}).get("error")
                or (r.get("item") or {}).get("errorKind")
                or r.get("error")]
    if summary:
        # One terminal event per request: finished | blocked |
        # client_disconnected_queued (the full handler record — the queue
        # loop's slim probe event has no item.port and is skipped).
        agg = {}
        for r in rows:
            if r.get("event") not in ("finished", "blocked", "client_disconnected_queued"):
                continue
            it = r.get("item") or {}
            if not it.get("port"):
                continue
            key = str(it.get("port"))
            entry = agg.setdefault(key, {"port": it.get("port"),
                                         "route": str(r.get("route") or ""),
                                         "total": 0, "errors": 0, "byKind": {}})
            entry["total"] += 1
            kind = str(it.get("errorKind") or it.get("reason") or "").strip()
            if kind or it.get("error"):
                entry["errors"] += 1
                k = kind or "error"
                entry["byKind"][k] = entry["byKind"].get(k, 0) + 1
        return {"date": date_text, "dates": dates, "summary": agg}
    rows = rows[-limit:]
    rows.reverse()
    if slim:
        drop = ("active", "queue", "policy", "cloudMeta", "cloudHeaders")
        rows = [{k: v for k, v in r.items() if k not in drop} for r in rows]
    return {"date": date_text, "dates": dates, "rows": rows, "limit": limit}

def proxy_daily_stats(date_text=None):
    """Per-route request counts for a given date (default: today).

    Returns:
      { date, routes: { <route_label>: { total, failed } } }

    total  = number of received events (one per unique request)
    failed = blocked + finished where status>=500 or errorKind in
             ("stopped", "upstream_timeout", "failed")
    """
    if not date_text:
        date_text = datetime.now().strftime("%Y-%m-%d")
    path = AGENT_PROXY_LOG_DIR / f"{date_text}.jsonl"
    routes: dict = {}

    def route_entry(route):
        if route not in routes:
            routes[route] = {"total": 0, "failed": 0, "paused": 0}
        return routes[route]

    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                event = row.get("event")
                route = row.get("route")
                if not route:
                    continue
                if event == "received":
                    route_entry(route)["total"] += 1
                elif event == "blocked":
                    item_kind = str((row.get("item") or {}).get("errorKind") or "")
                    if item_kind == "blocked":
                        # Route was paused/drain — not a real failure
                        route_entry(route)["paused"] += 1
                    else:
                        route_entry(route)["failed"] += 1
                elif event == "finished":
                    status = int(row.get("status") or 0)
                    error_kind = str(row.get("errorKind") or "")
                    if status >= 500 or error_kind in ("stopped", "upstream_timeout", "failed"):
                        route_entry(route)["failed"] += 1
        except Exception:
            pass

    return {"date": date_text, "routes": routes}


def iso_seconds(value):
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return None

def nearest_event(events, timestamp, max_delta=20):
    if timestamp is None:
        return None
    best = None
    best_delta = max_delta + 1
    for event in events:
        event_ts = iso_seconds(event.get("time"))
        if event_ts is None:
            continue
        delta = abs(event_ts - timestamp)
        if delta <= max_delta and delta < best_delta:
            best = event
            best_delta = delta
    if not best:
        return None
    return {**best, "approximate": True, "deltaSec": round(best_delta, 1)}
