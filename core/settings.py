# core/settings.py или skynet_settings.py в корне
from database import db

class SkynetSettings:
    # Дефолтные значения — всё включено на старте
    _default = {
        "skynet_enabled": True,           # Главный выключатель всего Скайнета
        "red_zone": True,                 # Наркота, жесткие нарушения
        "yellow_commerce": True,          # Коммерция, папики, спонсоры
        "twin_radar": True,               # Радар твинков
        "autoban_on_block": True,         # Автобан за блокировку бота
        "vip_sniper": True,               # Снайпер по верификации (таймер)
        "bio_hardcheck": True,            # Жесткая проверка БИО на таможне
        "auto_corpse_removal": True,      # Автоочистка трупов при рассылках
        "proxy_system": True,             # Черный Ящик (Анонимные чаты)
        "referral_system": True,          # Рефералка для VIP
        "parni_autounmute": True,         # Локальная амнистия в Парнях
        "radar_logging": True,            # Запись логов в Живой Радар
        "quarantine_active": True,        # Карантин новорегов (48ч)
        "may_1_active": True,             # Операция 1 Мая (параметры)
    }

    @staticmethod
    def get():
        settings = db['settings'].find_one({"_id": "skynet"})
        if not settings:
            db['settings'].insert_one({"_id": "skynet", **SkynetSettings._default})
            return SkynetSettings._default.copy()
        # Склеиваем дефолты и то, что в базе (на случай если добавим новые тумблеры)
        return {**SkynetSettings._default, **settings}

    @staticmethod
    def set(key: str, value: bool):
        db['settings'].update_one(
            {"_id": "skynet"},
            {"$set": {key: value}},
            upsert=True
        )
        return True