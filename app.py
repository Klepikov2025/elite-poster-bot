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
    all_cities, insert_to_all
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

# ==================== ФУНКЦИИ, ТРЕБУЮЩИЕ BOT ====================
def is_banned_in_network(user_id):
    """Проверяет статус пользователя в самых крупных (якорных) чатах сети"""
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
        target_city = None
        for city_name, networks in all_cities.items():
            for net, groups in networks.items():
                if any(g['chat_id'] == chat_id for g in groups):
                    target_city = city_name
                    break
        
        if target_city:
            user_data = users_collection.find_one({"_id": user_id}) or {}
            main_city = user_data.get("main_city")
            purchased_cities = user_data.get("purchased_cities", [])

            if main_city:
                # 📍 СЦЕНАРИЙ А: Юзер уже привязан к городу
                if main_city == target_city or target_city in purchased_cities:
                    bot.approve_chat_join_request(chat_id, user_id)
                    db['network_stats'].update_one({"_id": "current_period"}, {"$inc": {"approved": 1, f"chats.{chat_id}.approved": 1}}, upsert=True)
                    return
                else:
                    # Чужой город! Отклоняем моментально + Кидаем Оффер
                    bot.decline_chat_join_request(chat_id, user_id)
                    
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(
                        types.InlineKeyboardButton(f"🎟 Купить пропуск в г. {target_city} (250⭐️)", callback_data=f"buy_city_{target_city}"),
                        types.InlineKeyboardButton("👑 Купить VIP (Все города)", callback_data="start_verification")
                    )
                    try:
                        bot.send_message(
                            user_id, 
                            f"❌ Ваша заявка в чат **{target_city}** отклонена.\n\n"
                            f"По правилам сети за вами закреплен город: **{main_city}**.\n\n"
                            f"Вы можете приобрести разовый пропуск (откроет доступ к сетям МК, Парни 18+, НС и др. в г. {target_city}), либо стать VIP-участником для неограниченного доступа везде.",
                            reply_markup=markup,
                            parse_mode="Markdown"
                        )
                    except: pass
                    return
            else:
                # 📍 СЦЕНАРИЙ Б: Метод «Первой двери» для новичков
                # Намертво привязываем к городу и СРАЗУ пускаем
                users_collection.update_one({"_id": user_id}, {"$set": {"main_city": target_city}}, upsert=True)
                
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
            bot.send_message(
                message.chat.id, 
                "🚫 **Доступ закрыт.**\n\nВы находитесь в черном списке нашей сети и заблокированы в основных чатах.", 
                parse_mode="Markdown"
            )
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

def ban_user_everywhere(target_id, reason="Без причины", admin_name="Система", user_link=None, trigger_text=None, origin_chat=None):
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
    
    # 📡 ОТПРАВЛЯЕМ СИГНАЛ В WEB-РАДАР
    add_radar_log(f"💥 БАН ({admin_name}): {target_id} | {reason}")
    
    return len(banned_in)

# ==================== 📩 СИСТЕМА ТИКЕТОВ (САППОРТ) ====================
@bot.message_handler(func=lambda message: message.text == "💬 Написать в Поддержку" and message.chat.type == "private")
def support_request_handler(message):
    # 1. Просим юзера написать проблему
    msg = bot.send_message(
        message.chat.id, 
        "📝 **Служба поддержки**\n\nНапишите ваш вопрос, жалобу или предложение *одним сообщением* ниже. Мы ответим вам прямо в этом чате.", 
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

# ==================== ЛОВЕЦ ЗВЕЗД (ОПЛАТА 50 ЗВЕЗД В ГРУППЕ) ====================
# Перечисляем абсолютно ВСЕ типы, чтобы бот ловил стикеры, кружки, фото, текст и т.д.
@bot.message_handler(func=lambda message: str(message.chat.id) == str(SUPPORT_GROUP_ID), content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'location', 'contact', 'successful_payment'])
def catch_paid_stars(message):
    # Игнорируем сообщения от других ботов и системные уведомления
    if message.from_user.is_bot: return
    
    uid = message.from_user.id
    
    # В этой группе любое сообщение стоит 50 звезд. 
    # Сбрасываем страйки и ставим status: 1
    db['paid_users'].update_one(
        {"uid": uid},
        {"$set": {
            "status": 1,
            "strikes": 0,  # <-- Обязательно обнуляем страйки тут!
            "timestamp": datetime.now()
        }},
        upsert=True
    )

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

