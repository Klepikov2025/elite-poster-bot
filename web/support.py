"""
Вкладка «📩 Входящие»: обращения в поддержку Скайнета (кнопка «💬 Написать в Поддержку»).

2.0 (12.10.2026):
- ответы админов хранятся отдельными сообщениями (раньше ответ затирал предыдущий и не было видно, кто отвечал);
- в списке — сколько непрочитанных, статус человека (VIP/BEYOND/ЧС/мут), фильтр «ждут ответа», поиск и архив;
- быстрые ответы (заготовки) хранятся в базе и общие для всех админов.
"""
import time

from flask import request, jsonify, session
from telebot import types

from database import db

QUICK_DOC = "support_quick_replies"


def _card(uids):
    """uid -> краткая карточка человека для списка диалогов."""
    out = {u: {} for u in uids}
    if not uids:
        return out
    now = time.time()
    for u in db['users'].find({"_id": {"$in": uids}}, {"is_vip": 1, "is_queer": 1, "is_verified": 1, "main_city": 1,
                                                       "net_mute_until": 1, "custom_tag": 1}):
        c = out[u["_id"]]
        c["vip"] = bool(u.get("is_vip"))
        c["beyond"] = bool(u.get("is_queer"))
        c["verified"] = bool(u.get("is_verified"))
        city = u.get("main_city")
        if city and city != "Не привязан":
            c["city"] = city
        try:
            if float(u.get("net_mute_until") or 0) > now:
                c["muted"] = True
        except (TypeError, ValueError):
            pass
    for b in db['banned'].find({"_id": {"$in": uids}}, {"_id": 1}):
        out[b["_id"]]["banned"] = True
    return out


