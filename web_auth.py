"""
web_auth.py — защита веб-панели «Глаз Саурона».

Что делает:
  1. Логин + пароль (пароль хранится как ХЕШ в переменной окружения, не в коде).
  2. Второй фактор: одноразовый код приходит владельцу В TELEGRAM (с IP и браузером того, кто входит).
  3. Лимит попыток входа по IP (5 ошибок -> бан на 15 минут).
  4. Глобальный «охранник»: ВСЕ пути /glaz/* требуют сессию, даже если в роуте забыли проверку.
  5. Безопасные cookie + срок жизни сессии 12 часов.
  6. Проверка подписи CryptoBot и секрета Telegram-вебхука.

Подключение — см. ИНСТРУКЦИЯ в ответе (3 правки в app.py).
"""
import os
import time
import hmac
import hashlib
import secrets
from datetime import timedelta

from flask import request, session, redirect, url_for, render_template, jsonify, abort
from werkzeug.security import check_password_hash

from database import db

MAX_FAILS = 5
BLOCK_SECONDS = 15 * 60
CODE_TTL = 5 * 60
CODE_MAX_TRIES = 3
SESSION_HOURS = 12

# пути под /glaz, которые доступны без сессии
PUBLIC_PATHS = {
    "/glaz/login",
    "/glaz/2fa",
    "/glaz/api/cryptobot_webhook",  # защищён подписью, см. verify_cryptobot_signature
}


def client_ip():
    # За прокси (Render/Heroku/nginx) реальный IP лежит в X-Forwarded-For
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[0].strip() if xff else request.remote_addr) or "?"


# ---------- ЛИМИТ ПОПЫТОК ----------
def _is_blocked(ip):
    rec = db["login_attempts"].find_one({"_id": ip})
    return bool(rec and rec.get("blocked_until", 0) > time.time())


def _register_fail(ip):
    rec = db["login_attempts"].find_one_and_update(
        {"_id": ip}, {"$inc": {"fails": 1}, "$set": {"last": time.time()}},
        upsert=True, return_document=True,
    )
    if rec["fails"] >= MAX_FAILS:
        db["login_attempts"].update_one(
            {"_id": ip}, {"$set": {"blocked_until": time.time() + BLOCK_SECONDS, "fails": 0}}
        )


def _clear_fails(ip):
    db["login_attempts"].delete_one({"_id": ip})


# ---------- ПРОВЕРКА ПОДПИСЕЙ ВНЕШНИХ ВЕБХУКОВ ----------
def verify_cryptobot_signature(raw_body: bytes, header_sig: str) -> bool:
    """CryptoBot: HMAC-SHA256(body, key=SHA256(CRYPTO_TOKEN)), заголовок crypto-pay-api-signature."""
    token = os.getenv("CRYPTO_TOKEN", "")
    if not token or not header_sig:
        return False
    key = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig)


def verify_telegram_webhook_secret() -> bool:
    """Telegram шлёт X-Telegram-Bot-Api-Secret-Token, если вебхук поставлен с secret_token."""
    expected = os.getenv("TG_WEBHOOK_SECRET", "")
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return bool(expected) and hmac.compare_digest(expected, got)