# ==================== ПЕРЕХВАТЧИК "МЕРТВЫХ ДУШ" (Защита от старых заявок + Амнистия) ====================
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

        # --- 🕊️ ЛОКАЛЬНАЯ АМНИСТИЯ ПАРНИ (Для тех, кто вошел сам или одобрен вручную) ---
        if chat_id in PARNI_CHATS:
            user_data = users_collection.find_one({"_id": user_id}) or {}
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
                        # Если это верификация — выдаем официальный статус и тег!
                        users_collection.update_one(
                            {"_id": target_uid}, 
                            {"$set": {"is_verified": True, "custom_tag": "Верифицирован МК"}, "$unset": {"shame_tag": ""}},
                            upsert=True
                        )
                    elif task['action'] == "fine_unban":
                        # Если просто оплатил штраф — снимаем позор, но верификацию не даем
                        users_collection.update_one(
                            {"_id": target_uid}, 
                            {"$unset": {"shame_tag": ""}}
                        )
                    
                    # 3. ОТЧЕТ В ФЛУДИЛКУ АДМИНАМ!
                    if task['action'] == "fine_unban":
                        report_text = f"💸 **Скайнет (Автоматика):**\nЮзер `{target_uid}` оплатил штраф!\nОграничения сняты. Глобально разбанен ({unbanned} чатов) и размучен ({unmuted} чатов)."
                    else:
                        report_text = f"✅ **Скайнет (Автоматика):**\nЮзер `{target_uid}` прошел ручную верификацию Секретарем!\nГлобально разбанен ({unbanned} чатов) и размучен ({unmuted} чатов)."
                    
                    try: bot.send_message(STAFF_GROUP_ID, report_text, parse_mode="Markdown")
                    except: pass
                    
                    # 4. Закрываем задачу
                    db['skynet_tasks'].update_one({"_id": task['_id']}, {"$set": {"status": "done"}})
        except Exception as e:
            print(f"Ошибка слушателя: {e}")
            
        time.sleep(3) # Проверяем приказы каждые 3 секунды

# === ЗАПУСКАЕМ ФОНОВЫЕ ПРОЦЕССЫ ЗДЕСЬ (КОГДА ПИТОН УЖЕ ЗНАЕТ ВСЕ ФУНКЦИИ) ===
threading.Thread(target=vip_funnel_sniper, daemon=True).start()
threading.Thread(target=skynet_listener, daemon=True).start()
# ============================================================================

# ==================== ВЕБ-ПАНЕЛЬ (ГЛАЗ САУРОНА) ====================
import threading

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

                # --- ДОБАВЛЯЕМ ПРОВЕРКУ КАРАНТИНА ---
                is_quarantine = False
                first_seen = u_info.get("first_seen", 0) if u_info else 0
                if uid > 7800000000 and first_seen > 0 and (time.time() - first_seen) < 172800:
                    is_quarantine = True
                # ------------------------------------

                user_data = {
                    "id": uid,
                    "is_quarantine": is_quarantine,  # <--- ВОТ НАШ НОВЫЙ ФЛАГ
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
        "unanswered_tickets": db['support_tickets'].count_documents({"is_answered": False}) # <--- НОВОЕ
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
    """Отдает список логов для хакерского терминала ИЗ БАЗЫ"""
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    
    # Достаем 100 самых свежих событий из базы (сортируем по убыванию времени)
    logs = db['radar_logs'].find().sort("ts", -1).limit(100)
    
    return jsonify([log["text"] for log in logs])

@app.route('/glaz/api/get_list')
def api_get_list():
    """Умные списки базы данных"""
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
        for doc in banned_collection.find().limit(1000): # Лимит, чтобы браузер не умер от 20000 строк
            results.append({"id": doc["_id"], "info": doc.get("reason", "Забанен"), "tag": "ЧС"})
            
    return jsonify(results)

@app.route('/glaz/api/proxy_sessions')
def api_proxy_sessions():
    """Секретный API: Отдает список всех анонимных диалогов (Черный Ящик)"""
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    
    # Берем 30 последних переписок из базы
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
    """Секретный API: Отдает полную переписку конкретной сессии"""
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
    """Оружие Массового Поражения (работает в фоне) + Кастомные причины + МУТ"""
    if not session.get('logged_in'): return jsonify({"success": False}), 401
    
    raw_ids = request.form.get('uids', '')
    action = request.form.get('action', 'ban')
    reason = request.form.get('reason', '').strip()
    
    if not reason:
        reason = "Массовая репрессия (Web)"
        
    uids = []
    for line in raw_ids.replace(',', '\n').split('\n'):
        clean_id = line.strip()
        if clean_id.isdigit(): uids.append(int(clean_id))
        
    if not uids:
        return jsonify({"success": False, "message": "Не найдено валидных ID!"})
        
    add_radar_log(f"⚡ Запущен МАССОВЫЙ {action.upper()} ({reason}) для {len(uids)} юзеров!")
        
    def background_mass_task(id_list, act, rsn):
        for uid in id_list:
            if act == 'ban':
                ban_user_everywhere(uid, reason=rsn, admin_name="Web-Саурон")
            elif act == 'mute':
                mute_user_everywhere(uid, reason=rsn, admin_name="Web-Саурон")
            elif act == 'unban':
                unban_user_everywhere(uid)
                unmute_user_everywhere(uid)
            time.sleep(0.5) # Защита от лимитов Telegram API
            
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
        add_radar_log(f"💥 БАН: {uid}")
        log_to_staff = False 
    elif action == 'unban':
        unban_user_everywhere(uid)
        unmute_user_everywhere(uid)
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
            
    # 👇 ВОТ СЮДА ВСТАВЛЯЕМ НОВЫЙ БЛОК ДЛЯ ГОРОДА 👇
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

@app.route('/glaz/withdrawal_action', methods=['POST'])
def glaz_withdrawal_action():
    if not session.get('logged_in'): return redirect(url_for('login'))
    wd_id = request.form.get('wd_id')
    action = request.form.get('action')
    wd = withdrawals_collection.find_one({"_id": wd_id})
    if wd and wd.get('status') == 'pending':
        uid = wd['user_id']
        amount = wd['amount']
        if action == 'pay':
            update_user_stats(uid, balance_add=-amount)
            withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "paid"}})
            add_radar_log(f"💸 ОПЛАЧЕНА ЗАЯВКА: {wd_id}")
            try: bot.send_message(uid, f"✅ Ваш запрос на вывод {amount}⭐️ одобрен! Деньги отправлены.")
            except: pass
        elif action == 'reject':
            withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "rejected"}})
            add_radar_log(f"🚫 ОТКЛОНЕНА ЗАЯВКА: {wd_id}")
            try: bot.send_message(uid, "❌ Ваш запрос на вывод средств отклонён.")
            except: pass
    return redirect(url_for('admin_panel'))

