"""
core/textvars.py — переменные в текстах, которые правятся в панели.

В тексте пишем {quarantine_hours} — бот подставит текущее значение из настроек.
Поменяли цифру в «Настройках» — все тексты подхватили её сами, переписывать ничего не нужно.
Неизвестные {слова} не трогаются (например, {user_link} подставляет сам обработчик).
"""
import re

from database import db

# ключ -> (подпись для панели, откуда брать)
VARS = {
    "quarantine_hours": "Карантин новорегов, ч",
    "strike_hours": "Мут за страйки, ч",
    "strikes": "Страйков до мута",
    "flood_hours": "Мут за флуд, ч",
    "fine_free": "Штраф для тега «Свободен», ⭐️",
    "fine_sponsor": "Взнос спонсора, ⭐️",
    "indulgence_price": "Индульгенция, ⭐️",
    "support_price": "Доступ к поддержке, ⭐️",
    "spam_fine": "Штраф за спам кнопками, ⭐️",
    "vip_price": "Цена VIP, ⭐️",
    "beyond_price": "Цена BEYOND, ⭐️",
    "rub_per_star": "Курс ₽ за ⭐️",
}

_RX = re.compile(r"\{(" + "|".join(VARS) + r")\}")


def values():
    lim = db['settings'].find_one({"_id": "moderation_limits"}) or {}
    price = db['settings'].find_one({"_id": "skynet_pricing"}) or {}
    try:
        from core.cfg import cfg
        c = lambda k, d: cfg(k)
    except Exception:
        c = lambda k, d: d
    rate = c("rub_per_star", 2.0)
    return {
        "quarantine_hours": int(lim.get("quaran_hours", 120)),
        "strike_hours": int(lim.get("strike_hours", 72)),
        "strikes": c("repost_strikes", 3),
        "flood_hours": int(lim.get("flood_norm_hours", 6)),
        "fine_free": c("fine_tag_free", 650),
        "fine_sponsor": c("fine_tag_sponsor", 750),
        "indulgence_price": c("indulgence_price", 2000),
        "support_price": c("support_price", 50),
        "spam_fine": c("spam_fine", 111),
        "vip_price": int(price.get("vip_price", 250)),
        "beyond_price": int(price.get("beyond_price", 250)),
        "rub_per_star": (int(rate) if float(rate).is_integer() else rate),
    }


def fill(text, vals=None):
    """Подставляет значения вместо {переменных}. Ошибка в базе не ломает отправку текста."""
    if not text or "{" not in text:
        return text
    try:
        v = vals or values()
        return _RX.sub(lambda m: str(v.get(m.group(1), m.group(0))), text)
    except Exception:
        return text


def migrate_texts_v1():
    """Разово: цифры в уже сохранённых текстах → переменные (копия старых текстов — в settings.texts_backup_vars_v1)."""
    try:
        if db['settings'].find_one({"_id": "migration_textvars_v1"}):
            return
        db['settings'].insert_one({"_id": "migration_textvars_v1", "ts": __import__("time").time()})
    except Exception:
        return  # другой воркер уже делает
    backup = {}
    t = db['settings'].find_one({"_id": "skynet_texts"}) or {}
    q = t.get("quarantine_warn")
    if q:
        new = re.sub(r"(карантин\w*\s+)\d+\s*час\w*", r"\1{quarantine_hours} ч.", q, flags=re.I)
        if new != q:
            backup["quarantine_warn"] = q
            db['settings'].update_one({"_id": "skynet_texts"}, {"$set": {"quarantine_warn": new}})
    sp = db['bot_templates'].find_one({"_id": "tpl_sponsor"})
    if sp and sp.get("text"):
        fee = str(values()["fine_sponsor"])
        new = re.sub(r"\b" + fee + r"\s*⭐", "{fine_sponsor}⭐", sp["text"])
        if new != sp["text"]:
            backup["tpl_sponsor"] = sp["text"]
            db['bot_templates'].update_one({"_id": "tpl_sponsor"}, {"$set": {"text": new}})
    if backup:
        db['settings'].update_one({"_id": "texts_backup_vars_v1"}, {"$set": backup}, upsert=True)
