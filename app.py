import os
import telebot
from telebot import types
import time
import threading
from flask import Flask, request
from datetime import datetime
import pytz
import random
import re

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

ADMIN_CHAT_ID = 479938867
OWNER_ID = 479938867  # твой ID

# Главный канал — обязательная подписка
MAIN_CHANNEL_ID = -1002246737442

# Разрешения
MUTED_PERMISSIONS = types.ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_other_messages=False,
    can_send_polls=False,
    can_add_web_page_previews=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_change_info=False
)

FULL_PERMISSIONS = types.ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_other_messages=True,
    can_send_polls=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
    can_pin_messages=False,
    can_change_info=False
)

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
        "Знакомства 72": "Тюмень",
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

# ==================== СТАРЫЙ ФУНКЦИОНАЛ ОБЪЯВЛЕНИЙ ====================
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
    if message.text and message.text.lower() == "да":
        bot.send_message(message.chat.id, "📋 Выберите сеть для публикации:", reply_markup=get_network_markup())
        bot.register_next_step_handler(message, select_network, text, media_type, file_id)
    elif message.text and message.text.lower() == "нет":
        bot.send_message(message.chat.id, "Хорошо, напишите текст объявления заново:")
        bot.register_next_step_handler(message, process_text)
    else:
        bot.send_message(message.chat.id, "❌ Неверный ответ. Выберите 'Да' или 'Нет'.")
        bot.register_next_step_handler(message, handle_confirmation, text, media_type, file_id)

def get_network_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
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

                if net_key == "ns":
                    substitute_city = ns_city_substitution.get(city, city)
                    chat_id = chat_dict.get(substitute_city) or chat_dict.get(city)
                else:
                    norm = normalize_city_name(city)
                    entry = next((e for e in all_cities.get(norm, {}).get(net_key, [])), None)
                    chat_id = entry["chat_id"] if entry else chat_dict.get(city)

                if not chat_id:
                    bot.send_message(message.chat.id, f"❌ Город не найден в сети «{network}».")
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
                    bot.send_message(message.chat.id, f"✅ Опубликовано в «{network}» — {city}")
                except Exception as e:
                    bot.send_message(message.chat.id, f"Ошибка: {e}")
            ask_for_new_post(message)
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🛠️ Пройти верификацию", url=VERIFICATION_LINK))
            bot.send_message(message.chat.id, "🔓 Для публикации нужна верификация:", reply_markup=markup)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка VIP-проверки: {e}")

def ask_for_new_post(message):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Да", "Нет")
    bot.send_message(message.chat.id, "Хотите опубликовать ещё одно объявление?", reply_markup=markup)
    bot.register_next_step_handler(message, handle_new_post_choice)

def handle_new_post_choice(message):
    if message.text and message.text.lower() == "да":
        bot.send_message(message.chat.id, "Напишите текст объявления:")
        bot.register_next_step_handler(message, process_text)
    else:
        bot.send_message(message.chat.id, "Спасибо за использование бота! 🙌", reply_markup=get_main_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "respond")
def handle_respond(call):
    key = (call.message.chat.id, call.message.message_id)
    if key not in post_owner:
        return
    if key not in responded:
        responded[key] = set()
    if call.from_user.id in responded[key]:
        bot.answer_callback_query(call.id, "Вы уже откликались.")
        return
    responded[key].add(call.from_user.id)
    vip_id = post_owner[key]
    name = get_user_name(call.from_user)
    try:
        bot.send_message(vip_id, f"Вами заинтересовался {name}", parse_mode="Markdown")
        bot.answer_callback_query(call.id, "Отклик отправлен!")
    except:
        bot.send_message(ADMIN_CHAT_ID, "Не удалось отправить отклик VIP")

# ==================== НОВАЯ ФУНКЦИЯ МУТА ДО ПОДПИСКИ ====================
def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

@bot.chat_member_handler()
def handle_new_member(update: types.ChatMemberUpdated):
    if not update.new_chat_member or not update.new_chat_member.user:
        return
    user = update.new_chat_member.user
    chat_id = update.chat.id

    if update.new_chat_member.status not in ("member", "administrator", "creator"):
        return
    if user.is_bot or update.new_chat_member.status in ("administrator", "creator"):
        return

    old_status = update.old_chat_member.status if update.old_chat_member else "left"
    if old_status in ("left", "kicked"):
        time.sleep(3)
        if not is_subscribed(user.id):
            try:
                bot.restrict_chat_member(chat_id, user.id, permissions=MUTED_PERMISSIONS)
                bot.send_message(chat_id, f"🔇 {user.first_name}, подпишитесь на главный канал, чтобы писать!\nПосле подписки напишите любое сообщение — мут снимется.", disable_notification=True)
            except Exception as e:
                print(f"Mute error: {e}")

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'location', 'contact'])
def check_on_message(message):
    if message.chat.type == "private" or not message.from_user:
        return
    try:
        member = bot.get_chat_member(message.chat.id, message.from_user.id)
        if member and not member.can_send_messages:
            if is_subscribed(message.from_user.id):
                bot.restrict_chat_member(message.chat.id, message.from_user.id, permissions=FULL_PERMISSIONS)
                bot.reply_to(message, "✅ Подписка подтверждена! Теперь можете писать.")
            else:
                bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        print(f"Check message error: {e}")

# Массовая проверка (при старте + каждый час)
def subscription_mass_check():
    print(f"[{datetime.now().strftime('%H:%M')}] Запуск проверки подписки...")
    count = 0
    all_chats = set(chat_ids_mk.values()) | set(chat_ids_parni.values()) | set(chat_ids_ns.values()) | set(chat_ids_rainbow.values()) | set(chat_ids_gayznak.values())

    for chat_id in all_chats:
        try:
            admins = {a.user.id for a in bot.get_chat_admins(chat_id)}
            offset = 0
            while True:
                members = bot.get_chat_members(chat_id, offset=offset, limit=200)
                if not members:
                    break
                for m in members:
                    u = m.user
                    if u.is_bot or u.id in admins or m.status in ("administrator", "creator") or not m.can_send_messages:
                        continue
                    if not is_subscribed(u.id):
                        bot.restrict_chat_member(chat_id, u.id, permissions=MUTED_PERMISSIONS)
                        count += 1
                    time.sleep(0.035)
                if len(members) < 200:
                    break
                offset = members[-1].user.id
            time.sleep(0.8)
        except Exception as e:
            print(f"Error in group {chat_id}: {e}")
    print(f"Проверка завершена. Замучено: {count}")

def start_checker():
    subscription_mass_check()
    while True:
        time.sleep(3600)
        subscription_mass_check()

threading.Thread(target=start_checker, daemon=True).start()

@bot.message_handler(commands=['checkall'])
def cmd_checkall(message):
    if message.from_user.id != OWNER_ID:
        return
    bot.reply_to(message, "Запуск ручной проверки...")
    subscription_mass_check()
    bot.reply_to(message, "Готово!")

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == '__main__':
    print("Бот запущен — автомут до подписки работает")
    app.run(host='0.0.0.0', port=5000)