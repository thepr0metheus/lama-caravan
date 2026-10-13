"""Signing a cloud account in and out: a subscription signs in by a one-time
code (DeviceLogin), its tokens are renewed through the credential vault, and a
deleted account's sign-in is ended at the provider (SignOut).

The other way — a return to http://localhost:1455 — is gone (2026-10-07, the
operator's word). It finished only in a browser on the controller's own
machine, which a controller on a NAS or in a container does not have, and it
sat beside the code as a second button that could not work there.
"""
import base64
import json
import re
import secrets as secrets_mod
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from caravan import __version__
from caravan.admin.cloud import (
    account_secret_entry,
    device_login_preset,
    device_login_spec,
    load_cloud_data,
)
from caravan.common.errors import AppError
from caravan.common.credential_vault import CredentialVault
from caravan.admin.paths import PROVIDER_SECRETS_FILE


_oauth_sessions = {}

_oauth_lock = threading.Lock()


class EndedLogins:
    """Why a login the board still waits on is no longer pending.

    A new start replaces the account's pending login, and a deleted account
    takes its login with it. The board kept asking about the old one and got
    "unknown" — it could not tell a code replaced from another window from a
    controller that restarted (found 2026-10-07: a code shown in one window was
    replaced from another, and the first window went on waiting). Each ended
    login keeps its reason here for as long as a code could still be on
    someone's screen.
    """

    KEEP = 30 * 60

    def __init__(self, clock=time.time):
        self.clock = clock
        self._ended = {}

    def note(self, state, result):
        now = self.clock()
        self._ended = {s: e for s, e in self._ended.items() if now - e[0] < self.KEEP}
        self._ended[state] = (now, dict(result))

    def result(self, state):
        found = self._ended.get(state)
        if not found or self.clock() - found[0] >= self.KEEP:
            return None
        return dict(found[1])


ENDED = EndedLogins()

#: What a replaced or removed login says when the board asks about it.
REPLACED = {"state": "error", "reason": "replaced",
            "error": "a newer sign-in replaced this code — use the code shown last"}
REMOVED = {"state": "error", "reason": "removed", "error": "the account was removed during the sign-in"}

def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _decode_jwt_email(id_token):
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return str(data.get("email") or data.get("preferred_username") or "")
    except Exception:
        return ""

def _exchange_oauth_code(account, code, verifier, redirect_uri):
    cfg = account.get("oauthConfig") or {}
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.get("clientId") or "",
        "code_verifier": verifier,
    }).encode("ascii")
    req = urllib.request.Request(cfg.get("tokenUrl") or "", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))

def _store_oauth_tokens(account_id, tokens):
    now = int(time.time())
    oauth = {
        "accessToken": tokens.get("access_token") or "",
        "refreshToken": tokens.get("refresh_token") or "",
        "tokenType": tokens.get("token_type") or "Bearer",
        "scope": tokens.get("scope") or "",
        "expiresAt": now + int(tokens.get("expires_in") or 0) if tokens.get("expires_in") else 0,
        "obtainedAt": now,
        "email": _decode_jwt_email(tokens.get("id_token") or ""),
    }
    CredentialVault(PROVIDER_SECRETS_FILE).put_oauth(account_id, oauth)
    return oauth

class LoginFailure:
    """What a failed step of a sign-in may say about itself.

    The provider's answer can quote the one-use code or a token, so only its
    HTTP status and its error code — one word of the protocol — are kept,
    never its free text. Before 1.3.443 a failed sign-in said only "OAuth
    completion failed" and the reason was lost.
    """

    #: A word of the protocol has a letter: Cloudflare's numeric codes repeat
    #: the status and say nothing more.
    CODE_RE = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9_.-]{1,64}$")

    @classmethod
    def describe(cls, exc):
        if isinstance(exc, AppError):
            return str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            word = cls._error_word(exc)
            return f"HTTP {exc.code}" + (f" {word}" if word else "")
        if isinstance(exc, urllib.error.URLError):
            return f"no answer: {cls._reason(exc.reason)}"
        if isinstance(exc, OSError):
            return f"no answer: {cls._reason(exc)}"
        if isinstance(exc, ValueError):
            return "a malformed answer"
        return type(exc).__name__

    @classmethod
    def _error_word(cls, exc):
        try:
            error = json.loads(exc.read(4096).decode("utf-8", "replace")).get("error")
        except Exception:
            return ""
        word = (error.get("code") or error.get("type")) if isinstance(error, dict) else error
        return str(word) if word and cls.CODE_RE.match(str(word)) else ""

    @staticmethod
    def _reason(reason):
        if isinstance(reason, TimeoutError):
            return "timed out"
        text = getattr(reason, "strerror", None) or (reason if isinstance(reason, str) else type(reason).__name__)
        return str(text)[:120]

