import time
import re
import difflib
import threading
from datetime import datetime
import pytz
import random
from telebot import types
import telebot

from config import (
    OWNER_ID, ADMIN_CHAT_IDS, VIP_CHAT_ID, BEYOND_CHAT_ID, PARNI_CHATS,
    all_cities, STAFF_GROUP_ID, SUPPORT_GROUP_ID, JOURNAL_CHAT_ID, # <--- Добавили их сюда
    chat_ids_mk, chat_ids_parni, chat_ids_ns,
    chat_ids_rainbow, chat_ids_gayznak, MAIN_CHANNEL_LINK
)
from database import users_collection, banned_collection, db, archive_collection
from utils import escape_md, get_user_name

# 🔴 Красная зона (Глобал бан)
RED_WORDS = [
    r"\bфен\b",          # Ограничили жестко с двух сторон, чтобы не банил за "телефон" или "феномен"
    r"\bмеф\b", 
    r"\bкристаллы\b", 
    r"\bсоли\b", 
    r"\bстафф\b", 
    r"\bцп\b", 
    r"\bдетское\b",
    
    # 👇 НАШИ НОВЫЕ БРОНЕБОЙНЫЕ ФИЛЬТРЫ 👇
    r"\bмяу\b",          # Сработает ТОЛЬКО на отдельное слово "мяу". "Мяукать" пропустит!
    r"\bне\s*зож\b"      # Ловит "не зож", "незож", "не  зож" (любое количество пробелов между ними)
]

# 🟡 Желтая зона: Коммерция
YELLOW_COMMERCE_REGEX = [
    r'\bмп\b', r'\bм\.п\b', r'\bмат\s*помощь\b', r'\bспонсор\b', 
    r'\bсодержу\b', r'\bкоммерция\b', r'\bвознаграждение\b', r'\bбабки\b',
    
    # 👇 ТВОИ НОВЫЕ ФИЛЬТРЫ 👇
    r'\bпапик[а-я]*\b',             # Ловит: "папик", "папика", "папику" (благодаря [а-я]*)
    r'\bтакси\s+с\s+тебя\b',        # Четкая фраза "такси с тебя" с любым количеством пробелов
    
    # 👇 ПРОФЕССИОНАЛЬНЫЙ СЛЕНГ ПЛАТНЫХ АНКЕТ 👇
    r'\bпрайс\b',                   # "мой прайс", "прайс в лс" — 100% коммерция
    r'\bгонорар[а-я]*\b',           # "за гонорар", "обсудим гонорар"
    r'\bапарт[ыа-я]*\b',            # "апарты", "апартаменты", "выезд/апарты"
    r'\bиндивидуалка[а-я]*\b',      # Без комментариев, сразу в мут
    r'\bуслуги\b',                  # "оказываю услуги", "интим услуги" (рискованное, но в анкетах МК работает четко)
    r'\bвстреч[аи]\s+за\b'          # Ловит "встреча за...", "встречи за..." (обычно там дальше идет "деньги" или "мп")
]

warned_users = {}  # Кэш отбивок подписок (chat_id, user_id) -> message_id

