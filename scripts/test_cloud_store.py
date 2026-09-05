#!/usr/bin/env python3
"""The cloud accounts file and the secrets beside it, pinned before either moves.

Two documents with opposite jobs. `cloud-providers.json` is configuration —
accounts and blocks, read on every topology build. `provider-secrets.json` holds
the API keys, is mode 0600, and must never leak into anything the panel renders:
the account list carries `hasCredential` and the last four characters, never the
key.

Both are cached on the file's own (mtime, size), and that is not an optimisation
detail — it is load-bearing. Reading them was treated as free: the credential
summary reads the accounts once per lookup and the block list calls that once per
block, so 502 blocks meant ~500 re-parses of a 99 KB file for ONE request, ~100 MB
of parsing, and every parse holds the GIL — eight tabs polling did not run eight
builds in parallel, they queued behind each other. A rewrite that drops the cache
gets the symptom back (time-to-first-byte 750 ms → 4.5 s) with nothing red.

The other half of that trade is invalidation: a key rotated through the UI or a
file edited by hand must be visible on the very next call, or an operator rotates
a key and the caravan keeps using the old one.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


def run(body, providers=None, secrets=None):
    """A snippet with both cloud files pointed at throwaway paths."""
    script = ("import json, sys\n"
              "from caravan.admin import cloud\n"
              "from caravan.common.errors import AppError\n"
              "def attempt(fn, *a, **k):\n"
              "    try: return {'ok': fn(*a, **k)}\n"
              "    except AppError as exc: return {'refused': str(exc)}\n"
              + body)
    with tempfile.TemporaryDirectory() as tmp:
        prov = Path(tmp) / "cloud-providers.json"
        sec = Path(tmp) / "provider-secrets.json"
        if providers is not None:
            prov.write_text(providers if isinstance(providers, str) else json.dumps(providers),
                            encoding="utf-8")
        if secrets is not None:
            sec.write_text(secrets if isinstance(secrets, str) else json.dumps(secrets),
                           encoding="utf-8")
        env = dict(os.environ, CLOUD_PROVIDERS_FILE=str(prov), PROVIDER_SECRETS_FILE=str(sec),
                   LLAMA_ADMIN_STATE=str(Path(tmp) / "admin.json"), PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                             capture_output=True, text=True)
        mode = oct(sec.stat().st_mode & 0o777) if sec.exists() else ""
        stored = None
        if sec.exists():
            try:
                stored = json.loads(sec.read_text(encoding="utf-8"))
            except ValueError:
                stored = "не JSON"
        return out, mode, stored


LEGACY = {"providers": [
    {"id": "openai-1", "type": "openai", "name": "OpenAI", "baseUrl": "https://api.openai.com/v1",
     "model": "gpt-4", "modelMode": "rewrite"},
]}

PAIRED = {"accounts": [{"id": "acct-1", "type": "openai", "name": "OpenAI",
                        "baseUrl": "https://api.openai.com/v1", "authMode": "apiKey"},
                       # No `id` key at all — the case the filter is for. Not
                       # {"id": "no-id-here"}, which HAS one and rightly survives.
                       {"name": "nameless"}],
          "blocks": [{"id": "blk-1", "accountId": "acct-1", "name": "B", "model": "gpt-4"},
                     {"noid": True}]}


def run_keeping(body, providers=None, secrets=None):
    """Like run(), but answers with the `.unreadable-*` copies left behind."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        prov = Path(tmp) / "cloud-providers.json"
        sec = Path(tmp) / "provider-secrets.json"
        if providers is not None:
            prov.write_text(providers, encoding="utf-8")
        if secrets is not None:
            sec.write_text(secrets, encoding="utf-8")
        script = ("import json, sys\nfrom caravan.admin import cloud\n" + body)
        env = dict(os.environ, CLOUD_PROVIDERS_FILE=str(prov), PROVIDER_SECRETS_FILE=str(sec),
                   LLAMA_ADMIN_STATE=str(Path(tmp) / "admin.json"), PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                             capture_output=True, text=True)
        kept = sorted(p.name for p in Path(tmp).glob("*.unreadable-*"))
        return out, kept


def secrets_sidecar_mode():
    """Mode of the .unreadable copy made from a 0600 secrets file."""
    import os as _os
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        sec = Path(tmp) / "provider-secrets.json"
        sec.write_text('{"acct": {"apiKey": "sk-not-a-real-key', encoding="utf-8")
        _os.chmod(sec, 0o600)
        env = dict(os.environ, PROVIDER_SECRETS_FILE=str(sec),
                   CLOUD_PROVIDERS_FILE=str(Path(tmp) / "cloud-providers.json"),
                   LLAMA_ADMIN_STATE=str(Path(tmp) / "admin.json"), PYTHONPATH=str(ROOT))
        subprocess.run([sys.executable, "-c",
                        "from caravan.admin import cloud; cloud.load_provider_secrets()"],
                       env=env, cwd=ROOT, capture_output=True, text=True)
        copies = sorted(Path(tmp).glob("*.unreadable-*"))
        mode = oct(copies[0].stat().st_mode & 0o777) if copies else "нет копии"
        return mode, [c.name for c in copies]