def _oauth_account(account_id):
    """The account a login is for; refused when it cannot sign in with OAuth."""
    account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
    if account and account.get("testAliasOf"):
        raise AppError("a test alias uses its original account login", 400)
    if not account:
        raise AppError("unknown account", 404)
    if account.get("authMode") != "oauth":
        raise AppError("account authMode is not oauth", 400)
    cfg = account.get("oauthConfig") or {}
    if not cfg.get("tokenUrl") or not cfg.get("clientId"):
        raise AppError("account oauthConfig incomplete (tokenUrl/clientId)", 400)
    return account

def _finish_login(account_id, tokens):
    """The one ending of every way to sign in: keep the tokens and fetch the
    account's model list — the next thing "+ Add step" asks for is a model."""
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise AppError("the provider returned no login token", 502)
    oauth = _store_oauth_tokens(account_id, tokens)
    from caravan.admin import model_catalog
    from caravan.admin.cloud_api import refresh_account_models_cache
    model_catalog.kick_refresh(account_id, lambda: refresh_account_models_cache(account_id))
    return {"state": "done", "email": oauth.get("email", "")}

def _end_pending(account_id, why):
    """End the account's pending logins: a new start replaces them (one login
    per account at a time), and a deleted account takes them with it — `why`
    is what a board still waiting on one of them is told (REPLACED, REMOVED).
    One already trading its code is left to finish: it checks that its account
    is still there before it keeps anything."""
    with _oauth_lock:
        old = [(key, _oauth_sessions.pop(key)) for key, sess in list(_oauth_sessions.items())
               if sess.get("accountId") == account_id and not sess.get("completing")]
        for key, session in old:
            # One that already ended on its own keeps its own answer: a done
            # login is not "replaced" because the account signed in again.
            ended = (session.get("result") or {}).get("state") not in (None, "pending")
            ENDED.note(key, session["result"] if ended else why)
    for _key, session in old:
        stop = session.get("stop")
        if stop is not None:
            stop()

def refresh_oauth_token(account):
    """Renew through the same per-account lock the data plane uses."""
    try:
        oauth = CredentialVault(PROVIDER_SECRETS_FILE).oauth(
            account.get("credentialAccountId") or account["id"], account.get("oauthConfig") or {})
        return {"ok": True, "oauth": oauth} if oauth else None
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def oauth_login_status(state):
    """Where a login stands: pending, done, error — with `reason` "replaced" or
    "removed" for one a newer start or a deletion ended — or "unknown" for one
    this controller never had (or forgot when it restarted)."""
    state = str(state or "")
    with _oauth_lock:
        sess = _oauth_sessions.get(state)
        if sess:
            return dict(sess["result"])
        return ENDED.result(state) or {"state": "unknown"}


