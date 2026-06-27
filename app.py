import os
import sys
import telebot
import requests
from telebot import types
from flask import Flask, request, render_template, session, redirect, url_for, jsonify
from datetime import datetime
from core.settings import SkynetSettings
import pymongo
from pymongo import MongoClient
import pytz
import random
import uuid
import json
import re
import time
import difflib
import threading


# ====================== НОВЫЕ МОДУЛИ ======================
from config import (
    TOKEN, MONGO_URI, ADMIN_CHAT_IDS, OWNER_ID, VIP_PRICE_STARS,
    STAFF_GROUP_ID, JOURNAL_CHAT_ID, SUPPORT_GROUP_ID,
    MAIN_CHANNEL_ID, MAIN_CHANNEL_LINK, NETWORK_LINKS,
    VIP_CHAT_ID, BEYOND_CHAT_ID, NON_CITIES,
    chat_ids_mk, chat_ids_parni, chat_ids_ns, 
    chat_ids_rainbow, chat_ids_gayznak, PARNI_CHATS,
    all_cities, insert_to_all, GROQ_API_KEYS  # <--- ДОБАВИЛИ СЮДА!
)

from database import (
    users_collection, pending_refs_collection, banned_collection,
    posts_collection, archive_collection, temp_posts, proxy_sessions,
    withdrawals_collection, update_user_stats, get_user_stats,
    set_pending_ref, get_pending_ref, delete_pending_ref, db
)

from utils import (
    escape_md, clean_user_text, format_time, get_user_name,
    net_key_to_name, get_referral_bonus
)

from handlers.admin import register_admin_handlers
from handlers.vip import register_vip_handlers, send_vip_welcome
from handlers.posts import register_post_handlers
from handlers.proxy import register_proxy_handlers
from handlers.skynet import register_skynet_handlers

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

app.secret_key = "skynet_secret_eye_2026"
# Секретные данные для входа на твой сайт (можешь поменять на свои!)
WEB_USER = "admin"
WEB_PASS = "mkadmin"

# === 👑 ROOT: КОНСТРУКТОР КНОПОК ===
ROOT_PIN = "6996"  # ⚠️ ПОМЕНЯЙ ЭТОТ ПАРОЛЬ НА СВОЙ СЕКРЕТНЫЙ ПИН-КОД!

# Глобальные переменные
ns_city_substitution = {}
responded = {}
pending_verification_users = {}
active_vip_requests = set()
safe_from_autoban = set()

# 📡 ЖИВОЙ РАДАР (Теперь использует общую базу данных MongoDB)
def add_radar_log(text):
    now = datetime.now(pytz.timezone('Asia/Yekaterinburg')).strftime("%H:%M:%S")
    # Пишем напрямую в матрицу, чтобы все процессы сервера это видели
    db['radar_logs'].insert_one({
        "text": f"[{now}] {text}",
        "ts": time.time()
    })

def is_banned_in_network(user_id):
    """Проверяет статус пользователя в базе Скайнета и в крупных чатах сети"""
    # 1. СНАЧАЛА ПРОВЕРЯЕМ БАЗУ СКАЙНЕТА (Самое надежное)
    if banned_collection.find_one({"_id": user_id}):
        return True

    # 2. ДВОЙНАЯ ПРОВЕРКА ПО ФИЗИЧЕСКИМ ЯКОРЯМ
    anchor_chats = [
        VIP_CHAT_ID,
        chat_ids_mk.get("БЕЗ ПРЕДРАССУДКОВ"), 
        chat_ids_mk.get("Москва"),            
        chat_ids_mk.get("Екатеринбург"),      
        chat_ids_parni.get("Екатеринбург")    
    ]
    anchor_chats = [cid for cid in anchor_chats if cid]
    for chat_id in anchor_chats:
        try:
            member = bot.get_chat_member(chat_id, user_id)
            if member.status == "kicked": return True
        except: pass 
    return False

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("Создать новое объявление"))
    markup.add(types.KeyboardButton("Удалить объявление"), types.KeyboardButton("Удалить все объявления"))
    markup.add(types.KeyboardButton("👑 Вступить в VIP-чат"), types.KeyboardButton("👤 Партнерская программа"))
    # 👇 НОВАЯ КНОПКА САППОРТА 👇
    markup.add(types.KeyboardButton("💬 Написать в Поддержку"))
    return markup

def safe_set_tag(chat_id, user_id, tag):
    """Безопасная выдача тегов без прав админа (обновление Telegram от Марта 2026)"""
    try:
        # Пробуем нативный метод (если библиотека обновлена)
        bot.set_chat_member_tag(chat_id, user_id, tag)
    except AttributeError:
        # Если библиотека старая, бьем напрямую в API Телеграма
        url = f"https://api.telegram.org/bot{TOKEN}/setChatMemberTag"
        requests.post(url, json={"chat_id": chat_id, "user_id": user_id, "tag": tag})

def is_real_vip(user_id: int) -> bool:
    """Надёжная проверка VIP-статуса по живому состоянию в чате"""
    try:
        member = bot.get_chat_member(VIP_CHAT_ID, user_id)
        
        if member.status in ['member', 'administrator', 'creator']:
            return True
            
        if member.status == 'restricted':
            return getattr(member, 'is_member', False)
            
        return False
        
    except telebot.apihelper.ApiTelegramException as e:
        error = str(e).lower()
        if any(phrase in error for phrase in ["user not found", "chat not found", "not a member", "forbidden", "user is not a member"]):
            # Зачищаем "призраков" в базе
            users_collection.update_one(
                {"_id": user_id}, 
                {"$set": {"is_vip": False}}
            )
            return False
        # Для других ошибок API (например, таймаут) — логируем
        print(f"[is_real_vip] Telegram API error for {user_id}: {e}")
        
    except Exception as e:
        print(f"[is_real_vip] Unexpected error for {user_id}: {e}")
    
    # Fallback — только если Telegram полностью недоступен
    user_data = users_collection.find_one({"_id": user_id}) or {}
    return bool(user_data.get("is_vip", False))

