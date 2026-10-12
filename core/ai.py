"""
core/ai.py — единая точка обращения к ИИ (Groq + запасной провайдер Cerebras).

Модель llama-3.3-70b-versatile Groq отключил 16.08.2026 (рекомендованная замена — openai/gpt-oss-120b,
её же использует Секретарь). Модель меняется в панели (Настройки → ИИ) без правки кода.
gpt-oss — «думающая» модель: тратит часть токенов на рассуждение, поэтому лимит токенов с запасом.

Цепочка при лимите (429): основная модель на Groq → та же модель на Cerebras (если задан CEREBRAS_API_KEY,
это та же «умная» модель у другого провайдера) → Google Gemini (если задан GEMINI_API_KEY, бесплатно без карты,
модель умнее нашей) → запасные модели Groq.
Запасные модели слабее, поэтому их «виновен» не исполняется автоматически: ai_verdict возвращает None,
и админам приходят кнопки (см. last_was_weak()).
"""
import os
import re
import threading
import requests

from config import GROQ_API_KEYS

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_KEYS = [k for k in (os.getenv("CEREBRAS_API_KEY"), os.getenv("CEREBRAS_API_KEY_2")) if k]
# Нативный API Google: новые ключи AI Studio (начинаются на «AQ.») передаются заголовком x-goog-api-key
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_SAFETY = [{"category": c, "threshold": "BLOCK_NONE"} for c in (
    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")]


def _gemini_call(model, key, prompt, max_tokens, temperature, timeout):
    """-> (status, text|None, finish, response). Фильтры Google ослаблены: модератору нужно читать «плохие» тексты."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "safetySettings": _GEMINI_SAFETY,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens + 1500,
                                 "thinkingConfig": {"thinkingLevel": "low"}}}
    url = GEMINI_URL.format(model=model)
    r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=timeout)
    if r.status_code == 401:  # на случай старого формата ключа
        r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=body, timeout=timeout)
    if r.status_code != 200:
        return r.status_code, None, None, r
    cand = (r.json().get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    return 200, text, cand.get("finishReason"), r
GEMINI_KEYS = [k for k in (os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_API_KEY_2")) if k]
KEY_ENV = {"Groq": "GROQ_API_KEY", "Cerebras": "CEREBRAS_API_KEY", "Gemini": "GEMINI_API_KEY"}


def gemini_model():
    try:
        from core.cfg import cfg
        return cfg("gemini_model") or "gemini-3.8-flash"
    except Exception:
        return "gemini-3.8-flash"

OLD_FALLBACK_DEFAULT = "openai/gpt-oss-20b, llama-3.1-8b-instant"
NEW_FALLBACK_DEFAULT = "qwen/qwen3.8-27b, openai/gpt-oss-20b"

_last = threading.local()  # какая модель ответила последней в этом потоке


def last_was_weak():
    """True — последний вердикт в этом потоке вынесла запасная (слабая) модель и он отправлен людям."""
    return bool(getattr(_last, "weak_ban", False))


def _bare(model):
    return str(model or "").split("/")[-1].lower()


def groq_model():
    """Переменная окружения GROQ_MODEL главнее; иначе — модель из панели «Настройки → ИИ»."""
    env = os.getenv("GROQ_MODEL")
    if env:
        return env
    try:
        from core.cfg import cfg
        return cfg("groq_model") or "openai/gpt-oss-120b"
    except Exception:
        return "openai/gpt-oss-120b"


# Модель на «перерыве» после HTTP 429: (ключ, модель) -> до какого времени не трогать.
# Лимиты считаются на модель, поэтому при 429 на основной модели переходим дальше по цепочке,
# а в «Диагностику» пишем один раз за перерыв, а не на каждое сообщение.
_COOLDOWN = {}


def groq_models(low_priority=False):
    """Основная модель + запасные из панели. Для второстепенного (прожарки) — сначала запасные,
    чтобы не тратить лимит основной модели, которая решает баны."""
    main = groq_model()
    try:
        from core.cfg import cfg
        raw = str(cfg("groq_fallback_models") or "")
    except Exception:
        raw = NEW_FALLBACK_DEFAULT
    if raw.replace(" ", "") == OLD_FALLBACK_DEFAULT.replace(" ", ""):
        raw = NEW_FALLBACK_DEFAULT  # старый список по умолчанию: llama-3.1-8b слабая и ушла с бесплатного тарифа
    extra = [m.strip() for m in raw.split(",") if m.strip()]
    models = [main] + [m for m in extra if m != main]
    if low_priority and len(models) > 1:
        models = models[1:] + models[:1]
    return models


def _chain(low_priority=False):
    """-> [(провайдер, url, модель, ключи, сильная?)] в порядке опроса.
    Для прожарок (low_priority) Cerebras и Gemini не трогаем — их лимиты берегём для проверок."""
    main = groq_model()
    out = []
    for m in groq_models(low_priority):
        out.append(("Groq", GROQ_URL, m, GROQ_API_KEYS, _bare(m) == _bare(main)))
        if _bare(m) == _bare(main) and not low_priority:
            if CEREBRAS_KEYS and _bare(main) in ("gpt-oss-120b", "qwen-3.8-27b"):
                out.append(("Cerebras", CEREBRAS_URL, _bare(main), CEREBRAS_KEYS, True))
            if GEMINI_KEYS:
                out.append(("Gemini", GEMINI_URL, gemini_model(), GEMINI_KEYS, True))
    return out


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
    m = re.search(r'retryDelay"?\s*:\s*"?([\d.]+)s', r.text or "")  # формат Google
    if m:
        return min(3600.0, float(m.group(1)) + 1)
    if "per day" in (r.text or "").lower() or "perday" in (r.text or "").lower():
        return 3600.0  # дневной лимит — не долбим час
    return 60.0


def groq_chat(prompt, max_tokens=400, temperature=0.0, timeout=12, where="ИИ", low_priority=False):
    """-> текст ответа или None, если ни один ключ и ни одна модель не ответили (ошибки — в «Диагностику»).
    После вызова _last.strong показывает, ответила ли основная («умная») модель."""
    import time as _t
    from core.diag import log_error
    _last.strong = False
    if not GROQ_API_KEYS and not CEREBRAS_KEYS and not GEMINI_KEYS:
        return None
    now = _t.time()
    for prov, url, model, keys, strong in _chain(low_priority):
        body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature, "max_tokens": max_tokens}
        if "gpt-oss" in model:
            # gpt-oss сначала «думает», и эти мысли съедают лимит токенов. Думать мало, мысли не присылать.
            body.update({"reasoning_effort": "low", "max_tokens": max_tokens + 1200})
            if prov == "Groq":
                body["include_reasoning"] = False
        elif "qwen" in model:
            body["max_tokens"] = max_tokens + 1500  # qwen может «подумать» в <think>…</think>, вырезаем ниже
        for i, key in enumerate(keys, 1):
            base = KEY_ENV[prov]
            kname = f"{base}{'' if i == 1 else '_' + str(i)}"
            if _COOLDOWN.get((key, model), 0) > now:
                continue
            try:
                if prov == "Gemini":
                    # Gemini 3 всегда «думает» (выключить нельзя) — думать мало, запас токенов внутри
                    code, gtext, finish, r = _gemini_call(model, key, prompt, max_tokens, temperature, max(timeout, 25))
                    if code == 200:
                        if gtext:
                            _last.strong = strong
                            _last.model = f"{prov}:{model}"
                            return gtext
                        log_error(prov, f"{where}: пустой ответ ({model}, {finish or 'без причины'}, ключ {kname})")
                        continue
                else:
                    r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                      json=body, timeout=timeout)
                if r.status_code == 200:
                    choice = r.json()["choices"][0]
                    text = (choice["message"].get("content") or "")
                    text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
                    if text:
                        _last.strong = strong
                        _last.model = f"{prov}:{model}"
                        return text
                    why = "модель не успела ответить, кончился лимит токенов" if choice.get("finish_reason") == "length" else "пустой ответ"
                    log_error(prov, f"{where}: {why} ({model}, ключ {kname})")
                    continue
                if r.status_code == 429:
                    wait = _retry_after(r)
                    _COOLDOWN[(key, model)] = now + wait
                    log_error(prov, f"лимит {model} ({kname}) исчерпан, пауза {int(wait)} сек — работаю дальше по цепочке")
                    continue
                if r.status_code in (400, 404) and "model" in (r.text or "").lower():
                    _COOLDOWN[(key, model)] = now + 3600  # модель отключена/не существует — не долбим час
                log_error(prov, f"{where}: HTTP {r.status_code}, {model}, ключ {kname}: {r.text[:160]}")
            except Exception as e:
                log_error(prov, f"{where}: {model}, ключ {kname}: {e}")
    return None


def ai_verdict(text, zone):
    """True — нарушение, False — безопасно, None — решает человек (ИИ недоступен или «виновен» сказала запасная модель)."""
    _last.weak_ban = False
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
    _last.weak_ban = False
    ans = groq_chat(prompts[zone].format(t=str(text)[:1500]), max_tokens=400, where=f"проверка зоны {zone}")
    if ans is None:
        return None
    ans = ans.upper()
    verdict = True if "BAN" in ans else (False if "SKIP" in ans else None)
    strong = getattr(_last, "strong", False)
    if verdict is True and not strong:
        # Запасная модель слабее основной: её «виновен» не исполняем сами — решают люди по кнопкам.
        _last.weak_ban = True
        return None
    if verdict is not None and strong and db is not None:
        try:
            db['ai_cache'].update_one({"_id": key}, {"$set": {"v": verdict, "ts": _t.time()}}, upsert=True)
        except Exception:
            pass
    return verdict
