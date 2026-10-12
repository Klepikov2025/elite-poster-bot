"""
Вкладка «📊 Статистика»: динамика сети по дням для живых графиков.
GET /glaz/api/stats/trends?days=7|30|90 — одним запросом всё, что рисует вкладка.
GET /glaz/api/stats/people — «Кто в базе», воронки и оценки поддержки (кэш 2 минуты: 85 тыс. записей).
Выручку видит только владелец.
"""
import time
from datetime import datetime, timedelta

import pytz
from flask import jsonify, request, session

from database import db, users_collection, banned_collection, archive_collection

MSK = pytz.timezone("Europe/Moscow")
EKB = pytz.timezone("Asia/Yekaterinburg")  # так пишется архив наказаний


def _day_keys(days):
    today = datetime.now(MSK).date()
    return [today - timedelta(days=i) for i in range(days - 1, -1, -1)]


def register_stats_routes(app):
    from web_auth import is_owner
    register_people_routes(app)

    @app.route('/glaz/api/stats/trends')
    def api_stats_trends():
        if not session.get('logged_in'):
            return jsonify({"error": "Unauthorized"}), 401
        try:
            days = int(request.args.get("days", 30))
        except ValueError:
            days = 30
        days = days if days in (7, 30, 90) else 30
        span = days * 2  # текущий + предыдущий период — для «±% к прошлому»
        keys = _day_keys(span)
        start_dt = MSK.localize(datetime.combine(keys[0], datetime.min.time()))
        start_ts = start_dt.timestamp()
        idx = {k: i for i, k in enumerate(keys)}

        def bucket_ts(ts):
            try:
                return idx.get(datetime.fromtimestamp(float(ts), MSK).date())
            except Exception:
                return None

        def series_from_ts(values):
            out = [0] * span
            for v in values:
                i = bucket_ts(v)
                if i is not None:
                    out[i] += 1
            return out

        # 1. Новые участники
        new_users = series_from_ts(u.get("first_seen") for u in users_collection.find(
            {"first_seen": {"$gte": start_ts}}, {"first_seen": 1}))

        # 2. Опубликованные анкеты (поле time — datetime в UTC, либо timestamp)
        posts = [0] * span
        for p in db['posts'].find({"time": {"$gte": start_dt.astimezone(pytz.utc).replace(tzinfo=None)}}, {"time": 1}):
            t = p.get("time")
            if isinstance(t, datetime):
                t = pytz.utc.localize(t).timestamp() if t.tzinfo is None else t.timestamp()
            i = bucket_ts(t)
            if i is not None:
                posts[i] += 1

        # 3. Тикеты поддержки
        tickets = series_from_ts(t.get("timestamp") for t in db['support_tickets'].find(
            {"timestamp": {"$gte": start_ts}}, {"timestamp": 1}))

        # 4. Наказания из архива: даты строками «дд.мм.гггг чч:мм» по Екатеринбургу
        date_strs = {}
        for k in keys:
            date_strs[k.strftime("%d.%m.%Y")] = k
        bans, mutes = [0] * span, [0] * span
        heat = [[0] * 24 for _ in range(7)]  # [день недели][час] по Москве
        pattern = "^(" + "|".join(s.replace(".", r"\.") for s in date_strs) + ")"
        pipeline = [
            {"$match": {"history.date": {"$regex": pattern}}},
            {"$unwind": "$history"},
            {"$match": {"history.date": {"$regex": pattern}}},
            {"$project": {"_id": 0, "d": "$history.date", "a": "$history.action"}},
        ]
        try:
            rows = list(archive_collection.aggregate(pipeline))
        except Exception:
            rows = []
        for r in rows:
            d, a = str(r.get("d") or ""), str(r.get("a") or "").upper()
            if "РАЗ" in a:  # разбан / размут — не наказание
                continue
            try:
                local = EKB.localize(datetime.strptime(d[:16], "%d.%m.%Y %H:%M")).astimezone(MSK)
            except ValueError:
                continue
            i = idx.get(local.date())
            if i is None:
                continue
            if "БАН" in a:
                bans[i] += 1
            elif "МУТ" in a:
                mutes[i] += 1
            else:
                continue
            if i >= span - days:
                heat[local.weekday()][local.hour] += 1

        # 5. Выручка в звёздах — только владельцу
        revenue = None
        if is_owner():
            from web.finance import _rev_kind
            revenue = [0] * span
            for r in db['daily_revenue'].find({"date": {"$in": list(date_strs)}}, {"type": 1, "amount": 1, "currency": 1, "date": 1}):
                if _rev_kind(r) != "stars":
                    continue
                k = date_strs.get(r.get("date"))
                if k is not None:
                    revenue[idx[k]] += int(r.get("amount") or 0)

        def pack(arr):
            cur, prev = arr[span - days:], arr[:span - days]
            return {"series": cur, "total": sum(cur), "prev": sum(prev)}

        total = users_collection.count_documents({})
        vips = users_collection.count_documents({"is_vip": True})
        queers = users_collection.count_documents({"is_queer": True, "is_vip": {"$ne": True}})
        verified = users_collection.count_documents({"is_verified": True, "is_vip": {"$ne": True}, "is_queer": {"$ne": True}})
        cities = list(users_collection.aggregate([
            {"$match": {"main_city": {"$exists": True, "$nin": ["Не привязан", "", None]}}},
            {"$group": {"_id": "$main_city", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}, {"$limit": 10}]))

        data = {
            "days": days,
            "labels": [k.strftime("%d.%m") for k in keys[span - days:]],
            "new_users": pack(new_users),
            "posts": pack(posts),
            "tickets": pack(tickets),
            "bans": pack(bans),
            "mutes": pack(mutes),
            "heat": heat,
            "composition": {"total": total, "vip": vips, "beyond": queers, "verified": verified,
                            "regular": max(0, total - vips - queers - verified),
                            "banned": banned_collection.count_documents({})},
            "cities": [{"name": c["_id"], "count": c["count"]} for c in cities],
            "generated": int(time.time()),
        }
        if revenue is not None:
            data["revenue"] = pack(revenue)
        return jsonify(data)


# ===================== «Кто в базе» + воронки + оценки =====================
_PEOPLE_CACHE = {"ts": 0, "data": None}

VIP_STAGES = {"deciding": "выбирает тариф", "awaiting_video": "должен прислать кружок",
              "admin_review": "кружок у админов на проверке", "awaiting_payment": "ждём оплату"}
BEYOND_STEPS = {"start": "начал анкету", "waiting_proof": "должен прислать подтверждение",
                "admin_review": "у админов на проверке", "waiting_promo": "вводит промокод",
                "waiting_payment": "ждём оплату", "paying": "оплачивает"}


def _age_days(ts, now):
    try:
        if isinstance(ts, datetime):
            ts = (MSK.localize(ts) if ts.tzinfo is None else ts).timestamp()
        return (now - float(ts)) / 86400
    except Exception:
        return None


def _funnel_stages(coll, field, names, now):
    stages, stale = {}, 0
    for f in db[coll].find({}, {field: 1, "timestamp": 1}):
        k = f.get(field) or "?"
        stages[k] = stages.get(k, 0) + 1
        age = _age_days(f.get("timestamp"), now)
        if age is not None and age > 7:
            stale += 1
    rows = [{"key": k, "label": names.get(k, k), "count": v} for k, v in stages.items()]
    order = list(names)
    rows.sort(key=lambda r: order.index(r["key"]) if r["key"] in order else 99)
    return {"total": sum(stages.values()), "stages": rows, "stale": stale}


def build_people():
    now = time.time()
    month_ago = now - 30 * 86400
    banned_ids = {b["_id"] for b in banned_collection.find({}, {"_id": 1})}
    groups = {k: 0 for k in ("deleted", "vip", "beyond", "verified", "banned", "new", "city", "bot_only", "legacy")}
    f = {"intent_vip": 0, "intent_vip_bought": 0, "intent_ads": 0, "intent_support": 0}
    user_ids_ads = set()
    total = 0
    proj = {"is_deleted": 1, "is_vip": 1, "is_queer": 1, "is_verified": 1, "first_seen": 1, "main_city": 1,
            "intent_vip": 1, "intent_post_ads": 1, "intent_support": 1}
    support_uids = set()
    banned_in_base = 0
    for u in users_collection.find({}, proj):
        total += 1
        if u["_id"] in banned_ids:
            banned_in_base += 1
        city = u.get("main_city")
        has_city = bool(city) and city != "Не привязан"
        fs = u.get("first_seen")
        if u.get("is_deleted"):
            g = "deleted"
        elif u.get("is_vip"):
            g = "vip"
        elif u.get("is_queer"):
            g = "beyond"
        elif u.get("is_verified"):
            g = "verified"
        elif u["_id"] in banned_ids:
            g = "banned"
        elif fs and (_age_days(fs, now) or 999) <= 30:
            g = "new"
        elif has_city:
            g = "city"
        elif fs:
            g = "bot_only"
        else:
            g = "legacy"
        groups[g] += 1
        if u.get("intent_vip"):
            f["intent_vip"] += 1
            if u.get("is_vip"):
                f["intent_vip_bought"] += 1
        if u.get("intent_post_ads"):
            f["intent_ads"] += 1
            user_ids_ads.add(u["_id"])
        if u.get("intent_support"):
            support_uids.add(u["_id"])

    # Объявления: кто реально опубликовал (хоть раз за всё время, что хранятся посты) и за 30 дней
    since = datetime.utcfromtimestamp(month_ago)
    posters_all = set(db['posts'].distinct("user_id"))
    posters_30 = set(db['posts'].distinct("user_id", {"time": {"$gte": since}}))
    clicked_and_posted = len(user_ids_ads & posters_all)

    # Поддержка: оба бота — тикеты Скайнета + диалоги Секретаря (оценённые и нет)
    support_uids |= set(x for x in db['support_tickets'].distinct("uid") if x)
    support_uids |= set(x for x in db['ticket_ratings'].distinct("uid") if x)
    support_uids |= set(x for x in db['paid_users'].distinct("uid", {"thread_id": {"$exists": True, "$ne": None}}) if x)

    # Оценки: только реально оценённые, стабильный порядок (по числу оценок)
    ratings, unrated = [], 0
    rated_total, rated_sum = 0, 0
    for r in db['ticket_ratings'].aggregate([
            {"$group": {"_id": "$admin_id", "avg": {"$avg": "$rating"}, "n": {"$sum": {"$cond": [{"$gt": ["$rating", 0]}, 1, 0]}},
                        "all": {"$sum": 1}, "sum": {"$sum": {"$ifNull": ["$rating", 0]}}}}]):
        if not r.get("n"):
            unrated += r.get("all", 0)
            continue
        unrated += r.get("all", 0) - r["n"]
        rated_total += r["n"]
        rated_sum += r.get("sum") or 0
        ratings.append({"name": str(r["_id"] or "Неизвестный"), "avg": round(r.get("avg") or 0, 2), "count": r["n"]})
    ratings.sort(key=lambda x: (-x["count"], x["name"]))
    since_7 = now - 7 * 86400
    bad_week = db['ticket_ratings'].count_documents({"rating": {"$lte": 2, "$gt": 0}, "timestamp": {"$gte": since_7}})

    return {
        "total": total,
        "groups": groups,
        "banned_list": len(banned_ids),
        "banned_in_base": banned_in_base,
        "banned_not_in_base": len(banned_ids) - banned_in_base,
        "funnels": {
            "vip": {"clicked": f["intent_vip"], "bought": f["intent_vip_bought"], "now": _funnel_stages("vip_funnel", "stage", VIP_STAGES, now),
                    "vips_total": groups["vip"]},
            "beyond": {"now": _funnel_stages("beyond_funnel", "step", BEYOND_STEPS, now),
                       "approved": users_collection.count_documents({"is_queer": True})},
            "ads": {"clicked": f["intent_ads"], "clicked_and_posted": clicked_and_posted,
                    "posters_all": len(posters_all), "posters_30": len(posters_30)},
            "support": {"people": len(support_uids), "rated": rated_total, "unrated": unrated,
                        "avg": round(rated_sum / rated_total, 2) if rated_total else None, "bad_week": bad_week},
        },
        "ratings": ratings,
        "generated": int(now),
    }


def register_people_routes(app):
    @app.route('/glaz/api/stats/people')
    def api_stats_people():
        if not session.get('logged_in'):
            return jsonify({"error": "Unauthorized"}), 401
        if not _PEOPLE_CACHE["data"] or time.time() - _PEOPLE_CACHE["ts"] > 120:
            _PEOPLE_CACHE["data"] = build_people()
            _PEOPLE_CACHE["ts"] = time.time()
        return jsonify(_PEOPLE_CACHE["data"])