class DeviceLogin:
    """Sign in to a ChatGPT subscription with a one-time code — OpenAI's
    device authorization for the Codex app (`codex login --device-auth`).

    The board shows OpenAI's page and a code; the operator opens the page on
    any computer, signs in there and types the code; the controller asks
    OpenAI every few seconds whether the code was entered and takes the login
    itself. Nothing returns to localhost: a controller on a NAS or in a
    container finishes it by itself.

    One instance is one login. `begin()` gets the code, `step()` asks OpenAI
    once and says where the login stands, `run()` repeats `step()` in the
    login's thread until it is done, refused, expired or replaced. The board
    reads the login's `result` through `_oauth_sessions`.
    """

    #: Cloudflare in front of auth.openai.com answers urllib's own User-Agent
    #: (`Python-urllib/3.x`) on the device paths with HTTP 530 "1xxx" —
    #: measured 2026-10-07; a named client passes.
    HEADERS = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": f"lama-caravan/{__version__}"}
    #: OpenAI's answer while nobody has entered the code yet: 403
    #: `deviceauth_authorization_pending`. Codex waits on 404 as well.
    PENDING = (403, 404)
    #: How long a code lives: OpenAI's `expires_at` and Codex's own limit.
    LIFETIME = 15 * 60
    #: The pause between two questions when OpenAI names none (it says 5 s).
    INTERVAL = 5
    #: Failures to reach OpenAI in a row before the login gives up.
    PATIENCE = 5

    def __init__(self, account, spec, request=urllib.request.urlopen, clock=time.time):
        self.account = account
        self.spec = spec
        self.request = request
        self.clock = clock
        self.state = _b64url(secrets_mod.token_bytes(16))
        self.stopped = threading.Event()
        self.session = {"accountId": account["id"], "result": {"state": "pending"},
                        "startedAt": int(clock()), "stop": self.stopped.set}
        self.device_auth_id = ""
        self.user_code = ""
        self.interval = self.INTERVAL
        self.expires_at = 0.0
        self.failures = 0

    @property
    def result(self):
        with _oauth_lock:
            return dict(self.session["result"])

    def _post(self, url, payload):
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=dict(self.HEADERS), method="POST")
        with self.request(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def begin(self):
        """Ask OpenAI for a code. Answers what the board shows: `userCode`, the
        page to enter it on, until when it works, and this login's `state`."""
        client_id = (self.account.get("oauthConfig") or {}).get("clientId") or ""
        try:
            answer = self._post(self.spec["userCodeUrl"], {"client_id": client_id})
        except Exception as exc:
            raise AppError(f"OpenAI gave no sign-in code ({LoginFailure.describe(exc)})", 502)
        self.device_auth_id = str(answer.get("device_auth_id") or "")
        self.user_code = str(answer.get("user_code") or answer.get("usercode") or "")
        if not self.device_auth_id or not self.user_code:
            raise AppError("OpenAI gave no sign-in code (its answer has none)", 502)
        self.interval = self.pause(answer.get("interval"))
        now = self.clock()
        stated = self.moment(answer.get("expires_at"))
        self.expires_at = stated if now < stated < now + self.LIFETIME else now + self.LIFETIME
        return {"state": self.state, "userCode": self.user_code, "verifyUrl": self.spec["verifyUrl"],
                "expiresAt": int(self.expires_at), "interval": self.interval}

    @classmethod
    def pause(cls, raw):
        """OpenAI sends the pause as a string ("5"). None, zero or junk is the
        default; no pause is longer than a minute."""
        try:
            seconds = int(float(raw))
        except (TypeError, ValueError):
            return cls.INTERVAL
        return min(seconds, 60) if seconds > 0 else cls.INTERVAL

    @staticmethod
    def moment(raw):
        """`expires_at` as Unix seconds — an ISO time or a number — or 0 when it
        is missing or unreadable."""
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return 0.0

    def step(self):
        """Ask OpenAI once whether the code was entered, and take the login when
        it was. Answers where the login stands: pending, done or error."""
        current = self.result["state"]
        if current != "pending":
            return current
        if self.clock() >= self.expires_at:
            return self._end({"state": "error", "reason": "expired", "error": "the code expired; start the sign-in again"})
        try:
            answer = self._post(self.spec["pollUrl"],
                                {"device_auth_id": self.device_auth_id, "user_code": self.user_code})
        except urllib.error.HTTPError as exc:
            if exc.code in self.PENDING:
                self.failures = 0
                return "pending"
            return self._end({"state": "error", "error": f"OpenAI refused the sign-in ({LoginFailure.describe(exc)})"})
        except Exception as exc:
            # The network, or a reply that is not JSON: OpenAI may come back.
            self.failures += 1
            if self.failures < self.PATIENCE:
                return "pending"
            return self._end({"state": "error", "error": f"OpenAI did not answer ({LoginFailure.describe(exc)})"})
        self.failures = 0
        code, verifier = answer.get("authorization_code"), answer.get("code_verifier")
        if not code or not verifier:
            return self._end({"state": "error", "error": "OpenAI accepted the code but sent no login"})
        if not self._account_kept():
            # Deleted while the code waited: its login has nowhere to go, and a
            # credential kept for a removed account would outlive it unseen.
            return self._end({"state": "error", "error": "the subscription was removed during login"})
        with _oauth_lock:
            self.session["completing"] = True
        try:
            tokens = _exchange_oauth_code(self.account, code, verifier, self.spec["redirectUri"])
            result = _finish_login(self.account["id"], tokens)
        except Exception as exc:
            result = {"state": "error",
                      "error": f"the login was not taken ({LoginFailure.describe(exc)}); start the sign-in again"}
        return self._end(result)

    def _account_kept(self):
        return any(a.get("id") == self.account["id"] for a in load_cloud_data()["accounts"])

    def _end(self, result):
        with _oauth_lock:
            self.session["result"] = result
            self.session["completing"] = False
        self.stopped.set()
        return result["state"]

    def run(self):
        """Ask OpenAI every `interval` seconds until the login ends or a newer
        start replaces it."""
        while not self.stopped.wait(self.interval):
            if self.step() != "pending":
                return

class SignOut:
    """End a deleted account's sign-in at the provider — the request `codex
    logout` sends (openai/codex, codex-rs/login/src/auth/revoke.rs): the
    refresh token with the client it was issued to, or the access token when
    there is no refresh token.

    Until 2026-10-07 deleting a subscription forgot its tokens here and told
    OpenAI nothing: the sign-in stayed valid there, and no screen of the
    caravan could end it any more. The account goes first either way, as in
    Codex; a provider that does not confirm is said out loud, not hidden.

    Only the account's own tokens leave, and only to its plan's address: a
    test alias signs in through its original, a pool has no tokens of its
    own, and an address stored with the account is not trusted with a token.
    """

    #: Codex waits 10 s for the same answer.
    TIMEOUT = 10

    def __init__(self, url, oauth, client_id, request=urllib.request.urlopen):
        self.url = url
        self.oauth = dict(oauth)
        self.client_id = client_id
        self.request = request

    @classmethod
    def of(cls, account, removed, request=urllib.request.urlopen):
        """The sign-out a deleted account owes, or None when it owes none.
        `removed` is the credential entry the vault gave up (CredentialVault.delete)."""
        if not account or account.get("testAliasOf") or account.get("isPool"):
            return None
        oauth = removed.get("oauth") if isinstance(removed, dict) else None
        if not isinstance(oauth, dict) or not (oauth.get("refreshToken") or oauth.get("accessToken")):
            return None
        plan = device_login_preset(account.get("accountType")).get("oauth") or {}
        if not plan.get("revokeUrl"):
            return None
        client_id = (account.get("oauthConfig") or {}).get("clientId") or plan.get("clientId") or ""
        return cls(plan["revokeUrl"], oauth, client_id, request)

    def body(self):
        refresh = str(self.oauth.get("refreshToken") or "")
        if refresh:
            return {"token": refresh, "token_type_hint": "refresh_token", "client_id": self.client_id}
        return {"token": str(self.oauth.get("accessToken") or ""), "token_type_hint": "access_token"}

    def send(self):
        """{ok: true} once the provider confirms; {ok: false, error} when it does not."""
        req = urllib.request.Request(self.url, data=json.dumps(self.body()).encode("utf-8"),
                                     headers=dict(DeviceLogin.HEADERS), method="POST")
        try:
            with self.request(req, timeout=self.TIMEOUT) as response:
                response.read(4096)
        except Exception as exc:
            return {"ok": False, "error": LoginFailure.describe(exc)}
        return {"ok": True, "error": ""}


def end_pending_logins(account_id):
    """A deleted account's sign-in in progress ends with it — a sign-in by code
    would otherwise keep asking OpenAI for up to 15 minutes."""
    _end_pending(str(account_id or ""), REMOVED)

def start_device_login(account_id):
    """Start a sign-in by a one-time code for an account whose provider has
    one (cloud.device_login_spec). Answers what the board shows; the login
    itself runs in its own thread and ends in the account's session."""
    account = _oauth_account(account_id)
    spec = device_login_spec(account)
    if not spec:
        raise AppError("this account's provider has no sign-in by code", 400)
    login = DeviceLogin(account, spec)
    shown = login.begin()
    _end_pending(account["id"], REPLACED)
    with _oauth_lock:
        _oauth_sessions[login.state] = login.session
    threading.Thread(target=login.run, daemon=True).start()
    return shown
