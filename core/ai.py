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


def groq_chat(prompt, max_tokens=400, temperature=0.0, timeout=12, where="ИИ"):
    """-> текст ответа или None, если ни один ключ не сработал (ошибки пишутся в «Диагностику»)."""
    from core.diag import log_error
    if not GROQ_API_KEYS:
        return None
    model = groq_model()
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature, "max_tokens": max_tokens}
    if "gpt-oss" in model:
        # gpt-oss сначала «думает», и эти мысли съедают лимит токенов: при 400 токенах ответ
        # приходил пустым («пустой ответ» в Диагностике). Думать мало, мысли не присылать, запас токенов.
        body.update({"reasoning_effort": "low", "include_reasoning": False, "max_tokens": max_tokens + 1200})
    for i, key in enumerate(GROQ_API_KEYS, 1):
        kname = f"GROQ_API_KEY{'' if i == 1 else '_' + str(i)}"
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
            log_error("Groq", f"{where}: HTTP {r.status_code}, ключ {kname}: {r.text[:160]}")
        except Exception as e:
            log_error("Groq", f"{where}: ключ {kname}: {e}")
    return None


# Анкета «возраст/рост/вес[/размер]»: «21/169/58», «21 169 58», «21-169-58». Первое число — возраст АВТОРА.
_ANKETA = re.compile(r'(?<![\d/])(\d{2})\s*[/\\|,\- ]\s*(1[4-9]\d|2[0-2]\d)\s*[/\\|,\- ]\s*\d{2,3}(?![\d])')
_SEEKING = re.compile(r'\b(ищу|ищем|нужен|нужна|нравятся|предпочитаю|интересуют|от|до|старше|младше)\b')

def anketa_age(text):
    """Возраст автора из анкеты или None. Если перед анкетой «ищу/от/до…» — это описание того, кого ищут."""
    t = str(text or "").lower()
    for m in _ANKETA.finditer(t):
        if _SEEKING.search(t[max(0, m.start() - 25):m.start()]):
            continue
        return int(m.group(1))
    return None

_ANKETA_HINT = ("В чатах знакомств анкету пишут числами через дробь: «возраст/рост/вес/размер», например «21/169/58» — "
                "это автору 21 год, рост 169, вес 58. ПЕРВОЕ число — возраст автора. ")

def ai_verdict(text, zone):
    """True — нарушение, False — безопасно, None — ИИ недоступен (решает человек)."""
    # Однозначная анкета решается без ИИ: модель не знала формат и оправдывала «21/169/58»
    age = anketa_age(text)
    if age is not None:
        if zone == "orange" and 18 <= age <= 21:
            return True
        if zone == "black" and age < 18:
            return True
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
    ans = groq_chat(prompts[zone].format(t=str(text)[:1500]), max_tokens=400, where=f"проверка зоны {zone}")
    if ans is None:
        return None
    ans = ans.upper()
    if "BAN" in ans:
        return True
    if "SKIP" in ans:
        return False
    return None