def main():
    # ── reading ──────────────────────────────────────────────────────────────
    out, _, _ = run('print(json.dumps(cloud.load_cloud_data(), sort_keys=True))')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a missing file reads as empty, not an error",
              got == {"accounts": [], "blocks": []}, str(got)[:200])
    else:
        check("read on a missing file", False, out.stderr.strip()[-300:])

    out, _, _ = run('print(json.dumps(cloud.load_cloud_data(), sort_keys=True))',
                    providers="{ not json")
    if out.returncode == 0:
        check("a corrupt file reads as empty, not a crash",
              json.loads(out.stdout) == {"accounts": [], "blocks": []})
    else:
        check("read on a corrupt file", False, out.stderr.strip()[-300:])

    # An unreadable accounts file reads as "no accounts", and the operator's next
    # edit writes that emptiness over it. These two documents hold the cloud
    # accounts and their API KEYS, so a copy has to survive the first write —
    # the sibling ProxyStore made that choice and this one had not.
    out, kept = run_keeping(
        'cloud.load_cloud_data()\n'
        'cloud.upsert_cloud_account({"id": "acct-new", "type": "openai", "name": "N",\n'
        '                            "baseUrl": "https://x/v1", "authMode": "apiKey"})\n'
        'print("ok")\n',
        providers='{"accounts": [{"id": "acct-real", "type": "openai", "name": "R",')
    check("нечитаемый файл аккаунтов откладывается до первой перезаписи",
          out.returncode == 0 and len(kept) == 1, f"копий: {kept}, stderr: {out.stderr[-200:]}")

    # The copy is as sensitive as the original. provider-secrets.json holds the
    # cloud API keys at 0600; the first version of the sidecar used write_bytes,
    # which creates at the umask default, and left every key world-readable in a
    # file nothing ever cleans up.
    mode, keeps = secrets_sidecar_mode()
    check("копия файла секретов наследует права оригинала", mode == "0o600",
          f"оригинал 0o600, копия {mode}, копий: {keeps}")

    out, _, _ = run('''
d = cloud.load_cloud_data()
print(json.dumps({"accounts": [a["id"] for a in d["accounts"]],
                  "blocks": [b["id"] for b in d["blocks"]]}, sort_keys=True))
''', providers=PAIRED)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("an entry with no id is dropped rather than half-loaded",
              got == {"accounts": ["acct-1"], "blocks": ["blk-1"]}, str(got))
    else:
        check("id filtering", False, out.stderr.strip()[-300:])

    # ── the legacy flat schema ───────────────────────────────────────────────
    out, _, _ = run('print(json.dumps(cloud.load_cloud_data(), sort_keys=True))',
                    providers=LEGACY)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        acct = (got["accounts"] or [{}])[0]
        blk = (got["blocks"] or [{}])[0]
        check("a flat provider list becomes an account and a block",
              len(got["accounts"]) == 1 and len(got["blocks"]) == 1, str(got)[:250])
        check("the block keeps the id the routes already point at",
              blk.get("id") == "openai-1", str(blk))
        check("…and is wired to the account minted for it",
              blk.get("accountId") == acct.get("id") == "openai-1-acct", str(blk))
    else:
        check("legacy migration", False, out.stderr.strip()[-300:])

    # ── the cache, and the invalidation that makes it safe ───────────────────
    out, _, _ = run('''
import json, os, time
from caravan.admin.paths import CLOUD_PROVIDERS_FILE
first = cloud.load_cloud_data()
second = cloud.load_cloud_data()
CLOUD_PROVIDERS_FILE.write_text(json.dumps(
    {"accounts": [{"id": "acct-2", "type": "openai", "name": "N",
                   "baseUrl": "https://x/v1", "authMode": "apiKey"}], "blocks": []}),
    encoding="utf-8")
os.utime(CLOUD_PROVIDERS_FILE, (time.time() + 2, time.time() + 2))
after = cloud.load_cloud_data()
print(json.dumps({"cached": first is second,
                  "sees the edit": [a["id"] for a in after["accounts"]],
                  "one generation kept": len(cloud._CLOUD_DATA_CACHE)}))
''', providers=PAIRED)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a second read of an unchanged file is served from cache",
              got["cached"] is True, str(got))
        check("an edit is picked up on the very next call",
              got["sees the edit"] == ["acct-2"], str(got))
        check("the cache keeps one generation, not one per save",
              got["one generation kept"] <= 1, str(got))
    else:
        check("cloud cache", False, out.stderr.strip()[-300:])

    # ── secrets: the file mode and what never leaves it ──────────────────────
    out, mode, stored = run('''
cloud.save_provider_secrets({"acct-1": {"apiKey": "sk-livekey-ABCD1234"}})
print(json.dumps({"summary": cloud.account_credential_summary("acct-1"),
                  "state": cloud.cloud_accounts_state()}, sort_keys=True))
''', providers=PAIRED)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        summary, state = got["summary"], got["state"]
        check("the secrets file is readable only by its owner", mode == "0o600", mode)
        check("the summary says a credential exists without repeating it",
              summary["hasCredential"] is True and summary["kind"] == "apiKey", str(summary))
        check("only the last four characters are exposed",
              summary["last4"] == "1234", str(summary))
        blob = json.dumps(state)
        check("the key itself never reaches the account list",
              "sk-livekey" not in blob and "ABCD" not in blob, blob[:200])
        check("the account list still says a key is there",
              state and state[0]["hasCredential"] is True and state[0]["keyLast4"] == "1234",
              str(state)[:200])
    else:
        check("secret summary", False, out.stderr.strip()[-300:])

    # ── a key stored the old way (a bare string) still works ─────────────────
    out, _, _ = run('print(json.dumps(cloud.account_secret_entry("acct-1")))',
                    providers=PAIRED, secrets={"acct-1": "sk-bare-string-9876"})
    if out.returncode == 0:
        check("a secret saved as a bare string is read as an apiKey",
              json.loads(out.stdout) == {"apiKey": "sk-bare-string-9876"}, out.stdout.strip())
    else:
        check("legacy secret shape", False, out.stderr.strip()[-300:])

    out, _, _ = run('print(json.dumps(cloud.account_secret_entry("nobody")))', providers=PAIRED)
    check("an account with no secret answers {}, not None",
          out.returncode == 0 and json.loads(out.stdout) == {}, out.stdout.strip())

    # ── no credential at all, and the account that needs none ────────────────
    out, _, _ = run('''
print(json.dumps({
  "no key": cloud.account_credential_summary("acct-1"),
  "noKey account": cloud.account_credential_summary("free-1"),
}, sort_keys=True))
''', providers={"accounts": [
        {"id": "acct-1", "type": "openai", "name": "A", "baseUrl": "https://x/v1", "authMode": "apiKey"},
        {"id": "free-1", "type": "custom", "name": "F", "baseUrl": "https://y/v1", "authMode": "noKey"},
    ], "blocks": []})
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("an account without a key says so", got["no key"]["hasCredential"] is False, str(got))
        check("an account that needs no key counts as credentialled",
              got["noKey account"]["hasCredential"] is True
              and got["noKey account"]["kind"] == "noKey", str(got["noKey account"]))
    else:
        check("credential states", False, out.stderr.strip()[-300:])

    # ── deleting a credential ────────────────────────────────────────────────
    out, _, stored = run('''
cloud.save_provider_secrets({"acct-1": {"apiKey": "sk-a"}, "acct-2": {"apiKey": "sk-b"}})
cloud.delete_account_credential("acct-1")
print(json.dumps(cloud.load_provider_secrets(), sort_keys=True))
''', providers=PAIRED)
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("deleting one credential leaves the others alone",
              got == {"acct-2": {"apiKey": "sk-b"}}, str(got))
        check("…and the file on disk agrees",
              stored == {"acct-2": {"apiKey": "sk-b"}}, str(stored))
    else:
        check("credential deletion", False, out.stderr.strip()[-300:])

    # ── the headers a request actually carries ───────────────────────────────
    out, _, _ = run('''
acct = {"id": "a", "type": "anthropic", "authMode": "apiKey"}
print(json.dumps({
  "apiKey": cloud.account_auth_headers(acct, {"apiKey": "sk-xyz"}),
  "oauth": cloud.account_auth_headers({"id": "b", "type": "anthropic", "authMode": "oauth"},
                                      {"oauth": {"accessToken": "tok-1"}}),
  "nothing": cloud.account_auth_headers(acct, {}),
}, sort_keys=True))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("an api key becomes the provider's own auth header",
              any("sk-xyz" in str(v) for v in got["apiKey"].values()), str(got["apiKey"]))
        check("an oauth token becomes a bearer",
              got["oauth"].get("Authorization") == "Bearer tok-1", str(got["oauth"]))
        check("no credential means no auth header invented",
              not any("Authorization" in k or "api-key" in k.lower() for k in got["nothing"]),
              str(got["nothing"]))
    else:
        check("auth headers", False, out.stderr.strip()[-300:])

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
