import time
import uuid
import json
import threading
from datetime import datetime
from flask import request, render_template, session, redirect, url_for, jsonify
from core.settings import SkynetSettings
from database import db, users_collection, banned_collection, withdrawals_collection, proxy_sessions

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
                        "history": history_list
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

    @app.route('/glaz/broadcast', methods=['POST'])
    def glaz_broadcast():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        text = request.form.get('text')
        target = request.form.get('target')
        buttons_raw = request.form.get('buttons', '[]')
        try: buttons_list = json.loads(buttons_raw)
        except: buttons_list = []
        def bg_broadcast(txt, tgt, btns_list):
            from telebot import types
            markup = None
            if btns_list:
                markup = types.InlineKeyboardMarkup(row_width=1)
                for btn in btns_list:
                    kwargs = {"text": btn["text"], "url": btn["url"]}
                    if btn.get("style") and btn["style"] != "default": kwargs["style"] = btn["style"]
                    if btn.get("emoji_id"): kwargs["icon_custom_emoji_id"] = btn["emoji_id"]
                    markup.add(types.InlineKeyboardButton(**kwargs))
            add_radar_log(f"🚀 Запуск рассылки для: {tgt}")
            cursor = users_collection.find({}) if tgt == 'all' else users_collection.find({"is_vip": True}) if tgt == 'vip' else users_collection.find({"is_queer": True}) if tgt == 'queer' else None
            if not cursor: return
            count = 0
            dead_count = 0
            for u in cursor:
                try:
                    bot.send_message(u['_id'], txt, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)
                    count += 1
                except Exception as e:
                    err_text = str(e).lower()
                    if "parse entities" in err_text:
                        try:
                            bot.send_message(u['_id'], txt, disable_web_page_preview=True, reply_markup=markup)
                            count += 1
                        except Exception as inner_e:
                            if "deactivated" in str(inner_e).lower():
                                users_collection.delete_one({"_id": u['_id']})
                                dead_count += 1
                    elif "deactivated" in err_text:
                        users_collection.delete_one({"_id": u['_id']})
                        dead_count += 1
                        if SkynetSettings.get().get("auto_corpse_removal", True):
                            threading.Thread(target=background_corpse_removal, args=(u['_id'],), daemon=True).start() 
            add_radar_log(f"✅ Рассылка: Доставлено {count}. 💀 Вывезено трупов: {dead_count}")
            try: bot.send_message(STAFF_GROUP_ID, f"🚀 **Рассылка завершена!**\nЦель: {tgt}\n✅ Доставлено: {count} чел.\n💀 Удалено мертвых душ из базы: {dead_count}")
            except: pass
        threading.Thread(target=bg_broadcast, args=(text, target, buttons_list), daemon=True).start()
        return jsonify({"success": True, "message": "🚀 Рассылка запущена в фоне!"})

    @app.route('/glaz/api/dictionary', methods=['GET'])
    def get_dictionary():
        data = db['settings'].find_one({"_id": "skynet_dictionary"}) or {"red": [], "yellow": []}
        return jsonify({"red": data.get("red", []), "yellow": data.get("yellow", [])})

    @app.route('/glaz/api/dictionary/add', methods=['POST'])
    def add_dictionary_word():
        if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
        data = request.json
        word = data.get('word', '').strip().lower()
        zone = data.get('zone')
        exact = data.get('exact', False)
        if not word or zone not in ['red', 'yellow']: return jsonify({"success": False, "error": "Некорректные данные"})
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