"""GGUF model catalog: metadata parsing, family detection, local model listing."""
import re
from pathlib import Path
from struct import calcsize, unpack

from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.paths import LLAMA_HOME


GGUF_VALUE_TYPES = {
    0: "B",
    1: "b",
    2: "H",
    3: "h",
    4: "I",
    5: "i",
    6: "f",
    7: "?",
    10: "Q",
    11: "q",
    12: "d",
}

def read_gguf_metadata(path, limit_keys=256):
    wanted_suffixes = (
        "block_count",
        "context_length",
        "embedding_length",
        "attention.head_count",
        "attention.head_count_kv",
        "attention.key_length",
        "attention.value_length",
        "pooling_type",
    )
    wanted = {"general.architecture"}
    meta = {}
    try:
        with path.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                return meta
            version = unpack("<I", handle.read(4))[0]
            if version < 2:
                return meta
            _tensor_count = unpack("<Q", handle.read(8))[0]
            kv_count = unpack("<Q", handle.read(8))[0]

            def read_string():
                length = unpack("<Q", handle.read(8))[0]
                return handle.read(length).decode("utf-8", errors="replace")

            def read_value(value_type):
                if value_type == 8:
                    return read_string()
                if value_type == 9:
                    item_type = unpack("<I", handle.read(4))[0]
                    length = unpack("<Q", handle.read(8))[0]
                    values = [read_value(item_type) for _ in range(min(length, 32))]
                    for _ in range(max(0, length - 32)):
                        read_value(item_type)
                    return values
                fmt = GGUF_VALUE_TYPES.get(value_type)
                if not fmt:
                    return None
                return unpack("<" + fmt, handle.read(calcsize("<" + fmt)))[0]

            for _ in range(min(kv_count, limit_keys)):
                key = read_string()
                value_type = unpack("<I", handle.read(4))[0]
                value = read_value(value_type)
                if key in wanted or key.endswith(wanted_suffixes):
                    meta[key] = value
            return meta
    except Exception:
        return {}

def extract_runtime_meta(meta):
    arch = meta.get("general.architecture", "")
    prefix = f"{arch}." if arch else ""

    def number(name):
        value = meta.get(prefix + name)
        if value is None:
            for key, candidate in meta.items():
                if key.endswith(name):
                    value = candidate
                    break
        try:
            return int(value)
        except Exception:
            return 0

    # pooling_type is present only on embedding GGUFs (0=none,1=mean,2=cls,
    # 3=last,4=rank). -1 means "not an embedding model / unspecified". Read it
    # presence-aware because 0 is a valid value that number() can't distinguish
    # from "missing".
    pooling_type = -1
    for key, value in meta.items():
        if key.endswith("pooling_type"):
            try:
                pooling_type = int(value)
            except (TypeError, ValueError):
                pooling_type = -1
            break

    return {
        "architecture": arch,
        "blockCount": number("block_count"),
        "contextLength": number("context_length"),
        "embeddingLength": number("embedding_length"),
        "headCount": number("attention.head_count"),
        "headCountKv": number("attention.head_count_kv") or number("attention.head_count"),
        "keyLength": number("attention.key_length"),
        "valueLength": number("attention.value_length"),
        "poolingType": pooling_type,
    }

# Recommended flags per model family. Keys are family prefixes parsed from the top-level
# model directory name (e.g. "gemma4-12b-it" → "gemma4", "qwen3.6-27b-mtp" → "qwen3.6").
# SPEC_TYPE / SPEC_DRAFT_* are only shown in the GUI when a draft file is also available.
FAMILY_DEFAULTS = {
    "gemma4": {
        "ENABLE_FLASH_ATTN": "1",
        "ENABLE_JINJA": "1",
        "CACHE_TYPE_K": "q8_0",
        "CACHE_TYPE_V": "q8_0",
        "SPEC_TYPE": "draft-mtp",
        "SPEC_DRAFT_N_MAX": "2",
        "SPEC_DRAFT_N_GPU_LAYERS": "999",
    },
    "qwen3.6": {
        "ENABLE_FLASH_ATTN": "1",
        "ENABLE_JINJA": "1",
        "CACHE_TYPE_K": "q8_0",
        "CACHE_TYPE_V": "q8_0",
        "SPEC_TYPE": "draft-mtp",
        "SPEC_DRAFT_N_MAX": "2",
    },
    "qwen3": {
        "ENABLE_FLASH_ATTN": "1",
        "ENABLE_JINJA": "1",
        "CACHE_TYPE_K": "q8_0",
        "CACHE_TYPE_V": "q8_0",
    },
    "qwen2.5": {
        "ENABLE_FLASH_ATTN": "1",
        "ENABLE_JINJA": "1",
        "CACHE_TYPE_K": "q8_0",
        "CACHE_TYPE_V": "q8_0",
    },
}

