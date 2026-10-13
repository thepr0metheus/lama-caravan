#!/usr/bin/env python3
"""Value snapshot: sign-in to a ChatGPT subscription by a one-time code, and
the sign-out a deleted account owes (caravan/admin/oauth.py, DeviceLogin and
SignOut; caravan/admin/cloud.py, device_login_spec and delete_cloud_account).

A fake OpenAI on 127.0.0.1 answers the three requests of the device login
the way auth.openai.com does (measured 2026-10-07): a code for the Codex
client, 403 `deviceauth_authorization_pending` until somebody enters it, then
the authorization code with its PKCE verifier, traded for tokens at the
account's token URL. Like Cloudflare in front of the real one, it refuses
urllib's own User-Agent on the device paths (the token URL takes it).

Pinned: which accounts sign in by code (by accountType — the first
subscription accounts are type `openai`); what the board is shown; that
nothing is taken before the code is entered; the trade uses OpenAI's own
verifier and the device redirect, never localhost; the account's model list
is fetched — "+ Add step" asks for a model next; refusals, expiry and a silent network end the login
with a reason that never quotes the provider's free text; a new start
replaces the account's pending login, and the window waiting on the old one
learns why. Deleting an account sends its own refresh token to the plan's
revoke address once the account is gone here, the way `codex logout` does,
and says when OpenAI did not confirm.

Run: python3 scripts/test_device_login.py
"""
import base64
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-device-login-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
(TMP / "config").mkdir()
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud, model_catalog, oauth  # noqa: E402
from caravan.common.credential_vault import CredentialVault  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# ── the fake OpenAI ──

SEEN = []          # (path, user agent, body) of every request
PLAN = {}          # what the next answers are


def jwt_with(email):
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


class FakeOpenAI(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        agent = self.headers.get("User-Agent") or ""
        SEEN.append((self.path, agent, raw))
        if agent.startswith("Python-urllib") and self.path.startswith("/api/accounts/deviceauth/"):
            return self._send(530, {"error": {"code": 530, "message": "A 1xxx error occured.", "type": "cf_route_error"}})
        if self.path == "/api/accounts/deviceauth/usercode":
            # Each code its own id, the way OpenAI gives them: a poll says whose it is.
            PLAN["codes"] = PLAN.get("codes", 0) + 1
            return self._send(200, {"device_auth_id": f"dev-{PLAN['codes']}", "user_code": "ABCD-12345",
                                    "interval": PLAN.get("interval", "5"), "expires_at": PLAN.get("expires_at", "")})
        if self.path == "/api/accounts/deviceauth/token":
            queue = PLAN.setdefault("poll", [])
            status, body = queue.pop(0) if queue else (403, {"error": {"code": "deviceauth_authorization_pending"}})
            return self._send(status, body)
        if self.path == "/oauth/token":
            status, body = PLAN.get("exchange", (200, {}))
            return self._send(status, body)
        if self.path == "/oauth/revoke":
            status, body = PLAN.get("revoke", (200, {}))
            return self._send(status, body)
        self._send(404, {})


SERVER = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{SERVER.server_address[1]}"
SPEC = {"userCodeUrl": f"{BASE}/api/accounts/deviceauth/usercode", "pollUrl": f"{BASE}/api/accounts/deviceauth/token",
        "verifyUrl": "https://auth.openai.com/codex/device", "redirectUri": "https://auth.openai.com/deviceauth/callback"}
ACCEPTED = (200, {"authorization_code": "auth-code-1", "code_challenge": "chal", "code_verifier": "verifier-from-openai"})
TOKENS = (200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600,
                "id_token": jwt_with("owner@example.test")})


def oauth_config():
    return {"tokenUrl": f"{BASE}/oauth/token", "clientId": "app_test"}


