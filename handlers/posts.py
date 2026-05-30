from telebot import types
from datetime import datetime
import random
from config import chat_ids_mk, chat_ids_parni, chat_ids_ns, chat_ids_rainbow, chat_ids_gayznak, all_cities
from database import posts_collection, temp_posts, users_collection
from utils import format_time, get_user_name, escape_md, clean_user_text, net_key_to_name

def register_post_handlers(bot, is_banned_in_network, get_main_keyboard, is_real_vip):

    @bot.message_handler(func=lambda message: message.text == "Создать новое объявление")
    def create_new_post(message):
        if message.chat.type != "private":
            bot.send_message(message.chat.id, "Пожалуйста, используйте ЛС для работы с ботом.")
            return

        # 👇 НОВЫЙ ЖУЧОК СКАЙНЕТА 👇
        users_collection.update_one({"_id": message.from_user.id}, {"$set": {"intent_post_ads": True}}, upsert=True)
        # 👆 ==================== 👆

        if is_banned_in_network(message.from_user.id):
            bot.send_message(message.chat.id, "🚫 Вы не можете публиковать объявления. Ваш аккаунт заблокирован в сети.")
            return

        # 👑 ЛОГИКА ДЛЯ VIP-ПОЛЬЗОВАТЕЛЕЙ
        if is_real_vip(message.from_user.id):
            # Очищаем старые ручные черновики, чтобы не было конфликтов
            temp_posts.delete_one({"_id": message.from_user.id})
            
            # 🔥 ВАЖНО: Укажи тут свой домен Render!
            APP_URL = "https://elite-poster-bot.onrender.com"
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            # В ссылке передаем роут, который отдает HTML страничку
            web_app_info = types.WebAppInfo(url=f"{APP_URL}/mini_app_post")
            
            markup.add(types.InlineKeyboardButton("🚀 Быстрое создание (Мини-апп)", web_app=web_app_info))
            markup.add(types.InlineKeyboardButton("✍️ По шагам вручную", callback_data="manual_vip_post"))
            
            bot.send_message(
                message.chat.id, 
                "👑 **VIP-Публикация**\n\n"
                "Выберите удобный способ создания объявления:\n\n"
                "📱 **Мини-апп:** Удобная форма на одном экране.\n"
                "🤖 **Вручную:** Классический пошаговый ввод в диалоге с ботом.", 
                reply_markup=markup,
                parse_mode="Markdown"
            )
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

    # 🚀 ========================================================== 🚀
    # 👇 ВОТ ЭТОТ НОВЫЙ БЛОК ВСТАВЛЯЕМ СЮДА 👇
    # 🚀 ========================================================== 🚀
    @bot.message_handler(func=lambda message: message.text == "🚀 Опубликовать анкету")
    def finalize_mini_app_post(message):
        uid = message.from_user.id
        draft = temp_posts.find_one({"_id": uid, "status": "ready_to_publish"})
        if not draft: return

        media_type = None
        file_id = uid

        media_count = len(draft.get('media', []))
        if media_count == 1:
            media_type = draft['media'][0]['type']
            file_id = draft['media'][0]['id']
        elif media_count > 1:
            media_type = "album"

        # ⚡️ Берем сеть и город прямо из черновика Мини-аппа
        network = draft.get('network', 'Неизвестно')
        city = draft.get('city', 'Неизвестно')

        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("✅ Всё верно, публиковать!", "❌ Отмена")
        
        bot.send_message(
            message.chat.id, 
            f"📋 **Финальная проверка:**\n\n"
            f"🌐 **Сеть:** {network}\n"
            f"📍 **Город:** {city}\n\n"
            f"📝 **Текст:**\n{draft['text']}\n\n"
            f"Всё верно?", 
            reply_markup=markup,
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(message, handle_mini_app_publish, draft['text'], network, city, media_type, file_id)

    def handle_mini_app_publish(message, text, network, city, media_type, file_id):
        if message.text == "✅ Всё верно, публиковать!":
            bot.send_message(message.chat.id, "🚀 Запускаю рассылку...", reply_markup=types.ReplyKeyboardRemove())
            
            # Хак: подменяем message.text на название города, 
            # так как твоя старая функция select_city_and_publish ждет город именно там
            message.text = city
            select_city_and_publish(message, text, network, media_type, file_id)
        else:
            bot.send_message(message.chat.id, "❌ Публикация отменена. Вы можете создать новое объявление из меню.", reply_markup=get_main_keyboard())
            temp_posts.delete_one({"_id": message.from_user.id})
    # 👆 КОНЕЦ НОВОГО БЛОКА 👆

    # ==========================================================
    # 👇 НИЖЕ ИДЕТ ТОЛЬКО СТАРЫЙ РУЧНОЙ МЕТОД (ЛЕГАСИ) 👇
    # ==========================================================
    
    @bot.callback_query_handler(func=lambda call: call.data == "manual_vip_post")
    def start_manual_vip_post(call):
        bot.answer_callback_query(call.id)
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        
        msg = bot.send_message(call.message.chat.id, "✍️ **Напишите текст вашего объявления:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_draft_text)

    def process_draft_text(message):
        if message.text == "Назад":
            bot.send_message(message.chat.id, "Вы вернулись в главное меню.", reply_markup=get_main_keyboard())
            return

        if not message.text:
            msg = bot.send_message(message.chat.id, "❌ Ошибка! Нужно прислать именно текст. Попробуйте еще раз:")
            bot.register_next_step_handler(msg, process_draft_text)
            return

        temp_posts.update_one(
            {"_id": message.from_user.id},
            {"$set": {"text": message.html or message.text, "media": []}},
            upsert=True
        )

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("✅ Все файлы загружены. Опубликовать")
        markup.add("Назад")

        warn_text = (
            "📸 **Теперь отправляйте фото или видео (до 10 штук).**\n\n"
            "⚠️ **ВНИМАНИЕ:** Публикация ПОРНО-материалов строго запрещена во всех сетях, кроме «ПАРНИ 18+».\n"
            "За нарушение в общих чатах — мгновенный бан без возврата VIP.\n\n"
            "Как закончите — жмите кнопку **«✅ Все файлы загружены»** 👇"
        )
        msg = bot.send_message(message.chat.id, warn_text, reply_markup=markup, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_draft_media_loop)

    def process_draft_media_loop(message):
        uid = message.from_user.id

        if message.text == "✅ Все файлы загружены. Опубликовать":
            draft = temp_posts.find_one({"_id": uid})
            if not draft: return
            
            media_type = None
            file_id = uid
            
            media_count = len(draft.get('media', []))
            if media_count == 1:
                media_type = draft['media'][0]['type']
                file_id = draft['media'][0]['id']
            elif media_count > 1:
                media_type = "album"

            confirm_text(message, draft['text'], media_type=media_type, file_id=file_id)
            return

        if message.text == "Назад":
            bot.send_message(message.chat.id, "Создание отменено.", reply_markup=get_main_keyboard())
            return

        bot.register_next_step_handler(message, process_draft_media_loop)

        # Собираем медиа
        media_item = None
        if message.photo: media_item = {"type": "photo", "id": message.photo[-1].file_id}
        elif message.video: media_item = {"type": "video", "id": message.video.file_id}

        if media_item:
            draft = temp_posts.find_one({"_id": uid})
            current_media = draft.get('media', [])
            
            if len(current_media) >= 10:
                if not message.media_group_id:
                    bot.send_message(message.chat.id, "🚫 Лимит 10 файлов исчерпан! Жмите кнопку «Опубликовать».")
            else:
                temp_posts.update_one({"_id": uid}, {"$push": {"media": media_item}})
                if not message.media_group_id:
                    bot.send_message(message.chat.id, f"📥 Файл принят ({len(current_media) + 1}/10)")

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
        else: bot.send_message(message.chat.id, "❌ У вас нет опубликованных объявлений.")

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
        else: bot.send_message(message.chat.id, "❌ У вас нет опубликованных объявлений.")

    def process_delete_choice(message):
        if message.text == "Отмена":
            bot.send_message(message.chat.id, "Удаление отменено.", reply_markup=get_main_keyboard())
            return
        user_id = message.from_user.id
        posts = list(posts_collection.find({"user_id": user_id}))
        for post in posts:
            time_formatted = format_time(post["time"])
            if message.text == f"Удалить: {time_formatted}, {post['city']}, {post['network']}":
                msg_ids = post.get("message_ids", [post.get("message_id")])
                for m_id in msg_ids:
                    if m_id:
                        try: bot.delete_message(post["chat_id"], m_id)
                        except: pass
                posts_collection.delete_one({"_id": post["_id"]})
                bot.send_message(message.chat.id, "✅ Объявление (и все вложения) полностью удалено.", reply_markup=get_main_keyboard())
                return
        bot.send_message(message.chat.id, "❌ Объявление не найдено.")

    def process_delete_all_choice(message):
        user_id = message.from_user.id
        if message.text == "Да, удалить всё":
            posts = list(posts_collection.find({"user_id": user_id}))
            for post in posts:
                msg_ids = post.get("message_ids", [post.get("message_id")])
                for m_id in msg_ids:
                    if m_id:
                        try: bot.delete_message(post["chat_id"], m_id)
                        except: pass
            posts_collection.delete_many({"user_id": user_id})
            bot.send_message(message.chat.id, "✅ Все ваши объявления успешно удалены.", reply_markup=get_main_keyboard())
        else: bot.send_message(message.chat.id, "Удаление отменено.", reply_markup=get_main_keyboard())

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
            bot.register_next_step_handler(message, process_draft_text)
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
            create_new_post(message)
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
            bot.register_next_step_handler(message, select_network, text, media_type, file_id) # Лучше возвращать на выбор сети!

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
            is_privileged = is_real_vip(user_id)

            if is_privileged:
                # 1. Извлекаем имя юзера в правильном HTML-формате
                user_name_html = f'<a href="tg://user?id={user_id}">{message.from_user.first_name}</a>'

                # 2. Анимированный ВЕРХ (Буквы V I P)
                vip_top_stickers = (
                    '<tg-emoji emoji-id="5467688183229610037">V</tg-emoji>'
                    '<tg-emoji emoji-id="5467466378233543299">I</tg-emoji>'
                    '<tg-emoji emoji-id="5467630896955815565">P</tg-emoji>\n\n'
                )

                # 3. Анимированный НИЗ (Галочка и Звезды)
                vip_bottom = (
                    '\n\n<tg-emoji emoji-id="5949582599012750373">✅</tg-emoji> <b>Анкета проверена администрацией сети</b>\n\n'
                    '<tg-emoji emoji-id="6215039782955783886">🌟</tg-emoji> <b>Привилегированный участник</b> <tg-emoji emoji-id="6215039782955783886">🌟</tg-emoji>'
                )

                # 4. Обновленные заголовки (без старого Markdown)
                headers = [
                    f"💎 VIP-СООБЩЕНИЕ от {user_name_html}! 💎",
                    f"🚨 🔥 Срочное объявление от {user_name_html}! 🚨",
                    f"👑 {user_name_html} публикует элитное объявление: 👑",
                    f"🌟 Особое сообщение от привилегированного пользователя {user_name_html}: 🌟",
                    f"🔒 Только для избранных: сообщение от {user_name_html} 🔒",
                    f"📣 Важное объявление от {user_name_html}!",
                    f"🌐 Объявление уровня PREMIUM от {user_name_html}!",
                    f"📢 Привилегированное сообщение от {user_name_html}:",
                    f"🛑 Эксклюзив! {user_name_html} пишет:",
                    f"💼 Серьёзное объявление от проверенного участника {user_name_html}",
                    f"💠 {user_name_html} публикует объявление с высоким приоритетом",
                    f"🪙 {user_name_html} использует привилегию VIP для объявления:",
                    f"⚠️ Срочно на всех экранах: {user_name_html} врывается с объявлением!",
                    f"🔥 {user_name_html} бросает вызов одиночеству!",
                    f"🚀 {user_name_html} не ждёт — он действует! Объявление внутри:",
                    f"🥵 Горячо! {user_name_html} делится откровенным сообщением:",
                    f"⚡ Найдено ВИП-сообщение! Проверь, что пишет {user_name_html}",
                    f"🧿 Внимание! VIP-сообщение от {user_name_html}",
                    f"🏷️ Объявление с особыми правами: {user_name_html}"
                ]

                # 5. Склеиваем всё вместе (без escape_md, так как мы теперь работаем с HTML)
                full_text = f"{vip_top_stickers}{random.choice(headers)}\n\n{clean_user_text(text)}{vip_bottom}"

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
                        ids_to_store = []
                        if media_type == "album":
                            draft = temp_posts.find_one({"_id": user_id})
                            media_list = []
                            for m in draft['media']:
                                if m['type'] == 'photo': media_list.append(types.InputMediaPhoto(m['id']))
                                else: media_list.append(types.InputMediaVideo(m['id']))
                            
                            sent_album = bot.send_media_group(chat_id, media_list)
                            for msg in sent_album: ids_to_store.append(msg.message_id)
                            
                            sent_text = bot.send_message(chat_id, full_text, parse_mode="HTML", reply_markup=markup_inline)
                            ids_to_store.append(sent_text.message_id)
                            
                        elif media_type == "photo":
                            sent_message = bot.send_photo(chat_id, file_id, caption=full_text, parse_mode="HTML", reply_markup=markup_inline)
                            ids_to_store.append(sent_message.message_id)
                            
                        elif media_type == "video":
                            sent_message = bot.send_video(chat_id, file_id, caption=full_text, parse_mode="HTML", reply_markup=markup_inline)
                            ids_to_store.append(sent_message.message_id)
                            
                        else:
                            sent_message = bot.send_message(chat_id, full_text, parse_mode="HTML", reply_markup=markup_inline)
                            ids_to_store.append(sent_message.message_id)

                        post_data = {
                            "user_id": user_id,
                            "message_ids": ids_to_store,
                            "chat_id": chat_id,
                            "time": datetime.now(),
                            "city": city,
                            "network": network_name
                        }
                        posts_collection.insert_one(post_data)
                        bot.send_message(message.chat.id, f"✅ Ваше объявление опубликовано в сети «{network_name}», городе {city}.")
                    except Exception as e:
                        bot.send_message(message.chat.id, f"❌ Ошибка отправки в {network_name}: {str(e)}")

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

        except Exception as e:
            bot.send_message(message.chat.id, f"⚠️ Ошибка при проверке VIP-статуса: {str(e)}")

    def ask_for_new_post(message):
        bot.send_message(
            message.chat.id, 
            "✅ Публикация завершена!\nЕсли захотите создать еще одно объявление, воспользуйтесь меню ниже.", 
            reply_markup=get_main_keyboard()
        )