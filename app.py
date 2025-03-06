import os
import telebot
from telebot import types
from flask import Flask, request
from datetime import datetime

# Получаем токен из переменной окружения
TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Создаём Flask-приложение
app = Flask(__name__)

# Списки chat_id для каждой сети и города
chat_ids_mk = {
    "Екатеринбург": -1002210043742,
    "Челябинск": -1002238514762,
    "Пермь": -1002205127231,
    "Ижевск": -1001604781452,
    "Казань": -1002228881675,
    "Оренбург": -1002255568202,
    "Уфа": -1002196469365,
    "Новосибирск": -1002235645677,
    "Красноярск": -1002248474008,
    "Барнаул": -1002234471215,
    "Саранск": -1002426762134,
    "Омск": -1002274367832,
    "Саратов": -1002426762134,
    "Воронеж": -1002207503508,
    "Самара": -1001852671383,
    "Волгоград": -1002426762134,
    "Курган": -1002469285352,
    "Нижний Новгород": -1002426762134,
    "Калининград": -1002217056197,
    "Иркутск": -1002210419274,
    "Кемерово": -1002426762134,
    "Москва": -1002208434096,
    "Санкт Петербург": -1002248474008,
    "Общая группа Юга": -1002161346845,
    "Общая группа Дальнего Востока": -1002210419274,
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
    "Новосибирск": -1002413764329,
    "ЯМАО": -1002371438340
}

# ID VIP-чата "Elite Lounge"
VIP_CHAT_ID = -1002446486648  # Ваш VIP-чат

# Ссылка для верификации и оплаты
VERIFICATION_LINK = "http://t.me/vip_znakbot"  # Ссылка на бота для верификации

# Словарь для хранения всех сообщений пользователей
user_posts = {}

# Создаём клавиатуру с основными кнопками
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Создать новое объявление", "Удалить объявление", "Удалить все объявления")
    return markup

# Форматируем время
def format_time(timestamp):
    return timestamp.strftime("%H:%M, %d %B %Y")

# Получаем имя пользователя с кликабельной ссылкой
def get_user_name(user):
    if user.username:
        return f"[{user.first_name}](https://t.me/{user.username})"
    elif user.id:
        return f"[{user.first_name}](tg://user?id={user.id})"
    else:
        return user.first_name

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "Привет! Я ElitePoster. 👋\nВыберите действие:",
        reply_markup=get_main_keyboard()
    )

# Обработчик для кнопки "Создать новое объявление"
@bot.message_handler(func=lambda message: message.text == "Создать новое объявление")
def create_new_post(message):
    bot.send_message(message.chat.id, "Напишите текст объявления:")
    bot.register_next_step_handler(message, process_text)

# Обработчик для кнопки "Удалить объявление"
@bot.message_handler(func=lambda message: message.text == "Удалить объявление")
def handle_delete_post(message):
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

# Обработчик для кнопки "Удалить все объявления"
@bot.message_handler(func=lambda message: message.text == "Удалить все объявления")
def handle_delete_all_posts(message):
    if message.chat.id in user_posts and user_posts[message.chat.id]:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("Да, удалить всё", "Нет, отменить")
        bot.send_message(message.chat.id, "Вы уверены, что хотите удалить все свои объявления?", reply_markup=markup)
        bot.register_next_step_handler(message, process_delete_all_choice)
    else:
        bot.send_message(message.chat.id, "❌ У вас нет опубликованных объявлений.")

# Обработчик выбора объявления для удаления
def process_delete_choice(message):
    if message.text == "Отмена":
        bot.send_message(message.chat.id, "Удаление отменено.", reply_markup=get_main_keyboard())
    else:
        try:
            # Ищем выбранное объявление
            for post in user_posts[message.chat.id]:
                time_formatted = format_time(post["time"])
                if message.text == f"Удалить: {time_formatted}, {post['city']}, {post['network']}":
                    # Удаляем объявление
                    bot.delete_message(post["chat_id"], post["message_id"])
                    user_posts[message.chat.id].remove(post)
                    bot.send_message(message.chat.id, "✅ Объявление успешно удалено.", reply_markup=get_main_keyboard())
                    return
            bot.send_message(message.chat.id, "❌ Объявление не найдено.")
        except (ValueError, IndexError):
            bot.send_message(message.chat.id, "❌ Ошибка! Пожалуйста, выберите объявление из списка.")

# Обработчик подтверждения удаления всех объявлений
def process_delete_all_choice(message):
    if message.text == "Да, удалить всё":
        # Удаляем все объявления
        for post in user_posts[message.chat.id]:
            try:
                bot.delete_message(post["chat_id"], post["message_id"])
            except telebot.apihelper.ApiTelegramException as e:
                bot.send_message(message.chat.id, f"⚠️ Не удалось удалить одно из объявлений: {e.description}")
        # Очищаем список объявлений пользователя
        user_posts[message.chat.id] = []
        bot.send_message(message.chat.id, "✅ Все ваши объявления успешно удалены.", reply_markup=get_main_keyboard())
    else:
        bot.send_message(message.chat.id, "Удаление отменено.", reply_markup=get_main_keyboard())

# Функция для обработки текста объявления
def process_text(message):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "Вы вернулись в главное меню.", reply_markup=get_main_keyboard())
        return

    if message.photo or message.video:
        # Если пользователь отправил медиа, сохраняем его
        if message.photo:
            media_type = "photo"
            file_id = message.photo[-1].file_id  # Берём самое большое фото
            text = message.caption if message.caption else ""
        elif message.video:
            media_type = "video"
            file_id = message.video.file_id
            text = message.caption if message.caption else ""
    elif message.text:
        # Если пользователь отправил только текст
        media_type = None
        file_id = None
        text = message.text
    else:
        bot.send_message(message.chat.id, "❌ Ошибка! Отправьте текст, фото или видео.")
        bot.register_next_step_handler(message, process_text)
        return

    # Спрашиваем подтверждение текста
    confirm_text(message, text, media_type, file_id)

