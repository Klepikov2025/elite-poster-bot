"""
core/diag.py — прозрачность для веб-панели (вкладка «🩺 Диагностика»).
  log_error  — «что сломалось»: ошибки задач, ответы Groq, спорные/упавшие оплаты.
  log_admin  — журнал действий админов веб-панели (кто, что, когда).
"""
import re
import time
from database import db

# Токен бота попадает в текст ошибок requests (…/bot123:AAG…/approveChatJoinRequest). В журнал — без него.
_TOKEN_RE = re.compile(r"(bot)?\d{6,12}:[A-Za-z0-9_-]{30,}")


def mask_secrets(text):
    return _TOKEN_RE.sub(lambda m: (m.group(1) or "") + "<токен скрыт>", str(text))


def log_error(kind, text, uid=None, level="error"):
    try:
        db['skynet_errors'].insert_one({"ts": time.time(), "kind": kind, "text": mask_secrets(text)[:500], "uid": uid, "level": level})
    except Exception:
        pass


def log_admin(login, text):
    try:
        db['admin_audit'].insert_one({"ts": time.time(), "login": login, "text": str(text)[:500]})
    except Exception:
        pass
