"""Every setting the GUI can change, in one file — and back again.

The reason this exists is an agent, or a person, exploring the panel by clicking
things. Exploration is how you learn a UI and it is also how a fleet's routing,
a cell's launch line and a client's label get quietly rewritten. Per-cell
snapshots already existed, and they answer "undo THIS cell"; nothing answered
"put the whole panel back the way it was an hour ago".

Two rules shape what goes in:

SETTINGS, NOT HISTORY. A cell's config is a setting; the tokens it served last
week are not. Telemetry restored from a bundle would overwrite measurements of
what actually happened with measurements from another machine or another day —
a record that lies is worse than a record that is missing.

SECRETS LEAVE ONLY WHEN ASKED. An export is a file that gets copied around, so
API keys and the HF token are stripped by default and the bundle says which
fields it stripped. The other half of that promise lives in the import: a
redacted bundle must not WIPE the keys on the machine it lands on, so import
carries the current values forward wherever the bundle has a placeholder.
"""
import base64
import json
import os
import time
from pathlib import Path

from caravan.admin.paths import (
    ADMIN_STATE_FILE,
    AGENT_PROXY_CONFIG_FILE,
    CLIENT_LABELS_FILE,
    CLOUD_PROVIDERS_FILE,
    MODEL_CATALOG_FILE,
    PROJECT_ROOT,
    PROVIDER_SECRETS_FILE,
    SERVER_CELLS_DIR,
    START_SCRIPT,
)
from caravan.common.errors import AppError
from caravan.common.fsio import atomic_write_text

BUNDLE_FORMAT = 1
REDACTED = "__redacted__"

# Where the pre-import copy of the current settings is written, so that restoring
# a bundle is itself undoable. An import that cannot be undone is a worse trap
# than the exploration it is meant to protect against.
SETTINGS_BACKUP_DIR = Path(os.environ.get("CARAVAN_SETTINGS_BACKUPS")
                           or (PROJECT_ROOT / "var/settings-backups"))


def _files():
    """Logical name → path. Logical names travel in the bundle, not paths: a
    bundle taken on one host restores on another whose home directory differs."""
    return {
        "controller-config": START_SCRIPT,        # the config block every new cell inherits
        "admin-state": ADMIN_STATE_FILE,          # topology, cells, layout, schedules, favourites
        "agent-proxies": AGENT_PROXY_CONFIG_FILE,
        "cloud-providers": CLOUD_PROVIDERS_FILE,
        "client-labels": CLIENT_LABELS_FILE,
        "model-catalog": MODEL_CATALOG_FILE,
    }


def _credential_files():
    """Accounts and cloud keys. These restore a controller whose login or whose
    provider keys were wrecked, which is the other half of "put it all back" —
    and they are also the two things that make an export file dangerous to leave
    lying around. So they travel only when the operator ticks the box, and the
    bundle says on its face that it carries them.
    """
    from caravan.admin.auth import AUTH_DB
    return {
        "provider-secrets": (PROVIDER_SECRETS_FILE, "json"),
        "auth-db": (AUTH_DB, "base64"),          # SQLite: accounts, hashes, sessions
    }


# Deliberately absent, with the reason, because "what is NOT in the file" is the
# question someone will have at the worst possible moment.
EXCLUDED = {
    "token-history.json": "measurements of what was served, not a setting",
    "monitor-history.json": "sampled load, not a setting",
    "incident-log.jsonl": "what happened here, not a setting",
    "agent-proxy-state.json": "live proxy bindings — rebuilt from the routes",
    "logs/": "logs",
}


def _redact_admin_state(data, include_secrets):
    if include_secrets or not isinstance(data, dict):
        return data, []
    out = json.loads(json.dumps(data))
    hit = []
    # Volatile: sampled load lives here too, and it is not a setting.
    out.pop("monitor", None)
    if out.get("hfToken"):
        out["hfToken"] = REDACTED
        hit.append("admin-state.hfToken")
    return out, hit


def _redact_proxies(data, include_secrets):
    if include_secrets or not isinstance(data, dict):
        return data, []
    out = json.loads(json.dumps(data))
    hit = []
    for route in out.get("routes", []) or []:
        if isinstance(route, dict) and route.get("apiKey"):
            route["apiKey"] = REDACTED
            # A route is identified by its PORT — there is no id field. Naming
            # the wrong key here is not cosmetic: the import matches on the same
            # thing, and matching on a field nothing has meant every key would
            # have failed to carry forward and been replaced by the placeholder.
            hit.append(f"agent-proxies.routes[:{route.get('port', '?')}].apiKey")
    return out, hit


