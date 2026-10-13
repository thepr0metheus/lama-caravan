#!/usr/bin/env python3
"""Value snapshot: the credential document has one writer, and a write of it
keeps a token renewal that lands at the same moment.

caravan/common/credential_vault.py — `put_api_key` and `replace`, both under the
document lock a renewal takes, both re-reading the file under it;
caravan/admin/cloud_api.py — the board's "set key" goes through the vault.

Found 2026-10-07 and reproduced on the code before the fix: a renewal that
landed between the board's read of the whole file and its write of it was
undone, and the spent refresh token went back into the file. The ChatGPT
subscription then fails its next renewal and needs a new login.

The files are temp files. Nothing is sent anywhere: the key test is stubbed.

Run: python3 scripts/test_secret_writes.py
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-secret-writes-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud_api  # noqa: E402
from caravan.common.credential_vault import CredentialVault  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

SECRETS = Path(os.environ["PROVIDER_SECRETS_FILE"])
SUB_OLD = {"accessToken": "at-0", "refreshToken": "rt-0", "expiresAt": 1}
SUB_NEW = {"accessToken": "at-1", "refreshToken": "rt-1", "expiresAt": 9999999999}

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def put(doc):
    SECRETS.write_text(json.dumps(doc), encoding="utf-8")


def stored():
    return json.loads(SECRETS.read_text(encoding="utf-8"))


def mode():
    return SECRETS.stat().st_mode & 0o777


class RenewalInTheWindow(CredentialVault):
    """The vault the board's key write gets. Right after its read of the file, a
    renewal starts in another thread — what the proxy runs when the token
    endpoint answers — and gets half a second to land before the read is used."""

    renewal = None
    landed_in_window = None

    def read(self):
        data = super().read()
        if RenewalInTheWindow.renewal is None:
            renewal = threading.Thread(target=lambda: CredentialVault(self.path)._put_oauth("sub", dict(SUB_NEW)))
            RenewalInTheWindow.renewal = renewal
            renewal.start()
            renewal.join(0.5)
            RenewalInTheWindow.landed_in_window = not renewal.is_alive()
        return data


def test_key_write_and_renewal():
    print("«set key» на доске и обновление токена подписки в тот же миг:")
    Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({"accounts": [
        {"id": "sub", "type": "openai", "accountType": "openai-subscription", "authMode": "oauth"},
        {"id": "api", "type": "openai", "authMode": "apiKey"}], "blocks": []}), encoding="utf-8")
    put({"sub": {"oauth": dict(SUB_OLD)}, "api": {"apiKey": "sk-old"}})
    keep = (cloud_api.CredentialVault, cloud_api.test_account_key)
    cloud_api.CredentialVault = RenewalInTheWindow
    cloud_api.test_account_key = lambda account, key: {"ok": True}
    try:
        got = cloud_api.set_account_key("api", "sk-new")
    finally:
        cloud_api.CredentialVault, cloud_api.test_account_key = keep
    if RenewalInTheWindow.renewal is not None:      # None: the write went around the vault
        RenewalInTheWindow.renewal.join(2)
    doc = stored()
    check(doc["sub"]["oauth"] == SUB_NEW and doc["api"] == {"apiKey": "sk-new"},
          "оба в файле: новый ключ и обновлённый токен; потраченный rt-0 не вернулся")
    check(RenewalInTheWindow.landed_in_window is False,
          "обновление ждёт, пока запись ключа держит документ: между её чтением и записью оно не встало")
    check(got == {"ok": True, "test": {"ok": True}, "last4": "-new"} and mode() == 0o600,
          "ответ доски прежний: последние 4 знака; файл 0600")


def test_refused_key_writes_nothing():
    print("отказ — ничего не записано:")
    put({"sub": {"oauth": dict(SUB_OLD)}, "api": {"apiKey": "sk-old"}})
    before = SECRETS.read_bytes()
    keep = cloud_api.test_account_key
    cloud_api.test_account_key = lambda account, key: {"ok": False, "status": 401, "error": "key rejected"}
    try:
        got = cloud_api.set_account_key("api", "sk-wrong")
        try:
            cloud_api.set_account_key("nobody", "sk-x")
            unknown = None
        except AppError as exc:
            unknown = exc.status
    finally:
        cloud_api.test_account_key = keep
    check(got["ok"] is False and SECRETS.read_bytes() == before,
          "negative: провайдер не принял ключ — файл не тронут")
    check(unknown == 404 and SECRETS.read_bytes() == before, "negative: учётки нет — 404, файл не тронут")


def test_put_api_key():
    print("ключ встаёт в свою запись, остальное как было:")
    vault = CredentialVault(SECRETS)
    put({"sub": {"oauth": dict(SUB_OLD)}, "legacy": "sk-bare", "other": {"apiKey": "sk-other"}})
    vault.put_api_key("sub", "sk-sub")
    doc = stored()
    check(doc == {"sub": {"oauth": SUB_OLD, "apiKey": "sk-sub"}, "legacy": "sk-bare", "other": {"apiKey": "sk-other"}},
          "ключ встал рядом с токенами этой учётки; чужие записи не тронуты")
    vault.put_api_key("legacy", "sk-2")
    check(stored()["legacy"] == {"apiKey": "sk-2"}, "запись старого вида (строка) стала записью с ключом")
    SECRETS.unlink()
    vault.put_api_key("x", "sk-first")
    check(stored() == {"x": {"apiKey": "sk-first"}} and mode() == 0o600, "файла не было — он появился сразу 0600")


def test_replace_takes_the_lock():
    print("замена всего документа (восстановление настроек) — под тем же замком:")
    put({"sub": {"oauth": dict(SUB_OLD)}})
    before = SECRETS.read_bytes()
    result = {}
    with CredentialVault(SECRETS).locked(".write"):
        restore = threading.Thread(target=lambda: result.update(
            done=CredentialVault(SECRETS).replace({"api": {"apiKey": "sk-restored"}})))
        restore.start()
        restore.join(0.3)
        waited = restore.is_alive() and SECRETS.read_bytes() == before
    restore.join(2)
    check(waited, "пока документ занят (обновление пишет), замена ждёт и файл не трогает")
    check(stored() == {"api": {"apiKey": "sk-restored"}} and mode() == 0o600,
          "потом пишет документ целиком, 0600")
    before = SECRETS.read_bytes()
    try:
        CredentialVault(SECRETS).replace(["not", "an", "object"])
        refused = False
    except ValueError:
        refused = True
    check(refused and SECRETS.read_bytes() == before,
          "negative: не объект — отказ, файл не тронут: иначе он читался бы как «ключей нет»")


for fn in (test_key_write_and_renewal, test_refused_key_writes_nothing, test_put_api_key, test_replace_takes_the_lock):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("secret writes snapshot holds")
