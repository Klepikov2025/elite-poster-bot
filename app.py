import os
import telebot
import requests
from telebot import types
from flask import Flask, request
from datetime import datetime
import pymongo
from pymongo import MongoClient
import pytz
import random
import re
import time
import threading

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

ADMIN_CHAT_IDS = [479938867, 7235010425]
OWNER_ID = 479938867

# ==================== НАСТРОЙКИ VIP И РЕФЕРАЛКИ ====================
VIP_PRICE_STARS = 250

# ==================== НАСТРОЙКИ СЛУЖЕБНЫХ ЧАТОВ ====================
STAFF_GROUP_ID = -1002196190507
JOURNAL_CHAT_ID = -1002158861390

# ==================== БАЗА ДАННЫХ MONGODB ====================
MONGO_URI = os.getenv('MONGO_URI')
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client['elite_bot_db']

users_collection = db['users']               # Статистика и балансы рефералов
pending_refs_collection = db['pending_refs'] # Клики и ожидающие оплаты
banned_collection = db['banned']             # Черный список (забаненные)
posts_collection = db['posts']

# --- Функции общения с базой ---
def update_user_stats(user_id, invites_add=0, balance_add=0, clicks_add=0):
    users_collection.update_one(
        {"_id": user_id},
        {"$inc": {"invites": invites_add, "balance": balance_add, "clicks": clicks_add}},
        upsert=True
    )
withdrawals_collection = db['withdrawals']   # Заявки на вывод средств

def get_user_stats(user_id):
    user = users_collection.find_one({"_id": user_id})
    if user: return {'invites': user.get('invites', 0), 'balance': user.get('balance', 0), 'clicks': user.get('clicks', 0)}
    return {'invites': 0, 'balance': 0, 'clicks': 0}

def set_pending_ref(new_user_id, ref_id):
    pending_refs_collection.update_one({"_id": new_user_id}, {"$set": {"ref_id": ref_id}}, upsert=True)

def get_pending_ref(new_user_id):
    doc = pending_refs_collection.find_one({"_id": new_user_id})
    return doc['ref_id'] if doc else None

def delete_pending_ref(new_user_id):
    pending_refs_collection.delete_one({"_id": new_user_id})
# ==============================================================

def get_referral_bonus(invites_count):
    """Лестница бонусов: чем больше пригласил, тем выше процент"""
    if invites_count <= 10:   return 0.10, int(VIP_PRICE_STARS * 0.10)
    elif invites_count <= 30: return 0.13, int(VIP_PRICE_STARS * 0.13)
    elif invites_count <= 50: return 0.15, int(VIP_PRICE_STARS * 0.15)
    elif invites_count <= 100:return 0.17, int(VIP_PRICE_STARS * 0.17)
    else:                     return 0.20, int(VIP_PRICE_STARS * 0.20)

# Главный канал
MAIN_CHANNEL_ID = -1002246737442
MAIN_CHANNEL_USERNAME = "@clubofrm"
MAIN_CHANNEL_LINK = "https://t.me/clubofrm"

# Сеть ПАРНИ — полностью исключаем из всех проверок
PARNI_CHATS = {
    -1002413948841, -1002255622479, -1002274367832, -1002406302365,
    -1002280860973, -1002469285352, -1002287709568, -1002448909000,
    -1002261777025, -1002371438340
}

# ==================== СПИСКИ ЧАТОВ ====================
chat_ids_mk = {
    "Екатеринбург": -1002210043742,
    "Челябинск": -1002238514762,
    "БЕЗ ПРЕДРАССУДКОВ": -1001219669239,
    "RAINBOW MAN": -1003496028436,
    "Пермь": -1002205127231,
    "Ижевск": -1001604781452,
    "Казань": -1002228881675,
    "Оренбург": -1002255568202,
    "Уфа": -1002196469365,
    "Новосибирск": -1002235645677,
    "Красноярск": -1002248474008,
    "Барнаул": -1002234471215,
    "Омск": -1002151258573,
    "Саратов": -1002426762134,
    "Воронеж": -1002207503508,
    "Самара": -1001852671383,
    "Волгоград": -1002167762598,
    "Нижний Новгород": -1001631628911,
    "Калининград": -1002217056197,
    "Иркутск": -1002685095003,
    "Кемерово": -1002147522863,
    "Москва": -1002208434096,
    "Санкт-Петербург": -1002485776859, # <-- Добавлен дефис
    "Общая группа Юга": -1001814693664,
    
    # === ТРЮК С РЕГИОНАМИ ===
    "Тюмень": -1002210623988, # Заменили "Общую группу Тюмень и Север"
    "ХМАО": -1002210623988,   # Дублируем ID для серверных городов
    "ЯМАЛ": -1002210623988,   # Дублируем ID для серверных городов
    # ========================

    "Казахстан": -1003091556050,
    "Мужской Чат": -1002169723426,
    "Фетиши": -1002197215824,
    "Аренда Жилья": -1001238252865,
    "Секс Туризм": -1002236337328,
    "Галерея": -1002217967528,
    "Тестовая группа 🛠️": -1002426733876
}

chat_ids_parni = {
    "Екатеринбург": -1002413948841,
    "Тюмень": -1002255622479,
    "Омск": -1002274367832,
    "Челябинск": -1002406302365,
    "Пермь": -1002280860973,
    "Курган": -1002469285352,
    "ХМАО": -1002287709568,
    "Уфа": -1002448909000,
    "Новосибирск": -1002261777025,
    "ЯМАЛ": -1002371438340,
    "Оренбург": -1003888335997,
    "Москва": -1003856528145,
    "Санкт-Петербург": -1003519420984,
    "Красноярск": -1003347456711
}

chat_ids_ns = {
    "Новосибирск": -1001824149334,
    "Челябинск": -1002233108474,
    "Пермь": -1001753881279,
    "Уфа": -1001823390636,
    "ЯМАЛ": -1002145851794, # <-- Сделали капсом
    "Москва": -1001938448310,
    "ХМАО": -1001442597049,
    "Екатеринбург": -1002169473861, # Заменили "Знакомства 66"
    "Тюмень": -1002170955867,       # Заменили "Знакомства 72"
    "Санкт-Петербург": -1002335014334,
    
    # Так как в НС оказалось два Челябинска и две Тюмени, 
    # вторые группы называем с цифрой 2:
    "Тюмень 2": -1001427433513,     # Заменили "Секс Знакомства Тюмень"
    "Челябинск 2": -1002193127380   # Заменили "Знакомства 74"
}

chat_ids_rainbow = {
    "Екатеринбург": -1002419653224
}

chat_ids_gayznak = {
    "Красноярск": -1002335149925,
    "Екатеринбург": -1002571605722,
    "Пермь": -1002599206099,
    "Тюмень": -1002553431228,
    "Новосибирск": -1002627786446,
    "Самара": -1002301984331,
    "Казань": -1002277433049,
    "Воронеж": -1002428155161,
    "Кемерово": -1002418700136,
    "Иркутск": -1002454522264,
    "Челябинск": -1003366643944,
    "Орёл": -1003323558103,
    "Саратов": -1003638608363,
    "Архангельск": -1003120218775,
    "Ярославль": -1003332193158,
    "Тверь": -1003369813272,
    "Великий Новгород": -1003429766543,
    "Владимир": -1003276544901,
    "Мурманск": -1003302580641,
    "Рязань": -1003460247519,
    "Смоленск": -1003423811230,
    "Тамбов": -1003225139634,
    "Липецк": -1003487872172,
    "Тула": -1003482077625,
    "Брянск": -1003372917376,
    "Волгоград": -1002476113714
}

# ==================== АВТОГЕНЕРАЦИЯ all_cities ====================
# Уничтожили логику маппинга, так как теперь всё стандартизировано!
def normalize_city_name(name):
    return name 

all_cities = {}

def insert_to_all(city, net_key, real_name, chat_id):
    # Чтобы в "Все сети" не дублировались кнопки (Тюмень и Тюмень 2),
    # обрезаем " 2" и кладем всё в одну общую категорию для кнопок.
    clean_city = city.replace(" 2", "")
    
    if clean_city not in all_cities:
        all_cities[clean_city] = {}
    if net_key not in all_cities[clean_city]:
        all_cities[clean_city][net_key] = []
    all_cities[clean_city][net_key].append({"name": real_name, "chat_id": chat_id})

for city, chat_id in chat_ids_mk.items():
    insert_to_all(city, "mk", city, chat_id)
