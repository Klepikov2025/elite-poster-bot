import os
import telebot
from telebot import types
from flask import Flask, request
from datetime import datetime
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

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def escape_md(text):
    escape_chars = r'\_*[]()~`>#+=|{}'
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

def clean_user_text(text):
    return re.sub(r'(?<=\d)\*(?=\d)', '×', text)

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Создать новое объявление", "Удалить объявление", "Удалить все объявления")
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

        if message.chat.id not in user_posts:
            user_posts[message.chat.id] = []

        bot.send_message(
            message.chat.id,
            "Привет! Я ElitePoster. 👋\nВыберите действие:",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        error_text = f"Ошибка в /start: {e}"
        for admin_id in ADMIN_CHAT_IDS:
            try:
                bot.send_message(admin_id, error_text)
            except Exception:
                pass  # или print, если хочется видеть в консоли

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
            # === КРАСНАЯ КНОПКА ВЕРИФИКАЦИИ ===
            markup = types.InlineKeyboardMarkup()
            verify_button = types.InlineKeyboardButton(
                text="🛠️ Пройти верификацию",
                url=VERIFICATION_LINK,
                style="danger"          # КРАСНАЯ
            )
            markup.add(verify_button)
            bot.send_message(message.chat.id, "🔓 Вы не являетесь привилегированным участником. Для публикации объявлений пройдите верификацию:", reply_markup=markup)

    except telebot.apihelper.ApiTelegramException as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка при проверке VIP-статуса: {e.description}")

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

        if not vip_id:
            bot.answer_callback_query(call.id, "Не удалось определить автора объявления", show_alert=True)
            return

        reporter_name = report["reporter_link"]
        ann_link = report["ann_link"]

        if action == "accept":
            reply_text = (
                f"✅ Жалоба на пользователя в объявлении {ann_link} **принята**.\n"
                f"Спасибо, {reporter_name}! Мы занимаемся этим вопросом."
            )
        elif action == "reject":
            reply_text = (
                f"❌ Жалоба на пользователя в объявлении {ann_link} **отклонена**.\n"
                f"Спасибо за сигнал, но оснований для действий недостаточно."
            )
        elif action == "details":
            reply_text = (
                f"ℹ️ По жалобе на объявление {ann_link} нужны дополнительные детали.\n"
                f"Пожалуйста, напишите @FAQMKBOT или @elite_loungebot что именно вызывает подозрения."
            )
        else:
            reply_text = "Неизвестное действие."

        # Отправляем ответ VIP-юзеру
        try:
            bot.send_message(vip_id, reply_text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            print(f"Не удалось уведомить VIP {vip_id}: {e}")

        # Уведомляем админа, что действие выполнено
        bot.answer_callback_query(call.id, f"Действие «{action}» выполнено", show_alert=False)

        # Можно удалить клавиатуру жалобы (опционально)
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None
        )

        # Удаляем запись (чтобы не накапливать)
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

# ==================== TELEGRAM STARS — ТЕСТОВАЯ ОПЛАТА И ОБРАБОТКА ====================

@bot.message_handler(commands=['teststar'])
def test_star_payment(message):
    """Только для админов — отправляет счёт на 1 Star"""
    if message.from_user.id not in ADMIN_CHAT_IDS:
        bot.send_message(message.chat.id, "⛔ Доступ запрещён.")
        return

    try:
        bot.send_invoice(
            chat_id=message.chat.id,
            title="Тестовая покупка Stars",
            description="Тестовый платёж на 1 ⭐.\nПосле оплаты в настройках бота должна появиться кнопка Balance.",
            payload="test_star_1",
            provider_token="",        # важно для Stars
            currency="XTR",
            prices=[types.LabeledPrice(label="1 Star", amount=1)]
        )
        bot.send_message(message.chat.id, "✅ Счёт на 1 ⭐ отправлен тебе.\nОплати его, чтобы активировать Balance в BotFather.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка отправки инвойса:\n{str(e)}")


@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout_query(pre_checkout_query):
    """Обязательный обработчик для всех платежей"""
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=['successful_payment'])
def successful_payment_handler(message):
    """Обработка успешной оплаты Stars"""
    payment = message.successful_payment
    user_id = message.from_user.id
    amount = payment.total_amount
    payload = payment.invoice_payload or "unknown"

    success_text = f"✅ Оплата прошла успешно!\n\n" \
                   f"Сумма: **{amount}** ⭐\n" \
                   f"Payload: `{payload}`"

    bot.send_message(user_id, success_text, parse_mode="Markdown")

    # Уведомляем всех админов
    admin_text = f"💰 Новая оплата Stars!\n" \
                 f"Пользователь: {user_id}\n" \
                 f"Сумма: {amount} ⭐\n" \
                 f"Payload: {payload}"

    for admin_id in ADMIN_CHAT_IDS:
        try:
            bot.send_message(admin_id, admin_text)
        except:
            pass

    # Здесь позже будем добавлять VIP и реферальные начисления
    print(f"[PAYMENT] User {user_id} paid {amount} Stars. Payload: {payload}")

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == '__main__':
    print("Бот запущен — мягкая версия с приветствием и удалением сообщений (кроме сети ПАРНИ)")
    app.run(host='0.0.0.0', port=5000)