# ==================== МОДУЛЬ 2: УМНАЯ ТАМОЖНЯ + СТАТИСТИКА ====================
@bot.chat_join_request_handler()
def handle_join_requests(message: telebot.types.ChatJoinRequest):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # 👇 1. СИСТЕМА УЧЕТА CPA ТРАФИКА (ПЕРЕХВАТ ССЫЛКИ + АНТИФРОД) 👇
    if message.invite_link and message.invite_link.name and message.invite_link.name.startswith("cpa_"):
        agent_id = int(message.invite_link.name.split("_")[1])
        
        # Ищем, был ли этот юзер когда-либо в нашей базе
        existing_traffic = db['cpa_traffic'].find_one({"new_user_id": user_id})
        
        if not existing_traffic:
            # ✅ ЮЗЕР УНИКАЛЬНЫЙ!
            db['cpa_traffic'].insert_one({
                "new_user_id": user_id,
                "agent_id": agent_id, 
                "status": "hold", 
                "join_time": time.time(), 
                "chat_id": chat_id
            })
            
            # Радуем Агента быстрым дофамином
            try:
                bot.send_message(
                    agent_id, 
                    f"👀 **У вас новый реферал!**\nПользователь подал заявку по вашей ссылке.\n⏳ _Скайнет поместил его в карантин. Если он выживет 48 часов, вы получите 15 очков!_",
                    parse_mode="Markdown"
                )
            except: pass
        else:
            # ❌ ЮЗЕР УЖЕ ЕСТЬ В СЕТИ (Или зашел по ссылке другого агента ранее)
            # Просто тихо плюсуем счетчик "Дубликаты", чтобы агент видел клики, но не получал спам в ЛС
            db['paid_users'].update_one({"uid": agent_id}, {"$inc": {"cpa_duplicates": 1}}, upsert=True)
    # 👆 ============================================================= 👆
    
    # 1. ФИКСИРУЕМ ЗАЯВКУ В СТАТИСТИКЕ (Строго 1 раз за весь период!)
    req_id = f"{user_id}_{chat_id}"
    
    # Ищем, стучался ли он уже в этот чат в текущем периоде
    if not db['period_joins'].find_one({"_id": req_id}):
        db['period_joins'].insert_one({"_id": req_id}) # Запоминаем его стук
        
        # Плюсуем счетчик заявок!
        db['network_stats'].update_one(
            {"_id": "current_period"}, 
            {"$inc": {"total": 1, f"chats.{chat_id}.total": 1}}, 
            upsert=True
        )
    
    try:
        # --- ФАЗА -1: Проверка Глобального Черного Списка ---
        if is_banned_in_network(user_id):
            bot.decline_chat_join_request(chat_id, user_id)
            try:
                bot.send_message(
                    user_id, 
                    "🚫 **Доступ заблокирован за грубые нарушения.**\n\n"
                    "Ваш аккаунт находится в глобальном черном списке сети. "
                    "Разблокировка возможна только после оплаты официального штрафа.\n\n"
                    "📍 Обратитесь в поддержку для уточнения суммы и получения ссылки на оплату: @MK_MensClubSUPPORT",
                    parse_mode="Markdown"
                )
            except: pass
            return

        # --- 🕊️ ЛОКАЛЬНАЯ АМНИСТИЯ ПАРНИ (Размут ТОЛЬКО в 18+) ---
        if chat_id in PARNI_CHATS:
            user_data = users_collection.find_one({"_id": user_id}) or {}
            last_reason = user_data.get("last_mute_reason", "")
            
            # Проверяем, был ли мут именно за параметры
            if any(word in last_reason for word in ["1 Мая", "параметр"]):
                # РАЗМУЧИВАЕМ ТОЛЬКО В ЭТОЙ СЕТИ
                count = unmute_in_parni_only(user_id)
                
                # Очищаем причину, чтобы не срабатывало повторно
                users_collection.update_one({"_id": user_id}, {"$unset": {"last_mute_reason": ""}})
                
                # Сообщаем админам о частичной свободе
                try: 
                    bot.send_message(STAFF_GROUP_ID, f"🕊️ **ЛОКАЛЬНАЯ АМНИСТИЯ:** Юзер `{user_id}` размучен ТОЛЬКО в сети ПАРНИ 18+ ({count} чатов). В остальных сетях ограничения сохраняются до верификации.")
                except: pass

        # --- ФАЗА 0: Санитарный контроль (БИО) ---
        settings = SkynetSettings.get()
        if settings.get("bio_hardcheck", True):
            user_info = bot.get_chat(user_id)
            bio = user_info.bio.lower() if user_info.bio else ""
            
            allowed_links = ["anonquebot", "secretmessagebot", "askbot", "contactme", "voprosy"]
            has_bad_link = ("t.me/" in bio or "http" in bio) and not any(allowed in bio for allowed in allowed_links)
            
            # Убираем маску параметров из БИО, чтобы "15" (размер) не считалось за 15 лет
            safe_bio = re.sub(r'(?<!\d)[1-9]\d/1\d{2}/\d{2,3}(?:/\d{1,2}(?:[.,*xхX]\d{1,2})?)?(?!\d)', '', bio)
            safe_bio = re.sub(r'\b(1[0-7])\s*(см|cm)\b', '', safe_bio)
            
            minor_bio_patterns = [
                r'\b(мне|я)\s*(1[0-7])\b',                   
                r'\b(мне|я)\s*18\s*-\s*[1-9]\b',             
                r'\b(1[0-7]|18\s*-\s*[1-9])\s*(лет|годик)\b',
                r'\b(1[0-7])\s*[/\\-]\s*1\d{2}\b',           
                r'\b(200[9]|201[0-9])\s*(г|год|года|г\.р)\b',
                r'\bочень молод(ой|енький)\b'
            ]
            has_bad_age = any(re.search(p, safe_bio) for p in minor_bio_patterns)
            
            if has_bad_age:
                bot.decline_chat_join_request(chat_id, user_id)
                bot.send_message(STAFF_GROUP_ID, f"🚨 **СКАЙНЕТ: ТАМОЖНЯ**\nОтклонена заявка от малолетки (`{user_id}`).\nЗапускаю глобальный БАН...")
                ban_user_everywhere(user_id, reason="Возраст <18 (или 'очень молодой') в БИО", admin_name="Скайнет 🛂")
                return

            if has_bad_link:
                bot.approve_chat_join_request(chat_id, user_id) 
                db['network_stats'].update_one({"_id": "current_period"}, {"$inc": {"approved": 1, f"chats.{chat_id}.approved": 1}}, upsert=True)
                bot.send_message(STAFF_GROUP_ID, f"⚠️ **СКАЙНЕТ: ТАМОЖНЯ**\nПустил спамера со ссылкой в БИО (`{user_id}`) для массовки.\nЗатыкаю рот глобальным МУТОМ 🤐...")
                mute_user_everywhere(user_id, reason="Рекламная ссылка в БИО", admin_name="Скайнет 🛂")
                return

        # --- ФАЗА 1: Режим БОГА (VIP и BEYOND) ---
        user_data = users_collection.find_one({"_id": user_id}) or {}
        # Проверяем сначала базу (вдруг он только что оплатил, но еще не зашел)
        is_privileged = user_data.get("is_vip", False) or user_data.get("is_queer", False)
        
        # Если в базе нет, на всякий случай проверяем физическое наличие в чате
        if not is_privileged:
            for priv_chat in [VIP_CHAT_ID, BEYOND_CHAT_ID]:
                try:
                    member = bot.get_chat_member(priv_chat, user_id)
                    is_physically_there = getattr(member, 'is_member', False) if member.status == 'restricted' else True
                    if member.status in ['member', 'administrator', 'creator'] or (member.status == 'restricted' and is_physically_there):
                        is_privileged = True
                        break 
                except: pass
        
        if is_privileged:
            bot.approve_chat_join_request(chat_id, user_id)
            # Считаем в общую статку + в счетчик Золотых билетов
            db['network_stats'].update_one(
                {"_id": "current_period"}, 
                {"$inc": {"approved": 1, "vip_tickets": 1, f"chats.{chat_id}.approved": 1}}, 
                upsert=True
            )
            return

        # --- ФАЗА 2: Биг-чаты (Открытые котлы) ---
        big_chats = [
            chat_ids_mk.get("БЕЗ ПРЕДРАССУДКОВ"),
            chat_ids_mk.get("Секс Туризм"),
            chat_ids_mk.get("Галерея"),
            chat_ids_mk.get("Мужской Чат"),
            chat_ids_mk.get("Фетиши"),  # <--- ВОТ ЗДЕСЬ НУЖНА ЗАПЯТАЯ!
            chat_ids_mk.get("Аренда Жилья")
        ]
        if chat_id in big_chats:
            bot.approve_chat_join_request(chat_id, user_id)
            db['network_stats'].update_one({"_id": "current_period"}, {"$inc": {"approved": 1, f"chats.{chat_id}.approved": 1}}, upsert=True)
            return

        # --- ФАЗА 3: Гео-контроль (Единый город + Метод первой двери + Монетизация) ---
        possible_cities = []
        for city_name, networks in all_cities.items():
            for net, groups in networks.items():
                if any(g['chat_id'] == chat_id for g in groups):
                    possible_cities.append(city_name)
        
        if possible_cities:
            user_data = users_collection.find_one({"_id": user_id}) or {}
            main_city = user_data.get("main_city")
            purchased_cities = user_data.get("purchased_cities", [])

            # Берем первый город для системных сообщений/пейвола (по умолчанию)
            primary_target_city = possible_cities[0]

            if main_city:
                # 📍 СЦЕНАРИЙ А: Юзер уже привязан к городу
                # Пускаем, если его родной город ИЛИ купленный город есть в списке допустимых для этого чата
                if main_city in possible_cities or any(c in purchased_cities for c in possible_cities):
                    bot.approve_chat_join_request(chat_id, user_id)
                    db['network_stats'].update_one({"_id": "current_period"}, {"$inc": {"approved": 1, f"chats.{chat_id}.approved": 1}}, upsert=True)
                    return
                else:
                    # Чужой город! Отклоняем моментально + Кидаем Оффер
                    bot.decline_chat_join_request(chat_id, user_id)
                    
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(
                        types.InlineKeyboardButton(f"🎟 Купить пропуск в г. {primary_target_city} (250⭐️)", callback_data=f"buy_city_{primary_target_city}"),
                        types.InlineKeyboardButton("👑 Купить VIP (Все города)", callback_data="start_verification")
                    )
                    try:
                        bot.send_message(
                            user_id, 
                            f"❌ Ваша заявка в чат **{primary_target_city}** отклонена.\n\n"
                            f"По правилам сети за вами закреплен город: **{main_city}**.\n\n"
                            f"Вы можете приобрести разовый пропуск, либо стать VIP-участником для неограниченного доступа везде.",
                            reply_markup=markup,
                            parse_mode="Markdown"
                        )
                    except: pass
                    return
            else:
                # 📍 СЦЕНАРИЙ Б: Метод «Первой двери» для новичков
                users_collection.update_one({"_id": user_id}, {"$set": {"main_city": primary_target_city}}, upsert=True)
                
                bot.approve_chat_join_request(chat_id, user_id)
                db['network_stats'].update_one({"_id": "current_period"}, {"$inc": {"approved": 1, f"chats.{chat_id}.approved": 1}}, upsert=True)
                return

    except Exception as e:
        print(f"Ошибка Таможни: {e}")

