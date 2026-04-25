import os
import telebot
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
    "Иркутск": -1002210419274,
    "Кемерово": -1002147522863,
    "Москва": -1002208434096,
    "Санкт Петербург": -1002485776859,
    "Общая группа Юга": -1001814693664,
    "Общая группа Дальнего Востока": -1002161346845,
    "Общая группа Тюмень и Север": -1002210623988,
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
    "ЯМАО": -1002371438340,
    "Оренбург": -1003888335997,
    "Москва": -1003856528145,
    "Питер": -1003519420984,
    "Красноярск": -1003347456711
}

chat_ids_ns = {
    "Курган": -1001465465654,
    "Новосибирск": -1001824149334,
    "Челябинск": -1002233108474,
    "Пермь": -1001753881279,
    "Уфа": -1001823390636,
    "Ямал": -1002145851794,
    "Москва": -1001938448310,
    "ХМАО": -1001442597049,
    "Знакомства 66": -1002169473861,
    "Знакомства 72": -1002170955867,
    "Знакомства 74": -1002193127380
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
    "Москва": -1002255869134,
    "Волгоград": -1002476113714
}

# ==================== АВТОГЕНЕРАЦИЯ all_cities ====================
def normalize_city_name(name):
    mapping = {
        "Перми": "Пермь",
        "ЯМАО": "Ямал",
        "Знакомства 66": "Екатеринбург",
        "ЗНАКОМСТВА 72": "Тюмень",
        "Знакомства 74": "Челябинск"
    }
    return mapping.get(name, name)

all_cities = {}

def insert_to_all(city, net_key, real_name, chat_id):
    norm = normalize_city_name(city)
    if norm not in all_cities:
        all_cities[norm] = {}
    if net_key not in all_cities[norm]:
        all_cities[norm][net_key] = []
    all_cities[norm][net_key].append({"name": real_name, "chat_id": chat_id})

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

fallback_mk = {"Тюмень", "Ямал", "ХМАО"}
for city in fallback_mk:
    if "mk" not in all_cities.get(city, {}):
        insert_to_all(city, "mk", "Общая группа Тюмень и Север", -1002210623988)

def net_key_to_name(key):
    return {
        "mk": "Мужской Клуб",
        "parni": "ПАРНИ 18+",
        "ns": "НС",
        "rainbow": "Радуга",
        "gayznak": "Гей Знакомства"
    }.get(key, key)

ns_city_substitution = {
    "Екатеринбург": "Знакомства 66",
    "Челябинск": "Знакомства 74"
}

VIP_CHAT_ID = -1002446486648
VERIFICATION_LINK = "http://t.me/vip_znakbot"

user_posts = {}
post_owner = {}
responded = {}
scam_reports = {}  # ключ: report_id (случайный или timestamp+random), значение: {reporter_id, vip_id, chat_id, msg_id, responder_id, message_id_in_admin_chat}
pending_verification_users = {}
safe_from_autoban = set() # Те, кто официально отказался

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def escape_md(text):
    escape_chars = r'\_*[]()~`>#+=|{}'
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

def clean_user_text(text):
    return re.sub(r'(?<=\d)\*(?=\d)', '×', text)

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

@bot.message_handler(commands=['start'])
def start(message):
    try:
        if message.chat.type != "private":
            bot.send_message(message.chat.id, "Пожалуйста, используйте ЛС для работы с ботом.")
            return

        # 1. Ловим реферальную ссылку (t.me/bot?start=ref_12345)
        start_params = message.text.split()
        is_referral = False
        if len(start_params) > 1 and start_params[1].startswith('ref_'):
            ref_id = int(start_params[1].replace('ref_', ''))
            if ref_id != message.from_user.id:
                # ПИШЕМ КЛИК В БАЗУ!
                set_pending_ref(message.from_user.id, ref_id)
                update_user_stats(ref_id, clicks_add=1)
                is_referral = True
                try: 
                    bot.send_message(ref_id, "🔔 По вашей ссылке перешел новый человек! Ждем его оплату.") 
                except: 
                    pass

        if message.chat.id not in user_posts:
            user_posts[message.chat.id] = []

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
    args = message.text.split(maxsplit=3)
    if len(args) < 3:
        bot.send_message(message.chat.id, "❌ Формат: `/ban [ID] [V или ALL] [Причина]`")
        return
    
    target_id = int(args[1])
    prefix = args[2].upper()
    reason = args[3] if len(args) > 3 else "Не указана"
    admin_info = get_user_name(message.from_user)
    
    if prefix == 'ALL':
        bot.send_message(message.chat.id, "🚀 Массовый бан запущен...")
        count = ban_user_everywhere(target_id, reason, admin_info)
        bot.send_message(message.chat.id, f"✅ Готово! Забанен в {count} чатах. Отчет в Журнале.")
    elif prefix == 'V':
        try:
            bot.ban_chat_member(VIP_CHAT_ID, target_id)
            bot.send_message(JOURNAL_CHAT_ID, f"🚫 **#BAN (VIP)**\n• **Кто:** {admin_info}\n• **Кому:** `[{target_id}]`\n• **Причина:** {reason}", parse_mode="Markdown")
            bot.send_message(message.chat.id, f"✅ Юзер удален из VIP.")
        except: 
            bot.send_message(message.chat.id, "❌ Ошибка бана в VIP.")

