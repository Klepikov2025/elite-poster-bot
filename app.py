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

ADMIN_CHAT_ID = 479938867
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
    "RAINBOW MAN": -1001415498051,
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
    "Перми": -1002280860973,
    "Курган": -1002469285352,
    "ХМАО": -1002287709568,
    "Уфа": -1002448909000,
    "Новосибирск": -1002261777025,
    "ЯМАО": -1002371438340
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

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def escape_md(text):
    escape_chars = r'\_*[]()~`>#+-=|{}'
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
        bot.send_message(ADMIN_CHAT_ID, f"Ошибка в /start: {e}")

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

            markup_inline = types.InlineKeyboardMarkup()
            markup_inline.add(types.InlineKeyboardButton("Откликнуться♥", callback_data="respond"))

            if selected_network == "Все сети":
                # формируем список доступных сетей по all_cities
                norm_city = normalize_city_name(city)
                nets = list(all_cities.get(norm_city, {}).keys())
                networks = [net_key_to_name(k) for k in nets]
            else:
                networks = [selected_network]

            for network in networks:
                # выбираем словарь по названию сети
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

                # Для НС возможна подстановка городов (ns_city_substitution)
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
            markup = types.InlineKeyboardMarkup()
            verify_button = types.InlineKeyboardButton(text="🛠️ Пройти верификацию", url=VERIFICATION_LINK)
            markup.add(verify_button)
            bot.send_message(message.chat.id, "🔓 Вы не являетесь привилегированным участником. Для публикации объявлений пройдите верификацию:", reply_markup=markup)
    except telebot.apihelper.ApiTelegramException as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка при проверке VIP-статуса: {e.description}")
def ask_for_new_post(message):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Да", "Нет")
    bot.send_message(message.chat.id, "Хотите опубликовать ещё одно объявление?", reply_markup=markup)
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

    # Теперь username точно есть → делаем красивую кликабельную ссылку
    name = f"[{escape_md(responder.first_name)}](https://t.me/{responder.username})"

    try:
        bot.send_message(
            vip_id,
            f"Вами заинтересовался {name}",
            parse_mode="MarkdownV2"  # MarkdownV2, потому что мы используем escape_md
        )
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"❗️Не удалось уведомить VIP: {e}")

    bot.answer_callback_query(call.id, "✅ Ваш отклик отправлен!")

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"Ошибка при проверке подписки для {user_id}: {e}")
        return False

# ==================== УДАЛЕНИЕ СООБЩЕНИЙ БЕЗ ПОДПИСКИ + ОТБИВКА ====================
# Отбивка один раз + автоудаление через 2 минуты (120 секунд)
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
        # Подписан → очищаем отбивку (если была), НО НЕ return!
        # Сообщение должно дойти до city_redirect_handler
        if key in warned_users:
            try:
                bot.delete_message(chat_id, warned_users[key])
            except:
                pass
            del warned_users[key]
        # Здесь НЕ return — продолжаем цепочку обработчиков
    else:
        # Не подписан → удаляем сообщение
        try:
            bot.delete_message(chat_id, message.message_id)
        except:
            pass

        # Отбивка ТОЛЬКО ОДИН РАЗ
        if key not in warned_users:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("Подписаться на главный канал", url=MAIN_CHANNEL_LINK),
                types.InlineKeyboardButton("Резервный канал", url="https://t.me/gaysexchatrur")
            )

            try:
                sent = bot.send_message(
                    chat_id=chat_id,
                    text="❗ Внимание, чтобы писать в чате вам необходимо подписаться на наш основной канал.\n\n"
                         "Без подписки на канал ваши сообщения будут удаляться автоматически.",
                    reply_markup=markup
                )
                msg_id = sent.message_id
                print(f"Отбивка отправлена, id {msg_id} пользователю {user_id}")

                warned_users[key] = msg_id

                def auto_delete():
                    time.sleep(120)
                    try:
                        bot.delete_message(chat_id, msg_id)
                        print(f"Отбивка {msg_id} удалена (2 минуты прошли)")
                    except Exception as e:
                        print(f"Не удалось удалить отбивку {msg_id}: {e}")
                    if key in warned_users:
                        del warned_users[key]

                threading.Thread(target=auto_delete, daemon=True).start()

            except Exception as e:
                print(f"Ошибка отправки отбивки пользователю {user_id}: {e}")

        # Здесь НЕ return — но поскольку сообщение уже удалено, дальше ничего не произойдёт