@bot.message_handler(commands=['start'])
def start(message):
    try:
        if message.chat.type != "private":
            bot.send_message(message.chat.id, "Пожалуйста, используйте ЛС для работы с ботом.")
            return

        # --- СТАТИСТИКА: ЗАПИСЫВАЕМ НОВОГО ЮЗЕРА В БАЗУ ---
        users_collection.update_one({"_id": message.from_user.id}, {"$set": {"active": True}}, upsert=True)
        # -------------------------------------------------

        # --- ЖЕСТКИЙ ФЕЙСКОНТРОЛЬ ---
        if is_banned_in_network(message.from_user.id):
            try:
                from config import VIP_PRICE_STARS
                prices = db['settings'].find_one({"_id": "skynet_pricing"})
                current_vip_price = prices.get("vip_price", VIP_PRICE_STARS) if prices else VIP_PRICE_STARS
            except Exception:
                current_vip_price = 250
                
            ban_doc = banned_collection.find_one({"_id": message.from_user.id}) or {}
            reason = ban_doc.get("reason", "").lower()
            
            strict_triggers = ["красн", "желт", "черн", "коммерц", "наркот", "цп", "несовершеннолет", "эскорт", "мп"]
            is_strict = any(t in reason for t in strict_triggers)
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("🆘 Обратиться в Поддержку", url="https://t.me/FAQMKBOT"))
            
            if not is_strict:
                markup.add(types.InlineKeyboardButton(f"💸 Оплатить штраф ({current_vip_price}⭐️)", callback_data=f"sec_chance_buy_{current_vip_price}"))
                text = (
                    "🚫 **Доступ закрыт.**\n"
                    "Вы находитесь в черном списке нашей сети и заблокированы в основных чатах.\n\n"
                    "Так как ваше нарушение не относится к категории строгих, вы можете воспользоваться правом на **«Второй шанс»** — оплатить штраф за срыв прошлой верификации или поведение, после чего процесс получения VIP-статуса начнется заново."
                )
            else:
                text = (
                    "🚫 **Доступ закрыт.**\n"
                    "Вы находитесь в черном списке нашей сети за грубое нарушение правил.\n"
                    "Апелляция и снятие ограничений возможны только через Службу Поддержки."
                )

            bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")
            return # Выбрасываем из функции, меню не покажется!
        # ----------------------------

        # 1. Ловим реферальную ссылку (t.me/bot?start=ref_12345)
        start_params = message.text.split()
        is_referral = False
        if len(start_params) > 1 and start_params[1].startswith('ref_'):
            ref_id = int(start_params[1].replace('ref_', ''))
            
            # Проверяем, не переходил ли он уже по ссылке ранее (защита от накрутки)
            existing_ref = pending_refs_collection.find_one({"_id": message.from_user.id})
            
            if ref_id != message.from_user.id and not existing_ref:
                # ПИШЕМ КЛИК В БАЗУ!
                set_pending_ref(message.from_user.id, ref_id)
                update_user_stats(ref_id, clicks_add=1)
                is_referral = True
                try: 
                    bot.send_message(ref_id, "🔔 По вашей ссылке перешел новый человек! Ждем его оплату.") 
                except: 
                    pass
            elif existing_ref:
                # Человек уже кликал ссылку, просто запускаем приветствие без спама
                is_referral = True 

        # 2. Выдаем меню
        bot.send_message(
            message.chat.id,
            f"Привет, {escape_md(message.from_user.first_name)}! Я ElitePoster. 👋\n\n"
            "Здесь ты можешь опубликовать объявление в наших сетях-партнерах, "
            "а также подать заявку в закрытый VIP-клуб.\n\n"
            "Выберите действие в меню ниже:",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )

        # 3. Если пришел от друга — сразу запускаем приветствие VIP
        if is_referral:
            send_vip_welcome(bot, message.chat.id, message.from_user.first_name)

    except Exception as e:
        for admin_id in ADMIN_CHAT_IDS:
            try: bot.send_message(admin_id, f"Ошибка в /start: {e}")
            except: pass

def ban_user_everywhere(target_id, reason="Без причины", admin_name="Система", user_link=None, trigger_text=None, origin_chat=None, force=False):
    # 👇 ТОТАЛЬНАЯ ЗАЩИТА ЭЛИТЫ (ПРЕДОХРАНИТЕЛЬ ЯДРА) 👇
    if not force:
        user_data = users_collection.find_one({"_id": target_id}) or {}
        
        # --- УЗКАЯ ЗАЩИТА СПОНСОРОВ (ТОЛЬКО ОТ МП) ---
        is_sponsor = user_data.get("custom_tag") == "Спонсор_Одобрен"
        if is_sponsor:
            # Слова-маркеры в причине или самом тексте, которые прощаются Спонсорам
            safe_sponsor_triggers = ["мп", "спонсор", "содержан", "вознагражден", "коммерц", "деньги", "плачу", "щедр"]
            reason_and_text = (str(reason) + " " + str(trigger_text)).lower()
            
            # Если в причине бана или тексте юзера есть слова о коммерции — СПАСАЕМ!
            if any(word in reason_and_text for word in safe_sponsor_triggers):
                try: bot.send_message(STAFF_GROUP_ID, f"💎 **СПОНСОРСКИЙ ИММУНИТЕТ:** Юзер `{target_id}` написал про МП, но он официальный Спонсор! Бан отменен.", parse_mode="Markdown")
                except: pass
                add_radar_log(f"💎 ИММУНИТЕТ МП: {target_id} спасен от бана")
                return 0
        # ---------------------------------------------
        
        # ЗАЩИТА VIP И QUEER (ОТ ВСЕГО)
        if user_data.get("is_vip", False) or user_data.get("is_queer", False):
            status_name = "🏳️‍🌈 BEYOND" if user_data.get("is_queer") else "👑 VIP"
            who_tried = admin_name if admin_name else "Система"
            
            alert_text = (
                f"🛡 **СКАЙНЕТ: БЛОКИРОВКА БАНА!** 🛡\n\n"
                f"Попытка забанить пользователя `{target_id}`.\n"
                f"**Инициатор:** {who_tried}\n"
                f"**Причина:** {reason}\n\n"
                f"❌ Действие отменено, так как это действующий {status_name}!\n\n"
                f"👉 *Если вы действительно хотите уничтожить этого клиента, сначала снимите с него VIP-статус в Веб-Панели, а затем баньте.*"
            )
            try: bot.send_message(STAFF_GROUP_ID, alert_text, parse_mode="Markdown")
            except: pass
            
            add_radar_log(f"🛡 ЗАЩИТА ОТ БАНА: {target_id} спасен от {who_tried}")
            return 0 # Прерываем функцию, 0 чатов забанено
    # 👆 ================================================ 👆

    # === СБРАСЫВАЕМ VIP-СТАТУС И ТЕГИ ПРИ БАНЕ ===
    users_collection.update_one({"_id": target_id}, {"$set": {"is_vip": False}, "$unset": {"custom_tag": ""}})
    # ============================================

    banned_collection.update_one({"_id": target_id}, {"$set": {"reason": reason}}, upsert=True)
   
    chats_to_ban = {VIP_CHAT_ID: "VIP Клуб"}
    for city, cid in chat_ids_parni.items(): chats_to_ban[cid] = f"ПАРНИ 18+ | {city}"
    for city, cid in chat_ids_mk.items(): chats_to_ban[cid] = f"МК | {city}"
    for city, cid in chat_ids_ns.items(): chats_to_ban[cid] = f"НС | {city}"
    for city, cid in chat_ids_rainbow.items(): chats_to_ban[cid] = f"Радуга | {city}"
    for city, cid in chat_ids_gayznak.items(): chats_to_ban[cid] = f"Гей Знакомства | {city}"
                
    banned_in = []
    for cid, name in chats_to_ban.items():
        try:
            # === СТИРАЕМ ЮЗЕРА ИЗ РЕАЛЬНОСТИ (Удаляем все его сообщения) ===
            bot.ban_chat_member(cid, target_id, revoke_messages=True)
            
            # 🔥 Выжигаем все его реакции (до 10 000 шт) по новому API Телеграма
            try: bot.delete_all_message_reactions(chat_id=cid, user_id=target_id)
            except: pass
            # ===============================================================
            banned_in.append(f"🔸 {name}")
        except: pass
            
    who_is_it = user_link if user_link else f"[{target_id}](tg://user?id={target_id})"
    
    # БАЗОВЫЙ ТЕКСТ ОТЧЕТА
    base_text = (
        f"🚫 **#BAN**\n"
        f"• **Кто наказал:** {admin_name}\n"
        f"• **Кому:** {who_is_it} (ID: `{target_id}`)\n"
        f"• **Причина:** {reason}\n"
    )
    # === ДОБАВЛЯЕМ ИНФОРМАЦИЮ О ЧАТЕ ===
    if origin_chat:
        base_text += f"• **Где попался:** {origin_chat}\n"
    
    if trigger_text and trigger_text != "Без текста (медиа)":
        base_text += f"• **Улика:** _{escape_md(trigger_text[:300])}_\n"
        # Запоминаем для Радара (если текст длиннее 30 символов)
        if len(trigger_text) > 30:
            clean_for_radar = re.sub(r'\s+', '', trigger_text.lower())
            db['blacklisted_texts'].insert_one({
                "uid": target_id,
                "clean_text": clean_for_radar,
                "timestamp": time.time()
            })
        
    # ДВА РАЗНЫХ СООБЩЕНИЯ ДЛЯ РАЗНЫХ ЧАТОВ
    journal_text = base_text + f"• **Группы:** ({len(banned_in)} шт.)\n" + "\n".join(banned_in)
    staff_text = base_text + f"• **Забанен в группах:** {len(banned_in)} шт."
    
    # Отправляем простыню в журнал
    try: bot.send_message(JOURNAL_CHAT_ID, journal_text, parse_mode="Markdown")
    except: pass
    
    # Отправляем короткую сводку в рабочий чат
    try: bot.send_message(STAFF_GROUP_ID, staff_text, parse_mode="Markdown")
    except: pass
    
    # === ПИШЕМ ИСТОРИЮ В АРХИВ ДЛЯ СЕКРЕТАРЯ ===
    now_str = datetime.now(pytz.timezone('Asia/Yekaterinburg')).strftime("%d.%m.%Y %H:%M")
    archive_collection.update_one(
        {"target": str(target_id)}, 
        {"$push": {"history": {"date": now_str, "action": "Глобальный БАН (Скайнет)", "reason": reason}}},
        upsert=True
    )
    # ===========================================
    
    return len(banned_in)
    
    # 📡 ОТПРАВЛЯЕМ СИГНАЛ В WEB-РАДАР
    add_radar_log(f"💥 БАН ({admin_name}): {target_id} | {reason}")
    
    return len(banned_in)

