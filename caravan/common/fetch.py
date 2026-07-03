"""Small HTTP client helpers over urllib (stdlib only)."""
import json
import urllib.request


def fetch_json(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def fetch_text(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR: {exc}"

def post_json(url, payload, timeout=5):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {"ok": True}
