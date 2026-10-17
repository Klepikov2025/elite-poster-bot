"""
core/config_schema.py — реестр настроек, которые меняются из веб-панели (вкладка «🎛 Управление»).

Каждая настройка: где лежит в базе (settings._id = doc, поле = field), тип, значение по умолчанию
(= как было в коде), подсказка. Добавить новую ручку = добавить строку сюда и читать её через cfg().
owner=True — видит и меняет только владелец (деньги, рефералка).
bots — какие боты читают настройку (для подписи в панели).
"""

G_MONEY = "💰 Цены и курсы"
G_VIP = "👑 VIP-воронка"
G_CPA = "💼 CPA-агенты"
G_POSTER = "📝 Мини-приложение публикации"
G_MOD = "🛡 Модерация и уборка"
G_AI = "🤖 ИИ"
G_LINKS = "🔗 Ссылки"
G_STEALTH = "🥷 Автопилот"
G_SEC = "🗂 Секретарь"
G_BEYOND = "🏳️‍🌈 BEYOND"
G_MP = "📢 МП (реклама)"
G_FINES = "⚖️ Прайс штрафов"
G_CASH = "💸 Кэшбэк и вывод"
G_CASINO = "🎰 Казино и экономика"
G_JOBS = "⏰ Автособытия Секретаря"
G_ECON = "🏛 Экономика: краны и налоги"
G_BANK = "🏦 Банковская ячейка"
G_KARMA = "⭐ Карма"
G_AUCT = "🔨 Теневой аукцион и артефакты"

_LIST = r"\d+(\s*[,;]\s*\d+)*"
_PAIRS = r"\d+\s*:\s*\d+(\s*[,;]\s*\d+\s*:\s*\d+)*"
_TIME = r"([01]?\d|2[0-3]):[0-5]\d"