# ==================== 📩 СИСТЕМА ТИКЕТОВ (САППОРТ) ====================
@bot.message_handler(func=lambda message: message.text == "💬 Написать в Поддержку" and message.chat.type == "private")
def support_request_handler(message):
    
    # === ПРОВЕРКА НА VIP И QUEER (BEYOND) ===
    user_id = message.from_user.id
    user_data = users_collection.find_one({"_id": user_id}) or {}
    
    # Если юзер не VIP и не QUEER — отказываем и отправляем в FAQ
    if not user_data.get("is_vip", False) and not user_data.get("is_queer", False):
        bot.send_message(
            message.chat.id, 
            "⚠️ **Служба поддержки недоступна**\n\n"
            "Поддержка в этом боте доступна только участникам закрытых VIP и BEYOND чатов.\n\n"
            "По общим вопросам, проблемам с верификацией или разблокировке обращайтесь в нашего сервисного бота: @FAQMKBOT",
            parse_mode="Markdown"
        )
        return # ⛔️ Важно! Прерываем выполнение, чтобы капкан не включился
    # ========================================

    # 👇 НОВЫЙ ЖУЧОК СКАЙНЕТА 👇
    users_collection.update_one({"_id": user_id}, {"$set": {"intent_support": True}}, upsert=True)
    # 👆 ==================== 👆

    # 1. Просим юзера написать проблему (он прошел проверку)
    msg = bot.send_message(
        message.chat.id, 
        "📝 **VIP Служба поддержки**\n\nНапишите ваш вопрос, жалобу или предложение *одним сообщением* ниже. Мы ответим вам прямо в этом чате.", 
        parse_mode="Markdown"
    )
    # 2. Включаем "капкан": ловим только следующее сообщение от этого юзера!
    bot.register_next_step_handler(msg, process_support_msg)

def process_support_msg(message):
    # 3. Защита от дурака: если юзер передумал и нажал другую кнопку меню
    if message.text in ["💬 Написать в Поддержку", "/start", "Создать новое объявление", "👑 Вступить в VIP-чат"]:
        bot.send_message(message.chat.id, "Отмена отправки сообщения в поддержку. Выберите действие в меню 👇", reply_markup=get_main_keyboard())
        return
        
    text = message.text or message.caption or "[Медиафайл / Без текста]"
    
    # 4. Сохраняем вопрос юзера в новую базу данных (Ящик Входящих)
    db['support_tickets'].insert_one({
        "uid": message.from_user.id,
        "name": message.from_user.first_name,
        "username": message.from_user.username,
        "text": text,
        "timestamp": time.time(),
        "is_read": False,    # Метка для вебки: прочитано админом или нет
        "is_answered": False # Метка для вебки: ответили или нет
    })
    
    # 5. Сигналим на твой Радар
    add_radar_log(f"📩 НОВЫЙ ТИКЕТ: Вопрос от {message.from_user.id}")
    
    # 6. Успокаиваем юзера
    bot.send_message(message.chat.id, "✅ Ваше сообщение успешно доставлено Администрации! Ожидайте ответа, мы напишем вам сюда.")
# ======================================================================

def background_corpse_removal(dead_uid):
    """Медленно и аккуратно выносит труп из всех чатов сети, чтобы не словить Flood Wait"""
    # Собираем все чаты Империи в один список
    all_empire_chats = []
    if isinstance(PARNI_CHATS, list): all_empire_chats.extend(PARNI_CHATS)
    if isinstance(chat_ids_mk, dict): all_empire_chats.extend(chat_ids_mk.values())
    if isinstance(chat_ids_parni, dict): all_empire_chats.extend(chat_ids_parni.values())
    all_empire_chats.extend([VIP_CHAT_ID, BEYOND_CHAT_ID])
    
    # Убираем дубликаты
    all_empire_chats = list(set(all_empire_chats))
    
    for chat in all_empire_chats:
        try:
            # ban + revoke_messages=True: Вышвыриваем и сжигаем ВСЕ его сообщения в этом чате! 🔥
            bot.ban_chat_member(chat, dead_uid, revoke_messages=True)
            # unban: Сразу снимаем системный блок, чтобы не засорять черный список группы
            bot.unban_chat_member(chat, dead_uid)
        except: pass
        time.sleep(0.3)  # Пауза, чтобы Телеграм не счел это спамом

