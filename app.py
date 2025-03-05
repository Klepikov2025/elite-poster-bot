import os
import telebot
from flask import Flask, request

# Получаем токен из переменной окружения
TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Создаём Flask-приложение
app = Flask(__name__)

# Вебхук для обработки входящих сообщений
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Привет! Я ElitePoster. 👋")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
