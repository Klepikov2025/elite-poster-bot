import os
import telebot
import requests
from telebot import types
from flask import Flask, request, render_template, session, redirect, url_for, jsonify
from datetime import datetime
import pymongo
from pymongo import MongoClient
import pytz
import random
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
            r'\bочень молод(ой|енький)\b'  # <--- ЛОВИМ "ОЧЕНЬ МОЛОДОГО"
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
    
    return len(muted_in)

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

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"Ошибка при проверке подписки для {user_id}: {e}")
        return False

# --- МГНОВЕННЫЙ РАДАР БЛОКИРОВОК (Ловит ТОЛЬКО беглецов из VIP-воронки) ---
@bot.my_chat_member_handler()
def catch_bot_block(message):
    if message.chat.type == "private":
        new_status = message.new_chat_member.status
        if new_status == "kicked": 
            user_id = message.from_user.id
            
            # 1. ПРОВЕРКА: СВОИХ НЕ ТРОГАЕМ (VIP-ЗАЩИТА)
            try:
                chat_member = bot.get_chat_member(VIP_CHAT_ID, user_id)
                if chat_member.status in ["member", "administrator", "creator"]:
                    return 
            except:
                pass 
                
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
# ========================================================================

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

# ==================== ЛОВЕЦ ЗВЕЗД (ОПЛАТА 50 ЗВЕЗД) ====================
@bot.message_handler(func=lambda message: str(message.chat.id) == str(SUPPORT_GROUP_ID))
def catch_paid_stars(message):
    # Игнорируем сообщения от других ботов и системные уведомления
    if message.from_user.is_bot: return
    
    uid = message.from_user.id
    
    # В этой группе любое сообщение стоит 50 звезд. 
    # Пишем в базу paid_users "status: 1", чтобы Секретарь его пропустил
    db['paid_users'].update_one(
        {"uid": uid},
        {"$set": {
            "status": 1,
            "timestamp": datetime.now()
        }},
        upsert=True
    )

# ==================== НАСТРОЙКИ И ЕДИНОЕ ЯДРО СКАЙНЕТА ====================

# 🔴 Красная зона (Глобал бан) - добавлены \b для точного поиска коротких слов
RED_WORDS = [r"фен\b", r"\bмеф\b", r"кристаллы", r"\bсоли\b", r"стафф", r"\bцп\b", r"детское"]

# 🟡 Желтая зона: Коммерция (Умный Regex, чтобы не банить "симпатичных")
YELLOW_COMMERCE_REGEX = [r'\bмп\b', r'\bм\.п\b', r'\bмат\s*помощь\b', r'\bспонсор\b', r'\bсодержу\b', r'\bкоммерция\b', r'\bвознаграждение\b', r'\bбабки\b']

# 🟡 Желтая зона: Попрошайки (Мут на 2 часа)
YELLOW_BEGGARS = ["у меня бан", "пиши первым", "напишите первым", "жду в лс", "пиши в лс", "ставь реакцию", "ставьте реакции"]

# 🔵 Синяя зона: Теги (Без мута)
VIRT_WORDS = ["обмен", "вирт", "вз", "дроч", "видеозвонок", "слить", "фотками"]
CAR_WORDS = ["в машине", "на авто", "на заднем", "тачка", "в тачке"]
WC_WORDS = ["туалет", "кабинка", "тц", "в кабинке", "в туалете", "глори", "glory"]

warned_users = {}  # (chat_id, user_id) -> message_id отбивки