def unmute_user_everywhere(target_id):
    """Снимает мут с пользователя абсолютно во всех чатах сети"""
    # 1. Собираем базовые чаты (для всех)
    all_chats = []
    all_chats.extend(chat_ids_parni.values())
    all_chats.extend(chat_ids_mk.values())
    all_chats.extend(chat_ids_ns.values())
    all_chats.extend(chat_ids_rainbow.values())
    all_chats.extend(chat_ids_gayznak.values())
    
    # --- УМНЫЙ РАЗМУТ (ТОЛЬКО ДЛЯ СВОИХ) ---
    user_data = users_collection.find_one({"_id": target_id}) or {}
    
    # Добавляем VIP-чат только если юзер реально VIP
    if user_data.get("is_vip", False):
        all_chats.append(VIP_CHAT_ID)
        
    # Добавляем BEYOND-чат только если юзер реально QUEER
    if user_data.get("is_queer", False):
        all_chats.append(BEYOND_CHAT_ID)
    # ---------------------------------------
    
    unmuted_count = 0
    for cid in all_chats:
        try:
            bot.restrict_chat_member(
                cid, target_id,
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
            unmuted_count += 1
        except:
            pass
            
    # === ПИШЕМ ИСТОРИЮ В АРХИВ ДЛЯ СЕКРЕТАРЯ ===
    now_str = datetime.now(pytz.timezone('Asia/Yekaterinburg')).strftime("%d.%m.%Y %H:%M")
    archive_collection.update_one(
        {"target": str(target_id)}, 
        {"$push": {"history": {"date": now_str, "action": "Глобальный РАЗМУТ (Скайнет)", "reason": "Амнистия / Снятие ограничений"}}},
        upsert=True
    )
    # ===========================================
            
    return unmuted_count

def unmute_in_parni_only(target_id):
    """Снимает мут ТОЛЬКО в чатах сети ПАРНИ 18+"""
    success_count = 0
    for cid in PARNI_CHATS:
        try:
            bot.restrict_chat_member(
                cid, target_id,
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
            success_count += 1
        except:
            pass
    return success_count

def unban_user_everywhere(target_id):
    """Снимает глобальный бан с пользователя во всех чатах сети"""
    # 1. Удаляем метку бана из памяти Скайнета
    banned_collection.delete_one({"_id": target_id})
    
    # 2. Собираем все чаты
    all_chats = [VIP_CHAT_ID, BEYOND_CHAT_ID]
    all_chats.extend(chat_ids_parni.values())
    all_chats.extend(chat_ids_mk.values())
    all_chats.extend(chat_ids_ns.values())
    all_chats.extend(chat_ids_rainbow.values())
    all_chats.extend(chat_ids_gayznak.values())
    
    unbanned_count = 0
    for cid in all_chats:
        try:
            # only_if_banned=True - важно, чтобы бот просто вычеркнул из ЧС, а не кикнул случайно
            bot.unban_chat_member(cid, target_id, only_if_banned=True)
            unbanned_count += 1
        except:
            pass
            
    # === ПИШЕМ ИСТОРИЮ В АРХИВ ДЛЯ СЕКРЕТАРЯ ===
    now_str = datetime.now(pytz.timezone('Asia/Yekaterinburg')).strftime("%d.%m.%Y %H:%M")
    archive_collection.update_one(
        {"target": str(target_id)}, 
        {"$push": {"history": {"date": now_str, "action": "Глобальный РАЗБАН (Скайнет)", "reason": "Амнистия / Снятие ограничений"}}},
        upsert=True
    )
    # ===========================================
            
    return unbanned_count

# --- ФУНКЦИЯ: ГЛОБАЛЬНЫЙ МУТ (ДЛЯ РЕКЛАМЩИКОВ И НАРУШИТЕЛЕЙ) ---
def mute_user_everywhere(target_id, reason="Без причины", admin_name="Система", user_link=None, trigger_text=None, mute_time=0, origin_chat=None):
    
    # 👇 МАГИЯ ЩИТА ИММУНИТЕТА (ЗАЩИТА ОТ АВТО-МУТОВ) 👇
    user_data = users_collection.find_one({"_id": target_id}) or {}
    
    # --- УЗКАЯ ЗАЩИТА СПОНСОРОВ (ТОЛЬКО ОТ МП) ---
    is_sponsor = user_data.get("custom_tag") == "Спонсор_Одобрен"
    if is_sponsor:
        safe_sponsor_triggers = ["мп", "спонсор", "содержан", "вознагражден", "коммерц", "деньги", "плачу", "щедр"]
        reason_and_text = (str(reason) + " " + str(trigger_text)).lower()
        
        if any(word in reason_and_text for word in safe_sponsor_triggers):
            try: bot.send_message(STAFF_GROUP_ID, f"💎 **СПОНСОРСКИЙ ИММУНИТЕТ:** Юзер `{target_id}` написал про МП, но он официальный Спонсор! Мут отменен.", parse_mode="Markdown")
            except: pass
            add_radar_log(f"💎 ИММУНИТЕТ МП: {target_id} спасен от мута")
            return 0
    # ---------------------------------------------
    
    # Достаем данные юзера из базы для проверки одноразовых щитов
    user_paid_data = db['paid_users'].find_one({"uid": target_id}) or {}
    
    if user_paid_data.get("immunity", 0) > 0:
        # 1. Списываем один щит
        db['paid_users'].update_one({"uid": target_id}, {"$inc": {"immunity": -1}})
        
        # 2. Пишем в веб-радар
        add_radar_log(f"🛡 ЩИТ СРАБОТАЛ: {target_id} спасен от мута ({reason})")
        
        # 3. Пишем юзеру в ЛС, что он чудом спасся
        try:
            bot.send_message(
                target_id, 
                f"⛔️ **Скайнет зафиксировал нарушение!**\nПричина: {reason}\n\n"
                f"Но ваш **🛡 Щит Иммунитета поглотил удар!** Вы избежали глобального мута.\n"
                f"_Щит разрушен. Будьте осторожны в следующий раз!_",
                parse_mode="Markdown"
            )
        except: pass
        
        # 4. Уведомляем админов
        try:
            bot.send_message(STAFF_GROUP_ID, f"🛡 **БРОНЯ ПРОБИТА:** Скайнет пытался выдать мут `{target_id}` за ({reason}), но **Щит Иммунитета** поглотил удар!", parse_mode="Markdown")
        except: pass
        
        # 5. ПРЕРЫВАЕМ ФУНКЦИЮ! Мут не выдается (возвращаем 0).
        return 0
    # 👆 ======================================================== 👆

    # --- СОХРАНЯЕМ ПРИЧИНУ ДЛЯ АМНИСТИИ В ПАРНЯХ ---
    users_collection.update_one({"_id": target_id}, {"$set": {"last_mute_reason": reason}}, upsert=True)
    chats_to_mute = {}
    for city, cid in chat_ids_parni.items(): chats_to_mute[cid] = f"ПАРНИ 18+ | {city}"
    for city, cid in chat_ids_mk.items(): chats_to_mute[cid] = f"МК | {city}"
    for city, cid in chat_ids_ns.items(): chats_to_mute[cid] = f"НС | {city}"
    for city, cid in chat_ids_rainbow.items(): chats_to_mute[cid] = f"Радуга | {city}"
    for city, cid in chat_ids_gayznak.items(): chats_to_mute[cid] = f"Гей Знакомства | {city}"
                
    muted_in = []
    for cid, name in chats_to_mute.items():
        try:
            bot.restrict_chat_member(cid, target_id, until_date=mute_time, can_send_messages=False)
            muted_in.append(f"🔸 {name}")
        except: pass
            
    who_is_it = user_link if user_link else f"[{target_id}](tg://user?id={target_id})"
    
    # БАЗОВЫЙ ТЕКСТ ОТЧЕТА
    base_text = (
        f"🤐 **#MUTE (Глобальный)**\n"
        f"• **Кто наказал:** {admin_name}\n"
        f"• **Кому:** {who_is_it} (ID: `{target_id}`)\n"
        f"• **Причина:** {reason}\n"
    )
    # === ДОБАВЛЯЕМ ИНФОРМАЦИЮ О ЧАТЕ ===
    if origin_chat:
        base_text += f"• **Где попался:** {origin_chat}\n"
        
    if trigger_text and trigger_text != "Без текста (медиа)":
        base_text += f"• **Улика:** _{escape_md(trigger_text[:300])}_\n"
        # Запоминаем для Радара (если текст длиннее 30 символов)
        if len(trigger_text) > 30:
            clean_for_radar = re.sub(r'\s+', '', trigger_text.lower())
            db['blacklisted_texts'].insert_one({
                "uid": target_id,
                "clean_text": clean_for_radar,
                "timestamp": time.time()
            })
        
    # ДВА РАЗНЫХ СООБЩЕНИЯ ДЛЯ РАЗНЫХ ЧАТОВ
    journal_text = base_text + f"• **Группы:** ({len(muted_in)} шт.)\n" + "\n".join(muted_in)
    staff_text = base_text + f"• **Замучен в группах:** {len(muted_in)} шт."
    
    # Отправляем простыню в журнал
    try: bot.send_message(JOURNAL_CHAT_ID, journal_text, parse_mode="Markdown")
    except: pass
    
    # Отправляем короткую сводку в рабочий чат
    try: bot.send_message(STAFF_GROUP_ID, staff_text, parse_mode="Markdown")
    except: pass
    
    # === ПИШЕМ ИСТОРИЮ В АРХИВ ДЛЯ СЕКРЕТАРЯ ===
    now_str = datetime.now(pytz.timezone('Asia/Yekaterinburg')).strftime("%d.%m.%Y %H:%M")
    archive_collection.update_one(
        {"target": str(target_id)}, 
        {"$push": {"history": {"date": now_str, "action": "Глобальный МУТ (Скайнет)", "reason": reason}}},
        upsert=True
    )
    # ===========================================
    
    # 📡 ОТПРАВЛЯЕМ СИГНАЛ В WEB-РАДАР
    add_radar_log(f"🤐 МУТ ({admin_name}): {target_id} | {reason}")
    
    return len(muted_in)

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"Ошибка при проверке подписки для {user_id}: {e}")
        return False

# === АКТИВАЦИЯ ВНЕШНИХ ХЭНДЛЕРОВ ===
register_admin_handlers(
    bot, 
    ban_user_everywhere, 
    mute_user_everywhere, 
    unban_user_everywhere, 
    unmute_user_everywhere, 
    unmute_in_parni_only
)

register_vip_handlers(
    bot,
    pending_verification_users,
    active_vip_requests,
    safe_from_autoban,
    ban_user_everywhere,
    unmute_user_everywhere,
    unban_user_everywhere
)

register_post_handlers(bot, is_banned_in_network, get_main_keyboard, is_real_vip)
register_proxy_handlers(bot, ban_user_everywhere)
register_skynet_handlers(bot, ban_user_everywhere, mute_user_everywhere, safe_set_tag, add_radar_log, is_subscribed)

from web.support import register_support_routes
from web.finance import register_finance_routes
from web.routes import register_main_routes
from web.ads import register_ads_routes

# --- МГНОВЕННЫЙ РАДАР БЛОКИРОВОК (Ловит ТОЛЬКО беглецов из VIP-воронки) ---
@bot.my_chat_member_handler()
def catch_bot_block(message):
    # 🎛️ ПРОВЕРЯЕМ ТУМБЛЕР С САЙТА
    settings = SkynetSettings.get()
    if not settings.get("autoban_on_block", True):
        return  # Если выключен — игнорируем блокировки бота, никого не баним!

    if message.chat.type == "private":
        new_status = message.new_chat_member.status
        if new_status == "kicked": 
            # В приватных чатах chat.id — это 100% ID самого пользователя
            user_id = message.chat.id
            
            # =================================================================
            # 🛡️ ФАЗА 1: ЖЕЛЕЗОБЕТОННАЯ ЗАЩИТА СВОИХ (VIP & BEYOND ИММУНИТЕТ)
            # =================================================================
            
            # А) Сначала проверяем по нашей базе данных (самый надежный способ)
            user_data = users_collection.find_one({"_id": user_id}) or {}
            if user_data.get("is_vip", False) or user_data.get("is_queer", False):
                return  # Своих не трогаем, пусть блокируют бота сколько влезет
                
            # Б) На всякий случай проверяем живое присутствие в VIP-чате
            try:
                m_vip = bot.get_chat_member(VIP_CHAT_ID, user_id)
                if m_vip.status in ["member", "administrator", "creator"]:
                    return
                if m_vip.status == 'restricted' and getattr(m_vip, 'is_member', False):
                    return
            except: pass
            
            # В) И живое присутствие в чате BEYOND (QUEER)
            try:
                m_beyond = bot.get_chat_member(BEYOND_CHAT_ID, user_id)
                if m_beyond.status in ["member", "administrator", "creator"]:
                    return
                if m_beyond.status == 'restricted' and getattr(m_beyond, 'is_member', False):
                    return
            except: pass
            
            # =================================================================

            # 2. ПРОВЕРКА: ИММУНИТЕТ (Официальный отказ)
            if user_id in safe_from_autoban:
                try: safe_from_autoban.remove(user_id)
                except: pass
                return
                
            # 3. ПРОВЕРКА НА БЕГЛЕЦА: Он был в воронке отбора?
            is_in_funnel = db['vip_funnel'].find_one({"_id": user_id})
            is_pending = pending_verification_users.get(user_id, False)
            
            if is_in_funnel or is_pending:
                # Ага! Нажал кнопку верификации и сбежал в блок! ЛИКВИДИРОВАТЬ!
                try:
                    bot.send_message(STAFF_GROUP_ID, f"⚡️ **РАДАР СРАБОТАЛ** ⚡️\nТрус `{user_id}` попытался сбежать с верификации и заблокировал бота! Запускаю ликвидацию...")
                except: pass
                
                ban_user_everywhere(user_id, reason="Сбежал с верификации и заблокировал бота", admin_name="Auto-Radar ⚡️")
                
                # Зачищаем следы в воронке
                db['vip_funnel'].delete_one({"_id": user_id})
                pending_verification_users[user_id] = False
            else:
                # Это обычный обыватель. Просто заблокировал бота. Пусть живет мирно 🕊
                pass

# ==================== ПЕРЕХВАТЧИК "МЕРТВЫХ ДУШ" (Защита от старых заявок + Амнистия + Теги) ====================
@bot.message_handler(content_types=['new_chat_members'])
def catch_illegal_entry(message):
    for new_user in message.new_chat_members:
        user_id = new_user.id
        chat_id = message.chat.id
        
        # 1. Проверяем, есть ли он в черном списке Скайнета
        banned_info = banned_collection.find_one({"_id": user_id})
        
        if banned_info:
            # 2. Мгновенно баним обратно
            try:
                bot.ban_chat_member(chat_id, user_id, revoke_messages=True)
            except:
                pass
            
            # 3. Отчет в Staff-чат
            user_link = f"[{escape_md(new_user.first_name)}](tg://user?id={user_id})"
            chat_title = escape_md(message.chat.title) if message.chat.title else str(chat_id)
            
            report = (
                f"🚨 **ПЕРЕХВАТ ПРОНИКНОВЕНИЯ!**\n"
                f"Кто-то одобрил старую заявку забаненного юзера {user_link} (`{user_id}`).\n"
                f"📍 **Где:** {chat_title}\n"
                f"🤖 Скайнет мгновенно вернул его в бан! 🛡"
            )
            try: bot.send_message(STAFF_GROUP_ID, report, parse_mode="Markdown")
            except: pass
            return # Если юзер в бане, дальше не идем

        # 👇 НОВЫЙ БЛОК: АВТО-ВОССТАНОВЛЕНИЕ ТЕГОВ 👇
        user_data = users_collection.find_one({"_id": user_id}) or {}
        saved_tag = user_data.get("custom_tag")
        
        if saved_tag:
            try:
                # Надеваем бейджик обратно при входе!
                safe_set_tag(chat_id, user_id, saved_tag)
            except Exception as e:
                print(f"Не удалось восстановить тег '{saved_tag}' для {user_id}: {e}")
        # 👆 ========================================== 👆

        # --- 🕊️ ЛОКАЛЬНАЯ АМНИСТИЯ ПАРНИ (Для тех, кто вошел сам или одобрен вручную) ---
        if chat_id in PARNI_CHATS:
            last_reason = user_data.get("last_mute_reason", "")
            
            # Если мут был за параметры (1 Мая)
            if any(word in last_reason for word in ["1 Мая", "параметр"]):
                # РАЗМУЧИВАЕМ ТОЛЬКО В СЕТИ ПАРНИ
                count = unmute_in_parni_only(user_id)
                
                # Очищаем причину, чтобы не срабатывало повторно
                users_collection.update_one({"_id": user_id}, {"$unset": {"last_mute_reason": ""}})
                
                # Отчет админам
                try: 
                    bot.send_message(STAFF_GROUP_ID, f"🕊️ **АМНИСТИЯ (Вход):** Юзер `{user_id}` вошел в сеть ПАРНИ 18+ и был автоматически размучен ({count} чатов).")
                except: pass
# ===========================================================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("radar_ban_"))
def radar_confirm_ban(call):
    target_id = int(call.data.split("_")[2])
    admin_info = get_user_name(call.from_user)
    
    # Меняем текст сообщения, чтобы другие админы не нажали повторно
    try: bot.edit_message_text(call.message.text + f"\n\n✅ **ЗАБАНЕН АДМИНОМ:** {admin_info}", call.message.chat.id, call.message.message_id)
    except: pass
    
    # Казним!
    bot.send_message(call.message.chat.id, "🚀 Запускаю массовый бан твинка...")
    count = ban_user_everywhere(target_id, reason="Радар Твинков (Клон забаненной анкеты)", admin_name=admin_info)
    bot.send_message(call.message.chat.id, f"✅ Твинк уничтожен в {count} чатах.")

# ==================== VIP СНАЙПЕР (Фоновая задача) ====================
def vip_funnel_sniper():
    while True:
        try:
            settings = SkynetSettings.get()
            if settings.get("vip_sniper", True):
                now = time.time()
                
                for doc in db['vip_funnel'].find():
                    user_id = doc['_id']
                    
                    # 👇 ЗАЩИТА ОТ ДРУЖЕСТВЕННОГО ОГНЯ (ДЛЯ ДЕЙСТВУЮЩИХ ВИПОВ) 👇
                    user_data = users_collection.find_one({"_id": user_id}) or {}
                    if user_data.get("is_vip", False) or user_data.get("is_queer", False):
                        # Юзер УЖЕ вип! Он случайно нажал кнопку верификации.
                        # Просто тихо удаляем его из воронки и не баним.
                        db['vip_funnel'].delete_one({"_id": user_id})
                        continue
                    # 👆 ========================================================= 👆

                    timestamp = doc.get('timestamp', now)
                    reminded = doc.get('reminded', False)
                    
                    # 1. Напоминание через неделю
                    if not reminded and (now - timestamp > 604800):
                        reminder_text = (
                            "⚠️ **Системное уведомление!**\n\n"
                            "Вы начали процесс вступления в VIP, но остановились. "
                            "Если вы не завершите верификацию или оплату, ваша заявка будет аннулирована.\n\n"
                            "Ждем ваших действий! ⏱"
                        )
                        try:
                            bot.send_message(user_id, reminder_text, parse_mode="Markdown")
                        except:
                            pass
                        
                        db['vip_funnel'].update_one(
                            {"_id": user_id}, 
                            {"$set": {"reminded": True, "timestamp": now}}
                        )
                    
                    # 2. Бан через 3 дня после напоминания
                    elif reminded and (now - timestamp > 259200):
                        ban_user_everywhere(user_id, reason="Не оплатил ВИП, тянул время", admin_name="Скайнет ⏱")
                        db['vip_funnel'].delete_one({"_id": user_id})
                        
        except Exception as e:
            print(f"Ошибка Снайпера: {e}")
            
        time.sleep(43200)

# 👇 УМНАЯ ПРОВЕРКА КОНТЕКСТА ЧЕРЕЗ ИИ 👇
def ai_context_checker(text, zone="black"):
    if not GROQ_API_KEYS or not text:
        return True # Если нет ключей или текста, верим Андрюшеньке на слово

    if zone == "black":
        prompt = f"""Ты модератор. Сообщение: "{text}"
1. Автор СЕЙЧАС младше 18 лет?
2. Ищет интим с несовершеннолетними?
(Жалобы, прошлое или размеры - НЕ нарушение). Ответь СТРОГО: BAN или SKIP."""
    elif zone == "orange":
        prompt = f"""Ты модератор. Сообщение: "{text}"
Автору СЕЙЧАС от 18 до 21 года?
(Размеры "20 см" или поиск "ищу 20 летнего" - НЕ нарушение). Ответь СТРОГО: BAN или SKIP."""
    elif zone == "yellow":
        prompt = f"""Ты строгий модератор. Прочитай это сообщение из чата: "{text}"
Определи, нарушает ли автор правила сети (коммерция и эскорт):
Ищет или предлагает ли автор интим за деньги, материальную помощь (МП), подарки за встречи, спонсорство или платные услуги эскорта?
ВНИМАНИЕ: Если человек просто говорит про подарки на день рождения, праздники, обычные бытовые ситуации, работу, ИЛИ просто ищет/предлагает МАССАЖ без упоминания денег и цен — это БЕЗОПАСНО (SKIP). Наказывай ТОЛЬКО если есть явный финансовый подтекст (цена, прайс, покупка, продажа, МП).
Ответь СТРОГО: BAN или SKIP."""
    else:
        return True

    import requests
    for key in GROQ_API_KEYS:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 10},
                timeout=5
            )
            if resp.status_code == 200:
                return "BAN" in resp.json()["choices"][0]["message"]["content"].strip().upper()
        except: continue
    return True
