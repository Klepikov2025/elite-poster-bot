from telebot import types
import time
from datetime import datetime
import pytz
import tempfile
import threading
import os
import random
import requests # <--- Добавить, если еще нет

def get_crypto_pay_url(custom_payload, amount_stars, description, asset=None):
    import os
    import requests
    
    amount_rub = int(amount_stars * 1.8)
    API_TOKEN = os.getenv("CRYPTO_TOKEN")
    
    if not API_TOKEN:
        print("❌ ОШИБКА: Токен CRYPTO_TOKEN не найден!", flush=True)
        return None

    url = "https://pay.crypt.bot/api/createInvoice"
    
    headers = {
        "Crypto-Pay-API-Token": API_TOKEN,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    payload = {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": str(amount_rub), 
        "payload": custom_payload,
        "description": description
    }
    
    # 👇 ЕСЛИ ПЕРЕДАН КОНКРЕТНЫЙ АССЕТ — ФОРСИРУЕМ ЕГО 👇
    if asset:
        payload["asset"] = asset
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        res = response.json()
        
        if res.get("ok"): 
            return res["result"]["mini_app_invoice_url"]
    except Exception as e: 
        print(f"❌ Ошибка связи с CryptoBot: {e}", flush=True)
        
    return None

from config import (
    VIP_PRICE_STARS, ADMIN_CHAT_IDS, STAFF_GROUP_ID,
    VIP_CHAT_ID, NETWORK_LINKS, all_cities
)
from database import (
    db, users_collection, archive_collection, withdrawals_collection,
    update_user_stats, get_user_stats, get_pending_ref, delete_pending_ref,
    banned_collection
)
from utils import escape_md, get_user_name, get_referral_bonus, net_key_to_name

def analyze_vip_video_speech(bot, file_id, admin_chat_ids):
    """Фоновая задача для распознавания речи из VIP-кружка через Groq API"""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key: return

    temp_video_path = None
    listening_msgs = []
    
    # 1. Отправляем во все админские чаты плашку "Слушаю..." и запоминаем её ID
    for admin_id in admin_chat_ids:
        try:
            msg = bot.send_message(admin_id, "⏳ *Скайнет слушает VIP-кружок...*", parse_mode="Markdown")
            listening_msgs.append((admin_id, msg.message_id))
        except: pass

    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video:
            temp_video.write(downloaded_file)
            temp_video_path = temp_video.name

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {groq_key}"}
        
        with open(temp_video_path, "rb") as audio_file:
            files = {"file": ("video.mp4", audio_file, "video/mp4")}
            data = {"model": "whisper-large-v3", "language": "ru", "response_format": "json"}
            response = requests.post(url, headers=headers, files=files, data=data)

        if response.status_code == 200:
            text = response.json().get("text", "").lower()
            
            # Ищем ключевые слова из фразы: "Привет админам вип-чата, сегодня [дата], на часах [время], хочу стать вип-участником"
            keywords = ["привет", "админ", "вип", "сегодня", "час", "хочу", "стать", "участник"]
            matches = sum(1 for k in keywords if k in text)
            score = int((matches / len(keywords)) * 100)

            if score >= 70:
                verdict = f"✅ **Шаблон подтвержден ({score}%)!** Можете выставлять счет."
            else:
                verdict = f"⚠️ **Совпадение низкое ({score}%). Послушайте вручную.**"

            msg_text = f"🤖 **Нейросеть Скайнета (STT):**\nРаспознанный текст:\n_«{text}»_\n\n{verdict}"
        else:
            msg_text = "⚠️ *Ошибка нейросети.* Проверьте кружок вручную."

        # 2. Заменяем плашку "Слушаю..." на готовый результат ИИ
        for chat_id, msg_id in listening_msgs:
            try: bot.edit_message_text(msg_text, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown")
            except: pass

    except Exception as e:
        print(f"Ошибка при работе STT (VIP): {e}")
    finally:
        if temp_video_path and os.path.exists(temp_video_path):
            try: os.remove(temp_video_path)
            except: pass

# Выносим отдельно, так как эта функция нужна и для команды /start
def send_vip_welcome(bot, chat_id, first_name):
    # 🔥 Достаем динамическую цену из базы Скайнета
    try:
        prices = db['settings'].find_one({"_id": "skynet_pricing"})
        current_vip_price = prices.get("vip_price", VIP_PRICE_STARS) if prices else VIP_PRICE_STARS
    except Exception:
        current_vip_price = VIP_PRICE_STARS

    welcome_text = (
        f"Приветствую, {escape_md(first_name)}! 👋\n\n"
        "Это бот отбора в ВИП-чат, вход после верификации (кружок с лицом) "
        f"и оплаты взноса {current_vip_price}⭐️ единоразово!\n\n"
        "В случае, если вы заблокируете бот и не укажете фразу «Я отказываюсь от продолжения», "
        "вы будете заблокированы во всех сетях-партнерах.\n\n"
        "**ПРЕИМУЩЕСТВА УЧАСТИЯ В ВИП-ЧАТЕ:**\n"
        "1) лояльное отношение администраций сетей-партнеров;\n"
        "2) «золотой билет» - вступление в разные города сети;\n"
        "3) бесплатная публикация объявлений через специальный бот.\n\n"
        "Нажмите кнопку ниже, чтобы начать верификацию:"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Готов пройти верификацию", callback_data="start_verification"))
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="Markdown")

def register_vip_handlers(bot, pending_verification_users, active_vip_requests, safe_from_autoban, ban_user_everywhere, unmute_user_everywhere, unban_user_everywhere):

    @bot.message_handler(func=lambda message: message.text == "👑 Вступить в VIP-чат")
    def handle_vip_join_button(message):
        # 👇 НОВЫЙ ЖУЧОК СКАЙНЕТА 👇
        users_collection.update_one({"_id": message.from_user.id}, {"$set": {"intent_vip": True}}, upsert=True)
        # 👆 ==================== 👆
        send_vip_welcome(bot, message.chat.id, message.from_user.first_name)

    @bot.message_handler(func=lambda message: message.text == "👤 Партнерская программа")
    def show_profile(message):
        user_id = message.from_user.id
        stats = get_user_stats(user_id)
        
        invites = stats['invites']
        balance = stats['balance']
        clicks = stats['clicks']
        
        current_percent, _ = get_referral_bonus(invites + 1)
        ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{user_id}"
        
        text = (
            f"📊 **Твой профиль партнера**\n\n"
            f"👣 Переходов по ссылке: **{clicks}**\n"
            f"👥 Успешных оплат: **{invites}**\n"
            f"💰 Твой баланс: **{balance} звезд**\n"
            f"📈 Текущая ставка: **{int(current_percent * 100)}%**\n\n"
            f"🔗 **Твоя персональная ссылка:**\n`{ref_link}`"
        )
        
        markup = types.InlineKeyboardMarkup()
        if balance > 0:
            markup.add(types.InlineKeyboardButton("💸 Запросить вывод средств", callback_data="request_withdrawal"))
        
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda call: call.data == "request_withdrawal")
    def start_withdrawal(call):
        pending_request = withdrawals_collection.find_one({"user_id": call.from_user.id, "status": "pending"})
        if pending_request:
            bot.answer_callback_query(call.id, "❌ У вас уже есть активная заявка. Дождитесь её обработки!", show_alert=True)
            return

        stats = get_user_stats(call.from_user.id)
        if stats['balance'] <= 0:
            bot.answer_callback_query(call.id, "❌ Ваш баланс пуст", show_alert=True)
            return

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"💰 Ваш баланс: **{stats['balance']} звезд**.\n\nВведите номер карты и название банка для вывода:",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(call.message, process_withdrawal_details, stats['balance'])

    def process_withdrawal_details(message, amount):
        if message.text == "Назад" or len(message.text) < 10:
            bot.send_message(message.chat.id, "❌ Некорректные данные. Попробуйте еще раз через меню профиля.")
            return

        user_info = get_user_name(message.from_user)
        details = message.text

        withdrawal_id = f"w_{int(time.time())}_{message.from_user.id}"
        withdrawals_collection.insert_one({
            "_id": withdrawal_id,
            "user_id": message.from_user.id,
            "amount": amount,
            "details": details,
            "status": "pending"
        })

        bot.send_message(message.chat.id, "✅ Заявка принята! Администратор проверит её в ближайшее время.")

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Оплачено", callback_data=f"wd_pay_{withdrawal_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"wd_reject_{withdrawal_id}")
        )

        bot.send_message(
            STAFF_GROUP_ID,
            f"💸 **НОВАЯ ЗАЯВКА НА ВЫВОД**\n\n"
            f"👤 **От:** {user_info}\n"
            f"💰 **Сумма:** {amount} звезд\n"
            f"💳 **Реквизиты:** `{details}`",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: call.data == "start_verification")
    def ask_for_video(call):
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        
        db['vip_funnel'].update_one(
            {"_id": call.from_user.id},
            {"$set": {"timestamp": time.time(), "reminded": False}},
            upsert=True
        )

        instruction_text = (
            f"{escape_md(call.from_user.first_name)}, запишите видеосообщение (кружок) с лицом и скажите в нем:\n\n"
            "💬 *«Привет админам вип-чата, сегодня [назовите дату], на часах [назовите время], хочу стать вип-участником»*\n\n"
            "Просто отправьте кружок сюда и ожидайте ответа."
        )
        pending_verification_users[call.from_user.id] = True
        bot.send_message(call.message.chat.id, instruction_text, parse_mode="Markdown")

    @bot.message_handler(content_types=['video_note'])
    def handle_video_note(message):
        if message.chat.type != "private": return
        if not pending_verification_users.get(message.from_user.id): return

        db['vip_funnel'].update_one(
            {"_id": message.from_user.id}, 
            {"$set": {"timestamp": time.time(), "reminded": False}}
        )

        active_vip_requests.add(message.from_user.id)
        bot.send_message(message.chat.id, f"⏳ {escape_md(message.from_user.first_name)}, проверяем вашу анкету, подождите...")

        # 👇 ДОСТАЕМ АКТУАЛЬНУЮ ЦЕНУ ИЗ ВЕБ-ПАНЕЛИ
        try:
            prices = db['settings'].find_one({"_id": "skynet_pricing"})
            current_vip_price = prices.get("vip_price", VIP_PRICE_STARS) if prices else VIP_PRICE_STARS
        except Exception:
            current_vip_price = VIP_PRICE_STARS

        # 👇 ДОСТАЕМ ДОСЬЕ ИЗ БАЗ СКАЙНЕТА
        user_id = message.from_user.id
        user_record = archive_collection.find_one({"target": str(user_id)}) or archive_collection.find_one({"target": message.from_user.username})
        skynet_ban = banned_collection.find_one({"_id": user_id})

        dossier_text = "🟢 **История чиста.** Отличный кандидат."
        if user_record and "history" in user_record:
            dossier_text = "⚠️ **Досье пользователя (последние 5 записей):**\n"
            for entry in user_record["history"][-5:]:
                reason = entry.get('reason', 'Не указана')
                if not reason: reason = 'Не указана'
                dossier_text += f"• {entry['date']} — {entry['action']} ({reason})\n"

        if skynet_ban:
            dossier_text += f"\n🚨 **АКТИВНЫЙ БАН В СЕТИ:** {skynet_ban.get('reason', 'Не указана')}"
        # 👆 ================================ 👆

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(f"✅ Одобрить (Счет на {current_vip_price}⭐️)", callback_data=f"vip_approve_{user_id}"),
            types.InlineKeyboardButton("🔄 Запросить повторно", callback_data=f"vip_retry_{user_id}"),
            types.InlineKeyboardButton("❌ Отказать (Нарушения)", callback_data=f"vip_reject_{user_id}"),
            types.InlineKeyboardButton("🔨 Забанить везде", callback_data=f"vip_ban_{user_id}")
        )

        for admin_id in ADMIN_CHAT_IDS:
            try:
                # Отправляем инфу с пришитым досье!
                bot.send_message(admin_id, f"🚨 **Заявка в VIP!**\nОт: {get_user_name(message.from_user)}\nID: `{user_id}`\n\n{dossier_text}", parse_mode="Markdown")
                bot.forward_message(admin_id, message.chat.id, message.message_id)
                bot.send_message(admin_id, "Действие:", reply_markup=markup)
            except: pass
        
        pending_verification_users[user_id] = False

        # 🔥 ЗАПУСКАЕМ НЕЙРОСЕТЬ В ФОНЕ 🔥
        threading.Thread(
            target=analyze_vip_video_speech, 
            args=(bot, message.video_note.file_id, ADMIN_CHAT_IDS)
        ).start()

    @bot.message_handler(func=lambda message: message.text and message.text.strip().lower() in ["я отказываюсь от продолжения", "отказываюсь от продолжения"])
    def handle_refusal(message):
        if message.chat.type != "private": return
        
        user_id = message.from_user.id
        safe_from_autoban.add(user_id)  
        pending_verification_users[user_id] = False 
        db['vip_funnel'].delete_one({"_id": user_id})
        
        bot.send_message(message.chat.id, "✅ Ваша заявка аннулирована. Вы можете безопасно заблокировать бота.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith(("vip_approve_", "vip_retry_", "vip_reject_", "vip_ban_", "vip_forceban_", "vip_cancelban_")))
    def handle_vip_decision(call):
        action, user_id_str = call.data.rsplit("_", 1)
        user_id = int(user_id_str)
        admin_info = get_user_name(call.from_user)

        # 🛡️ 1. Обработка отмены (админ одумался)
        if action == "vip_cancelban":
            try: bot.edit_message_text("✅ Фух! Действие отменено. Платный клиент спасен! 🛡", call.message.chat.id, call.message.message_id)
            except: pass
            return

        # 🛡️ 2. ПРЕДОХРАНИТЕЛЬ ДЛЯ РУЧНОГО БАНА
        if action == "vip_ban":
            user_data = users_collection.find_one({"_id": user_id}) or {}
            is_vip = user_data.get("is_vip", False)
            is_queer = user_data.get("is_queer", False)
            
            if is_vip or is_queer:
                status_name = "🏳️‍🌈 BEYOND" if is_queer else "👑 VIP"
                warn_text = (
                    f"⚠️ **СТОП! СРАБОТАЛА ЗАЩИТА СКАЙНЕТА!** ⚠️\n\n"
                    f"Этот пользователь УЖЕ является премиум-клиентом: **{status_name}**!\n"
                    f"Возможно, он просто перепутал ботов или прислал кружок по ошибке. "
                    f"Блокируя его, вы навсегда выкинете действующего платного клиента из ВСЕХ чатов сети.\n\n"
                    f"**Вы абсолютно уверены?**"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🚨 ДА, СНЕСТИ ЕГО (ПЕРМАЧ)", callback_data=f"vip_forceban_{user_id}"))
                markup.add(types.InlineKeyboardButton("Отмена (Сохранить клиента)", callback_data=f"vip_cancelban_{user_id}"))
                bot.send_message(call.message.chat.id, warn_text, reply_markup=markup, parse_mode="Markdown")
                return

        # 3. Проверка на двойные клики (кроме форсированного бана)
        if action in ["vip_approve", "vip_retry", "vip_reject", "vip_ban"]:
            if user_id not in active_vip_requests:
                bot.answer_callback_query(call.id, "❌ Коллега уже обработал эту заявку!", show_alert=True)
                try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
                except: pass
                return
            active_vip_requests.remove(user_id)
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except: pass

        # 4. Обработка форсированного бана (убираем кнопки у подтверждения)
        if action == "vip_forceban":
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except: pass
            if user_id in active_vip_requests:
                active_vip_requests.remove(user_id)

        # 5. Установка статусов для логов
        status_text = ""
        if "approve" in action: status_text = "✅ Одобрена (счет)"
        elif "retry" in action: status_text = "🔄 Запрошен повтор"
        elif "reject" in action: status_text = "❌ Отклонена"
        elif "ban" in action: status_text = "🔨 Забанен"

        notification_text = f"📢 **Статус заявки изменен**\n👤 Юзер: `{user_id}`\n📝 Итог: {status_text}\n👮‍♂️ Модератор: {admin_info}"
        
        for admin_id in ADMIN_CHAT_IDS:
            if admin_id != call.message.chat.id:
                try: bot.send_message(admin_id, notification_text, parse_mode="Markdown")
                except: pass

        # 6. ИСПОЛНЕНИЕ ПРИГОВОРОВ
        if "approve" in action:
            # 👇 СНАЧАЛА ДОСТАЕМ АКТУАЛЬНУЮ ЦЕНУ 👇
            try:
                prices_db = db['settings'].find_one({"_id": "skynet_pricing"})
                current_vip_price = prices_db.get("vip_price", VIP_PRICE_STARS) if prices_db else VIP_PRICE_STARS
            except:
                current_vip_price = VIP_PRICE_STARS
            # 👆 ================================ 👆

            cheap_stars_text = (
                "💡 **Лайфхак: Как купить звёзды ДЕШЕВЛЕ официального курса?**\n\n"
                "Перед оплатой рекомендуем приобрести звёзды через проверенный сервис. "
                "Это выйдет значительно выгоднее, чем покупать их напрямую через Telegram.\n\n"
                "**Инструкция:**\n"
                "1️⃣ Перейдите по ссылке: https://t.me/Avrrorkastarbot?start=7924963993\n"
                "2️⃣ Нажмите кнопку «⭐️ Купить звезды»\n"
                "3️⃣ Выберите пункт «👤 Себе»\n"
                f"4️⃣ Выберите пакет «⭐️ {current_vip_price} звезд»\n" # <--- Цена подставится автоматически!
                "5️⃣ Оплатите удобным способом\n\n"
                "После покупки возвращайтесь сюда и оплачивайте VIP-доступ счетом ниже! 👇"
            )
            try: bot.send_message(user_id, cheap_stars_text, parse_mode="Markdown", disable_web_page_preview=True)
            except: pass

            try:
                # Генерируем персональные ссылки под каждую монету отдельно
                url_usdt = get_crypto_pay_url(f"vip_{user_id}", current_vip_price, f"Оплата VIP Клуба ({current_vip_price}⭐️)", asset="USDT")
                url_ton = get_crypto_pay_url(f"vip_{user_id}", current_vip_price, f"Оплата VIP Клуба ({current_vip_price}⭐️)", asset="TON")

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("🎫 У меня есть промокод", callback_data=f"checkout_promo_vip_{current_vip_price}"))
                markup.add(types.InlineKeyboardButton(f"⭐️ Оплатить {current_vip_price} Звезд", callback_data=f"checkout_pay_vip_{current_vip_price}"))
                
                # Выводим кнопки крипты
                if url_usdt:
                    markup.add(types.InlineKeyboardButton("🟢 Оплатить через USDT (CryptoBot)", url=url_usdt))
                if url_ton:
                    markup.add(types.InlineKeyboardButton("💎 Оплатить через TON (CryptoBot)", url=url_ton))

                # 👇 ЭКОСИСТЕМА СЕКРЕТАРЯ: Кэшбэк (₽) и Очки (🎰) 👇
                paid_user = db['paid_users'].find_one({"uid": user_id})
                
                rub_balance = paid_user.get("cashback_balance", 0) if paid_user else 0
                points_balance = paid_user.get("bounty_points", 0) if paid_user else 0 
                
                cost_rub = int(current_vip_price * 1.8) # Курс: 1 звезда = 1.8₽
                cost_points = current_vip_price * 5    # Курс: 1 звезда = 5 очков
                
                # 1. Кнопка оплаты РУБЛЯМИ
                if rub_balance >= cost_rub:
                    markup.add(types.InlineKeyboardButton(f"💳 Списать с баланса ({cost_rub}₽)", callback_data=f"vip_eco_rub_{cost_rub}_{current_vip_price}"))
                elif rub_balance > 0:
                    markup.add(types.InlineKeyboardButton(f"💳 Баланса не хватает (Твой: {rub_balance}₽)", callback_data="insufficient_funds_vip"))

                # 2. Кнопка оплаты ОЧКАМИ
                if points_balance >= cost_points:
                    markup.add(types.InlineKeyboardButton(f"🎰 Оплатить очками ({cost_points} очк.)", callback_data=f"vip_eco_pts_{cost_points}_{current_vip_price}"))
                elif points_balance > 0:
                    markup.add(types.InlineKeyboardButton(f"🎰 Очков не хватает (Твои: {points_balance})", callback_data="btn_game_club"))
                # 👆 =================================== 👆

                bot.send_message(
                    user_id, 
                    f"💎 **Оформление VIP-доступа**\n\nСтоимость: **{current_vip_price}⭐️** (Доступ навсегда)\n\nВыберите удобный способ оплаты ниже 👇", 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
                bot.send_message(call.message.chat.id, f"✅ Меню оплаты с раздельным выбором монет отправлено пользователю {user_id}.")
            except Exception as e:
                if "bot was blocked" in str(e).lower() or "forbidden" in str(e).lower():
                    if user_id in safe_from_autoban:
                        bot.send_message(call.message.chat.id, f"ℹ️ Юзер {user_id} заблокировал бота, НО он официально отказался. Бан отменен.")
                        try: safe_from_autoban.remove(user_id)
                        except: pass
                    else:
                        bot.send_message(call.message.chat.id, f"🚨 Юзер {user_id} заблокировал бота БЕЗ отказа! Авто-бан активирован.")
                        ban_user_everywhere(user_id, reason="Блокировка бота при верификации", admin_name="Auto-Defender")
                else:
                    bot.send_message(call.message.chat.id, f"❌ Ошибка отправки счета: {e}")

        elif "retry" in action:
            bot.send_message(call.message.chat.id, f"🔄 Запрос на повторный кружок отправлен пользователю {user_id}.")
            retry_text = "⚠️ **Ваш кружок не принят**\n\nК сожалению, видео не соответствует требованиям.\nПожалуйста, **запишите кружок повторно**, четко сказав:\n💬 *«Привет админам вип-чата, сегодня [назовите дату], на часах [назовите время], хочу стать вип-участником»*"
            try:
                bot.send_message(user_id, retry_text, parse_mode="Markdown")
                pending_verification_users[user_id] = True
            except: bot.send_message(call.message.chat.id, f"❌ Не удалось отправить уведомление.")

        elif "reject" in action:
            bot.send_message(call.message.chat.id, f"❌ Вы отклонили заявку {user_id}.")
            db['vip_funnel'].delete_one({"_id": user_id})
            
            # 🔥 Если юзер был на "втором шансе", возвращаем его в ЧС 🔥
            users_collection.update_one({"_id": user_id}, {"$unset": {"fine_paid_pending_vip": ""}})
            banned_collection.update_one({"_id": user_id}, {"$set": {"reason": "Повторный отказ после оплаты штрафа"}}, upsert=True)
            
            reject_text = (
                "❌ **К сожалению, ваша заявка отклонена из-за нарушений.**\n\n"
                "Уточнить причину ограничений можно у операторов в поддержке: @FAQMKBOT"
            )
            try: bot.send_message(user_id, reject_text, parse_mode="Markdown")
            except: pass

        elif "ban" in action:
            bot.send_message(call.message.chat.id, "🔨 Запускаю процесс бана...")
            db['vip_funnel'].delete_one({"_id": user_id})
            
            # Проверяем, нажал ли админ кнопку подтверждения (forceban)
            is_force = "forceban" in action
            
            # Передаем команду в ядро
            count = ban_user_everywhere(user_id, reason="Не прошел модерацию кружка (бан админом)", admin_name=admin_info, force=is_force)
            
            if count > 0:
                bot.send_message(call.message.chat.id, f"✅ Пользователь забанен в {count} чатах.")
            else:
                bot.send_message(call.message.chat.id, "🛡 Бан отменен встроенной защитой Скайнета (пользователь — VIP).")

    @bot.callback_query_handler(func=lambda call: call.data.startswith(("wd_pay_", "wd_reject_")))
    def handle_withdrawal_admin(call):
        action, _, wd_id = call.data.split("_")
        wd_request = withdrawals_collection.find_one({"_id": wd_id})

        if not wd_request or wd_request['status'] != "pending":
            bot.answer_callback_query(call.id, "Заявка уже обработана")
            return

        user_id = wd_request['user_id']
        amount = wd_request['amount']
        admin_info = get_user_name(call.from_user)

        if action == "pay":
            update_user_stats(user_id, balance_add=-amount)
            withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "paid"}})
            try: bot.send_message(user_id, f"✅ Ваш запрос на вывод {amount} звезд одобрен! Деньги отправлены на ваши реквизиты.")
            except: pass
            bot.edit_message_text(call.message.text + f"\n\n✅ **ОПЛАЧЕНО:** {admin_info}", STAFF_GROUP_ID, call.message.message_id)
            
        elif action == "reject":
            withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "rejected"}})
            try: bot.send_message(user_id, "❌ Ваш запрос на вывод средств был отклонен администрацией.")
            except: pass
            bot.edit_message_text(call.message.text + f"\n\n❌ **ОТКЛОНЕНО:** {admin_info}", STAFF_GROUP_ID, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('buy_city_'))
    def handle_buy_city(call):
        city_name = call.data.split('_', 2)[2]
        CITY_PRICE_STARS = 250
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        bot.send_invoice(call.message.chat.id, title=f"Пропуск: {city_name} 🏙", description=f"Открывает доступ ко всем чатам нашей сети в городе {city_name} навсегда.", invoice_payload=f"city_access_{city_name}", provider_token="", currency="XTR", prices=[types.LabeledPrice(label=f"Доступ к {city_name}", amount=CITY_PRICE_STARS)])

    @bot.callback_query_handler(func=lambda call: call.data.startswith('sec_chance_buy_'))
    def handle_sec_chance_buy(call):
        try: bot.answer_callback_query(call.id)
        except: pass
        amount = int(call.data.split('_')[3])
        bot.send_invoice(
            call.message.chat.id, 
            title="Оплата штрафа 💸", 
            description="Штраф за нарушение правил / срыв верификации. После оплаты запустится процесс проверки.", 
            invoice_payload=f"second_chance_payment_{amount}", 
            provider_token="", currency="XTR", 
            prices=[types.LabeledPrice(label="Штраф", amount=amount)]
        )

    def process_promo_code(message, target_type, original_amount, call_msg):
        try: bot.edit_message_reply_markup(call_msg.chat.id, call_msg.message_id, reply_markup=None)
        except: pass
        
        promo_text = message.text.strip().upper()
        promo_data = db['promocodes'].find_one({"_id": promo_text})
        
        if not promo_data or not promo_data.get("is_active") or promo_data["used_count"] >= promo_data.get("usage_limit", 1) or promo_data.get("target") not in ["all", target_type]:
            bot.send_message(message.chat.id, "❌ Промокод не найден, исчерпан или недействителен. Выставляем полный счет.")
            bot.send_invoice(message.chat.id, title="Вход в VIP Клуб 👑", description="Оплата доступа.", invoice_payload="vip_access_payment", provider_token="", currency="XTR", prices=[types.LabeledPrice(label="VIP Доступ", amount=original_amount)])
            return

        discount = promo_data["value"]
        new_amount = original_amount
        if promo_data["type"] == "percent": new_amount = int(original_amount * (1 - discount / 100))
        elif promo_data["type"] == "fixed": new_amount = original_amount - discount
        if new_amount < 1: new_amount = 1 
            
        db['promocodes'].update_one({"_id": promo_text}, {"$inc": {"used_count": 1}})
        bot.send_message(message.chat.id, f"✅ **Промокод успешно применен!**\nСкидка составила {original_amount - new_amount}⭐️.", parse_mode="Markdown")
        
        # 👇 НОВОЕ: ГЕНЕРИРУЕМ ПОЛНОЕ МЕНЮ ОПЛАТЫ СО СКИДКОЙ 👇
        user_id = message.chat.id
        url_usdt = get_crypto_pay_url(f"vip_{user_id}", new_amount, f"Оплата VIP Клуба ({new_amount}⭐️)", asset="USDT")
        url_ton = get_crypto_pay_url(f"vip_{user_id}", new_amount, f"Оплата VIP Клуба ({new_amount}⭐️)", asset="TON")
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton(f"⭐️ Оплатить {new_amount} Звезд", callback_data=f"checkout_pay_vip_{new_amount}"))
        
        if url_usdt: markup.add(types.InlineKeyboardButton("🟢 Оплатить через USDT (CryptoBot)", url=url_usdt))
        if url_ton: markup.add(types.InlineKeyboardButton("💎 Оплатить через TON (CryptoBot)", url=url_ton))

        paid_user = db['paid_users'].find_one({"uid": user_id})
        rub_balance = paid_user.get("cashback_balance", 0) if paid_user else 0
        points_balance = paid_user.get("bounty_points", 0) if paid_user else 0 
        
        cost_rub = int(new_amount * 1.8)
        cost_points = new_amount * 5
        
        if rub_balance >= cost_rub: markup.add(types.InlineKeyboardButton(f"💳 Списать с баланса ({cost_rub}₽)", callback_data=f"vip_eco_rub_{cost_rub}_{new_amount}"))
        elif rub_balance > 0: markup.add(types.InlineKeyboardButton(f"💳 Баланса не хватает (Твой: {rub_balance}₽)", callback_data="insufficient_funds_vip"))

        if points_balance >= cost_points: markup.add(types.InlineKeyboardButton(f"🎰 Оплатить очками ({cost_points} очк.)", callback_data=f"vip_eco_pts_{cost_points}_{new_amount}"))
        elif points_balance > 0: markup.add(types.InlineKeyboardButton(f"🎰 Очков не хватает (Твои: {points_balance})", callback_data="insufficient_funds_vip"))

        bot.send_message(
            user_id, 
            f"💎 **Оформление VIP-доступа (Со скидкой)**\n\nК оплате: **{new_amount}⭐️**\n\nВыберите удобный способ оплаты ниже 👇", 
            reply_markup=markup, 
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith('checkout_'))
    def handle_checkout(call):
        parts = call.data.split('_')
        action = parts[1] 
        target_type = parts[2] 
        original_amount = int(parts[3])
        
        if action == "pay":
            try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except: pass
            bot.send_invoice(call.message.chat.id, title="Вход в VIP Клуб 👑", description="Оплата доступа.", invoice_payload="vip_access_payment", provider_token="", currency="XTR", prices=[types.LabeledPrice(label="VIP Доступ", amount=original_amount)])
        elif action == "promo":
            msg = bot.send_message(call.message.chat.id, "👇 **Введите ваш промокод ответом на это сообщение:**", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_promo_code, target_type=target_type, original_amount=original_amount, call_msg=call.message)