@app.route('/glaz/add_promo', methods=['POST'])
def glaz_add_promo():
    if not session.get('logged_in'): return redirect(url_for('login'))
    code = request.form.get('code').strip().upper()
    discount = int(request.form.get('discount'))
    target = request.form.get('target')
    limit = int(request.form.get('limit'))
    db['promocodes'].update_one(
        {"_id": code},
        {"$set": {"type": "percent", "value": discount, "target": target, "usage_limit": limit, "used_count": 0, "owner_uid": OWNER_ID, "is_active": True}},
        upsert=True
    )
    add_radar_log(f"🎫 СОЗДАН ПРОМОКОД: {code} ({discount}%)")
    return redirect(url_for('admin_panel'))

@app.route('/glaz/delete_promo', methods=['POST'])
def glaz_delete_promo():
    """Уничтожитель промокодов"""
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    code = request.form.get('code')
    if code:
        db['promocodes'].delete_one({"_id": code})
        add_radar_log(f"🗑 ПРОМОКОД УНИЧТОЖЕН: {code}")
        
    return redirect(url_for('admin_panel'))

# ==================== ДОПОЛНИТЕЛЬНЫЕ МОДУЛИ КОНТРОЛЯ ЯДРА ====================
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
    try: bot.send_message(uid, "✅ Администрация досрочно сняла с вас карантин! Можете писать в чаты.")
    except: pass
    return jsonify({"success": True})