# Ловим вообще ВСЁ в группах (текст, фото, видео и т.д.)
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'location', 'contact'], func=lambda message: message.chat.type in ['group', 'supergroup'])
def skynet_core_handler(message):
    
    # --- БРОНЯ ДЛЯ АДМИНОВ И КАНАЛОВ ---
    if getattr(message, 'sender_chat', None) or message.from_user.id in [777000, 136817688]:
        return
    # -----------------------------------

    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Собираем данные и генерируем твою Markdown-ссылку
    raw_text = message.text or message.caption or ""
    text = raw_text.lower()
    trigger_text = raw_text if raw_text else "Без текста (медиа)"
    user_link = get_user_name(message.from_user)
    
    # === ФИКСИРУЕМ НАЗВАНИЕ ЧАТА ДЛЯ ОТЧЕТОВ ===
    chat_title = escape_md(message.chat.title) if message.chat.title else f"Чат {chat_id}"

    try:
        # 1. СИНХРОНИЗАЦИЯ СТАТУСОВ И ТЕГОВ ИЗ БАЗЫ
        user_data = users_collection.find_one({"_id": user_id}) or {}
        is_vip = user_data.get("is_vip", False)
        is_queer = user_data.get("is_queer", False)
        is_verified = user_data.get("is_verified", False)
        shame_tag = user_data.get("shame_tag")
        custom_tag = user_data.get("custom_tag")

        # --- ТЕНЕВАЯ ИНДЕКСАЦИЯ ГОРОДОВ (SMART LEGACY) ---
        main_city = user_data.get("main_city")
        if not main_city:
            # Юзер еще не привязан. Определяем город текущего чата:
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
        # ------------------------------------------------- 

        # --- АВТО-СИНХРОНИЗАЦИЯ ФИЗИЧЕСКОГО ПРИСУТСТВИЯ (ДВУСТОРОННЯЯ) ---
        try:
            m_vip = bot.get_chat_member(VIP_CHAT_ID, user_id)
            is_physically_there = getattr(m_vip, 'is_member', False) if m_vip.status == 'restricted' else True
            actual_vip = m_vip.status in ['member', 'administrator', 'creator'] or (m_vip.status == 'restricted' and is_physically_there)
            
            if is_vip != actual_vip:
                is_vip = actual_vip
                users_collection.update_one({"_id": user_id}, {"$set": {"is_vip": is_vip}}, upsert=True)
                
        except telebot.apihelper.ApiTelegramException as e:
            error = str(e).lower()
            if any(phrase in error for phrase in ["user not found", "chat not found", "not a member", "forbidden", "user is not a member"]):
                if is_vip: 
                    is_vip = False
                    users_collection.update_one({"_id": user_id}, {"$set": {"is_vip": False}}, upsert=True)
        except Exception:
            pass # Игнорируем сетевые лаги, не срываем погоны!

        try:
            m_beyond = bot.get_chat_member(BEYOND_CHAT_ID, user_id)
            is_physically_there_q = getattr(m_beyond, 'is_member', False) if m_beyond.status == 'restricted' else True
            actual_queer = m_beyond.status in ['member', 'administrator', 'creator'] or (m_beyond.status == 'restricted' and is_physically_there_q)
            
            if is_queer != actual_queer:
                is_queer = actual_queer
                users_collection.update_one({"_id": user_id}, {"$set": {"is_queer": is_queer}}, upsert=True)
                
        except telebot.apihelper.ApiTelegramException as e:
            error = str(e).lower()
            if any(phrase in error for phrase in ["user not found", "chat not found", "not a member", "forbidden", "user is not a member"]):
                if is_queer:
                    is_queer = False
                    users_collection.update_one({"_id": user_id}, {"$set": {"is_queer": False}}, upsert=True)
        except Exception:
            pass # Игнорируем сетевые лаги

        # --- МАГИЯ: ПЕРЕХВАТ РУЧНЫХ ТЕГОВ ИЗ ИНТЕРФЕЙСА ---
        try:
            member = bot.get_chat_member(chat_id, user_id)
            current_tag = getattr(member, 'custom_title', None)
            bot_tags = ["𝓟𝓡𝓔𝓜𝓘𝓤𝓜", "𝐐𝐔𝐄𝐄𝐑 ♛", "𝐑𝐄𝐀𝐋/𝐕𝐈𝐏♕", "Верифицирован МК", "Not verified", "РИСК/ВИРТ/ОБМЕН", "автососка", "туалетная соска"]
            if current_tag and current_tag not in bot_tags:
                users_collection.update_one({"_id": user_id}, {"$set": {"custom_tag": current_tag}}, upsert=True)
                custom_tag = current_tag 
        except: pass

        # Определяем итоговый тег
        final_tag = "Not verified"
        if custom_tag: final_tag = custom_tag
        elif is_vip and is_queer: final_tag = "𝓟𝓡𝓔𝓜𝓘𝓤𝓜"
        elif is_queer: final_tag = "𝐐𝐔𝐄𝐄𝐑 ♛"
        elif is_vip: final_tag = "𝐑𝐄𝐀𝐋/𝐕𝐈𝐏♕"
        elif is_verified: final_tag = "Верифицирован МК"
        elif shame_tag: final_tag = shame_tag

        try: safe_set_tag(chat_id, user_id, final_tag)
        except: pass

        # 2. КРАСНАЯ ЗОНА (Проверяем ВСЕХ)
        if any(re.search(word, text) for word in RED_WORDS):
            bot.delete_message(chat_id, message.message_id)
            ban_user_everywhere(user_id, reason="Мясорубка: Красная зона", admin_name="Скайнет ⚔️", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
            return

        # 2.5. ЧЕРНАЯ ЗОНА: НЕСОВЕРШЕННОЛЕТНИЕ (< 18) - МГНОВЕННЫЙ БАН
        safe_minor = re.sub(r'\b(1[0-7])\s*(см|cm)\b', '', text)
        
        minor_patterns = [
            r'\b(мне|я)\s*(1[0-7])\b',                   
            r'\b(мне|я)\s*18\s*-\s*[1-9]\b',             
            r'\b(1[0-7]|18\s*-\s*[1-9])\s*(лет|годик)\b',
            r'\b(1[0-7])\s*[/\\-]\s*1\d{2}\b',           
            r'\b(200[9]|201[0-9])\s*(г|год|года|г\.р)\b',
            r'\bочень молод(ой|енький)\b'  # <--- ЛОВИМ И В ЧАТАХ ТОЖЕ
        ]
        
        if any(re.search(p, safe_minor) for p in minor_patterns):
            bot.delete_message(chat_id, message.message_id)
            ban_user_everywhere(user_id, reason="Черная зона: Несовершеннолетний (<18)", admin_name="Скайнет 🔞", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
            return

        # ИММУНИТЕТ ДЛЯ ЭЛИТЫ И ВЕРИФИЦИРОВАННЫХ 
        if any([is_vip, is_queer, is_verified, custom_tag]): return 

        # ИСКЛЮЧЕНИЕ "ПАРНИ"
        if chat_id in PARNI_CHATS: return

        # 3. ПРОВЕРКА ПОДПИСКИ
        if not is_subscribed(user_id):
            try: bot.delete_message(chat_id, message.message_id)
            except: pass
            key = (chat_id, user_id)
            if key not in warned_users:
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(types.InlineKeyboardButton(text="Подписаться на МК", url=MAIN_CHANNEL_LINK, icon_custom_emoji_id="5215330331711775720", style="success"))
                markup.add(types.InlineKeyboardButton(text="ПАРНИ 18+", url="https://t.me/znakparni"))
                markup.add(types.InlineKeyboardButton("Резервный канал", url="https://t.me/gaysexchatrur"), types.InlineKeyboardButton("ПРАВИЛА МК", url="https://t.me/MensClubRules"))
                markup.add(types.InlineKeyboardButton(text="🚀 БЕСПЛАТНЫЙ VPN ДЛЯ ВСЕХ", url="https://t.me/perec?start=ref_2BBPF35H", icon_custom_emoji_id="5981123193862098366", style="primary"))
                sent = bot.send_message(chat_id, "❗ Внимание, чтобы писать в чате вам необходимо подписаться на наш основной канал.\n\nБез подписки на канал ваши сообщения будут удаляться автоматически. Вступая в чат, я подтверждаю совершеннолетие и обязуюсь соблюдать правила, с которыми ознакомлен и согласен.", reply_markup=markup)
                warned_users[key] = sent.message_id
                def auto_delete():
                    time.sleep(120)
                    try: bot.delete_message(chat_id, sent.message_id)
                    except: pass
                    if key in warned_users: del warned_users[key]
                threading.Thread(target=auto_delete, daemon=True).start()
            return

        # === 🚀 РАДАР ТВИНКОВ (Сравнение текстов) ===
        if len(raw_text) > 30:
            clean_current = re.sub(r'\s+', '', text)
            # Берем последние 30 забаненных текстов
            recent_bans = list(db['blacklisted_texts'].find().sort("_id", -1).limit(30))
            
            for bad in recent_bans:
                clean_bad = bad.get("clean_text", "")
                if not clean_bad: continue
                
                # Сравниваем совпадение (от 0 до 1)
                similarity = difflib.SequenceMatcher(None, clean_current, clean_bad).ratio()
                
                if similarity > 0.85: # Если текст совпадает больше чем на 85%
                    try: bot.delete_message(chat_id, message.message_id) # Тихо съедаем
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
                    
                    return # Останавливаем код, сообщение не пройдет дальше!
        # ==========================================

        # === 🛡 КАРАНТИН НОВОРЕГОВ (С реальным таймером 48ч) ===
        # 1. Проверяем, когда мы впервые увидели этот аккаунт
        first_seen = user_data.get('first_seen')
        if not first_seen:
            first_seen = time.time()
            users_collection.update_one({"_id": user_id}, {"$set": {"first_seen": first_seen}}, upsert=True)

        # 2. Считаем, сколько часов прошло (48 часов = 172800 сек)
        seconds_passed = time.time() - first_seen
        
        # 3. Если ID "свежий" (больше 7.8 млрд) И прошло меньше 48 часов
        if user_id > 7800000000 and seconds_passed < 172800:
            try: bot.delete_message(chat_id, message.message_id)
            except: pass
            
            # --- ОТЧЕТ В STAFF (Чтобы поддержка знала) ---
            try: 
                bot.send_message(
                    STAFF_GROUP_ID, 
                    f"🥷 **КАРАНТИН:** Удалено сообщение от новорега {user_link} (`{user_id}`).\n"
                    f"📍 Чат: {chat_title}\n"
                    f"🕒 Прошло: {int(seconds_passed // 3600)}ч. из 48ч.",
                    parse_mode="Markdown"
                )
            except: pass
            
            # --- ПРЕДУПРЕЖДЕНИЕ В ГРУППУ (На 5 минут) ---
            try:
                # Прячем ссылку в слово, чтобы нижнее подчеркивание не ломало Markdown!
                warning_msg = bot.send_message(
                    chat_id, 
                    f"🚨 {user_link}, **Защита от спама!**\n"
                    "Ваш аккаунт создан недавно. Для безопасности сети действует карантин 48 часов.\n"
                    "Подождите, или пройдите верификацию в [Службе Поддержки](https://t.me/MK_MensClubSUPPORT).", 
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                
                def delete_quarantine_warning():
                    time.sleep(300) # Удалит через 5 минут
                    try: bot.delete_message(chat_id, warning_msg.message_id)
                    except: pass
                threading.Thread(target=delete_quarantine_warning, daemon=True).start()
            except Exception as e:
                print(f"Ошибка отправки карантина: {e}")
            
            return # Сообщение не идет дальше
        # ==========================================

        # 3.5. ОПЕРАЦИЯ "1 МАЯ" (Строгий формат параметров)
        EXCLUDED_FROM_PARAMS = set(PARNI_CHATS)
        EXCLUDED_FROM_PARAMS.update([VIP_CHAT_ID, BEYOND_CHAT_ID])
        EXCLUDED_FROM_PARAMS.update([
            chat_ids_mk.get("Фетиши"),
            chat_ids_mk.get("Мужской Чат"),
            chat_ids_mk.get("Секс Туризм"),
            chat_ids_mk.get("Аренда Жилья")
        ])

        if chat_id not in EXCLUDED_FROM_PARAMS:
            strict_match = re.search(r'(?<!\d)[1-9]\d/1\d{2}/\d{2,3}(?:/\d{1,2}(?:[.,*xхX]\d{1,2})?)?(?!\d)', text)
            
            if not strict_match:
                bot.delete_message(chat_id, message.message_id)
                mute_user_everywhere(user_id, reason="Нет параметров или неверный формат (1 Мая)", admin_name="Скайнет 📏", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
                
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🛠 Пройти верификацию", url="https://t.me/MK_MensClubSUPPORT"),
                    types.InlineKeyboardButton("😈 ПАРНИ 18+ (Без ограничений)", url="https://t.me/znakparni/116")
                )

                warning_msg = bot.send_message(
                    chat_id, 
                    f"🚨 {user_link}, **ВНИМАНИЕ!**\n\n"
                    "С 1 мая введен СТРОГИЙ стандарт оформления анкет для досок объявлений.\n"
                    "Любой текст **БЕЗ ПАРАМЕТРОВ** или с неправильным форматом запрещен!\n"
                    "Параметры должны быть указаны **ТОЛЬКО через слеш (/) без пробелов и лишних слов**.\n\n"
                    "✅ *Примеры:* `24/187/72` или `24/187/72/19` (допускается `19.5` или `19*4`)\n\n"
                    "Ваша анкета удалена, а вы временно ограничены в общении во всех группах сети. Пройдите верификацию для разблокировки.\n\n"
                    "💡 *P.S. В нашей сети «ПАРНИ 18+» нет ограничений на формат текста и разрешен любой откровенный контент (включая порно). Переходи туда! 👇*",
                    reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True
                )
                
                def delete_warning_may():
                    time.sleep(300)
                    try: bot.delete_message(chat_id, warning_msg.message_id)
                    except: pass
                threading.Thread(target=delete_warning_may, daemon=True).start()
                return

        # 4. КОММЕРЦИЯ (ГЛОБАЛЬНЫЙ МУТ)
        clean_commerce = re.sub(r'без\s*м\.?п\.?|не\s*коммерция|без\s*мат(\.?|ериальной)\s*помощи', '', text)
        if any(re.search(pattern, clean_commerce) for pattern in YELLOW_COMMERCE_REGEX):
            bot.delete_message(chat_id, message.message_id)
            mute_user_everywhere(user_id, reason="Желтая зона: Коммерция", admin_name="Скайнет ⚔️", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
            return

        # 5. ПОПРОШАЙКИ (ГЛОБАЛЬНЫЙ МУТ на 2 часа!)
        if any(word in text for word in YELLOW_BEGGARS):
            bot.delete_message(chat_id, message.message_id)
            mute_user_everywhere(user_id, reason="Желтая зона: Попрошайка", admin_name="Скайнет 🤫", user_link=user_link, trigger_text=trigger_text, mute_time=int(time.time())+7200, origin_chat=chat_title)
            return

        # 5.5. ОРАНЖЕВАЯ ЗОНА: ВОЗРАСТ 18 ЛЕТ (ГЛОБАЛЬНЫЙ МУТ!)
        safe_age = re.sub(r'(от|парня|мальчика|мужчину|ищу|для)\s*18\b', '', text)
        safe_age = re.sub(r'\b18\s*-\s*\d{2}\b', '', safe_age) 
        safe_age = re.sub(r'\b18\s*\+', '', safe_age) 
        safe_age = re.sub(r'\b18\s*(см|cm)\b', '', safe_age) 
        
        if re.search(r'\b18\s*(лет|год|годик|y\.?o\.?)\b|\b18\s*[/\\-]\s*1\d{2}\b|\b(мне|я)\s*18\b', safe_age):
            bot.delete_message(chat_id, message.message_id)
            mute_user_everywhere(user_id, reason="Оранжевая зона: 18 лет", admin_name="Скайнет 🔞", user_link=user_link, trigger_text=trigger_text, origin_chat=chat_title)
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🛠 Пройти верификацию 🔞", url="https://t.me/FAQMKBOT"))
            warning_msg = bot.send_message(
                chat_id, 
                f"🚨 {user_link}, **Внимание!**\n"
                "Ваша анкета попала под автоматический фильтр безопасности сети.\n\n"
                "Для защиты участников чата, вам необходимо пройти обязательную верификацию. Вы временно ограничены в общении во всех группах сети до подтверждения профиля администрацией.", 
                reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True
            )
            
            def delete_warning_18():
                time.sleep(300)
                try: bot.delete_message(chat_id, warning_msg.message_id)
                except: pass
            threading.Thread(target=delete_warning_18, daemon=True).start()
            return

        # 6. СИНЯЯ ЗОНА: ТЕГИ (Без отчетов)
        new_tag = None

        age_match = re.search(r'\b(?:мне|я)\s*([1-9]\d)\b|\b([1-9]\d)\s*(?:лет|год|годик)\b|\b([1-9]\d)\s*[/\\-]\s*1\d{2}\b', text)
        if age_match:
            found_age = None
            for group in age_match.groups():
                if group:
                    found_age = int(group)
                    break
            if found_age and found_age >= 18: 
                saved_age = user_data.get("saved_age")
                if not saved_age:
                    users_collection.update_one({"_id": user_id}, {"$set": {"saved_age": found_age}})
                elif abs(saved_age - found_age) > 1: 
                    new_tag = "Параметры FAKE"

        if not new_tag:
            if "вирт" in text and "не вирт" not in text: new_tag = "РИСК/ВИРТ/ОБМЕН"
            elif any(re.search(fr'\b{word}\b', text) for word in ["вз", "обмен", "слить", "тц"]): 
                new_tag = "туалетная соска" if "тц" in text else "РИСК/ВИРТ/ОБМЕН"
            elif any(word in text for word in ["дроч", "фотками"]): new_tag = "РИСК/ВИРТ/ОБМЕН"
            elif any(word in text for word in ["в машине", "на авто", "на заднем", "тачка", "в тачке"]): new_tag = "автососка"
            elif any(word in text for word in ["туалет", "кабинка", "в кабинке", "глори", "glory"]): new_tag = "туалетная соска"
            elif any(word in text for word in ["нерусск", "кавказ", "восточн", "узбек", "таджик", "дагестан", "чечен", "чурк"]): 
                new_tag = "чернильница"

        if new_tag:
            try: 
                safe_set_tag(chat_id, user_id, new_tag)
                users_collection.update_one({"_id": user_id}, {"$set": {"shame_tag": new_tag}}, upsert=True)
            except: pass

    except Exception as e:
        print(f"Ошибка Единого Ядра: {e}")

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
            now = time.time()
            # Достаем всех, кто застрял в воронке
            for doc in db['vip_funnel'].find():
                user_id = doc['_id']
                timestamp = doc.get('timestamp', now)
                reminded = doc.get('reminded', False)
                
                # 1. Прошла неделя (7 дней = 604800 секунд) -> Шлем напоминалку
                if not reminded and (now - timestamp > 604800):
                    reminder_text = (
                        "⚠️ **Системное уведомление!**\n\n"
                        "Вы начали процесс вступления в VIP, но остановились. "
                        "Если вы не завершите верификацию или оплату, ваша заявка будет аннулирована, "
                        "а доступ к сети будет ограничен системой безопасности.\n\n"
                        "Ждем ваших действий! ⏱"
                    )
                    try:
                        bot.send_message(user_id, reminder_text, parse_mode="Markdown")
                    except: pass # Бот может быть заблокирован, пофиг, забаним через 3 дня
                    
                    # Ставим отметку, что напомнили, и сбрасываем таймер
                    db['vip_funnel'].update_one({"_id": user_id}, {"$set": {"reminded": True, "timestamp": now}})
                
                # 2. Прошло еще 3 дня (259200 секунд) после напоминалки -> КАЗНЬ
                elif reminded and (now - timestamp > 259200):
                    # Баним везде
                    ban_user_everywhere(user_id, reason="Не оплатил ВИП, тянул время", admin_name="Скайнет ⏱")
                    # Снимаем с мушки
                    db['vip_funnel'].delete_one({"_id": user_id})
        except Exception as e:
            print(f"Ошибка Снайпера: {e}")
            
        # Спим 12 часов до следующей проверки
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
@app.route('/glaz/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] == WEB_USER and request.form['password'] == WEB_PASS:
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            error = 'ОТКАЗАНО: Неверный маркер доступа!'
    return render_template('login.html', error=error)

@app.route('/glaz/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/glaz', methods=['GET', 'POST'])
def admin_panel():
    # Защита: Если не залогинен — выгоняем на страницу логина
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
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

                # Проверяем, является ли пользователь админом или создателем сети
                is_admin_system = (uid == OWNER_ID or uid in ADMIN_CHAT_IDS)

                user_data = {
                    "id": uid,
                    "is_vip": u_info.get("is_vip", False) if u_info else False,
                    "is_queer": u_info.get("is_queer", False) if u_info else False,
                    "is_verified": u_info.get("is_verified", False) if u_info else False,
                    "is_admin": is_admin_system,  # Передаем статус админа на фронтенд!
                    "main_city": u_info.get("main_city", "Не привязан") if u_info else "Не привязан",
                    "custom_tag": u_info.get("custom_tag", "Отсутствует") if u_info else "Отсутствует",
                    "shame_tag": u_info.get("shame_tag", "Отсутствует") if u_info else "Отсутствует",
                    "banned": True if b_info else False,
                    "ban_reason": detected_reason,
                    "history": history_list
                }
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
    """Секретный JSON-эндпоинт для фонового обновления цифр без перезагрузки"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "total": users_collection.count_documents({}),
        "vips": users_collection.count_documents({"is_vip": True}),
        "queers": users_collection.count_documents({"is_queer": True}),
        "banned": banned_collection.count_documents({})
    })

@app.route('/glaz/user_action', methods=['POST'])
def glaz_user_action():
    """Интеллектуальный фоновый обработчик кнопок досье (AJAX-JSON)"""
    if not session.get('logged_in'):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
        
    uid = int(request.form.get('uid'))
    action = request.form.get('action')
    msg = "Действие выполнено"
    
    if action == 'ban':
        ban_user_everywhere(uid, reason="Ликвидация через Web-Панель", admin_name="Web-Саурон 👁️")
        msg = f"💥 Пользователь {uid} полностью ликвидирован во всех чатах!"
    elif action == 'unban':
        unban_user_everywhere(uid)
        unmute_user_everywhere(uid)
        msg = f"🕊️ С пользователя {uid} успешно сняты все баны и муты."
    elif action == 'make_vip':
        users_collection.update_one({"_id": uid}, {"$set": {"is_vip": True}}, upsert=True)
        msg = f"👑 Пользователь {uid} успешно коронован (VIP выдано)!"
        try: bot.send_message(uid, "👑 Администрация выдала вам статус VIP через панель управления!")
        except: pass
    elif action == 'remove_vip':
        users_collection.update_one({"_id": uid}, {"$set": {"is_vip": False}})
        msg = f"❌ Корона снята. Статус VIP для {uid} аннулирован."
        try: bot.send_message(uid, "❌ Ваш статус VIP аннулирован администрацией.")
        except: pass
    elif action == 'make_queer':
        users_collection.update_one({"_id": uid}, {"$set": {"is_queer": True}}, upsert=True)
        msg = f"🏳️‍🌈 Пользователь {uid} добавлен в спец-клуб BEYOND!"
        try: bot.send_message(uid, "🏳️‍🌈 Администрация предоставила вам доступ к клубу BEYOND!")
        except: pass
    elif action == 'remove_queer':
        users_collection.update_one({"_id": uid}, {"$set": {"is_queer": False}})
        msg = f"⚠️ Пользователь {uid} удален из спец-клуба BEYOND."
    elif action == 'set_tag':
        new_tag = request.form.get('tag', '').strip()
        if new_tag and new_tag.lower() != 'none':
            users_collection.update_one({"_id": uid}, {"$set": {"custom_tag": new_tag}}, upsert=True)
            msg = f"🎖️ Пользователю присвоен новый кастомный тег: {new_tag}"
        else:
            users_collection.update_one({"_id": uid}, {"$unset": {"custom_tag": ""}})
            msg = "🧹 Кастомный тег успешно аннулирован."

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
            try: bot.send_message(uid, f"✅ Ваш запрос на вывод {amount}⭐️ одобрен! Деньги отправлены.")
            except: pass
        elif action == 'reject':
            withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "rejected"}})
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
    return redirect(url_for('admin_panel'))

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == '__main__':
    print("Бот запущен — мягкая версия с приветствием и удалением сообщений (кроме сети ПАРНИ)")
    app.run(host='0.0.0.0', port=5000)