def embedding_family_defaults(haystack, pooling_type, context_length=0):
    """Recommended launch flags for an embedding model. Pooling is taken from the
    GGUF `pooling_type` metadata when present (0=none,1=mean,2=cls,3=last,4=rank);
    otherwise guessed from the model-family name. BERT-style families (bge) use
    CLS, sentence-transformer families (e5/gte/nomic) use MEAN, and recent
    decoder-based embedders (Qwen3-Embedding) use LAST.

    A value of "" means "recommend clearing this field" (drop the flag); a toggle
    value of "0" means "recommend turning this off" — both render in the UI as
    remove/off so chat-only cruft carried over from a chat config gets flagged."""
    pool_map = {0: "none", 1: "mean", 2: "cls", 3: "last", 4: "rank"}
    pool = pool_map.get(pooling_type)
    if not pool:
        if "bge" in haystack:
            pool = "cls"
        elif any(tok in haystack for tok in ("e5", "gte", "nomic", "minilm", "mpnet")):
            pool = "mean"
        else:
            pool = "last"
    rec = {
        "ENABLE_EMBEDDINGS": "1",
        "POOLING": pool,
        # Turn OFF / drop chat-only flags that are useless (or mildly harmful) on
        # an embeddings server and usually carry over from a chat config:
        "ENABLE_JINJA": "0",   # no chat template is applied in embedding mode
        "SPEC_TYPE": "",       # speculative decoding is meaningless for embeddings
        "CACHE_TYPE_K": "",    # KV-cache quant is pointless for a single embed pass
        "CACHE_TYPE_V": "",
    }
    # Right-size the context window to what the model was actually trained for,
    # so a chat config's huge CTX_SIZE (e.g. 100k on a 32k model) gets flagged.
    if context_length > 0:
        rec["CTX_SIZE"] = str(context_length)
    return rec

def detect_family(rel):
    """Parse model family from top-level directory name.

    Handles both fused and hyphenated number suffixes:
      'gemma4-12b-it/...'   → 'gemma4'
      'gemma-4-12b-it/...'  → 'gemma4'   (hyphen between name and version digit)
      'qwen3.6-27b-mtp/...' → 'qwen3.6'
      'llama-3-8b/...'      → 'llama3'
    """
    parts = Path(rel).parts
    if not parts:
        return ""
    top = parts[0].lower()
    # First try to match name with fused version (e.g. "qwen3.6", "gemma4")
    m = re.match(r'^([a-z][a-z0-9]*(?:\.[0-9]+)?)', top)
    if not m:
        return ""
    family = m.group(1)
    rest = top[m.end():]
    # If the family ends without a digit and the rest starts with "-<digit>",
    # fold that digit into the family name (gemma + -4 → gemma4).
    if not family[-1].isdigit():
        d = re.match(r'^-([0-9]+)', rest)
        if d:
            family = family + d.group(1)
    return family

