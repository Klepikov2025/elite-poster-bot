"""
Разбор анкет знакомств «возраст/рост/вес/размер» с учётом кривых вариантов.

Роли определяются не по месту, а по смыслу:
  • подписи: «21 год», «возраст 21», «рост 180», «70 кг», «18 см», «размер 18» — точно;
  • рост — трёхзначное 140–215; вес — сразу после роста, 40–150;
  • размер — 10–26 в КОНЦЕ анкеты после веса (классика «180/70/19» — это не возраст);
  • возраст — первым числом, либо 27+ там, где размер невозможен,
    либо «спрятан» между ростом и весом («180/19/70») — тогда это подозрение, а не факт.

parse_anketa(text) -> (age, confident) или None
  confident=True  — возраст однозначен, можно решать без ИИ;
  confident=False — возможно возраст (спрятан/двусмысленно): решает ИИ с подсказкой, при сбое ИИ — человек.
"""
import re

_NUM = re.compile(r'(?<![\d.,:])(\d{2,3})(?![\d]|[.,]\d|\s*\+)')  # «18+» — пометка, не возраст
_UNIT_AFTER = re.compile(r'\s*(лет|года?|годик\w*|г\.?\s?о\.?|y\.?o\.?|yo|см|cm|кг|kg)(?![а-яa-z])')
_LABEL_BEFORE = re.compile(r'(возраст\w*|рост\w*|вес\w*|размер\w*|разм\.?|р-р|член\w*|хуй|писюн\w*|лет)\s*[:\-–—=]?\s*$')
_GAP_OK = re.compile(r'[\s/\\|,;:\-–—+х×x*]*')
_SEEKING = re.compile(r'\b(ищу|ищем|нужен|нужна|нужны|нравятся|предпочитаю|интересуют|от|до|старше|младше|не\s+старше|не\s+младше)\s*[^\d\n]{0,15}$')

_ROLE_BY_UNIT = {"лет": "age", "год": "age", "года": "age", "yo": "age", "кг": "weight", "kg": "weight"}


def _unit_role(unit, val):
    u = unit.replace('.', '').replace(' ', '')
    if u.startswith(('лет', 'год', 'го', 'yo')):
        return "age"
    if u in ('кг', 'kg'):
        return "weight"
    if u in ('см', 'cm'):
        return "height" if val >= 130 else "size"
    return None


def _label_role(label):
    l = label
    if l.startswith('возраст') or l == 'лет':
        return "age"
    if l.startswith('рост'):
        return "height"
    if l.startswith('вес'):
        return "weight"
    return "size"  # размер, р-р, член…


def _runs(text):
    """Группы чисел, идущих подряд через разделители/подписи — это и есть анкета."""
    t = text.lower()
    nums = []
    for m in _NUM.finditer(t):
        val = int(m.group(1))
        role, end = None, m.end()
        u = _UNIT_AFTER.match(t, m.end())
        if u:
            role, end = _unit_role(u.group(1), val), u.end()
        lab = _LABEL_BEFORE.search(t[max(0, m.start() - 14):m.start()])
        lab_start = m.start() - (len(lab.group(0)) if lab else 0)
        if lab and role is None:
            role = _label_role(lab.group(1))
        nums.append({"val": val, "role": role, "start": m.start(), "lab_start": lab_start, "end": end})

    runs, cur = [], []
    for n in nums:
        if cur:
            gap = t[cur[-1]["end"]:n["lab_start"]]
            if len(gap) <= 6 and _GAP_OK.fullmatch(gap):
                cur.append(n)
                continue
            runs.append(cur)
        cur = [n]
    if cur:
        runs.append(cur)
    return t, runs


def _classify(run):
    """-> (age, confident) для одной группы чисел или None."""
    roles = [n["role"] for n in run]
    vals = [n["val"] for n in run]

    # 1) Явная подпись возраста — однозначно
    for n in run:
        if n["role"] == "age" and 10 <= n["val"] <= 99:
            return n["val"], True
    if len(run) < 2:
        return None

    # 2) Рост: подписанный или первое трёхзначное 140–215
    h = next((i for i, r in enumerate(roles) if r == "height"), None)
    if h is None:
        h = next((i for i, v in enumerate(vals) if roles[i] is None and 140 <= v <= 215), None)
        if h is not None:
            roles[h] = "height"

    if h is not None:
        # Вес: подписанный или сразу после роста (40–150)
        w = next((i for i, r in enumerate(roles) if r == "weight"), None)
        if w is None and h + 1 < len(run) and roles[h + 1] is None and 40 <= vals[h + 1] <= 150:
            w = h + 1
            roles[w] = "weight"

        # До роста: первое число — возраст по классике «возраст/рост/…»
        before = [i for i in range(h) if roles[i] is None and 10 <= vals[i] <= 99]
        if len(before) == 1:
            i = before[0]
            return vals[i], (i == 0)
        if len(before) > 1:
            # «70/21/180»: до роста два числа — 40+ похоже на вес, возраст — меньшее (неуверенно)
            young = [i for i in before if vals[i] < 40]
            i = young[0] if young else before[0]
            return vals[i], False

        # Сразу после роста, но это не вес — возраст спрятан на 2-е место («180/19/70»)
        if h + 1 < len(run) and roles[h + 1] is None and 10 <= vals[h + 1] <= 39:
            return vals[h + 1], False

        # После веса: ≤26 — размер (классика «180/70/19»), 27+ — это уже возраст
        tail = [i for i in range(h + 1, len(run)) if roles[i] is None]
        for i in tail:
            if 27 <= vals[i] <= 99:
                return vals[i], (w is not None)
        # возраст мог быть спрятан в конец, но без подписи 10–26 там почти всегда размер
        return None

    # 3) Роста нет: «21/58/18», «21 70»
    free = [i for i, r in enumerate(roles) if r is None]
    if free and free[0] == 0 and 14 <= vals[0] <= 79:
        has_weight = any(40 <= vals[i] <= 150 for i in free[1:]) or "weight" in roles
        return vals[0], (has_weight and len(run) >= 3)
    return None


def parse_anketa(text):
    """Возраст автора из анкеты: (age, confident) или None.
    Группа после «ищу/от/до/старше…» описывает того, кого ищут, — пропускаем."""
    t, runs = _runs(str(text or ""))
    best = None
    for run in runs:
        if _SEEKING.search(t[max(0, run[0]["lab_start"] - 30):run[0]["lab_start"]]):
            continue
        res = _classify(run)
        if res is None:
            continue
        if res[1]:
            return res
        best = best or res
    return best


ANKETA_HINT = ("Анкеты в чатах знакомств пишут числами: «возраст/рост/вес/размер» (например «21/169/58/18»), "
               "но порядок бывает кривым, а возраст иногда прячут на 2-е или 3-е место. Рост — 140–215, вес обычно "
               "идёт после роста, а число 10–26 в конце анкеты чаще всего размер члена в см, а не возраст. ")
