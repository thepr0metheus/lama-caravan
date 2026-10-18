"""Accounts, sessions and the fleet token (SQLite, stdlib-only).

Auth is OFF until the first user exists (open homelab default). Creating the
first account (UI Security panel or `python3 -m caravan.admin.auth
create-user`) turns the guard on for every route except the login page, the
auth bootstrap endpoints and the machine endpoints, which switch to the
fleet token (scouts put it into config.json as `controllerToken`).

The DB lives next to admin.json (LLAMA_ADMIN_AUTH_DB to override), chmod 0600.
The fleet token is stored in plaintext there — the controller must SEND it to
scouts, so a hash would not do; same trust model as provider-secrets.json.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from http import cookies as http_cookies
from pathlib import Path

from caravan.admin.paths import ADMIN_STATE_FILE
from caravan.common.errors import AppError
from caravan.store.auth import AuthStore

AUTH_DB = Path(os.environ.get("LLAMA_ADMIN_AUTH_DB",
    str(ADMIN_STATE_FILE.parent / "auth.db")))

#: The database, its schema and its caches. See caravan/store/auth.py for why
#: each of the careful bits is careful; this module is the panel's vocabulary
#: over it — one function per thing an operator or a request can do.
store = AuthStore(AUTH_DB)

SESSION_COOKIE = "caravan_session"
SESSION_TTL = store.session_ttl       # 30 days
#: How much of a session's token hash the panel calls its id. The list hands
#: it out and a revoke names a session by it, so both cut it here — a revoke
#: that matched any prefix ended whichever session came first for "" or "a".
SESSION_ID_LENGTH = 12
PBKDF2_ITERS = store.iterations
#: Kept as module names because callers and tests reach for them directly: the
#: settings import clears both after replacing the database under a live process.
_LOGIN_FAILS = store.login_fails      # ip -> [fails, lock_until]
_SESSION_CACHE = store.session_cache  # token_hash -> (info, cached_until)
_ENABLED_CACHE = store.enabled_cache  # [bool, cached_until]


def _db():
    return store.connect()


def auth_enabled() -> bool:
    now = store.now()
    if _ENABLED_CACHE[0] is not None and now < _ENABLED_CACHE[1]:
        return _ENABLED_CACHE[0]
    with _db() as conn:
        enabled = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    _ENABLED_CACHE[0] = enabled
    _ENABLED_CACHE[1] = now + store.enabled_ttl
    return enabled


def _hash_password(password: str, salt: bytes, iters: int = PBKDF2_ITERS) -> bytes:
    return store.hash_password(password, salt, iters)


def create_user(username: str, password: str, role: str = "admin") -> dict:
    username = str(username or "").strip()
    role = str(role or "admin").strip().lower()
    if role not in ("admin", "viewer"):
        raise AppError("role must be admin or viewer")
    if not username or len(username) > 64:
        raise AppError("username is required (max 64 chars)")
    if len(password or "") < 8:
        raise AppError("password must be at least 8 characters")
    salt = store.new_salt()
    digest = _hash_password(password, salt)
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO users (username, salt, hash, iters, created_at, role) VALUES (?,?,?,?,?,?)",
                (username, salt, digest, PBKDF2_ITERS, int(time.time()), role))
    except sqlite3.IntegrityError:
        raise AppError(f"user {username} already exists", 409)
    store.invalidate()
    return {"username": username, "role": role}

def set_role(username: str, role: str) -> None:
    role = str(role or "").strip().lower()
    if role not in ("admin", "viewer"):
        raise AppError("role must be admin or viewer")
    with _db() as conn:
        if role == "viewer":
            admins = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND username != ?",
                (username,)).fetchone()[0]
            if admins == 0:
                raise AppError("cannot demote the last admin", 400)
        cur = conn.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        if cur.rowcount == 0:
            raise AppError(f"no such user: {username}", 404)
    store.invalidate()


def set_password(username: str, password: str) -> None:
    if len(password or "") < 8:
        raise AppError("password must be at least 8 characters")
    salt = store.new_salt()
    digest = _hash_password(password, salt)
    with _db() as conn:
        cur = conn.execute("UPDATE users SET salt=?, hash=?, iters=? WHERE username=?",
                           (salt, digest, PBKDF2_ITERS, username))
        if cur.rowcount == 0:
            raise AppError(f"no such user: {username}", 404)


def delete_user(username: str) -> None:
    with _db() as conn:
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            raise AppError(f"no such user: {username}", 404)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count <= 1:
            raise AppError("cannot delete the last user — disable auth is not supported from the UI", 400)
        conn.execute("DELETE FROM sessions WHERE user_id=?", (row[0],))
        conn.execute("DELETE FROM users WHERE id=?", (row[0],))
    store.invalidate()


def list_users() -> list:
    with _db() as conn:
        rows = conn.execute("SELECT username, created_at, role FROM users ORDER BY id").fetchall()
    return [{"username": r[0], "createdAt": r[1], "role": r[2] or "admin"} for r in rows]


def verify_login(username: str, password: str, ip: str = "") -> dict:
    now = store.now()
    if now < store.locked_until(ip):
        raise AppError("too many attempts — try again in a minute", 429)
    with _db() as conn:
        row = conn.execute(
            "SELECT id, username, salt, hash, iters FROM users WHERE username=?",
            (str(username or "").strip(),)).fetchone()  # role resolved per-session
    ok = False
    if row:
        ok = store.password_matches(password, row[2], row[3], row[4])
    else:
        store.absorb_timing(password)   # a missing user must not answer sooner
    if not ok:
        store.note_failure(ip, now)
        raise AppError("invalid username or password", 401)
    store.note_success(ip)
    return {"id": row[0], "username": row[1]}


def create_session(user_id: int, ip: str = "", ua: str = "") -> str:
    token = store.new_token()
    token_hash = store.token_hash(token)
    now = int(time.time())
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen, ip, ua) VALUES (?,?,?,?,?,?,?)",
            (token_hash, user_id, now, now + store.session_ttl, now, ip[:64], ua[:160]))
    return token


def validate_session(token: str) -> dict:
    """Return {'user': name, 'role': role} for a live session, or {} if invalid."""
    if not token:
        return {}
    token_hash = store.token_hash(token)
    now = store.now()
    cached = store.cached_session(token_hash, now)
    if cached is not None:
        return cached
    with _db() as conn:
        row = conn.execute(
            """SELECT s.last_seen, s.expires_at, u.username, u.role FROM sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token_hash=?""",
            (token_hash,)).fetchone()
        if not row or row[1] < now:
            store.forget_session(token_hash)
            return {}
        if now - row[0] > 60:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                         (int(now), token_hash))
    info = {"user": row[2], "role": row[3] or "admin"}
    store.cache_session(token_hash, info, now)
    return info


def delete_session(token: str) -> None:
    if not token:
        return
    token_hash = store.token_hash(token)
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    store.forget_session(token_hash)


def session_id(token_hash: str) -> str:
    """The id the panel lists a session under: the head of its token hash."""
    return token_hash[:SESSION_ID_LENGTH]


def list_sessions() -> list:
    now = int(time.time())
    with _db() as conn:
        rows = conn.execute(
            """SELECT s.token_hash, u.username, s.created_at, s.last_seen, s.ip, s.ua
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.expires_at >= ? ORDER BY s.last_seen DESC""", (now,)).fetchall()
    return [{"id": session_id(r[0]), "username": r[1], "createdAt": r[2],
             "lastSeen": r[3], "ip": r[4] or "", "ua": (r[5] or "")[:60]} for r in rows]


def revoke_other_sessions(current_token: str) -> int:
    """Kill every session except the caller's own; returns how many died."""
    keep = store.token_hash(current_token) if current_token else ""
    with _db() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
        killed = 0
        for (th,) in rows:
            if th == keep:
                continue
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
            store.forget_session(th)
            killed += 1
    return killed