def fresh_data():
    accounts = [
        {"id": "sub-old", "type": "openai", "name": "Old", "baseUrl": "https://chatgpt.com/backend-api",
         "authMode": "oauth", "accountType": "openai-subscription", "oauthConfig": oauth_config()},
        {"id": "sub-new", "type": "openai-subscription", "name": "New", "baseUrl": "https://chatgpt.com/backend-api",
         "authMode": "oauth", "accountType": "openai-subscription", "oauthConfig": oauth_config()},
        {"id": "api", "type": "openai", "name": "API", "baseUrl": "https://api.openai.com/v1", "authMode": "oauth",
         "accountType": "openai-api", "oauthConfig": oauth_config()},
    ]
    pools = [{"id": "pool", "name": "Pool", "steps": [
        {"id": "sub-old", "accountId": "sub-old", "model": "m"}]}]
    cloud.save_cloud_data({"accounts": accounts, "pools": pools, "migrations": []})
    secrets = Path(cloud.PROVIDER_SECRETS_FILE)
    if secrets.exists():
        secrets.unlink()


def account(aid):
    return next(a for a in cloud.load_cloud_data()["accounts"] if a["id"] == aid)


def stored_oauth(aid):
    path = Path(cloud.PROVIDER_SECRETS_FILE)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return (data.get(aid) or {}).get("oauth") or {}


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


KICKED = []
model_catalog.kick_refresh = lambda account_id, fn: KICKED.append(account_id)


def reset(**plan):
    fresh_data()
    SEEN.clear()
    KICKED.clear()
    PLAN.clear()
    PLAN.update(plan)
    oauth._oauth_sessions.clear()


def begun(aid="sub-new", clock=None, **plan):
    reset(**plan)
    login = oauth.DeviceLogin(account(aid), SPEC, clock=clock or Clock())
    return login, login.begin()


def polls():
    return [s for s in SEEN if s[0] == "/api/accounts/deviceauth/token"]


# ── pins ──

def test_who_signs_in_by_code():
    print("кто входит по коду:")
    reset()
    spec = cloud.device_login_spec
    check(spec(account("sub-new")) == cloud.OPENAI_DEVICE_LOGIN, "подписка (тип openai-subscription) — вход по коду OpenAI")
    check(spec(account("sub-old")) == cloud.OPENAI_DEVICE_LOGIN,
          "первая подписка (тип openai, accountType openai-subscription) — тоже по коду")
    check(spec(account("api")) == {} and spec({}) == {} and spec(None) == {},
          "negative: учётка API и пустая запись — входа по коду нет")
    check(spec({**account("sub-new"), "testAliasOf": "sub-new"}) == {}, "negative: тестовый двойник входит через оригинал")
    presets = {p["type"]: p["deviceLogin"] for p in cloud.cloud_provider_presets_public()}
    check(presets["openai-subscription"] is True and presets["openai"] is False and presets["anthropic"] is False,
          "доска знает о входе по коду из пресета")
    states = {a["id"]: a["deviceLogin"] for a in cloud.cloud_accounts_state()}
    check(states == {"sub-old": True, "sub-new": True, "api": False},
          f"и из каждой учётки; negative: пул — не учётка, его в списке нет (got {states})")
    check(cloud.OPENAI_DEVICE_LOGIN["verifyUrl"] == "https://auth.openai.com/codex/device"
          and cloud.OPENAI_DEVICE_LOGIN["redirectUri"] == "https://auth.openai.com/deviceauth/callback",
          "страница для кода и адрес обмена — OpenAI, не localhost")


def test_board_is_shown_a_code():
    print("доска получает код:")
    clock = Clock()
    login, shown = begun(clock=clock, interval="5",
                         expires_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(clock.now + 600)))
    check(shown == {"state": login.state, "userCode": "ABCD-12345", "verifyUrl": "https://auth.openai.com/codex/device",
                    "expiresAt": int(clock.now + 600), "interval": 5},
          f"код, страница, срок от OpenAI и пауза (got {shown})")
    path, agent, body = SEEN[0]
    check(path == "/api/accounts/deviceauth/usercode" and json.loads(body) == {"client_id": "app_test"},
          "код просят для клиента учётки")
    check(agent.startswith("lama-caravan/"), f"запрос назван (Cloudflare не пускает Python-urllib) (got {agent})")
    check(login.result == {"state": "pending"} and polls() == [], "пока ничего не спрошено — вход ждёт")
    login, shown = begun(clock=clock, expires_at="soon")
    check(shown["expiresAt"] == int(clock.now + 900), "срок не прочитан — 15 минут, как у Codex")
    login, shown = begun(clock=clock, expires_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(clock.now - 60)))
    check(shown["expiresAt"] == int(clock.now + 900), "negative: срок в прошлом (часы врут) — 15 минут, а не мгновенный отказ")
    check([oauth.DeviceLogin.pause(x) for x in ("5", 7, "0", None, "junk", "120")] == [5, 7, 5, 5, 5, 60],
          "пауза: строка или число; ноль, пусто, мусор — 5 с; не дольше минуты")
    check(oauth.DeviceLogin.moment(1_800_000_000) == 1_800_000_000.0 and oauth.DeviceLogin.moment(True) == 0.0
          and oauth.DeviceLogin.moment("2027-01-15T08:00:00Z") == 1800000000.0,
          "срок: число, ISO с Z; negative: True — не срок")


