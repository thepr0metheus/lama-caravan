#!/usr/bin/env python3
"""Snapshot: saving a cloud account — a new one, and an edit that sends only
what changed (caravan/admin/cloud.py, upsert_cloud_account).

The board's account editor sends the name, the address and the sign-in mode.
It used to send nothing at all for an existing account — and still said
"saved". Now that it sends, what it leaves out (a custom OAuth setup, the plan
type) must stay as stored rather than fall back to the preset's defaults.

Run: python3 scripts/test_cloud_accounts.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-cloudacct-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
for sub in ("state", "config", "secrets"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# One of the first subscriptions: made as type `openai`, it signs in by code
# through its plan (accountType), with an OAuth setup of its own.
STORED = {"id": "acc", "type": "openai", "name": "Old name", "baseUrl": "https://chatgpt.com/backend-api",
          "authMode": "oauth", "accountType": "openai-subscription",
          "oauthConfig": {"tokenUrl": "https://sso.example/token", "clientId": "custom-cid"}}


def stored():
    return next(a for a in cloud.load_cloud_data()["accounts"] if a["id"] == "acc")


def main():
    print("новый аккаунт:")
    cloud.save_cloud_data({"accounts": [], "blocks": []})
    new = cloud.upsert_cloud_account({"id": "fresh", "type": "openai", "name": "Fresh",
                                      "baseUrl": "https://api.openai.com/v1", "authMode": "apiKey"})
    check(new["accountType"] == "openai-api" and new["authMode"] == "apiKey" and "oauthConfig" not in new,
          "поля, которых нет в запросе, берутся из пресета; у ключа API нет настроек входа")
    oauth_api = cloud.upsert_cloud_account({"id": "api-oauth", "type": "openai", "name": "Api",
                                            "baseUrl": "https://api.openai.com/v1", "authMode": "oauth"})
    check(oauth_api["authMode"] == "apiKey" and "oauthConfig" not in oauth_api,
          "negative: OAuth у ключа API был возвратом на localhost, которого нет — учётка остаётся на ключе")

    print("правка существующего:")
    cloud.save_cloud_data({"accounts": [dict(STORED)], "blocks": []})
    edited = cloud.upsert_cloud_account({"id": "acc", "type": "openai", "name": "New name",
                                         "baseUrl": "https://chatgpt.com/backend-api", "authMode": "oauth"})
    check(edited["name"] == "New name" and stored()["name"] == "New name", "новое имя сохранено")
    check(stored()["oauthConfig"] == STORED["oauthConfig"] and stored()["accountType"] == "openai-subscription"
          and stored()["authMode"] == "oauth",
          "defect-history: то, чего правка не прислала (свой вход OAuth, тип тарифа), осталось как было — "
          f"без слияния нормализация вернула бы значения пресета (got {stored()['oauthConfig'].get('clientId')})")
    replaced = cloud.upsert_cloud_account({"id": "acc", "type": "openai", "oauthConfig": {"clientId": "other"}})
    check(replaced["oauthConfig"]["clientId"] == "other" and replaced["name"] == "New name",
          "as-is: присланное явно заменяет хранимое; неприсланное (имя) остаётся")
    before = dict(stored())
    try:
        cloud.upsert_cloud_account({"id": "acc", "type": "openai", "baseUrl": "10.0.0.9:8000"})
        refused = False
    except AppError as e:
        refused = e.status == 400
    check(refused and stored() == before, "negative: адрес без схемы — 400, хранимый аккаунт не тронут")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cloud accounts OK: правка сохраняет присланное и не трогает остальное")
    return 0


if __name__ == "__main__":
    sys.exit(main())