def revoke_session(short_id: str) -> None:
    """End the one session listed under this id. An id that names none — empty,
    or only the start of one — ends nothing: the first session in the table
    would otherwise die for it, the caller's own among them."""
    short_id = str(short_id or "").strip()
    if not short_id:
        raise AppError("session id is required", 400)
    with _db() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
        for (th,) in rows:
            if session_id(th) == short_id:
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
                store.forget_session(th)
                return
    raise AppError("session not found", 404)


# ── fleet token (machine endpoints: scouts <-> controller) ──────────────────

def fleet_token_get() -> str:
    with _db() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='fleet_token'").fetchone()
    return row[0] if row else ""


def fleet_token_ensure() -> str:
    token = fleet_token_get()
    if token:
        return token
    token = store.fleet_token_value()
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fleet_token', ?)", (token,))
    return token


def fleet_token_regenerate() -> str:
    token = store.fleet_token_value()
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fleet_token', ?)", (token,))
    return token


def fleet_token_verify(candidate: str) -> bool:
    return store.tokens_match(candidate, fleet_token_get())


# ── request-side helpers (used by the dispatcher) ────────────────────────────

class SessionStoreUnavailable(Exception):
    """The accounts database did not answer: locked, a disk that stalled, an I/O error. The session is then UNKNOWN,
    which is not "nobody is signed in": the first read as the second threw the owner to the sign-in page from the
    board in the middle of a big copy to the NAS (2026-10-17, one /api/topology poll answered 401 while the same
    cookie was good a second later)."""