# ==================== ОПЛАТА VIP ИЗ ЭКОСИСТЕМЫ РУЛЕТКИ ====================
    @bot.callback_query_handler(func=lambda call: call.data.startswith('vip_eco_rub_') or call.data.startswith('vip_eco_pts_'))
    def handle_vip_ecosystem_payment(call):
        bot.answer_callback_query(call.id)
        parts = call.data.split('_')
        
        currency_type = parts[2] # 'rub' или 'pts'
        cost = int(parts[3])
        stars_amount = int(parts[4])
        
        user_id = call.from_user.id
        paid_user = db['paid_users'].find_one({"uid": user_id})
        
        if currency_type == 'pts':
            current_funds = paid_user.get("bounty_points", 0) if paid_user else 0
            update_field = "bounty_points"
            currency_name = "очков"
            revenue_type = "vip_points"
        else:
            current_funds = paid_user.get("cashback_balance", 0) if paid_user else 0
            update_field = "cashback_balance"
            currency_name = "₽"
            revenue_type = "vip_rub_balance"
            
        if current_funds < cost:
            bot.send_message(call.message.chat.id, f"❌ Ошибка транзакции: Недостаточно {currency_name} на счету!")
            return
            
        # 1. Списываем средства
        db['paid_users'].update_one({"uid": user_id}, {"$inc": {update_field: -cost}})
        
        # 2. Пишем в бухгалтерию (в эквиваленте звезд)
        db['daily_revenue'].insert_one({
            "type": revenue_type, 
            "amount": stars_amount, 
            "timestamp": time.time(), 
            "date": datetime.now().strftime("%d.%m.%Y")
        })
        
        # 3. Выдача VIP (Идентично покупке за реальные деньги)
        db['vip_funnel'].delete_one({"_id": user_id})
        
        try:
            users_collection.update_one({"_id": user_id}, {"$set": {"is_vip": True}}, upsert=True)
            unmute_user_everywhere(user_id)
            unban_user_everywhere(user_id)
            users_collection.update_one({"_id": user_id}, {"$unset": {"shame_tag": ""}})
            archive_collection.update_one({"target": str(user_id)}, {"$unset": {"banned_in_support": "", "strikes": ""}})
        except Exception as e: print(f"Ошибка при амнистии: {e}")
            
        bot.send_message(STAFF_GROUP_ID, f"🤑 **ОПЛАТА VIP (ЭКОСИСТЕМА)!**\nЮзер `{user_id}` оплатил доступ за {cost}{currency_name if currency_name == '₽' else ' ' + currency_name}. Ссылку он получил.")
        
        try:
            invite = bot.create_chat_invite_link(VIP_CHAT_ID, member_limit=1)
            bot.send_message(user_id, f"🎉 *Оплата получена! Добро пожаловать в элиту.*\n\n👉 [НАЖМИТЕ СЮДА ДЛЯ ВХОДА В VIP-КЛУБ]({invite.invite_link})", parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            bot.send_message(user_id, "Оплата прошла, но возникла ошибка со ссылкой. Напиши админу!")
            for admin_id in ADMIN_CHAT_IDS: 
                try: bot.send_message(admin_id, f"🚨 Ошибка создания ссылки: {e}")
                except: pass
                
        # Выдаем бонус рефоводу (если есть)
        ref_id = get_pending_ref(user_id)
        if ref_id:
            update_user_stats(ref_id, invites_add=1)
            stats = get_user_stats(ref_id)
            _, bonus_stars = get_referral_bonus(stats['invites'])
            update_user_stats(ref_id, balance_add=bonus_stars)
            try: bot.send_message(ref_id, f"🥳 **Твой друг оплатил VIP!**\nТебе начислено: **{bonus_stars} звезд** ⭐️", parse_mode="Markdown")
            except: pass
            delete_pending_ref(user_id)
            
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass

    @bot.callback_query_handler(func=lambda call: call.data == "insufficient_funds_vip")
    def handle_insufficient_funds_vip(call):
        bot.answer_callback_query(call.id, "На вашем счету не хватает средств для оплаты VIP! 😔 Поиграйте еще в рулетку или используйте Telegram-звезды.", show_alert=True)

    @bot.pre_checkout_query_handler(func=lambda query: query.invoice_payload.startswith("vip_access_payment") or query.invoice_payload.startswith("fine_payment_") or query.invoice_payload.startswith("city_access_") or query.invoice_payload.startswith("second_chance_payment_"))
    def checkout_process(pre_checkout_query):
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    @bot.message_handler(content_types=['successful_payment'])
    def successful_payment(message):
        # 👇 НОВЫЕ ДВЕ СТРОЧКИ 👇
        from config import get_network_data
        chat_ids_mk, chat_ids_parni, chat_ids_ns, chat_ids_rainbow, chat_ids_gayznak, PARNI_CHATS, all_cities, MAIN_CHANNEL_LINK = get_network_data()

        new_user_id = message.from_user.id
        payload = message.successful_payment.invoice_payload
        
        # 👇 ДОБАВЬ ВОТ ЭТУ СТРОЧКУ ПРЯМО СЮДА 👇
        amount = message.successful_payment.total_amount

        if payload.startswith("second_chance_payment_"):
            db['daily_revenue'].insert_one({"type": "fine", "amount": amount, "timestamp": time.time(), "date": datetime.now().strftime("%d.%m.%Y")})
            
            # 1. Снимаем бан ТОЛЬКО В БАЗЕ (Физически в чатах он еще в бане!)
            banned_collection.delete_one({"_id": new_user_id})
            
            # 🔥 ВАЖНО: Даем иммунитет от бота, но не пускаем в чаты! 🔥
            users_collection.update_one({"_id": new_user_id}, {"$set": {"fine_paid_pending_vip": True}})
            
            # 2. Запускаем верификацию! (Эмитируем нажатие кнопки)
            db['vip_funnel'].update_one(
                {"_id": new_user_id},
                {"$set": {"timestamp": time.time(), "reminded": False}},
                upsert=True
            )
            
            instruction_text = (
                f"✅ **Оплата штрафа получена!**\n\n"
                f"Теперь мы можем начать процесс верификации с чистого листа. Запишите видеосообщение (кружок) с лицом и скажите в нем:\n\n"
                "💬 *«Привет админам вип-чата, сегодня [назовите дату], на часах [назовите время], хочу стать вип-участником»*\n\n"
                "Просто отправьте кружок сюда и ожидайте ответа."
            )
            pending_verification_users[new_user_id] = True
            bot.send_message(new_user_id, instruction_text, parse_mode="Markdown")
            
            try: bot.send_message(STAFF_GROUP_ID, f"🤑 **ОПЛАЧЕН ВТОРОЙ ШАНС (ШТРАФ)!**\nЮзер `{new_user_id}` оплатил {amount}⭐️ за разбан. Бот запросил у него кружок.")
            except: pass
            return
        # 👆 ================================= 👆

        if payload.startswith("city_access_"):
            # 👇 НОВАЯ СТРОЧКА: Пишем доход с пропуска 👇
            db['daily_revenue'].insert_one({"type": "city_access", "amount": amount, "timestamp": time.time(), "date": datetime.now().strftime("%d.%m.%Y")})
            purchased_city = payload.replace("city_access_", "")
            users_collection.update_one({"_id": new_user_id}, {"$addToSet": {"purchased_cities": purchased_city}}, upsert=True)
            
            links_text = f"🎉 **Оплата успешно получена!**\n\nВы приобрели доступ к городу **{purchased_city}**.\nВот ваши персональные одноразовые ссылки для входа:\n\n"
            links_generated = 0
            for net_key, groups in all_cities.get(purchased_city, {}).items():
                for group in groups:
                    try:
                        invite = bot.create_chat_invite_link(group['chat_id'], member_limit=1)
                        network_name = net_key_to_name(net_key)
                        links_text += f"🔹 **{network_name}**: [Вступить]({invite.invite_link})\n"
                        links_generated += 1
                    except: pass
            
            if links_generated == 0: links_text += "К сожалению, не удалось сгенерировать ссылки. Обратитесь в поддержку @MK_MensClubSUPPORT."
            else: links_text += "\n⚠️ *Внимание: Ссылки одноразовые! Никому их не передавайте, иначе вы не сможете войти сами.*"

            bot.send_message(new_user_id, links_text, parse_mode="Markdown", disable_web_page_preview=True)
            try: bot.send_message(STAFF_GROUP_ID, f"🤑 **ПРОДАЖА ПРОПУСКА!**\nЮзер `{new_user_id}` купил доступ к городу **{purchased_city}** за 250⭐️.")
            except: pass
            return

        if payload.startswith("fine_payment_"):
            # 👇 НОВАЯ СТРОЧКА: Пишем доход со штрафа 👇
            db['daily_revenue'].insert_one({"type": "fine", "amount": amount, "timestamp": time.time(), "date": datetime.now().strftime("%d.%m.%Y")})
            now = datetime.now(pytz.timezone('Asia/Yekaterinburg'))
            ticket_num = now.strftime("%d%m%Y%H%M%S") + f"-{random.randint(100, 999)}"
            
            db['skynet_tasks'].insert_one({"uid": new_user_id, "action": "fine_unban", "timestamp": now})
            archive_collection.update_one({"target": str(new_user_id)}, {"$push": {"history": {"date": now.strftime("%d.%m.%Y %H:%M"), "action": "Разблокировка (Штраф оплачен)", "reason": "Автоматическое снятие"}}}, upsert=True)
            
            paid_collection = db['paid_users']
            user_data = paid_collection.find_one({"uid": new_user_id})
            if user_data and "thread_id" in user_data:
                thread_id = user_data["thread_id"]
                try: bot.send_message("-1002196190507", f"🤑 **ЮЗЕР ОПЛАТИЛ ШТРАФ!**\nСкайнет получил приказ на разбан. Тикет закрыт: `{ticket_num}`", message_thread_id=thread_id, parse_mode="Markdown")
                except: pass
                try: bot.close_forum_topic("-1002196190507", thread_id)
                except: pass
                
            paid_collection.update_one({"uid": new_user_id}, {"$set": {"status": 0}, "$unset": {"topic_type": ""}})
            
            success_msg = f"✅ **Оплата штрафа успешно получена!**\n\nВаши ограничения сняты автоматически. Уникальный номер: `{ticket_num}`\n\n{NETWORK_LINKS}\n\n*Больше не нарушайте правила!*"
            bot.send_message(new_user_id, success_msg, parse_mode="Markdown", disable_web_page_preview=True)
            return

        # 👇 НОВАЯ СТРОЧКА: Пишем доход с VIP 👇
        db['daily_revenue'].insert_one({"type": "vip", "amount": amount, "timestamp": time.time(), "date": datetime.now().strftime("%d.%m.%Y")})
        
        db['vip_funnel'].delete_one({"_id": new_user_id})

        try:
            users_collection.update_one({"_id": new_user_id}, {"$set": {"is_vip": True}}, upsert=True)
            unmute_user_everywhere(new_user_id)
            unban_user_everywhere(new_user_id)
            users_collection.update_one({"_id": new_user_id}, {"$unset": {"shame_tag": ""}})
            archive_collection.update_one({"target": str(new_user_id)}, {"$unset": {"banned_in_support": "", "strikes": ""}})
        except Exception as e: print(f"Ошибка при амнистии: {e}")

        bot.send_message(STAFF_GROUP_ID, f"🤑 **УСПЕШНАЯ ОПЛАТА VIP!**\nЮзер `{new_user_id}` только что купил доступ навсегда. Ссылку он получил.")
        
        try:
            invite = bot.create_chat_invite_link(VIP_CHAT_ID, member_limit=1)
            bot.send_message(new_user_id, f"🎉 *Оплата получена! Добро пожаловать в элиту.*\n\n👉 [НАЖМИТЕ СЮДА ДЛЯ ВХОДА В VIP-КЛУБ]({invite.invite_link})", parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            bot.send_message(new_user_id, "Оплата прошла, но возникла ошибка со ссылкой. Напиши админу!")
            for admin_id in ADMIN_CHAT_IDS: 
                try: bot.send_message(admin_id, f"🚨 Ошибка создания ссылки: {e}")
                except: pass

        ref_id = get_pending_ref(new_user_id)
        if ref_id:
            update_user_stats(ref_id, invites_add=1)
            stats = get_user_stats(ref_id)
            _, bonus_stars = get_referral_bonus(stats['invites'])
            update_user_stats(ref_id, balance_add=bonus_stars)
            try: bot.send_message(ref_id, f"🥳 **Твой друг оплатил VIP!**\nТебе начислено: **{bonus_stars} звезд** ⭐️", parse_mode="Markdown")
            except: pass
            delete_pending_ref(new_user_id)