"""
core/join_gate.py — «вход в группу через бота» и бонус за подписку на бота.

Зачем: бот может писать в личку только тем, кто хоть раз нажал «Запустить» (/start).
Заявка в группу открывает личку всего на 5 минут, пока она не обработана.

Как работает (тумблер «Вход в группы через бота» в Настройках → Модерация):
1. Человек подаёт заявку в группу.
2. Если он уже запускал бота — одобряем сразу, как раньше.
3. Если нет — заявку не одобряем, а в эти 5 минут присылаем кнопку «Вступить». Кнопка открывает бота
   (это и есть /start), бот одобряет все его ждущие заявки. Личка остаётся открытой навсегда.
4. Если сообщение не доставилось — одобряем сразу, чтобы не потерять человека.
5. Кто так и не нажал — через N часов одобряем автоматически (0 — не одобрять).

Старым участникам: ссылка t.me/<бот>?start=sub даёт разовый бонус очками за подписку.
"""
import secrets
import time

from telebot import types

from core.cfg import cfg
from database import db, users_collection, banned_collection

_BOT_NAME = {}


def bot_username(bot):
    if "u" not in _BOT_NAME:
        try:
            _BOT_NAME["u"] = bot.get_me().username
        except Exception:
            return None
    return _BOT_NAME["u"]


def _approve(bot, chat_id, uid):
    try:
        bot.approve_chat_join_request(chat_id, uid)
        return True
    except Exception as e:
        # заявку уже обработали (одобрил админ / человек отозвал) — для нас это не ошибка
        if "HIDE_REQUESTER_MISSING" in str(e) or "USER_ALREADY_PARTICIPANT" in str(e):
            return True
        from core.diag import log_error
        log_error("Вход через бота", f"не удалось одобрить заявку {uid} в {chat_id}: {e}", uid)
        return False


def _approve_unless_banned(bot, chat_id, uid):
    """Одобрение отложенной заявки: за время ожидания человека могли забанить — тогда отклоняем."""
    try:
        banned = bool(banned_collection.find_one({"_id": uid}))
    except Exception:
        banned = False
    if banned:
        try:
            bot.decline_chat_join_request(chat_id, uid)
        except Exception:
            pass
        return False
    return _approve(bot, chat_id, uid)


def approve_or_gate(bot, chat_id, uid, chat_title=""):
    """Вместо bot.approve_chat_join_request в таможне. -> 'approved' | 'gated'."""
    if not cfg("join_via_bot"):
        _approve(bot, chat_id, uid)
        return "approved"
    u = users_collection.find_one({"_id": uid}, {"active": 1, "dm_blocked": 1}) or {}
    if u.get("active") and not u.get("dm_blocked"):
        _approve(bot, chat_id, uid)  # уже запускал бота — личка и так открыта
        return "approved"
    name = bot_username(bot)
    if not name:
        _approve(bot, chat_id, uid)
        return "approved"
    token = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
    db['join_gate'].update_one({"_id": f"{chat_id}:{uid}"},
                               {"$set": {"chat_id": chat_id, "uid": uid, "token": token, "ts": time.time(), "title": chat_title}},
                               upsert=True)
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("✅ Вступить в группу", url=f"https://t.me/{name}?start=j{token}"))
    text = str(cfg("join_gate_text") or "").replace("{chat}", chat_title or "группу")
    try:
        bot.send_message(uid, text, reply_markup=mk)
        return "gated"
    except Exception:
        # личка недоступна даже в окне заявки — не теряем человека
        db['join_gate'].delete_one({"_id": f"{chat_id}:{uid}"})
        _approve(bot, chat_id, uid)
        return "approved"


def release(bot, uid):
    """Человек открыл бота: одобряем все его ждущие заявки. -> список названий групп."""
    titles = []
    for g in list(db['join_gate'].find({"uid": uid})):
        if db['join_gate'].delete_one({"_id": g["_id"]}).deleted_count and _approve_unless_banned(bot, g["chat_id"], uid):
            titles.append(g.get("title") or "группа")
    return titles


def subscribe_bonus(uid):
    """Разовый бонус старому участнику за подписку на бота. -> очков начислено (0 — не положено)."""
    pts = int(cfg("subscribe_bonus_points") or 0)
    if pts <= 0 or banned_collection.find_one({"_id": uid}):
        return 0
    u = users_collection.find_one({"_id": uid}, {"first_seen": 1, "main_city": 1}) or {}
    if not (u.get("main_city") or (u.get("first_seen") and time.time() - float(u["first_seen"]) > 86400)):
        return 0  # бонус только тем, кто уже был в сети (защита от фермы новых аккаунтов)
    res = users_collection.update_one({"_id": uid, "subscribe_bonus": {"$ne": True}}, {"$set": {"subscribe_bonus": True}})
    if not res.modified_count:
        return 0
    db['paid_users'].update_one({"uid": uid}, {"$inc": {"bounty_points": pts}}, upsert=True)
    try:
        from core.janitor import log_points
        log_points(uid, "bounty_points", pts, reason="subscribe_bonus")
    except Exception:
        pass
    return pts


def gate_daemon(bot):
    """Кто не нажал кнопку за N часов — одобряем сами (0 — оставить заявку висеть)."""
    while True:
        try:
            hours = float(cfg("join_gate_timeout_hours") or 0)
            if hours > 0:
                for g in list(db['join_gate'].find({"ts": {"$lt": time.time() - hours * 3600}}).limit(200)):
                    if db['join_gate'].delete_one({"_id": g["_id"]}).deleted_count:
                        _approve_unless_banned(bot, g["chat_id"], g["uid"])
        except Exception as e:
            print(f"join_gate_daemon: {e}")
        time.sleep(600)
