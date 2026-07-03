"""HuggingFace REST browser: search, file listings, local GGUF copies."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.state import admin_state
from caravan.common.ttl_cache import MISS, TtlCache


_HF_CACHE_TTL = 300
_hf_cache = TtlCache(_HF_CACHE_TTL)

def _hf_request(path, timeout=12):
    url = "https://huggingface.co/api/" + path
    token = admin_state.get("hfToken") or ""
    cache_key = url + ("?auth=1" if token else "")
    hit = _hf_cache.get(cache_key)
    if hit is not MISS:
        return hit
    headers = {"User-Agent": "lama-caravan/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        _hf_cache.put(cache_key, data)
        return data
    except Exception as exc:
        return {"_error": str(exc)}

_QUANT_PAT = re.compile(
    r'\b(IQ\d_[A-Z0-9]+|Q\d[_\-][A-Z0-9]+(?:[_\-][A-Z0-9]+)*|BF16|F16|F32)\b',
    re.IGNORECASE,
)

def _classify_gguf(filename):
    n = filename.lower()
    if any(t in n for t in ("mmproj", "mm-proj", "projector")):
        return "mmproj"
    if "mtp" in n:
        return "mtp"
    if n.startswith("ggml-vocab") or "vocab" in n:
        return "vocab"
    return "model"

def _extract_quant(filename):
    m = _QUANT_PAT.search(filename)
    return m.group(0).upper() if m else ""

def hf_list_files(repo_id):
    repo_id = repo_id.strip().strip("/")
    if not re.match(r'^[\w.\-]+/[\w.\-]+$', repo_id):
        return {"ok": False, "error": "invalid repo id"}
    encoded = urllib.parse.quote(repo_id, safe='/')
    raw = _hf_request(f"models/{encoded}/tree/main?recursive=true&expand=true")
    if not isinstance(raw, list):
        err = (raw.get("_error") or raw.get("error") or "unexpected response") if isinstance(raw, dict) else "unexpected response"
        return {"ok": False, "error": err}
    last_modified = ""
    files = []
    for item in raw:
        if item.get("type") != "file":
            continue
        path = item.get("path", "")
        name = Path(path).name
        last_commit = item.get("lastCommit") or {}
        file_date = last_commit.get("date", "")
        if file_date and (not last_modified or file_date > last_modified):
            last_modified = file_date
        if not name.lower().endswith(".gguf"):
            continue
        kind = _classify_gguf(name)
        lfs = item.get("lfs") or {}
        size = lfs.get("size") or item.get("size") or 0
        files.append({
            "path": path,
            "name": name,
            "kind": kind,
            "quant": _extract_quant(name) if kind == "model" else "",
            "size": size,
            "date": file_date,
        })
    return {"ok": True, "repo": repo_id, "files": files, "lastModified": last_modified}

def hf_search(query, limit=20):
    query = query.strip()
    if not query:
        return {"ok": False, "error": "missing query"}
    if "/" in query:
        return {"ok": True, "repos": [{"id": query.strip("/"), "downloads": 0, "likes": 0}]}
    limit = max(5, min(100, int(limit)))
    raw = _hf_request(f"models?search={urllib.parse.quote(query)}&filter=gguf&limit={limit}&sort=downloads&direction=-1")
    if not isinstance(raw, list):
        err = (raw.get("_error", "search failed")) if isinstance(raw, dict) else "search failed"
        return {"ok": False, "error": err}
    repos = [{"id": r.get("id", ""), "downloads": r.get("downloads", 0), "likes": r.get("likes", 0),
              "createdAt": r.get("createdAt", ""),
              # Modality hints straight from the HF model record (already in the
              # search response — no extra request). pipeline_tag values like
              # "image-text-to-text" / "audio-text-to-text" / "any-to-any" and
              # the tags list let the UI badge vision/audio input.
              "pipelineTag": r.get("pipeline_tag") or "",
              "tags": [str(t) for t in (r.get("tags") or []) if isinstance(t, str)][:40]}
             for r in raw if r.get("id")]
    return {"ok": True, "repos": repos}

def hf_local_delete(repo_id: str, filename: str) -> dict:
    repo_id = repo_id.strip().strip("/")
    filename = filename.strip()
    if not repo_id or not filename:
        return {"ok": False, "error": "missing repo or filename"}
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return {"ok": False, "error": "invalid filename"}
    author = repo_id.split("/")[0] if "/" in repo_id else ""
    model_name = _derive_model_name(repo_id)
    models_dir = models_dir_from_config(parse_config())
    scan_root = models_dir / model_name / author if author else models_dir / model_name
    if not scan_root.is_dir():
        return {"ok": False, "error": "repo folder not found"}
    matches = [p for p in scan_root.rglob("*.gguf") if p.name == filename]
    if not matches:
        return {"ok": False, "error": "file not found"}
    for p in matches:
        # Security: must stay inside models_dir
        try:
            p.resolve().relative_to(models_dir.resolve())
        except ValueError:
            return {"ok": False, "error": "path escape detected"}
        p.unlink()
        # Remove empty parent directories up to (but never including) models_dir —
        # otherwise deleting the last quant leaves a dead model/author skeleton.
        try:
            p.parent.relative_to(models_dir)
            d = p.parent
            while d != models_dir and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
        except Exception:
            pass
    return {"ok": True}

def hf_local_check(repo_id: str) -> dict:
    repo_id = repo_id.strip().strip("/")
    if not repo_id:
        return {"ok": False, "error": "missing repo"}
    author = repo_id.split("/")[0] if "/" in repo_id else ""
    model_name = _derive_model_name(repo_id)
    models_dir = models_dir_from_config(parse_config())
    scan_root = models_dir / model_name / author if author else models_dir / model_name
    local_names: set[str] = set()
    if scan_root.is_dir():
        for p in scan_root.rglob("*.gguf"):
            local_names.add(p.name)
    return {"ok": True, "localNames": sorted(local_names)}


def _derive_model_name(repo_id: str) -> str:
    return repo_id.split("/")[-1] if "/" in repo_id else repo_id
