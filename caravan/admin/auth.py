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

AUTH_DB = Path(os.environ.get("LLAMA_ADMIN_AUTH_DB",
    str(ADMIN_STATE_FILE.parent / "auth.db")))

SESSION_COOKIE = "caravan_session"
SESSION_TTL = 30 * 24 * 3600          # 30 days
PBKDF2_ITERS = 200_000
_LOGIN_FAILS: dict = {}               # ip -> [fails, lock_until]
_SESSION_CACHE: dict = {}             # token_hash -> (username, cached_until)
_ENABLED_CACHE = [None, 0.0]          # [bool, cached_until]


def _db():
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    fresh = not AUTH_DB.exists()
    conn = sqlite3.connect(str(AUTH_DB), timeout=5)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
        salt BLOB NOT NULL, hash BLOB NOT NULL, iters INTEGER NOT NULL,
        created_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        last_seen INTEGER NOT NULL, ip TEXT, ua TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "role" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
    if fresh:
        try:
            os.chmod(AUTH_DB, 0o600)
        except OSError:
            pass
    return conn


def auth_enabled() -> bool:
    now = time.time()
    if _ENABLED_CACHE[0] is not None and now < _ENABLED_CACHE[1]:
        return _ENABLED_CACHE[0]
    with _db() as conn:
        enabled = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    _ENABLED_CACHE[0] = enabled
    _ENABLED_CACHE[1] = now + 3
    return enabled


def _hash_password(password: str, salt: bytes, iters: int = PBKDF2_ITERS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)


def create_user(username: str, password: str, role: str = "admin") -> dict:
    username = str(username or "").strip()
    role = str(role or "admin").strip().lower()
    if role not in ("admin", "viewer"):
        raise AppError("role must be admin or viewer")
    if not username or len(username) > 64:
        raise AppError("username is required (max 64 chars)")
    if len(password or "") < 8:
        raise AppError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = _hash_password(password, salt)
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO users (username, salt, hash, iters, created_at, role) VALUES (?,?,?,?,?,?)",
                (username, salt, digest, PBKDF2_ITERS, int(time.time()), role))
    except sqlite3.IntegrityError:
        raise AppError(f"user {username} already exists", 409)
    _ENABLED_CACHE[0] = None
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
    _SESSION_CACHE.clear()


def set_password(username: str, password: str) -> None:
    if len(password or "") < 8:
        raise AppError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
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
    _ENABLED_CACHE[0] = None
    _SESSION_CACHE.clear()


def list_users() -> list:
    with _db() as conn:
        rows = conn.execute("SELECT username, created_at, role FROM users ORDER BY id").fetchall()
    return [{"username": r[0], "createdAt": r[1], "role": r[2] or "admin"} for r in rows]


def verify_login(username: str, password: str, ip: str = "") -> dict:
    now = time.time()
    fails = _LOGIN_FAILS.get(ip or "?", [0, 0])
    if now < fails[1]:
        raise AppError("too many attempts — try again in a minute", 429)
    with _db() as conn:
        row = conn.execute(
            "SELECT id, username, salt, hash, iters FROM users WHERE username=?",
            (str(username or "").strip(),)).fetchone()  # role resolved per-session
    ok = False
    if row:
        ok = hmac.compare_digest(_hash_password(password or "", row[2], row[4]), row[3])
    else:
        _hash_password(password or "", b"caravan-timing-pad")  # constant-ish time
    if not ok:
        fails[0] += 1
        if fails[0] >= 5:
            fails[:] = [0, now + 60]
        _LOGIN_FAILS[ip or "?"] = fails
        raise AppError("invalid username or password", 401)
    _LOGIN_FAILS.pop(ip or "?", None)
    return {"id": row[0], "username": row[1]}


def create_session(user_id: int, ip: str = "", ua: str = "") -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen, ip, ua) VALUES (?,?,?,?,?,?,?)",
            (token_hash, user_id, now, now + SESSION_TTL, now, ip[:64], ua[:160]))
    return token