_REDACTORS = {"admin-state": _redact_admin_state, "agent-proxies": _redact_proxies}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"{Path(path).name} is not readable as JSON: {exc}")


def export_bundle(include_secrets=False):
    """The current settings as one JSON-serialisable object."""
    payload = {}
    redacted = []
    for name, path in _files().items():
        path = Path(path)
        if name == "controller-config":
            payload[name] = {"kind": "text",
                             "content": path.read_text(encoding="utf-8") if path.exists() else None}
            continue
        data = _read_json(path)
        if data is not None and name in _REDACTORS:
            data, hits = _REDACTORS[name](data, include_secrets)
            redacted.extend(hits)
        payload[name] = {"kind": "json", "content": data}

    # The cells as the operator sees them: one entry per port, its saved config.
    cells = {}
    cells_dir = Path(SERVER_CELLS_DIR)
    if cells_dir.is_dir():
        for entry in sorted(cells_dir.iterdir()):
            cell_json = entry / "cell.json"
            if cell_json.is_file():
                data = _read_json(cell_json)
                if data is None:
                    continue
                # The launch script comes too. cell.json is the record; start.sh
                # is what systemd actually executes, and a cell restored without
                # it is a card on the board whose ▶ has nothing to run — which
                # looks like a working restore right up until someone presses it.
                start = entry / "start.sh"
                cells[entry.name] = {"cell": data,
                                     "start": start.read_text(encoding="utf-8") if start.is_file() else None}
    payload["server-cells"] = {"kind": "cells", "content": cells}

    credentials = []
    for name, (path, kind) in _credential_files().items():
        path = Path(path)
        if not include_secrets:
            # Named, not silently missing: the difference between "this file has
            # no accounts in it" and "this file forgot accounts exist" is the
            # whole reason someone opens a backup at 3am.
            payload[name] = {"kind": kind, "content": None, "omitted": "secrets not requested"}
            continue
        if not path.exists():
            payload[name] = {"kind": kind, "content": None, "omitted": "not present on this host"}
            continue
        if kind == "base64":
            payload[name] = {"kind": kind,
                             "content": base64.b64encode(path.read_bytes()).decode("ascii")}
        else:
            payload[name] = {"kind": kind, "content": _read_json(path)}
        credentials.append(name)

    return {
        "format": BUNDLE_FORMAT,
        "kind": "lama-caravan-settings",
        "exportedAt": int(time.time()),
        "includesSecrets": bool(include_secrets),
        # Said on the face of the file, because a bundle holding password hashes
        # and cloud keys is a different object to handle than one that does not.
        "containsCredentials": sorted(credentials),
        "redacted": redacted,
        "excluded": EXCLUDED,
        "files": payload,
    }


ENC_MARK = "aes-256-gcm/scrypt"