def test_code_entered_login_taken():
    print("код введён — вход взят:")
    login, _ = begun(poll=[(403, {"error": {"code": "deviceauth_authorization_pending"}}), (404, {}), ACCEPTED],
                     exchange=TOKENS)
    check([login.step(), login.step()] == ["pending", "pending"] and stored_oauth("sub-new") == {},
          "403 и 404 — ждём, ничего не взято")
    check(login.step() == "done" and login.result == {"state": "done", "email": "owner@example.test"},
          f"код введён — вход есть, с почтой (got {login.result})")
    poll_bodies = [json.loads(b) for _p, _a, b in polls()]
    check(poll_bodies == [{"device_auth_id": "dev-1", "user_code": "ABCD-12345"}] * 3, "каждый вопрос — по своему коду")
    trade = urllib.parse.parse_qs(next(b for p, _a, b in SEEN if p == "/oauth/token"))
    check(trade == {"grant_type": ["authorization_code"], "code": ["auth-code-1"], "client_id": ["app_test"],
                    "redirect_uri": ["https://auth.openai.com/deviceauth/callback"], "code_verifier": ["verifier-from-openai"]},
          f"обмен: код и verifier от OpenAI, адрес обмена устройства (got {trade})")
    kept = stored_oauth("sub-new")
    check(kept.get("accessToken") == "access-1" and kept.get("refreshToken") == "refresh-1"
          and kept.get("email") == "owner@example.test", "токены записаны в хранилище учётки")
    check(KICKED == ["sub-new"], f"после входа берётся список моделей учётки — следующий вопрос «+ Add step» (got {KICKED})")
    asked = len(SEEN)
    check(login.step() == "done" and len(SEEN) == asked, "после входа OpenAI больше не спрашивают")


def test_refusals_end_with_a_reason():
    print("отказы с причиной, без чужого текста:")
    login, _ = begun(poll=[(400, {"error": {"code": "deviceauth_denied", "message": "quoted ABCD-12345 secret"}})])
    check(login.step() == "error" and login.result["error"] == "OpenAI refused the sign-in (HTTP 400 deviceauth_denied)",
          f"OpenAI отказал — статус и слово ошибки (got {login.result})")
    check("secret" not in json.dumps(login.result) and stored_oauth("sub-new") == {}, "negative: свободный текст ответа не попадает")
    cloudflare = urllib.error.HTTPError("u", 530, "x", {}, __import__("io").BytesIO(b'{"error":{"code":530,"type":"cf_route_error"}}'))
    check(oauth.LoginFailure.describe(cloudflare) == "HTTP 530", "negative: числовой код Cloudflare повторяет статус — не слово")
    clock = Clock()
    login, _ = begun(clock=clock)
    clock.now += 901
    check(login.step() == "error" and login.result["error"] == "the code expired; start the sign-in again"
          and login.result.get("reason") == "expired"
          and polls() == [], "код истёк — отказ без вопроса OpenAI")
    login, _ = begun(poll=[(200, {"code_challenge": "c"})])
    check(login.step() == "error" and login.result["error"] == "OpenAI accepted the code but sent no login",
          "принят, но без кода входа — отказ")
    login, _ = begun(poll=[ACCEPTED], exchange=(400, {"error": "invalid_grant", "error_description": "code auth-code-1 used"}))
    check(login.step() == "error" and login.result["error"] == "the login was not taken (HTTP 400 invalid_grant); start the sign-in again",
          f"обмен не прошёл — причина словом протокола (got {login.result})")
    check("auth-code-1" not in json.dumps(login.result) and stored_oauth("sub-new") == {} and KICKED == [],
          "negative: код не цитируется, вход не взят, список моделей не спрошен")


