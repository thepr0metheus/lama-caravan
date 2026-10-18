"""GGUF model catalog: metadata parsing, family detection, local model listing."""
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.gguf_header import GgufHeader
from caravan.admin.header_memory import header_memory
from caravan.admin.paths import LLAMA_HOME
from caravan.common.draft_file import DraftFile
from caravan.common.draft_pairing import DraftPairing


def read_gguf_metadata_cached(path):
    """read_gguf_metadata keyed by (path, mtime, size): each /api/state used to
    re-parse EVERY model header; a dozen concurrent pollers serialized on the
    GIL and the whole API crawled (live incident, 2026-07-05). The header of an
    unchanged file never changes — remember it. It is remembered across starts
    too (header_memory.py): the first /api/state after each start used to read
    all of them again, 51 s for the 56 models of the NAS (2026-10-14)."""
    try:
        st = path.stat()
    except OSError:
        return read_gguf_metadata(path)
    memory = header_memory()
    mtime = int(st.st_mtime)
    hit = memory.recall(path, mtime, st.st_size)
    if hit is None:
        hit = read_gguf_metadata(path)
        memory.remember(path, mtime, st.st_size, hit)
    return hit


def read_gguf_metadata(path, limit_keys=256):
    """The facts of a GGUF file's header that the controller wants, `{}` for a file that says none
    (caravan/admin/gguf_header.py: what is read, and what is passed over)."""
    return GgufHeader.read(path, limit_keys)


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

    langs = meta.get("general.languages") or []
    if isinstance(langs, str):
        langs = [langs]
    return {
        "architecture": arch,
        "sttVariant": str(meta.get("stt.variant") or ""),
        "languages": [str(x) for x in langs][:8],
        "blockCount": number("block_count"),
        "contextLength": number("context_length"),
        "embeddingLength": number("embedding_length"),
        "headCount": number("attention.head_count"),
        "headCountKv": number("attention.head_count_kv") or number("attention.head_count"),
        "keyLength": number("attention.key_length"),
        "valueLength": number("attention.value_length"),
        "poolingType": pooling_type,
        # Speculative sidecars (dflash/dspark) denoise a whole block per pass, so
        # their block size IS the useful draft depth: on Muse Glimmer, lifting
        # --spec-draft-n-max from the default 3 to this 16 measured 157 -> 227
        # tok/s. Reading it from the file keeps that number true for the next
        # sidecar instead of hardcoding today's.
        "specBlockSize": number("block_size"),
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

def _freshness_by_path():
    """{path from the models dir: state} from the watcher's latest report.

    Empty if the watcher has never run: a missing entry means "not checked",
    and the reader must tell that apart from "matches".
    """
    try:
        from caravan.admin.model_watch import freshness_report
        repos = freshness_report().get("repos") or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for repo in repos.values():
        for key, row in (repo.get("files") or {}).items():
            out[key] = str(row.get("state") or "")
    return out


def _gguf_kind(rel, architecture=""):
    """A GGUF's role by its path and, once its header was read, by the architecture the header names: "model",
    "mmproj" or "draft" — or None for a vocab or template file, or a part of a pipeline that no engine loads on
    its own.

    The architecture outranks the name for a projector, because the name misleads. MiniCPM-o's repository ships
    `…-projector-F16.gguf` whose architecture is `projector` (four tensors of its speech pipeline, nothing
    llama-server loads with --mmproj) and, named like any weights, `…-vision-F16.gguf` whose architecture is
    `clip` — the file the cell needs. By the name the cell was offered the first and never the second, and it
    died on "Failed to load CLIP model" (2026-10-17, :22011). A name says "mmproj" only where the header does
    not say otherwise; with no header (a file only a library holds, never read) the name stays the whole answer."""
    name = Path(rel).name.lower()
    parts = Path(rel).parts
    arch = str(architecture or "").lower()
    if "vocab" in name or (parts and parts[0] in ("vocabs", "templates")):
        return None
    # Draft: a speculative sidecar by its name or its mtp/ folder — the rule
    # the type is read by, so a file offered as a draft is launched as the one
    # it is (DraftFile). Only "mtp-" was recognised until b10357, so a
    # dflash-/dspark-/eagle3- sidecar was filed as an ordinary MODEL: it never
    # reached suggestedDraft, and the operator had to know it existed and type
    # its path by hand. That is what kept Muse Glimmer at a third of its speed.
    if DraftFile(rel).sidecar_type:
        return "draft"
    if arch == "clip" or any(token in name for token in ["mmproj", "mm-proj"]):
        return "mmproj"
    if "projector" in name:
        return None if arch else "mmproj"
    return "model"


def _kind_of(path, rel, size, store):
    """_gguf_kind with the header's architecture: read only for a file the name does not rule out already (a header
    read once is remembered, header_memory.py)."""
    if _gguf_kind(rel) is None:
        return None
    return _gguf_kind(rel, _header(path, rel, size, store).get("architecture") or "")


def _header(path, rel, size, store):
    """A GGUF header's runtime facts: read from this disk — or, for a file only
    a library holds, remembered from its local copy (library_meta.py). A file
    the library got some other way has none: {} rather than a guess."""
    if store is None:
        return extract_runtime_meta(read_gguf_metadata_cached(path))
    from caravan.admin.library_meta import library_meta
    return library_meta().lookup(store["id"], rel, size) or {}


def _where(store):
    """What a row says about its place: nothing for this disk, the library for
    a file only a library holds."""
    if store is None:
        return {}
    return {"store": {"id": store["id"], "name": store["name"]}, "libraryOnly": True}


def list_models(config=None, locations=None):
    """Scan models directory — flat layout where all files for one quant share a dir:
      {model}/{author}/{quant}/model.gguf
      {model}/{author}/{quant}/mmproj*.gguf   ← vision projector
      {model}/{author}/{quant}/mtp-*.gguf     ← speculative draft head
    …plus the files only a library holds (`locations`, model_locator.py), in
    their places, marked with the library.
    """
    rows = []
    models_dir = models_dir_from_config(config or parse_config())
    if locations is None:
        from caravan.admin.model_locator import current_locations
        locations = current_locations()
    if not models_dir.exists() and not locations.library_entries():
        return rows
    # Freshness for each file — from the same report the models page reads.
    # Gathered ONCE per list: the config panel opens often, and a directory
    # can hold close to a hundred rows.
    fresh_by_path = _freshness_by_path()
    ggufs = []
    for path in (sorted(models_dir.rglob("*.gguf")) if models_dir.exists() else []):
        if not path.is_file():
            continue
        rel = str(path.relative_to(models_dir))
        name = path.name.lower()
        try:
            st = path.stat()
            size = st.st_size
            mtime = int(st.st_mtime)
        except OSError:
            size = 0
            mtime = 0
        kind = _kind_of(path, rel, size, None)
        if kind is None:
            continue
        ggufs.append((path, rel, name, kind, size, mtime, None))
    # What only a library holds joins the list, marked with its library: the
    # picker must offer a model that moved to the NAS, since a cell can start
    # from there. This disk wins when it has the file too.
    local_rels = {entry[1] for entry in ggufs}
    for rel, store, f in locations.library_entries():
        if rel in local_rels:
            continue
        size = int(f.get("size") or 0)
        kind = _kind_of(None, rel, size, store)
        if kind is None:
            continue
        ggufs.append((None, rel, Path(rel).name.lower(), kind, size, int(f.get("mtime") or 0), store))
    # One order for both, by path parts — the order the directory walk gave —
    # so a library file sits beside its siblings from this disk.
    ggufs.sort(key=lambda entry: entry[1].split("/"))

    # A split model's FIRST part is what the picker offers for the whole model, so its row carries the size of all the parts
    # the list finds: the rule the models page and the ≈VRAM badge already follow (model_locator.py). With the part's own size
    # a 93 GB model read "0.01 GB" (its first part holds only the header) and the form's estimate said it fits anywhere.
    split_sizes: dict = {}
    for _path, rel, _name, kind, size, _mtime, _store in ggufs:
        split = locations.split_part(rel) if kind == "model" else None
        if split:
            split_sizes.setdefault(split[0], {})[split[1]] = size

    # Index companions (mmproj, draft) by their quant directory — same dir as the model.
    companions_by_dir: dict = {}
    for path, rel, name, kind, size, mtime, store in ggufs:
        if kind not in ("mmproj", "draft"):
            continue
        parent = str(Path(rel).parent)
        if parent not in companions_by_dir:
            companions_by_dir[parent] = {"mmproj": [], "draft": []}
        companions_by_dir[parent][kind].append(rel)
    # …and the drafts by the architecture of the model each is made for, wherever it lies (DraftPairing): a draft is found
    # by its folder first, and a model with none there by what its header says.
    pairing = DraftPairing()
    for path, rel, name, kind, size, mtime, store in ggufs:
        if kind == "draft":
            pairing.add(rel, _header(path, rel, size, store).get("architecture"))

    for path, rel, name, kind, size, mtime, store in ggufs:
        if kind != "model":
            continue

        # `size` stays this file's own: the header lookup keys on it. The row says the whole model's.
        split = locations.split_part(rel)
        whole = split_sizes.get(split[0]) if split and split[1] == 1 else None
        total = sum(whole.values()) if whole else size

        parts = Path(rel).parts
        top = parts[0] if parts else ""
        family = detect_family(rel)
        # MTP built-in: unsloth-style repos embed MTP heads in the model weights.
        has_mtp_builtin = bool(re.search(r"[-_]MTP[-_.]|[-_]MTP-GGUF$|[-_]MTP$", top, re.IGNORECASE))

        parent_rel = str(Path(rel).parent)
        # Also check the sibling "default/" folder — HF downloads files whose quant
        # isn't recognised (e.g. mtp-*, mmproj) there, next to the quant folder.
        default_sibling = str(Path(parent_rel).parent / "default")
        # …and every OTHER sibling quant folder. An HF repo ships one projector
        # and one speculative sidecar for the whole model, but the downloader
        # files each under the quant folder it was named for — so picking the
        # Q4_K_XL weights found no drafter sitting in Q4_K_M and silently offered
        # none. Own folder first, then default/, then the rest, so a companion
        # that really does belong to this quant still wins.
        quant_root = str(Path(parent_rel).parent)
        other_siblings = sorted(
            d for d in companions_by_dir
            if d not in (parent_rel, default_sibling) and str(Path(d).parent) == quant_root
        )

        def _merge(key):
            groups = [parent_rel, default_sibling, *other_siblings]
            seen = set()
            return [x for g in groups for x in companions_by_dir.get(g, {}).get(key, [])
                    if not (x in seen or seen.add(x))]
        gguf_meta = _header(path, rel, size, store)
        compatible = _merge("mmproj")[:5]
        # The folders' drafts first, then the ones made for this architecture that lie elsewhere in the library.
        by_folder = _merge("draft")
        compatible_drafts = [*by_folder, *(d for d in pairing.of(gguf_meta.get("architecture")) if d not in by_folder)][:5]
        suggested_draft = (compatible_drafts or [""])[0]

        haystack = re.sub(r"[^a-z0-9]+", " ", rel.lower())
        name_hints = any(tok in haystack.split() for tok in ["vision", "vl", "mm", "multimodal", "llava", "minicpmv"])
        capability = "vision_likely" if (compatible or name_hints) else "text"

        family_defaults = FAMILY_DEFAULTS.get(family, {})

        # Speech-to-text weights: the file says so itself (stt.variant). They
        # are GGUF and would otherwise sit in the picker looking exactly like a
        # chat model that llama-server could serve — it cannot, and the operator
        # had no way to tell which of forty files was the recognizer.
        #
        # Embedding models: detected by name ("embed"/"embedding") or by the GGUF
        # carrying a pooling_type (chat models don't). They serve /v1/embeddings,
        # not chat — so override the capability and recommend --embeddings + the
        # right --pooling instead of the chat family's flash-attn/jinja defaults.
        name_embed = any(tok in haystack.split() for tok in ["embed", "embedding", "embeddings"])
        if gguf_meta.get("sttVariant"):
            capability = "asr"
            family = "asr"
            family_defaults = {}
        elif name_embed or gguf_meta.get("poolingType", -1) >= 0:
            capability = "embedding_likely"
            family = "embedding"
            family_defaults = embedding_family_defaults(
                haystack, gguf_meta.get("poolingType", -1), gguf_meta.get("contextLength", 0))

        rows.append({
            "path": rel,
            "name": Path(rel).name,
            "kind": kind,
            "size": total,
            "sizeGb": round(total / (1024 ** 3), 2),
            # Only the first part of a split model: how many parts the name says, and how many of them the list found (here or in a library).
            **({"parts": split[2], "partsFound": len(whole)} if whole else {}),
            "mtime": mtime,
            # "" means not checked: the panel must tell that apart from "matches".
            "fresh": fresh_by_path.get(rel, ""),
            "capability": capability,
            "compatibleMmprojs": compatible,
            "suggestedMmproj": compatible[0] if compatible else "",
            # The picker offers exactly these (form.js ModelCompanions): the server decides which files are a
            # model's companions, the form does not guess from the folder a second time.
            "compatibleDrafts": compatible_drafts,
            "suggestedDraft": suggested_draft,
            "hasMtpBuiltin": has_mtp_builtin,
            "detectedFamily": family,
            "familyDefaults": family_defaults,
            "ggufMeta": gguf_meta,
            **_where(store),
        })

    # Also include mmproj and draft files so the frontend dropdown is populated
    # and modelsByPath() can identify them by kind (needed for auto-fill guard logic:
    # replacing wrong mmproj/draft when switching models).
    for path, rel, name, kind, size, mtime, store in ggufs:
        if kind not in ("mmproj", "draft"):
            continue
        row = {
            "path": rel,
            "name": Path(rel).name,
            "kind": kind,
            "size": size,
            "sizeGb": round(size / (1024 ** 3), 2),
            "mtime": mtime,
            # mmproj and the draft are re-issued together with the model, and
            # a companion that stays silent about its own freshness is only
            # half an answer about the launch.
            "fresh": fresh_by_path.get(rel, ""),
        }
        # A speculative sidecar's header carries the draft depth worth asking for
        # (<arch>.block_size). Companion rows used to ship without ggufMeta at
        # all, so the panel had nothing to read and fell back to a default of 3 —
        # a third of the throughput the file itself is asking for.
        if kind == "draft":
            row["ggufMeta"] = _header(path, rel, size, store)
        row.update(_where(store))
        rows.append(row)

    # What the walk read of the headers goes to the disk, once, at its end: a start that follows finds it.
    header_memory().flush()
    return rows


_ST_FORMAT_HINTS = ("NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8",
                    "INT4", "W4A16", "BNB", "BF16", "FP16", "FP32")


_ST_ARCH_CACHE = {}

#: A config.json bigger than this is not read: the answer is "no architecture", never a guess from a prefix. The biggest
#: one met is an AWQ checkpoint's, 649 KB (the quantisation block lists every module it leaves alone). Its model_type
#: stands near the top, but 64 KiB of a JSON is not a JSON: it did not parse, the answer was empty, and the folder
#: reached no runner that claims by architecture (Qwen3-Omni AWQ, found on the board). 16 MiB is 25 times the biggest
#: and still parses in a blink, once.
_ST_ARCH_MAX_BYTES = 16 * 1024 * 1024


def _st_arch(directory):
    """model_type from a checkpoint's config.json, cached by (path, mtime); the first of `architectures` when the
    file has no model_type (LFM2.5-Audio's has none: "Lfm2AudioForConditionalGeneration").

    list_st_artifacts deliberately reads no files — it runs on every /api/state.
    But the runner picker needs to tell a SeamlessM4T checkpoint from any other
    safetensors folder, and guessing from the directory NAME is the kind of
    list that drifts the first time somebody renames a download. One JSON per
    directory, cached the same way GGUF headers are, keeps the answer
    measured without paying for it on every poll. The file is read whole (up to
    _ST_ARCH_MAX_BYTES): a JSON cut short does not parse, and the keys that
    answer sit anywhere among nested blocks.
    """
    try:
        cfg = directory / "config.json"
        st = cfg.stat()
        key = (str(cfg), int(st.st_mtime), st.st_size)
    except OSError:
        return ""
    hit = _ST_ARCH_CACHE.get(key)
    if hit is None:
        try:
            if st.st_size > _ST_ARCH_MAX_BYTES:
                raise ValueError("config.json is too big to read")
            with open(cfg, "rb") as fh:
                doc = json.loads(fh.read().decode("utf-8", "replace"))
            archs = doc.get("architectures")
            hit = str(doc.get("model_type") or (archs[0] if isinstance(archs, list) and archs else "") or "")
        except Exception:  # noqa: BLE001
            hit = ""
        for old in [k for k in _ST_ARCH_CACHE if k[0] == key[0] and k != key]:
            _ST_ARCH_CACHE.pop(old, None)
        _ST_ARCH_CACHE[key] = hit
    return hit


def display_model_name(model_path):
    """A label for a cell's model, from the path the config stores.

    A GGUF path ends in the file, so its basename IS the name. A safetensors
    checkpoint is a DIRECTORY laid out <model>/<author>/<FORMAT>/, so the
    basename is the precision — every such cell rendered as "FP32", which names
    no model and is identical across all of them. The first segment is the name,
    the same rule list_st_artifacts already applies.
    """
    raw = str(model_path or "").strip()
    path = raw.strip("/")
    if not path:
        return ""
    if path.lower().endswith(".gguf"):
        return path.split("/")[-1]
    parts = [p for p in path.split("/") if p]
    # An absolute path is where a machine reads the model (a scout reports
    # one): the tree above the model is that machine's, so the layout is read
    # from the end — the folder before <author>/<FORMAT> when the last segment
    # names a format, else the folder itself. Read from the front it named the
    # checkpoint "home".
    if raw.startswith(("/", "~")):
        if len(parts) >= 3 and parts[-1].upper() in _ST_FORMAT_HINTS:
            return parts[-3]
        return parts[-1]
    # Two segments is not that layout — it is a Hugging Face repo id,
    # <author>/<model>, which is how the runners that download their own weights
    # name a model (facebook/nllb-200-distilled-600M). Applying the local rule
    # to it labels every such cell with the AUTHOR: "facebook".
    if len(parts) == 2:
        return parts[-1]
    return parts[0]


def list_st_artifacts(config=None):
    """Safetensors checkpoints in the models tree: one artifact per directory
    holding *.safetensors files. The /hf download layout is
    <model>/<author>/<FORMAT>/ so the format comes from a path segment —
    no file reads, this runs on every /api/state."""
    rows = []
    models_dir = models_dir_from_config(config or parse_config())
    if not models_dir.exists():
        return rows
    by_dir = {}
    for path in models_dir.rglob("*.safetensors"):
        if not path.is_file():
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        entry = by_dir.setdefault(path.parent, {"size": 0, "files": 0, "mtime": 0})
        entry["size"] += st.st_size
        entry["files"] += 1
        entry["mtime"] = max(entry["mtime"], int(st.st_mtime))
    for d in sorted(by_dir):
        entry = by_dir[d]
        rel = str(d.relative_to(models_dir))
        parts = Path(rel).parts
        fmt = ""
        for seg in reversed(parts):
            if seg.upper() in _ST_FORMAT_HINTS:
                fmt = seg.upper()
                break
        if not fmt:
            up_rel = rel.upper()
            for hint in _ST_FORMAT_HINTS:
                if hint in up_rel:
                    fmt = hint
                    break
        rows.append({
            "path": rel,                       # directory, relative to the models root
            "name": parts[0] if parts else rel,
            "kind": "safetensors",
            "arch": _st_arch(d),               # model_type, for runner matching
            "format": fmt or "ST",
            "files": entry["files"],
            "size": entry["size"],
            "sizeGb": round(entry["size"] / (1024 ** 3), 2),
            "mtime": entry["mtime"],
        })
    return rows


def list_whisper_sizes(config=None):
    """Which faster-whisper sizes are already on disk under <root>/whisper —
    dir names only (models--Systran--faster-whisper-<size>), no file reads."""
    models_dir = models_dir_from_config(config or parse_config())
    wroot = models_dir / "whisper"
    sizes = []
    if wroot.is_dir():
        for d in sorted(wroot.glob("models--*faster-whisper-*")):
            if d.is_dir():
                sizes.append(d.name.rsplit("faster-whisper-", 1)[-1])
    return sizes


def list_translate_models(config=None):
    """NLLB checkpoints already downloaded under <root>/translate, as repo ids.

    The HF cache names a directory models--<author>--<name>; the picker wants
    author/name. Directory names only, no file reads — this runs on every
    /api/state."""
    models_dir = models_dir_from_config(config or parse_config())
    troot = models_dir / "translate"
    out = []
    if troot.is_dir():
        for d in sorted(troot.glob("models--*")):
            if not d.is_dir():
                continue
            parts = d.name.split("--")
            if len(parts) >= 3:
                out.append(f"{parts[1]}/{'--'.join(parts[2:])}")
    return out


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

    Only serves files inside the CONFIGURED models directory — LLAMA_MODELS_DIR of
    the saved config, else the default (the data volume's models/ in a container):
    the directory the picker lists, so that every row it offers can be downloaded.
    It used to read LLAMA_HOME/models, which is the same place only while the
    config says so; a container answered 404 for every file it had just listed.
    No path traversal. Called from the GET /api/models/download?path=<rel> handler.
    """
    import urllib.parse
    params = urllib.parse.parse_qs(query_string or "")
    rel = (params.get("path") or [""])[0].strip()
    if not rel:
        handler.send_response(400)
        # Content-Length: 0 rather than a bare header block. This server keeps
        # connections alive now, and a body-permitting status with no length
        # and no body leaves the client waiting for one that never comes.
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return

    models_dir = models_dir_from_config(parse_config())
    try:
        target = (models_dir / rel).resolve()
        # Security: must stay inside models_dir
        target.relative_to(models_dir.resolve())
    except (ValueError, Exception):
        handler.send_response(403)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return

    if not target.is_file():
        handler.send_response(404)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return

    size = target.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(size))
    handler.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
    handler.end_headers()
    # Content-Length was promised from stat(); anything that stops the copy
    # early leaves the receiver holding a SHORT file it has no way to question —
    # a scout would write a truncated GGUF to disk and a cell would then fail to
    # load a model that looks downloaded. So count what actually goes out, and
    # if it does not match, drop the connection: a transfer that ends without
    # its declared length is one the client can detect, where a clean close is
    # not.
    sent = 0
    with open(target, "rb") as fh:
        while sent < size:
            chunk = fh.read(1 << 20)  # 1 MiB
            if not chunk:
                break                 # file shrank under us
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                handler.close_connection = True
                return                # the client left; nothing to report to
            sent += len(chunk)
    if sent != size:
        handler.close_connection = True
        handler.log_error("short read serving %s: %d of %d bytes", rel, sent, size)

def list_gguf_models() -> dict:
    """Return GGUF model files from the configured models directory, grouped by model dir.

    The directory is the one the picker and the downloads read (LLAMA_MODELS_DIR of
    the saved config, else the default) — not LLAMA_HOME/models, which a container
    has no reason to fill. A directory that is missing is said, never replaced by
    another one.

    Skips mmproj (vision projectors) and vocab files — those are not runnable
    standalone, and files under 1 KiB, which are stubs.
    """
    models_dir = models_dir_from_config(parse_config())
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


class ModelList:
    """The models the cell editor offers, and a stamp of them for the board
    (2026-09-26). The board read them once, with /api/state, and its beat
    reads only the topology: the caravan's shelf, which lists the same rows,
    never showed a model downloaded after the page opened. The stamp rides
    the topology on every beat; the rows go only when it moved.

    Kept for a few seconds: a beat per open board asks for the stamp, and a
    list is a walk of the models folder and the libraries' last measurement
    (4 ms warm on the controller, 49 rows, 2026-09-26).
    """

    TTL = 5.0

    def __init__(self, lister=None, clock=time.time):
        self.lister = lister or (lambda: list_models())
        self.clock = clock
        self._rows = None
        self._at = 0.0
        self._walking = threading.Lock()

    def rows(self):
        """One walk at a time. The first list is waited for by everyone who asks before it is there: a dozen pages
        that open together walked the folder a dozen times, each reading every header the others were reading
        (2026-10-14). A list that has gone stale is made anew by one caller, and the others are given the old one
        meanwhile: the board never waits for a walk it already has a list of."""
        rows = self._rows
        if rows is not None and self.clock() - self._at < self.TTL:
            return rows
        if rows is None:
            with self._walking:
                if self._rows is None:
                    self._walk()
                return self._rows
        if self._walking.acquire(blocking=False):
            try:
                self._walk()
            finally:
                self._walking.release()
        return self._rows

    def _walk(self):
        self._rows = self.lister()
        self._at = self.clock()

    def current(self):
        """The rows and their stamp, of the same list: read apart, the cache
        could turn between the two and pair a list with another's stamp."""
        rows = self.rows()
        return rows, self.stamp_of(rows)

    def stamp(self):
        return self.current()[1]

    @staticmethod
    def stamp_of(rows):
        """What a list is, in a few characters: a file coming, going, growing
        or being rewritten changes it; the same files give the same stamp."""
        facts = sorted([str(r.get("path") or ""), str(r.get("kind") or ""), int(r.get("size") or 0),
                        int(r.get("mtime") or 0), bool(r.get("libraryOnly"))]
                       for r in rows or [] if isinstance(r, dict))
        return hashlib.sha1(json.dumps(facts).encode()).hexdigest()[:16]


#: The one list the board follows.
MODEL_LIST = ModelList()
