"""
core/ai.py — единая точка обращения к Groq.

Модель llama-3.3-70b-versatile Groq отключил 16.08.2026 (рекомендованная замена — openai/gpt-oss-120b,
её же использует Секретарь). Модель меняется переменной GROQ_MODEL без правки кода.
gpt-oss — «думающая» модель: тратит часть токенов на рассуждение, поэтому лимит токенов с запасом.
"""
import os
import re
import requests

from config import GROQ_API_KEYS

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def groq_model():
    """Переменная окружения GROQ_MODEL главнее; иначе — модель из панели «🎛 Управление»."""
    env = os.getenv("GROQ_MODEL")
    if env:
        return env
    try:
        from core.cfg import cfg
        return cfg("groq_model") or "openai/gpt-oss-120b"
    except Exception:
        return "openai/gpt-oss-120b"


# Модель на «перерыве» после HTTP 429: (ключ, модель) -> до какого времени не трогать.
# Лимиты Groq считаются на модель, поэтому при 429 на основной модели переходим на запасные —
# у каждой свой отдельный лимит, а в «Диагностику» пишем один раз за перерыв, а не на каждое сообщение.
_COOLDOWN = {}


def groq_models(low_priority=False):
    """Основная модель + запасные из панели. Для второстепенного (прожарки) — сначала запасные,
    чтобы не тратить лимит основной модели, которая решает баны."""
    main = groq_model()
    try:
        from core.cfg import cfg
        extra = [m.strip() for m in str(cfg("groq_fallback_models") or "").split(",") if m.strip()]
    except Exception:
        extra = ["openai/gpt-oss-20b", "llama-3.1-8b-instant"]
    models = [main] + [m for m in extra if m != main]
    if low_priority and len(models) > 1:
        models = models[1:] + models[:1]
    return models


def _retry_after(r):
    try:
        h = r.headers.get("retry-after")
        if h:
            return min(3600.0, float(h))
    except Exception:
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", r.text or "")
    if m:
        return min(3600.0, int(m.group(1) or 0) * 60 + float(m.group(2)))
    return 60.0


def groq_chat(prompt, max_tokens=400, temperature=0.0, timeout=12, where="ИИ", low_priority=False):
    """-> текст ответа или None, если ни один ключ и ни одна модель не ответили (ошибки — в «Диагностику»)."""
    import time as _t
    from core.diag import log_error
    if not GROQ_API_KEYS:
        return None
    now = _t.time()
    for model in groq_models(low_priority):
        body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature, "max_tokens": max_tokens}
        if "gpt-oss" in model:
            # gpt-oss сначала «думает», и эти мысли съедают лимит токенов. Думать мало, мысли не присылать.
            body.update({"reasoning_effort": "low", "include_reasoning": False, "max_tokens": max_tokens + 1200})
        for i, key in enumerate(GROQ_API_KEYS, 1):
            kname = f"GROQ_API_KEY{'' if i == 1 else '_' + str(i)}"
            if _COOLDOWN.get((key, model), 0) > now:
                continue
            try:
                r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                  json=body, timeout=timeout)
                if r.status_code == 200:
                    choice = r.json()["choices"][0]
                    text = (choice["message"].get("content") or "").strip()
                    if text:
                        return text
                    why = "модель не успела ответить, кончился лимит токенов" if choice.get("finish_reason") == "length" else "пустой ответ"
                    log_error("Groq", f"{where}: {why} ({model}, ключ {kname})")
                    continue
                if r.status_code == 429:
                    wait = _retry_after(r)
                    _COOLDOWN[(key, model)] = now + wait
                    log_error("Groq", f"лимит {model} ({kname}) исчерпан, пауза {int(wait)} сек — работаю на запасной модели")
                    continue
                if r.status_code in (400, 404) and "model" in (r.text or "").lower():
                    _COOLDOWN[(key, model)] = now + 3600  # модель отключена/не существует — не долбим час
                log_error("Groq", f"{where}: HTTP {r.status_code}, {model}, ключ {kname}: {r.text[:160]}")
            except Exception as e:
                log_error("Groq", f"{where}: {model}, ключ {kname}: {e}")
    return None


def ai_verdict(text, zone):
    """True — нарушение, False — безопасно, None — ИИ недоступен (решает человек)."""
    # Анкета разбирается по ролям (core/anketa.py): однозначный возраст решается без ИИ —
    # модель не знала формат и оправдывала «21/169/58».
    from core.anketa import parse_anketa, ANKETA_HINT
    a = parse_anketa(text)
    if a and a[1]:
        if zone == "orange" and 18 <= a[0] <= 21:
            return True
        if zone == "black" and a[0] < 18:
            return True
    hint = ANKETA_HINT
    if a and not a[1]:
        hint += f"Внимание: в анкете возможно спрятан возраст автора — {a[0]}; оцени по контексту, возраст это или размер/вес. "
    _ANKETA_HINT = hint
    prompts = {
        "black": ("Ты модератор. " + _ANKETA_HINT + "Сообщение: \"{t}\"\n1. Автор СЕЙЧАС младше 18 лет?\n2. Ищет интим с несовершеннолетними?\n"
                  "Жалобы на других, прошлое («в 14 лет я был…») и размеры — НЕ нарушение. Ответь СТРОГО одним словом: BAN или SKIP."),
        "orange": ("Ты модератор. " + _ANKETA_HINT + "Сообщение: \"{t}\"\nСообщает ли автор (прямо, анкетой или «мне 20»), что ему СЕЙЧАС от 18 до 21 года включительно?\n"
                   "Если он ищет кого-то («ищу 20 летнего», «от 18»), говорит о размерах («20 см») или о прошлом — это НЕ нарушение. "
                   "Ответь СТРОГО одним словом: BAN или SKIP."),
        "yellow": ("Ты строгий модератор. Сообщение из чата: \"{t}\"\nИщет или предлагает ли автор интим за деньги, материальную помощь (МП), "
                   "подарки за встречи, спонсорство или платные услуги эскорта? Подарки на праздники, бытовые ситуации, работа или массаж "
                   "без денег и цен — безопасно. Ответь СТРОГО одним словом: BAN или SKIP."),
    }
    if zone not in prompts or not text:
        return True
    # Кэш: одинаковый текст (копипаст-анкеты) не гоняем через ИИ повторно — экономим лимит Groq
    import hashlib, time as _t
    key = f"{zone}:{hashlib.sha1(str(text).strip().lower().encode('utf-8')).hexdigest()}"
    try:
        from database import db
        hit = db['ai_cache'].find_one({"_id": key})
        if hit and _t.time() - hit.get("ts", 0) < 7 * 86400:
            return hit["v"]
    except Exception:
        db = None
    ans = groq_chat(prompts[zone].format(t=str(text)[:1500]), max_tokens=400, where=f"проверка зоны {zone}")
    if ans is None:
        return None
    ans = ans.upper()
    verdict = True if "BAN" in ans else (False if "SKIP" in ans else None)
    if verdict is not None and db is not None:
        try:
            db['ai_cache'].update_one({"_id": key}, {"$set": {"v": verdict, "ts": _t.time()}}, upsert=True)
        except Exception:
            pass
    return verdict
