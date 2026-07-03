"""Proxy event log: JSONL appends to logs/proxy-events/<date>.jsonl with
retention trimming. The admin server only reads these files."""
import json
import time
from datetime import datetime, timedelta

from caravan.proxy.paths import LOG_DIR, LOG_RETENTION_DAYS
from caravan.proxy.runtime import all_active_items, log_lock, queue_snapshot


def safe_json_value(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        if isinstance(value, dict):
            return {str(key): safe_json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [safe_json_value(item) for item in value]
        return str(value)

def trim_proxy_event_logs():
    if LOG_RETENTION_DAYS <= 0 or not LOG_DIR.exists():
        return
    cutoff = datetime.now().date() - timedelta(days=LOG_RETENTION_DAYS)
    for path in LOG_DIR.glob("*.jsonl"):
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except Exception:
            continue
        if day < cutoff:
            try:
                path.unlink()
            except Exception:
                pass

def write_proxy_event(event, route_label="", request_id="", item=None, **fields):
    try:
        now = time.time()
        active_items = all_active_items()
        pending = queue_snapshot()
        row = {
            "time": int(now),
            "timeIso": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "event": event,
            "route": route_label or (item or {}).get("route") or "",
            "requestId": str(request_id or (item or {}).get("id") or ""),
            "item": item or {},
            "active": active_items,
            "queue": pending,
            **fields,
        }
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{datetime.fromtimestamp(now).strftime('%Y-%m-%d')}.jsonl"
        with log_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(safe_json_value(row), ensure_ascii=False, separators=(",", ":")) + "\n")
            trim_proxy_event_logs()
    except Exception:
        pass
