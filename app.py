import os
import telebot
from telebot import types, formatting
from flask import Flask, request
from datetime import datetime

# Получаем токен из переменной окружения
TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Создаём Flask-приложение
app = Flask(__name__)

# ID администратора для уведомлений (ваш chat ID)
ADMIN_CHAT_ID = 479938867  # Ваш chat ID

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

# Функция для экранирования текста
def escape_text(text):
    return formatting.escape_markdown(text)

# Получаем имя пользователя с кликабельной ссылкой
def get_user_name(user):
    if user.username:
        return f"[{escape_text(user.first_name)}](https://t.me/{user.username})"
    elif user.id:
        return f"[{escape_text(user.first_name)}](tg://user?id={user.id})"
    else:
        return escape_text(user.first_name)
# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    # Сбрасываем состояние пользователя
    if message.chat.id in user_posts:
        del user_posts[message.chat.id]
    bot.send_message(
        message.chat.id,
        "Привет! Я ElitePoster. 👋\nВыберите действие:",
        reply_markup=get_main_keyboard()
    )

# Обработчик события "my_chat_member"
@bot.my_chat_member_handler()
def handle_chat_member_update(message):
    if message.new_chat_member.status == "kicked":
        # Удаляем данные пользователя, если он заблокировал бота
        if message.chat.id in user_posts:
            del user_posts[message.chat.id]
        bot.send_message(
            ADMIN_CHAT_ID,  # Уведомление вам, как администратору
            f"Пользователь {message.chat.id} заблокировал бота."
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
# Вебхук для обработки входящих сообщений
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

# Запуск Flask-приложения
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