def register_skynet_handlers(bot, ban_user_everywhere, mute_user_everywhere, safe_set_tag, add_radar_log, is_subscribed):
    
    # 👇 🤖 МОДУЛЬ: АВТО-АДМИН ПОДДЕРЖКИ 🤖 👇
    @bot.message_handler(func=lambda message: str(message.chat.id) == str(SUPPORT_GROUP_ID))
    def auto_support_handler(message):
        # 1. Игнорируем сообщения от самих админов (анонимных и обычных)
        if getattr(message, 'sender_chat', None) or message.from_user.id in [777000, 136817688, OWNER_ID]:
            return
            
        try:
            member = bot.get_chat_member(message.chat.id, message.from_user.id)
            if member.status in ['administrator', 'creator']:
                return
        except: pass

        text = (message.text or "").lower()
        response = None

        # 2. База знаний Скайнета (Триггеры и Ответы)
        phrases_verification = [
            "Жду вас в боте @FAQMKBOT для прохождения верификации 🤝",
            "Здравствуйте! Проходите верификацию в боте @FAQMKBOT.",
            "Пишите в бот @FAQMKBOT, там проходит быстрая верификация.",
            "Для верификации перейдите в @FAQMKBOT и нажмите /start"
        ]
        
        phrases_restrictions = [
            "Здравствуйте. Пишите в бот @FAQMKBOT, проверим ваш статус.",
            "Если у вас ограничения, напишите в @FAQMKBOT, мы посмотрим причину.",
            "Все вопросы по мутам и блокировкам решаем через @FAQMKBOT. Напишите туда."
        ]

        # 3. Логика распознавания
        if any(word in text for word in ["верификаци", "вериф", "пройти"]):
            response = random.choice(phrases_verification)
        elif any(word in text for word in [
            # Старые триггеры
            "забанили", "мут", "не могу писать", "запрет", "ограничени", "блок",
            # НОВЫЕ ТРИГГЕРЫ ИЗ ЧАТА ПОДДЕРЖКИ
            "разблок", "снять бан", "получил бан", "бан?", "оплатил", "звезд"
        ]):
            response = random.choice(phrases_restrictions)

        # 4. Имитация живого человека и отправка
        if response:
            # Показываем статус "Печатает..."
            bot.send_chat_action(message.chat.id, 'typing')
            # Ждем 1.5 секунды для реалистичности
            time.sleep(1.5) 
            # Отвечаем конкретно на сообщение юзера (Reply)
            bot.reply_to(message, response)
    # 👆 ========================================= 👆
    
    @bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'location', 'contact', 'video_note'], func=lambda message: message.chat.type in ['group', 'supergroup'])
    def skynet_core_handler(message):
        
        if getattr(message, 'sender_chat', None) or message.from_user.id in [777000, 136817688]:
            return

        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # 👇 ДОБАВЛЯЕМ ЭТОТ БЛОК 👇
        # Игнорируем служебные чаты: Поддержку, Журнал логов и чат Админов
        if str(chat_id) in [str(SUPPORT_GROUP_ID), str(STAFF_GROUP_ID), str(JOURNAL_CHAT_ID)]:
            return
        # 👆 👆 👆
        
        raw_text = message.text or message.caption or ""
        text = raw_text.lower()
        trigger_text = raw_text if raw_text else "Без текста (медиа)"
        user_link = get_user_name(message.from_user)
        chat_title = escape_md(message.chat.title) if message.chat.title else f"Чат {chat_id}"

        try:
            user_data = users_collection.find_one({"_id": user_id}) or {}
            is_vip = user_data.get("is_vip", False)
            is_queer = user_data.get("is_queer", False)
            is_verified = user_data.get("is_verified", False)
            shame_tag = user_data.get("shame_tag")
            custom_tag = user_data.get("custom_tag")

            main_city = user_data.get("main_city")
            if not main_city:
                detected_city = None
                for city_name, networks in all_cities.items():
                    for net, groups in networks.items():
                        if any(g['chat_id'] == chat_id for g in groups):
                            detected_city = city_name
                            break
                    if detected_city: break
                
                if detected_city:
                    users_collection.update_one({"_id": user_id}, {"$set": {"main_city": detected_city}}, upsert=True)
                    main_city = detected_city

            sys_settings = db['settings'].find_one({"_id": "skynet"}) or {"quarantine_active": True, "may_1_active": True}

            try:
                m_vip = bot.get_chat_member(VIP_CHAT_ID, user_id)
                is_physically_there = getattr(m_vip, 'is_member', False) if m_vip.status == 'restricted' else True
                actual_vip = m_vip.status in ['member', 'administrator', 'creator'] or (m_vip.status == 'restricted' and is_physically_there)
                if is_vip != actual_vip:
                    is_vip = actual_vip
                    users_collection.update_one({"_id": user_id}, {"$set": {"is_vip": is_vip}}, upsert=True)
            except: pass

            try:
                m_beyond = bot.get_chat_member(BEYOND_CHAT_ID, user_id)
                is_physically_there_q = getattr(m_beyond, 'is_member', False) if m_beyond.status == 'restricted' else True
                actual_queer = m_beyond.status in ['member', 'administrator', 'creator'] or (m_beyond.status == 'restricted' and is_physically_there_q)
                if is_queer != actual_queer:
                    is_queer = actual_queer
                    users_collection.update_one({"_id": user_id}, {"$set": {"is_queer": is_queer}}, upsert=True)
            except: pass

            try:
                member = bot.get_chat_member(chat_id, user_id)
                current_tag = getattr(member, 'custom_title', None)
                bot_tags = ["𝓟𝓡𝓔𝓜𝓘𝓤𝓜", "𝐐𝐔𝐄𝐄𝐑 ♛", "𝐑𝐄𝐀𝐋/𝐕𝐈𝐏♕", "Верифицирован МК", "Not verified", "РИСК/ВИРТ/ОБМЕН", "автососка", "туалетная соска"]
                if current_tag and current_tag not in bot_tags:
                    users_collection.update_one({"_id": user_id}, {"$set": {"custom_tag": current_tag}}, upsert=True)
                    custom_tag = current_tag 
            except: pass

            final_tag = "Not verified"
            if custom_tag: final_tag = custom_tag
            elif is_vip and is_queer: final_tag = "𝓟𝓡𝓔𝓜𝓘𝓤𝓜"
            elif is_queer: final_tag = "𝐐𝐔𝐄𝐄𝐑 ♛"
            elif is_vip: final_tag = "𝐑𝐄𝐀𝐋/𝐕𝐈𝐏♕"
            elif is_verified: final_tag = "Верифицирован МК"
            elif shame_tag: final_tag = shame_tag

            try: safe_set_tag(chat_id, user_id, final_tag)
            except: pass

            # 👇 🛡️ ИММУНИТЕТ ДЛЯ ОДОБРЕННЫХ СПОНСОРОВ 🛡️ 👇
            if custom_tag == "Спонсор_Одобрен":
                return
            # 👆 ======================================================= 👆

            # === 🤬 СЛОВАРЬ ИНКВИЗИТОРА (ТЯНЕМ ИЗ БАЗЫ) ===
            dict_settings = db['settings'].find_one({"_id": "skynet_dictionary"}) or {}
            live_red = RED_WORDS + [w['pattern'] for w in dict_settings.get('red', [])]
            live_yellow = YELLOW_COMMERCE_REGEX + [w['pattern'] for w in dict_settings.get('yellow', [])]
            # ===============================================

            if any(re.search(word, text) for word in live_red):
                bot.delete_message(chat_id, message.message_id)
                ban_user_everywhere(user_id, reason="Мясорубка: Красная зона", admin_name="Скайнет ⚔️", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
                return

            safe_minor = re.sub(r'\b(1[0-7])\s*(см|cm)\b', '', text)
            minor_patterns = [
                r'\b(мне|я)\s*(1[0-7])\b',                   
                r'\b(мне|я)\s*18\s*-\s*[1-9]\b',             
                r'\b(1[0-7]|18\s*-\s*[1-9])\s*(лет|годик)\b',
                r'\b(1[0-7])\s*[/\\-]\s*1\d{2}\b',           
                r'\b(200[9]|201[0-9])\s*(г\.р\.?|года?\s*рожд\w*)\b', # <--- ИСПРАВЛЕНО! (Только г.р. или год рождения)
                r'\bочень молод(ой|енький)\b'
            ]
            if any(re.search(p, safe_minor) for p in minor_patterns):
                bot.delete_message(chat_id, message.message_id)
                ban_user_everywhere(user_id, reason="Черная зона: Несовершеннолетний (<18)", admin_name="Скайнет 🔞", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
                return

            # 1. Сначала фильтруем коммерцию (для всех, даже для VIP/QUEER)
            clean_commerce = re.sub(r'без\s*м\.?п\.?|не\s*коммерция|без\s*мат(\.?|ериальной)\s*помощи', '', text)
            if any(re.search(pattern, clean_commerce) for pattern in live_yellow):
                bot.delete_message(chat_id, message.message_id)
                mute_user_everywhere(user_id, reason="Желтая зона: Коммерция", admin_name="Скайнет ⚔️", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
                return

            # 2. А ТОЛЬКО ПОТОМ разрешаем VIP/QUEER писать что угодно (кроме коммерции)
            if any([is_vip, is_queer, is_verified, custom_tag]): return 
            if chat_id in PARNI_CHATS: return

            if not is_subscribed(user_id):
                try: bot.delete_message(chat_id, message.message_id)
                except: pass
                key = (chat_id, user_id)
                if key not in warned_users:
                    # === МАГИЯ ТВОЕГО КОНСТРУКТОРА (С ЦВЕТАМИ И ЭМОДЗИ) ===
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    
                    db_buttons = db['settings'].find_one({"_id": "skynet_buttons"})
                    
                    if db_buttons and db_buttons.get("buttons"):
                        for btn in db_buttons["buttons"]:
                            # Базовые параметры (Текст и Ссылка)
                            kwargs = {"text": btn["text"], "url": btn["url"]}
                            
                            # Если выбран цвет (и это не дефолт)
                            if btn.get("style") and btn["style"] != "default":
                                kwargs["style"] = btn["style"]
                                
                            # Если указан ID кастомного эмодзи
                            if btn.get("emoji_id"):
                                kwargs["icon_custom_emoji_id"] = btn["emoji_id"]
                                
                            markup.add(types.InlineKeyboardButton(**kwargs))
                    else:
                        # Если база пустая (страховка)
                        markup.add(types.InlineKeyboardButton(text="Подписаться на МК", url="https://t.me/clubofrm"))
                    # ======================================================

                    sent = bot.send_message(chat_id, "❗ Внимание, чтобы писать в чате вам необходимо подписаться на наш основной канал.\n\nБез подписки на канал ваши сообщения будут удаляться автоматически. Вступая в чат, я подтверждаю совершеннолетие и обязуюсь соблюдать правила, с которыми ознакомлен и согласен.", reply_markup=markup)
                    warned_users[key] = sent.message_id
                    def auto_delete():
                        time.sleep(120)
                        try: bot.delete_message(chat_id, sent.message_id)
                        except: pass
                        if key in warned_users: del warned_users[key]
                    threading.Thread(target=auto_delete, daemon=True).start()
                return

            if len(raw_text) > 30:
                clean_current = re.sub(r'\s+', '', text)
                recent_bans = list(db['blacklisted_texts'].find().sort("_id", -1).limit(30))
                for bad in recent_bans:
                    clean_bad = bad.get("clean_text", "")
                    if not clean_bad: continue
                    similarity = difflib.SequenceMatcher(None, clean_current, clean_bad).ratio()
                    if similarity > 0.85: 
                        try: bot.delete_message(chat_id, message.message_id) 
                        except: pass
                        report = (
                            f"🚨 **РАДАР ТВИНКОВ СРАБОТАЛ!** 🚨\n"
                            f"Юзер {user_link} (`{user_id}`) отправил анкету, которая на **{int(similarity * 100)}%** совпадает с текстом нарушителя `{bad['uid']}`!\n\n"
                            f"📝 **Текст:** _{escape_md(raw_text[:200])}_\n\n"
                            f"🤖 **Действие:** Скайнет тихо удалил сообщение (Shadowban).\nВыдать ему глобальный БАН?"
                        )
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🔨 ЗАБАНИТЬ ВЕЗДЕ", callback_data=f"radar_ban_{user_id}"))
                        try: bot.send_message(STAFF_GROUP_ID, report, parse_mode="Markdown", reply_markup=markup)
                        except: pass
                        return

            # === 🛡 КАРАНТИН НОВОРЕГОВ ===
            if sys_settings.get("quarantine_active", True):
                first_seen = user_data.get('first_seen')
                if not first_seen:
                    first_seen = time.time()
                    users_collection.update_one({"_id": user_id}, {"$set": {"first_seen": first_seen}}, upsert=True)
                seconds_passed = time.time() - first_seen
                if user_id > 7800000000 and seconds_passed < 172800:
                    try: bot.delete_message(chat_id, message.message_id)
                    except: pass
                    try: 
                        bot.send_message(
                            STAFF_GROUP_ID, 
                            f"🥷 **КАРАНТИН:** Удалено сообщение от новорега {user_link} (`{user_id}`).\n"
                            f"📍 Чат: {chat_title}\n"
                            f"🕒 Прошло: {int(seconds_passed // 3600)}ч. из 48ч.",
                            parse_mode="Markdown"
                        )
                    except: pass
                    try:
                        # 📝 ТЯНЕМ ТЕКСТ КАРАНТИНА ИЗ БАЗЫ
                        db_texts = db['settings'].find_one({"_id": "skynet_texts"}) or {}
                        raw_text_quarantine = db_texts.get("quarantine_warn", "🚨 {user_link}, **Защита от спама!**\nВаш аккаунт создан недавно. Для безопасности сети действует карантин 48 часов.\nПодождите, или пройдите верификацию в [Службе Поддержки](https://t.me/MK_MensClubSUPPORT).")
                        
                        warning_msg = bot.send_message(
                            chat_id, 
                            raw_text_quarantine.replace("{user_link}", user_link), 
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                        def delete_quarantine_warning():
                            time.sleep(300) 
                            try: bot.delete_message(chat_id, warning_msg.message_id)
                            except: pass
                        threading.Thread(target=delete_quarantine_warning, daemon=True).start()
                    except: pass
                    return 

            # === 📏 ОПЕРАЦИЯ "1 МАЯ" ===
            if sys_settings.get("may_1_active", True):
                # СПАСИТЕЛЬНЫЙ ФИЛЬТР: ГДЕ НЕ НУЖНЫ ПАРАМЕТРЫ!
                EXCLUDED_FROM_PARAMS = set(PARNI_CHATS)
                EXCLUDED_FROM_PARAMS.update([VIP_CHAT_ID, BEYOND_CHAT_ID])
                EXCLUDED_FROM_PARAMS.update([chat_ids_mk.get("Фетиши"), chat_ids_mk.get("Мужской Чат"), chat_ids_mk.get("Секс Туризм"), chat_ids_mk.get("Аренда Жилья")])

                # 👇 ДОБАВИЛИ ПРОВЕРКУ: КРУЖКИ НЕ МУТИМ ЗА ОТСУТСТВИЕ ТЕКСТА 👇
                if chat_id not in EXCLUDED_FROM_PARAMS and message.content_type != 'video_note':
                    strict_match = re.search(r'(?<!\d)[1-9]\d/1\d{2}/\d{2,3}(?:/\d{1,2}(?:[.,*xхX]\d{1,2})?)?(?!\d)', text)
                    if not strict_match:
                        bot.delete_message(chat_id, message.message_id)
                        mute_user_everywhere(user_id, reason="Нет параметров или неверный формат (1 Мая)", admin_name="Скайнет 📏", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
                        markup = types.InlineKeyboardMarkup(row_width=1)
                        markup.add(
                            types.InlineKeyboardButton("🛠 Пройти верификацию", url="https://t.me/MK_MensClubSUPPORT"),
                            types.InlineKeyboardButton("😈 ПАРНИ 18+ (Без ограничений)", url="https://t.me/znakparni/116")
                        )
                        # 📝 ТЯНЕМ ТЕКСТ "1 МАЯ" ИЗ БАЗЫ
                        db_texts = db['settings'].find_one({"_id": "skynet_texts"}) or {}
                        raw_text_may1 = db_texts.get("may_1_warn", "🚨 {user_link}, **ВНИМАНИЕ!**\n\nС 1 мая введен СТРОГИЙ стандарт оформления анкет для досок объявлений.\nЛюбой текст **БЕЗ ПАРАМЕТРОВ** или с неправильным форматом запрещен!\nПараметры должны быть указаны **ТОЛЬКО через слеш (/) без пробелов и лишних слов**.\n\n✅ *Примеры:* `24/187/72` или `24/187/72/19` (допускается `19.5` или `19*4`)\n\nВаша анкета удалена, а вы временно ограничены в общении во всех группах сети.\n\n💡 *P.S. В нашей сети «ПАРНИ 18+» нет ограничений на формат текста и разрешен любой откровенный контент (включая порно). Переходи туда! 👇*")

                        warning_msg = bot.send_message(
                            chat_id, 
                            raw_text_may1.replace("{user_link}", user_link),
                            reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True
                        )
                        def delete_warning_may():
                            time.sleep(300)
                            try: bot.delete_message(chat_id, warning_msg.message_id)
                            except: pass
                        threading.Thread(target=delete_warning_may, daemon=True).start()
                        return

            safe_age = re.sub(r'(от|парня|мальчика|мужчину|ищу|для)\s*18\b|\b18\s*-\s*\d{2}\b|\b18\s*\+|\b18\s*(см|cm)\b', '', text)
            if re.search(r'\b18\s*(лет|год|годик|y\.?o\.?)\b|\b18\s*[/\\-]\s*1\d{2}\b|\b(мне|я)\s*18\b', safe_age):
                bot.delete_message(chat_id, message.message_id)
                mute_user_everywhere(user_id, reason="Оранжевая зона: 18 лет", admin_name="Скайнет 🔞", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🛠 Пройти верификацию 🔞", url="https://t.me/FAQMKBOT"))
                # 📝 ТЯНЕМ ТЕКСТ 18+ ИЗ БАЗЫ
                db_texts = db['settings'].find_one({"_id": "skynet_texts"}) or {}
                raw_text_minor = db_texts.get("minor_warn", "🚨 {user_link}, **Внимание!**\nВаша анкета попала под автоматический фильтр безопасности сети. Пройдите обязательную верификацию 🔞.")
                
                warning_msg = bot.send_message(chat_id, raw_text_minor.replace("{user_link}", user_link), reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
                def delete_warning_18():
                    time.sleep(300)
                    try: bot.delete_message(chat_id, warning_msg.message_id)
                    except: pass
                threading.Thread(target=delete_warning_18, daemon=True).start()
                return

            new_tag = None
            age_match = re.search(r'\b(?:мне|я)\s*([1-9]\d)\b|\b([1-9]\d)\s*(?:лет|год|годик)\b|\b([1-9]\d)\s*[/\\-]\s*1\d{2}\b', text)
            if age_match:
                found_age = next((int(g) for g in age_match.groups() if g), None)
                if found_age and found_age >= 18: 
                    saved_age = user_data.get("saved_age")
                    if not saved_age: users_collection.update_one({"_id": user_id}, {"$set": {"saved_age": found_age}})
                    elif abs(saved_age - found_age) > 1: new_tag = "Параметры FAKE"

            if not new_tag:
                if "вирт" in text and "не вирт" not in text: new_tag = "РИСК/ВИРТ/ОБМЕН"
                elif any(re.search(fr'\b{word}\b', text) for word in ["вз", "обмен", "слить", "тц"]): new_tag = "туалетная соска" if "тц" in text else "РИСК/ВИРТ/ОБМЕН"
                elif any(word in text for word in ["дроч", "фотками"]): new_tag = "РИСК/ВИРТ/ОБМЕН"
                elif any(word in text for word in ["в машине", "на авто", "на заднем", "тачка", "в тачке"]): new_tag = "автососка"
                elif any(word in text for word in ["туалет", "кабинка", "в кабинке", "глори", "glory"]): new_tag = "туалетная соска"
                elif any(word in text for word in ["нерусск", "кавказ", "восточн", "узбек", "таджик", "дагестан", "чечен", "чурк"]): new_tag = "чернильница"

            if new_tag:
                try: 
                    safe_set_tag(chat_id, user_id, new_tag)
                    users_collection.update_one({"_id": user_id}, {"$set": {"shame_tag": new_tag}}, upsert=True)
                except: pass

        except Exception as e:
            print(f"Ошибка Единого Ядра в модуле Skynet: {e}")