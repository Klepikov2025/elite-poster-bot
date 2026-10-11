"""
Вкладка «📊 Статистика»: динамика сети по дням для живых графиков.
GET /glaz/api/stats/trends?days=7|30|90 — одним запросом всё, что рисует вкладка.
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