for city, chat_id in chat_ids_parni.items():
    insert_to_all(city, "parni", city, chat_id)
for city, chat_id in chat_ids_ns.items():
    insert_to_all(city, "ns", city, chat_id)
for city, chat_id in chat_ids_rainbow.items():
    insert_to_all(city, "rainbow", city, chat_id)
for city, chat_id in chat_ids_gayznak.items():
    insert_to_all(city, "gayznak", city, chat_id)

def net_key_to_name(key):
    return {
        "mk": "Мужской Клуб",
        "parni": "ПАРНИ 18+",
        "ns": "НС",
        "rainbow": "Радуга",
        "gayznak": "Гей Знакомства"
    }.get(key, key)

# Оставляем этот словарь пустым, чтобы не сломать функцию публикации!
ns_city_substitution = {}

VIP_CHAT_ID = -1002446486648
BEYOND_CHAT_ID = -1002873115881
VERIFICATION_LINK = "http://t.me/vip_znakbot"

responded = {}
scam_reports = {}  # ключ: report_id (случайный или timestamp+random), значение: {reporter_id, vip_id, chat_id, msg_id, responder_id, message_id_in_admin_chat}
pending_verification_users = {}
active_vip_requests = set()
safe_from_autoban = set() # Те, кто официально отказался

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def escape_md(text):
    escape_chars = r'\_*[]()~`>#+=|{}'
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

def clean_user_text(text):
    return re.sub(r'(?<=\d)\*(?=\d)', '×', text)

def is_banned_in_network(user_id):
    """Проверяет статус пользователя в самых крупных (якорных) чатах сети"""
    
    # Собираем актуальные крупные узлы для проверки:
    anchor_chats = [
        VIP_CHAT_ID,
        chat_ids_mk.get("БЕЗ ПРЕДРАССУДКОВ"), 
        chat_ids_mk.get("Москва"),            
        chat_ids_mk.get("Екатеринбург"),      
        chat_ids_parni.get("Екатеринбург")    
    ]
    
    # Очищаем список от пустых значений
    anchor_chats = [cid for cid in anchor_chats if cid]

    for chat_id in anchor_chats:
        try:
            member = bot.get_chat_member(chat_id, user_id)
            # Если статус "kicked" хотя бы в одном — не пускаем
            if member.status == "kicked":
                return True
        except:
            pass 
            
    return False

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("Создать новое объявление"))
    markup.add(types.KeyboardButton("Удалить объявление"), types.KeyboardButton("Удалить все объявления"))
    markup.add(types.KeyboardButton("👑 Вступить в VIP-чат"), types.KeyboardButton("👤 Партнерская программа"))
    return markup

def format_time(timestamp):
    tz = pytz.timezone('Asia/Yekaterinburg')
    local_time = timestamp.astimezone(tz)
    return local_time.strftime("%H:%M, %d %B %Y")

def get_user_name(user):
    name = escape_md(user.first_name)
    if user.username:
        return f"[{name}](https://t.me/{user.username})"
    else:
        return f"[{name}](tg://user?id={user.id})"

def safe_set_tag(chat_id, user_id, tag):
    """Безопасная выдача тегов без прав админа (обновление Telegram от Марта 2026)"""
    try:
        # Пробуем нативный метод (если библиотека обновлена)
        bot.set_chat_member_tag(chat_id, user_id, tag)
    except AttributeError:
        # Если библиотека старая, бьем напрямую в API Телеграма
        url = f"https://api.telegram.org/bot{TOKEN}/setChatMemberTag"
        requests.post(url, json={"chat_id": chat_id, "user_id": user_id, "tag": tag})

# ==================== МОДУЛЬ 2: УМНАЯ ТАМОЖНЯ + СТАТИСТИКА ====================
@bot.chat_join_request_handler()
def handle_join_requests(message: telebot.types.ChatJoinRequest):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # 1. ФИКСИРУЕМ ЗАЯВКУ В СТАТИСТИКЕ (Общая и по конкретному чату)
    db['network_stats'].update_one(
        {"_id": "current_period"}, 
        {"$inc": {"total": 1, f"chats.{chat_id}.total": 1}}, 
        upsert=True
    )
    
    try:
        # --- ФАЗА -1: Проверка Глобального Черного Списка ---
        if is_banned_in_network(user_id):
            bot.decline_chat_join_request(chat_id, user_id)
            return

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
        is_privileged = False
        for priv_chat in [VIP_CHAT_ID, BEYOND_CHAT_ID]:
            try:
                member = bot.get_chat_member(priv_chat, user_id)
                if member.status in ['member', 'administrator', 'creator']:
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

        # --- ФАЗА 3: Гео-контроль (Городские чаты) ---
        target_city = None
        for city_name, networks in all_cities.items():
            for net, groups in networks.items():
                if any(g['chat_id'] == chat_id for g in groups):
                    target_city = city_name
                    break
        
        if target_city and user_has_city_passport(user_id, target_city):
            bot.approve_chat_join_request(chat_id, user_id)
            db['network_stats'].update_one({"_id": "current_period"}, {"$inc": {"approved": 1, f"chats.{chat_id}.approved": 1}}, upsert=True)
            return

        # --- ФАЗА 4: Новички ---
        # Оставляем висеть в списке (ты одобришь их кнопкой "Одобрить все" 1-го или 15-го числа)
        pass

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
            send_vip_welcome(message.chat.id, message.from_user.first_name)

    except Exception as e:
        for admin_id in ADMIN_CHAT_IDS:
            try: bot.send_message(admin_id, f"Ошибка в /start: {e}")
            except: pass

# ==================== VIP И ПАРТНЕРКА ====================
@bot.message_handler(func=lambda message: message.text == "👑 Вступить в VIP-чат")
def handle_vip_join_button(message):
    send_vip_welcome(message.chat.id, message.from_user.first_name)