# 👆 ===================================== 👆

# ==================== СЛУШАТЕЛЬ СЕКРЕТАРЯ (РАЗБАН ПО КНОПКЕ) ====================
def skynet_listener():
    while True:
        try:
            # Ищем невыполненные приказы в базе
            tasks = db['skynet_tasks'].find({"status": {"$ne": "done"}})
            for task in tasks:
                if task['action'] in ["full_unban", "fine_unban"]:
                    target_uid = task['uid']
                    
                    # 1. Снимаем бан и мут везде
                    unbanned = unban_user_everywhere(target_uid)
                    unmuted = unmute_user_everywhere(target_uid)
                    
                    # 2. ВЫДАЕМ ИММУНИТЕТ ИЛИ ПРОСТО ЧИСТИМ ТЕГ
                    if task['action'] == "full_unban":
                        # Если это чистая верификация — выдаем официальный статус и тег!
                        users_collection.update_one(
                            {"_id": target_uid}, 
                            {"$set": {"is_verified": True, "custom_tag": "Верифицирован МК"}, "$unset": {"shame_tag": ""}},
                            upsert=True
                        )
                    
                    elif task['action'] == "fine_unban":
                        # 🔥 АБСОЛЮТНО БРОНЕБОЙНАЯ ЛОГИКА ШТРАХОВ И ТЕГОВ 🔥
                        # Пытаемся достать сумму из задачи или ищем последний платеж в fine_payments
                        amount = task.get('amount') or task.get('price')
                        if not amount:
                            last_pay = db['fine_payments'].find_one({"uid": target_uid}, sort=[("timestamp", -1)])
                            amount = last_pay.get('amount', 0) if last_pay else 0
                        
                        if int(amount) == 650:
                            # Особый случай: покупка свободного тега за 650 звезд
                            users_collection.update_one(
                                {"_id": target_uid}, 
                                {"$set": {"custom_tag": "Свободен"}, "$unset": {"shame_tag": ""}},
                                upsert=True
                            )
                            add_radar_log(f"🎖️ Юзер {target_uid} оплатил 650⭐️ и получил тег 'Свободен'")
                            
                        elif int(amount) == 750:
                            # 🔥 НОВЫЙ КЕЙС: Покупка статуса Спонсора за 750 звезд 🔥
                            users_collection.update_one(
                                {"_id": target_uid}, 
                                {"$set": {"custom_tag": "Спонсор_Одобрен"}, "$unset": {"shame_tag": ""}},
                                upsert=True
                            )
                            add_radar_log(f"💎 Юзер {target_uid} оплатил 750⭐️ и получил тег 'Спонсор_Одобрен'")
                            
                        else:
                            # Обычный штраф: принудительно выжигаем custom_tag (none) и shame_tag
                            users_collection.update_one(
                                {"_id": target_uid}, 
                                {"$unset": {"shame_tag": "", "custom_tag": ""}}
                            )
                            add_radar_log(f"🧹 Юзер {target_uid} оплатил обычный штраф ({amount}⭐️), теги сброшены")
                    
                    # 3. ОТЧЕТ В ФЛУДИЛКУ АДМИНАМ!
                    if task['action'] == "fine_unban":
                        report_text = f"💸 **Скайнет (Автоматика):**\nЮзер `{target_uid}` оплатил штраф!\nОграничения сняты. Глобально разбанен ({unbanned} чатов) и размучен ({unmuted} чатов)."
                    else:
                        report_text = f"✅ **Скайнет (Автоматика):**\nЮзер `{target_uid}` прошел ручную верификацию Секретарем!\nГлобально разбанен ({unbanned} чатов) и размучен ({unmuted} чатов)."
                    
                    try: bot.send_message(STAFF_GROUP_ID, report_text, parse_mode="Markdown")
                    except: pass
                    
                    # 4. Закрываем задачу
                    db['skynet_tasks'].update_one({"_id": task['_id']}, {"$set": {"status": "done"}})
                
                # 👇 ИСПОЛНЕНИЕ ПРИКАЗОВ ОТ ШПИОНА (С ДВОЙНОЙ ПРОВЕРКОЙ ИИ) 👇
                elif task['action'] in ["global_ban", "global_mute"]:
                    trigger_text = task.get('trigger_text', '')
                    reason = task.get('reason', 'Шпионаж')
                    
                    # 🔥 СУДЬЯ СКАЙНЕТ ПРОВЕРЯЕТ УЛИКИ АНДРЮШЕНЬКИ 🔥
                    is_guilty = True
                    if trigger_text:
                        reason_lower = reason.lower() # Приводим к нижнему регистру для надежности!
                        if "черная зона" in reason_lower:
                            is_guilty = ai_context_checker(trigger_text, zone="black")
                        elif "оранжевая зона" in reason_lower:
                            is_guilty = ai_context_checker(trigger_text, zone="orange")
                        elif "желтая зона" in reason_lower:
                            is_guilty = ai_context_checker(trigger_text, zone="yellow")

                    if is_guilty:
                        # ИИ подтвердил вину -> Наказываем!
                        if task['action'] == "global_ban":
                            ban_user_everywhere(
                                target_id=int(task['uid']), 
                                reason=reason, 
                                admin_name="Андрюшенька (Спецагент Шпион) 🕵️‍♂️", 
                                trigger_text=trigger_text, 
                                origin_chat=escape_md(task.get('origin_chat', ''))
                            )
                        else:
                            mute_user_everywhere(
                                target_id=int(task['uid']), 
                                reason=reason, 
                                admin_name="Андрюшенька (Спецагент Шпион) 🕵️‍♂️",  
                                trigger_text=trigger_text, 
                                origin_chat=escape_md(task.get('origin_chat', ''))
                            )
                    else:
                        # 🛡 ИИ ОПРАВДАЛ ЮЗЕРА! Ордер аннулирован.
                        print(f"🛡 СКАЙНЕТ ОТМЕНИЛ АРЕСТ! Андрюшенька ошибся. Улика: {trigger_text}")

                    # В любом случае закрываем задачу, чтобы не зациклилась
                    db['skynet_tasks'].update_one({"_id": task['_id']}, {"$set": {"status": "done"}})

        except Exception as e:
            print(f"Ошибка слушателя: {e}")
            
        time.sleep(3) # Проверяем приказы каждые 3 секунды