# ───────────────────────────────────────────────
# АВТООТВЕТЫ ПО ГОРОДАМ ТОЛЬКО В ДВУХ БИГ-ЧАТАХ
# ───────────────────────────────────────────────

CITY_REDIRECT_CHATS = {
    -1001219669239,   # МК БЕЗ ПРЕДРАССУДКОВ
    -1001415498051,   # RAINBOW MAN
}

CITY_INVITE_LINKS = {}          # chat_id → вечная invite-ссылка

COOLDOWN_SECONDS   = 480        # 8 минут
AUTO_DELETE_AFTER  = 180        # 3 минуты — автоудаление ответа бота

last_city_reply = {}            # (chat_id, norm_city) → timestamp

def escape_md_v2(text):
    chars = r'_*[]()~`>#+-=|{}.!'
    for c in chars:
        text = text.replace(c, f'\\{c}')
    return text

def get_or_create_invite_link(chat_id):
    if chat_id in CITY_INVITE_LINKS:
        return CITY_INVITE_LINKS[chat_id]

    try:
        invite = bot.create_chat_invite_link(
            chat_id=chat_id,
            name="Ссылка от ElitePoster (авто)",
            member_limit=0,
            expire_date=None
        )
        link = invite.invite_link
        CITY_INVITE_LINKS[chat_id] = link
        print(f"[Invite] Создана ссылка для {chat_id}: {link}")
        return link
    except Exception as e:
        print(f"[Invite Error] {chat_id}: {e}")
        return None

CITY_ALIASES = {
    "мск": "Москва", "москва": "Москва", "мос": "Москва", "мскв": "Москва", "мск": "Москва",
    "спб": "Санкт Петербург", "питер": "Санкт Петербург", "птб": "Санкт Петербург", "петербург": "Санкт Петербург",
    "екб": "Екатеринбург", "ебург": "Екатеринбург", "екатерин": "Екатеринбург", "екатеринбург": "Екатеринбург", "екбш": "Екатеринбург",
    "чел": "Челябинск", "челя": "Челябинск", "члб": "Челябинск", "челябинск": "Челябинск", "чехи": "Челябинск", "челяба": "Челябинск",
    "нск": "Новосибирск", "новосиб": "Новосибирск", "н-ск": "Новосибирск", "новосибирск": "Новосибирск", "нскв": "Новосибирск",
    "красноярск": "Красноярск", "крас": "Красноярск", "крск": "Красноярск", "кряс": "Красноярск",
    "омск": "Омск", "ом": "Омск",
    "тюм": "Тюмень", "тюмень": "Тюмень", "тюменька": "Тюмень",
    "пермь": "Пермь", "перм": "Пермь", "пм": "Пермь", "перми": "Пермь",
    "уфа": "Уфа", "уфим": "Уфа", "уф": "Уфа",
    "казань": "Казань", "каз": "Казань", "кзнь": "Казань", "казан": "Казань",
    "самара": "Самара", "сам": "Самара", "смр": "Самара", "самар": "Самара",
    "нн": "Нижний Новгород", "н-нов": "Нижний Новгород", "нижний": "Нижний Новгород",
    "воронеж": "Воронеж", "врнж": "Воронеж", "врж": "Воронеж",
    "волгоград": "Волгоград", "волг": "Волгоград", "волжск": "Волгоград",
    "иркутск": "Иркутск", "ирк": "Иркутск", "иркут": "Иркутск",
    "кемерово": "Кемерово", "кем": "Кемерово", "кемер": "Кемерово",
    "барнаул": "Барнаул", "барна": "Барнаул", "барн": "Барнаул",
    "саратов": "Саратов", "сар": "Саратов", "сарат": "Саратов",
    "калининград": "Калининград", "калинин": "Калининград", "кгд": "Калининград", "кёниг": "Калининград",
    "ростов": "Ростов-на-Дону", "рнд": "Ростов-на-Дону", "ростов нд": "Ростов-на-Дону",
    "кдр": "Краснодар", "краснод": "Краснодар", "крд": "Краснодар",
}