def list_models(config=None):
    """Scan models directory — flat layout where all files for one quant share a dir:
      {model}/{author}/{quant}/model.gguf
      {model}/{author}/{quant}/mmproj*.gguf   ← vision projector
      {model}/{author}/{quant}/mtp-*.gguf     ← speculative draft head
    """
    rows = []
    models_dir = models_dir_from_config(config or parse_config())
    if not models_dir.exists():
        return rows
    ggufs = []
    for path in sorted(models_dir.rglob("*.gguf")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(models_dir))
        name = path.name.lower()
        parts = Path(rel).parts
        is_vocab = "vocab" in name or parts[0] in ("vocabs", "templates")
        if is_vocab:
            continue
        is_mmproj = any(token in name for token in ["mmproj", "mm-proj", "projector"])
        # Draft: filename starts with "mtp-", OR lives in a legacy "mtp" subdirectory.
        is_draft = name.startswith("mtp-") or (len(parts) >= 2 and parts[1] == "mtp")
        if is_draft:
            kind = "draft"
        elif is_mmproj:
            kind = "mmproj"
        else:
            kind = "model"
        try:
            st = path.stat()
            size = st.st_size
            mtime = int(st.st_mtime)
        except OSError:
            size = 0
            mtime = 0
        ggufs.append((path, rel, name, kind, size, mtime))

    # Index companions (mmproj, draft) by their quant directory — same dir as the model.
    companions_by_dir: dict = {}
    for path, rel, name, kind, size, mtime in ggufs:
        if kind not in ("mmproj", "draft"):
            continue
        parent = str(path.parent.relative_to(models_dir))
        if parent not in companions_by_dir:
            companions_by_dir[parent] = {"mmproj": [], "draft": []}
        companions_by_dir[parent][kind].append(rel)

    for path, rel, name, kind, size, mtime in ggufs:
        if kind != "model":
            continue

        parts = Path(rel).parts
        top = parts[0] if parts else ""
        family = detect_family(rel)
        # MTP built-in: unsloth-style repos embed MTP heads in the model weights.
        has_mtp_builtin = bool(re.search(r"[-_]MTP[-_.]|[-_]MTP-GGUF$|[-_]MTP$", top, re.IGNORECASE))

        parent_rel = str(path.parent.relative_to(models_dir))
        # Also check the sibling "default/" folder — HF downloads files whose quant
        # isn't recognised (e.g. mtp-*, mmproj) there, next to the quant folder.
        default_sibling = str(Path(parent_rel).parent / "default")
        def _merge(key):
            a = companions_by_dir.get(parent_rel, {}).get(key, [])
            b = companions_by_dir.get(default_sibling, {}).get(key, [])
            seen = set()
            return [x for x in a + b if not (x in seen or seen.add(x))]
        compatible = _merge("mmproj")[:5]
        suggested_draft = (_merge("draft") or [""])[0]

        haystack = re.sub(r"[^a-z0-9]+", " ", rel.lower())
        name_hints = any(tok in haystack.split() for tok in ["vision", "vl", "mm", "multimodal", "llava", "minicpmv"])
        capability = "vision_likely" if (compatible or name_hints) else "text"

        family_defaults = FAMILY_DEFAULTS.get(family, {})
        gguf_meta = extract_runtime_meta(read_gguf_metadata(path))

        # Embedding models: detected by name ("embed"/"embedding") or by the GGUF
        # carrying a pooling_type (chat models don't). They serve /v1/embeddings,
        # not chat — so override the capability and recommend --embeddings + the
        # right --pooling instead of the chat family's flash-attn/jinja defaults.
        name_embed = any(tok in haystack.split() for tok in ["embed", "embedding", "embeddings"])
        if name_embed or gguf_meta.get("poolingType", -1) >= 0:
            capability = "embedding_likely"
            family = "embedding"
            family_defaults = embedding_family_defaults(
                haystack, gguf_meta.get("poolingType", -1), gguf_meta.get("contextLength", 0))

        rows.append({
            "path": rel,
            "name": path.name,
            "kind": kind,
            "size": size,
            "sizeGb": round(size / (1024 ** 3), 2),
            "mtime": mtime,
            "capability": capability,
            "compatibleMmprojs": compatible,
            "suggestedMmproj": compatible[0] if compatible else "",
            "suggestedDraft": suggested_draft,
            "hasMtpBuiltin": has_mtp_builtin,
            "detectedFamily": family,
            "familyDefaults": family_defaults,
            "ggufMeta": gguf_meta,
        })

    # Also include mmproj and draft files so the frontend dropdown is populated
    # and modelsByPath() can identify them by kind (needed for auto-fill guard logic:
    # replacing wrong mmproj/draft when switching models).
    for path, rel, name, kind, size, mtime in ggufs:
        if kind not in ("mmproj", "draft"):
            continue
        rows.append({
            "path": rel,
            "name": path.name,
            "kind": kind,
            "size": size,
            "sizeGb": round(size / (1024 ** 3), 2),
            "mtime": mtime,
        })

    return rows

def list_chat_templates(config=None):
    config = config or parse_config()
    models_dir = models_dir_from_config(config)
    roots = [LLAMA_HOME / "templates", models_dir / "templates"]
    rows = []
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.jinja")) + sorted(root.glob("*.jinja2")):
            if not path.is_file():
                continue
            value = str(path)
            if value in seen:
                continue
            seen.add(value)
            rows.append({"path": value, "name": path.name})
    return rows

def serve_model_file(handler, query_string: str) -> None:
    """Stream a model .gguf file to the requesting client.

    Only serves files inside LLAMA_HOME/models (no path traversal).
    Called from the GET /api/models/download?path=<rel> handler.
    """
    import urllib.parse
    params = urllib.parse.parse_qs(query_string or "")
    rel = (params.get("path") or [""])[0].strip()
    if not rel:
        handler.send_response(400)
        handler.end_headers()
        return

    models_dir = LLAMA_HOME / "models"
    try:
        target = (models_dir / rel).resolve()
        # Security: must stay inside models_dir
        target.relative_to(models_dir.resolve())
    except (ValueError, Exception):
        handler.send_response(403)
        handler.end_headers()
        return

    if not target.is_file():
        handler.send_response(404)
        handler.end_headers()
        return

    size = target.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(size))
    handler.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
    handler.end_headers()
    with open(target, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                break

def list_gguf_models() -> dict:
    """Return GGUF model files from LLAMA_HOME/models, grouped by model dir.

    Skips mmproj (vision projectors) and vocab files — those are not runnable
    standalone. Only files < 2 TiB are included as a safety guard.
    """
    models_dir = LLAMA_HOME / "models"
    if not models_dir.is_dir():
        return {"ok": False, "error": f"models dir not found: {models_dir}", "models": []}
    files = []
    for p in sorted(models_dir.rglob("*.gguf")):
        rel = p.relative_to(models_dir)
        # skip projectors, vocab, and zero-byte files
        name_lower = p.name.lower()
        if any(x in name_lower for x in ("mmproj", "vocab", "projector")):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size < 1024:
            continue
        files.append({
            "path": str(rel),          # relative to models dir — send to route-agent
            "name": p.name,
            "sizeMiB": round(size / 1048576),
            "dir": str(rel.parent),
        })
    return {"ok": True, "models": files, "modelsDir": str(models_dir)}
