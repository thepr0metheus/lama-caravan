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
from caravan.admin.state import topology as topo
from caravan.common.errors import AppError
from caravan.common.model_artifacts import artifact_dirs, folder_weight

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
    for slot in topo.slots().values():
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


def part_group(rel):
    """The group a multi-part GGUF belongs to — its own path when it is whole.
    Public because a move plans by group, whichever store the file sits in."""
    return _part_group(rel)


def referenced_set():
    """Every model path a cell refers to right now, as relative paths. The same
    answer for any store: a cell names its files relative to a models root."""
    refs, _owners = _referenced_relpaths(with_owners=True)
    return set(refs)


def _artifact_dirs(models_dir):
    """Non-gguf artifacts as (relpath, kind) — whisper HF-cache dirs and
    safetensors checkpoint folders. The rule they are found by is the one a
    library is walked with too (caravan/common/model_artifacts.py), so the same
    folder is one item on either side of a move."""
    return artifact_dirs(str(models_dir))


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
    # Named by a cell and read by one are two different facts, and the page
    # shows both: a stopped cell's model can still travel (its start brings it
    # back), while a running cell's cannot be moved out from under it.
    running = running_owners({w for who in owners.values() for w in who})
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
            "readBy": [w for w in (owners.get(rel) or group_owners.get(_part_group(rel)) or []) if w in running],
            "group": _part_group(rel),
        })
    # Non-gguf artifacts (whisper HF-cache dirs, safetensors folders) join the
    # same list — one manager for everything under the models root.
    for rel, kind in _artifact_dirs(models_dir):
        size, mtime = folder_weight(str(models_dir / rel))
        referenced = rel in refs
        files.append({
            "path": rel,
            "kind": kind,
            "sizeBytes": size,
            "sizeGb": round(size / 2**30, 2),
            "ageDays": int((now - mtime) // 86400) if mtime else 0,
            "referenced": referenced,
            "referencedBy": owners.get(rel) or [],
            "readBy": [w for w in (owners.get(rel) or []) if w in running],
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
                size, _mtime = folder_weight(str(target))
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


def referenced_any(rels):
    """True if a cell uses any of these files — or any part of their multi-part
    groups — right now.

    A move asks this at the last moment before removing a local copy: the list
    it planned from is minutes or hours old by then, and a cell configured in
    between must keep its file. One rule, the same one delete_models refuses by.
    """
    refs = _referenced_relpaths()
    groups = {_part_group(r) for r in refs}
    return any(str(r) in refs or _part_group(str(r)) in groups for r in rels)


def running_owners(owners):
    """Which of these cells are RUNNING, as "host:port".

    A cell on a client host cannot be asked from here — its systemd is not this
    host's — so it counts as running: treating it as busy is the harmless
    mistake, and whatever refuses says whose cell it is.
    """
    from caravan.admin.paths import CONTROLLER_HOST_ID
    from caravan.admin.systemd_ctl import cell_service_status
    out = set()
    for who in set(owners):
        host, _, port = str(who).rpartition(":")
        if host != CONTROLLER_HOST_ID:
            out.add(who)
            continue
        try:
            if (cell_service_status(int(port)) or {}).get("ActiveState") == "active":
                out.add(who)
        except (ValueError, OSError):
            out.add(who)
    return out


def holders(rels):
    """The cells READING these files right now, as "host:port".

    A move asks this, and deletion does not: a stopped cell's model may travel,
    because a start brings it back, while a running cell has the file open and
    deleting it underneath would end the cell mid-answer.

    Only the cells that name these very files are asked — one question each, not
    one per cell in the fleet.
    """
    _refs, owners = _referenced_relpaths(with_owners=True)
    groups = {}
    for rel, who in owners.items():
        groups.setdefault(_part_group(rel), []).extend(who)
    wanted = set()
    for rel in rels:
        rel = str(rel)
        wanted.update(owners.get(rel) or [])
        wanted.update(groups.get(_part_group(rel)) or [])
    return sorted(running_owners(wanted))