# === ЗАПУСКАЕМ ФОНОВЫЕ ПРОЦЕССЫ ЗДЕСЬ (КОГДА ПИТОН УЖЕ ЗНАЕТ ВСЕ ФУНКЦИИ) ===
threading.Thread(target=vip_funnel_sniper, daemon=True).start()
threading.Thread(target=skynet_listener, daemon=True).start()
# ============================================================================

# ==================== ДЕМОН CPA-СЕТИ (БУХГАЛТЕР) ====================
def cpa_tracker_daemon():
    while True:
        try:
            now = time.time()
            # 172800 секунд = 48 часов. 
            # (💡 Для тестов можешь поставить 60 секунд, чтобы проверить сразу)
            HOLD_TIME = 172800 
            
            # Ищем всех, кто висит в заморозке
            pending_traffic = db['cpa_traffic'].find({"status": "hold"})
            
            for record in pending_traffic:
                if now - record['join_time'] > HOLD_TIME:
                    new_user_id = record['new_user_id']
                    agent_id = record['agent_id']
                    
                    # Проверяем, не убил ли Скайнет этого новичка за спам?
                    is_banned = banned_collection.find_one({"_id": new_user_id})
                    
                    if is_banned:
                        # Трафик оказался спамером. Забраковано!
                        db['cpa_traffic'].update_one({"_id": record['_id']}, {"$set": {"status": "fraud"}})
                    else:
                        # Трафик ВЫЖИЛ! Одобряем и платим Агенту
                        db['cpa_traffic'].update_one({"_id": record['_id']}, {"$set": {"status": "approved"}})
                        
                        # 1. Начисляем базовые 15 очков + 1 в счетчик рефералов
                        paid_collection = db['paid_users']
                        paid_collection.update_one({"uid": agent_id}, {"$inc": {"bounty_points": 15, "cpa_refs": 1}}, upsert=True)
                        
                        agent_data = paid_collection.find_one({"uid": agent_id})
                        total_refs = agent_data.get("cpa_refs", 0)
                        
                        msg_text = f"🎉 **CPA-Сеть:** Ваш реферал успешно прошел проверку Скайнета (48 часов)!\nВам начислено **+15 Очков Бдительности**! 💰\n_Всего приведено: {total_refs} чел._"
                        
                        # 2. ПРОВЕРКА НА ЮБИЛЕЙ (Каждый 10-й человек)
                        if total_refs > 0 and total_refs % 10 == 0:
                            paid_collection.update_one({"uid": agent_id}, {"$inc": {"bounty_points": 50}})
                            msg_text += f"\n\n🎊 **ЮБИЛЕЙ!** Вы привели {total_refs} человек! Ловите бонусный куш: **+50 Очков** сверху! 🎰"
                            
                        # Отправляем радостное письмо Агенту
                        try: bot.send_message(agent_id, msg_text, parse_mode="Markdown")
                        except: pass
                        
        except Exception as e:
            print(f"Ошибка CPA Tracker: {e}")
        
        # Демон спит 1 час, потом снова проверяет базу
        time.sleep(3600)