SCHEMA = [
    # --- деньги ---
    {"key": "rub_per_star", "group": G_MONEY, "label": "Курс: рублей за 1 ⭐️", "type": "float", "default": 2.0, "min": 0.5, "max": 10,
     "help": "Единый курс сети: оплата с рублёвого баланса, крипто-счета, цены на рынке.", "bots": "Скайнет, Секретарь, BEYOND, МП", "owner": True},
    {"key": "points_per_star", "group": G_MONEY, "label": "Курс: очков за 1 ⭐️", "type": "int", "default": 5, "min": 1, "max": 100,
     "help": "Оплата очками: VIP, штрафы, индульгенция, BEYOND, реклама.", "bots": "Скайнет, Секретарь, BEYOND, МП", "owner": True},
    {"key": "city_pass_price", "group": G_MONEY, "label": "Пропуск в чужой город, ⭐️", "type": "int", "default": 250, "min": 1, "max": 100000,
     "bots": "Скайнет", "owner": True},
    {"key": "fine_tag_free", "group": G_FINES, "label": "Иммунитет (тег «Свободен»), ⭐️", "type": "int", "default": 650, "min": 1, "max": 100000,
     "help": "Оплата ровно этой суммы даёт тег «Свободен». Этой же суммой Секретарь штрафует за карантин, «1 мая», проваленный и просроченный кружок.", "bots": "Скайнет, Секретарь", "owner": True},
    {"key": "fine_tag_sponsor", "group": G_FINES, "label": "Взнос спонсора (тег «Спонсор_Одобрен»), ⭐️", "type": "int", "default": 750, "min": 1, "max": 100000,
     "help": "Оплата этой суммы даёт тег «Спонсор_Одобрен» (иммунитет к фильтру коммерции). Секретарь берёт её за спонсорство.", "bots": "Скайнет, Секретарь", "owner": True},
    {"key": "ref_tiers", "group": G_MONEY, "label": "Рефералка: пороги и проценты", "type": "text", "default": "10:10, 30:13, 50:15, 100:17, *:20",
     "help": "Формат «до N приглашённых : процент». Звёздочка — все, кто больше. Процент считается от цены VIP.", "bots": "Скайнет", "owner": True},

    # --- VIP ---
    {"key": "vip_remind_days", "group": G_VIP, "label": "Напомнить застрявшему через, дней", "type": "int", "default": 7, "min": 1, "max": 60,
     "help": "Если человек начал вступление в VIP и остановился (не прислал кружок или не оплатил).", "bots": "Скайнет"},
    {"key": "vip_ban_days", "group": G_VIP, "label": "Бан после напоминания через, дней", "type": "int", "default": 3, "min": 1, "max": 60,
     "help": "Работает, только если включён тумблер «VIP-Снайпер». Тех, чей кружок на проверке, не трогает.", "bots": "Скайнет"},
    {"key": "cheap_stars_url", "group": G_VIP, "label": "Ссылка «купить звёзды дешевле»", "type": "text",
     "default": "https://t.me/Avrrorkastarbot?start=7924963993", "help": "Отправляется вместе со счётом на VIP и перед тарифами рекламы. Пусто — не отправлять.", "bots": "Скайнет, МП", "owner": True},

    # --- CPA ---
    {"key": "cpa_hold_days", "group": G_CPA, "label": "Холд лида, дней", "type": "int", "default": 14, "min": 1, "max": 90,
     "help": "Сколько приведённый человек должен продержаться в чате, чтобы агент получил кейс.", "bots": "Скайнет"},
    {"key": "cpa_welcome_points", "group": G_CPA, "label": "Стартовый набор новичку: очки", "type": "int", "default": 50, "min": 0, "max": 10000, "bots": "Скайнет", "owner": True},
    {"key": "cpa_welcome_shields", "group": G_CPA, "label": "Стартовый набор новичку: щиты", "type": "int", "default": 1, "min": 0, "max": 100, "bots": "Скайнет", "owner": True},
    {"key": "cpa_contest_min", "group": G_CPA, "label": "Конкурс месяца: минимум лидов", "type": "int", "default": 50, "min": 1, "max": 10000, "bots": "Скайнет"},
    {"key": "cpa_prize_4", "group": G_CPA, "label": "Конкурс: 4 место, очки", "type": "int", "default": 3000, "min": 0, "max": 1000000, "bots": "Скайнет", "owner": True},
    {"key": "cpa_prize_5", "group": G_CPA, "label": "Конкурс: 5 место, очки", "type": "int", "default": 1500, "min": 0, "max": 1000000, "bots": "Скайнет", "owner": True},

    # --- мини-приложение ---
    {"key": "bump_hours", "doc": "moderation_limits", "group": G_POSTER, "label": "Поднимать анкету не чаще, часов", "type": "int", "default": 12, "min": 1, "max": 168, "bots": "Скайнет"},
    {"key": "poster_cooldown_min", "group": G_POSTER, "label": "Пауза между публикациями, минут", "type": "int", "default": 2, "min": 1, "max": 1440, "bots": "Скайнет"},
    {"key": "poster_max_templates", "group": G_POSTER, "label": "Шаблонов у одного человека", "type": "int", "default": 5, "min": 1, "max": 30, "bots": "Скайнет"},
    {"key": "poster_max_drafts", "group": G_POSTER, "label": "Черновиков у одного человека", "type": "int", "default": 10, "min": 1, "max": 50, "bots": "Скайнет"},

    # --- модерация ---
    {"key": "join_via_bot", "group": G_MOD, "label": "Вход в группы через бота", "type": "bool", "default": False,
     "help": "Кто ни разу не запускал Скайнета, получает в личку кнопку «Вступить»: нажал — бот открылся и заявка одобрена. Так личка открывается навсегда и до человека доходят рассылки. Кто уже запускал бота — проходит сразу, как раньше.", "bots": "Скайнет"},
    {"key": "join_gate_text", "group": G_MOD, "label": "Текст с кнопкой «Вступить»", "type": "textarea",
     "default": "👋 Почти готово! Чтобы вступить в «{chat}», нажмите кнопку ниже — откроется бот, и заявка одобрится сама.\n\nЗаодно вы будете получать важные новости сети.",
     "help": "{chat} — название группы. Сообщение приходит сразу после заявки.", "bots": "Скайнет"},
    {"key": "join_gate_timeout_hours", "group": G_MOD, "label": "Не нажал кнопку — одобрить сами через, ч", "type": "float", "default": 24, "min": 0, "max": 720,
     "help": "0 — не одобрять (заявка висит, пока человек не нажмёт кнопку или её не одобрит админ).", "bots": "Скайнет"},
    {"key": "subscribe_bonus_points", "group": G_MOD, "label": "Бонус старому участнику за подписку на бота, очков", "type": "int", "default": 50, "min": 0, "max": 100000,
     "help": "Разово, по ссылке t.me/<бот Скайнета>?start=sub — вставьте её кнопкой в рассылку по группам. Только тем, кто уже был в сети; 0 — без бонуса.", "bots": "Скайнет"},
    {"key": "cleanup_minutes", "doc": "moderation_limits", "group": G_MOD, "label": "Удалять прожарки бота через, минут", "type": "int", "default": 10, "min": 1, "max": 1440, "bots": "Скайнет"},
    {"key": "repost_strikes", "group": G_MOD, "label": "Страйков за баяны и копипаст до мута", "type": "int", "default": 3, "min": 1, "max": 20, "bots": "Скайнет"},
    {"key": "photo_similarity", "group": G_MOD, "label": "Анти-баян: чувствительность к похожим фото", "type": "int", "default": 8, "min": 0, "max": 20,
     "help": "0 — только точные копии, 8 — обрезанные и пережатые копии, больше — ловит и просто похожие.", "bots": "Скайнет"},
    {"key": "spy_delete_delay", "group": G_MOD, "label": "Шпион: удалять спам ботов-мусорщиков через, сек", "type": "int", "default": 12, "min": 0, "max": 3600, "bots": "Шпион"},
    {"key": "spy_trash_bots", "group": G_MOD, "label": "Шпион: ID ботов-мусорщиков (через запятую)", "type": "text", "default": "7195399721",
     "help": "Сообщения этих ботов Шпион удаляет из чатов. Сейчас: @CPBlockerBot.", "bots": "Шпион"},
    {"key": "corpse_sweep_hours", "group": G_MOD, "label": "Шпион: искать удалённые аккаунты в группах раз в, часов", "type": "int", "default": 24, "min": 0, "max": 720,
     "help": "Шпион просматривает участников групп сети и отдаёт Скайнету «Deleted Account» на вынос. 0 — выключено. Вынос работает, пока включён тумблер «Автоочистка трупов».", "bots": "Шпион, Скайнет"},
    {"key": "corpse_history_depth", "group": G_MOD, "label": "Шпион: сколько сообщений истории просматривать в больших группах", "type": "int", "default": 20000, "min": 0, "max": 200000,
     "help": "Если Telegram отдал не весь список участников, Шпион ищет удалённые аккаунты среди авторов последних N сообщений группы. 0 — не искать в истории.", "bots": "Шпион"},

    # --- ИИ ---
    {"key": "groq_model", "group": G_AI, "label": "Модель Groq", "type": "text", "default": "openai/gpt-oss-120b",
     "help": "Если Groq снова отключит модель, впишите новую из console.groq.com/docs/models. Пусто — по умолчанию.", "bots": "Скайнет, Шпион"},
    {"key": "gemini_model", "group": G_AI, "label": "Модель Google Gemini (резерв)", "type": "text", "default": "gemini-3.8-flash",
     "help": "Вторая «умная» линия после основной модели Groq. Работает, только если в Render у Скайнета задан GEMINI_API_KEY (бесплатно, без карты: aistudio.google.com → Get API key). Если Google переименует модель — впишите новое название сюда.", "bots": "Скайнет"},
    {"key": "groq_fallback_models", "group": G_AI, "label": "Запасные модели Groq (через запятую)", "type": "text", "default": "qwen/qwen3.8-27b, openai/gpt-oss-20b",
     "help": "Когда у основной модели кончается лимит (ошибка 429), бот сначала пробует Google Gemini (если в Render задан GEMINI_API_KEY), потом эти запасные. Запасные слабее, поэтому их «виновен» не исполняется сам — админам приходят кнопки. Прожарки сразу идут на запасные, чтобы беречь основную для проверок.", "bots": "Скайнет"},

    # --- ссылки ---
    {"key": "support_bot", "group": G_LINKS, "label": "Бот поддержки (без @)", "type": "text", "default": "FAQMKBOT", "bots": "Скайнет, МП",
     "help": "Куда ведут кнопки «Поддержка» / «Пройти верификацию» и автоответы Скайнета в чатах."},
    {"key": "vip_bot", "group": G_LINKS, "label": "Бот VIP-вступления (без @)", "type": "text", "default": "Elitepost_bot", "bots": "Скайнет",
     "help": "Кнопка «Купить VIP-статус» в предупреждениях Скайнета."},

    # --- Секретарь ---
    {"key": "support_price", "group": G_SEC, "label": "Доступ к поддержке, ⭐️", "type": "int", "default": 50, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "support_group_price", "group": G_SEC, "label": "Цена вопроса в платной группе поддержки (текст)", "type": "text",
     "default": "от 60 до 150 звёзд", "help": "Подставляется в сообщение «Сначала задайте вопрос в платной группе и оплатите …». Пишите как в тексте: «от 60 до 150 звёзд».",
     "bots": "Секретарь", "owner": True},
    {"key": "spam_fine", "group": G_SEC, "label": "Штраф за спам кнопками, ⭐️", "type": "int", "default": 111, "min": 1, "max": 100000,
     "help": "Выставляется после 3 ошибок подряд в меню Секретаря. Не должен совпадать с ценой поддержки.", "bots": "Секретарь", "owner": True},
    {"key": "indulgence_price", "group": G_SEC, "label": "Индульгенция, ⭐️", "type": "int", "default": 2000, "min": 1, "max": 100000,
     "help": "Снятие бана без вопросов + иммунитет. Доступа в VIP и BEYOND не даёт.", "bots": "Секретарь, Скайнет", "owner": True},
    {"key": "shop_price_50", "group": G_SEC, "label": "Магазин: 50 очков, ⭐️", "type": "int", "default": 50, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "shop_price_300", "group": G_SEC, "label": "Магазин: 300 очков, ⭐️", "type": "int", "default": 200, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "shop_price_1000", "group": G_SEC, "label": "Магазин: 1000 очков + щит, ⭐️", "type": "int", "default": 500, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},

    # --- BEYOND ---
    {"key": "beyond_reject_days", "group": G_BEYOND, "label": "Повторная заявка после отказа через, дней", "type": "int", "default": 3, "min": 1, "max": 365, "bots": "BEYOND"},
    {"key": "beyond_remind_days", "group": G_BEYOND, "label": "Напомнить застрявшему через, дней", "type": "int", "default": 7, "min": 1, "max": 60, "bots": "BEYOND"},
    {"key": "beyond_ban_days", "group": G_BEYOND, "label": "Бан после напоминания через, дней", "type": "int", "default": 3, "min": 1, "max": 60, "bots": "BEYOND"},
    {"key": "beyond_invite_days", "group": G_BEYOND, "label": "Ссылка-приглашение живёт, дней", "type": "int", "default": 7, "min": 1, "max": 30, "bots": "BEYOND"},
    {"key": "beyond_fine_price", "group": G_BEYOND, "label": "Штраф BEYOND, ⭐️", "type": "int", "default": 0, "min": 0, "max": 100000, "help": "Сколько платит человек из ЧС, чтобы подать заявку. 0 — равен цене вступления (как было раньше).", "bots": "BEYOND, Скайнет", "owner": True},
    {"key": 'beyond_txt_start', "group": G_BEYOND, "label": 'Текст приветствия (/start)', "type": "textarea", "default": 'Привет, {name}!\nЭто бот поддержки участников и кандидатов в <b>Beyond</b> — закрытое транс-пространство для знакомств, общения и поддержки.\n\nДЛЯ ТЕХ, КТО НЕ НАУЧИЛСЯ ЧИТАТЬ В 1 КЛАССЕ - ДОСТУП ПЛАТНЫЙ ДЛЯ ОПРЕДЕЛЕННЫХ КАТЕГОРИЙ!\n\n📌 Здесь не ведётся обсуждение других групп.\n❌ Не блокируй бота — это приведёт к отказу и глобальному бану.\n💬 Все вопросы — только по теме Beyond.\n🚪 Передумал(а) на любом этапе до отправки анкеты — напиши <b>{opt_out}</b>, после этого бота можно спокойно заблокировать.\n\nПожалуйста, цени своё и наше время. Если готов, жми кнопку ниже:', "help": '{name} — имя человека, {opt_out} — фраза отказа. HTML: <b>, <i>.', "bots": "BEYOND"},
    {"key": 'beyond_txt_bio', "group": G_BEYOND, "label": 'Вопрос-анкета', "type": "textarea", "default": 'Оставь краткую анкету о себе одним сообщением:\n- Имя/Ник\n- Возраст\n- Кратко о себе\n\n<i>Пиши честно, система проверяет заявки.</i>', "help": 'Что прислать о себе.', "bots": "BEYOND"},
    {"key": 'beyond_txt_proof_trans', "group": G_BEYOND, "label": 'Запрос подтверждения (транс)', "type": "textarea", "default": 'Обязательное условие: отправь <b>фото или видео-кружок в образе</b>', "help": 'Пусто — текст по умолчанию.', "bots": "BEYOND"},
    {"key": 'beyond_txt_proof_nb', "group": G_BEYOND, "label": 'Вопрос для небинарных', "type": "textarea", "default": 'Объясни своими словами в одном сообщении:\nЧто для тебя значит небинарность?', "help": 'Пусто — текст по умолчанию.', "bots": "BEYOND"},
    {"key": 'beyond_txt_rejected', "group": G_BEYOND, "label": 'Текст отказа', "type": "textarea", "default": '❌ <b>К сожалению, ваша заявка отклонена.</b>\n\nНесоответствие правилам или формату сообщества.\nУточнить причину, пройти проверку или оспорить решение можно в Службе Поддержки: @FAQMKBOT', "help": 'Пусто — текст по умолчанию.', "bots": "BEYOND"},
    {"key": 'beyond_txt_fake', "group": G_BEYOND, "label": 'Текст «проверка не пройдена → в платники»', "type": "textarea", "default": '⚠️ <b>Проверка не пройдена.</b>\n\nВы переведены в категорию «Интересующиеся». Оплатите взнос.', "help": 'Пусто — текст по умолчанию.', "bots": "BEYOND"},

    # --- МП (рекламный бот) ---
    {"key": "mp_daily_limit", "group": G_MP, "label": "Публикаций в день на одну сеть/город", "type": "int", "default": 3, "min": 1, "max": 50,
     "help": "Сколько раз рекламодатель может выложить объявление в одной сети одного города за сутки (автопосты тоже считаются).", "bots": "МП"},
    {"key": "mp_vip_markup", "group": G_MP, "label": "Наценка за рекламу TG-групп/каналов (×)", "type": "float", "default": 1.5, "min": 1, "max": 10,
     "help": "1.5 = +50% к прайсу. Применяется после одобрения ресурса админом.", "bots": "МП", "owner": True},
    {"key": "mp_pin_markup", "group": G_MP, "label": "Наценка за закреп (×)", "type": "float", "default": 1.2, "min": 1, "max": 10,
     "help": "1.2 = +20% к цене тарифа.", "bots": "МП", "owner": True},
    {"key": "mp_renew_discount", "group": G_MP, "label": "Скидка на продление, %", "type": "int", "default": 10, "min": 0, "max": 90,
     "help": "Удержание: действует, пока доступ идёт, и N дней после окончания. 0 — выключить. Напоминания бота пишут про эту скидку.", "bots": "МП", "owner": True},
    {"key": "mp_renew_grace_days", "group": G_MP, "label": "Скидка на продление после окончания, дней", "type": "int", "default": 3, "min": 0, "max": 30,
     "help": "Сколько дней после окончания доступа ещё действует скидка (и приходят сообщения «доступ закончился» и «последние 12 часов»).", "bots": "МП", "owner": True},

    {"key": "mp_pack_3", "group": G_MP, "label": "«Все сети»: скидка за 3 сети, %", "type": "int", "default": 10, "min": 0, "max": 90, "bots": "МП", "owner": True},
    {"key": "mp_pack_4", "group": G_MP, "label": "«Все сети»: скидка за 4 сети, %", "type": "int", "default": 20, "min": 0, "max": 90, "bots": "МП", "owner": True},
    {"key": "mp_pack_5", "group": G_MP, "label": "«Все сети»: скидка за 5 сетей, %", "type": "int", "default": 30, "min": 0, "max": 90, "bots": "МП", "owner": True},
    {"key": "mp_autopost_extra", "group": G_MP, "label": "Автопост: повторов после первого поста", "type": "int", "default": 2, "min": 0, "max": 10,
     "help": "2 = всего 3 выхода. 0 — автопостинг выключен (в боте и кабинете).", "bots": "МП"},
    {"key": "mp_autopost_intervals", "group": G_MP, "label": "Автопост: варианты интервала, часов", "type": "text", "default": "4, 6, 8, 12",
     "help": "Через запятую, от 1 до 24.", "bots": "МП"},
    {"key": "mp_sig_mk", "group": G_MP, "label": "Подпись под объявлением: Мужской Клуб", "type": "textarea", "default": '<b>Администрация сети не рекомендует вносить какую-либо предоплату. Если ВАС обманули или развели, сообщите в бота поддержки!</b>\n\n<i>Реклама. Не является публичной офертой.</i>',
     "help": "Можно <b>жирный</b>, <i>курсив</i>, <a href=\"…\">ссылку</a>. Если в HTML ошибка, бот возьмёт стандартную подпись и напишет об этом в «Диагностике». Пусто — по умолчанию.", "bots": "МП"},
    {"key": "mp_sig_parni", "group": G_MP, "label": "Подпись под объявлением: ПАРНИ 18+", "type": "textarea", "default": '<b>Администрация сети не рекомендует вносить какую-либо предоплату. Если ВАС обманули или развели, сообщите в бота поддержки!</b>\n\n<i>Реклама. Не является публичной офертой.</i>',
     "help": "Можно <b>жирный</b>, <i>курсив</i>, <a href=\"…\">ссылку</a>. Если в HTML ошибка, бот возьмёт стандартную подпись и напишет об этом в «Диагностике». Пусто — по умолчанию.", "bots": "МП"},
    {"key": "mp_sig_ns", "group": G_MP, "label": "Подпись под объявлением: НС", "type": "textarea", "default": '<b>Администрация сети не рекомендует вносить какую-либо предоплату. Если ВАС обманули или развели, сообщите в бота поддержки!</b>\n\n<i>Реклама. Не является публичной офертой.</i>',
     "help": "Можно <b>жирный</b>, <i>курсив</i>, <a href=\"…\">ссылку</a>. Если в HTML ошибка, бот возьмёт стандартную подпись и напишет об этом в «Диагностике». Пусто — по умолчанию.", "bots": "МП"},
    {"key": "mp_sig_rainbow", "group": G_MP, "label": "Подпись под объявлением: Радуга", "type": "textarea", "default": 'Администрация не несёт ответственности за объявления пользователей.\nНе вносите предоплату незнакомым лицам.\n\n<i>Реклама. Не является публичной офертой.</i>',
     "help": "Можно <b>жирный</b>, <i>курсив</i>, <a href=\"…\">ссылку</a>. Если в HTML ошибка, бот возьмёт стандартную подпись и напишет об этом в «Диагностике». Пусто — по умолчанию.", "bots": "МП"},
    {"key": "mp_sig_gayznak", "group": G_MP, "label": "Подпись под объявлением: Гей Знакомства", "type": "textarea", "default": 'Будьте осторожны при общении, не переводите деньги незнакомым людям.\n\n<i>Реклама. Не является публичной офертой.</i>',
     "help": "Можно <b>жирный</b>, <i>курсив</i>, <a href=\"…\">ссылку</a>. Если в HTML ошибка, бот возьмёт стандартную подпись и напишет об этом в «Диагностике». Пусто — по умолчанию.", "bots": "МП"},

    # --- автопилот (стелс) ---

    # --- ⚖️ прайс штрафов (ИИ поддержки Секретаря и кнопки админов) ---
    {"key": "fine_nark", "group": G_FINES, "label": 'Наркотики (красная зона), ⭐️', "type": "int", "default": 2000, "min": 1, "max": 100000, "help": 'Ставится ИИ поддержки, если в причине бана наркотики.', "bots": "Секретарь", "owner": True},
    {"key": "fine_minor", "group": G_FINES, "label": 'Несовершеннолетний / обман с возрастом, ⭐️', "type": "int", "default": 2000, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "fine_nark_react", "group": G_FINES, "label": 'Реакция на запрещёнку, ⭐️', "type": "int", "default": 1563, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "fine_minor_react", "group": G_FINES, "label": 'Реакция на детское, ⭐️', "type": "int", "default": 1563, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "fine_commerce", "group": G_FINES, "label": 'Коммерция (жёлтая зона), ⭐️', "type": "int", "default": 1563, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "fine_flood", "group": G_FINES, "label": 'Флуд / спам / копипаст, ⭐️', "type": "int", "default": 500, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "fine_bio", "group": G_FINES, "label": 'Ссылка в БИО, ⭐️', "type": "int", "default": 250, "min": 1, "max": 100000, "help": 'Можно вставить в текст шаблона как {fine_bio}.', "bots": "Секретарь", "owner": True},
    {"key": "fine_bot_block", "group": G_FINES, "label": 'Блок бота / сбежал с проверки, ⭐️', "type": "int", "default": 250, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "fine_manual", "group": G_FINES, "label": 'Ручной бан, если в досье нет суммы, ⭐️', "type": "int", "default": 1500, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "fine_quick", "group": G_FINES, "label": 'Кнопки быстрого штрафа у админов, ⭐️', "type": "text", "default": '250, 650, 1563', "regex": _LIST, "regex_hint": 'числа через запятую', "help": 'До 4 сумм через запятую — кнопки «💳 …⭐️» в топике поддержки.', "bots": "Секретарь", "owner": True},

    # --- 💸 кэшбэк ---
    {"key": "cb_min_phone", "group": G_CASH, "label": 'Минимум вывода на телефон, ₽', "type": "int", "default": 500, "min": 1, "max": 100000, "help": 'Это и общий минимум для вывода.', "bots": "Секретарь", "owner": True},
    {"key": "cb_min_crypto", "group": G_CASH, "label": 'Минимум вывода в крипте, ₽', "type": "int", "default": 1000, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "cb_min_card", "group": G_CASH, "label": 'Минимум вывода на карту, ₽', "type": "int", "default": 3500, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "cb_exchange_packs", "group": G_CASH, "label": 'Обменник: пакеты рубли:очки', "type": "text", "default": '50:50, 150:175, 250:300, 500:650', "regex": _PAIRS, "regex_hint": 'формат «рубли:очки, рубли:очки»', "help": 'Кнопки обменника в боте и в мини-приложении. Выгода в процентах считается сама.', "bots": "Секретарь", "owner": True},

    # --- 🎰 казино ---
    {"key": "casino_spin_price", "group": G_CASINO, "label": 'Рулетка: цена прокрутки, очков', "type": "int", "default": 50, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "casino_tax_pct", "group": G_CASINO, "label": 'Рулетка: сектор «Налоговая», % очков', "type": "int", "default": 30, "min": 0, "max": 100, "bots": "Секретарь", "owner": True},
    {"key": "casino_tax_outcast_pct", "group": G_CASINO, "label": '«Налоговая» для изгоев (карма ≤ −50), %', "type": "int", "default": 50, "min": 0, "max": 100, "bots": "Секретарь", "owner": True},
    {"key": "casino_points_wins", "group": G_CASINO, "label": 'Рулетка: сектор «Куш», варианты очков', "type": "text", "default": '100, 150, 250', "regex": _LIST, "regex_hint": 'числа через запятую', "bots": "Секретарь", "owner": True},
    {"key": "casino_cash_wins", "group": G_CASINO, "label": 'Рулетка: денежный купон, рубли:вес', "type": "text", "default": '100:75, 250:20, 500:5', "regex": _PAIRS, "regex_hint": 'формат «рубли:вес»', "help": 'Вес — насколько часто выпадает сумма. Деньги берутся из фонда казино; если фонда не хватает — даются очки ×2.', "bots": "Секретарь", "owner": True},
    {"key": "casino_jackpot_points", "group": G_CASINO, "label": 'Джекпот 777: очков к VIP-билету', "type": "int", "default": 300, "min": 0, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "casino_mini_points", "group": G_CASINO, "label": 'Мини-джекпот (фонд пуст): очков', "type": "int", "default": 1000, "min": 0, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "casino_mini_shards", "group": G_CASINO, "label": 'Мини-джекпот: осколков', "type": "int", "default": 5, "min": 0, "max": 1000, "bots": "Секретарь", "owner": True},
    {"key": "casino_premium_cost", "group": G_CASINO, "label": 'Фонд: цена Telegram Premium, ⭐️', "type": "int", "default": 1500, "min": 1, "max": 100000, "help": 'Столько звёзд уходит из фонда казино, когда кто-то выбивает Premium.', "bots": "Секретарь", "owner": True},
    {"key": "casino_cert_cost", "group": G_CASINO, "label": 'Фонд: цена сертификата, ⭐️', "type": "int", "default": 1250, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "casino_cert_rub", "group": G_CASINO, "label": 'Номинал сертификата, ₽', "type": "int", "default": 1000, "min": 1, "max": 100000, "help": 'Раньше в боте было 1000 ₽, а в мини-приложении 1500 ₽ — теперь одна цифра.', "bots": "Секретарь", "owner": True},
    {"key": "craft_shards", "group": G_CASINO, "label": 'Наковальня: осколков на сборку', "type": "int", "default": 50, "min": 1, "max": 10000, "bots": "Секретарь", "owner": True},
    {"key": "craft_odds", "group": G_CASINO, "label": 'Наковальня: шансы VIP, щит, Premium, %', "type": "text", "default": '60, 30, 10', "regex": _LIST, "regex_hint": 'три числа через запятую', "sum": 100, "help": 'В сумме 100.', "bots": "Секретарь", "owner": True},
    {"key": "chest_price", "group": G_CASINO, "label": 'Секретный сундук: цена, очков', "type": "int", "default": 1000, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "chest_odds", "group": G_CASINO, "label": 'Сундук: шансы кот, осколки, щит, джекпот, %', "type": "text", "default": '45, 35, 15, 5', "regex": _LIST, "regex_hint": 'четыре числа через запятую', "sum": 100, "help": 'В сумме 100. В мини-приложении карма сдвигает шанс кота (святым меньше, изгоям больше).', "bots": "Секретарь", "owner": True},
    {"key": "chest_jackpot_rub", "group": G_CASINO, "label": 'Сундук: джекпот, ₽ кэшбэка', "type": "int", "default": 500, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "bonus_min", "group": G_CASINO, "label": 'Бонус /bonus в боте: от, очков', "type": "int", "default": 15, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "bonus_max", "group": G_CASINO, "label": 'Бонус /bonus в боте: до, очков', "type": "int", "default": 50, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "bonus_shard_pct", "group": G_CASINO, "label": 'Бонус /bonus: шанс осколка, %', "type": "int", "default": 5, "min": 0, "max": 100, "bots": "Секретарь", "owner": True},
    {"key": "bonus_streak", "group": G_CASINO, "label": 'Бонус в мини-приложении по дням серии, очков', "type": "text", "default": '15, 25, 40, 50, 50, 50, 100', "regex": _LIST, "regex_hint": 'числа через запятую', "help": 'Награда за 1-й, 2-й… день подряд. За последний день — ещё осколок, и серия начинается заново.', "bots": "Секретарь", "owner": True},
    {"key": "donate_buttons", "group": G_CASINO, "label": 'Кнопки донатов, ⭐️', "type": "text", "default": '50, 150, 500', "regex": _LIST, "regex_hint": 'числа через запятую', "help": 'До 4 сумм. Кнопка «своя сумма» остаётся.', "bots": "Секретарь", "owner": True},

    # --- ⏰ автособытия ---
    {"key": "job_bomb", "group": G_JOBS, "label": 'Кибер-бомба в чаты', "type": "bool", "default": True, "help": 'Случайный дроп очков в чат сети.', "bots": "Секретарь"},
    {"key": "job_bomb_every_min", "group": G_JOBS, "label": 'Кибер-бомба: раз в, минут', "type": "int", "default": 120, "min": 10, "max": 10080, "bots": "Секретарь", "owner": False},
    {"key": "job_cat", "group": G_JOBS, "label": 'Набег соседского кота', "type": "bool", "default": True, "help": 'Ежедневный «налог» кота.', "bots": "Секретарь"},
    {"key": "job_cat_time", "group": G_JOBS, "label": 'Набег кота: время (МСК)', "type": "text", "default": '12:00', "regex": _TIME, "regex_hint": 'время ЧЧ:ММ', "bots": "Секретарь", "owner": False},
    {"key": "job_beetle", "group": G_JOBS, "label": 'Колорадский жук на фермах', "type": "bool", "default": True, "help": 'Жуки нападают на картофельные поля.', "bots": "Секретарь"},
    {"key": "job_beetle_every_min", "group": G_JOBS, "label": 'Жук: раз в, минут', "type": "int", "default": 30, "min": 5, "max": 1440, "bots": "Секретарь", "owner": False},
    {"key": "job_auction", "group": G_JOBS, "label": 'Авто-аукцион', "type": "bool", "default": True, "help": 'Автоматический лот на аукционе по расписанию (см. «день и время»).', "bots": "Секретарь"},
    {"key": "job_auction_when", "group": G_JOBS, "label": 'Авто-аукцион: день и время (МСК)', "type": "text", "default": 'пт 18:00', "regex": r'(пн|вт|ср|чт|пт|сб|вс)\s+' + _TIME + r'([\s,;]+(пн|вт|ср|чт|пт|сб|вс)\s+' + _TIME + r')*', "regex_hint": 'например «пт 18:00» или несколько слотов: «пн 12:00, ср 15:00, пт 18:00» (лот живёт 48 ч; пока прошлый не завершён, новый не выставится)', "bots": "Секретарь", "owner": False},
    {"key": "job_bonus_push", "group": G_JOBS, "label": 'Вечерний пуш о бонусах', "type": "bool", "default": True, "help": 'Напоминание в личку забрать ежедневный бонус.', "bots": "Секретарь"},
    {"key": "job_bonus_push_time", "group": G_JOBS, "label": 'Пуш о бонусах: время (МСК)', "type": "text", "default": '20:00', "regex": _TIME, "regex_hint": 'время ЧЧ:ММ', "bots": "Секретарь", "owner": False},
    {"key": "job_scout", "group": G_JOBS, "label": 'Разведчик праздничных конкурсов', "type": "bool", "default": True, "help": 'Ищет праздник через 10 дней и готовит фотоконкурс.', "bots": "Секретарь"},
    {"key": "job_scout_time", "group": G_JOBS, "label": 'Разведчик: время (МСК)', "type": "text", "default": '10:00', "regex": _TIME, "regex_hint": 'время ЧЧ:ММ', "bots": "Секретарь", "owner": False},
    {"key": "job_funnel", "group": G_JOBS, "label": 'Тизеры-воронка в чаты', "type": "bool", "default": True, "help": 'Реклама рулетки, наковальни, обменника и т.п. по кругу.', "bots": "Секретарь"},
    {"key": "job_funnel_every_h", "group": G_JOBS, "label": 'Тизеры: раз в, часов', "type": "int", "default": 6, "min": 1, "max": 168, "bots": "Секретарь", "owner": False},
    {"key": "job_farm_dm", "group": G_JOBS, "label": 'Уведомления фермы в личку', "type": "bool", "default": True, "help": '«Урожай созрел», «пора полить».', "bots": "Секретарь"},
    {"key": "job_collectors", "group": G_JOBS, "label": 'Коллекторы', "type": "bool", "default": True, "help": 'Напоминания и взыскание с должников по займам.', "bots": "Секретарь"},

    # --- 🏛 экономика: краны (откуда берутся очки) и стоки (куда сгорают) ---
    {"key": "lux_tax_on", "group": G_ECON, "label": '🏛 Налог на роскошь: включён', "type": "bool", "default": False,
     "help": 'Раз в сутки сгорает процент с больших копилок (и кошельков, если включено ниже). Очки не уходят в сейф — исчезают. Игроки получают уведомление в личку.', "bots": "Секретарь", "owner": True},
    {"key": "lux_tax_tiers", "group": G_ECON, "label": 'Налог на роскошь: ступени «порог:% в сутки»', "type": "text", "default": '30000:1, 100000:2, 150000:3',
     "regex": _PAIRS, "regex_hint": 'формат «порог:процент», например «30000:1, 100000:2»',
     "help": 'Как подоходный по ступеням: каждая ставка берётся только со своей части. «30000:1, 100000:2» — до 30 000 бесплатно, с части 30–100 тыс. 1 %, выше 100 тыс. 2 %. Пример: копилка 188 789 при значении по умолчанию платит 2 863 в сутки.', "bots": "Секретарь", "owner": True},
    {"key": "lux_tax_wallets", "group": G_ECON, "label": 'Налог на роскошь: и личные кошельки', "type": "bool", "default": True,
     "help": 'Те же ступени для кошельков (админов не трогает). Выключите — налог только с копилок.', "bots": "Секретарь", "owner": True},
    {"key": "lux_tax_time", "group": G_ECON, "label": 'Налог на роскошь: время (МСК)', "type": "text", "default": '04:00', "regex": _TIME, "regex_hint": 'время ЧЧ:ММ', "bots": "Секретарь", "owner": True},
    {"key": "lux_tax_notify", "group": G_ECON, "label": 'Налог на роскошь: писать в личку', "type": "bool", "default": True, "bots": "Секретарь", "owner": True},

    {"key": "potato_seed", "group": G_ECON, "label": '🥔 Поле: цена семян за клетку', "type": "int", "default": 60, "min": 1, "max": 100000,
     "help": 'Главный «кран» очков. Сейчас урожай в среднем 90 при цене 60 — гарантированные +30 с клетки за 8 ч.', "bots": "Секретарь", "owner": True},
    {"key": "potato_yield", "group": G_ECON, "label": '🥔 Поле: урожай «от, до», очков', "type": "text", "default": '70, 110', "regex": r"\d+\s*[,;]\s*\d+", "regex_hint": 'два числа через запятую, например «55, 95»',
     "help": 'Случайно в этих пределах с одного куста.', "bots": "Секретарь", "owner": True},
    {"key": "potato_grow_h", "group": G_ECON, "label": '🥔 Поле: созревание, часов', "type": "int", "default": 8, "min": 1, "max": 72, "bots": "Секретарь", "owner": True},
    {"key": "potato_dust", "group": G_ECON, "label": '🥔 Поле: Дуст (убрать жуков), очков', "type": "int", "default": 100, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "potato_spray", "group": G_ECON, "label": '🥔 Поле: обработка от жуков, очков', "type": "int", "default": 150, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "potato_spray_h", "group": G_ECON, "label": '🥔 Поле: обработка действует, часов', "type": "int", "default": 12, "min": 1, "max": 168, "bots": "Секретарь", "owner": True},

    {"key": "safe_blue_tick", "group": G_ECON, "label": '🔐 Сейф данных: прирост в минуту, очков', "type": "int", "default": 5, "min": 0, "max": 1000,
     "help": '5 в минуту = 7 200 новых очков в сутки из воздуха. 0 — сейф пополняется только налогами и комиссиями.', "bots": "Секретарь", "owner": True},
    {"key": "safe_blue_start", "group": G_ECON, "label": '🔐 Сейф данных: стартовый куш после взлома, очков', "type": "int", "default": 10000, "min": 0, "max": 1000000, "bots": "Секретарь", "owner": True},
    {"key": "safe_red_start", "group": G_ECON, "label": '🔐 Фин. сейф: стартовый куш после взлома, ₽', "type": "int", "default": 500, "min": 0, "max": 100000,
     "help": 'Это настоящие рубли кэшбэка.', "bots": "Секретарь", "owner": True},

    {"key": "hack_cost", "group": G_ECON, "label": '💻 Взлом игрока: цена попытки, очков', "type": "int", "default": 200, "min": 1, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "hack_chance", "group": G_ECON, "label": '💻 Взлом игрока: шанс, %', "type": "int", "default": 30, "min": 0, "max": 100,
     "help": 'Против «Крысы» +10 %. В Судную ночь — 80 % (не меняется).', "bots": "Секретарь", "owner": True},
    {"key": "hack_cooldown_min", "group": G_ECON, "label": '💻 Взлом игрока: перезарядка, минут', "type": "int", "default": 60, "min": 1, "max": 10080, "bots": "Секретарь", "owner": True},

    {"key": "wedding_price", "group": G_ECON, "label": '💍 Свадьба: госпошлина, очков', "type": "int", "default": 500, "min": 1, "max": 1000000, "bots": "Секретарь", "owner": True},
    {"key": "divorce_price", "group": G_ECON, "label": '💔 Развод: штраф, очков', "type": "int", "default": 1000, "min": 1, "max": 1000000, "bots": "Секретарь", "owner": True},
    {"key": "anniv_reward_pct", "group": G_ECON, "label": '💍 Годовщины: награда, % от таблицы', "type": "int", "default": 100, "min": 0, "max": 1000,
     "help": 'Очки в общак, щиты и осколки за годовщины. 50 — вдвое меньше, 0 — без наград.', "bots": "Секретарь", "owner": True},
    {"key": "karma_vote_cooldown_s", "group": G_KARMA, "label": '⭐ Карма: пауза между «+» одному человеку, сек', "type": "int", "default": 120, "min": 10, "max": 86400,
     "help": 'Сейчас 2 минуты: двое знакомых накручивают до 720 кармы в сутки. 3600 — раз в час.', "bots": "Секретарь", "owner": True},

    # --- 💸 кэшбэк: откуда берутся настоящие рубли ---
    {"key": "cb_month_cap", "group": G_CASH, "label": 'Лимит вывода на человека за 30 дней, ₽', "type": "int", "default": 0, "min": 0, "max": 1000000,
     "help": '0 — без лимита. Защита кассы: даже если все разом захотят вывести, за месяц уйдёт не больше этой суммы с человека.', "bots": "Секретарь", "owner": True},
    {"key": "money_tree_rub", "group": G_CASH, "label": 'Денежное дерево: кэшбэк за урожай «от, до», ₽', "type": "text", "default": '10, 30',
     "regex": r"\d+\s*[,;]\s*\d+", "regex_hint": 'два числа через запятую, «0, 0» — без рублей',
     "help": 'Дерево плодоносит каждые сутки бесконечно: это вечный кран НАСТОЯЩИХ рублей из очков. 16 деревьев = до 480 ₽ в сутки одному игроку.', "bots": "Секретарь", "owner": True},
    {"key": "agent_case_cash_rub", "group": G_CASH, "label": 'Кейс агента CPA: денежный приз, ₽', "type": "int", "default": 500, "min": 0, "max": 100000,
     "help": '0 — вместо рублей 1000 очков.', "bots": "Секретарь", "owner": True},
    {"key": "quest_comp_rub", "group": G_CASH, "label": 'Квест: компенсация «все статусы уже есть», ₽', "type": "int", "default": 500, "min": 0, "max": 100000,
     "help": '0 — вместо рублей 2500 очков.', "bots": "Секретарь", "owner": True},

    # --- 🏦 банковская ячейка ---
    {"key": "vault_on", "group": G_BANK, "label": 'Банковская ячейка: включена', "type": "bool", "default": True,
     "help": 'Игроки прячут очки от грабежа в Судную ночь за ежедневную абонентку (сгорает). В мини-приложении — «Рюкзак».', "bots": "Секретарь", "owner": True},
    {"key": "vault_tiers", "group": G_BANK, "label": 'Абонентка: ступени «порог:% в сутки»', "type": "text", "default": '0:0.5, 30000:1.5, 100000:2.5, 150000:3.5',
     "regex": r"\d+\s*:\s*\d+(\.\d+)?(\s*[,;]\s*\d+\s*:\s*\d+(\.\d+)?)*", "regex_hint": 'например «0:0.5, 30000:1.5» (дробные проценты можно)',
     "help": 'Каждая ставка — со своей части суммы. По умолчанию всегда на ~0,5 % дороже налога на роскошь, чтобы в ячейку не прятались от налога. Пример: 100 000 → 1 250 в сутки.', "bots": "Секретарь", "owner": True},
    {"key": "vault_fee_min", "group": G_BANK, "label": 'Абонентка: минимум, очков в сутки', "type": "int", "default": 50, "min": 0, "max": 100000, "bots": "Секретарь", "owner": True},
    {"key": "vault_points_protect_pct", "group": G_BANK, "label": 'Тариф «Очки»: защищено, %', "type": "int", "default": 70, "min": 0, "max": 100,
     "help": 'Остальное в Судную ночь могут украсть. Тариф «Кэшбэк» всегда защищает 100 %.', "bots": "Секретарь", "owner": True},
    {"key": "vault_rub_discount_pct", "group": G_BANK, "label": 'Тариф «Кэшбэк»: цена, % от очкового (в рублях)', "type": "int", "default": 50, "min": 1, "max": 500,
     "help": 'Абонентка в рублях = очковая абонентка, пересчитанная по курсу сети, × этот процент. 50 — вдвое выгоднее очков: стимул тратить кэшбэк, а не выводить.', "bots": "Секретарь", "owner": True},
    {"key": "vault_fresh_h", "group": G_BANK, "label": 'Деньги в пути: защита включается через, часов', "type": "int", "default": 12, "min": 0, "max": 168,
     "help": 'Чтобы не прятались в момент объявления Судной ночи.', "bots": "Секретарь", "owner": True},
    {"key": "vault_min_deposit", "group": G_BANK, "label": 'Минимальный вклад, очков', "type": "int", "default": 500, "min": 1, "max": 1000000, "bots": "Секретарь", "owner": True},

    # --- ⭐ карма ---
    {"key": "karma_minus_cooldown_h", "group": G_KARMA, "label": 'Минус одному и тому же: не чаще раза в, часов', "type": "int", "default": 6, "min": 1, "max": 168,
     "help": 'Защита от травли. Минусы ставят только не-новички (50+ сообщений или статус) и не Изгои.', "bots": "Секретарь", "owner": True},
    {"key": "karma_minus_daily_cap", "group": G_KARMA, "label": 'Максимум минусов одному человеку в сутки', "type": "int", "default": 20, "min": 1, "max": 1000,
     "help": 'Сколько бы людей ни минусовали, за сутки карма упадёт не больше чем на это число.', "bots": "Секретарь", "owner": True},
    {"key": "karma_regen_per_day", "group": G_KARMA, "label": 'Самовосстановление: +кармы в сутки', "type": "int", "default": 1, "min": 0, "max": 100,
     "help": 'Тем, кто в минусе, но вчера написал 10+ сообщений и не в муте. 0 — выключено.', "bots": "Секретарь", "owner": True},
    {"key": "karma_bonus_penalty", "group": G_KARMA, "label": 'Штраф к ежедневному бонусу при −10 / −25 / −50, %', "type": "text", "default": '10, 20, 30',
     "regex": _LIST, "regex_hint": 'три числа через запятую', "bots": "Секретарь", "owner": True},

    # --- 🔨 аукцион и прочие цены ---
    {"key": "auction_hours", "group": G_AUCT, "label": 'Торги длятся, часов', "type": "int", "default": 48, "min": 1, "max": 336, "bots": "Секретарь", "owner": True},
    {"key": "auction_start_bid", "group": G_AUCT, "label": 'Стартовая ставка, очков', "type": "int", "default": 1000, "min": 1, "max": 10000000, "bots": "Секретарь", "owner": True},
    {"key": "auction_step", "group": G_AUCT, "label": 'Минимальный шаг ставки, очков', "type": "int", "default": 100, "min": 1, "max": 1000000, "bots": "Секретарь", "owner": True},
    {"key": "auction_charges", "group": G_AUCT, "label": 'Разовые артефакты: зарядов за победу', "type": "int", "default": 1, "min": 1, "max": 20,
     "help": 'Перчатка, Разлучник, Рейд, Глас Бога, Гуантанамо, Мастер-Ключ, NPC. 3 — артефакт работает три раза.', "bots": "Секретарь", "owner": True},
    {"key": "auction_casino_owner_days", "group": G_AUCT, "label": '«Владелец Казино» действует, дней', "type": "int", "default": 3, "min": 1, "max": 90, "bots": "Секретарь", "owner": True},
    {"key": "auction_offshore_days", "group": G_AUCT, "label": '«Офшорный счёт» действует, дней', "type": "int", "default": 7, "min": 1, "max": 90, "bots": "Секретарь", "owner": True},
    {"key": "anarchy_price", "group": G_AUCT, "label": '🔥 Судная ночь (!анархия): цена, очков', "type": "int", "default": 10000, "min": 1, "max": 10000000, "bots": "Секретарь", "owner": True},
    {"key": "anarchy_minutes", "group": G_AUCT, "label": '🔥 Судная ночь: длится, минут', "type": "int", "default": 60, "min": 5, "max": 1440, "bots": "Секретарь", "owner": True},
    {"key": "adopt_price", "group": G_AUCT, "label": '👶 Усыновление: пошлина, очков', "type": "int", "default": 1000, "min": 1, "max": 1000000, "bots": "Секретарь", "owner": True},

    {"key": "stealth_enemy_ref", "group": G_STEALTH, "label": "Стелс: какую реф-ссылку подменять", "type": "text", "default": "ref_EQHH7XHV", "bots": "Скайнет", "owner": True},
    {"key": "stealth_boss_ref", "group": G_STEALTH, "label": "Стелс: на какую подменять", "type": "text", "default": "ref_2BBPF35H", "bots": "Скайнет", "owner": True},
    {"key": "stealth_exempt_ids", "group": G_STEALTH, "label": "Стелс: кому показывать оригинал (ID через запятую)", "type": "text", "default": "7235010425", "bots": "Скайнет", "owner": True},
]

BY_KEY = {e["key"]: e for e in SCHEMA}
GROUP_ORDER = [G_MONEY, G_FINES, G_CASH, G_CASINO, G_ECON, G_BANK, G_KARMA, G_AUCT, G_JOBS, G_SEC, G_VIP, G_BEYOND, G_MP, G_CPA, G_POSTER, G_MOD, G_AI, G_LINKS, G_STEALTH]