def register_support_routes(app, bot, add_radar_log):

    @app.route('/glaz/api/tickets', methods=['GET'])
    def api_get_tickets():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        archive = request.args.get('view') == 'archive'
        q = (request.args.get('q') or '').strip().lstrip('@')
        match = {"is_closed": True} if archive else {"is_closed": {"$ne": True}}
        match["from_admin"] = {"$ne": True}
        if q:
            if q.isdigit():
                match["uid"] = int(q)
            else:
                import re
                rx = {"$regex": re.escape(q), "$options": "i"}
                match["$or"] = [{"name": rx}, {"username": rx}, {"text": rx}]
        pipeline = [
            {"$match": match},
            {"$sort": {"timestamp": -1}},
            {"$group": {
                "_id": "$uid",
                "uid": {"$first": "$uid"},
                "name": {"$first": "$name"},
                "username": {"$first": "$username"},
                "text": {"$first": "$text"},
                "timestamp": {"$first": "$timestamp"},
                "is_answered": {"$first": "$is_answered"},
                "unread": {"$sum": {"$cond": [{"$eq": ["$is_answered", False]}, 1, 0]}},
                "count": {"$sum": 1},
                "answered_by": {"$first": "$answered_by"},
            }},
            {"$sort": {"timestamp": -1}},
            {"$limit": 100 if archive else 300},
        ]
        tickets = list(db['support_tickets'].aggregate(pipeline))
        cards = _card([t["uid"] for t in tickets if t.get("uid") is not None])
        for t in tickets:
            t.pop("_id", None)
            t["card"] = cards.get(t.get("uid"), {})
        # Сначала те, кто ждёт ответа (самые старые ожидающие — выше), потом остальные
        if not archive:
            waiting = sorted([t for t in tickets if t.get("unread")], key=lambda t: t.get("timestamp") or 0)
            rest = [t for t in tickets if not t.get("unread")]
            tickets = waiting + rest
        return jsonify(tickets)

    @app.route('/glaz/api/tickets/history', methods=['GET'])
    def api_get_ticket_history():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        try:
            uid = int(request.args.get('uid'))
        except (TypeError, ValueError):
            return jsonify([])
        out = []
        for h in db['support_tickets'].find({"uid": uid}).sort("timestamp", 1).limit(500):
            if h.get("from_admin"):
                out.append({"kind": "admin", "text": h.get("text", ""), "ts": h.get("timestamp"), "admin": h.get("admin") or "админ"})
                continue
            out.append({"kind": "user", "text": h.get("text", ""), "ts": h.get("timestamp"), "name": h.get("name") or "",
                        "closed": bool(h.get("is_closed"))})
            if h.get("reply_text"):  # старый формат: ответ хранился внутри вопроса
                out.append({"kind": "admin", "text": h["reply_text"], "ts": h.get("answered_at") or h.get("timestamp"),
                            "admin": h.get("answered_by") or "админ"})
        return jsonify(out)

    @app.route('/glaz/api/tickets/reply', methods=['POST'])
    def api_reply_ticket():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json or {}
        try:
            uid = int(data.get('uid'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Нет получателя"})
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify({"success": False, "error": "Пустой ответ"})
        markup = None
        buttons_raw = [b for b in (data.get('buttons') or []) if b.get("text") and str(b.get("url", "")).startswith(("http://", "https://", "tg://"))]
        if buttons_raw:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for btn in buttons_raw:
                markup.add(types.InlineKeyboardButton(text=btn["text"], url=btn["url"]))
        admin = session.get("login") or "админ"
        try:
            bot.send_message(uid, f"👨‍💻 <b>Ответ Службы Поддержки:</b>\n\n{text}", parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err:
                return jsonify({"success": False, "error": "Человек заблокировал бота — ответ не доставлен"})
            if "deactivated" in err:
                return jsonify({"success": False, "error": "Аккаунт удалён — ответ не доставлен"})
            return jsonify({"success": False, "error": str(e)[:200]})
        now = time.time()
        db['support_tickets'].insert_one({"uid": uid, "from_admin": True, "admin": admin, "text": text,
                                          "buttons": buttons_raw, "timestamp": now, "is_answered": True})
        db['support_tickets'].update_many({"uid": uid, "is_answered": False, "from_admin": {"$ne": True}},
                                          {"$set": {"is_answered": True, "answered_by": admin, "answered_at": now}})
        add_radar_log(f"✅ {admin} ответил в поддержке юзеру {uid}")
        return jsonify({"success": True})

    @app.route('/glaz/api/tickets/close', methods=['POST'])
    def api_close_ticket():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json or {}
        try:
            uid = int(data.get('uid'))
        except (TypeError, ValueError):
            return jsonify({"success": False})
        silent = bool(data.get('silent'))
        admin = session.get("login") or "админ"
        db['support_tickets'].update_many({"uid": uid, "is_closed": {"$ne": True}},
                                          {"$set": {"is_closed": True, "closed_by": admin, "closed_at": time.time(), "is_answered": True}})
        if not silent:
            try:
                bot.send_message(uid,
                    "✅ **Ваш запрос в Поддержку успешно решен и закрыт.**\n\nЕсли у вас возникнут новые вопросы — просто нажмите кнопку **«💬 Написать в Поддержку»** в меню бота, и мы снова будем на связи!",
                    parse_mode="Markdown")
            except Exception:
                pass
        add_radar_log(f"🧹 {admin} закрыл диалог поддержки с {uid}" + (" (без уведомления)" if silent else ""))
        return jsonify({"success": True})

    @app.route('/glaz/api/tickets/reopen', methods=['POST'])
    def api_reopen_ticket():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        try:
            uid = int((request.json or {}).get('uid'))
        except (TypeError, ValueError):
            return jsonify({"success": False})
        db['support_tickets'].update_many({"uid": uid}, {"$set": {"is_closed": False}})
        return jsonify({"success": True})

    # ---------- быстрые ответы ----------
    @app.route('/glaz/api/tickets/quick', methods=['GET'])
    def api_quick_replies():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        doc = db['settings'].find_one({"_id": QUICK_DOC}) or {}
        items = doc.get("items")
        if items is None:
            items = [
                {"title": "Приветствие", "text": "Здравствуйте! Спасибо за обращение, сейчас разберёмся."},
                {"title": "Верификация", "text": "Чтобы пройти верификацию, нажмите в меню «👑 Вступить в VIP-чат» и следуйте шагам бота."},
                {"title": "Разбан — к Секретарю", "text": "Вопросы разблокировки решает сервисный бот @FAQMKBOT — напишите ему, там всё быстро."},
            ]
        return jsonify(items)

    @app.route('/glaz/api/tickets/quick/save', methods=['POST'])
    def api_quick_replies_save():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        items = []
        for it in (request.json or {}).get("items", [])[:30]:
            title, text = str(it.get("title", "")).strip()[:40], str(it.get("text", "")).strip()[:2000]
            if title and text:
                items.append({"title": title, "text": text})
        db['settings'].update_one({"_id": QUICK_DOC}, {"$set": {"items": items}}, upsert=True)
        return jsonify({"success": True, "items": items})
