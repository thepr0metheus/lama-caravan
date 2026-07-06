"""Model-cache GC: find GGUFs on the controller's models disk that no cell
references, and delete the ones the user picked.

"Referenced" = mentioned by any server slot's saved config (MODEL_FILE /
MMPROJ_FILE / SPEC_DRAFT_MODEL_FILE) or by the legacy start-server.sh config.
Multi-part files (…-00001-of-00004.gguf) are grouped: if any part is
referenced, every part is.
"""
import re
import time
from pathlib import Path

from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.state import topology_store
from caravan.common.errors import AppError

_PART_RE = re.compile(r"^(?P<stem>.+)-\d{5}-of-(?P<n>\d{5})\.gguf$", re.I)


def _part_group(rel_path):
    """Group key for multi-part ggufs: siblings share the group."""
    match = _PART_RE.match(rel_path)
    return f"{match.group('stem')}-*-of-{match.group('n')}.gguf" if match else rel_path


def _referenced_relpaths(with_owners=False):
    """Set of referenced rel-paths; with_owners=True also returns
    {relpath: ["host:port", ...]} for the UI's "who uses this" column."""
    refs = set()
    owners = {}

    def add(value, owner=None):
        v = str(value or "").strip().lstrip("/")
        if not v:
            return
        refs.add(v)
        if owner:
            owners.setdefault(v, [])
            if owner not in owners[v]:
                owners[v].append(owner)

    config = parse_config()
    models_root = str(models_dir_from_config(config)).rstrip("/")
    for key in ("MODEL_FILE", "MMPROJ_FILE", "SPEC_DRAFT_MODEL_FILE"):
        add(config.get(key), "legacy")
    for slot in topology_store().get("serverSlots", {}).values():
        cfg = slot.get("config") or {}
        owner = f"{slot.get('hostId') or '?'}:{slot.get('port') or '?'}"
        add(slot.get("model"), owner)
        for key in ("MODEL_FILE", "MMPROJ_FILE", "SPEC_DRAFT_MODEL_FILE"):
            add(cfg.get(key), owner)
        # vLLM cells reference a safetensors DIRECTORY via an absolute path.
        vm = str(cfg.get("VLLM_MODEL") or "").strip().rstrip("/")
        if vm.startswith(models_root + "/"):
            add(vm[len(models_root) + 1:], owner)
        # whisper cells reference a SIZE — map it to the HF-cache dir name.
        if str(cfg.get("RUNNER") or "").strip().lower() == "whisper":
            size = str(cfg.get("WHISPER_MODEL") or "").strip() or "large-v3"
            add(f"whisper/models--Systran--faster-whisper-{size}", owner)
    return (refs, owners) if with_owners else refs


def _dir_stats(d):
    size = 0
    mtime = 0
    for f in d.rglob("*"):
        try:
            if f.is_file():
                st = f.stat()
                size += st.st_size
                mtime = max(mtime, int(st.st_mtime))
        except OSError:
            continue
    return size, mtime


def _artifact_dirs(models_dir):
    """Non-gguf artifacts as (relpath, kind) — whisper HF-cache dirs and
    safetensors checkpoint folders."""
    out = []
    wroot = models_dir / "whisper"
    if wroot.is_dir():
        for d in sorted(wroot.glob("models--*")):
            if d.is_dir():
                out.append((str(d.relative_to(models_dir)), "whisper"))
    seen = set()
    for f in models_dir.rglob("*.safetensors"):
        d = f.parent
        if d not in seen and d != models_dir:
            seen.add(d)
            out.append((str(d.relative_to(models_dir)), "safetensors"))
    return out


def list_unused_models():
    """Every GGUF under the models dir, flagged referenced/unused."""
    models_dir = models_dir_from_config(parse_config())
    if not models_dir.is_dir():
        return {"ok": False, "path": str(models_dir), "error": "models dir not found", "files": []}
    refs, owners = _referenced_relpaths(with_owners=True)
    ref_groups = {_part_group(r) for r in refs}
    group_owners = {}
    for rel, who in owners.items():
        group_owners.setdefault(_part_group(rel), [])
        for w in who:
            if w not in group_owners[_part_group(rel)]:
                group_owners[_part_group(rel)].append(w)
    now = time.time()
    files = []
    for f in sorted(models_dir.rglob("*.gguf")):
        try:
            stat = f.stat()
        except OSError:
            continue
        rel = str(f.relative_to(models_dir))
        referenced = rel in refs or _part_group(rel) in ref_groups
        files.append({
            "path": rel,
            "sizeBytes": stat.st_size,
            "sizeGb": round(stat.st_size / 2**30, 2),
            "ageDays": int((now - stat.st_mtime) // 86400),
            "referenced": referenced,
            "referencedBy": owners.get(rel) or group_owners.get(_part_group(rel)) or [],
            "group": _part_group(rel),
        })
    # Non-gguf artifacts (whisper HF-cache dirs, safetensors folders) join the
    # same list — one manager for everything under the models root.
    for rel, kind in _artifact_dirs(models_dir):
        size, mtime = _dir_stats(models_dir / rel)
        referenced = rel in refs
        files.append({
            "path": rel,
            "kind": kind,
            "sizeBytes": size,
            "sizeGb": round(size / 2**30, 2),
            "ageDays": int((now - mtime) // 86400) if mtime else 0,
            "referenced": referenced,
            "referencedBy": owners.get(rel) or [],
            "group": rel,
        })
    unused = [f for f in files if not f["referenced"]]
    return {
        "ok": True,
        "path": str(models_dir),
        "files": files,
        "unusedCount": len(unused),
        "unusedGb": round(sum(f["sizeBytes"] for f in unused) / 2**30, 1),
    }


def delete_models(body):
    """Delete the given relative paths — refusing anything referenced or
    outside the models dir."""
    paths = body.get("files")
    if not isinstance(paths, list) or not paths:
        raise AppError("files must be a non-empty list")
    models_dir = models_dir_from_config(parse_config()).resolve()
    refs = _referenced_relpaths()
    ref_groups = {_part_group(r) for r in refs}
    artifact_rels = {rel for rel, _kind in _artifact_dirs(Path(models_dir))}
    deleted, freed = [], 0
    for rel in paths:
        rel = str(rel or "").strip().lstrip("/")
        is_artifact_dir = rel.rstrip("/") in artifact_rels
        if not rel.endswith(".gguf") and not is_artifact_dir:
            raise AppError(f"not a gguf or a known artifact folder: {rel}")
        target = (models_dir / rel).resolve()
        if models_dir not in target.parents and target != models_dir:
            raise AppError(f"path escapes the models dir: {rel}", 400)
        if rel in refs or _part_group(rel) in ref_groups:
            raise AppError(f"refusing to delete a referenced model: {rel}", 409)
        try:
            if is_artifact_dir:
                import shutil
                size, _mtime = _dir_stats(target)
                shutil.rmtree(target)
            else:
                size = target.stat().st_size
                target.unlink()
            deleted.append(rel)
            freed += size
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise AppError(f"delete failed for {rel}: {exc}", 500)
    return {"ok": True, "deleted": deleted, "freedGb": round(freed / 2**30, 2)}