# Функция для подтверждения текста
def confirm_text(message, text, media_type=None, file_id=None):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Да", "Нет")
    bot.send_message(message.chat.id, f"Ваш текст:\n{text}\n\nВсё верно?", reply_markup=markup)
    bot.register_next_step_handler(message, handle_confirmation, text, media_type, file_id)

# Обработчик подтверждения
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

# Функция для получения клавиатуры выбора сети
def get_network_markup():
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Мужской Клуб", "ПАРНИ 18+", "Обе сети", "Назад")
    return markup

# Функция для выбора сети
def select_network(message, text, media_type, file_id):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "Напишите текст объявления:")
        bot.register_next_step_handler(message, process_text)
        return

    selected_network = message.text
    if selected_network in ["Мужской Клуб", "ПАРНИ 18+", "Обе сети"]:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True, row_width=2)
        cities = chat_ids_mk.keys() if selected_network == "Мужской Клуб" else \
                chat_ids_parni.keys() if selected_network == "ПАРНИ 18+" else \
                list(chat_ids_mk.keys()) + list(chat_ids_parni.keys())
        for city in cities:
            markup.add(city)
        markup.add("Выбрать другую сеть", "Назад")
        bot.send_message(message.chat.id, "📍 Выберите город для публикации или нажмите 'Выбрать другую сеть':", reply_markup=markup)
        bot.register_next_step_handler(message, select_city_and_publish, text, selected_network, media_type, file_id)
    else:
        bot.send_message(message.chat.id, "❌ Ошибка! Выберите правильную сеть.")
        bot.register_next_step_handler(message, process_text)

# Функция для выбора города и публикации объявления
def select_city_and_publish(message, text, selected_network, media_type, file_id):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "📋 Выберите сеть для публикации:", reply_markup=get_network_markup())
        bot.register_next_step_handler(message, select_network, text, media_type, file_id)
        return

    city = message.text
    if city == "Выбрать другую сеть":
        bot.send_message(message.chat.id, "📋 Выберите сеть для публикации:", reply_markup=get_network_markup())
        bot.register_next_step_handler(message, select_network, text, media_type, file_id)
    else:
        try:
            # Проверка на VIP-участника
            chat_member = bot.get_chat_member(VIP_CHAT_ID, message.from_user.id)
            if chat_member.status in ["member", "administrator", "creator"]:
                vip_tag = "\n\n⭐️ Привилегированный участник ⭐️"
                # Создаем кликабельное имя пользователя
                user_name = get_user_name(message.from_user)
                full_text = f"📢 Объявление от {user_name}:\n\n{text}{vip_tag}"
                # Публикация в выбранных сетях
                if selected_network == "Обе сети":
                    networks = ["Мужской Клуб", "ПАРНИ 18+"]
                else:
                    networks = [selected_network]

                for network in networks:
                    chat_dict = chat_ids_mk if network == "Мужской Клуб" else chat_ids_parni
                    if city in chat_dict:
                        chat_id = chat_dict[city]
                        try:
                            if media_type == "photo":
                                sent_message = bot.send_photo(chat_id, file_id, caption=full_text, parse_mode="Markdown")
                            elif media_type == "video":
                                sent_message = bot.send_video(chat_id, file_id, caption=full_text, parse_mode="Markdown")
                            else:
                                sent_message = bot.send_message(chat_id, full_text, parse_mode="Markdown")
                            # Сохраняем ID сообщения, время, город и сеть
                            if message.chat.id not in user_posts:
                                user_posts[message.chat.id] = []
                            user_posts[message.chat.id].append({
                                "message_id": sent_message.message_id,
                                "chat_id": chat_id,
                                "time": datetime.now(),  # Время публикации
                                "city": city,            # Город
                                "network": network       # Сеть
                            })
                            bot.send_message(message.chat.id, f"✅ Ваше объявление опубликовано в сети «{network}», городе {city}.")
                        except telebot.apihelper.ApiTelegramException as e:
                            bot.send_message(message.chat.id, f"❌ Ошибка: {e.description}")
                    else:
                        bot.send_message(message.chat.id, f"❌ Ошибка! Город '{city}' не найден в сети «{network}».")

                # Предлагаем опубликовать ещё одно объявление
                ask_for_new_post(message)

            else:
                # Если пользователь не VIP, предлагаем верификацию
                markup = types.InlineKeyboardMarkup()
                verify_button = types.InlineKeyboardButton(text="🛠️ Пройти верификацию", url=VERIFICATION_LINK)
                markup.add(verify_button)
                bot.send_message(message.chat.id, "🔓 Вы не являетесь привилегированным участником. Для публикации объявлений пройдите верификацию:", reply_markup=markup)
        except telebot.apihelper.ApiTelegramException as e:
            bot.send_message(message.chat.id, f"⚠️ Ошибка при проверке VIP-статуса: {e.description}")

# Функция для предложения нового объявления
def ask_for_new_post(message):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Да", "Нет")
    bot.send_message(message.chat.id, "Хотите опубликовать ещё одно объявление?", reply_markup=markup)
    bot.register_next_step_handler(message, handle_new_post_choice)

# Обработчик выбора (Да/Нет)
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

# Вебхук для обработки входящих сообщений
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

# Запуск Flask-приложения
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
