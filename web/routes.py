import time
import uuid
import json
import threading
from datetime import datetime
from flask import request, render_template, session, redirect, url_for, jsonify
from core.settings import SkynetSettings
from database import db, users_collection, banned_collection, withdrawals_collection, proxy_sessions, archive_collection

def register_main_routes(app, bot, add_radar_log, ban_user_everywhere, mute_user_everywhere,
                         unban_user_everywhere, unmute_user_everywhere, background_corpse_removal,
                         WEB_USER, WEB_PASS, OWNER_ID, ADMIN_CHAT_IDS, ROOT_PIN, STAFF_GROUP_ID):

    @app.route('/glaz/login', methods=['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            if request.form['username'] == WEB_USER and request.form['password'] == WEB_PASS:
                session['logged_in'] = True
                add_radar_log("🔐 Успешный вход в систему: Web-Саурон")
                return redirect(url_for('admin_panel'))
            else:
                error = 'ОТКАЗАНО: Неверный маркер доступа!'
                add_radar_log(f"⚠️ Неудачная попытка входа! Логин: {request.form.get('username')}")
        return render_template('login.html', error=error)

    @app.route('/glaz/logout')
    def logout():
        session.pop('logged_in', None)
        return redirect(url_for('login'))

    @app.route('/glaz', methods=['GET', 'POST'])
    def admin_panel():
        if not session.get('logged_in'): return redirect(url_for('login'))
        
        total_users = users_collection.count_documents({})
        vip_users = users_collection.count_documents({"is_vip": True})
        queer_users = users_collection.count_documents({"is_queer": True})
        banned_users = banned_collection.count_documents({})
        
        all_withdrawals = list(withdrawals_collection.find().sort("_id", -1).limit(50))
        all_promos = list(db['promocodes'].find().sort("_id", -1))
        
        user_data = None
        search_error = None
        
        search_id = request.args.get('search_id') or request.form.get('search_id')
        if search_id:
            try:
                uid = int(search_id.strip())
                u_info = users_collection.find_one({"_id": uid})
                b_info = banned_collection.find_one({"_id": uid})
                archive_info = archive_collection.find_one({"target": str(uid)})
                
                if u_info or b_info or archive_info:
                    history_list = []
                    if archive_info and archive_info.get("history"):
                        for entry in archive_info["history"]:
                            history_list.append(f"[{entry.get('date', '')}] {entry.get('action', '')} — {entry.get('reason', '')}")
                    
                    detected_reason = "Нет активных блокировок"
                    if b_info and b_info.get("reason"): detected_reason = b_info.get("reason")
                    elif u_info and u_info.get("last_mute_reason"): detected_reason = u_info.get("last_mute_reason")
                    elif archive_info and archive_info.get("history"): detected_reason = archive_info["history"][-1].get("reason", "Не указана")

                    is_admin_system = (uid == OWNER_ID or uid in ADMIN_CHAT_IDS)

                    is_quarantine = False
                    first_seen = u_info.get("first_seen", 0) if u_info else 0
                    if uid > 7800000000 and first_seen > 0 and (time.time() - first_seen) < 172800:
                        is_quarantine = True

                    # 💎 ВЫТАСКИВАЕМ СОКРОВИЩА ИЗ ПЛАТЕЖНОЙ БАЗЫ СКАЙНЕТА
                    p_info = db['paid_users'].find_one({"uid": uid}) or {}
                    
                    # Расчет остатка таймера кружка верификации
                    v_timer = p_info.get("verif_timer")
                    seconds_left = 0
                    if v_timer:
                        diff = (datetime.now() - v_timer).total_seconds()
                        seconds_left = max(0, int(300 - diff))

                    user_data = {
                        "id": uid,
                        "is_quarantine": is_quarantine,
                        "is_vip": u_info.get("is_vip", False) if u_info else False,
                        "is_queer": u_info.get("is_queer", False) if u_info else False,
                        "is_verified": u_info.get("is_verified", False) if u_info else False,
                        "is_admin": is_admin_system,
                        "main_city": u_info.get("main_city", "Не привязан") if u_info else "Не привязан",
                        "custom_tag": u_info.get("custom_tag", "Отсутствует") if u_info else "Отсутствует",
                        "shame_tag": u_info.get("shame_tag", "Отсутствует") if u_info else "Отсутствует",
                        "banned": True if b_info else False,
                        "ban_reason": detected_reason,
                        "history": history_list,
                        
                        # Новые поля для админки
                        "points": p_info.get("bounty_points", 0),
                        "shards": p_info.get("jackpot_shards", 0),
                        "cashback": p_info.get("cashback_balance", 0),
                        "immunity": p_info.get("immunity", 0),
                        "strikes": p_info.get("strikes", 0),
                        "admin_notes": p_info.get("admin_notes", ""),
                        "ai_memory": p_info.get("dialog_history", [])[-6:], # Последние 6 реплик
                        "secret_code": p_info.get("secret_code", ""),
                        "verif_seconds_left": seconds_left
                    }
                    add_radar_log(f"🔎 Обыск досье: {uid}")
                else:
                    search_error = f"Юзер {uid} не найден в матрице базы данных."
            except ValueError:
                search_error = "ID должен состоять только из цифр!"

        return render_template(
            'index.html', 
            total=total_users, vips=vip_users, queers=queer_users, banned=banned_users,
            user_data=user_data, search_error=search_error, search_id=search_id or "",
            withdrawals=all_withdrawals, promos=all_promos
        )

    @app.route('/glaz/api/stats')
    def api_stats():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        return jsonify({
            "total": users_collection.count_documents({}),
            "vips": users_collection.count_documents({"is_vip": True}),
            "queers": users_collection.count_documents({"is_queer": True}),
            "banned": banned_collection.count_documents({}),
            "unanswered_tickets": db['support_tickets'].count_documents({"is_answered": False, "is_closed": {"$ne": True}})
        })

    @app.route('/glaz/api/xray')
    def api_xray():
        if not session.get('logged_in'): 
            return jsonify({"error": "Unauthorized"}), 401
        
        total = users_collection.count_documents({})
        vips = users_collection.count_documents({"is_vip": True})
        queers = users_collection.count_documents({"is_queer": True})
        verified_only = users_collection.count_documents({
            "is_verified": True, 
            "is_vip": {"$ne": True}, 
            "is_queer": {"$ne": True}
        })
        banned = banned_collection.count_documents({})

        # === ВОРОНКА ВЕРИФИКАЦИИ ===
        in_verification = db['vip_funnel'].count_documents({})

        # === УМНАЯ КЛАССИФИКАЦИЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ ===
        # Активные (у кого бот определил город или кто нажимал на кнопки создания рекламы/саппорта)
        active_regular = users_collection.count_documents({
            "is_vip": {"$ne": True},
            "is_queer": {"$ne": True},
            "is_verified": {"$ne": True},
            "$or": [
                {"main_city": {"$exists": True, "$ne": "Не привязан"}},
                {"intent_post_ads": True},
                {"intent_support": True}
            ]
        })

        # В процессе верификации (заходили в меню, но не завершили кружок)
        pending_vip = users_collection.count_documents({
            "is_vip": {"$ne": True},
            "is_queer": {"$ne": True},
            "intent_vip": True
        })

        # Зеваки (зашли, получили первый контакт, но ничего не нажимали и город не привязался)
        just_viewed = users_collection.count_documents({
            "is_vip": {"$ne": True},
            "is_queer": {"$ne": True},
            "is_verified": {"$ne": True},
            "first_seen": {"$exists": True},
            "main_city": {"$exists": False},
            "intent_vip": {"$ne": True},
            "intent_support": {"$ne": True},
            "intent_post_ads": {"$ne": True}
        })

        # Настоящие мертвые души (старые аккаунты до внедрения логирования)
        real_ghosts = users_collection.count_documents({
            "is_vip": {"$ne": True},
            "is_queer": {"$ne": True},
            "is_verified": {"$ne": True},
            "first_seen": {"$exists": False},
            "main_city": {"$exists": False},
            "intent_vip": {"$ne": True},
            "intent_support": {"$ne": True},
            "intent_post_ads": {"$ne": True}
        })

        # Данные для счетчиков кнопок
        intent_vip = users_collection.count_documents({"intent_vip": True})
        intent_support = users_collection.count_documents({"intent_support": True})
        intent_ads = users_collection.count_documents({"intent_post_ads": True})

        return jsonify({
            "total": total,
            "vips": vips,
            "queers": queers,
            "verified": verified_only,
            "banned": banned,
            "in_verification": in_verification,
            "active_regular": active_regular,
            "just_viewed": just_viewed,
            "ghosts": real_ghosts,
            "intent_vip": intent_vip,
            "intent_support": intent_support,
            "intent_ads": intent_ads,
            "pending_vip": pending_vip
        })

    @app.route('/glaz/api/chart_data')
    def api_chart_data():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        total = users_collection.count_documents({})
        vips = users_collection.count_documents({"is_vip": True})
        queers = users_collection.count_documents({"is_queer": True})
        banned = banned_collection.count_documents({})
        regular = max(0, total - vips - queers)

        pipeline = [
            {"$match": {"main_city": {"$exists": True, "$ne": "Не привязан"}}},
            {"$group": {"_id": "$main_city", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        city_stats = list(users_collection.aggregate(pipeline))
        
        return jsonify({
            "status_values": [regular, vips, queers, banned],
            "city_labels": [item["_id"] for item in city_stats],
            "city_values": [item["count"] for item in city_stats]
        })

    @app.route('/glaz/api/radar')
    def api_radar():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        logs = db['radar_logs'].find().sort("ts", -1).limit(100)
        return jsonify([log["text"] for log in logs])

    @app.route('/glaz/api/get_list')
    def api_get_list():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        list_type = request.args.get('type')
        results = []
        
        if list_type == 'vip':
            for doc in users_collection.find({"is_vip": True}):
                results.append({"id": doc["_id"], "info": doc.get("main_city", "Не указан"), "tag": doc.get("custom_tag", "VIP")})
        elif list_type == 'queer':
            for doc in users_collection.find({"is_queer": True}):
                results.append({"id": doc["_id"], "info": doc.get("main_city", "Не указан"), "tag": doc.get("custom_tag", "QUEER")})
        elif list_type == 'banned':
            for doc in banned_collection.find().limit(1000):
                results.append({"id": doc["_id"], "info": doc.get("reason", "Забанен"), "tag": "ЧС"})
                
        return jsonify(results)

    @app.route('/glaz/api/proxy_sessions')
    def api_proxy_sessions():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        sessions = list(proxy_sessions.find().sort("_id", -1).limit(30))
        result = []
        for s in sessions:
            result.append({
                "id": s["_id"],
                "vip_id": s.get("vip_id", "Неизвестно"),
                "guest_id": s.get("guest_id", "Неизвестно"),
                "is_active": s.get("is_active", False),
                "msg_count": len(s.get("history", []))
            })
        return jsonify(result)

    @app.route('/glaz/api/proxy_chat')
    def api_proxy_chat():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        session_id = request.args.get('session_id')
        s = proxy_sessions.find_one({"_id": session_id})
        if not s: return jsonify({"error": "Not found"})
        return jsonify({
            "vip_id": s.get("vip_id"),
            "guest_id": s.get("guest_id"),
            "is_active": s.get("is_active", False),
            "history": s.get("history", [])
        })

    @app.route('/glaz/mass_action', methods=['POST'])
    def glaz_mass_action():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        raw_ids = request.form.get('uids', '')
        action = request.form.get('action', 'ban')
        reason = request.form.get('reason', '').strip()
        if not reason: reason = "Массовая репрессия (Web)"
        uids = []
        for line in raw_ids.replace(',', '\n').split('\n'):
            clean_id = line.strip()
            if clean_id.isdigit(): uids.append(int(clean_id))
        if not uids: return jsonify({"success": False, "message": "Не найдено валидных ID!"})
        add_radar_log(f"⚡ Запущен МАССОВЫЙ {action.upper()} ({reason}) для {len(uids)} юзеров!")
        def background_mass_task(id_list, act, rsn):
            for uid in id_list:
                if act == 'ban': ban_user_everywhere(uid, reason=rsn, admin_name="Web-Саурон")
                elif act == 'mute': mute_user_everywhere(uid, reason=rsn, admin_name="Web-Саурон")
                elif act == 'unban': unban_user_everywhere(uid); unmute_user_everywhere(uid)
                time.sleep(0.5)
            add_radar_log(f"✅ Массовый {act.upper()} успешно завершен!")
            try: bot.send_message(STAFF_GROUP_ID, f"🚀 **ВЕБ-АДМИНКА:** Завершен массовый {act.upper()} для {len(id_list)} пользователей!\n📝 Причина: {rsn}")
            except: pass
        threading.Thread(target=background_mass_task, args=(uids, action, reason), daemon=True).start()
        return jsonify({"success": True, "message": f"🔥 Процесс пошел! Наказание займет около {len(uids)//2} сек."})

    @app.route('/glaz/user_action', methods=['POST'])
    def glaz_user_action():
        if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
        uid = int(request.form.get('uid'))
        action = request.form.get('action')
        msg = "Действие выполнено"
        log_to_staff = True
        staff_msg = ""
        if action == 'ban':
            ban_user_everywhere(uid, reason="Ликвидация через Web-Панель", admin_name="Web-Саурон 👁️")
            msg = f"💥 Пользователь {uid} ликвидирован!"
            log_to_staff = False 
        elif action == 'unban':
            unban_user_everywhere(uid); unmute_user_everywhere(uid)
            msg = f"🕊️ С {uid} сняты баны."
            add_radar_log(f"🕊️ АМНИСТИЯ: {uid}")
            staff_msg = f"🕊️ **ВЕБ-АДМИНКА: ПОЛНАЯ АМНИСТИЯ**\n\n• **Пользователь:** `{uid}`\n• **Действие:** Глобально разбанен!"
        elif action == 'make_vip':
            users_collection.update_one({"_id": uid}, {"$set": {"is_vip": True}}, upsert=True)
            msg = f"👑 {uid} коронован!"
            add_radar_log(f"👑 ВЫДАН VIP: {uid}")
            staff_msg = f"👑 **ВЕБ-АДМИНКА: КОРОНАЦИЯ (VIP)**\n\n• **Пользователь:** `{uid}`"
            try: bot.send_message(uid, "👑 Администрация выдала вам статус VIP через панель управления!")
            except: pass
        elif action == 'remove_vip':
            users_collection.update_one({"_id": uid}, {"$set": {"is_vip": False}})
            msg = f"❌ VIP снят с {uid}."
            add_radar_log(f"❌ СНЯТ VIP: {uid}")
            staff_msg = f"❌ **ВЕБ-АДМИНКА: СНЯТИЕ VIP**\n\n• **Пользователь:** `{uid}`"
            try: bot.send_message(uid, "❌ Ваш статус VIP аннулирован администрацией.")
            except: pass
        elif action == 'make_queer':
            users_collection.update_one({"_id": uid}, {"$set": {"is_queer": True}}, upsert=True)
            msg = f"🏳️‍🌈 {uid} добавлен в BEYOND!"
            add_radar_log(f"🏳️‍🌈 ВЫДАН QUEER: {uid}")
            staff_msg = f"🏳️‍🌈 **ВЕБ-АДМИНКА: ДОСТУП BEYOND**\n\n• **Пользователь:** `{uid}`"
            try: bot.send_message(uid, "🏳️‍🌈 Администрация предоставила вам доступ к клубу BEYOND!")
            except: pass
        elif action == 'remove_queer':
            users_collection.update_one({"_id": uid}, {"$set": {"is_queer": False}})
            msg = f"⚠️ {uid} удален из BEYOND."
            add_radar_log(f"⚠️ СНЯТ QUEER: {uid}")
            staff_msg = f"⚠️ **ВЕБ-АДМИНКА: ИСКЛЮЧЕНИЕ ИЗ BEYOND**\n\n• **Пользователь:** `{uid}`"
        elif action == 'set_tag':
            new_tag = request.form.get('tag', '').strip()
            if new_tag and new_tag.lower() != 'none':
                users_collection.update_one({"_id": uid}, {"$set": {"custom_tag": new_tag}}, upsert=True)
                msg = f"🎖️ Выдан тег: {new_tag}"
                add_radar_log(f"🎖️ ТЕГ [{new_tag}]: {uid}")
                staff_msg = f"🎖️ **ВЕБ-АДМИНКА: ВЫДАЧА ПОГОН**\n\n• **Пользователь:** `{uid}`\n• **Тег:** `{new_tag}`"
            else:
                users_collection.update_one({"_id": uid}, {"$unset": {"custom_tag": ""}})
                msg = "🧹 Тег аннулирован."
                add_radar_log(f"🧹 СНЯТ ТЕГ: {uid}")
                staff_msg = f"🧹 **ВЕБ-АДМИНКА: СБРОС ТЕГА**\n\n• **Пользователь:** `{uid}`"
        elif action == 'set_city':
            new_city = request.form.get('city', '').strip()
            users_collection.update_one({"_id": uid}, {"$set": {"main_city": new_city}}, upsert=True)
            msg = f"📍 Город изменен на: {new_city}"
            add_radar_log(f"📍 ГОРОД [{new_city}]: {uid}")
            staff_msg = f"📍 **ВЕБ-АДМИНКА:** Изменен город для `{uid}` на `{new_city}`"
        if log_to_staff and staff_msg:
            try: bot.send_message(STAFF_GROUP_ID, staff_msg, parse_mode="Markdown")
            except: pass
        return jsonify({"success": True, "message": msg})

    @app.route('/glaz/api/add_balance', methods=['POST'])
    def api_add_balance():
        if not session.get('logged_in'): 
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        uid = int(request.form.get('uid'))
        currency = request.form.get('currency') # Ожидаем 'points' или 'shards'
        amount = int(request.form.get('amount', 0))
        
        admin_info = "Web-Саурон 👁️"
        
        if amount == 0:
            return jsonify({"success": False, "error": "Сумма не может быть нулем"})

        if currency == 'points':
            db['paid_users'].update_one({"uid": uid}, {"$inc": {"bounty_points": amount}}, upsert=True)
            msg = f"💰 Очки Бдительности {'добавлены' if amount > 0 else 'списаны'}: {amount}"
            add_radar_log(f"💰 БАЛАНС ОЧКОВ [{amount}]: {uid}")
            staff_msg = f"💰 **ВЕБ-АДМИНКА: ИЗМЕНЕНИЕ ОЧКОВ**\n\n• **Юзер:** `{uid}`\n• **Изменение:** `{amount}` очков"
            user_msg = f"🎁 **Уведомление!**\nАдминистрация изменила ваш баланс Очков Бдительности на **{amount}**."
            
        elif currency == 'shards':
            db['paid_users'].update_one({"uid": uid}, {"$inc": {"jackpot_shards": amount}}, upsert=True)
            msg = f"🧩 Осколки {'добавлены' if amount > 0 else 'списаны'}: {amount}"
            add_radar_log(f"🧩 БАЛАНС ОСКОЛКОВ [{amount}]: {uid}")
            staff_msg = f"🧩 **ВЕБ-АДМИНКА: ИЗМЕНЕНИЕ ОСКОЛКОВ**\n\n• **Юзер:** `{uid}`\n• **Изменение:** `{amount}` осколков"
            user_msg = f"🧩 **Уведомление!**\nАдминистрация изменила ваш баланс Осколков на **{amount}**."
            
        else:
            return jsonify({"success": False, "error": "Неизвестная валюта"})

        # Отправляем уведомления
        try: bot.send_message(STAFF_GROUP_ID, staff_msg, parse_mode="Markdown")
        except: pass
        
        # Если начисляем в плюс, радуем юзера сообщением
        if amount > 0:
            try: bot.send_message(uid, user_msg, parse_mode="Markdown")
            except: pass

        return jsonify({"success": True, "message": msg})

    @app.route('/glaz/api/system_settings')
    def api_system_settings():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        return jsonify(SkynetSettings.get())

    @app.route('/glaz/toggle_setting', methods=['POST'])
    def toggle_setting():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        setting_name = request.form.get('setting')
        if not setting_name: return jsonify({"success": False, "error": "No setting specified"})
        current = SkynetSettings.get()
        new_val = not current.get(setting_name, True)
        SkynetSettings.set(setting_name, new_val)
        add_radar_log(f"⚙️ Тумблер: {setting_name} ➡️ {'ВКЛ' if new_val else 'ВЫКЛ'}")
        return jsonify({"success": True, "state": new_val, "setting": setting_name})

    @app.route('/glaz/api/quarantine_list')
    def api_quarantine_list():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        now = time.time()
        threshold = now - 172800
        newbies = list(users_collection.find({"_id": {"$gt": 7800000000}, "first_seen": {"$gt": threshold}}))
        result = [{"id": u["_id"], "hours_left": round((172800 - (now - u['first_seen'])) / 3600, 1)} for u in newbies]
        return jsonify(result)

    @app.route('/glaz/release_quarantine', methods=['POST'])
    def release_quarantine():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        uid = int(request.form.get('uid'))
        users_collection.update_one({"_id": uid}, {"$set": {"first_seen": 0}}) 
        add_radar_log(f"🥷 Амнистия новорега: {uid}")
        try: bot.send_message(uid, "Base Администрация досрочно сняла с вас карантин! Можете писать в чаты.")
        except: pass
        return jsonify({"success": True})

    @app.route('/glaz/api/preview_broadcast', methods=['POST'])
    def api_preview_broadcast():
        if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        data = request.json
        txt = data.get('text', '')
        buttons_list = data.get('buttons', [])
        
        from telebot import types
        markup = None
        if buttons_list:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for btn in buttons_list:
                kwargs = {"text": btn["text"], "url": btn["url"]}
                if btn.get("style") and btn["style"] != "default": kwargs["style"] = btn["style"]
                if btn.get("emoji_id"): kwargs["icon_custom_emoji_id"] = btn["emoji_id"]
                markup.add(types.InlineKeyboardButton(**kwargs))
                
        try:
            # Отправляем тестовое сообщение создателю (OWNER_ID берется из config.py)
            bot.send_message(
                OWNER_ID, 
                f"👀 **ПРЕДПРОСМОТР РАССЫЛКИ:**\n\n{txt}", 
                parse_mode="HTML", 
                disable_web_page_preview=True, 
                reply_markup=markup
            )
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    # 👇 НОВЫЙ БЛОК: ТРЕКИНГ КЛИКОВ, ТАЙМЕР И РАССЫЛКА 👇
    @app.route('/t/<link_id>')
    def track_link(link_id):
        # Находим шпионскую ссылку, плюсуем клик и перекидываем юзера
        link_data = db['tracked_links'].find_one_and_update(
            {"_id": link_id}, {"$inc": {"clicks": 1}}
        )
        if link_data: return redirect(link_data["url"])
        return "Ссылка не найдена или устарела", 404

    def execute_broadcast(txt, tgt, btns_list):
        from telebot import types
        import time
        from config import all_cities # <-- Достаем список всех городов и чатов
        
        markup = None
        if btns_list:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for btn in btns_list:
                kwargs = {"text": btn["text"], "url": btn["url"]}
                if btn.get("style") and btn["style"] != "default": kwargs["style"] = btn["style"]
                if btn.get("emoji_id"): kwargs["icon_custom_emoji_id"] = btn["emoji_id"]
                markup.add(types.InlineKeyboardButton(**kwargs))
                
        add_radar_log(f"🚀 Запуск рассылки для: {tgt}")
        
        count = 0
        dead_count = 0

        # 👇 НОВЫЙ БЛОК: РАССЫЛКА ПО ВСЕМ ГРУППАМ СЕТИ 👇
        if tgt == 'groups_all':
            group_ids = set() # Используем set, чтобы исключить дубликаты
            for city, networks in all_cities.items():
                for net_key, groups in networks.items():
                    for group in groups:
                        group_ids.add(group['chat_id'])
            
            for chat_id in group_ids:
                try:
                    bot.send_message(chat_id, txt, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
                    count += 1
                    time.sleep(0.5) # Пауза для групп чуть больше (0.5 сек), чтобы ТГ не дал Flood Wait
                except Exception as e:
                    print(f"Ошибка рассылки в чат {chat_id}: {e}")
                    
            add_radar_log(f"✅ Рассылка по группам: Доставлено в {count} чатов.")
            try: bot.send_message(STAFF_GROUP_ID, f"🚀 **Рассылка по ГРУППАМ завершена!**\n✅ Опубликовано в: {count} чатов.")
            except: pass
            return
        # 👆 ========================================== 👆

        # --- СТАРАЯ ЛОГИКА ДЛЯ ЛС ПОЛЬЗОВАТЕЛЕЙ ---
        cursor = users_collection.find({}) if tgt == 'all' else users_collection.find({"is_vip": True}) if tgt == 'vip' else users_collection.find({"is_queer": True}) if tgt == 'queer' else None
        if not cursor: return
        
        for u in cursor:
            try:
                bot.send_message(u['_id'], txt, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
                count += 1
                time.sleep(0.05) # Искусственная пауза (~20 сообщений в секунду)
                
            except Exception as e:
                err_text = str(e).lower()
                
                # 1. Обработка лимитов Telegram (ждем, если просят)
                if "too many requests" in err_text:
                    try:
                        import re
                        wait_time = int(re.search(r'retry after (\d+)', err_text).group(1))
                    except:
                        wait_time = 3 
                    time.sleep(wait_time)
                    
                # 2. Пользователь УДАЛИЛ аккаунт (настоящий "труп")
                elif "deactivated" in err_text:
                    users_collection.delete_one({"_id": u['_id']})
                    dead_count += 1
                    # 🔥 Физически выгоняем из всех чатов сети!
                    try:
                        ban_user_everywhere(u['_id'], reason="Удаленный аккаунт (Автоочистка)", admin_name="Скайнет")
                    except:
                        pass
                        
                # 3. Пользователь просто заблокировал бота в ЛС (он жив, но рассылку не хочет)
                elif "blocked" in err_text:
                    users_collection.delete_one({"_id": u['_id']})
                    dead_count += 1
                    
                # 4. Ошибка форматирования текста
                elif "parse entities" in err_text:
                    try:
                        bot.send_message(u['_id'], txt, disable_web_page_preview=True, reply_markup=markup)
                        count += 1
                        time.sleep(0.05)
                    except Exception:
                        pass

        add_radar_log(f"✅ Рассылка: Доставлено {count}. 💀 Вывезено трупов: {dead_count}")
        try: bot.send_message(STAFF_GROUP_ID, f"🚀 **Рассылка завершена!**\nЦель: {tgt}\n✅ Доставлено: {count} чел.\n💀 Мертвых душ удалено: {dead_count}")
        except: pass

    # Демон, который проверяет отложенные рассылки каждую минуту
    def scheduled_daemon():
        while True:
            try:
                now = time.time()
                tasks = list(db['scheduled_broadcasts'].find({"status": "pending", "run_at": {"$lte": now}}))
                for t in tasks:
                    db['scheduled_broadcasts'].update_one({"_id": t["_id"]}, {"$set": {"status": "done"}})
                    execute_broadcast(t["text"], t["target"], t["buttons"])
            except Exception as e: print(e)
            time.sleep(30)
            
    threading.Thread(target=scheduled_daemon, daemon=True).start()

    @app.route('/glaz/broadcast', methods=['POST'])
    def glaz_broadcast():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        text = request.form.get('text')
        target = request.form.get('target')
        run_at_str = request.form.get('run_at')
        buttons_raw = request.form.get('buttons', '[]')
        
        try: buttons_list = json.loads(buttons_raw)
        except: buttons_list = []

        # 🎯 ТРЕКЕР КЛИКОВ: Превращаем обычные ссылки в наши трекеры
        host_url = request.url_root.replace('http://', 'https://')
        for btn in buttons_list:
            if btn.get("url") and btn["url"].startswith("http"):
                link_id = str(uuid.uuid4())[:8]
                db['tracked_links'].insert_one({
                    "_id": link_id, "url": btn["url"], "clicks": 0, 
                    "name": btn["text"], "timestamp": time.time()
                })
                btn["url"] = f"{host_url}t/{link_id}"

        # ⏰ ТАЙМЕР: Проверка на отложенный запуск
        if run_at_str:
            try:
                import pytz # На всякий случай импортируем библиотеку
                
                # Указываем ваш часовой пояс (если нужна Москва, напишите 'Europe/Moscow')
                tz = pytz.timezone('Asia/Yekaterinburg') 
                
                # Читаем время и привязываем к нему часовой пояс
                naive_dt = datetime.strptime(run_at_str, "%Y-%m-%dT%H:%M")
                run_at_ts = tz.localize(naive_dt).timestamp()
                
                if run_at_ts > time.time():
                    db['scheduled_broadcasts'].insert_one({
                        "text": text, "target": target, "buttons": buttons_list,
                        "run_at": run_at_ts, "status": "pending"
                    })
                    add_radar_log(f"⏰ Рассылка отложена до {run_at_str.replace('T', ' ')}")
                    return jsonify({"success": True, "message": "⏰ Рассылка успешно поставлена в очередь!"})
            except Exception as e: print("Ошибка таймера:", e)

        # 🚀 ЗАПУСК СЕЙЧАС (если дата не указана)
        threading.Thread(target=execute_broadcast, args=(text, target, buttons_list), daemon=True).start()
        return jsonify({"success": True, "message": "🚀 Рассылка запущена в фоне!"})

    @app.route('/glaz/api/broadcast_stats')
    def api_broadcast_stats():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        # Собираем очередь
        scheduled = list(db['scheduled_broadcasts'].find({"status": "pending"}).sort("run_at", 1))
        sched_res = [{"id": str(s["_id"]), "target": s["target"], "time": datetime.fromtimestamp(s["run_at"]).strftime("%d.%m.%Y %H:%M")} for s in scheduled]
        # Собираем статистику кликов
        links = list(db['tracked_links'].find().sort("timestamp", -1).limit(50))
        links_res = [{"id": L["_id"], "name": L.get("name", "Кнопка"), "url": L.get("url", ""), "clicks": L.get("clicks", 0), "time": datetime.fromtimestamp(L.get("timestamp", time.time())).strftime("%d.%m.%Y %H:%M")} for L in links]
            
        return jsonify({"scheduled": sched_res, "links": links_res})
    
    @app.route('/glaz/api/cancel_broadcast', methods=['POST'])
    def api_cancel_broadcast():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        from bson import ObjectId
        db['scheduled_broadcasts'].delete_one({"_id": ObjectId(request.json.get("id"))})
        return jsonify({"success": True})
    # 👆 ================================================== 👆

    @app.route('/glaz/api/dictionary', methods=['GET'])
    def get_dictionary():
        data = db['settings'].find_one({"_id": "skynet_dictionary"}) or {"red": [], "yellow": [], "black": []}
        return jsonify({
            "red": data.get("red", []), 
            "yellow": data.get("yellow", []), 
            "black": data.get("black", [])
        })

    @app.route('/glaz/api/dictionary/add', methods=['POST'])
    def add_dictionary_word():
        if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
        data = request.json
        word = data.get('word', '').strip().lower()
        zone = data.get('zone')
        exact = data.get('exact', False)
        if not word or zone not in ['red', 'yellow', 'black']: return jsonify({"success": False, "error": "Некорректные данные"})
        if exact: pattern = rf"\b{word}\b"
        else: pattern = rf"\b{word}[а-я]*\b"
        new_entry = {"word": word, "pattern": pattern, "exact": exact}
        db['settings'].update_one({"_id": "skynet_dictionary"}, {"$push": {zone: new_entry}}, upsert=True)
        return jsonify({"success": True, "message": f"Слово '{word}' добавлено в {zone} zone!"})

    @app.route('/glaz/api/dictionary/remove', methods=['POST'])
    def remove_dictionary_word():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json
        word = data.get('word')
        zone = data.get('zone')
        db['settings'].update_one({"_id": "skynet_dictionary"}, {"$pull": {zone: {"word": word}}})
        return jsonify({"success": True})

    @app.route('/glaz/api/system_texts', methods=['GET'])
    def api_get_system_texts():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        data = db['settings'].find_one({"_id": "skynet_texts"}) or {}
        return jsonify({
            "quarantine_warn": data.get("quarantine_warn", "🚨 {user_link}, **Защита от спама!**\nВаш аккаунт создан недавно. Для безопасности сети действует карантин 48 часов.\nПодождите, или пройдите верификацию в [Службе Поддержки](https://t.me/MK_MensClubSUPPORT)."),
            "may_1_warn": data.get("may_1_warn", "🚨 {user_link}, **ВНИМАНИЕ!**\n\nС 1 мая введен СТРОГИЙ стандарт оформления анкет для досок объявлений.\nЛюбой текст **БЕЗ ПАРАМЕТРОВ** или с неправильным форматом запрещен!\nПараметры должны быть указаны **ТОЛЬКО через слеш (/) без пробелов и лишних слов**.\n\n✅ *Примеры:* `24/187/72` или `24/187/72/19` (допускается `19.5` или `19*4`)\n\nВаша анкета удалена, а вы временно ограничены в общении во всех группах сети.\n\n💡 *P.S. В нашей сети «ПАРНИ 18+» нет ограничений на формат текста и разрешен любой откровенный контент (включая порно). Переходи туда! 👇*"),
            "minor_warn": data.get("minor_warn", "🚨 {user_link}, **Внимание!**\nВаша анкета попала под автоматический фильтр безопасности сети. Пройдите обязательную верификацию 🔞.")
        })

    @app.route('/glaz/api/system_texts/save', methods=['POST'])
    def api_save_system_texts():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json
        db['settings'].update_one(
            {"_id": "skynet_texts"},
            {"$set": {
                "quarantine_warn": data.get("quarantine_warn"),
                "may_1_warn": data.get("may_1_warn"),
                "minor_warn": data.get("minor_warn")
            }},
            upsert=True
        )
        add_radar_log("📝 Тексты системных предупреждений обновлены!")
        return jsonify({"success": True, "message": "✅ Тексты успешно вшиты в нейросеть!"})

    @app.route('/glaz/api/send_sauron_msg', methods=['POST'])
    def api_send_sauron_msg():
        if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
        uid = request.form.get('uid')
        message_text = request.form.get('message')
        if not uid or not message_text: return jsonify({"success": False, "error": "Пустые данные"}), 400
        try:
            bot.send_message(chat_id=int(uid), text=f"👑 **Сообщение от Администрации:**\n\n{message_text}", parse_mode="Markdown")
            add_radar_log(f"👁‍🗨 Голос Саурона: Отправлено ЛС юзеру {uid}")
            return jsonify({"success": True})
        except Exception as e:
            err_str = str(e).lower()
            if "bot was blocked" in err_str or "deactivated" in err_str:
                return jsonify({"success": False, "error": "Пользователь заблокировал бота или удален 💀"})
            return jsonify({"success": False, "error": "Ошибка API Telegram"})

    @app.route('/glaz/api/templates', methods=['GET'])
    def api_get_templates():
        templates = list(db['templates'].find({}, {"_id": 0}))
        return jsonify(templates)

    @app.route('/glaz/api/templates/save', methods=['POST'])
    def api_save_template():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json
        new_template = {
            "id": str(uuid.uuid4())[:8],
            "name": data.get("name", "Новый шаблон"),
            "text": data.get("text", ""),
            "target": data.get("target", "all"),
            "buttons": data.get("buttons", []),
            "autopilot_interval": 0,
            "last_run": 0
        }
        db['templates'].insert_one(new_template)
        return jsonify({"success": True, "message": "Шаблон сохранен!"})

    @app.route('/glaz/api/templates/delete', methods=['POST'])
    def api_delete_template():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        db['templates'].delete_one({"id": request.json.get("id")})
        return jsonify({"success": True})

    @app.route('/glaz/api/templates/toggle_autopilot', methods=['POST'])
    def api_toggle_autopilot():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        tid = request.json.get("id")
        interval = int(request.json.get("interval", 0))
        db['templates'].update_one({"id": tid}, {"$set": {"autopilot_interval": interval, "last_run": 0}})
        return jsonify({"success": True})

    @app.route('/glaz/api/root/buttons', methods=['POST'])
    def api_get_root_buttons():
        data = request.json
        if data.get('pin') != ROOT_PIN:
            return jsonify({"error": "Access Denied"}), 403
        
        btns = db['settings'].find_one({"_id": "skynet_buttons"})
        if not btns or not btns.get("buttons"):
            default_btns = [
                {"text": "Подписаться на МК", "url": "https://t.me/своя_ссылка"},
                {"text": "ПАРНИ 18+", "url": "https://t.me/znakparni"}
            ]
            return jsonify({"buttons": default_btns})
        return jsonify({"buttons": btns.get("buttons", [])})

    @app.route('/glaz/api/root/save_buttons', methods=['POST'])
    def api_save_root_buttons():
        data = request.json
        if data.get('pin') != ROOT_PIN:
            return jsonify({"error": "Access Denied"}), 403
        
        new_buttons = data.get('buttons', [])
        # Теперь кнопки сохраняются правильно в общую таблицу настроек!
        db['settings'].update_one(
            {"_id": "skynet_buttons"}, 
            {"$set": {"buttons": new_buttons}}, 
            upsert=True
        )
        return jsonify({"status": "ok"})

    # === РОУТЫ ДЛЯ МИНИ-АППКИ VIP ===
    # 1. Отдаем саму страничку Мини-аппа
    @app.route('/mini_app_post')
    def mini_app_post():
        return render_template('create_post.html')

    # 2. Принимаем хардкорную FormData с текстом и файлами
    @app.route('/api/submit_mini_app', methods=['POST'])
    def submit_mini_app():
        import io
        user_id = request.form.get('user_id')
        text = request.form.get('text')
        network = request.form.get('network')
        city = request.form.get('city')
        uploaded_files = request.files.getlist('media')

        if not user_id:
            return jsonify({"status": "error", "message": "No user_id"}), 400

        user_id = int(user_id)

        # Вытаскиваем байты файлов из памяти сразу, пока запрос активен
        files_to_process = []
        for file in uploaded_files[:10]: # Ограничение Телеграма — до 10 файлов
            filename = file.filename.lower()
            is_video = filename.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))
            files_to_process.append({
                "bytes": file.read(),
                "is_video": is_video
            })

        # Асинхронная фоновая отправка в Telegram
        def background_upload(uid, txt, net, cty, f_list):
            from database import temp_posts
            from telebot import types
            import io
            
            if f_list:
                try: bot.send_message(uid, f"⏳ Получено {len(f_list)} файлов из Мини-аппа. Начинаю загрузку в Telegram...")
                except: pass
            
            media_items = []
            for f in f_list:
                try:
                    bio = io.BytesIO(f['bytes'])
                    if f['is_video']:
                        bio.name = "video.mp4"
                        msg = bot.send_video(uid, bio)
                        media_items.append({"type": "video", "id": msg.video.file_id})
                    else:
                        bio.name = "photo.jpg"
                        msg = bot.send_photo(uid, bio)
                        media_items.append({"type": "photo", "id": msg.photo[-1].file_id})
                except Exception as e:
                    print(f"Ошибка фоновой загрузки медиа: {e}")
            
            # Сохраняем готовый черновик в базу данных
            temp_posts.update_one(
                {"_id": uid},
                {"$set": {
                    "text": txt,
                    "network": net,
                    "city": cty,
                    "media": media_items,
                    "status": "ready_to_publish" # Меняем статус на "готов к публикации"
                }},
                upsert=True
            )
            
            # Предлагаем кнопку финальной публикации в чате бота
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add("🚀 Опубликовать анкету")
            markup.add("Назад")
            try:
                bot.send_message(
                    uid, 
                    "✅ **Все медиафайлы успешно загружены через Мини-апп!**\n\nНажмите на кнопку ниже, чтобы запустить публикацию анкеты:", 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
            except: pass

        # Запускаем поток и мгновенно отвечаем фронтенду "ok", чтобы закрыть/переключить окно
        threading.Thread(target=background_upload, args=(user_id, text, network, city, files_to_process), daemon=True).start()
        return jsonify({"status": "ok"})

# === API ДЛЯ УПРАВЛЕНИЯ АНКЕТАМИ В МИНИ-АППКЕ ===
    
    @app.route('/api/get_user_posts', methods=['GET'])
    def api_get_user_posts():
        user_id_str = request.args.get('user_id', '0')
        user_id = int(user_id_str) if user_id_str.isdigit() else 0
        
        # Получаем посты юзера из базы, сортируем от новых к старым
        posts = list(db['posts'].find({"user_id": user_id}).sort("time", -1))
        
        from utils import format_time
        result = []
        for p in posts:
            time_str = format_time(p["time"]) if "time" in p else "Неизвестно"
            text_preview = p.get("text", "")[:40] + "..." # Обрезаем длинный текст для превью
            
            result.append({
                "id": str(p["_id"]),
                "network": p.get("network", "Неизвестно"),
                "city": p.get("city", "Неизвестно"),
                "time": time_str,
                "text": text_preview
            })
        return jsonify({"success": True, "posts": result})

    @app.route('/api/delete_post', methods=['POST'])
    def api_delete_post():
        data = request.json
        post_id = data.get('post_id')
        user_id = data.get('user_id')
        
        from bson import ObjectId
        post = db['posts'].find_one({"_id": ObjectId(post_id), "user_id": int(user_id)})
        
        if not post:
            return jsonify({"success": False, "message": "Анкета не найдена"})
            
        # 🔥 Правильное удаление (как в posts.py)
        chat_id = post.get("chat_id")
        msg_ids = post.get("message_ids", [post.get("message_id")])
        
        if chat_id:
            for m_id in msg_ids:
                if m_id:
                    try: bot.delete_message(chat_id, m_id)
                    except: pass
                    
        db['posts'].delete_one({"_id": ObjectId(post_id)})
        return jsonify({"success": True})

# 👇 УНИВЕРСАЛЬНЫЙ КРИПТО-КАССИР ДЛЯ VIP, ШТРАФОВ И ГОРОДОВ 👇
    @app.route('/glaz/api/cryptobot_webhook', methods=['POST'])
    def cryptobot_webhook():
        import random
        from config import VIP_CHAT_ID # Подтягиваем настройки
        
        data = request.json
        if not data or data.get("update_type") != "invoice_paid":
            return jsonify({"status": "ignored"}), 200
            
        invoice = data.get("payload", {})
        payload_str = invoice.get("payload", "") 
        amount_rub = float(invoice.get("amount", 0))

        # 👑 1. ОПЛАТА VIP-КЛУБА
        if payload_str.startswith("vip_"):
            uid = int(payload_str.replace("vip_", ""))
            db['vip_funnel'].delete_one({"_id": uid})
            try:
                users_collection.update_one({"_id": uid}, {"$set": {"is_vip": True}}, upsert=True)
                unmute_user_everywhere(uid)
                unban_user_everywhere(uid)
                users_collection.update_one({"_id": uid}, {"$unset": {"shame_tag": ""}})
                archive_collection.update_one({"target": str(uid)}, {"$unset": {"banned_in_support": "", "strikes": ""}})
            except Exception as e: print(e)
            
            try: 
                bot.send_message(STAFF_GROUP_ID, f"🤑 **УСПЕШНАЯ ОПЛАТА VIP КРИПТОЙ!**\nЮзер: `{uid}`\nСумма: {amount_rub} руб.")
                invite = bot.create_chat_invite_link(VIP_CHAT_ID, member_limit=1)
                bot.send_message(uid, f"🎉 **Крипто-оплата успешно получена!**\n👉 [ВХОД В VIP-КЛУБ]({invite.invite_link})", parse_mode="Markdown", disable_web_page_preview=True)
            except: pass

        # 🚨 2. ОПЛАТА ШТРАФА (АМНИСТИЯ)
        elif payload_str.startswith("fine_"):
            uid = int(payload_str.replace("fine_", ""))
            now = datetime.now()
            ticket_num = now.strftime("%d%m%Y%H%M%S") + f"-{random.randint(100, 999)}"
            
            db['skynet_tasks'].insert_one({"uid": uid, "action": "fine_unban", "timestamp": now})
            archive_collection.update_one({"target": str(uid)}, {"$push": {"history": {"date": now.strftime("%d.%m.%Y %H:%M"), "action": "Разблокировка (Крипта)", "reason": "Штраф оплачен"}}}, upsert=True)
            
            # 👇 ДОСТАЕМ THREAD_ID ДЛЯ ЗАКРЫТИЯ ТОПИКА 👇
            user_data = db['paid_users'].find_one({"uid": uid})
            thread_id = user_data.get("thread_id") if user_data else None
            
            db['paid_users'].update_one({"uid": uid}, {"$set": {"status": 0}, "$unset": {"topic_type": ""}})
            
            try:
                # Отправляем отчет прямо в топик и ЗАКРЫВАЕМ его
                if thread_id:
                    bot.send_message(STAFF_GROUP_ID, f"🤑 **ШТРАФ ОПЛАЧЕН КРИПТОЙ!**\nЮзер: `{uid}`\nСумма: {amount_rub} руб.", message_thread_id=thread_id)
                    bot.close_forum_topic(STAFF_GROUP_ID, thread_id)
                else:
                    bot.send_message(STAFF_GROUP_ID, f"🤑 **ШТРАФ ОПЛАЧЕН КРИПТОЙ!**\nЮзер: `{uid}`\nСумма: {amount_rub} руб.")
                    
                bot.send_message(uid, f"✅ **Оплата штрафа получена!**\n\nОграничения сняты. Уникальный номер: `{ticket_num}`\n*Больше не нарушайте правила!*", parse_mode="Markdown")
            except: pass

        # 🏙 3. ОПЛАТА ДОСТУПА К ГОРОДУ
        elif payload_str.startswith("city_"):
            # Формат: city_123456789_Екатеринбург
            parts = payload_str.split("_", 2)
            uid = int(parts[1])
            purchased_city = parts[2]
            
            users_collection.update_one({"_id": uid}, {"$addToSet": {"purchased_cities": purchased_city}}, upsert=True)
            try:
                bot.send_message(STAFF_GROUP_ID, f"🤑 **ПРОПУСК В ГОРОД КРИПТОЙ!**\nЮзер: `{uid}`\nГород: {purchased_city}")
                bot.send_message(uid, f"🎉 **Оплата получена!** Доступ к городу **{purchased_city}** открыт.\n\n*Так как ссылки одноразовые, отправьте боту команду /start или нажмите на кнопку выбора города еще раз, чтобы получить их.*", parse_mode="Markdown")
            except: pass

        # 📢 4. ОПЛАТА РЕКЛАМЫ
        elif payload_str.startswith("ad_access_"):
            # Расшифровываем маячок: ad_access_7_mk_Екатеринбург___123456789
            actual_payload, uid_str = payload_str.split("___")
            uid = int(uid_str)
            
            # Пишем доход
            db['daily_revenue'].insert_one({"type": "ads", "amount": amount_rub, "timestamp": time.time(), "date": datetime.now().strftime("%d.%m.%Y")})
            
            has_pin = "_pin" in actual_payload
            clean_payload = actual_payload.replace("_pin", "")
            parts = clean_payload.split('_')
            
            if "discount" in actual_payload:
                days = int(parts[3])
                net_key = parts[4]
                city = parts[5]
                promo_code = parts[6]
                db['promocodes'].update_one({"_id": promo_code}, {"$inc": {"used_count": 1}})
            else:
                days = int(parts[2])
                net_key = parts[3]
                city = parts[4]
                
            names = {"mk": "Мужской Клуб", "parni": "ПАРНИ 18+", "ns": "НС", "rainbow": "Радуга", "gayznak": "Гей Знакомства"}
            network = names.get(net_key, net_key)

            # Вычисляем срок годности по Екатеринбургу (как в mpserv.py)
            from datetime import timedelta
            import pytz
            ekb_tz = pytz.timezone('Asia/Yekaterinburg')
            now_ekb = datetime.now(ekb_tz)
            end_date = now_ekb + timedelta(days=days)

            # 💥 ЗАПИСЬ В БАЗУ ДАННЫХ
            db['ad_subscriptions'].insert_one({
                "user_id": uid,
                "network": network,
                "city": city,
                "end_date": end_date,
                "purchase_date": now_ekb,
                "has_pin": has_pin 
            })
            
            try:
                bot.send_message(STAFF_GROUP_ID, f"💰 **Новая продажа Рекламы (КРИПТА)!**\nЮзер: `{uid}`\nСеть: **{network}**\nГород: **{city}**\nСрок: **{days}** дн.", parse_mode="Markdown")
            except: pass

            try:
                bot.send_message(uid, f"✅ **Оплата успешно получена!**\n\nДоступ к сети **{network}** ({city}) открыт на {days} дней.\nНажмите «Создать новое объявление».", parse_mode="Markdown")
            except: pass

        # 💖 5. ДОНАТЫ (ЧАЕВЫЕ)
        elif payload_str.startswith("donation_"):
            uid = int(payload_str.replace("donation_", ""))
            
            # Записываем деньги в кассу (amount_rub получаем от CryptoBot)
            db['daily_revenue'].insert_one({
                "type": "donation", 
                "amount": amount_rub, 
                "timestamp": time.time(), 
                "date": datetime.now().strftime("%d.%m.%Y")
            })
            
            try:
                bot.send_message(
                    uid, 
                    f"💖 **Огромное спасибо за ваш крипто-донат ({amount_rub} руб.)!**\nЭти средства очень помогут нашему проекту развиваться.", 
                    parse_mode="Markdown"
                )
                bot.send_message(
                    STAFF_GROUP_ID, 
                    f"💸 **КРИПТО-ДОНАТ!** Пользователь `{uid}` только что отправил чаевые: **{amount_rub} руб.**! 🎉", 
                    parse_mode="Markdown"
                )
            except: 
                pass

        return jsonify({"status": "ok"}), 200
    # 👆 ============================================================== 👆

    # 👇 РОУТЫ ДЛЯ РЕДАКТОРА ШАБЛОНОВ И БАЗЫ ЗНАНИЙ ИИ 👇

    @app.route('/glaz/api/get_bot_template', methods=['GET'])
    def api_get_bot_template():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        name = request.args.get('name')
        if not name: return jsonify({"error": "No name"}), 400
        
        # 1. Сначала всегда ищем текст в общей базе Mongo (Синхронизация с Секретарем)
        doc = db['bot_templates'].find_one({"_id": name})
        if doc:
            return jsonify({"text": doc["text"]})
            
        # 2. 🚨 ХАРДКОД-ФОЛЛБЕК (так как templates.py физически лежит на другом сервере) 🚨
        NETWORK_LINKS = (
            "📍 **Ссылки для возврата в чаты:**\n"
            "• [МК (Мужской Клуб)](https://t.me/clubofrm/44)\n"
            "• [ПАРНИ 18+](https://t.me/znakparni/116)\n"
            "• [ГЕЙ чаты (Инфо)](https://t.me/gaychatcities_info/4)\n"
            "• [НС (Урал)](https://t.me/uralns/118)"
        )
        
        TEMPLATES = {
            "tpl_18": "🛑 **Внимание: Проверка возраста**\n\nУ администрации сети возникли подозрения относительно вашего совершеннолетия.\n\nℹ️ **Правило:** Находиться в сети чатов МК, ПАРНИ 18+, ГЕЙ чаты, НС, Радуга разрешено *исключительно* лицам, достигшим 18 лет.\n\n🛡 **Как снять ограничения:**\nВам необходимо предоставить фото одного из официальных документов, подтверждающих возраст:\n• Паспорт (РФ или заграничный)\n• Водительское удостоверение\n• Военный билет\n• Паспорт иностранного гражданина или ВНЖ\n*(Студенческие билеты, банковские карты и пропуски не принимаются!)*\n\nВ целях вашей безопасности мы просим **закрасить или скрыть** все персональные данные, оставив видимыми только **фотографию лица и дату рождения**.\n\n*После отправки фото ожидайте, администратор укажет дальнейший порядок действий.*",
            "tpl_nark_react": "⛔️ **БЛОКИРОВКА: Реакция на запрещенные вещества**\n\nВы были заблокированы за положительную реакцию (смайлик) на сообщение, связанное с наркотическими веществами.\n\nℹ️ В нашей сети действует нулевая терпимость к любым формам поддержки запрещенных веществ.\n\n🔓 Разблокировка возможна только на платной основе (штраф).",
            "tpl_verif": "⚠️ **Сработала система защиты**\n\nМы временно ограничили ваш доступ к сети МК из-за подозрительной активности аккаунта.\n\nℹ️ **Как снять ограничения:**\nДля подтверждения необходимо пройти видео-верификацию (записать видео-кружок). На видео должно быть четко видно ваше лицо, и вам нужно будет произнести специальную фразу.\n\n👉 Если вы готовы пройти проверку, напишите сюда: **«Готов»**.",
            "tpl_mp": "💰 **Ограничение: Коммерческая деятельность**\n\nВаши ограничения связаны с публикацией объявлений об оказании услуг за материальную помощь (МП).\n\nℹ️ Согласно правилам сети: любая коммерческая деятельность допускается *только после оплаты рекламного взноса*.\n\n🔓 **Для снятия ограничений** необходимо оплатить штраф за нарушение правил + оплатить рекламный пакет. Напишите «+» или «ДА», если хотите узнать условия.",
            "tpl_sponsor": "💎 **Ограничение: Предложение спонсорства**\n\nВаши ограничения связаны с публикацией сообщений, в которых вы предлагаете финансовую поддержку (выступаете в роли спонсора).\n\nℹ️ В нашей сети подобные предложения приравниваются к платной коммерческой деятельности. Публикация таких объявлений допускается только после оплаты специального взноса.\n\n🔓 **Для снятия ограничений** и получения официального разрешения необходимо оплатить штраф-взнос в размере 750⭐️. Напишите «Готов оплатить», чтобы мы выставили счет.",
            "tpl_nark": "⛔️ **БЛОКИРОВКА: Наркотические вещества**\n\nПричина вашей блокировки — упоминание наркотиков. Любые вещества и их эвфемизмы (смайлики, сленг, положительные реакции, комментарии) строго запрещены.\n\n⚖️ **Условия разблокировки:**\nРазбан возможен только после предоставления справки от врача-нарколога либо справки от МВД.\n\n*В исключительных случаях возможен разбан после оплаты штрафа (сумма определяется старшим администратором).*.",
            "tpl_flood": "🔇 **Ограничение: Флуд в чатах**\n\nВы получили временный мут за флуд (однотипные сообщения более 3-х раз подряд).\n\n⏳ **Ограничение снимется автоматически** (точное время указано в системном сообщении внутри чата).\n\n⚡️ Если вы не хотите ждать, возможно досрочное снятие мута на платной основе (от 100₽).",
            "tpl_vip": "⚠️ **Служебное уведомление системы**\n\nВы были заблокированы по внутренней сети партнерских проектов.\n\nℹ️ **Причина:** Вы заблокировали VIP или ТРАНС-бота в момент проведения диалога и не отправили ключевую фразу.\n\n🔓 Разблокировка возможна только на платной основе.",
            "tpl_bio": "🛑 **Ограничение: Ссылка в профиле**\n\nАвтомодератор обнаружил в вашем профиле (BIO) стороннюю ссылку или тег канала.\n\nℹ️ **Порядок действий:**\n1. Полностью уберите ссылку/канал из профиля Telegram.\n2. Не возвращайте ее на всё время пребывания в сетях МК, ПАРНИ 18+, ГЕЙ чаты, НС, Радуга.\n3. Оплатите штраф 250⭐️.\n\n*После оплаты и проверки профиля администратором ограничения будут сняты.*",
            "tpl_minor": "⛔️ **БЛОКИРОВКА: Несовершеннолетние**\n\nВы заблокированы за то, что оставили реакцию на объявление несовершеннолетнего пользователя.\n\nℹ️ Мы строго следим за возрастным цензом. Это грубое нарушение правил безопасности.\n\n🔓 Разблокировка возможна только на платной основе (штраф)."
        }

        if name == "network_links":
            return jsonify({"text": NETWORK_LINKS})
        elif name == "ai_system_prompt":
            return jsonify({"text": "Ты строгий, но понимающий ИИ-модератор поддержки.\nТебе нужно выслушать проблему пользователя и помочь ему. Если ситуация сложная — переводи на оператора."}) 
        else:
            return jsonify({"text": TEMPLATES.get(name, "Шаблон не найден")})

    @app.route('/glaz/api/save_bot_template', methods=['POST'])
    def api_save_bot_template():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json
        name = data.get("name")
        text = data.get("text")
        
        if name and text:
            db['bot_templates'].update_one(
                {"_id": name},
                {"$set": {"text": text}},
                upsert=True
            )
            add_radar_log(f"📝 Администратор обновил системный текст: {name}")
            return jsonify({"success": True})
        return jsonify({"error": "Bad data"}), 400

    @app.route('/glaz/api/ai_prompt', methods=['GET'])
    def api_get_prompt_legacy():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        doc = db['bot_templates'].find_one({"_id": "ai_system_prompt"})
        return jsonify({"prompt": doc["text"] if doc else ""})

    @app.route('/glaz/api/ai_prompt/save', methods=['POST'])
    def api_save_prompt_legacy():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        text = request.json.get("prompt")
        db['bot_templates'].update_one({"_id": "ai_system_prompt"}, {"$set": {"text": text}}, upsert=True)
        add_radar_log("🧠 Инструкции нейросети обновлены!")
        return jsonify({"success": True})
        
    # 👆 ======================================================== 👆

        
    @app.route('/glaz/api/user/save_inventory', methods=['POST'])
    def api_user_save_inventory():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json
        uid = int(data.get("uid"))
        
        db['paid_users'].update_one(
            {"uid": uid},
            {"$set": {
                "bounty_points": int(data.get("points", 0)),
                "jackpot_shards": int(data.get("shards", 0)),
                "cashback_balance": int(data.get("cashback", 0)),
                "immunity": int(data.get("immunity", 0))
            }},
            upsert=True
        )
        add_radar_log(f"💰 Web-Изменение инвентаря у юзера {uid}")
        return jsonify({"success": True})

    @app.route('/glaz/api/user/reset_strikes', methods=['POST'])
    def api_user_reset_strikes():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        uid = int(request.json.get("uid"))
        db['paid_users'].update_one({"uid": uid}, {"$set": {"strikes": 0}})
        add_radar_log(f"🕊️ Счетчик страйков обнулен для {uid}")
        return jsonify({"success": True})

    @app.route('/glaz/api/user/clear_ai_memory', methods=['POST'])
    def api_user_clear_ai_memory():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        uid = int(request.json.get("uid"))
        db['paid_users'].update_one({"uid": uid}, {"$unset": {"dialog_history": ""}})
        add_radar_log(f"🧠 Память ИИ стерта для юзера {uid} (Люди в черном 🕶️)")
        return jsonify({"success": True})

    @app.route('/glaz/api/user/save_notes', methods=['POST'])
    def api_user_save_notes():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json
        uid = int(data.get("uid"))
        notes = data.get("notes", "").strip()
        
        db['paid_users'].update_one({"uid": uid}, {"$set": {"admin_notes": notes}}, upsert=True)
        return jsonify({"success": True})

# 👇 СИСТЕМА КОНТРОЛЯ КАЧЕСТВА И АНАЛИТИКИ ОЦЕНОК (ТИКЕТЫ) 👇

    @app.route('/glaz/api/ratings_analytics', methods=['GET'])
    def api_ratings_analytics():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        # 1. Считаем средний балл и количество закрытых тикетов по каждому админу и ИИ
        pipeline = [
            {"$group": {
                "_id": "$admin_id",
                "avg_score": {"$avg": "$rating"},
                "total_tickets": {"$sum": 1}
            }}
        ]
        raw_stats = list(db['ticket_ratings'].aggregate(pipeline))
        
        stats = []
        for item in raw_stats:
            stats.append({
                "admin": item["_id"],
                "avg": round(item.get("avg_score") or 0, 2), # 🔥 ПРЕДОХРАНИТЕЛЬ УСТАНОВЛЕН 🔥
                "count": item["total_tickets"]
            })
            
        # 2. Вытаскиваем последние 5 критических жалоб (1-2 звезды) для Радара Гнева
        bad_ratings = list(db['ticket_ratings'].find({"rating": {"$lte": 2}}).sort("timestamp", -1).limit(5))
        bad_list = []
        for r in bad_ratings:
            bad_list.append({
                "uid": r.get("uid"),
                "admin_id": r.get("admin_id"),
                "rating": r.get("rating"),
                "time": datetime.fromtimestamp(r.get("timestamp", time.time())).strftime("%d.%m %H:%M")
            })
            
        return jsonify({
            "stats": stats,
            "bad_list": bad_list
        })

    # === ИНФРАСТРУКТУРА И СЕТИ (ЭТАП 1) ===
    @app.route('/glaz/api/infrastructure', methods=['GET'])
    def api_get_infra():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        data = db['settings'].find_one({"_id": "infrastructure"}) or {}
        
        # 👇 СТРАХОВКА ОТ КРАША JSON 👇
        if "_id" in data:
            del data["_id"] 
            
        return jsonify(data)

    @app.route('/glaz/api/infrastructure/save', methods=['POST'])
    def api_save_infrastructure():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        data = request.json
        db['settings'].update_one(
            {"_id": "infrastructure"},
            {"$set": data},
            upsert=True
        )
        add_radar_log("🗺 Архитектура сети была изменена в ЦУП!")
        return jsonify({"success": True, "message": "✅ Инфраструктура сети успешно сохранена в MongoDB!"})
    # =======================================

    @app.route('/glaz/api/infrastructure/ping', methods=['GET'])
    def api_ping_infrastructure():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        data = db['settings'].find_one({"_id": "infrastructure"}) or {}
        networks = data.get("networks", {})
        statuses = {}
        
        bot_id = bot.get_me().id # Узнаем ID нашего бота
        
        for net_key, chats in networks.items():
            for chat in chats:
                cid = chat.get("id")
                if not cid: continue
                try:
                    # Проверяем, какие права у бота в этом чате
                    bot_member = bot.get_chat_member(cid, bot_id)
                    if bot_member.status == 'administrator':
                        statuses[cid] = {"code": "ok", "text": "🟢 Активен (Админ)"}
                    elif bot_member.status in ['member', 'restricted']:
                        statuses[cid] = {"code": "warn", "text": "🟡 Нет прав админа!"}
                    else:
                        statuses[cid] = {"code": "err", "text": "🔴 Бот кикнут"}
                except Exception as e:
                    err_str = str(e).lower()
                    if "chat not found" in err_str:
                        statuses[cid] = {"code": "err", "text": "🔴 Чат удален / Не найден"}
                    else:
                        statuses[cid] = {"code": "err", "text": "🔴 Ошибка доступа"}
                        
        return jsonify(statuses)

    @app.route('/glaz/api/moderation', methods=['GET'])
    def api_get_mod_settings():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        data = db['settings'].find_one({"_id": "moderation_limits"}) or {}
        return jsonify(data)

    @app.route('/glaz/api/moderation/save', methods=['POST'])
    def api_save_mod_settings():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        data = request.json
        db['settings'].update_one({"_id": "moderation_limits"}, {"$set": data}, upsert=True)
        add_radar_log("⚙️ Таймеры и настройки модерации изменены!")
        return jsonify({"success": True})

# 👇 МАГИЧЕСКАЯ МИГРАЦИЯ ИЗ CONFIG.PY В MONGODB 👇
    @app.route('/glaz/api/infrastructure/migrate', methods=['GET'])
    def api_migrate_infrastructure():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        # Загружаем старые данные из конфига
        from config import all_cities, chat_ids_parni, chat_ids_mk, chat_ids_ns, chat_ids_rainbow, chat_ids_gayznak, MAIN_CHANNEL_LINK
        
        # Умный конвертер словарей в нужный нам формат
        def convert_dict_to_list(chat_dict):
            return [{"name": name, "id": str(chat_id)} for name, chat_id in chat_dict.items()]

        migrated_data = {
            "cities": ", ".join(all_cities),
            "global_links": {"main_channel": MAIN_CHANNEL_LINK, "faq": ""},
            "networks": {
                "parni": convert_dict_to_list(chat_ids_parni),
                "mk": convert_dict_to_list(chat_ids_mk),
                "ns": convert_dict_to_list(chat_ids_ns),
                "rainbow": convert_dict_to_list(chat_ids_rainbow),
                "gayznak": convert_dict_to_list(chat_ids_gayznak)
            },
            "competitors": []
        }
        
        # Записываем в базу
        db['settings'].update_one(
            {"_id": "infrastructure"},
            {"$set": migrated_data},
            upsert=True
        )
        return "✅ Миграция успешно завершена! Вернитесь в ЦУП и обновите страницу."

    # === ПРЯМОЕ УПРАВЛЕНИЕ АНДРЮШЕНЬКОЙ (ЦЕЛИ) ===
    @app.route('/glaz/api/spy', methods=['GET'])
    def api_get_spy():
        if not session.get('logged_in'): return jsonify([])
        doc = db['settings'].find_one({"_id": "spy_settings"}) or {}
        return jsonify(doc.get("chats", []))

    @app.route('/glaz/api/spy/add', methods=['POST'])
    def api_add_spy():
        if not session.get('logged_in'): return jsonify({"success": False})
        chat = request.json.get('chat')
        try:
            if str(chat).lstrip('-').isdigit(): chat = int(chat)
        except: pass
        db['settings'].update_one({"_id": "spy_settings"}, {"$addToSet": {"chats": chat}}, upsert=True)
        add_radar_log(f"🎯 Новая цель для Бульдозера: {chat}")
        return jsonify({"success": True})

    @app.route('/glaz/api/spy/del', methods=['POST'])
    def api_del_spy():
        if not session.get('logged_in'): return jsonify({"success": False})
        chat = request.json.get('chat')
        try:
            if str(chat).lstrip('-').isdigit(): chat = int(chat)
        except: pass
        db['settings'].update_one({"_id": "spy_settings"}, {"$pull": {"chats": chat}})
        return jsonify({"success": True})

    # === ОТДАЕМ ПУЛЬС БОТОВ В ВЕБ-ПАНЕЛЬ ===
    @app.route('/glaz/api/system_status', methods=['GET'])
    def api_get_system_status():
        status_data = db['settings'].find_one({"_id": "bot_status"}) or {}
        if "_id" in status_data:
            del status_data["_id"]
        return jsonify(status_data)