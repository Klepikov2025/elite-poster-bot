import re
import pytz
from config import VIP_PRICE_STARS

def net_key_to_name(key):
    return {
        "mk": "Мужской Клуб", "parni": "ПАРНИ 18+", "ns": "НС",
        "rainbow": "Радуга", "gayznak": "Гей Знакомства"
    }.get(key, key)

def get_referral_bonus(invites_count):
    if invites_count <= 10:   return 0.10, int(VIP_PRICE_STARS * 0.10)
    elif invites_count <= 30: return 0.13, int(VIP_PRICE_STARS * 0.13)
    elif invites_count <= 50: return 0.15, int(VIP_PRICE_STARS * 0.15)
    elif invites_count <= 100:return 0.17, int(VIP_PRICE_STARS * 0.17)
    else:                     return 0.20, int(VIP_PRICE_STARS * 0.20)

def escape_md(text):
    escape_chars = r'\_*[]()~`>#+=|{}'
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

def clean_user_text(text):
    return re.sub(r'(?<=\d)\*(?=\d)', '×', text)

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