def session_from_handler(handler) -> dict:
    """{'user','role'} for the request's cookie session, or {} when the request has none: no cookie, a cookie that does
    not parse, a session the store does not know or has expired. A store that does not answer raises
    SessionStoreUnavailable (the dispatcher answers 503 to it, which no page takes for a sign-out)."""
    raw = handler.headers.get("Cookie") or ""
    try:
        morsel = http_cookies.SimpleCookie(raw).get(SESSION_COOKIE)
    except http_cookies.CookieError:
        return {}
    if not morsel:
        return {}
    try:
        return validate_session(morsel.value)
    except (sqlite3.Error, OSError) as exc:
        raise SessionStoreUnavailable(str(exc)) from exc


def session_cookie_header(token: str, clear: bool = False) -> str:
    if clear:
        return f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
    return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Lax"


# The two auth pages share one shell (styles, language select, script) and
# differ in the form it carries. Each form lives at its own URL — /login and
# /setup — with the server redirecting between them by auth state; see
# login_page() / setup_page().
_SIGN_IN_FORM = """<form id="loginForm" data-t="login-form">
      <label for="u" data-i18n="user">Username</label>
      <input id="u" autocomplete="username" autofocus data-t="login-username">
      <label for="p" data-i18n="pass">Password</label>
      <input id="p" type="password" autocomplete="current-password" data-t="login-password">
      <button class="primary" type="submit" data-i18n="signin" data-t="login-submit">Sign in</button>
      <!-- role="alert" because this <p> starts EMPTY and is filled by script
           after a failed sign-in. Without it a screen reader never learns the
           attempt failed — the text simply appears, silently, and the only
           feedback is that nothing happened. alert (not status) because it
           answers an action the user just took and should interrupt. It also
           gives the element a real role instead of generic, so a test can ask
           getByRole("alert") rather than for the paragraph by name. -->
      <p class="err" id="e" role="alert" data-t="login-error"></p>
    </form>"""

_FIRST_RUN_FORM = """<form id="setupForm" data-t="setup-form">
      <p class="note" data-i18n="setupNote">No account exists yet. Until you create one, this controller answers nothing but this page. There is no default admin/admin on purpose.</p>
      <label for="su" data-i18n="user">Username</label>
      <input id="su" autocomplete="username" autofocus data-t="setup-username">
      <label for="sp" data-i18n="passNew">Password (min 8 chars)</label>
      <input id="sp" type="password" autocomplete="new-password" data-t="setup-password">
      <label for="sp2" data-i18n="passRepeat">Repeat password</label>
      <input id="sp2" type="password" autocomplete="new-password" data-t="setup-password-repeat">
      <button class="primary" type="submit" data-i18n="create" data-t="setup-submit">Create account &amp; enable sign-in</button>
      <p class="err" id="se"></p>
    </form>"""