# ==================== ВОРОНКА ВЕРИФИКАЦИИ ====================
@bot.callback_query_handler(func=lambda call: call.data == "start_verification")
def ask_for_video(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
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

    bot.send_message(message.chat.id, f"⏳ {escape_md(message.from_user.first_name)}, проверяем вашу анкету, подождите...")

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Одобрить (Счет на 250⭐️)", callback_data=f"vip_approve_{message.from_user.id}"),
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
    
    pending_verification_users[message.from_user.id] = False

def ban_user_everywhere(target_id, reason="Без причины", admin_name="Система"):
    banned_collection.update_one({"_id": target_id}, {"$set": {"reason": reason}}, upsert=True)
    
    # Список всех чатов сети
    chats_to_ban = {VIP_CHAT_ID: "VIP Клуб"}
    for city, cid in chat_ids_parni.items(): chats_to_ban[cid] = f"ПАРНИ 18+ | {city}"
    for city, cid in chat_ids_mk.items(): chats_to_ban[cid] = f"МК | {city}"
    for city, cid in chat_ids_ns.items(): chats_to_ban[cid] = f"НС | {city}"
    for city, cid in chat_ids_rainbow.items(): chats_to_ban[cid] = f"Радуга | {city}"
    for city, cid in chat_ids_gayznak.items(): chats_to_ban[cid] = f"Гей Знакомства | {city}"
                
    banned_in = []
    for cid, name in chats_to_ban.items():
        try:
            bot.ban_chat_member(cid, target_id)
            banned_in.append(f"🔸 {name}")
        except:
            pass
            
    report_text = (
        f"🚫 **#BAN**\n"
        f"• **Кто:** {admin_name}\n"
        f"• **Кому:** `[{target_id}]`\n"
        f"• **Причина:** {reason}\n"
        f"• **Группы:**\n" + "\n".join(banned_in)
    )
    try:
        bot.send_message(JOURNAL_CHAT_ID, report_text, parse_mode="Markdown")
    except: pass
    return len(banned_in)

# --- ОБРАБОТКА ОТКАЗА ОТ ВЕРИФИКАЦИИ ---
@bot.message_handler(func=lambda message: message.text and message.text.strip().lower() in ["я отказываюсь от продолжения", "отказываюсь от продолжения"])
def handle_refusal(message):
    if message.chat.type != "private": return
    
    user_id = message.from_user.id
    safe_from_autoban.add(user_id)  # Добавляем в белый список
    pending_verification_users[user_id] = False # Снимаем статус проверки
    
    bot.send_message(
        message.chat.id, 
        "✅ Ваша заявка аннулирована. Вы можете безопасно заблокировать бота, автоматической блокировки в сетях-партнерах не будет."
    )

# Действия админа (Одобрить/Отказать/Забанить)
@bot.callback_query_handler(func=lambda call: call.data.startswith("vip_approve_") or call.data.startswith("vip_reject_") or call.data.startswith("vip_ban_"))
def handle_vip_decision(call):
    action, user_id_str = call.data.rsplit("_", 1)
    user_id = int(user_id_str)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    admin_info = get_user_name(call.from_user)
    
    if "approve" in action:
        # --- НАЧАЛО: ЛАЙФХАК С ДЕШЕВЫМИ ЗВЕЗДАМИ ---
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
        # --- КОНЕЦ: ЛАЙФХАК С ДЕШЕВЫМИ ЗВЕЗДАМИ ---

        try:
            bot.send_invoice(user_id, title="Вход в VIP Клуб 👑", description="Оплата доступа в закрытый чат.", invoice_payload="vip_access_payment", provider_token="", currency="XTR", prices=[types.LabeledPrice(label="VIP Доступ", amount=VIP_PRICE_STARS)])
            bot.send_message(call.message.chat.id, f"✅ Счет отправлен пользователю {user_id}.")
        except Exception as e:
            if "bot was blocked by the user" in str(e):
                # ПРОВЕРКА ИММУНИТЕТА
                if user_id in safe_from_autoban:
                    bot.send_message(call.message.chat.id, f"ℹ️ Юзер {user_id} заблокировал бота, НО он официально отказался. Бан отменен.")
                    safe_from_autoban.remove(user_id) # Чистим за собой
                else:
                    bot.send_message(call.message.chat.id, f"🚨 Юзер {user_id} заблокировал бота БЕЗ отказа! Авто-бан активирован.")
                    ban_user_everywhere(user_id, reason="Блокировка бота при верификации", admin_name="Auto-Defender")
            else:
                bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
            
    elif "reject" in action:
        bot.send_message(call.message.chat.id, f"❌ Вы отклонили заявку {user_id}.")
        try:
            bot.send_message(user_id, "К сожалению, ваша заявка отклонена из-за нарушений.")
        except:
            pass

    elif "ban" in action:
        bot.send_message(call.message.chat.id, "🔨 Запускаю массовый бан...")
        count = ban_user_everywhere(user_id, reason="Не прошел модерацию кружка", admin_name=admin_info)
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
    
    # 1. Генерируем ссылку
    try:
        invite = bot.create_chat_invite_link(VIP_CHAT_ID, member_limit=1)
        bot.send_message(new_user_id, f"🎉 **Оплата получена! Добро пожаловать в элиту.**\n\nТвоя ссылка для входа:\n{invite.invite_link}", parse_mode="Markdown")
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
        percent, bonus_stars = get_referral_bonus(stats['invites']) # Посчитали бонус
        
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
    bot.send_message(message.chat.id, "Напишите текст объявления:")
    bot.register_next_step_handler(message, process_text)

@bot.message_handler(func=lambda message: message.text == "Удалить объявление")
def handle_delete_post(message):
    if message.chat.type != "private":
        bot.send_message(message.chat.id, "Пожалуйста, используйте ЛС для работы с ботом.")
        return
    if message.chat.id in user_posts and user_posts[message.chat.id]:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        for post in user_posts[message.chat.id]:
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
    if message.chat.type != "private":
        bot.send_message(message.chat.id, "Пожалуйста, используйте ЛС для работы с ботом.")
        return
    if message.chat.id in user_posts and user_posts[message.chat.id]:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("Да, удалить всё", "Нет, отменить")
        bot.send_message(message.chat.id, "Вы уверены, что хотите удалить все свои объявления?", reply_markup=markup)
        bot.register_next_step_handler(message, process_delete_all_choice)
    else:
        bot.send_message(message.chat.id, "❌ У вас нет опубликованных объявлений.")

def process_delete_choice(message):
    if message.text == "Отмена":
        bot.send_message(message.chat.id, "Удаление отменено.", reply_markup=get_main_keyboard())
    else:
        try:
            for post in user_posts[message.chat.id]:
                time_formatted = format_time(post["time"])
                if message.text == f"Удалить: {time_formatted}, {post['city']}, {post['network']}":
                    try:
                        bot.delete_message(post["chat_id"], post["message_id"])
                    except Exception:
                        pass
                    user_posts[message.chat.id].remove(post)
                    bot.send_message(message.chat.id, "✅ Объявление успешно удалено.", reply_markup=get_main_keyboard())
                    return
            bot.send_message(message.chat.id, "❌ Объявление не найдено.")
        except (ValueError, IndexError):
            bot.send_message(message.chat.id, "❌ Ошибка! Пожалуйста, выберите объявление из списка.")

def process_delete_all_choice(message):
    if message.text == "Да, удалить всё":
        for post in user_posts[message.chat.id]:
            try:
                bot.delete_message(post["chat_id"], post["message_id"])
            except Exception:
                pass
        user_posts[message.chat.id] = []
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
    # добавляем сети
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
            # только города где >= 2 сетей
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
        chat_member = bot.get_chat_member(VIP_CHAT_ID, message.from_user.id)
        if chat_member.status in ["member", "administrator", "creator"]:
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

            # === ЦВЕТНАЯ КНОПКА ОТКЛИКА ===
            markup_inline = types.InlineKeyboardMarkup()
            markup_inline.add(
                types.InlineKeyboardButton(
                    text="Откликнуться ♥",
                    callback_data="respond",
                    icon_custom_emoji_id="6088882892526587287",   # твой эмодзи
                    style="success"          # ЗЕЛЁНАЯ
                )
            )

            if selected_network == "Все сети":
                norm_city = normalize_city_name(city)
                nets = list(all_cities.get(norm_city, {}).keys())
                networks = [net_key_to_name(k) for k in nets]
            else:
                networks = [selected_network]

            for network in networks:
                if network == "Мужской Клуб":
                    chat_dict = chat_ids_mk
                    net_key = "mk"
                elif network == "ПАРНИ 18+":
                    chat_dict = chat_ids_parni
                    net_key = "parni"
                elif network == "НС":
                    chat_dict = chat_ids_ns
                    net_key = "ns"
                elif network == "Радуга":
                    chat_dict = chat_ids_rainbow
                    net_key = "rainbow"
                elif network == "Гей Знакомства":
                    chat_dict = chat_ids_gayznak
                    net_key = "gayznak"
                else:
                    continue

                # Для НС возможна подстановка городов
                if net_key == "ns":
                    if city not in chat_dict and city in ns_city_substitution:
                        substitute_city = ns_city_substitution[city]
                        if substitute_city in chat_dict:
                            chat_id = chat_dict[substitute_city]
                        else:
                            bot.send_message(message.chat.id, f"❌ Ошибка! Город '{city}' не найден в сети «{network}».")
                            continue
                    elif city in chat_dict:
                        chat_id = chat_dict[city]
                    else:
                        bot.send_message(message.chat.id, f"❌ Ошибка! Город '{city}' не найден в сети «{network}».")
                        continue
                else:
                    if city in chat_dict:
                        chat_id = chat_dict[city]
                    else:
                        norm = normalize_city_name(city)
                        found = False
                        for entry in all_cities.get(norm, {}).get(net_key, []):
                            chat_id = entry.get('chat_id')
                            found = True
                            break
                        if not found:
                            bot.send_message(message.chat.id, f"❌ Ошибка! Город '{city}' не найден в сети «{network}».")
                            continue

                try:
                    if media_type == "photo":
                        sent_message = bot.send_photo(chat_id, file_id, caption=full_text, parse_mode="Markdown", reply_markup=markup_inline)
                    elif media_type == "video":
                        sent_message = bot.send_video(chat_id, file_id, caption=full_text, parse_mode="Markdown", reply_markup=markup_inline)
                    else:
                        sent_message = bot.send_message(chat_id, full_text, parse_mode="Markdown", reply_markup=markup_inline)

                    post_owner[(chat_id, sent_message.message_id)] = message.from_user.id

                    if message.chat.id not in user_posts:
                        user_posts[message.chat.id] = []
                    user_posts[message.chat.id].append({
                        "message_id": sent_message.message_id,
                        "chat_id": chat_id,
                        "time": datetime.now(),
                        "city": city,
                        "network": network
                    })
                    bot.send_message(message.chat.id, f"✅ Ваше объявление опубликовано в сети «{network}», городе {city}.")
                except telebot.apihelper.ApiTelegramException as e:
                    bot.send_message(message.chat.id, f"❌ Ошибка: {e.description}")

            ask_for_new_post(message)

        else:
            # === КРАСНАЯ КНОПКА ВЕРИФИКАЦИИ (ЗАПУСКАЕТ НАШУ ВОРОНКУ) ===
            markup = types.InlineKeyboardMarkup()
            verify_button = types.InlineKeyboardButton(
                text="🛠️ Пройти верификацию",
                callback_data="start_verification", # <--- Магия здесь!
                style="danger"          # КРАСНАЯ (оставил твой стиль)
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
    responder = call.from_user  # полный объект User

    key = (chat_id, msg_id)
    if key not in post_owner:
        bot.answer_callback_query(call.id, "Ошибка объявления.")
        return

    if key not in responded:
        responded[key] = set()

    if user_id in responded[key]:
        bot.answer_callback_query(call.id, "Вы уже откликались на это объявление.")
        return

    # === БЛОКИРОВКА ОТКЛИКА БЕЗ @username ===
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
    # ========================================

    responded[key].add(user_id)
    vip_id = post_owner[key]

    # Формируем имя + ссылку на профиль
    if responder.username:
        name = f"[{escape_md(responder.first_name)}](https://t.me/{responder.username})"
    else:
        name = f"[{escape_md(responder.first_name)}](tg://user?id={user_id})"

    # === КРАСНАЯ КНОПКА ЖАЛОБЫ ===
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            text="🚨 Это спам / скам / мошенник",
            callback_data=f"report_scam_{chat_id}_{msg_id}_{user_id}",
            style="danger"          # КРАСНАЯ кнопка
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
        error_text = f"❗️Не удалось уведомить VIP {vip_id}: {e}"
        for admin_id in ADMIN_CHAT_IDS:
            try:
                bot.send_message(admin_id, error_text)
            except Exception:
                pass

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

# ==================== УДАЛЕНИЕ СООБЩЕНИЙ БЕЗ ПОДПИСКИ + ОТБИВКА ====================
warned_users = {}  # (chat_id, user_id) -> message_id отбивки

@bot.message_handler(content_types=[
    'text', 'photo', 'video', 'document', 'audio', 'voice',
    'sticker', 'animation', 'location', 'contact'
])
def check_subscription(message):
    if message.chat.type == "private" or not message.from_user:
        return
    if message.sender_chat:
        return
    if message.chat.id in PARNI_CHATS:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    key = (chat_id, user_id)

    if is_subscribed(user_id):
        if key in warned_users:
            try:
                bot.delete_message(chat_id, warned_users[key])
            except:
                pass
            del warned_users[key]
        return

    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

    if key not in warned_users:
        markup = types.InlineKeyboardMarkup(row_width=2)

        # Кнопка "Подписаться на МК" + анимированный стикер в начале кнопки
        markup.add(
            types.InlineKeyboardButton(
                text="Подписаться на МК",   # текст остаётся
                url=MAIN_CHANNEL_LINK,
                icon_custom_emoji_id="5215330331711775720",   # ← твой стикер для МК
                style="success"                              # зелёная кнопка (как было)
            )
        )

        # Кнопка ПАРНИ 18+ (без изменений)
        markup.add(
            types.InlineKeyboardButton(
                text="ПАРНИ 18+",
                url="https://t.me/znakparni"
            )
        )

        # Резервный канал и ПРАВИЛА (без изменений)
        markup.add(
            types.InlineKeyboardButton("Резервный канал", url="https://t.me/gaysexchatrur"),
            types.InlineKeyboardButton("ПРАВИЛА МК", url="https://t.me/MensClubRules")
        )

        # Кнопка БЕСПЛАТНЫЙ VPN + анимированный стикер
        markup.add(
            types.InlineKeyboardButton(
                text="🚀 БЕСПЛАТНЫЙ VPN ДЛЯ ВСЕХ",
                url="https://t.me/perec?start=ref_2BBPF35H",
                icon_custom_emoji_id="5981123193862098366",   # ← твой стикер для VPN
                style="primary"                              # синяя кнопка (как было)
            )
        )

        try:
            sent = bot.send_message(
                chat_id=chat_id,
                text="❗ Внимание, чтобы писать в чате вам необходимо подписаться на наш основной канал.\n\n"
                     "Без подписки на канал ваши сообщения будут удаляться автоматически. "
                     "Вступая в чат, я подтверждаю совершеннолетие и обязуюсь соблюдать правила, "
                     "с которыми ознакомлен и согласен.",
                reply_markup=markup
            )
            warned_users[key] = sent.message_id

            def auto_delete():
                time.sleep(120)
                try:
                    bot.delete_message(chat_id, sent.message_id)
                except:
                    pass
                if key in warned_users:
                    del warned_users[key]

            threading.Thread(target=auto_delete, daemon=True).start()

        except Exception as e:
            print(f"Ошибка отправки отбивки: {e}")

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == '__main__':
    print("Бот запущен — мягкая версия с приветствием и удалением сообщений (кроме сети ПАРНИ)")
    app.run(host='0.0.0.0', port=5000)