SMALL_TOWN_TO_CENTER = {
    # Челябинская → Челябинск
    "чебаркуль": "Челябинск", "миасс": "Челябинск", "златоуст": "Челябинск", "копейск": "Челябинск",
    "коркино": "Челябинск", "южноуральск": "Челябинск", "троицк": "Челябинск", "сатка": "Челябинск",
    "аш": "Челябинск", "верхний уфалей": "Челябинск", "куса": "Челябинск", "катав-ивановск": "Челябинск",
    "сим": "Челябинск", "миньяр": "Челябинск", "бакал": "Челябинск", "касля": "Челябинск",
    "озёрск": "Челябинск", "снежинск": "Челябинск", "трехгорный": "Челябинск", "пласт": "Челябинск",
    "еманжелинск": "Челябинск", "кыштым": "Челябинск", "верхнеуральск": "Челябинск",

    # Свердловская → Екатеринбург
    "нижний тагил": "Екатеринбург", "н.тагил": "Екатеринбург", "каменск-уральский": "Екатеринбург",
    "первоуральск": "Екатеринбург", "серова": "Екатеринбург", "полевской": "Екатеринбург",
    "асбест": "Екатеринбург", "невьянск": "Екатеринбург", "ревда": "Екатеринбург", "берёзовский": "Екатеринбург",
    "лесной": "Екатеринбург", "новоуральск": "Екатеринбург", "верхняя пышма": "Екатеринбург",
    "заречный": "Екатеринбург", "ивдель": "Екатеринбург", "краснотурьинск": "Екатеринбург",
    "красноуральск": "Екатеринбург", "карпинск": "Екатеринбург", "алапаевск": "Екатеринбург",
    "артёмовский": "Екатеринбург", "богданович": "Екатеринбург", "качканар": "Екатеринбург",

    # Новосибирская → Новосибирск
    "бердск": "Новосибирск", "искитим": "Новосибирск", "обь": "Новосибирск", "купино": "Новосибирск",
    "карасук": "Новосибирск", "барабинск": "Новосибирск", "татарск": "Новосибирск", "черепаново": "Новосибирск",
    "куйбышев": "Новосибирск", "болотное": "Новосибирск",

    # Пермский край → Пермь
    "березники": "Пермь", "соликамск": "Пермь", "кунгур": "Пермь", "краснокамск": "Пермь",
    "чайковский": "Пермь", "добрянка": "Пермь", "чернушка": "Пермь", "губаха": "Пермь",
    "кизел": "Пермь", "лысьва": "Пермь", "очер": "Пермь", "александровск": "Пермь",

    # ХМАО / ЯМАО
    "сургут": "ХМАО", "нижневартовск": "ХМАО", "нефтеюганск": "ХМАО", "мегион": "ХМАО",
    "лангепас": "ХМАО", "покачи": "ХМАО", "радужный": "ХМАО", "пыт-ях": "ХМАО",
    "урай": "ХМАО",
    "новый уренгой": "ЯМАО", "ноябрьск": "ЯМАО", "надым": "ЯМАО", "муравленко": "ЯМАО",
    "губкинский": "ЯМАО", "тарко-сале": "ЯМАО", "лабытнанги": "ЯМАО",

    # Юг (Краснодар / Ростов / Воронеж)
    "сочи": "Краснодар", "адлер": "Краснодар", "туапсе": "Краснодар", "анапа": "Краснодар",
    "геленджик": "Краснодар", "новороссийск": "Краснодар", "крымск": "Краснодар",
    "славянск-на-кубани": "Краснодар", "темрюк": "Краснодар", "тихорецк": "Краснодар",
    "таганрог": "Ростов-на-Дону", "шахты": "Ростов-на-Дону", "новочеркасск": "Ростов-на-Дону",
    "батайск": "Ростов-на-Дону", "азов": "Ростов-на-Дону", "волгодонск": "Ростов-на-Дону",
    "россошь": "Воронеж", "лиски": "Воронеж", "борисоглебск": "Воронеж",
}