def test_silent_network():
    print("сеть молчит:")
    login, _ = begun()
    real = login.request
    login.request = Mock(side_effect=urllib.error.URLError(TimeoutError("timed out")))
    states = [login.step() for _ in range(4)]
    check(states == ["pending"] * 4, "четыре сбоя подряд — ещё ждём")
    login.request = real
    check(login.step() == "pending" and login.failures == 0, "OpenAI ответил «ждём» — счёт сбоев с нуля")
    login.request = Mock(side_effect=urllib.error.URLError(TimeoutError("timed out")))
    states = [login.step() for _ in range(5)]
    check(states == ["pending"] * 4 + ["error"] and login.result["error"] == "OpenAI did not answer (no answer: timed out)",
          f"пять сбоев подряд — отказ с причиной (got {states[-1]} {login.result})")


def test_start_replaces_and_finishes():
    print("старт входа по коду:")
    reset(interval="1", poll=[ACCEPTED], exchange=TOKENS)
    keep = oauth.device_login_spec
    oauth.device_login_spec = lambda acct: dict(SPEC) if acct.get("accountType") == "openai-subscription" else {}
    try:
        stopped = []
        oauth._oauth_sessions["old"] = {"accountId": "sub-new", "result": {"state": "pending"},
                                        "startedAt": time.time(), "stop": lambda: stopped.append("old")}
        oauth._oauth_sessions["other"] = {"accountId": "sub-old", "result": {"state": "pending"},
                                          "startedAt": time.time(), "stop": lambda: stopped.append("other")}
        oauth._oauth_sessions["signed"] = {"accountId": "sub-new", "result": {"state": "done", "email": "a@example.test"},
                                           "startedAt": time.time(), "stop": lambda: stopped.append("signed")}
        shown = oauth.start_device_login("sub-new")
        check(set(oauth._oauth_sessions) == {"other", shown["state"]} and "old" in stopped and "other" not in stopped,
              "прежний вход этой учётки снят (перестал спрашивать OpenAI), чужой остался")
        check(oauth.oauth_login_status("old") == dict(oauth.REPLACED)
              and oauth.oauth_login_status("old")["reason"] == "replaced",
              "окно, что ждёт прежний код, узнаёт: код заменён новым входом — а не «unknown» (2026-10-07)")
        check(oauth.oauth_login_status("signed") == {"state": "done", "email": "a@example.test"},
              "negative: вход, что уже состоялся, не становится «заменённым» — он помнит свой ответ")
        check(oauth.oauth_login_status(shown["state"]) == {"state": "pending"}, "статус по state — «ждём»")
        deadline = time.time() + 5
        while time.time() < deadline and oauth.oauth_login_status(shown["state"])["state"] == "pending":
            time.sleep(0.05)
        check(oauth.oauth_login_status(shown["state"]) == {"state": "done", "email": "owner@example.test"},
              "поток сам спросил OpenAI и взял вход")
        reset()
        got = None
        try:
            oauth.start_device_login("api")
        except AppError as exc:
            got = (exc.status, str(exc))
        check(got == (400, "this account's provider has no sign-in by code") and oauth._oauth_sessions == {},
              f"negative: учётка без входа по коду — 400, ничего не начато (got {got})")
        try:
            oauth.start_device_login("nobody")
        except AppError as exc:
            got = exc.status
        check(got == 404, "negative: неизвестная учётка — 404")
    finally:
        oauth.device_login_spec = keep