def passphrase_available():
    """Whether this host can lock the credentials at all.

    The project runs on the standard library, and AES is not in it. Rather than
    make `cryptography` the first dependency for one optional feature, the
    capability is DECLARED: where it is missing the control says so instead of
    offering a lock that errors when used. Installing it into the service venv
    is what turns the feature on:

        .venv/bin/pip install cryptography
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        return True
    except ImportError:
        return False


def _derive(passphrase, salt):
    import hashlib
    # scrypt, not a plain hash: the thing being protected is a file someone can
    # copy and attack offline for as long as they like.
    # maxmem explicitly: n=2^15 needs ~32 MB and OpenSSL's default ceiling is
    # exactly 32 MB, so the derivation fails on the boundary rather than running
    # slowly. Silent-looking failures at a limit are worth pinning down.
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1,
                          dklen=32, maxmem=96 * 1024 * 1024)


def _aesgcm(key):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise AppError("passphrase protection needs the 'cryptography' package on this host")
    return AESGCM(key)


def encrypt_credentials(bundle, passphrase):
    """Lock ONLY the accounts database and the cloud keys.

    Deliberately not the whole file. A settings export is reached for when
    something is already broken, and that is the worst moment to discover the
    passphrase is gone — so the cells, the routes and the topology stay readable
    no matter what, and only the two things that are dangerous to leave lying
    around need the word.
    """
    if not passphrase:
        return bundle
    import base64
    import os as _os
    for name in _credential_files():
        entry = (bundle.get("files") or {}).get(name)
        if not entry or entry.get("content") is None:
            continue
        salt = _os.urandom(16)
        nonce = _os.urandom(12)
        raw = json.dumps(entry["content"]).encode("utf-8")
        blob = _aesgcm(_derive(passphrase, salt)).encrypt(nonce, raw, None)
        entry["content"] = {
            "enc": ENC_MARK,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "data": base64.b64encode(blob).decode("ascii"),
        }
        entry["encrypted"] = True
    bundle["credentialsEncrypted"] = True
    return bundle


def _decrypt_entry(entry, passphrase):
    """The content, or None when it stays locked. Never a partial answer."""
    import base64
    content = entry.get("content")
    if not isinstance(content, dict) or content.get("enc") != ENC_MARK:
        return content
    if not passphrase:
        return None
    key = _derive(passphrase, base64.b64decode(content["salt"]))
    try:
        raw = _aesgcm(key).decrypt(base64.b64decode(content["nonce"]),
                                   base64.b64decode(content["data"]), None)
    except AppError:
        raise
    except Exception:  # noqa: BLE001
        # GCM authenticates: a wrong passphrase cannot half-decrypt into
        # plausible nonsense, it fails. Say which, rather than letting the
        # caller wonder whether the file was damaged.
        raise AppError("wrong passphrase for the credentials in this settings file")
    return json.loads(raw.decode("utf-8"))


def _merge_secrets(name, incoming, current):
    """Carry a redacted secret forward from what is on disk.

    A bundle exported without secrets says REDACTED where a key was. Writing
    that through would replace a working key with the literal string — the cell
    would keep running and start failing authentication later, which is the
    slowest possible way to find out.
    """
    if not isinstance(incoming, dict) or not isinstance(current, dict):
        return incoming
    if name == "admin-state":
        if incoming.get("hfToken") == REDACTED:
            incoming["hfToken"] = current.get("hfToken", "")
        # monitor is excluded from exports; keep whatever this machine has.
        if "monitor" not in incoming and "monitor" in current:
            incoming["monitor"] = current["monitor"]
    if name == "agent-proxies":
        by_port = {str(r.get("port")): r for r in (current.get("routes") or []) if isinstance(r, dict)}
        for route in incoming.get("routes", []) or []:
            if isinstance(route, dict) and route.get("apiKey") == REDACTED:
                route["apiKey"] = (by_port.get(str(route.get("port"))) or {}).get("apiKey", "")
    return incoming


def validate_bundle(bundle):
    if not isinstance(bundle, dict):
        raise AppError("not a settings file")
    if bundle.get("kind") != "lama-caravan-settings":
        raise AppError("this file is not a Lama Caravan settings export")
    fmt = bundle.get("format")
    if fmt != BUNDLE_FORMAT:
        raise AppError(f"settings format {fmt} — this controller reads format {BUNDLE_FORMAT}")
    if not isinstance(bundle.get("files"), dict):
        raise AppError("settings file has no files section")
    return True


def preview_import(bundle):
    """What applying this bundle would change, before anything is written."""
    validate_bundle(bundle)
    rows = []
    files = bundle["files"]
    for name, path in _files().items():
        entry = files.get(name)
        if not entry or entry.get("content") is None:
            rows.append({"name": name, "action": "skip", "note": "not in the file"})
            continue
        if name == "controller-config":
            cur = Path(path).read_text(encoding="utf-8") if Path(path).exists() else None
            incoming = entry["content"]
        else:
            cur = _read_json(path)
            # Compare what would actually be WRITTEN, which is the bundle after
            # the local secrets are carried into it. Comparing the raw bundle
            # reported "replace" for a file whose only difference was the
            # placeholder standing in for a key — telling the operator a restore
            # changes things it does not, at the moment they most need to trust
            # the list.
            incoming = _merge_secrets(name, json.loads(json.dumps(entry["content"])), cur or {})
        rows.append({"name": name,
                     "action": "same" if cur == incoming else "replace"})
    for name, (path, kind) in _credential_files().items():
        entry = files.get(name)
        if not entry or entry.get("content") is None:
            rows.append({"name": name, "action": "skip",
                         "note": (entry or {}).get("omitted") or "not in the file"})
            continue
        locked = isinstance(entry.get("content"), dict) and entry["content"].get("enc")
        rows.append({"name": name,
                     "action": "locked" if locked else "replace",
                     "note": ("needs the passphrase" if locked
                              else "credentials" if kind == "base64" else "cloud keys")})

    cells = (files.get("server-cells") or {}).get("content") or {}
    here = {}
    if Path(SERVER_CELLS_DIR).is_dir():
        for entry in Path(SERVER_CELLS_DIR).iterdir():
            cj = entry / "cell.json"
            if cj.is_file():
                st = entry / "start.sh"
                here[entry.name] = {"cell": _read_json(cj),
                                    "start": st.read_text(encoding="utf-8") if st.is_file() else None}
    # Compared, not assumed. Reporting "replace" whenever the bundle had cells
    # said a restore rewrites 24 cells even when all 24 are identical — and a
    # list that cries wolf is a list the operator stops reading, which is the
    # opposite of what a preview is for.
    if not cells:
        action = "skip"
    else:
        action = "same" if cells == here else "replace"
    rows.append({"name": "server-cells", "action": action,
                 "note": f"{len(cells)} in file, {len(here)} here"})
    return {"changes": rows, "includesSecrets": bool(bundle.get("includesSecrets")),
            "exportedAt": bundle.get("exportedAt")}


def apply_bundle(bundle, passphrase=""):
    """Write the bundle's settings over the current ones.

    The pre-import copy is taken FIRST and its path is returned, so the answer to
    "that restored the wrong thing" is another import rather than an apology.
    """
    validate_bundle(bundle)
    SETTINGS_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    before = SETTINGS_BACKUP_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-before-import.json"
    atomic_write_text(before, json.dumps(export_bundle(include_secrets=True), indent=2), mkdir=True)

    written = []
    skipped = []
    files = bundle["files"]
    for name, path in _files().items():
        entry = files.get(name)
        if not entry or entry.get("content") is None:
            continue
        path = Path(path)
        if name == "controller-config":
            atomic_write_text(path, entry["content"], mkdir=True)
        else:
            data = _merge_secrets(name, json.loads(json.dumps(entry["content"])), _read_json(path) or {})
            atomic_write_text(path, json.dumps(data, indent=2), mkdir=True)
        written.append(name)

    cells = (files.get("server-cells") or {}).get("content") or {}
    for port, data in cells.items():
        # Format 1 shipped cells as the bare cell.json; the same field now
        # carries {"cell", "start"}. Both are read, so a file taken before this
        # still restores — refusing an operator's own backup because the shape
        # grew is the failure they would least expect.
        cell = data.get("cell", data) if isinstance(data, dict) else data
        start = data.get("start") if isinstance(data, dict) else None
        base = Path(SERVER_CELLS_DIR) / str(port)
        atomic_write_text(base / "cell.json", json.dumps(cell, indent=2), mkdir=True)
        if start:
            atomic_write_text(base / "start.sh", start, mkdir=True)
            try:
                os.chmod(base / "start.sh", 0o755)
            except OSError:
                pass
    if cells:
        written.append(f"server-cells({len(cells)})")

    for name, (path, kind) in _credential_files().items():
        entry = files.get(name)
        if not entry or entry.get("content") is None:
            continue                          # a bundle without them changes nothing here
        entry = dict(entry)
        decoded = _decrypt_entry(entry, passphrase)
        if decoded is None:
            # Locked and no passphrase given: everything else still restores.
            # Silently skipping would be the worse failure, so it is reported.
            skipped.append(name)
            continue
        entry["content"] = decoded
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "base64":
            # Written whole and then locked down. A world-readable accounts
            # database is a worse outcome than the one being repaired.
            tmp = path.with_suffix(path.suffix + ".restoring")
            tmp.write_bytes(base64.b64decode(entry["content"]))
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        else:
            atomic_write_text(path, json.dumps(entry["content"], indent=2), mkdir=True)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        written.append(name)

    if any(n in written for n in _credential_files()):
        # Sessions and the "is auth on" answer are cached in memory. Restoring a
        # different accounts database while those stand would keep admitting
        # people the restored database no longer knows — the restore would look
        # applied and not be, for as long as the cache lives.
        try:
            from caravan.admin import auth as _auth
            _auth._SESSION_CACHE.clear()
            _auth._ENABLED_CACHE[0] = None
            _auth._ENABLED_CACHE[1] = 0.0
        except Exception:  # noqa: BLE001
            pass

    # The admin store is a module-level object every other module holds a
    # reference to, so it is refilled IN PLACE — rebinding it here would leave
    # the rest of the process reading the settings we just replaced.
    from caravan.admin.state import admin_state, load_admin_state
    fresh = load_admin_state()
    admin_state.clear()
    admin_state.update(fresh)

    return {"written": written, "skipped": skipped, "backup": str(before)}
