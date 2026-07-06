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
    r'\b(NVFP4|MXFP4|IQ\d_[A-Z0-9]+|Q\d[_\-][A-Z0-9]+(?:[_\-][A-Z0-9]+)*|BF16|F16|F32)\b',
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

_SKIP_REPO_FILES = (".gitattributes", "readme.md", "license", "license.txt", "notice.txt")
_ST_NAME_HINTS = ("NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8", "INT4", "W4A16", "BNB")


def _safetensors_format(repo_id, config_json=None):
    """Human badge for a safetensors checkpoint: NVFP4 / AWQ / … / BF16.
    The repo name usually says it; config.json's quantization_config is the
    source of truth when it doesn't."""
    up = repo_id.upper()
    for hint in _ST_NAME_HINTS:
        if hint in up:
            return hint
    qc = (config_json or {}).get("quantization_config") or {}
    method = str(qc.get("quant_method") or "").lower()
    if method:
        return {"modelopt": "NVFP4", "fp8": "FP8", "awq": "AWQ", "gptq": "GPTQ",
                "autoround": "AUTOROUND", "bitsandbytes": "BNB"}.get(method, method.upper())
    dtype = str((config_json or {}).get("torch_dtype") or "").lower()
    if dtype in ("bfloat16", "float16", "float32"):
        return {"bfloat16": "BF16", "float16": "FP16", "float32": "FP32"}[dtype]
    return "SAFETENSORS"


def _fetch_repo_config(repo_id):
    try:
        from caravan.common.fetch import fetch_json
        encoded = urllib.parse.quote(repo_id, safe="/")
        return fetch_json(f"https://huggingface.co/{encoded}/resolve/main/config.json", timeout=8)
    except Exception:
        return None


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
    st_files = []
    other_files = []
    for item in raw:
        if item.get("type") != "file":
            continue
        path = item.get("path", "")
        name = Path(path).name
        last_commit = item.get("lastCommit") or {}
        file_date = last_commit.get("date", "")
        if file_date and (not last_modified or file_date > last_modified):
            last_modified = file_date
        lfs = item.get("lfs") or {}
        size = lfs.get("size") or item.get("size") or 0
        if name.lower().endswith(".gguf"):
            kind = _classify_gguf(name)
            files.append({
                "path": path,
                "name": name,
                "kind": kind,
                "quant": _extract_quant(name) if kind == "model" else "",
                "size": size,
                "date": file_date,
            })
            continue
        # Everything else that belongs to a safetensors checkpoint is collected
        # into ONE downloadable artifact (config/tokenizer/shards/index) so the
        # repo lands in the models tree as <model>/<author>/<FORMAT>/…
        low = name.lower()
        if low in _SKIP_REPO_FILES or low.endswith((".md", ".png", ".jpg", ".jpeg", ".gif", ".pdf")):
            other_files.append({"path": path, "name": name, "size": size})
            continue
        st_files.append({"path": path, "name": name, "size": size})
    result = {"ok": True, "repo": repo_id, "files": files, "lastModified": last_modified}
    # No safetensors weights in the repo -> the collected candidates are just
    # unsupported extras (onnx, tf, bins…): surface them in the grey list too.
    if not any(f["name"].lower().endswith(".safetensors") for f in st_files):
        other_files.extend(st_files)
        st_files = []
    other_files.sort(key=lambda f: f["name"].lower())
    if other_files:
        result["otherFiles"] = other_files
    if any(f["name"].lower().endswith(".safetensors") for f in st_files):
        cfg = _fetch_repo_config(repo_id)
        result["safetensors"] = {
            "format": _safetensors_format(repo_id, cfg),
            "files": st_files,
            "totalSize": sum(int(f.get("size") or 0) for f in st_files),
        }
    return result

def _tree_item_format(item):
    """Format badge for a model-tree entry. Library/tags beat name hints:
    'CodeFault/…-NVFP4-GGUF' is a GGUF repo even though the name says NVFP4."""
    tags = [str(t).lower() for t in (item.get("tags") or [])]
    library = str(item.get("library_name") or "").lower()
    if "gguf" in tags or library == "llama.cpp":
        return "GGUF"
    if "mlx" in tags or library == "mlx":
        return "MLX"
    if "onnx" in tags or library == "onnx":
        return "ONNX"
    for t in ("nvfp4", "mxfp4", "awq", "gptq", "autoround", "fp8", "exl2", "exl3", "bnb"):
        if t in tags:
            return t.upper()
    up = str(item.get("id") or "").upper()
    for hint in _ST_NAME_HINTS:
        if hint in up:
            return hint
    if up.endswith("-GGUF") or "-GGUF-" in up:
        return "GGUF"
    if "safetensors" in tags:
        return "SAFETENSORS"
    return ""


def _tree_items(raw, exclude=""):
    if not isinstance(raw, list):
        return []
    ex = exclude.lower()
    items = []
    for r in raw:
        rid = str(r.get("id") or "")
        if not rid or rid.lower() == ex:
            continue
        items.append({
            "id": rid,
            "downloads": r.get("downloads", 0) or 0,
            "likes": r.get("likes", 0) or 0,
            "format": _tree_item_format(r),
        })
    return items


def hf_model_tree(repo_id):
    """HF model tree, the part the caravan can act on: quantized descendants of
    this repo, plus — when the repo is itself a quant — the base model and its
    other quants (so an NVFP4 page leads to the GGUF twins one click away)."""
    repo_id = repo_id.strip().strip("/")
    if not re.match(r'^[\w.\-]+/[\w.\-]+$', repo_id):
        return {"ok": False, "error": "invalid repo id"}
    quant_filter = urllib.parse.quote(f"base_model:quantized:{repo_id}")
    quants_raw = _hf_request(f"models?filter={quant_filter}&sort=downloads&direction=-1&limit=30")
    quants = _tree_items(quants_raw, exclude=repo_id)
    base = ""
    siblings = []
    info = _hf_request(f"models/{urllib.parse.quote(repo_id, safe='/')}")
    if isinstance(info, dict) and not info.get("_error"):
        for t in info.get("tags") or []:
            m = re.match(r"^base_model:quantized:(.+)$", str(t))
            if m:
                base = m.group(1).strip()
                break
    if base and base.lower() != repo_id.lower():
        sib_filter = urllib.parse.quote(f"base_model:quantized:{base}")
        sib_raw = _hf_request(f"models?filter={sib_filter}&sort=downloads&direction=-1&limit=30")
        siblings = _tree_items(sib_raw, exclude=repo_id)
    return {"ok": True, "repo": repo_id, "quantizations": quants, "base": base, "siblings": siblings}


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