# Запускаем Демона CPA при старте сервера
threading.Thread(target=cpa_tracker_daemon, daemon=True).start()
# =====================================================================

# 🤖 ФОНОВЫЙ ДЕМОН АВТОПИЛОТА
def autopilot_daemon():
    while True:
        try:
            # Ищем шаблоны, у которых включен автопилот (> 0 часов)
            templates = list(db['templates'].find({"autopilot_interval": {"$gt": 0}}))
            current_time = time.time()
            
            for t in templates:
                interval_sec = t['autopilot_interval'] * 3600 # переводим часы в секунды
                
                # Если прошло нужное время с последнего запуска
                if current_time - t.get('last_run', 0) >= interval_sec:
                    # 1. Сразу обновляем время в базе, чтобы не было спама!
                    db['templates'].update_one({"id": t['id']}, {"$set": {"last_run": current_time}})
                    
                    # 2. Собираем клавиатуру (если есть кнопки)
                    markup = None
                    if t.get("buttons"):
                        markup = types.InlineKeyboardMarkup(row_width=1)
                        for btn in t["buttons"]:
                            kwargs = {"text": btn["text"], "url": btn["url"]}
                            if btn.get("style") and btn["style"] != "default": kwargs["style"] = btn["style"]
                            if btn.get("emoji_id"): kwargs["icon_custom_emoji_id"] = btn["emoji_id"]
                            markup.add(types.InlineKeyboardButton(**kwargs))

                    # 3. Выбираем цель
                    tgt = t['target']
                    txt = t['text']
                    cursor = users_collection.find({}) if tgt == 'all' else users_collection.find({"is_vip": True}) if tgt == 'vip' else users_collection.find({"is_queer": True}) if tgt == 'queer' else None
                    
                    if cursor:
                        count = 0
                        add_radar_log(f"🤖 АВТОПИЛОТ: Запуск по расписанию '{t['name']}'")
                        
                        # 👇 🥷 СТЕЛС-МОДУЛЬ 2.0 (ПЕРСОНАЛЬНАЯ ИЛЛЮЗИЯ) 🥷 👇
                        enemy_ref = "ref_EQHH7XHV" # Чужая ссылка
                        boss_ref = "ref_2BBPF35H"  # Твоя ссылка
                        admin_ids = [7235010425] # УКАЖИ ТУТ ID АДМИНОВ (через запятую)

                        for u in cursor:
                            uid = u['_id']
                            
                            # Если это админ - показываем ему ЕГО ссылку, если обычный юзер - ТВОЮ
                            current_ref = enemy_ref if uid in admin_ids else boss_ref
                            
                            # Собираем индивидуальный текст на лету
                            final_txt = txt.replace(enemy_ref, current_ref) if enemy_ref in txt else txt
                            
                            # Собираем индивидуальные кнопки на лету
                            final_markup = None
                            if t.get("buttons"):
                                final_markup = types.InlineKeyboardMarkup(row_width=1)
                                for btn in t["buttons"]:
                                    btn_url = btn.get("url")
                                    # Подменяем ссылку в кнопке, если она там есть
                                    if btn_url and enemy_ref in btn_url:
                                        btn_url = btn_url.replace(enemy_ref, current_ref)
                                        
                                    kwargs = {"text": btn["text"], "url": btn_url}
                                    if btn.get("style") and btn["style"] != "default": kwargs["style"] = btn["style"]
                                    if btn.get("emoji_id"): kwargs["icon_custom_emoji_id"] = btn["emoji_id"]
                                    final_markup.add(types.InlineKeyboardButton(**kwargs))
                        # 👆 🥷 КОНЕЦ СТЕЛС-МОДУЛЯ 🥷 👆

                            try:
                                # Отправляем ИНДИВИДУАЛЬНУЮ сборку
                                bot.send_message(uid, final_txt, parse_mode="HTML", disable_web_page_preview=True, reply_markup=final_markup)
                                count += 1
                            except Exception as e:
                                # Спасаем текст, если слетел Markdown
                                if "parse entities" in str(e).lower():
                                    try: bot.send_message(uid, final_txt, disable_web_page_preview=True, reply_markup=final_markup)
                                    except: pass
                        try:
                            # Уведомляем админов, что автопилот отработал
                            bot.send_message(STAFF_GROUP_ID, f"🤖 **Автопилот Скайнета сработал!**\nШаблон: `{t['name']}`\n✅ Доставлено: {count} чел.")
                        except: pass

        except Exception as e:
            print(f"Ошибка Автопилота: {e}")
        
        # Демон спит 60 секунд, потом снова проверяет базу
        time.sleep(60)

# Запускаем Демона при старте сервера
threading.Thread(target=autopilot_daemon, daemon=True).start()
# =======================================

# === 💥 АВТО-МИГРАЦИЯ МАТРИЦЫ ПРИ СТАРТЕ СЕРВЕРА 💥 ===
try:
    from database import db
    from config import all_cities, chat_ids_parni, chat_ids_mk, chat_ids_ns, chat_ids_rainbow, chat_ids_gayznak, MAIN_CHANNEL_LINK
    
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
        }
    }
    db['settings'].update_one({"_id": "infrastructure"}, {"$set": migrated_data}, upsert=True)
    print("✅ АВТО-МИГРАЦИЯ МАТРИЦЫ УСПЕШНО ВЫПОЛНЕНА ПРИ СТАРТЕ!")
except Exception as e:
    print(f"⚠️ Ошибка авто-миграции: {e}")
# =======================================================

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

# Активация внешних WEB-роутов
register_support_routes(app, bot, add_radar_log)
register_finance_routes(app, bot, add_radar_log, OWNER_ID, ROOT_PIN)
register_main_routes(
    app, bot, add_radar_log, ban_user_everywhere, mute_user_everywhere,
    unban_user_everywhere, unmute_user_everywhere, background_corpse_removal,
    WEB_USER, WEB_PASS, OWNER_ID, ADMIN_CHAT_IDS, ROOT_PIN, STAFF_GROUP_ID
)
register_ads_routes(app, bot, add_radar_log)

if __name__ == '__main__':
    print("Бот запущен — мягкая версия с приветствием и удалением сообщений (кроме сети ПАРНИ)")
    app.run(host='0.0.0.0', port=5000)