def send_vip_welcome(chat_id, first_name):
    welcome_text = (
        f"Приветствую, {escape_md(first_name)}! 👋\n\n"
        "Это бот отбора в ВИП-чат, вход после верификации (кружок с лицом) "
        f"и оплаты взноса {VIP_PRICE_STARS}⭐️ единоразово!\n\n"
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

# Юзер нажал "Запросить вывод"
@bot.callback_query_handler(func=lambda call: call.data == "request_withdrawal")
def start_withdrawal(call):
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

    # Создаем заявку в БД
    withdrawal_id = f"w_{int(time.time())}_{message.from_user.id}"
    withdrawals_collection.insert_one({
        "_id": withdrawal_id,
        "user_id": message.from_user.id,
        "amount": amount,
        "details": details,
        "status": "pending"
    })

    bot.send_message(message.chat.id, "✅ Заявка принята! Администратор проверит её в ближайшее время.")

    # Уведомляем админов в STAFF_GROUP
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

@bot.message_handler(commands=['ban'])
def handle_manual_ban(message):
    if message.chat.id != STAFF_GROUP_ID: return
    
    # Разбиваем текст максимум на 3 части: [команда, ID, всё остальное как причина]
    args = message.text.split(maxsplit=2)
    
    if len(args) < 2:
        bot.send_message(message.chat.id, "❌ Формат: `/ban [ID] [Причина]`\nПример: `/ban 123456789 Реклама`", parse_mode="Markdown")
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: ID должен состоять только из цифр!")
        return
        
    reason = args[2] if len(args) > 2 else "Не указана"
    admin_info = get_user_name(message.from_user)
    
    bot.send_message(message.chat.id, "🚀 Глобальный бан запущен...")
    count = ban_user_everywhere(target_id, reason, admin_info)
    bot.send_message(message.chat.id, f"✅ Готово! Юзер `{target_id}` забанен в {count} чатах. Отчет отправлен в Журнал.", parse_mode="Markdown")

@bot.message_handler(commands=['get_report'])
def get_detailed_report(message):
    if message.from_user.id != OWNER_ID: return
    
    stats = db['network_stats'].find_one({"_id": "current_period"})
    if not stats:
        bot.send_message(message.chat.id, "📊 Статистика за этот период пуста.")
        return

    total = stats.get('total', 0)
    approved = stats.get('approved', 0)
    vip_tickets = stats.get('vip_tickets', 0)
    
    # Считаем ручные одобрения и общее число юзеров в боте
    manual_pending = total - approved 
    total_bot_users = users_collection.count_documents({})
    
    chat_names = {}
    for city, cid in chat_ids_mk.items(): chat_names[cid] = f"МК | {city}"
    for city, cid in chat_ids_parni.items(): chat_names[cid] = f"ПАРНИ | {city}"
    for city, cid in chat_ids_ns.items(): chat_names[cid] = f"НС | {city}"
    for city, cid in chat_ids_rainbow.items(): chat_names[cid] = f"Радуга | {city}"
    for city, cid in chat_ids_gayznak.items(): chat_names[cid] = f"Гей Знакомства | {city}"
    chat_names[VIP_CHAT_ID] = "VIP Клуб"
    chat_names[BEYOND_CHAT_ID] = "BEYOND"

    city_details = ""
    chats_data = stats.get('chats', {})
    for cid_str, data in chats_data.items():
        cid = int(cid_str)
        name = chat_names.get(cid, f"Неизвестный чат ({cid})")
        c_total = data.get('total', 0)
        c_appr = data.get('approved', 0)
        c_manual = c_total - c_appr
        city_details += f"📍 {name}: {c_total} (авто: {c_appr} | ручками: {c_manual})\n"

    report_text = (
        f"📋 **Z-ОТЧЕТ СЕТИ (Период)**\n\n"
        f"🤖 **ЮЗЕРОВ В БОТЕ:** {total_bot_users}\n"
        f"📈 **ЗАЯВОК ВСЕГО:** {total}\n"
        f"✅ **АВТО-ВХОД:** {approved}\n"
        f"👑 **ЗОЛОТОЙ БИЛЕТ:** {vip_tickets}\n"
        f"⏳ **РУЧНОЕ ОДОБРЕНИЕ:** {manual_pending}\n\n"
        f"🏙 **ДЕТАЛИЗАЦИЯ:**\n{city_details}\n\n"
        f"📅 *Следующая выгрузка: 01.05.2026*"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🗑 Сбросить счетчики", callback_data="reset_stats"))
    bot.send_message(message.chat.id, report_text, reply_markup=markup)

@bot.message_handler(commands=['tag'])
def set_custom_user_tag(message):
    # --- ДИНАМИЧЕСКАЯ ПРОВЕРКА ПРАВ ---
    try:
        staff_member = bot.get_chat_member(STAFF_GROUP_ID, message.from_user.id)
        if staff_member.status not in ['administrator', 'creator']:
            bot.send_message(message.chat.id, "❌ Отказано. У вас нет прав доступа Скайнета.")
            return
    except Exception:
        return 
    # ----------------------------------

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.send_message(message.chat.id, "❌ Формат: `/tag [ID] [ТЕГ]`\nЧтобы убрать: `/tag [ID] none`", parse_mode="Markdown")
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: ID должен состоять только из цифр!")
        return

    new_tag = args[2]
    
    if new_tag.lower() == "none":
        users_collection.update_one({"_id": target_id}, {"$unset": {"custom_tag": ""}})
        bot.send_message(message.chat.id, f"✅ Глобальный тег для `{target_id}` успешно удален.")
    else:
        # 1. Записываем в базу (Память Скайнета)
        users_collection.update_one({"_id": target_id}, {"$set": {"custom_tag": new_tag}}, upsert=True)
        
        # 2. Глобальный авто-размут по всей сети!
        unmuted_count = unmute_user_everywhere(target_id)
        
        bot.send_message(message.chat.id, f"✅ Юзер `{target_id}` верифицирован как `{new_tag}` и глобально размучен в {unmuted_count} чатах!")

@bot.message_handler(commands=['unban'])
def global_unban_user(message):
    # --- ДИНАМИЧЕСКАЯ ПРОВЕРКА ПРАВ (только для админов Staff-группы) ---
    try:
        staff_member = bot.get_chat_member(STAFF_GROUP_ID, message.from_user.id)
        if staff_member.status not in ['administrator', 'creator']:
            bot.send_message(message.chat.id, "❌ Отказано. Вы не можете отдавать приказы Скайнету.")
            return
    except Exception:
        return 
    # -------------------------------------------------------------------

    args = message.text.split(maxsplit=2)
    
    if len(args) < 2:
        bot.send_message(message.chat.id, "❌ Формат: `/unban [ID] [НЕОБЯЗАТЕЛЬНО: ТЕГ]`\nПример: `/unban 123456 𝐑𝐄𝐀𝐋/𝐕𝐈𝐏♕`", parse_mode="Markdown")
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: ID должен состоять только из цифр!")
        return

    bot.send_message(message.chat.id, f"🔄 Запускаю протокол амнистии для `{target_id}`...")
    
    # 1. Глобальный разбан
    unbanned_count = unban_user_everywhere(target_id)
    
    # 2. Если админ передал тег — сразу вешаем его в базу!
    tag_info = ""
    if len(args) == 3:
        new_tag = args[2]
        if new_tag.lower() == "none":
            users_collection.update_one({"_id": target_id}, {"$unset": {"custom_tag": ""}})
            tag_info = "\n🔖 Глобальный тег очищен."
        else:
            users_collection.update_one({"_id": target_id}, {"$set": {"custom_tag": new_tag}}, upsert=True)
            tag_info = f"\n🔖 Присвоен новый тег: `{new_tag}`"
    
    bot.send_message(
        message.chat.id, 
        f"✅ **Амнистия завершена!**\nЮзер `{target_id}` вычеркнут из Черного Списка в {unbanned_count} чатах.{tag_info}\n\n"
        f"⚠️ *Передайте ему, что он может заново вступать в группы по ссылкам.*",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['admin'])
def promote_to_admin_global(message):
    # --- ДИНАМИЧЕСКАЯ ПРОВЕРКА ПРАВ (только для руководства) ---
    try:
        staff_member = bot.get_chat_member(STAFF_GROUP_ID, message.from_user.id)
        if staff_member.status not in ['administrator', 'creator']:
            bot.send_message(message.chat.id, "❌ Отказано. Только руководство может раздавать погоны.")
            return
    except Exception:
        return 
    # ------------------------------------------------------------

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.send_message(message.chat.id, "❌ Формат: `/admin [ID] [Должность]`\nПример: `/admin 123456789 прЫнц`", parse_mode="Markdown")
        return

    try:
        target_id = int(args[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: ID должен состоять только из цифр!")
        return

    custom_title = args[2]
    
    # Ограничение самого Телеграма: тег админа не может быть длиннее 16 символов
    if len(custom_title) > 16:
        bot.send_message(message.chat.id, "❌ Ошибка: Телеграм не позволяет делать тег админа длиннее 16 символов. Сократите название.")
        return
        
    bot.send_message(message.chat.id, f"🔄 Запускаю протокол «Коронация» для `{target_id}`.\nНазначаю права и должность «{custom_title}» по всей сети...", parse_mode="Markdown")

    # Собираем все чаты сети в единый список
    all_chats.extend(chat_ids_parni.values())
    all_chats.extend(chat_ids_mk.values())
    all_chats.extend(chat_ids_ns.values())
    all_chats.extend(chat_ids_rainbow.values())
    all_chats.extend(chat_ids_gayznak.values())

    # Превращаем в set, чтобы убрать дубли (например, Тюмень и ХМАО с одинаковым ID)
    unique_chats = set(all_chats)
    
    success_count = 0
    error_count = 0

    for cid in unique_chats:
        try:
            # 1. Выдаем базовые права модератора строго по скриншоту
            bot.promote_chat_member(
                chat_id=cid,
                user_id=target_id,
                can_manage_chat=True,        # (Обязательная галочка для API Телеграма)
                can_change_info=False,       # Изменение профиля группы: НЕТ ❌
                can_delete_messages=True,    # Удаление сообщений: ДА ✅
                can_restrict_members=True,   # Блокировка пользователей: ДА ✅
                can_invite_users=True,       # Добавление участников: ДА ✅
                can_pin_messages=False,      # Закрепление сообщений: НЕТ ❌
                can_manage_video_chats=True, # Управление видеочатами: ДА ✅
                is_anonymous=True,           # Анонимность: ДА ✅
                can_promote_members=False    # Добавление администраторов: НЕТ ❌
            )
            
            # 2. Устанавливаем кастомный тег (Должность)
            bot.set_chat_administrator_custom_title(
                chat_id=cid,
                user_id=target_id,
                custom_title=custom_title
            )
            success_count += 1
            
        except Exception as e:
            error_count += 1
            
        # Небольшая пауза, чтобы Телеграм не забанил бота за спам запросами
        time.sleep(1)

    bot.send_message(
        message.chat.id, 
        f"✅ **Коронация завершена!** 👑\n\n"
        f"Пользователь `{target_id}` назначен модератором в **{success_count}** чатах.\n"
        f"🔖 Выдана должность: `{custom_title}`\n\n"
        f"⚠️ *Ошибок/Пропусков: {error_count} (юзера нет в чате или у бота не хватает прав).*\n\n"
        f"**Важно:** Пусть новый админ добавится во все нужные чаты, если он еще не там, чтобы права применились корректно.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['unadmin'])
def demote_admin_global(message):
    # --- ДИНАМИЧЕСКАЯ ПРОВЕРКА ПРАВ (только для руководства) ---
    try:
        staff_member = bot.get_chat_member(STAFF_GROUP_ID, message.from_user.id)
        if staff_member.status not in ['administrator', 'creator']:
            bot.send_message(message.chat.id, "❌ Отказано. Только руководство может срывать погоны.")
            return
    except Exception:
        return 
    # ------------------------------------------------------------

    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "❌ Формат: `/unadmin [ID]`\nПример: `/unadmin 123456789`", parse_mode="Markdown")
        return

    try:
        target_id = int(args[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: ID должен состоять только из цифр!")
        return

    bot.send_message(message.chat.id, f"🔄 Запускаю протокол «Разжалование» для `{target_id}`...\nСнимаю права по всей сети...", parse_mode="Markdown")

    # Собираем все чаты (без VIP и BEYOND)
    all_chats = []
    all_chats.extend(chat_ids_parni.values())
    all_chats.extend(chat_ids_mk.values())
    all_chats.extend(chat_ids_ns.values())
    all_chats.extend(chat_ids_rainbow.values())
    all_chats.extend(chat_ids_gayznak.values())

    unique_chats = set(all_chats)
    
    success_count = 0
    error_count = 0

    for cid in unique_chats:
        try:
            # Снимаем абсолютно все права (ставим False)
            bot.promote_chat_member(
                chat_id=cid,
                user_id=target_id,
                can_manage_chat=False,
                can_change_info=False,
                can_delete_messages=False,
                can_restrict_members=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_video_chats=False,
                is_anonymous=False,
                can_promote_members=False
            )
            success_count += 1
        except Exception:
            error_count += 1
            
        time.sleep(1) # Пауза от спам-блока Телеграма

    bot.send_message(
        message.chat.id, 
        f"✅ **Разжалование завершено!** 📉\n\n"
        f"Пользователь `{target_id}` лишен прав модератора в **{success_count}** чатах.\n\n"
        f"⚠️ *Ошибок/Пропусков: {error_count} (юзер уже не админ или его нет в чате).* \n\n"
        f"**Важно:** Кастомный тег должности удаляется автоматически при снятии прав.",
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data == "reset_stats")
def reset_network_stats(call):
    if call.from_user.id != OWNER_ID: return
    db['network_stats'].delete_one({"_id": "current_period"})
    bot.edit_message_text("✅ Статистика обнулена. Начинаем новый отсчет!", call.message.chat.id, call.message.message_id)

# ==================== ВОРОНКА ВЕРИФИКАЦИИ ====================
@bot.callback_query_handler(func=lambda call: call.data == "start_verification")
def ask_for_video(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    
    # --- ВХОД В ВОРОНКУ СНАЙПЕРА (Засекаем время старта) ---
    db['vip_funnel'].update_one(
        {"_id": call.from_user.id},
        {"$set": {"timestamp": time.time(), "reminded": False}},
        upsert=True
    )
    # --------------------------------------------------------

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
    if not pending_verification_users.get(message.from_user.id):
        return # Игнорируем кружки, если человек не нажимал кнопку верификации

    # --- ОБНОВЛЯЕМ ТАЙМЕР В ВОРОНКЕ (Кружок прислан, даем еще время на оплату) ---
    db['vip_funnel'].update_one(
        {"_id": message.from_user.id}, 
        {"$set": {"timestamp": time.time(), "reminded": False}}
    )
    # -----------------------------------------------------------------------------

    # === ЗАХВАТ В ТРЕКЕР ===
    active_vip_requests.add(message.from_user.id)
    # =======================

    bot.send_message(message.chat.id, f"⏳ {escape_md(message.from_user.first_name)}, проверяем вашу анкету, подождите...")

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Одобрить (Счет на 250⭐️)", callback_data=f"vip_approve_{message.from_user.id}"),
        types.InlineKeyboardButton("🔄 Запросить повторно", callback_data=f"vip_retry_{message.from_user.id}"),
        types.InlineKeyboardButton("❌ Отказать (Нарушения)", callback_data=f"vip_reject_{message.from_user.id}"),
        types.InlineKeyboardButton("🔨 Забанить везде", callback_data=f"vip_ban_{message.from_user.id}")
    )

    for admin_id in ADMIN_CHAT_IDS:
        try:
            bot.send_message(admin_id, f"🚨 **Заявка в VIP!**\nОт: {get_user_name(message.from_user)}\nID: `{message.from_user.id}`", parse_mode="Markdown")
            bot.forward_message(admin_id, message.chat.id, message.message_id)
            bot.send_message(admin_id, "Действие:", reply_markup=markup)
        except:
            pass
    
    # Мы отключаем ожидание, но при нажатии "Повторно" включим его обратно
    pending_verification_users[message.from_user.id] = False

def ban_user_everywhere(target_id, reason="Без причины", admin_name="Система", user_link=None, trigger_text=None, origin_chat=None):
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
    
    if trigger_text:
        base_text += f"• **Улика:** _{escape_md(trigger_text[:150])}_\n"
        
    # ДВА РАЗНЫХ СООБЩЕНИЯ ДЛЯ РАЗНЫХ ЧАТОВ
    journal_text = base_text + f"• **Группы:** ({len(banned_in)} шт.)\n" + "\n".join(banned_in)
    staff_text = base_text + f"• **Забанен в группах:** {len(banned_in)} шт."
    
    # Отправляем простыню в журнал
    try: bot.send_message(JOURNAL_CHAT_ID, journal_text, parse_mode="Markdown")
    except: pass
    
    # Отправляем короткую сводку в рабочий чат
    try: bot.send_message(STAFF_GROUP_ID, staff_text, parse_mode="Markdown")
    except: pass
    
    return len(banned_in)

def unmute_user_everywhere(target_id):
    """Снимает мут с пользователя абсолютно во всех чатах сети"""
    # Собираем ID абсолютно всех чатов в один большой список
    all_chats = [VIP_CHAT_ID, BEYOND_CHAT_ID]
    all_chats.extend(chat_ids_parni.values())
    all_chats.extend(chat_ids_mk.values())
    all_chats.extend(chat_ids_ns.values())
    all_chats.extend(chat_ids_rainbow.values())
    all_chats.extend(chat_ids_gayznak.values())
    
    unmuted_count = 0
    for cid in all_chats:
        try:
            # Возвращаем человеку все права: писать текст, слать медиа, стикеры и ссылки
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
            
    return unmuted_count

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
            
    return unbanned_count

# --- ФУНКЦИЯ: ГЛОБАЛЬНЫЙ МУТ (ДЛЯ РЕКЛАМЩИКОВ И НАРУШИТЕЛЕЙ) ---
def mute_user_everywhere(target_id, reason="Без причины", admin_name="Система", user_link=None, trigger_text=None, mute_time=0, origin_chat=None):
    chats_to_mute = {VIP_CHAT_ID: "VIP Клуб", BEYOND_CHAT_ID: "BEYOND"}
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
        
    if trigger_text:
        base_text += f"• **Улика:** _{escape_md(trigger_text[:150])}_\n"
        
    # ДВА РАЗНЫХ СООБЩЕНИЯ ДЛЯ РАЗНЫХ ЧАТОВ
    journal_text = base_text + f"• **Группы:** ({len(muted_in)} шт.)\n" + "\n".join(muted_in)
    staff_text = base_text + f"• **Замучен в группах:** {len(muted_in)} шт."
    
    # Отправляем простыню в журнал
    try: bot.send_message(JOURNAL_CHAT_ID, journal_text, parse_mode="Markdown")
    except: pass
    
    # Отправляем короткую сводку в рабочий чат
    try: bot.send_message(STAFF_GROUP_ID, staff_text, parse_mode="Markdown")
    except: pass
    
    return len(muted_in)

# --- ФУНКЦИЯ: ПРОВЕРКА "ПРОПИСКИ" В ГОРОДАХ ---
def user_has_city_passport(user_id, target_city):
    """Ищет юзера в других сетях в том же самом городе"""
    for network_key, cities in all_cities.get(target_city, {}).items():
        for group in cities:
            try:
                member = bot.get_chat_member(group['chat_id'], user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    return True
            except:
                continue
    return False

# --- ОБРАБОТКА ОТКАЗА ОТ ВЕРИФИКАЦИИ ---
@bot.message_handler(func=lambda message: message.text and message.text.strip().lower() in ["я отказываюсь от продолжения", "отказываюсь от продолжения"])
def handle_refusal(message):
    if message.chat.type != "private": return
    
    user_id = message.from_user.id
    safe_from_autoban.add(user_id)  
    pending_verification_users[user_id] = False 
    
    # --- СНИМАЕМ С МУШКИ СНАЙПЕРА (ОТКАЗАЛСЯ САМ) ---
    db['vip_funnel'].delete_one({"_id": user_id})
    # ------------------------------------------------
    
    bot.send_message(
        message.chat.id, 
        "✅ Ваша заявка аннулирована. Вы можете безопасно заблокировать бота, автоматической блокировки в сетях-партнерах не будет."
    )

# Действия админа (Одобрить / Повторно / Отказать / Забанить)
@bot.callback_query_handler(func=lambda call: call.data.startswith(("vip_approve_", "vip_retry_", "vip_reject_", "vip_ban_")))
def handle_vip_decision(call):
    action, user_id_str = call.data.rsplit("_", 1)
    user_id = int(user_id_str)
    
    # === 1. ЗАЩИТА ОТ ГОНКИ АДМИНОВ ===
    if user_id not in active_vip_requests:
        bot.answer_callback_query(call.id, "❌ Коллега уже обработал эту заявку!", show_alert=True)
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        return

    # Удаляем из активных, чтобы второй админ уже не смог нажать
    active_vip_requests.remove(user_id)
    # ==================================

    # Убираем кнопки у текущего админа сразу после нажатия
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except: pass
    
    admin_info = get_user_name(call.from_user)

    # === 2. УВЕДОМЛЕНИЕ ДЛЯ КОЛЛЕГ ===
    status_text = ""
    if "approve" in action: status_text = "✅ Одобрена (счет)"
    elif "retry" in action: status_text = "🔄 Запрошен повтор"
    elif "reject" in action: status_text = "❌ Отклонена"
    elif "ban" in action: status_text = "🔨 Забанен"

    notification_text = (
        f"📢 **Статус заявки изменен**\n"
        f"👤 Юзер: `{user_id}`\n"
        f"📝 Итог: {status_text}\n"
        f"👮‍♂️ Модератор: {admin_info}"
    )
    # Отправляем уведомление всем админам, КРОМЕ того, кто сейчас нажал кнопку 
    for admin_id in ADMIN_CHAT_IDS:
        if admin_id != call.message.chat.id:
            try: bot.send_message(admin_id, notification_text, parse_mode="Markdown")
            except: pass
    # ==================================

    # --- ОДОБРЕНИЕ (ВЫСТАВЛЕНИЕ СЧЕТА) ---
    if "approve" in action:
        # Информационное сообщение о выгодной покупке звезд
        cheap_stars_text = (
            "💡 **Лайфхак: Как купить звёзды ДЕШЕВЛЕ официального курса?**\n\n"
            "Перед оплатой рекомендуем приобрести звёзды через проверенный сервис. "
            "Это выйдет значительно выгоднее, чем покупать их напрямую через Telegram.\n\n"
            "**Инструкция:**\n"
            "1️⃣ Перейдите по ссылке: https://t.me/Avrrorkastarbot?start=7924963993\n"
            "2️⃣ Нажмите кнопку «⭐️ Купить звезды»\n"
            "3️⃣ Выберите пункт «👤 Себе»\n"
            "4️⃣ Выберите пакет «⭐️ 250 звезд»\n"
            "5️⃣ Оплатите удобным способом\n\n"
            "После покупки возвращайтесь сюда и оплачивайте VIP-доступ счетом ниже! 👇"
        )
        try:
            bot.send_message(user_id, cheap_stars_text, parse_mode="Markdown", disable_web_page_preview=True)
        except:
            pass

        # Отправка счета на оплату
        try:
            bot.send_invoice(
                user_id, 
                title="Вход в VIP Клуб 👑", 
                description="Оплата доступа в закрытый чат.", 
                invoice_payload="vip_access_payment", 
                provider_token="", 
                currency="XTR", 
                prices=[types.LabeledPrice(label="VIP Доступ", amount=VIP_PRICE_STARS)]
            )
            bot.send_message(call.message.chat.id, f"✅ Счет отправлен пользователю {user_id}.")
        except Exception as e:
            if "bot was blocked by the user" in str(e):
                # Проверка: если юзер заблокировал бота, проверяем, отказался ли он официально
                if user_id in safe_from_autoban:
                    bot.send_message(call.message.chat.id, f"ℹ️ Юзер {user_id} заблокировал бота, НО он официально отказался. Бан отменен.")
                    safe_from_autoban.remove(user_id) 
                else:
                    bot.send_message(call.message.chat.id, f"🚨 Юзер {user_id} заблокировал бота БЕЗ отказа! Авто-бан активирован.")
                    ban_user_everywhere(user_id, reason="Блокировка бота при верификации", admin_name="Auto-Defender")
            else:
                bot.send_message(call.message.chat.id, f"❌ Ошибка отправки счета: {e}")

    # --- ЗАПРОСИТЬ ПОВТОРНО (НОВАЯ ЛОГИКА) ---
    elif "retry" in action:
        bot.send_message(call.message.chat.id, f"🔄 Запрос на повторный кружок отправлен пользователю {user_id}.")
        
        retry_text = (
            "⚠️ **Ваш кружок не принят**\n\n"
            "К сожалению, видео не соответствует требованиям (неверная дата/время, не слышно голоса или не видно лица).\n\n"
            "Пожалуйста, **запишите кружок повторно**, четко сказав:\n"
            "💬 *«Привет админам вип-чата, сегодня [назовите дату], на часах [назовите время], хочу стать вип-участником»*"
        )
        try:
            bot.send_message(user_id, retry_text, parse_mode="Markdown")
            # Возвращаем юзера в режим ожидания кружка
            pending_verification_users[user_id] = True
        except:
            bot.send_message(call.message.chat.id, f"❌ Не удалось отправить уведомление пользователю {user_id} (возможно, бот заблокирован).")

    # --- ОТКАЗ ---
    elif "reject" in action:
        bot.send_message(call.message.chat.id, f"❌ Вы отклонили заявку {user_id}.")
        
        # --- СНИМАЕМ С МУШКИ СНАЙПЕРА (ОТКАЗ) ---
        db['vip_funnel'].delete_one({"_id": user_id})
        # ----------------------------------------
        
        try:
            bot.send_message(user_id, "К сожалению, ваша заявка отклонена из-за нарушений.")
        except:
            pass

    # --- БАН ВЕЗДЕ ---
    elif "ban" in action:
        bot.send_message(call.message.chat.id, "🔨 Запускаю массовый бан...")
        
        # --- СНИМАЕМ С МУШКИ СНАЙПЕРА (БАН) ---
        db['vip_funnel'].delete_one({"_id": user_id})
        # --------------------------------------
        
        count = ban_user_everywhere(user_id, reason="Не прошел модерацию кружка (бан админом)", admin_name=admin_info)
        bot.send_message(call.message.chat.id, f"✅ Пользователь забанен в {count} чатах.")

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
        # Списываем баланс в БД
        update_user_stats(user_id, balance_add=-amount)
        withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "paid"}})
        
        bot.send_message(user_id, f"✅ Ваш запрос на вывод {amount} звезд одобрен! Деньги отправлены на ваши реквизиты.")
        bot.edit_message_text(call.message.text + f"\n\n✅ **ОПЛАЧЕНО:** {admin_info}", STAFF_GROUP_ID, call.message.message_id)
        
    elif action == "reject":
        withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "rejected"}})
        bot.send_message(user_id, "❌ Ваш запрос на вывод средств был отклонен администрацией.")
        bot.edit_message_text(call.message.text + f"\n\n❌ **ОТКЛОНЕНО:** {admin_info}", STAFF_GROUP_ID, call.message.message_id)

# ==================== ОПЛАТА И ССЫЛКА ====================
@bot.pre_checkout_query_handler(func=lambda query: query.invoice_payload == "vip_access_payment")
def checkout_process(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def successful_payment(message):
    new_user_id = message.from_user.id
    
    # --- СНИМАЕМ С МУШКИ СНАЙПЕРА (ОПЛАТИЛ) ---
    db['vip_funnel'].delete_one({"_id": new_user_id})
    # ------------------------------------------
    
    # 1. Генерируем ссылку
    try:
        invite = bot.create_chat_invite_link(VIP_CHAT_ID, member_limit=1)
        
        # Прячем ссылку в красивый Markdown-формат [Текст](URL)
        bot.send_message(
            new_user_id, 
            f"🎉 *Оплата получена! Добро пожаловать в элиту.*\n\n👉 [НАЖМИТЕ СЮДА ДЛЯ ВХОДА В VIP-КЛУБ]({invite.invite_link})", 
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        bot.send_message(new_user_id, "Оплата прошла, но возникла ошибка со ссылкой. Напиши админу!")
        for admin_id in ADMIN_CHAT_IDS: 
            try:
                bot.send_message(admin_id, f"🚨 Ошибка создания ссылки: {e}")
            except:
                pass

    # 2. Бонус рефоводу (ЧЕРЕЗ БАЗУ ДАННЫХ)
    ref_id = get_pending_ref(new_user_id)
    if ref_id:
        update_user_stats(ref_id, invites_add=1) # Прибавили успешную оплату
        stats = get_user_stats(ref_id)           # Взяли свежие данные
        _, bonus_stars = get_referral_bonus(stats['invites']) # Посчитали бонус (percent не используем, заменил на _)
        
        update_user_stats(ref_id, balance_add=bonus_stars) # Начислили звезды на баланс
        
        try:
            bot.send_message(ref_id, f"🥳 **Твой друг оплатил VIP!**\nТебе начислено: **{bonus_stars} звезд** ⭐️", parse_mode="Markdown")
        except:
            pass
        delete_pending_ref(new_user_id) # Очистили ожидание

@bot.message_handler(func=lambda message: message.text == "Создать новое объявление")
def create_new_post(message):
    if message.chat.type != "private":
        bot.send_message(message.chat.id, "Пожалуйста, используйте ЛС для работы с ботом.")
        return

    if is_banned_in_network(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 Вы не можете публиковать объявления. Ваш аккаунт заблокирован в сети.")
        return

    bot.send_message(message.chat.id, "Напишите текст объявления:")
    bot.register_next_step_handler(message, process_text)

@bot.message_handler(func=lambda message: message.text == "Удалить объявление")
def handle_delete_post(message):
    if message.chat.type != "private": return
    
    user_id = message.from_user.id
    posts = list(posts_collection.find({"user_id": user_id}))
    
    if posts:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        for post in posts:
            time_formatted = format_time(post["time"])
            button_text = f"Удалить: {time_formatted}, {post['city']}, {post['network']}"
            markup.add(button_text)
        markup.add("Отмена")
        bot.send_message(message.chat.id, "Выберите объявление для удаления:", reply_markup=markup)
        bot.register_next_step_handler(message, process_delete_choice)
    else:
        bot.send_message(message.chat.id, "❌ У вас нет опубликованных объявлений.")

@bot.message_handler(func=lambda message: message.text == "Удалить все объявления")
def handle_delete_all_posts(message):
    if message.chat.type != "private": return
    
    user_id = message.from_user.id
    posts = list(posts_collection.find({"user_id": user_id}))
    
    if posts:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("Да, удалить всё", "Нет, отменить")
        bot.send_message(message.chat.id, "Вы уверены, что хотите удалить все свои объявления?", reply_markup=markup)
        bot.register_next_step_handler(message, process_delete_all_choice)
    else:
        bot.send_message(message.chat.id, "❌ У вас нет опубликованных объявлений.")

def process_delete_choice(message):
    if message.text == "Отмена":
        bot.send_message(message.chat.id, "Удаление отменено.", reply_markup=get_main_keyboard())
        return

    user_id = message.from_user.id
    posts = list(posts_collection.find({"user_id": user_id}))
    
    for post in posts:
        time_formatted = format_time(post["time"])
        if message.text == f"Удалить: {time_formatted}, {post['city']}, {post['network']}":
            try:
                bot.delete_message(post["chat_id"], post["message_id"])
            except: pass
            
            posts_collection.delete_one({"_id": post["_id"]})
            bot.send_message(message.chat.id, "✅ Объявление успешно удалено.", reply_markup=get_main_keyboard())
            return
            
    bot.send_message(message.chat.id, "❌ Объявление не найдено.")

def process_delete_all_choice(message):
    user_id = message.from_user.id
    if message.text == "Да, удалить всё":
        posts = list(posts_collection.find({"user_id": user_id}))
        for post in posts:
            try:
                bot.delete_message(post["chat_id"], post["message_id"])
            except: pass
        
        posts_collection.delete_many({"user_id": user_id})
        bot.send_message(message.chat.id, "✅ Все ваши объявления успешно удалены.", reply_markup=get_main_keyboard())
    else:
        bot.send_message(message.chat.id, "Удаление отменено.", reply_markup=get_main_keyboard())

def process_text(message):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "Вы вернулись в главное меню.", reply_markup=get_main_keyboard())
        return

    if message.photo or message.video:
        if message.photo:
            media_type = "photo"
            file_id = message.photo[-1].file_id
            text = message.caption if message.caption else ""
        elif message.video:
            media_type = "video"
            file_id = message.video.file_id
            text = message.caption if message.caption else ""
    elif message.text:
        media_type = None
        file_id = None
        text = message.text
    else:
        bot.send_message(message.chat.id, "❌ Ошибка! Отправьте текст, фото или видео.")
        bot.register_next_step_handler(message, process_text)
        return

    confirm_text(message, text, media_type, file_id)

def confirm_text(message, text, media_type=None, file_id=None):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Да", "Нет")
    bot.send_message(message.chat.id, f"Ваш текст:\n{text}\n\nВсё верно?", reply_markup=markup)
    bot.register_next_step_handler(message, handle_confirmation, text, media_type, file_id)

def handle_confirmation(message, text, media_type, file_id):
    if message.text.lower() == "да":
        bot.send_message(message.chat.id, "📋 Выберите сеть для публикации:", reply_markup=get_network_markup())
        bot.register_next_step_handler(message, select_network, text, media_type, file_id)
    elif message.text.lower() == "нет":
        bot.send_message(message.chat.id, "Хорошо, напишите текст объявления заново:")
        bot.register_next_step_handler(message, process_text)
    else:
        bot.send_message(message.chat.id, "❌ Неверный ответ. Выберите 'Да' или 'Нет'.")
        bot.register_next_step_handler(message, handle_confirmation, text, media_type, file_id)

def get_network_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Создать новое объявление", "Удалить объявление", "Удалить все объявления")
    network_row = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Мужской Клуб", "ПАРНИ 18+", "НС", "Радуга", "Гей Знакомства", "Все сети", "Назад")
    return markup

def select_network(message, text, media_type, file_id):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "Напишите текст объявления:")
        bot.register_next_step_handler(message, process_text)
        return

    selected_network = message.text
    if selected_network in ["Мужской Клуб", "ПАРНИ 18+", "НС", "Радуга", "Гей Знакомства", "Все сети"]:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True, row_width=2)
        if selected_network == "Мужской Клуб":
            cities = list(chat_ids_mk.keys())
        elif selected_network == "ПАРНИ 18+":
            cities = list(chat_ids_parni.keys())
        elif selected_network == "НС":
            cities = list(chat_ids_ns.keys())
        elif selected_network == "Радуга":
            cities = list(chat_ids_rainbow.keys())
        elif selected_network == "Гей Знакомства":
            cities = list(chat_ids_gayznak.keys())
        elif selected_network == "Все сети":
            cities = [city for city, data in all_cities.items() if len(data.keys()) >= 2]
        for city in cities:
            markup.add(city)
        markup.add("Выбрать другую сеть", "Назад")
        bot.send_message(message.chat.id, "📍 Выберите город для публикации или нажмите 'Выбрать другую сеть':", reply_markup=markup)
        bot.register_next_step_handler(message, select_city_and_publish, text, selected_network, media_type, file_id)
    else:
        bot.send_message(message.chat.id, "❌ Ошибка! Выберите правильную сеть.")
        bot.register_next_step_handler(message, process_text)

def select_city_and_publish(message, text, selected_network, media_type, file_id):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "📋 Выберите сеть для публикации:", reply_markup=get_network_markup())
        bot.register_next_step_handler(message, select_network, text, media_type, file_id)
        return

    city = message.text
    if city == "Выбрать другую сеть":
        bot.send_message(message.chat.id, "📋 Выберите сеть для публикации:", reply_markup=get_network_markup())
        bot.register_next_step_handler(message, select_network, text, media_type, file_id)
        return

    try:
        user_id = message.from_user.id
        is_privileged = False

        user_data = users_collection.find_one({"_id": user_id}) or {}
        if user_data.get("custom_tag"):
            is_privileged = True

        if not is_privileged:
            try:
                status = bot.get_chat_member(VIP_CHAT_ID, user_id).status
                if status in ["member", "administrator", "creator", "restricted"]:
                    is_privileged = True
            except: pass

        if is_privileged:
            vip_tag = "\n\n✅ *Анкета проверена администрацией сети*\n\n⭐️ *Привилегированный участник* ⭐️"

            user_name_md = get_user_name(message.from_user)

            headers = [
                f"💎 VIP-СООБЩЕНИЕ от {user_name_md}! 💎",
                f"🚨 🔥 Срочное объявление от {user_name_md}! 🚨",
                f"👑 {user_name_md} публикует элитное объявление: 👑",
                f"🌟 Особое сообщение от привилегированного пользователя {user_name_md}: 🌟",
                f"🔒 Только для избранных: сообщение от {user_name_md} 🔒",
                f"📣 Важное объявление от {user_name_md}!",
                f"🌐 Объявление уровня PREMIUM от {user_name_md}!",
                f"📢 Привилегированное сообщение от {user_name_md}:",
                f"🛑 Эксклюзив! {user_name_md} пишет:",
                f"💼 Серьёзное объявление от проверенного участника {user_name_md}",
                f"💠 {user_name_md} публикует объявление с высоким приоритетом",
                f"🪙 {user_name_md} использует привилегию VIP для объявления:",
                f"⚠️ Срочно на всех экранах: {user_name_md} врывается с объявлением!",
                f"🔥 {user_name_md} бросает вызов одиночеству!",
                f"🚀 {user_name_md} не ждёт — он действует! Объявление внутри:",
                f"🥵 Горячо! {user_name_md} делится откровенным сообщением:",
                f"⚡ Найдено ВИП-сообщение! Проверь, что пишет {user_name_md}",
                f"🧿 Внимание! VIP-сообщение от {user_name_md}",
                f"🏷️ Объявление с особыми правами: {user_name_md}"
            ]
            full_text = f"{random.choice(headers)}\n\n{escape_md(clean_user_text(text))}{vip_tag}"

            markup_inline = types.InlineKeyboardMarkup()
            markup_inline.add(
                types.InlineKeyboardButton(
                    text="Откликнуться ♥",
                    callback_data="respond",
                    icon_custom_emoji_id="6088882892526587287",   
                    style="success"          
                )
            )

            target_chats = []

            if selected_network == "Все сети":
                for net_key, groups in all_cities.get(city, {}).items():
                    for group in groups:
                        target_chats.append((group['chat_id'], net_key_to_name(net_key)))
            else:
                chat_id = None
                if selected_network == "Мужской Клуб": chat_id = chat_ids_mk.get(city)
                elif selected_network == "ПАРНИ 18+": chat_id = chat_ids_parni.get(city)
                elif selected_network == "НС": chat_id = chat_ids_ns.get(city)
                elif selected_network == "Радуга": chat_id = chat_ids_rainbow.get(city)
                elif selected_network == "Гей Знакомства": chat_id = chat_ids_gayznak.get(city)
                
                if chat_id:
                    target_chats.append((chat_id, selected_network))
                else:
                    bot.send_message(message.chat.id, f"❌ Ошибка! Город '{city}' не найден в сети «{selected_network}».")
                    ask_for_new_post(message)
                    return

            for chat_id, network_name in target_chats:
                try:
                    if media_type == "photo":
                        sent_message = bot.send_photo(chat_id, file_id, caption=full_text, parse_mode="Markdown", reply_markup=markup_inline)
                    elif media_type == "video":
                        sent_message = bot.send_video(chat_id, file_id, caption=full_text, parse_mode="Markdown", reply_markup=markup_inline)
                    else:
                        sent_message = bot.send_message(chat_id, full_text, parse_mode="Markdown", reply_markup=markup_inline)

                    post_data = {
                        "user_id": user_id,
                        "message_id": sent_message.message_id,
                        "chat_id": chat_id,
                        "time": datetime.now(),
                        "city": city,
                        "network": network_name
                    }
                    posts_collection.insert_one(post_data)
                    
                    bot.send_message(message.chat.id, f"✅ Ваше объявление опубликовано в сети «{network_name}», городе {city}.")
                except telebot.apihelper.ApiTelegramException as e:
                    bot.send_message(message.chat.id, f"❌ Ошибка отправки в {network_name}: {e.description}")

            ask_for_new_post(message)

        else:
            markup = types.InlineKeyboardMarkup()
            verify_button = types.InlineKeyboardButton(
                text="🛠️ Пройти верификацию",
                callback_data="start_verification", 
                style="danger"          
            )
            markup.add(verify_button)
            
            bot.send_message(
                message.chat.id, 
                "🔓 Вы не являетесь привилегированным участником.\n\n"
                "Для публикации элитных объявлений необходимо получить статус VIP. "
                "Пройдите быструю верификацию прямо здесь:", 
                reply_markup=markup
            )

    except telebot.apihelper.ApiTelegramException as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка при проверке VIP-статуса: {e.description}")

