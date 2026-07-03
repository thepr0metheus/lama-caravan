"""start-server.sh backups: list, inspect, delete, revert-to-latest."""
import shutil
from pathlib import Path

from caravan.admin.config_builder import parse_config_from_text
from caravan.admin.paths import START_SCRIPT
from caravan.common.errors import AppError
from caravan.common.fsio import read_text


def backups():
    pattern = f"{START_SCRIPT.name}.bak.*"
    rows = []
    for path in sorted(START_SCRIPT.parent.glob(pattern), reverse=True)[:20]:
        row = {"path": str(path), "name": path.name, "label": path.name.replace(f"{START_SCRIPT.name}.bak.", "")}
        try:
            config = parse_config_from_text(read_text(path), str(path))
            model = Path(config.get("MODEL_FILE") or "").name
            ctx = config.get("CTX_SIZE") or ""
            details = []
            if model:
                details.append(model)
            if ctx:
                details.append(f"ctx {ctx}")
            if details:
                row["label"] = f"{row['label']} - {' - '.join(details)}"
            row["modelFile"] = config.get("MODEL_FILE", "")
            row["ctxSize"] = ctx
        except Exception as exc:
            row["error"] = str(exc)
        rows.append(row)
    return rows

def resolve_backup_path(path_text):
    path = Path(path_text)
    try:
        resolved = path.resolve()
        resolved.relative_to(START_SCRIPT.parent.resolve())
    except Exception:
        raise AppError("Backup path is outside the launcher directory")
    if not resolved.name.startswith(f"{START_SCRIPT.name}.bak."):
        raise AppError("Not a start-server backup file")
    return resolved

def backup_config(path_text):
    resolved = resolve_backup_path(path_text)
    if not resolved.exists():
        raise AppError("Backup file was not found", 404)
    return {
        "path": str(resolved),
        "config": parse_config_from_text(read_text(resolved), str(resolved)),
        "text": read_text(resolved),
    }

def delete_backup(path_text):
    resolved = resolve_backup_path(path_text)
    if not resolved.exists():
        raise AppError("Backup file was not found", 404)
    resolved.unlink()
    return {"deleted": str(resolved)}

def revert_latest():
    latest = backups()
    if not latest:
        raise AppError("No saved configs found")
    backup = Path(latest[0]["path"])
    shutil.copy2(backup, START_SCRIPT)
    START_SCRIPT.chmod(0o755)
    return {"restored": str(backup)}