def test_deleted_account_takes_its_login():
    print("удалённая учётка забирает свой вход:")
    login, _ = begun(poll=[ACCEPTED], exchange=TOKENS)
    data = cloud.load_cloud_data()
    data["accounts"] = [a for a in data["accounts"] if a["id"] != "sub-new"]
    cloud.save_cloud_data(data)
    check(login.step() == "error" and login.result["error"] == "the subscription was removed during login",
          f"учётку удалили, пока ждали код — вход не взят (got {login.result})")
    check(not any(p == "/oauth/token" for p, _a, _b in SEEN) and stored_oauth("sub-new") == {},
          "negative: код не обменян, токенов для удалённой учётки нет")
    reset(interval="1")
    keep = oauth.device_login_spec
    oauth.device_login_spec = lambda acct: dict(SPEC)
    try:
        shown = oauth.start_device_login("sub-new")
        other = oauth.start_device_login("sub-old")
        cloud.delete_cloud_account("sub-new")
        check(oauth.oauth_login_status(shown["state"]) == dict(oauth.REMOVED)
              and oauth.oauth_login_status(other["state"]) == {"state": "pending"},
              "удаление учётки снимает её вход и так и говорит окну; negative: вход другой учётки идёт дальше")
        def asked(dev):
            return sum(1 for _p, _a, b in polls() if json.loads(b).get("device_auth_id") == dev)
        time.sleep(1.2)
        gone, kept = asked("dev-1"), asked("dev-2")
        time.sleep(2.4)
        check(asked("dev-1") == gone and asked("dev-2") > kept,
              f"снятый вход больше не спрашивает OpenAI, живой спрашивает (dev-1 {gone}→{asked('dev-1')}, dev-2 {kept}→{asked('dev-2')})")
    finally:
        oauth.device_login_spec = keep
        oauth.end_pending_logins("sub-old")


def test_ended_logins_keep_their_reason():
    print("кончившийся вход помнит, почему кончился:")
    now = [1000.0]
    ended = oauth.EndedLogins(clock=lambda: now[0])
    ended.note("s1", oauth.REPLACED)
    check(ended.result("s1") == dict(oauth.REPLACED), "заменённый код — «заменён»")
    check(ended.result("never") is None, "negative: вход, которого не было, — ничего (статус скажет unknown)")
    now[0] += oauth.EndedLogins.KEEP
    check(ended.result("s1") is None, "через 30 минут запись уходит: кода уже нет ни на одном экране")
    ended.note("s2", oauth.REMOVED)
    check(set(ended._ended) == {"s2"}, "negative: старые записи не копятся — уходят при следующей записи")
    check(oauth.oauth_login_status("no-such-state") == {"state": "unknown"},
          "статус входа, которого этот контроллер не знал, — unknown")


def revokes():
    return [(agent, json.loads(body)) for path, agent, body in SEEN if path == "/oauth/revoke"]