def ask_for_new_post(message):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Да", "Нет")
    bot.send_message(message.chat.id, "Хотите создать еще одно объявление?", reply_markup=markup)
    bot.register_next_step_handler(message, handle_new_post_choice)

def handle_new_post_choice(message):
    if message.text.lower() == "да":
        bot.send_message(message.chat.id, "Напишите текст объявления:")
        bot.register_next_step_handler(message, process_text)
    else:
        bot.send_message(
            message.chat.id,
            "Спасибо за использование бота! 🙌\nЕсли хотите создать новое объявление, нажмите кнопку ниже.",
            reply_markup=get_main_keyboard()
        )

@bot.callback_query_handler(func=lambda call: call.data == "respond")
def handle_respond(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    user_id = call.from_user.id
    responder = call.from_user  

    post = posts_collection.find_one({"chat_id": chat_id, "message_id": msg_id})
    
    if not post:
        bot.answer_callback_query(call.id, "Ошибка: Объявление устарело или было удалено.", show_alert=True)
        return

    vip_id = post["user_id"]

    key = (chat_id, msg_id)
    if key not in responded:
        responded[key] = set()

    if user_id in responded[key]:
        bot.answer_callback_query(call.id, "Вы уже откликались на это объявление.")
        return

    if not responder.username:
        bot.answer_callback_query(
            callback_query_id=call.id,
            text="❌ Отклик запрещён!\n\n"
                 "У вас скрыт @username в настройках приватности.\n\n"
                 "Чтобы откликаться на VIP-объявления — откройте его:\n"
                 "Настройки → Конфиденциальность и безопасность → "
                 "«Пересылка сообщений» → выбрать «Всем»",
            show_alert=True
        )
        return

    responded[key].add(user_id)

    if responder.username:
        name = f"[{escape_md(responder.first_name)}](https://t.me/{responder.username})"
    else:
        name = f"[{escape_md(responder.first_name)}](tg://user?id={user_id})"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            text="🚨 Это спам / скам / мошенник",
            callback_data=f"report_scam_{chat_id}_{msg_id}_{user_id}",
            style="danger"          
        )
    )

    try:
        bot.send_message(
            vip_id,
            f"Вами заинтересовался {name}",
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception as e:
        for admin_id in ADMIN_CHAT_IDS:
            try: bot.send_message(admin_id, f"❗️Не удалось уведомить VIP {vip_id}: {e}")
            except Exception: pass

    bot.answer_callback_query(call.id, "✅ Ваш отклик отправлен!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("report_scam_"))
def handle_report_scam(call):
    try:
        parts = call.data.split("_")
        if len(parts) < 5 or parts[0] != "report" or parts[1] != "scam":
            bot.answer_callback_query(call.id, "Неверный формат", show_alert=True)
            return

        chat_id     = int(parts[2])
        msg_id      = int(parts[3])
        responder_id = int(parts[4])   # тот, на кого жалуются

        reporter = call.from_user
        reporter_link = get_user_name(reporter)

        channel_part = str(chat_id)[4:] if str(chat_id).startswith("-100") else str(chat_id)
        ann_link = f"https://t.me/c/{channel_part}/{msg_id}"
        user_link = f"tg://user?id={responder_id}"

        report_time = datetime.now(pytz.timezone('Asia/Yekaterinburg')).strftime('%Y-%m-%d %H:%M:%S')

        text = (
            f"🚨 ЖАЛОБА НА СПАМ/СКАМ\n\n"
            f"От: {reporter_link}\n"
            f"На пользователя: [{responder_id}]({user_link})\n"
            f"Объявление: {ann_link}\n"
            f"Время: {report_time}\n\n"
            f"👇 Выберите действие:"
        )

        # Уникальный идентификатор жалобы
        report_id = f"{chat_id}_{msg_id}_{responder_id}_{int(time.time())}"

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Принять жалобу", callback_data=f"scam_accept_{report_id}"),
            types.InlineKeyboardButton("❌ Отклонить",      callback_data=f"scam_reject_{report_id}"),
        )
        markup.add(
            types.InlineKeyboardButton("ℹ️ Нужны детали",   callback_data=f"scam_details_{report_id}"),
        )

        # Сохраняем информацию о жалобе
        scam_reports[report_id] = {
            "reporter_id": reporter.id,
            "vip_id": post_owner.get((chat_id, msg_id), None),   # кто опубликовал объявление
            "chat_id": chat_id,
            "msg_id": msg_id,
            "responder_id": responder_id,
            "reporter_link": reporter_link,
            "ann_link": ann_link,
            "time": report_time
        }

        # Отправляем жалобу всем админам
        for admin_id in ADMIN_CHAT_IDS:
            try:
                bot.send_message(
                    admin_id,
                    text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                    reply_markup=markup
                )
            except Exception as e:
                print(f"Не удалось отправить жалобу админу {admin_id}: {e}")

        bot.answer_callback_query(call.id, "Жалоба отправлена администрации", show_alert=False)

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка обработки жалобы\n{e}", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("scam_accept_", "scam_reject_", "scam_details_")))
def handle_scam_admin_response(call):
    try:
        parts = call.data.split("_", 2)
        action = parts[1]         # accept / reject / details
        report_id = parts[2]

        if report_id not in scam_reports:
            bot.answer_callback_query(call.id, "Жалоба уже обработана или не найдена", show_alert=True)
            return

        report = scam_reports[report_id]
        vip_id = report.get("vip_id")
        responder_id = report.get("responder_id") # Тот, на кого пожаловались
        admin_info = get_user_name(call.from_user) # Кто из админов нажал кнопку

        if not vip_id:
            bot.answer_callback_query(call.id, "Не удалось определить автора объявления", show_alert=True)
            return

        ann_link = report["ann_link"]

        if action == "accept":
            # --- МАГИЯ АВТОМАТИЗАЦИИ ---
            bot.answer_callback_query(call.id, "🚀 Запускаю массовый бан скамера...")
            
            # 1. Запускаем наш "ядерный чемоданчик" банов
            reason = f"Жалоба на скам в объявлении {ann_link}"
            count = ban_user_everywhere(responder_id, reason=reason, admin_name=f"Admin: {admin_info}")
            
            # 2. Текст для VIP-пользователя
            reply_text = (
                f"✅ Ваша жалоба на пользователя в объявлении {ann_link} **принята**.\n\n"
                f"Мошенник заблокирован в {count} чатах сети! Спасибо за бдительность. 🛡️"
            )
            
        elif action == "reject":
            reply_text = (
                f"❌ Жалоба на пользователя в объявлении {ann_link} **отклонена**.\n"
                f"Спасибо за сигнал, но оснований для блокировки недостаточно."
            )
            
        elif action == "details":
            reply_text = (
                f"ℹ️ По жалобе на объявление {ann_link} нужны детали.\n"
                f"Пожалуйста, напишите нам в саппорт, что именно вызвал подозрения."
            )

        # Отправляем ответ VIP-юзеру
        try:
            bot.send_message(vip_id, reply_text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            print(f"Не удалось уведомить VIP {vip_id}: {e}")

        # Уведомляем админа в чате, что всё готово
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=call.message.text + f"\n\n✅ **Обработано админом:** {admin_info}\n**Результат:** {action.upper()}",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

        # Удаляем запись из памяти
        del scam_reports[report_id]

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {str(e)}", show_alert=True)

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"Ошибка при проверке подписки для {user_id}: {e}")
        return False

# --- МГНОВЕННЫЙ РАДАР БЛОКИРОВОК (Ловит тех, кто кинул в ЧС) ---
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
                
            # 2. ПРОВЕРКА: ИММУНИТЕТ (ФРАЗА ОТКАЗА)
            if user_id in safe_from_autoban:
                try: safe_from_autoban.remove(user_id)
                except: pass
                
            # 3. ЛИКВИДАЦИЯ ХИТРЕЦА
            else:
                try:
                    bot.send_message(STAFF_GROUP_ID, f"⚡️ **РАДАР СРАБОТАЛ** ⚡️\nЮзер `{user_id}` заблокировал бота без предупреждения! Запускаю ликвидацию...")
                except: pass
                
                ban_user_everywhere(user_id, reason="Мгновенный перехват блокировки бота", admin_name="Auto-Radar ⚡️")

# ==================== ПЕРЕХВАТЧИК "МЕРТВЫХ ДУШ" (Защита от старых заявок) ====================
@bot.message_handler(content_types=['new_chat_members'])
def catch_illegal_entry(message):
    for new_user in message.new_chat_members:
        user_id = new_user.id
        
        # 1. Проверяем, есть ли он в черном списке Скайнета
        banned_info = banned_collection.find_one({"_id": user_id})
        
        if banned_info:
            chat_id = message.chat.id
            
            # 2. Мгновенно баним обратно (стирать сообщение о входе не нужно, их у вас нет)
            try:
                bot.ban_chat_member(chat_id, user_id, revoke_messages=True)
            except:
                pass
            
            # 3. Гордо отчитываемся в Staff-чат
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
# ===========================================================================================

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

        # --- АВТО-СИНХРОНИЗАЦИЯ ФИЗИЧЕСКОГО ПРИСУТСТВИЯ ---
        if not is_vip:
            try:
                m_vip = bot.get_chat_member(VIP_CHAT_ID, user_id)
                if m_vip.status in ['member', 'administrator', 'creator']:
                    is_vip = True
                    users_collection.update_one({"_id": user_id}, {"$set": {"is_vip": True}}, upsert=True)
            except: pass

        if not is_queer:
            try:
                m_beyond = bot.get_chat_member(BEYOND_CHAT_ID, user_id)
                if m_beyond.status in ['member', 'administrator', 'creator']:
                    is_queer = True
                    users_collection.update_one({"_id": user_id}, {"$set": {"is_queer": True}}, upsert=True)
            except: pass

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
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🛠 Пройти верификацию", url="https://t.me/MK_MensClubSUPPORT"))
                warning_msg = bot.send_message(
                    chat_id, 
                    f"🚨 {user_link}, **ВНИМАНИЕ!**\n\n"
                    "С 1 мая введен СТРОГИЙ стандарт оформления анкет для досок объявлений.\n"
                    "Любой текст **БЕЗ ПАРАМЕТРОВ** или с неправильным форматом запрещен!\n"
                    "Параметры должны быть указаны **ТОЛЬКО через слеш (/) без пробелов и лишних слов**.\n\n"
                    "✅ *Примеры:* `24/187/72` или `24/187/72/19` (допускается `19.5` или `19*4`)\n\n"
                    "Ваша анкета удалена, а вы временно ограничены в общении во всех группах сети. Пройдите верификацию для разблокировки.",
                    reply_markup=markup, parse_mode="Markdown"
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
                reply_markup=markup, parse_mode="Markdown"
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

# Запускаем снайпера в отдельном потоке (добавить перед app.run)
threading.Thread(target=vip_funnel_sniper, daemon=True).start()
# =====================================================================

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == '__main__':
    print("Бот запущен — мягкая версия с приветствием и удалением сообщений (кроме сети ПАРНИ)")
    app.run(host='0.0.0.0', port=5000)