@app.route('/glaz/broadcast', methods=['POST'])
def glaz_broadcast():
    if not session.get('logged_in'): return jsonify({"success": False}), 401
    
    text = request.form.get('text')
    target = request.form.get('target')
    buttons_raw = request.form.get('buttons', '[]') # <-- Ловим кнопки с сайта
    
    # Парсим кнопки из строки в нормальный список
    try:
        buttons_list = json.loads(buttons_raw)
    except:
        buttons_list = []
    
    def bg_broadcast(txt, tgt, btns_list):
        # === 1. СОБИРАЕМ КЛАВИАТУРУ ИЗ КНОПОК ===
        markup = None
        if btns_list:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for btn in btns_list:
                kwargs = {"text": btn["text"], "url": btn["url"]}
                if btn.get("style") and btn["style"] != "default":
                    kwargs["style"] = btn["style"]
                if btn.get("emoji_id"):
                    kwargs["icon_custom_emoji_id"] = btn["emoji_id"]
                markup.add(types.InlineKeyboardButton(**kwargs))
        # ========================================

        add_radar_log(f"🚀 Запуск рассылки для: {tgt}")
        cursor = users_collection.find({}) if tgt == 'all' else users_collection.find({"is_vip": True}) if tgt == 'vip' else users_collection.find({"is_queer": True}) if tgt == 'queer' else None
        if not cursor: return
            
        count = 0
        dead_count = 0  # Счетчик трупаков 💀
        
        for u in cursor:
            try:
                # ПОПЫТКА 1: Отправляем с красивым Markdown и КНОПКАМИ (reply_markup=markup)
                bot.send_message(u['_id'], txt, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)
                count += 1
            except Exception as e:
                err_text = str(e).lower()
                
                # Если Телеграм ругается на кривую разметку
                if "parse entities" in err_text:
                    try:
                        # ПОПЫТКА 2: Спасаем рассылку! Голый текст, но КНОПКИ ОСТАВЛЯЕМ!
                        bot.send_message(u['_id'], txt, disable_web_page_preview=True, reply_markup=markup)
                        count += 1
                    except Exception as inner_e:
                        if "deactivated" in str(inner_e).lower():
                            users_collection.delete_one({"_id": u['_id']})
                            dead_count += 1
                
                # 💀 РАБОТАЕТ ТРУПОВОЗКА
                elif "deactivated" in err_text:
                    users_collection.delete_one({"_id": u['_id']})
                    dead_count += 1
                    
                    if SkynetSettings.get().get("auto_corpse_removal", True):
                        threading.Thread(target=background_corpse_removal, args=(u['_id'],), daemon=True).start() 
            
        # Отчет
        add_radar_log(f"✅ Рассылка: Доставлено {count}. 💀 Вывезено трупов: {dead_count}")
        try: 
            bot.send_message(
                STAFF_GROUP_ID, 
                f"🚀 **Рассылка завершена!**\nЦель: {tgt}\n✅ Доставлено: {count} чел.\n💀 Удалено мертвых душ из базы: {dead_count}"
            )
        except: pass

    # Запускаем поток, передавая ему наши кнопки (btns_list)
    threading.Thread(target=bg_broadcast, args=(text, target, buttons_list), daemon=True).start()
    return jsonify({"success": True, "message": "🚀 Рассылка запущена в фоне!"})

# === 👑 ROOT: КОНСТРУКТОР КНОПОК ===
ROOT_PIN = "6996"  # ⚠️ ПОМЕНЯЙ ЭТОТ ПАРОЛЬ НА СВОЙ СЕКРЕТНЫЙ ПИН-КОД!

@app.route('/glaz/api/root/buttons', methods=['POST'])
def api_get_root_buttons():
    data = request.json
    if data.get('pin') != ROOT_PIN:
        return jsonify({"error": "Access Denied"}), 403
    
    btns = db['settings'].find_one({"_id": "skynet_buttons"})
    if not btns or not btns.get("buttons"):
        # Если база пока пустая, отдаем дефолтные для примера
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
        
    # Сохраняем массив кнопок прямо в MongoDB
    db['settings'].update_one(
        {"_id": "skynet_buttons"}, 
        {"$set": {"buttons": data['buttons']}}, 
        upsert=True
    )
    return jsonify({"status": "ok"})

# === 🤬 СЛОВАРЬ ИНКВИЗИТОРА (Живой фильтр) ===
@app.route('/glaz/api/dictionary', methods=['GET'])
def get_dictionary():
    # Тянем слова из базы
    data = db['settings'].find_one({"_id": "skynet_dictionary"}) or {"red": [], "yellow": []}
    return jsonify({"red": data.get("red", []), "yellow": data.get("yellow", [])})

@app.route('/glaz/api/dictionary/add', methods=['POST'])
def add_dictionary_word():
    if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    data = request.json
    word = data.get('word', '').strip().lower()
    zone = data.get('zone') # 'red' или 'yellow'
    exact = data.get('exact', False)
    
    if not word or zone not in ['red', 'yellow']:
        return jsonify({"success": False, "error": "Некорректные данные"})

    # 🧠 УМНАЯ ГЕНЕРАЦИЯ REGEX (Машинный код)
    # Если галочка "Точное совпадение": ищем строго это слово (например "мяу", но не "мяукать")
    if exact:
        pattern = rf"\b{word}\b"
    # Если галочка снята: ищем корень и любые окончания (например "папик", "папика", "папику")
    else:
        pattern = rf"\b{word}[а-я]*\b"

    # Сохраняем в базу и само слово, и его машинный код
    new_entry = {"word": word, "pattern": pattern, "exact": exact}
    
    db['settings'].update_one(
        {"_id": "skynet_dictionary"},
        {"$push": {zone: new_entry}},
        upsert=True
    )
    return jsonify({"success": True, "message": f"Слово '{word}' добавлено в {zone} зону!"})

