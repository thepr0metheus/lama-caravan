#!/usr/bin/env python3
"""The settings file: what it carries, what it refuses to carry, and what it
must not destroy on the way back in.

The dangerous half is the import. A bundle exported without secrets says
"__redacted__" where an API key was, and writing that through would replace a
working key with a literal string — the cell keeps running and starts failing
authentication later, which is the slowest way to find out. So the test that
matters most here is the one asserting a redacted bundle LEAVES the local keys
alone.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="caravan-settings-test-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP)
os.environ["LLAMA_START_SCRIPT"] = str(_TMP / "start-server.sh")
os.environ["CARAVAN_SETTINGS_BACKUPS"] = str(_TMP / "settings-backups")

from caravan.admin import settings_bundle as sb   # noqa: E402
from caravan.common.errors import AppError        # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  ' + detail}")


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) if not isinstance(data, str) else data,
                    encoding="utf-8")


def main():
    proxies = Path(sb._files()["agent-proxies"])
    admin = Path(sb._files()["admin-state"])
    # Routes as agent-proxies.json really stores them: identified by PORT, with
    # no id field. The first version of this test invented an id, which made the
    # secret-merge pass against a shape that does not exist on any controller.
    write(proxies, {"routes": [{"port": 23001, "label": "a", "apiKey": "sk-live-secret"},
                               {"port": 23003, "label": "b"}]})
    write(admin, {"hfToken": "hf_secret", "topology": {"clients": {"a": {}}},
                  "monitor": {"retentionSeconds": 600}})

    # 1. A plain export carries the settings and none of the secrets.
    bundle = sb.export_bundle()
    routes = bundle["files"]["agent-proxies"]["content"]["routes"]
    check("export hides an API key", routes[0]["apiKey"] == sb.REDACTED, routes[0].get("apiKey"))
    check("export hides the HF token",
          bundle["files"]["admin-state"]["content"]["hfToken"] == sb.REDACTED)
    check("export says what it hid", len(bundle["redacted"]) == 2, str(bundle["redacted"]))
    check("export keeps the settings themselves",
          bundle["files"]["admin-state"]["content"]["topology"]["clients"] == {"a": {}})
    check("export drops sampled load",
          "monitor" not in bundle["files"]["admin-state"]["content"])
    check("export names what it excluded", "token-history.json" in (bundle.get("excluded") or {}))

    # 2. Opting in carries them.
    with_secrets = sb.export_bundle(include_secrets=True)
    check("secrets=1 carries the key",
          with_secrets["files"]["agent-proxies"]["content"]["routes"][0]["apiKey"] == "sk-live-secret")

    # 3. THE ONE THAT MATTERS: importing a redacted bundle must not wipe keys.
    #    The bundle changes a port, so this is a real restore, not a no-op.
    bundle["files"]["agent-proxies"]["content"]["routes"][1]["label"] = "b2"
    sb.apply_bundle(bundle)
    after = json.loads(proxies.read_text())
    check("import keeps the local API key", after["routes"][0]["apiKey"] == "sk-live-secret",
          after["routes"][0].get("apiKey"))
    check("import keeps the local HF token",
          json.loads(admin.read_text()).get("hfToken") == "hf_secret")
    check("import applies the non-secret change", after["routes"][1]["label"] == "b2")
    check("import keeps this machine's monitor block",
          "monitor" in json.loads(admin.read_text()))

    # 4. The restore is itself undoable.
    backups = sorted(Path(os.environ["CARAVAN_SETTINGS_BACKUPS"]).glob("*.json"))
    check("import leaves a copy of what it replaced", len(backups) == 1, str(backups))
    if backups:
        prior = json.loads(backups[0].read_text())
        check("that copy carries the secrets, so it can restore them",
              prior["files"]["agent-proxies"]["content"]["routes"][0]["apiKey"] == "sk-live-secret")

    # 5. A DELETED cell comes back. This is the thing the feature is for: an
    #    exploring agent removes a cell, and the file must put it back. Since
    #    step 6.9 every cell runs through the scout of its machine and IS its
    #    slot — it travels inside admin-state; the controller's own launch
    #    files (var/server-cells) went with its own cells.
    SLOT = {"hostId": "box-a", "port": 22222, "config": {"RUNNER": "llama-server", "MODEL_FILE": "m.gguf"}}
    state = json.loads(admin.read_text())
    state["topology"]["serverSlots"] = {"box-a:22222": SLOT}
    write(admin, state)
    snapshot = sb.export_bundle(include_secrets=True)
    check("export carries the cell as its slot",
          snapshot["files"]["admin-state"]["content"]["topology"]["serverSlots"] == {"box-a:22222": SLOT})
    check("negative: export carries no launch files of the controller's own cells",
          "server-cells" not in snapshot["files"], str(sorted(snapshot["files"])))
    state["topology"]["serverSlots"] = {}
    write(admin, state)
    sb.apply_bundle(snapshot)
    check("import brings the cell back",
          json.loads(admin.read_text())["topology"]["serverSlots"] == {"box-a:22222": SLOT})

    # 5b. A file taken while the controller still ran cells of its own carries
    #     their launch files. They have nowhere to go: said in the preview and
    #     in the answer, and nothing is written for them.
    old = json.loads(json.dumps(snapshot))
    old["files"]["server-cells"] = {"kind": "cells", "content": {
        "22001": {"cell": {"hostId": "controller", "port": 22001}, "start": "#!/bin/bash\nexec echo hello\n"}}}
    rows = [r for r in sb.preview_import(old)["changes"] if r["name"] == "server-cells"]
    check("preview names the old launch files and why they stay out",
          rows == [{"name": "server-cells", "action": "skip", "note": sb.SERVER_CELLS_GONE}], str(rows))
    check("the reason says where the cells are now",
          sb.SERVER_CELLS_GONE == "the controller runs no cells of its own since step 6.9 — its old launch "
                                  "files are not restored; the cells come back with admin-state")
    res = sb.apply_bundle(old)
    check("import reports them as not restored", res["skipped"] == ["server-cells"], str(res["skipped"]))
    check("negative: nothing is written for them",
          not (_TMP / "server-cells").exists() and not any(_TMP.rglob("start.sh")))
    check("negative: a file without them has no such row",
          not [r for r in sb.preview_import(snapshot)["changes"] if r["name"] == "server-cells"])

    # 5c. The labels the monitor gave the clients of the controller's own
    #     single server. It stopped watching that server in step 6.9 and
    #     nothing reads them: they neither leave nor come back.
    check("negative: export carries no client labels",
          "client-labels" not in snapshot["files"], str(sorted(snapshot["files"])))
    older = json.loads(json.dumps(snapshot))
    older["files"]["client-labels"] = dict(snapshot["files"]["model-catalog"], content={"10.0.0.7": "lab"})
    rows = [r for r in sb.preview_import(older)["changes"] if r["name"] == "client-labels"]
    check("preview names the old client labels and why they stay out",
          rows == [{"name": "client-labels", "action": "skip", "note": sb.CLIENT_LABELS_GONE}], str(rows))
    check("the reason says nothing reads them",
          sb.CLIENT_LABELS_GONE == "the controller no longer watches its own server's clients since step 6.9 — "
                                   "their labels are not restored; nothing reads them")
    res = sb.apply_bundle(older)
    check("import reports them as not restored", res["skipped"] == ["client-labels"], str(res["skipped"]))
    check("negative: nothing is written for them", not any(_TMP.rglob("client-labels.json")))
    both = json.loads(json.dumps(old))
    both["files"]["client-labels"] = older["files"]["client-labels"]
    check("a file with both retired sections names both, in one order",
          sb.apply_bundle(both)["skipped"] == ["server-cells", "client-labels"])

    # 6. Accounts and cloud keys: out only when asked, and restorable when they
    #    are. These are the two files that make an export dangerous to leave
    #    lying around, and also the two a wrecked controller cannot be rebuilt
    #    without — so both halves need proving.
    from caravan.admin.auth import AUTH_DB
    secrets_file = Path(sb.PROVIDER_SECRETS_FILE)
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    AUTH_DB.write_bytes(b"SQLite format 3\x00-pretend-accounts")
    write(secrets_file, {"openai": "sk-cloud-key"})

    plain = sb.export_bundle()
    check("a plain export carries no accounts", plain["files"]["auth-db"]["content"] is None)
    check("a plain export carries no cloud keys", plain["files"]["provider-secrets"]["content"] is None)
    check("and says why they are absent",
          "secrets" in (plain["files"]["auth-db"].get("omitted") or ""))
    check("a plain export declares no credentials", plain["containsCredentials"] == [])

    full = sb.export_bundle(include_secrets=True)
    check("secrets=1 carries the accounts database", full["files"]["auth-db"]["content"] is not None)
    check("secrets=1 declares what it carries",
          full["containsCredentials"] == ["auth-db", "provider-secrets"],
          str(full["containsCredentials"]))

    # Wreck both, then restore from the file.
    AUTH_DB.unlink()
    secrets_file.unlink()
    sb.apply_bundle(full)
    check("import restores the accounts database",
          AUTH_DB.is_file() and AUTH_DB.read_bytes().endswith(b"-pretend-accounts"))
    check("the restored accounts database is not world-readable",
          (AUTH_DB.stat().st_mode & 0o077) == 0, oct(AUTH_DB.stat().st_mode))
    check("import restores the cloud keys",
          json.loads(secrets_file.read_text())["openai"] == "sk-cloud-key")

    # And a bundle WITHOUT them must not wipe what is here.
    sb.apply_bundle(plain)
    check("a plain import leaves the accounts alone", AUTH_DB.is_file())
    check("a plain import leaves the cloud keys alone",
          json.loads(secrets_file.read_text())["openai"] == "sk-cloud-key")

    # 7. The passphrase locks ONLY the credentials, and only when asked.
    try:
        import cryptography  # noqa: F401
        have_crypto = True
    except ImportError:
        have_crypto = False
    if not have_crypto:
        print("  skip passphrase checks — no cryptography package on this host")
    else:
        AUTH_DB.write_bytes(b"SQLite format 3\x00-locked-accounts")
        write(secrets_file, {"openai": "sk-locked"})
        locked = sb.encrypt_credentials(sb.export_bundle(include_secrets=True), "hunter2")
        check("a passphrase declares itself on the file", locked.get("credentialsEncrypted") is True)
        check("the accounts database is unreadable without it",
              isinstance(locked["files"]["auth-db"]["content"], dict)
              and locked["files"]["auth-db"]["content"].get("enc") == sb.ENC_MARK)
        # The half that must NOT be locked: a restore is reached for when things
        # are already broken, and a forgotten passphrase must not take the cells
        # and the routes down with it.
        check("the cells stay readable without the passphrase",
              locked["files"]["admin-state"]["content"]["topology"]["serverSlots"] == {"box-a:22222": SLOT})
        check("the topology stays readable without the passphrase",
              locked["files"]["admin-state"]["content"]["topology"]["clients"] == {"a": {}})

        AUTH_DB.unlink()
        secrets_file.unlink()
        wiped = json.loads(admin.read_text())
        wiped["topology"]["serverSlots"] = {}
        write(admin, wiped)
        res = sb.apply_bundle(locked)          # no passphrase
        check("without the passphrase the credentials are skipped, not mangled",
              sorted(res["skipped"]) == ["auth-db", "provider-secrets"], str(res.get("skipped")))
        check("and the rest still restored",
              json.loads(admin.read_text())["topology"]["serverSlots"] == {"box-a:22222": SLOT})
        check("nothing was written where the credentials go", not AUTH_DB.exists())

        try:
            sb.apply_bundle(locked, "wrong-one")
            check("a wrong passphrase is refused", False, "it accepted it")
        except AppError as exc:
            check("a wrong passphrase is refused", "passphrase" in str(exc).lower(), str(exc))

        res = sb.apply_bundle(locked, "hunter2")
        check("the right passphrase restores the accounts database",
              AUTH_DB.is_file() and AUTH_DB.read_bytes().endswith(b"-locked-accounts"))
        check("and the cloud keys", json.loads(secrets_file.read_text())["openai"] == "sk-locked")

    # 8. Nonsense is refused rather than half-applied.
    for name, payload in (("not a bundle", {"hello": "world"}),
                          ("a future format", {"kind": "lama-caravan-settings", "format": 999,
                                               "files": {}}),
                          ("no files section", {"kind": "lama-caravan-settings",
                                                "format": sb.BUNDLE_FORMAT})):
        try:
            sb.validate_bundle(payload)
            check(f"refuses {name}", False, "accepted it")
        except AppError:
            check(f"refuses {name}", True)

    # 9. The preview reports before anything is written.
    fresh = sb.export_bundle()
    preview = sb.preview_import(fresh)
    check("preview of an unchanged bundle changes nothing",
          all(r["action"] != "replace" for r in preview["changes"]),
          str([r for r in preview["changes"] if r["action"] == "replace"]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