def validate_session(token: str) -> dict:
    """Return {'user': name, 'role': role} for a live session, or {} if invalid."""
    if not token:
        return {}
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    cached = _SESSION_CACHE.get(token_hash)
    if cached and now < cached[1]:
        return cached[0]
    with _db() as conn:
        row = conn.execute(
            """SELECT s.last_seen, s.expires_at, u.username, u.role FROM sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token_hash=?""",
            (token_hash,)).fetchone()
        if not row or row[1] < now:
            _SESSION_CACHE.pop(token_hash, None)
            return {}
        if now - row[0] > 60:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                         (int(now), token_hash))
    info = {"user": row[2], "role": row[3] or "admin"}
    _SESSION_CACHE[token_hash] = (info, now + 5)
    return info


def delete_session(token: str) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    _SESSION_CACHE.pop(token_hash, None)


def list_sessions() -> list:
    now = int(time.time())
    with _db() as conn:
        rows = conn.execute(
            """SELECT s.token_hash, u.username, s.created_at, s.last_seen, s.ip, s.ua
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.expires_at >= ? ORDER BY s.last_seen DESC""", (now,)).fetchall()
    return [{"id": r[0][:12], "username": r[1], "createdAt": r[2],
             "lastSeen": r[3], "ip": r[4] or "", "ua": (r[5] or "")[:60]} for r in rows]


def revoke_other_sessions(current_token: str) -> int:
    """Kill every session except the caller's own; returns how many died."""
    keep = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
    with _db() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
        killed = 0
        for (th,) in rows:
            if th == keep:
                continue
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
            _SESSION_CACHE.pop(th, None)
            killed += 1
    return killed


def revoke_session(short_id: str) -> None:
    with _db() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
        for (th,) in rows:
            if th.startswith(short_id):
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
                _SESSION_CACHE.pop(th, None)
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
    token = "caravan-" + secrets.token_urlsafe(24)
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fleet_token', ?)", (token,))
    return token


def fleet_token_regenerate() -> str:
    token = "caravan-" + secrets.token_urlsafe(24)
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fleet_token', ?)", (token,))
    return token


def fleet_token_verify(candidate: str) -> bool:
    token = fleet_token_get()
    return bool(token) and hmac.compare_digest(str(candidate or ""), token)


# ── request-side helpers (used by the dispatcher) ────────────────────────────

def session_from_handler(handler) -> dict:
    """{'user','role'} for the request's cookie session, or {}."""
    raw = handler.headers.get("Cookie") or ""
    try:
        jar = http_cookies.SimpleCookie(raw)
        morsel = jar.get(SESSION_COOKIE)
        return validate_session(morsel.value) if morsel else {}
    except Exception:
        return {}


def session_cookie_header(token: str, clear: bool = False) -> str:
    if clear:
        return f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
    return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Lax"