@bot.message_handler(content_types=['text'])
def city_redirect_handler(message):
    # отладка (можно убрать после теста)
    print(f"[DEBUG city] сообщение в чате {message.chat.id}: {message.text}")

    if message.chat.type not in ["group", "supergroup"]:
        return
    if message.chat.id not in CITY_REDIRECT_CHATS:
        return
    if message.from_user.is_bot:
        return

    text_lower = (message.text or "").lower().strip()
    if len(text_lower) < 6:
        return

    # Анти-спам
    if any(w in text_lower for w in ["цена", "сколько", "стоимость", "donate", "/ban", "/mute", "реклама", "куплю", "продам"]):
        return

    # Поиск города
    found_city = None
    for alias, city in CITY_ALIASES.items():
        if alias in text_lower:
            found_city = city
            break
    if not found_city:
        for c in all_cities:
            if c.lower() in text_lower:
                found_city = c
                break
    if not found_city:
        for small, center in SMALL_TOWN_TO_CENTER.items():
            if small in text_lower:
                found_city = center
                break
    if not found_city:
        return

    norm_city = normalize_city_name(found_city)
    if norm_city not in all_cities:
        return

    key = (message.chat.id, norm_city)
    now = time.time()
    if key in last_city_reply and now - last_city_reply[key] < COOLDOWN_SECONDS:
        return
    last_city_reply[key] = now

    lines = []
    networks = all_cities.get(norm_city, {})
    for net_key, entries in networks.items():
        net_name = net_key_to_name(net_key)
        for entry in entries:
            chat_id = entry["chat_id"]
            real_name = entry.get("name", norm_city)
            link = get_or_create_invite_link(chat_id)
            if link:
                escaped_net = escape_md_v2(net_name)
                escaped_city = escape_md_v2(real_name)
                line = f"• [{escaped_net} → {escaped_city}]({link})"
                lines.append(line)
            else:
                lines.append(f"• {net_name} → {real_name} (ссылка недоступна)")

    if not lines:
        return

    templates = [
        f"Ищете в **{escape_md_v2(norm_city)}**? Вот основные чаты:",
        f"В **{escape_md_v2(norm_city)}** обычно активнее здесь 👇",
        f"Быстрее найдёте в **{escape_md_v2(norm_city)}** по этим ссылкам:",
        f"Для **{escape_md_v2(norm_city)}** удобнее сразу перейти в эти группы:",
        f"**{escape_md_v2(norm_city)}** — вот актуальные чаты:",
        f"В **{escape_md_v2(norm_city)}** ищут вот здесь:",
        f"Переходите в **{escape_md_v2(norm_city)}** — здесь больше шансов:",
        f"**{escape_md_v2(norm_city)}** ждёт! Вот рабочие чаты:",
    ]

    response = (
        random.choice(templates) +
        "\n\n" +
        "\n".join(lines) +
        "\n\nУдачи в поиске! 💬"
    )

    try:
        sent_msg = bot.reply_to(
            message,
            response,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
            disable_notification=True
        )

        def delete_later():
            time.sleep(AUTO_DELETE_AFTER)
            try:
                bot.delete_message(message.chat.id, sent_msg.message_id)
            except Exception as e:
                print(f"Не удалось удалить автоответ {sent_msg.message_id}: {e}")

        threading.Thread(target=delete_later, daemon=True).start()

    except Exception as e:
        print(f"[city_redirect] Ошибка отправки в {message.chat.id}: {e}")

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == '__main__':
    print("Бот запущен — мягкая версия с приветствием и удалением сообщений (кроме сети ПАРНИ)")
    app.run(host='0.0.0.0', port=5000)