def test_delete_signs_out():
    print("удаление учётки завершает её вход у OpenAI:")
    keep = oauth.device_login_preset
    plan = {"tokenUrl": f"{BASE}/oauth/token", "clientId": "app_plan", "revokeUrl": f"{BASE}/oauth/revoke"}
    oauth.device_login_preset = lambda kind: {"oauth": dict(plan)} if kind == "openai-subscription" else {}
    vault = CredentialVault(Path(cloud.PROVIDER_SECRETS_FILE))
    try:
        reset()
        vault.put_oauth("sub-new", {"accessToken": "access-9", "refreshToken": "refresh-9"})
        vault.put_oauth("sub-old", {"accessToken": "access-8", "refreshToken": "refresh-8"})
        vault.put_api_key("api", "sk-test-0000")
        told = {a["id"]: a["signOutOnDelete"] for a in cloud.cloud_accounts_state()}
        check(told.get("sub-new") is True and told.get("sub-old") is True and told.get("api") is False,
              f"доска знает заранее, чьё удаление завершит вход у OpenAI; negative: учётка с ключом — нет (got {told})")
        got = cloud.delete_cloud_account("sub-new")
        sent = revokes()
        check(got == {"ok": True, "error": ""} and [b for _a, b in sent] == [
              {"token": "refresh-9", "token_type_hint": "refresh_token", "client_id": "app_test"}],
              f"OpenAI получил отзыв токена обновления с клиентом, которому его выдали — как в codex logout (got {got}, {sent})")
        check(sent and sent[0][0].startswith("lama-caravan/"),
              "запрос идёт под именем каравана, а не urllib: Cloudflare перед OpenAI отказывает urllib")
        check(stored_oauth("sub-new") == {} and all(a["id"] != "sub-new" for a in cloud.load_cloud_data()["accounts"])
              and stored_oauth("sub-old").get("refreshToken") == "refresh-8",
              "учётка и её токены ушли с контроллера; negative: токены второго подключения на месте")
        SEEN.clear()
        data = cloud.load_cloud_data()
        data["accounts"].append({**account("sub-old"), "id": "sub-old-test", "testAliasOf": "sub-old"})
        cloud.save_cloud_data(data)
        refused = None
        try:
            cloud.delete_cloud_account("sub-old")
        except AppError as exc:
            refused = exc.status
        check(refused == 409 and revokes() == [] and stored_oauth("sub-old").get("refreshToken") == "refresh-8",
              "negative: удаление отказано (у учётки есть тестовый двойник) — у OpenAI ничего не отозвано, вход цел")

        reset(revoke=(400, {"error": "invalid_request", "error_description": "token refresh-7 is bad"}))
        data = cloud.load_cloud_data()
        data["pools"] = []
        cloud.save_cloud_data(data)
        vault.put_oauth("sub-old", {"accessToken": "access-7", "refreshToken": "refresh-7"})
        got = cloud.delete_cloud_account("sub-old")
        check(got == {"ok": False, "error": "HTTP 400 invalid_request"} and stored_oauth("sub-old") == {}
              and all(a["id"] != "sub-old" for a in cloud.load_cloud_data()["accounts"]),
              f"OpenAI отказал — учётка всё равно удалена здесь, отказ назван; negative: свободный текст OpenAI с токеном не пересказан (got {got})")

        SEEN.clear()
        PLAN.clear()
        vault.put_oauth("sub-new", {"accessToken": "access-6", "refreshToken": ""})
        got = cloud.delete_cloud_account("sub-new")
        check(got == {"ok": True, "error": ""} and [b for _a, b in revokes()] == [
              {"token": "access-6", "token_type_hint": "access_token"}],
              "токена обновления нет — отзывается токен доступа, без клиента (как в Codex)")

        reset()
        plan["revokeUrl"] = "http://127.0.0.1:9/oauth/revoke"
        data = cloud.load_cloud_data()
        data["pools"] = []
        cloud.save_cloud_data(data)
        vault.put_oauth("sub-old", {"accessToken": "access-5", "refreshToken": "refresh-5"})
        got = cloud.delete_cloud_account("sub-old")
        check(not got["ok"] and got["error"].startswith("no answer:") and stored_oauth("sub-old") == {},
              f"OpenAI молчит — учётка удалена, и сказано, что выход не подтверждён (got {got})")
        plan["revokeUrl"] = f"{BASE}/oauth/revoke"

        SEEN.clear()
        vault.put_api_key("api", "sk-test-0000")
        check(cloud.delete_cloud_account("api") is None and revokes() == [] and "api" not in vault.read(),
              "negative: учётка с ключом — отзывать нечего, OpenAI не спрошен")
        check(cloud.delete_cloud_account("nobody") is None and revokes() == [],
              "negative: неизвестная учётка — ничего не отозвано")
        alias = {"id": "sub-alias", "testAliasOf": "sub-new", "accountType": "openai-subscription"}
        check(oauth.SignOut.of(alias, {"oauth": {"refreshToken": "r"}}) is None
              and oauth.SignOut.of({"id": "x", "accountType": "openai-subscription"}, {"oauth": {}}) is None,
              "negative: тестовый двойник входит через оригинал, пустой вход — отзывать нечего")
        check(oauth.SignOut.of({"id": "x", "accountType": "openai-subscription",
                                "oauthConfig": {"revokeUrl": "http://evil.example/steal"}},
                               {"oauth": {"refreshToken": "r"}}).url == plan["revokeUrl"],
              "negative: адрес из записи учётки не получает токен — только адрес её плана")
    finally:
        oauth.device_login_preset = keep


for fn in (test_who_signs_in_by_code, test_board_is_shown_a_code, test_code_entered_login_taken,
           test_refusals_end_with_a_reason, test_silent_network, test_start_replaces_and_finishes,
           test_deleted_account_takes_its_login, test_ended_logins_keep_their_reason, test_delete_signs_out):
    try:
        fn()
    except Exception as exc:  # a step that throws is that group's red, not the end of the snapshot
        check(False, f"{fn.__name__} оборвался: {type(exc).__name__}: {exc}")

SERVER.shutdown()
print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("device login snapshot holds")