LOGIN_PAGE = """<!doctype html>
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
<body>
  <div class="card">
    <div class="card-top">
      <div>
        <h1>&#129433; LAMA CARAVAN</h1>
        <p class="sub" data-t="sub">Sign in to the fleet controller</p>
      </div>
      <select class="lang" id="lang" aria-label="Language"></select>
    </div>

    <form id="loginForm">
      <label for="u" data-t="user">Username</label>
      <input id="u" autocomplete="username" autofocus>
      <label for="p" data-t="pass">Password</label>
      <input id="p" type="password" autocomplete="current-password">
      <button class="primary" type="submit" data-t="signin">Sign in</button>
      <p class="err" id="e"></p>
    </form>

    <form id="setupForm" class="hidden">
      <p class="note" data-t="setupNote">Sign-in is not enabled yet — this open page becomes protected once you create the first account. No default admin/admin exists on purpose.</p>
      <label for="su" data-t="user">Username</label>
      <input id="su" autocomplete="username">
      <label for="sp" data-t="passNew">Password (min 8 chars)</label>
      <input id="sp" type="password" autocomplete="new-password">
      <label for="sp2" data-t="passRepeat">Repeat password</label>
      <input id="sp2" type="password" autocomplete="new-password">
      <button class="primary" type="submit" data-t="create">Create account &amp; enable sign-in</button>
      <p class="err" id="se"></p>
    </form>

    <div id="tokenBox" class="hidden">
      <p class="note" data-t="tokenIntro">Fleet token — copy it now and add to every caravan-scout (pairing page or controllerToken in config.json):</p>
      <code class="token" id="tokenVal"></code>
      <button class="primary" id="goBoard" data-t="goBoard">Open the board</button>
    </div>
  </div>
<script>
(function () {
  var LANGS = [["en","☕ English"],["zh","🐼 中文"],["hi","🪷 हिन्दी"],["es","🥘 Español"],["fr","🥐 Français"],["ar","🕌 العربية"],["bn","🐅 বাংলা"],["pt","🌊 Português"],["ru","🪆 Русский"],["ja","🌸 日本語"],["de","🍺 Deutsch"],["id","🦎 Bahasa"],["ur","🏏 اردو"],["tr","🌙 Türkçe"],["ko","🫰 한국어"],["vi","🛵 Tiếng Việt"],["it","🍝 Italiano"],["te","🌶️ తెలుగు"],["mr","🚩 मराठी"],["ta","🐘 தமிழ்"]];
  var M = {
    en:{sub:"Sign in to the fleet controller",user:"Username",pass:"Password",signin:"Sign in",passNew:"Password (min 8 chars)",passRepeat:"Repeat password",create:"Create account & enable sign-in",setupNote:"Sign-in is not enabled yet — this open page becomes protected once you create the first account. No default admin/admin exists on purpose.",tokenIntro:"Fleet token — copy it now and add to every caravan-scout (pairing page or controllerToken in config.json):",goBoard:"Open the board",mismatch:"passwords do not match",failed:"login failed"},
    ru:{sub:"Вход в контроллер флота",user:"Логин",pass:"Пароль",signin:"Войти",passNew:"Пароль (мин. 8 символов)",passRepeat:"Повторите пароль",create:"Создать аккаунт и включить вход",setupNote:"Вход ещё не включён — эта открытая страница станет защищённой после создания первого аккаунта. Дефолтного admin/admin нет намеренно.",tokenIntro:"Fleet-токен — скопируйте сейчас и добавьте на каждый caravan-scout (страница сопряжения или controllerToken в config.json):",goBoard:"Открыть доску",mismatch:"пароли не совпадают",failed:"вход не выполнен"},
    zh:{sub:"登录车队控制器",user:"用户名",pass:"密码",signin:"登录",passNew:"密码（至少 8 个字符）",passRepeat:"重复密码",create:"创建账户并启用登录",setupNote:"登录尚未启用——创建第一个账户后此页面将受保护。有意不设默认 admin/admin。",tokenIntro:"Fleet 令牌——请立即复制并添加到每个 caravan-scout（配对页面或 config.json 的 controllerToken）：",goBoard:"打开看板",mismatch:"两次密码不一致",failed:"登录失败"},
    hi:{sub:"फ़्लीट कंट्रोलर में साइन इन करें",user:"उपयोगकर्ता नाम",pass:"पासवर्ड",signin:"साइन इन",passNew:"पासवर्ड (कम से कम 8 अक्षर)",passRepeat:"पासवर्ड दोहराएँ",create:"खाता बनाएँ और साइन-इन चालू करें",setupNote:"साइन-इन अभी चालू नहीं है — पहला खाता बनते ही यह पेज सुरक्षित हो जाएगा। जानबूझकर कोई डिफ़ॉल्ट admin/admin नहीं है।",tokenIntro:"Fleet टोकन — अभी कॉपी करें और हर caravan-scout में जोड़ें:",goBoard:"बोर्ड खोलें",mismatch:"पासवर्ड मेल नहीं खाते",failed:"साइन-इन विफल"},
    es:{sub:"Inicia sesión en el controlador de la flota",user:"Usuario",pass:"Contraseña",signin:"Entrar",passNew:"Contraseña (mín. 8 caracteres)",passRepeat:"Repite la contraseña",create:"Crear cuenta y activar el acceso",setupNote:"El acceso aún no está activado: esta página se protegerá al crear la primera cuenta. No existe admin/admin por defecto, a propósito.",tokenIntro:"Token de flota: cópialo ahora y añádelo a cada caravan-scout:",goBoard:"Abrir el tablero",mismatch:"las contraseñas no coinciden",failed:"no se pudo iniciar sesión"},
    fr:{sub:"Connexion au contrôleur de flotte",user:"Identifiant",pass:"Mot de passe",signin:"Se connecter",passNew:"Mot de passe (min. 8 caractères)",passRepeat:"Répétez le mot de passe",create:"Créer le compte et activer la connexion",setupNote:"La connexion n'est pas encore activée — cette page sera protégée dès le premier compte créé. Pas d'admin/admin par défaut, volontairement.",tokenIntro:"Jeton de flotte — copiez-le maintenant et ajoutez-le à chaque caravan-scout :",goBoard:"Ouvrir le tableau",mismatch:"les mots de passe ne correspondent pas",failed:"échec de connexion"},
    ar:{sub:"تسجيل الدخول إلى وحدة التحكم بالأسطول",user:"اسم المستخدم",pass:"كلمة المرور",signin:"تسجيل الدخول",passNew:"كلمة المرور (8 أحرف على الأقل)",passRepeat:"أعد كلمة المرور",create:"إنشاء حساب وتفعيل الدخول",setupNote:"الدخول غير مفعّل بعد — تصبح هذه الصفحة محمية بعد إنشاء أول حساب. لا يوجد admin/admin افتراضي عمداً.",tokenIntro:"رمز الأسطول — انسخه الآن وأضفه إلى كل caravan-scout:",goBoard:"فتح اللوحة",mismatch:"كلمتا المرور غير متطابقتين",failed:"فشل تسجيل الدخول"},
    bn:{sub:"ফ্লিট কন্ট্রোলারে সাইন ইন করুন",user:"ব্যবহারকারীর নাম",pass:"পাসওয়ার্ড",signin:"সাইন ইন",passNew:"পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর)",passRepeat:"পাসওয়ার্ড আবার লিখুন",create:"অ্যাকাউন্ট তৈরি করুন ও সাইন-ইন চালু করুন",setupNote:"সাইন-ইন এখনও চালু নয় — প্রথম অ্যাকাউন্ট তৈরি হলে পেজটি সুরক্ষিত হবে। ইচ্ছাকৃতভাবে কোনো ডিফল্ট admin/admin নেই।",tokenIntro:"Fleet টোকেন — এখনই কপি করে প্রতিটি caravan-scout-এ যোগ করুন:",goBoard:"বোর্ড খুলুন",mismatch:"পাসওয়ার্ড মেলে না",failed:"সাইন-ইন ব্যর্থ"},
    pt:{sub:"Entre no controlador da frota",user:"Usuário",pass:"Senha",signin:"Entrar",passNew:"Senha (mín. 8 caracteres)",passRepeat:"Repita a senha",create:"Criar conta e ativar o login",setupNote:"O login ainda não está ativado — esta página fica protegida ao criar a primeira conta. Não há admin/admin padrão, de propósito.",tokenIntro:"Token da frota — copie agora e adicione a cada caravan-scout:",goBoard:"Abrir o painel",mismatch:"as senhas não coincidem",failed:"falha no login"},
    ja:{sub:"フリートコントローラーにサインイン",user:"ユーザー名",pass:"パスワード",signin:"サインイン",passNew:"パスワード（8文字以上）",passRepeat:"パスワードを再入力",create:"アカウント作成してサインインを有効化",setupNote:"サインインはまだ無効です。最初のアカウントを作成するとこのページは保護されます。既定の admin/admin は意図的にありません。",tokenIntro:"フリートトークン — 今すぐコピーして各 caravan-scout に追加してください：",goBoard:"ボードを開く",mismatch:"パスワードが一致しません",failed:"サインイン失敗"},
    de:{sub:"Anmeldung am Flotten-Controller",user:"Benutzername",pass:"Passwort",signin:"Anmelden",passNew:"Passwort (mind. 8 Zeichen)",passRepeat:"Passwort wiederholen",create:"Konto erstellen & Anmeldung aktivieren",setupNote:"Die Anmeldung ist noch nicht aktiv — mit dem ersten Konto wird diese Seite geschützt. Ein Standard-admin/admin gibt es absichtlich nicht.",tokenIntro:"Fleet-Token — jetzt kopieren und jedem caravan-scout hinzufügen:",goBoard:"Board öffnen",mismatch:"Passwörter stimmen nicht überein",failed:"Anmeldung fehlgeschlagen"},
    id:{sub:"Masuk ke pengontrol armada",user:"Nama pengguna",pass:"Kata sandi",signin:"Masuk",passNew:"Kata sandi (min. 8 karakter)",passRepeat:"Ulangi kata sandi",create:"Buat akun & aktifkan masuk",setupNote:"Masuk belum diaktifkan — halaman ini terlindungi setelah akun pertama dibuat. Sengaja tidak ada admin/admin bawaan.",tokenIntro:"Token armada — salin sekarang dan tambahkan ke setiap caravan-scout:",goBoard:"Buka papan",mismatch:"kata sandi tidak cocok",failed:"gagal masuk"},
    ur:{sub:"فلیٹ کنٹرولر میں سائن ان کریں",user:"صارف نام",pass:"پاس ورڈ",signin:"سائن ان",passNew:"پاس ورڈ (کم از کم 8 حروف)",passRepeat:"پاس ورڈ دہرائیں",create:"اکاؤنٹ بنائیں اور سائن ان فعال کریں",setupNote:"سائن ان ابھی فعال نہیں — پہلا اکاؤنٹ بنتے ہی یہ صفحہ محفوظ ہو جائے گا۔ جان بوجھ کر کوئی ڈیفالٹ admin/admin نہیں ہے۔",tokenIntro:"فلیٹ ٹوکن — ابھی کاپی کریں اور ہر caravan-scout میں شامل کریں:",goBoard:"بورڈ کھولیں",mismatch:"پاس ورڈ مماثل نہیں",failed:"سائن ان ناکام"},
    tr:{sub:"Filo denetleyicisine giriş yapın",user:"Kullanıcı adı",pass:"Parola",signin:"Giriş yap",passNew:"Parola (en az 8 karakter)",passRepeat:"Parolayı tekrarla",create:"Hesap oluştur ve girişi etkinleştir",setupNote:"Giriş henüz etkin değil — ilk hesap oluşturulunca bu sayfa korunur. Varsayılan admin/admin bilerek yok.",tokenIntro:"Filo belirteci — şimdi kopyalayın ve her caravan-scout'a ekleyin:",goBoard:"Panoyu aç",mismatch:"parolalar eşleşmiyor",failed:"giriş başarısız"},
    ko:{sub:"플릿 컨트롤러에 로그인",user:"사용자 이름",pass:"비밀번호",signin:"로그인",passNew:"비밀번호(8자 이상)",passRepeat:"비밀번호 재입력",create:"계정 만들고 로그인 활성화",setupNote:"로그인은 아직 비활성 상태입니다. 첫 계정을 만들면 이 페이지가 보호됩니다. 기본 admin/admin은 의도적으로 없습니다.",tokenIntro:"플릿 토큰 — 지금 복사해 각 caravan-scout에 추가하세요:",goBoard:"보드 열기",mismatch:"비밀번호가 일치하지 않습니다",failed:"로그인 실패"},
    vi:{sub:"Đăng nhập bộ điều khiển đội máy",user:"Tên đăng nhập",pass:"Mật khẩu",signin:"Đăng nhập",passNew:"Mật khẩu (tối thiểu 8 ký tự)",passRepeat:"Nhập lại mật khẩu",create:"Tạo tài khoản & bật đăng nhập",setupNote:"Đăng nhập chưa được bật — trang này sẽ được bảo vệ sau khi tạo tài khoản đầu tiên. Cố ý không có admin/admin mặc định.",tokenIntro:"Mã fleet — sao chép ngay và thêm vào từng caravan-scout:",goBoard:"Mở bảng",mismatch:"mật khẩu không khớp",failed:"đăng nhập thất bại"},
    it:{sub:"Accedi al controller della flotta",user:"Nome utente",pass:"Password",signin:"Accedi",passNew:"Password (min. 8 caratteri)",passRepeat:"Ripeti la password",create:"Crea account e attiva l'accesso",setupNote:"L'accesso non è ancora attivo: questa pagina sarà protetta dopo il primo account. Nessun admin/admin predefinito, di proposito.",tokenIntro:"Token della flotta — copialo ora e aggiungilo a ogni caravan-scout:",goBoard:"Apri la board",mismatch:"le password non coincidono",failed:"accesso non riuscito"},
    te:{sub:"ఫ్లీట్ కంట్రోలర్‌లో సైన్ ఇన్ అవ్వండి",user:"వాడుకరి పేరు",pass:"పాస్‌వర్డ్",signin:"సైన్ ఇన్",passNew:"పాస్‌వర్డ్ (కనీసం 8 అక్షరాలు)",passRepeat:"పాస్‌వర్డ్ మళ్లీ ఇవ్వండి",create:"ఖాతా సృష్టించి సైన్-ఇన్ ప్రారంభించండి",setupNote:"సైన్-ఇన్ ఇంకా ప్రారంభించలేదు — మొదటి ఖాతా సృష్టించాక ఈ పేజీ రక్షించబడుతుంది. డిఫాల్ట్ admin/admin ఉద్దేశపూర్వకంగా లేదు.",tokenIntro:"Fleet టోకెన్ — ఇప్పుడే కాపీ చేసి ప్రతి caravan-scout కు జోడించండి:",goBoard:"బోర్డ్ తెరవండి",mismatch:"పాస్‌వర్డ్‌లు సరిపోలడం లేదు",failed:"సైన్ ఇన్ విఫలమైంది"},
    mr:{sub:"फ्लीट कंट्रोलरमध्ये साइन इन करा",user:"वापरकर्तानाव",pass:"पासवर्ड",signin:"साइन इन",passNew:"पासवर्ड (किमान 8 अक्षरे)",passRepeat:"पासवर्ड पुन्हा लिहा",create:"खाते तयार करा आणि साइन-इन सुरू करा",setupNote:"साइन-इन अजून सुरू नाही — पहिले खाते तयार होताच हे पान संरक्षित होईल. मुद्दाम कोणतेही डीफॉल्ट admin/admin नाही.",tokenIntro:"Fleet टोकन — आत्ताच कॉपी करा आणि प्रत्येक caravan-scout मध्ये जोडा:",goBoard:"बोर्ड उघडा",mismatch:"पासवर्ड जुळत नाहीत",failed:"साइन इन अयशस्वी"},
    ta:{sub:"ஃபிளீட் கண்ட்ரோலரில் உள்நுழையவும்",user:"பயனர்பெயர்",pass:"கடவுச்சொல்",signin:"உள்நுழை",passNew:"கடவுச்சொல் (குறைந்தது 8 எழுத்துகள்)",passRepeat:"கடவுச்சொல்லை மீண்டும் உள்ளிடவும்",create:"கணக்கை உருவாக்கி உள்நுழைவை இயக்கு",setupNote:"உள்நுழைவு இன்னும் இயக்கப்படவில்லை — முதல் கணக்கு உருவானதும் இந்தப் பக்கம் பாதுகாக்கப்படும். இயல்புநிலை admin/admin வேண்டுமென்றே இல்லை.",tokenIntro:"Fleet டோக்கன் — இப்போதே நகலெடுத்து ஒவ்வொரு caravan-scout இலும் சேர்க்கவும்:",goBoard:"போர்டைத் திற",mismatch:"கடவுச்சொற்கள் பொருந்தவில்லை",failed:"உள்நுழைவு தோல்வி"}
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
    document.querySelectorAll("[data-t]").forEach(function (el) { el.textContent = T(el.dataset.t); });
    document.documentElement.dir = (lang === "ar" || lang === "ur") ? "rtl" : "ltr";
  }
  sel.addEventListener("change", function () {
    lang = sel.value;
    localStorage.setItem("llamacppAdminLang", lang);
    apply();
  });
  apply();

  // Свежая установка: вход ещё не включён → мастер первого аккаунта.
  fetch("/api/auth/me").then(function (r) { return r.json(); }).then(function (me) {
    if (me && me.enabled === false) {
      document.getElementById("loginForm").classList.add("hidden");
      document.getElementById("setupForm").classList.remove("hidden");
    }
  }).catch(function () {});

  document.getElementById("loginForm").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var e = document.getElementById("e");
    e.textContent = "";
    fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: document.getElementById("u").value.trim(),
                             password: document.getElementById("p").value })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok && res.j.ok) { window.location = "/"; }
        else { e.textContent = res.j.error || T("failed"); }
      }).catch(function (err) { e.textContent = String(err); });
  });

  document.getElementById("setupForm").addEventListener("submit", function (ev) {
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
        if (res.ok && res.j.ok) {
          document.getElementById("setupForm").classList.add("hidden");
          document.getElementById("tokenBox").classList.remove("hidden");
          document.getElementById("tokenVal").textContent = res.j.fleetToken || "";
        } else { se.textContent = res.j.error || T("failed"); }
      }).catch(function (err) { se.textContent = String(err); });
  });
  document.getElementById("goBoard").addEventListener("click", function () { window.location = "/"; });
})();
</script>
</body>
</html>
"""


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