@app.route('/glaz/api/dictionary/remove', methods=['POST'])
def remove_dictionary_word():
    if not session.get('logged_in'): return jsonify({"success": False}), 401
    
    data = request.json
    word = data.get('word')
    zone = data.get('zone')
    
    db['settings'].update_one(
        {"_id": "skynet_dictionary"},
        {"$pull": {zone: {"word": word}}}
    )
    return jsonify({"success": True})

# === 📝 КОНСТРУКТОР ТЕКСТОВ СКАЙНЕТА ===
@app.route('/glaz/api/system_texts', methods=['GET'])
def api_get_system_texts():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    data = db['settings'].find_one({"_id": "skynet_texts"}) or {}
    
    # Возвращаем с дефолтными значениями, если база пока пустая
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

# === 👁‍🗨 ГОЛОС САУРОНА (Связь с юзером из Досье) ===
@app.route('/glaz/api/send_sauron_msg', methods=['POST'])
def api_send_sauron_msg():
    if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    uid = request.form.get('uid')
    message_text = request.form.get('message')
    
    if not uid or not message_text:
        return jsonify({"success": False, "error": "Пустые данные"}), 400
        
    try:
        # Отправляем сообщение от лица бота
        bot.send_message(
            chat_id=int(uid), 
            text=f"👑 **Сообщение от Администрации:**\n\n{message_text}", 
            parse_mode="Markdown"
        )
        # Логируем действие в радар, чтобы ты видел, что оно ушло
        add_radar_log(f"👁‍🗨 Голос Саурона: Отправлено ЛС юзеру {uid}")
        return jsonify({"success": True})
        
    except Exception as e:
        err_str = str(e).lower()
        if "bot was blocked" in err_str or "deactivated" in err_str:
            return jsonify({"success": False, "error": "Пользователь заблокировал бота или удален 💀"})
        return jsonify({"success": False, "error": "Ошибка API Telegram"})

# === 🕒 АВТОПИЛОТ И ШАБЛОНЫ РАССЫЛОК ===
@app.route('/glaz/api/templates', methods=['GET'])
def api_get_templates():
    # Отдаем список шаблонов из базы
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
        "autopilot_interval": 0, # 0 = Автопилот выключен. Иначе - часы (12, 24 и тд)
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
    # Обновляем интервал и сбрасываем таймер
    db['templates'].update_one({"id": tid}, {"$set": {"autopilot_interval": interval, "last_run": 0}})
    return jsonify({"success": True})

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
                        for u in cursor:
                            try:
                                bot.send_message(u['_id'], txt, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)
                                count += 1
                            except Exception as e:
                                # Спасаем текст, если слетел Markdown
                                if "parse entities" in str(e).lower():
                                    try: bot.send_message(u['_id'], txt, disable_web_page_preview=True, reply_markup=markup)
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

# === 📩 WEB-МЕССЕНДЖЕР (САППОРТ) ===
@app.route('/glaz/api/tickets', methods=['GET'])
def api_get_tickets():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    # Достаем последние 50 вопросов
    tickets = list(db['support_tickets'].find({}, {"_id": 0}).sort("timestamp", -1).limit(50))
    return jsonify(tickets)

@app.route('/glaz/api/tickets/reply', methods=['POST'])
def api_reply_ticket():
    if not session.get('logged_in'): return jsonify({"success": False}), 401
    data = request.json
    uid = data.get('uid')
    text = data.get('text')
    timestamp = data.get('timestamp')
    
    try:
        # Отправляем ответ юзеру
        bot.send_message(
            int(uid), 
            f"👨‍💻 **Ответ Службы Поддержки:**\n\n{text}", 
            parse_mode="Markdown"
        )
        # Помечаем в базе, что тикет закрыт (отвечен) и СОХРАНЯЕМ ТЕКСТ ОТВЕТА
        db['support_tickets'].update_one(
            {"uid": int(uid), "timestamp": timestamp},
            {"$set": {"is_answered": True, "reply_text": text}}
        )
        add_radar_log(f"✅ Отправлен ответ на тикет юзеру {uid}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == '__main__':
    print("Бот запущен — мягкая версия с приветствием и удалением сообщений (кроме сети ПАРНИ)")
    app.run(host='0.0.0.0', port=5000)