# ---------- ПОДКЛЮЧЕНИЕ ----------
def init_web_auth(app, bot, add_radar_log, owner_id):
    secret = os.getenv("FLASK_SECRET_KEY")
    if not secret or len(secret) < 32:
        raise RuntimeError("Задай FLASK_SECRET_KEY (>=32 символов) в переменных окружения!")
    app.secret_key = secret

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,       # только по HTTPS
        SESSION_COOKIE_SAMESITE="Lax",    # базовая защита от CSRF
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
    )

    web_user = os.getenv("WEB_USER", "")
    web_pass_hash = os.getenv("WEB_PASS_HASH", "")
    if not web_user or not web_pass_hash:
        raise RuntimeError("Задай WEB_USER и WEB_PASS_HASH в переменных окружения!")

    # ---- Глобальный охранник ----
    @app.before_request
    def guard_glaz():
        p = request.path
        if p.startswith("/glaz") and p not in PUBLIC_PATHS:
            if not session.get("logged_in"):
                if p.startswith("/glaz/api"):
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for("login"))

    @app.after_request
    def sec_headers(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store" if request.path.startswith("/glaz") else resp.headers.get("Cache-Control", "")
        return resp

    # ---- Шаг 1: логин + пароль ----
    @app.route("/glaz/login", methods=["GET", "POST"])
    def login():
        error = None
        ip = client_ip()
        if request.method == "POST":
            if _is_blocked(ip):
                return render_template("login.html", error="Слишком много попыток. Подожди 15 минут."), 429

            u = request.form.get("username", "")
            pw = request.form.get("password", "")
            user_ok = hmac.compare_digest(u, web_user)
            pass_ok = check_password_hash(web_pass_hash, pw)  # проверяем всегда, чтобы не было timing-разницы

            if user_ok and pass_ok:
                code = f"{secrets.randbelow(1_000_000):06d}"
                db["web_login_codes"].replace_one(
                    {"_id": "owner"},
                    {"_id": "owner", "code_hash": hashlib.sha256(code.encode()).hexdigest(),
                     "exp": time.time() + CODE_TTL, "tries": 0, "ip": ip},
                    upsert=True,
                )
                ua = request.headers.get("User-Agent", "?")[:120]
                try:
                    bot.send_message(
                        owner_id,
                        f"🔐 <b>Вход в веб-панель</b>\nКод: <code>{code}</code>\n\n"
                        f"IP: <code>{ip}</code>\nБраузер: {ua}\n\n"
                        f"Это не ты? Никому не говори код и смени пароль.",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    add_radar_log(f"⚠️ Не удалось отправить 2FA-код: {e}")
                    return render_template("login.html", error="Не могу отправить код в Telegram."), 500

                session.clear()
                session["pre_auth_until"] = time.time() + CODE_TTL
                add_radar_log(f"🔑 Пароль верный, ждём 2FA-код. IP {ip}")
                return redirect(url_for("two_factor"))

            _register_fail(ip)
            add_radar_log(f"⚠️ Неудачная попытка входа в веб! IP {ip}, логин: {u[:30]}")
            error = "ОТКАЗАНО: Неверный маркер доступа!"
        return render_template("login.html", error=error)

    # ---- Шаг 2: код из Telegram ----
    @app.route("/glaz/2fa", methods=["GET", "POST"])
    def two_factor():
        ip = client_ip()
        if session.get("pre_auth_until", 0) < time.time():
            return redirect(url_for("login"))
        if _is_blocked(ip):
            return render_template("2fa.html", error="Слишком много попыток."), 429

        error = None
        if request.method == "POST":
            entered = request.form.get("code", "").strip()
            rec = db["web_login_codes"].find_one({"_id": "owner"})
            if not rec or rec["exp"] < time.time() or rec["tries"] >= CODE_MAX_TRIES:
                session.clear()
                return redirect(url_for("login"))

            db["web_login_codes"].update_one({"_id": "owner"}, {"$inc": {"tries": 1}})
            good = hmac.compare_digest(rec["code_hash"], hashlib.sha256(entered.encode()).hexdigest())
            if good:
                db["web_login_codes"].delete_one({"_id": "owner"})
                _clear_fails(ip)
                session.clear()
                session.permanent = True
                session["logged_in"] = True
                session["login_ip"] = ip
                add_radar_log(f"🔐 Успешный вход в веб (2FA пройдена). IP {ip}")
                return redirect(url_for("admin_panel"))

            _register_fail(ip)
            add_radar_log(f"⚠️ Неверный 2FA-код! IP {ip}")
            error = "Неверный код"
        return render_template("2fa.html", error=error)

    @app.route("/glaz/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