_PAGE_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LAMA CARAVAN — sign in</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: flex; align-items: center;
         justify-content: center; background: #0e1116; color: #e6e6ea;
         font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
  .card { width: 100%; max-width: 380px; background: #171a22;
          border: 1px solid #2a2e3b; border-radius: 14px; padding: 24px 28px 26px; }
  .card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
  h1 { font-size: 19px; margin: 0 0 2px; }
  .sub { color: #8b8b96; font-size: 12.5px; margin: 0 0 16px; }
  label { display: block; font-size: 12px; color: #9aa3b2; margin: 12px 0 4px;
          text-transform: uppercase; letter-spacing: .05em; }
  input, select { width: 100%; background: #0e1116; color: #e6e6ea;
          border: 1px solid #2a2e3b; border-radius: 8px; padding: 10px 12px;
          font-size: 14px; }
  select.lang { width: auto; padding: 6px 8px; font-size: 12px; }
  input:focus, select:focus { outline: none; border-color: #4a7dbd; }
  button.primary { width: 100%; margin-top: 18px; background: #2e6bb0; color: #fff;
           border: 0; border-radius: 8px; padding: 11px; font-size: 14px;
           font-weight: 600; cursor: pointer; }
  button.primary:hover { background: #3a7cc4; }
  .err { color: #ec7063; font-size: 13px; margin: 10px 0 0; min-height: 18px; }
  .note { color: #8b8b96; font-size: 12.5px; margin-top: 10px; }
  .token { display: block; background: #0e1116; border: 1px solid #2a2e3b;
           border-radius: 8px; padding: 9px 11px; margin: 8px 0; font-size: 12.5px;
           word-break: break-all; user-select: all; }
  .hidden { display: none; }
</style>
</head>
<body data-t-page="<!--PAGE-->">
  <div class="card">
    <div class="card-top">
      <div>
        <h1>&#129433; LAMA CARAVAN</h1>
        <p class="sub" data-i18n="sub">Sign in to the fleet controller</p>
      </div>
      <select class="lang" id="lang" aria-label="Language" data-i18n-aria="langLabel" data-t="login-lang"></select>
    </div>

    <!--FORM-->
  </div>
<script>
(function () {
  var LANGS = [["en","☕ English"],["zh","🐼 中文"],["hi","🪷 हिन्दी"],["es","🥘 Español"],["fr","🥐 Français"],["ar","🕌 العربية"],["bn","🐅 বাংলা"],["pt","🌊 Português"],["ru","🪆 Русский"],["ja","🌸 日本語"],["de","🍺 Deutsch"],["id","🦎 Bahasa"],["ur","🏏 اردو"],["tr","🌙 Türkçe"],["ko","🫰 한국어"],["vi","🛵 Tiếng Việt"],["it","🍝 Italiano"],["te","🌶️ తెలుగు"],["mr","🚩 मराठी"],["ta","🐘 தமிழ்"]];
  var M = {
    en:{langLabel:"Interface language",sub:"Sign in to the fleet controller",subSetup:"Create the first account",user:"Username",pass:"Password",signin:"Sign in",passNew:"Password (min 8 chars)",passRepeat:"Repeat password",create:"Create account & enable sign-in",setupNote:"No account exists yet. Until you create one, this controller answers nothing but this page. There is no default admin/admin on purpose.",mismatch:"passwords do not match",failed:"login failed",badCredentials:"Invalid username or password",tooManyAttempts:"Too many attempts — try again in a minute"},
    ru:{langLabel:"Язык интерфейса",sub:"Вход в контроллер флота",subSetup:"Создайте первую учётную запись",user:"Логин",pass:"Пароль",signin:"Войти",passNew:"Пароль (мин. 8 символов)",passRepeat:"Повторите пароль",create:"Создать аккаунт и включить вход",setupNote:"Учётных записей ещё нет. Пока вы не создадите первую, контроллер отвечает только этой страницей. Учётной записи admin/admin по умолчанию нет намеренно.",mismatch:"пароли не совпадают",failed:"вход не выполнен",badCredentials:"Неверное имя пользователя или пароль",tooManyAttempts:"Слишком много попыток — повторите через минуту"},
    zh:{langLabel:"界面语言",sub:"登录车队控制器",subSetup:"创建第一个账户",user:"用户名",pass:"密码",signin:"登录",passNew:"密码（至少 8 个字符）",passRepeat:"重复密码",create:"创建账户并启用登录",setupNote:"目前还没有任何账户。在你创建账户之前，此控制器只会返回这个页面，不响应其他任何请求。有意不设默认 admin/admin。",mismatch:"两次密码不一致",failed:"登录失败",badCredentials:"用户名或密码错误",tooManyAttempts:"尝试次数过多，请在一分钟后重试"},
    hi:{langLabel:"इंटरफ़ेस भाषा",sub:"फ़्लीट कंट्रोलर में साइन इन करें",subSetup:"पहला खाता बनाएँ",user:"उपयोगकर्ता नाम",pass:"पासवर्ड",signin:"साइन इन",passNew:"पासवर्ड (कम से कम 8 अक्षर)",passRepeat:"पासवर्ड दोहराएँ",create:"खाता बनाएँ और साइन-इन चालू करें",setupNote:"अभी कोई खाता मौजूद नहीं है। जब तक आप खाता नहीं बनाते, यह कंट्रोलर इस पेज के सिवा किसी चीज़ का जवाब नहीं देता। जानबूझकर कोई डिफ़ॉल्ट admin/admin नहीं है।",mismatch:"पासवर्ड मेल नहीं खाते",failed:"साइन-इन विफल",badCredentials:"उपयोगकर्ता नाम या पासवर्ड गलत है",tooManyAttempts:"बहुत अधिक प्रयास — एक मिनट बाद फिर से कोशिश करें"},
    es:{langLabel:"Idioma de la interfaz",sub:"Inicia sesión en el controlador de la flota",subSetup:"Crea la primera cuenta",user:"Usuario",pass:"Contraseña",signin:"Entrar",passNew:"Contraseña (mín. 8 caracteres)",passRepeat:"Repite la contraseña",create:"Crear cuenta y activar el acceso",setupNote:"Aún no existe ninguna cuenta. Hasta que crees una, este controlador solo responde con esta página. No existe admin/admin por defecto, a propósito.",mismatch:"las contraseñas no coinciden",failed:"no se pudo iniciar sesión",badCredentials:"Usuario o contraseña incorrectos",tooManyAttempts:"Demasiados intentos: vuelve a intentarlo en un minuto"},
    fr:{langLabel:"Langue de l'interface",sub:"Connexion au contrôleur de flotte",subSetup:"Créez le premier compte",user:"Identifiant",pass:"Mot de passe",signin:"Se connecter",passNew:"Mot de passe (min. 8 caractères)",passRepeat:"Répétez le mot de passe",create:"Créer le compte et activer la connexion",setupNote:"Aucun compte n'existe encore. Tant que vous n'en avez pas créé un, ce contrôleur ne répond qu'avec cette page. Pas d'admin/admin par défaut, volontairement.",mismatch:"les mots de passe ne correspondent pas",failed:"échec de connexion",badCredentials:"Nom d'utilisateur ou mot de passe incorrect",tooManyAttempts:"Trop de tentatives — réessayez dans une minute"},
    ar:{langLabel:"لغة الواجهة",sub:"تسجيل الدخول إلى وحدة التحكم بالأسطول",subSetup:"إنشاء الحساب الأول",user:"اسم المستخدم",pass:"كلمة المرور",signin:"تسجيل الدخول",passNew:"كلمة المرور (8 أحرف على الأقل)",passRepeat:"أعد كلمة المرور",create:"إنشاء حساب وتفعيل الدخول",setupNote:"لا يوجد أي حساب بعد. إلى أن تنشئ حساباً، لا تردّ وحدة التحكم هذه إلا بهذه الصفحة. لا يوجد admin/admin افتراضي عمداً.",mismatch:"كلمتا المرور غير متطابقتين",failed:"فشل تسجيل الدخول",badCredentials:"اسم المستخدم أو كلمة المرور غير صحيحة",tooManyAttempts:"محاولات كثيرة جدًا — حاول مرة أخرى بعد دقيقة"},
    bn:{langLabel:"ইন্টারফেসের ভাষা",sub:"ফ্লিট কন্ট্রোলারে সাইন ইন করুন",subSetup:"প্রথম অ্যাকাউন্ট তৈরি করুন",user:"ব্যবহারকারীর নাম",pass:"পাসওয়ার্ড",signin:"সাইন ইন",passNew:"পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর)",passRepeat:"পাসওয়ার্ড আবার লিখুন",create:"অ্যাকাউন্ট তৈরি করুন ও সাইন-ইন চালু করুন",setupNote:"এখনও কোনো অ্যাকাউন্ট নেই। আপনি একটি অ্যাকাউন্ট তৈরি না করা পর্যন্ত এই কন্ট্রোলার এই পেজ ছাড়া আর কিছুর উত্তর দেয় না। ইচ্ছাকৃতভাবে কোনো ডিফল্ট admin/admin নেই।",mismatch:"পাসওয়ার্ড মেলে না",failed:"সাইন-ইন ব্যর্থ",badCredentials:"ব্যবহারকারীর নাম বা পাসওয়ার্ড সঠিক নয়",tooManyAttempts:"অনেকবার চেষ্টা করা হয়েছে — এক মিনিট পরে আবার চেষ্টা করুন"},
    pt:{langLabel:"Idioma da interface",sub:"Entre no controlador da frota",subSetup:"Crie a primeira conta",user:"Usuário",pass:"Senha",signin:"Entrar",passNew:"Senha (mín. 8 caracteres)",passRepeat:"Repita a senha",create:"Criar conta e ativar o login",setupNote:"Ainda não existe nenhuma conta. Até que você crie uma, este controlador responde apenas com esta página. Não há admin/admin padrão, de propósito.",mismatch:"as senhas não coincidem",failed:"falha no login",badCredentials:"Usuário ou senha inválidos",tooManyAttempts:"Muitas tentativas — tente novamente em um minuto"},
    ja:{langLabel:"表示言語",sub:"フリートコントローラーにサインイン",subSetup:"最初のアカウントを作成",user:"ユーザー名",pass:"パスワード",signin:"サインイン",passNew:"パスワード（8文字以上）",passRepeat:"パスワードを再入力",create:"アカウント作成してサインインを有効化",setupNote:"アカウントはまだ存在しません。アカウントを作成するまで、このコントローラーはこのページ以外には何も応答しません。既定の admin/admin は意図的にありません。",mismatch:"パスワードが一致しません",failed:"サインイン失敗",badCredentials:"ユーザー名またはパスワードが正しくありません",tooManyAttempts:"試行回数が多すぎます。1分後にもう一度お試しください"},
    de:{langLabel:"Anzeigesprache",sub:"Anmeldung am Flotten-Controller",subSetup:"Erstes Konto erstellen",user:"Benutzername",pass:"Passwort",signin:"Anmelden",passNew:"Passwort (mind. 8 Zeichen)",passRepeat:"Passwort wiederholen",create:"Konto erstellen & Anmeldung aktivieren",setupNote:"Es gibt noch kein Konto. Solange noch keines erstellt wurde, antwortet dieser Controller nur mit dieser Seite. Ein Standard-admin/admin gibt es absichtlich nicht.",mismatch:"Passwörter stimmen nicht überein",failed:"Anmeldung fehlgeschlagen",badCredentials:"Benutzername oder Passwort ist falsch",tooManyAttempts:"Zu viele Versuche – bitte in einer Minute erneut versuchen"},
    id:{langLabel:"Bahasa antarmuka",sub:"Masuk ke pengontrol armada",subSetup:"Buat akun pertama",user:"Nama pengguna",pass:"Kata sandi",signin:"Masuk",passNew:"Kata sandi (min. 8 karakter)",passRepeat:"Ulangi kata sandi",create:"Buat akun & aktifkan masuk",setupNote:"Belum ada akun. Sampai Anda membuat akun, pengontrol ini tidak menjawab apa pun selain halaman ini. Sengaja tidak ada admin/admin bawaan.",mismatch:"kata sandi tidak cocok",failed:"gagal masuk",badCredentials:"Nama pengguna atau kata sandi salah",tooManyAttempts:"Terlalu banyak percobaan — coba lagi dalam satu menit"},
    ur:{langLabel:"انٹرفیس کی زبان",sub:"فلیٹ کنٹرولر میں سائن ان کریں",subSetup:"پہلا اکاؤنٹ بنائیں",user:"صارف نام",pass:"پاس ورڈ",signin:"سائن ان",passNew:"پاس ورڈ (کم از کم 8 حروف)",passRepeat:"پاس ورڈ دہرائیں",create:"اکاؤنٹ بنائیں اور سائن ان فعال کریں",setupNote:"ابھی کوئی اکاؤنٹ موجود نہیں ہے۔ جب تک آپ اکاؤنٹ نہیں بنا لیتے، یہ کنٹرولر اس صفحے کے سوا کسی چیز کا جواب نہیں دیتا۔ جان بوجھ کر کوئی ڈیفالٹ admin/admin نہیں ہے۔",mismatch:"پاس ورڈ مماثل نہیں",failed:"سائن ان ناکام",badCredentials:"صارف نام یا پاس ورڈ غلط ہے",tooManyAttempts:"بہت زیادہ کوششیں — ایک منٹ بعد دوبارہ کوشش کریں"},
    tr:{langLabel:"Arayüz dili",sub:"Filo denetleyicisine giriş yapın",subSetup:"İlk hesabı oluşturun",user:"Kullanıcı adı",pass:"Parola",signin:"Giriş yap",passNew:"Parola (en az 8 karakter)",passRepeat:"Parolayı tekrarla",create:"Hesap oluştur ve girişi etkinleştir",setupNote:"Henüz hiç hesap yok. Bir hesap oluşturana kadar bu denetleyici bu sayfa dışında hiçbir şeye yanıt vermez. Varsayılan admin/admin bilerek yok.",mismatch:"parolalar eşleşmiyor",failed:"giriş başarısız",badCredentials:"Kullanıcı adı veya parola hatalı",tooManyAttempts:"Çok fazla deneme — bir dakika sonra tekrar deneyin"},
    ko:{langLabel:"인터페이스 언어",sub:"플릿 컨트롤러에 로그인",subSetup:"첫 계정 만들기",user:"사용자 이름",pass:"비밀번호",signin:"로그인",passNew:"비밀번호(8자 이상)",passRepeat:"비밀번호 재입력",create:"계정 만들고 로그인 활성화",setupNote:"아직 계정이 없습니다. 계정을 만들기 전까지 이 컨트롤러는 이 페이지 외에는 아무것도 응답하지 않습니다. 기본 admin/admin은 의도적으로 없습니다.",mismatch:"비밀번호가 일치하지 않습니다",failed:"로그인 실패",badCredentials:"아이디 또는 비밀번호가 올바르지 않습니다",tooManyAttempts:"시도 횟수가 너무 많습니다 — 1분 후에 다시 시도해 주세요"},
    vi:{langLabel:"Ngôn ngữ giao diện",sub:"Đăng nhập bộ điều khiển đội máy",subSetup:"Tạo tài khoản đầu tiên",user:"Tên đăng nhập",pass:"Mật khẩu",signin:"Đăng nhập",passNew:"Mật khẩu (tối thiểu 8 ký tự)",passRepeat:"Nhập lại mật khẩu",create:"Tạo tài khoản & bật đăng nhập",setupNote:"Chưa có tài khoản nào. Cho đến khi bạn tạo tài khoản, bộ điều khiển này không phản hồi gì ngoài trang này. Cố ý không có admin/admin mặc định.",mismatch:"mật khẩu không khớp",failed:"đăng nhập thất bại",badCredentials:"Tên đăng nhập hoặc mật khẩu không đúng",tooManyAttempts:"Quá nhiều lần thử — vui lòng thử lại sau một phút"},
    it:{langLabel:"Lingua dell'interfaccia",sub:"Accedi al controller della flotta",subSetup:"Crea il primo account",user:"Nome utente",pass:"Password",signin:"Accedi",passNew:"Password (min. 8 caratteri)",passRepeat:"Ripeti la password",create:"Crea account e attiva l'accesso",setupNote:"Non esiste ancora alcun account. Finché non ne crei uno, questo controller risponde solo con questa pagina. Nessun admin/admin predefinito, di proposito.",mismatch:"le password non coincidono",failed:"accesso non riuscito",badCredentials:"Nome utente o password non validi",tooManyAttempts:"Troppi tentativi — riprova tra un minuto"},
    te:{langLabel:"ఇంటర్‌ఫేస్ భాష",sub:"ఫ్లీట్ కంట్రోలర్‌లో సైన్ ఇన్ అవ్వండి",subSetup:"మొదటి ఖాతాను సృష్టించండి",user:"వాడుకరి పేరు",pass:"పాస్‌వర్డ్",signin:"సైన్ ఇన్",passNew:"పాస్‌వర్డ్ (కనీసం 8 అక్షరాలు)",passRepeat:"పాస్‌వర్డ్ మళ్లీ ఇవ్వండి",create:"ఖాతా సృష్టించి సైన్-ఇన్ ప్రారంభించండి",setupNote:"ఇంకా ఏ ఖాతా లేదు. మీరు ఒక ఖాతా సృష్టించే వరకు, ఈ కంట్రోలర్ ఈ పేజీ తప్ప మరేదానికీ స్పందించదు. డిఫాల్ట్ admin/admin ఉద్దేశపూర్వకంగా లేదు.",mismatch:"పాస్‌వర్డ్‌లు సరిపోలడం లేదు",failed:"సైన్ ఇన్ విఫలమైంది",badCredentials:"వినియోగదారు పేరు లేదా పాస్‌వర్డ్ సరైనది కాదు",tooManyAttempts:"చాలా ఎక్కువ ప్రయత్నాలు — ఒక నిమిషం తర్వాత మళ్లీ ప్రయత్నించండి"},
    mr:{langLabel:"इंटरफेस भाषा",sub:"फ्लीट कंट्रोलरमध्ये साइन इन करा",subSetup:"पहिले खाते तयार करा",user:"वापरकर्तानाव",pass:"पासवर्ड",signin:"साइन इन",passNew:"पासवर्ड (किमान 8 अक्षरे)",passRepeat:"पासवर्ड पुन्हा लिहा",create:"खाते तयार करा आणि साइन-इन सुरू करा",setupNote:"अजून कोणतेही खाते नाही. तुम्ही खाते तयार करेपर्यंत हा कंट्रोलर या पानाशिवाय इतर कशालाही उत्तर देत नाही. मुद्दाम कोणतेही डीफॉल्ट admin/admin नाही.",mismatch:"पासवर्ड जुळत नाहीत",failed:"साइन इन अयशस्वी",badCredentials:"वापरकर्तानाव किंवा पासवर्ड चुकीचा आहे",tooManyAttempts:"खूप जास्त प्रयत्न — एका मिनिटानंतर पुन्हा प्रयत्न करा"},
    ta:{langLabel:"இடைமுக மொழி",sub:"ஃபிளீட் கண்ட்ரோலரில் உள்நுழையவும்",subSetup:"முதல் கணக்கை உருவாக்கவும்",user:"பயனர்பெயர்",pass:"கடவுச்சொல்",signin:"உள்நுழை",passNew:"கடவுச்சொல் (குறைந்தது 8 எழுத்துகள்)",passRepeat:"கடவுச்சொல்லை மீண்டும் உள்ளிடவும்",create:"கணக்கை உருவாக்கி உள்நுழைவை இயக்கு",setupNote:"இன்னும் எந்தக் கணக்கும் இல்லை. நீங்கள் ஒரு கணக்கை உருவாக்கும் வரை, இந்தக் கண்ட்ரோலர் இந்தப் பக்கத்தைத் தவிர வேறு எதற்கும் பதிலளிக்காது. இயல்புநிலை admin/admin வேண்டுமென்றே இல்லை.",mismatch:"கடவுச்சொற்கள் பொருந்தவில்லை",failed:"உள்நுழைவு தோல்வி",badCredentials:"பயனர்பெயர் அல்லது கடவுச்சொல் தவறானது",tooManyAttempts:"அதிகமான முயற்சிகள் — ஒரு நிமிடம் கழித்து மீண்டும் முயற்சிக்கவும்"}
  };
  var sel = document.getElementById("lang");
  LANGS.forEach(function (l) {
    var o = document.createElement("option");
    o.value = l[0]; o.textContent = l[1];
    sel.appendChild(o);
  });
  var lang = localStorage.getItem("llamacppAdminLang") || "en";
  if (!M[lang]) lang = "en";
  sel.value = lang;
  function T(k) { return (M[lang] && M[lang][k]) || M.en[k] || k; }
  function apply() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = T(el.dataset.i18n); });
    // An aria-label is the element's NAME for a screen reader, and it was the
    // one string on this page that stayed English while the other twelve
    // translated — so a Russian page announced its language selector as
    // "Language". textContent cannot carry it: the <select> holds <option>s.
    document.querySelectorAll("[data-i18n-aria]").forEach(function (el) { el.setAttribute("aria-label", T(el.dataset.i18nAria)); });
    document.documentElement.dir = (lang === "ar" || lang === "ur") ? "rtl" : "ltr";
  }
  sel.addEventListener("change", function () {
    lang = sel.value;
    localStorage.setItem("llamacppAdminLang", lang);
    apply();
  });
  apply();

  // Which form this page carries is decided by the server, so exactly one of
  // the two handlers below has something to bind to. Both are guarded.
  var loginForm = document.getElementById("loginForm");
  if (loginForm) loginForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var e = document.getElementById("e");
    e.textContent = "";
    fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: document.getElementById("u").value.trim(),
                             password: document.getElementById("p").value })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j, status: r.status }; }); })
      .then(function (res) {
        if (res.ok && res.j.ok) { window.location = "/board"; return; }
        // Translate by STATUS, not by echoing the server's sentence. The
        // endpoint answers in English only, so printing res.j.error meant a
        // page running in Russian told you "invalid username or password" —
        // the one string on this page that never followed the language.
        // The server text is still the fallback for anything unforeseen: a
        // sentence in the wrong language beats no explanation at all.
        e.textContent = res.status === 401 ? T("badCredentials")
                      : res.status === 429 ? T("tooManyAttempts")
                      : (res.j.error || T("failed"));
      }).catch(function (err) { e.textContent = String(err); });
  });

  var setupForm = document.getElementById("setupForm");
  if (setupForm) setupForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var se = document.getElementById("se");
    se.textContent = "";
    var p1 = document.getElementById("sp").value, p2 = document.getElementById("sp2").value;
    if (p1 !== p2) { se.textContent = T("mismatch"); return; }
    fetch("/api/auth/setup", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: document.getElementById("su").value.trim(), password: p1 })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        // Straight to the board: the account is made and its session set. The
        // fleet token is the scouts' business — adding a scout from the board
        // hands it over — so it waits in System → Security, not on this page.
        if (res.ok && res.j.ok) { window.location = "/board"; }
        else { se.textContent = res.j.error || T("failed"); }
      }).catch(function (err) { se.textContent = String(err); });
  });
})();
</script>
</body>
</html>
"""


def login_page() -> str:
    """/login — the sign-in form, and nothing else.

    History, because this page has been reshaped twice for the same reason.
    It originally shipped BOTH forms with the wrong one display:none and a
    fetch of /api/auth/me deciding client-side — which made every name-based
    lookup ambiguous (getByLabel("Username") matched two fields) and sent the
    first-run wizard to everyone forever. Then the server chose one form per
    request on a single URL. Now each form has its own URL, with the routes
    redirecting by auth state: /login when accounts exist, /setup until then.
    The URL itself says which mode the controller is in, and neither document
    ever contains a control that cannot be used on it.

    (Role locators were never ambiguous at any point — display:none excludes
    an element from the accessibility tree. The name-based ones were.)
    """
    return (_PAGE_SHELL.replace("<!--FORM-->", _SIGN_IN_FORM)
            .replace("<!--PAGE-->", "login"))


def setup_page() -> str:
    """/setup — the first-run page: one account, then the board.

    Deliberately NOT called /signup: nobody self-registers here. The form
    works exactly once, on a controller with no accounts; every later account
    is created by an admin from the Security panel. It used to show the fleet
    token after the account, "copy it now" — a step from before scouts were
    added from the board, which hands them the token itself; a first user
    without scouts did not know what to make of it (2026-10-07). The token
    stays in System → Security, beside what it is for.

    The shared page script guards both forms' handlers, so each page simply
    has nothing to bind for the form it does not carry.
    """
    return (_PAGE_SHELL.replace("<!--FORM-->", _FIRST_RUN_FORM)
            .replace("<!--PAGE-->", "setup")
            .replace('<p class="sub" data-i18n="sub">Sign in to the fleet controller</p>',
                     '<p class="sub" data-i18n="subSetup">Create the first account</p>')
            .replace("<title>LAMA CARAVAN — sign in</title>",
                     "<title>LAMA CARAVAN — first run</title>"))


def main(argv=None):
    """CLI for prod ops: create-user / set-password / list / fleet-token."""
    import argparse
    import getpass
    parser = argparse.ArgumentParser(prog="python3 -m caravan.admin.auth")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_create = sub.add_parser("create-user"); p_create.add_argument("username")
    p_create.add_argument("--role", choices=["admin", "viewer"], default="admin")
    p_pass = sub.add_parser("set-password"); p_pass.add_argument("username")
    sub.add_parser("list")
    sub.add_parser("fleet-token")
    args = parser.parse_args(argv)
    if args.cmd == "create-user":
        password = getpass.getpass("Password (min 8 chars): ")
        create_user(args.username, password, role=args.role)
        print(f"user {args.username} ({args.role}) created; auth is now ON")
        print(f"fleet token (put into each scout's config as controllerToken): {fleet_token_ensure()}")
    elif args.cmd == "set-password":
        set_password(args.username, getpass.getpass("New password: "))
        print("password updated")
    elif args.cmd == "list":
        for u in list_users():
            print(u["username"], "·", u["role"])
        print(f"auth enabled: {auth_enabled()}")
    elif args.cmd == "fleet-token":
        print(fleet_token_ensure())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
