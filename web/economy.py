"""
web/economy.py — «Экономика очков» (только владелец): сколько очков всего в игре, где они лежат,
откуда берутся и куда уходят.

Остаток считается по всем хранилищам (кошельки, семейные копилки, сейфы, ставки аукциона), а не только
по кошелькам, как ТОП-30 Секретаря. Поток — по журналу points_ledger Секретаря (каждое изменение очков
у игрока, хранится 180 дней). Перемещения между игроками/копилками/сейфами — не выпуск и не сжигание,
поэтому показаны отдельно. Раз в сутки сохраняется снимок — по нему видно, растёт ли масса.
"""
import math
import time
from datetime import datetime, timedelta, timezone

from flask import jsonify, request, session

from database import db

MSK = timezone(timedelta(hours=3))

# причина в журнале = «файл.функция» Секретаря
LABELS = {
    "main.api_potato_action": "🥔 Картофельное поле", "main.reset_wave_if_empty": "🥔 Картофельное поле (сброс волны)",
    "main.api_farm_action": "🌱 Ферма (грядки)", "main.api_spin_roulette": "🎰 Рулетка (приложение)",
    "casino.process_spin_result": "🎰 Рулетка (бот)", "casino.handle_casino_spin": "🎰 Рулетка: ставка (бот)",
    "casino.handle_spin_for_cashback": "🎰 Рулетка за кэшбэк", "main.api_open_chest": "📦 Сундук (приложение)",
    "security.handle_buy_chest": "📦 Сундук (бот)", "main.api_claim_bonus": "🎁 Ежедневный бонус (приложение)",
    "casino.handle_daily_bonus": "🎁 Ежедневный бонус (бот)", "main.api_craft": "⚒ Наковальня (приложение)",
    "security.handle_craft_beyond": "⚒ Наковальня (бот)", "main.api_exchange": "💱 Обмен рублей на очки (приложение)",
    "security.handle_do_exchange": "💱 Обмен рублей на очки (бот)", "main.api_loan": "🏦 Займы",
    "main.pay_debt_chat": "🏦 Погашение займов", "main.api_open_agent_case": "💼 Кейс агента CPA",
    "main.api_open_task_case": "📋 Кейс за задания", "main.handle_quest_resolution": "📋 Квесты",
    "main.api_place_bid": "🔨 Аукцион", "main.buy_ticket": "🎟 Билеты розыгрышей", "main.pay_casino_owner": "👑 Владелец казино (10%)",
    "main.russian_roulette": "🔫 Русская рулетка", "main.handle_defuse": "💣 Кибер-бомба", "casino.handle_claim_airdrop": "🪂 Аирдроп в чате",
    "payments.successful_payment": "⭐️ Покупка очков за звёзды", "payments.handle_checkout": "⭐️ Оплата очками",
    "start_menu.handle_support_payment": "🆘 Оплата поддержки очками", "security.handle_reward_purchase": "🛒 Магазин наград",
    "security.handle_trade_in": "♻️ Сдача призов", "security.process_gift_code": "🎫 Подарочные коды",
    "security.handle_admin_report_decision": "🚨 Награда за донос", "admin.handle_give_cmd": "🛠 Выдача админом (/give)",
    "main.api_admin_user_action": "🛠 Выдача админом (приложение)", "admin.handle_rating": "⭐ Оценка поддержки",
    "contests.handle_contest_moderation": "🏆 Фотоконкурсы", "main._auto_grant_achievements": "🏅 Достижения",
    "main.handle_marriage_response": "💍 Свадьбы", "main.handle_adopt_response": "👶 Усыновление", "main.divorce": "💔 Развод",
    "main.trigger_anarchy": "🔥 Судная ночь", "main.resolve_uid": "❔ resolve_uid",
    # перемещения
    "main.family_piggy_bank": "🐷 Копилки: положили / сняли", "main.run_away_child": "🐷 Побег ребёнка с копилкой",
    "main.p2p_transfer": "🤝 Переводы игрокам", "main.handle_user_airdrop": "👜 Мешки: бросили", "main.handle_claim_userdrop": "👜 Мешки: подобрали",
    "scheduler.refund_expired_user_airdrops": "👜 Мешки: возврат", "main.api_buy_market": "🛍 Чёрный рынок",
    "main.handle_duel_response": "⚔️ Дуэли", "main.join_squid_game": "🦑 Кальмар: взнос", "main.start_squid_game": "🦑 Кальмар",
    "main.run_squid_game": "🦑 Кальмар: выигрыш", "main.join_heist": "🥷 Ограбления", "main.raider_takeover": "🏴 Рейдерский захват",
    "main.api_crack_safe": "🔐 Взлом сейфа", "main.master_key_safe": "🔐 Отмычка сейфа", "scheduler.stray_cat_tax": "🐈 Кот-налог (в сейф)",
    "main.handle_court_funding": "⚖️ Суды", "main.bribe_court": "⚖️ Суды: взятка", "main.public_court": "⚖️ Суды",
    "scheduler.refund_expired_courts": "⚖️ Суды: возврат",
    "hack._steal_family_bank": "💻 Взлом копилки (Судная ночь)", "hack.run_hack": "💻 Взлом",
    "scheduler.luxury_tax": "🏛 Налог на роскошь (кошельки)", "scheduler.luxury_tax_bank": "🏛 Налог на роскошь (копилки)",
}
# Эти операции перекладывают уже существующие очки (игрок↔игрок, игрок↔копилка, игрок↔сейф, ставки)
TRANSFER = {
    "main.family_piggy_bank", "main.run_away_child", "main.p2p_transfer", "main.handle_user_airdrop",
    "main.handle_claim_userdrop", "scheduler.refund_expired_user_airdrops", "main.api_buy_market",
    "main.handle_duel_response", "main.join_squid_game", "main.start_squid_game", "main.run_squid_game",
    "main.join_heist", "main.raider_takeover", "main.api_crack_safe", "main.master_key_safe",
    "scheduler.stray_cat_tax", "main.handle_court_funding", "main.bribe_court", "main.public_court",
    "scheduler.refund_expired_courts", "main.divorce",
    "hack._steal_family_bank",   # очки из чужой копилки в кошелёк хакера — не выпуск
}


def _label(r):
    return LABELS.get(r, r or "неизвестно")


def _names(uids):
    uids = [u for u in uids if u]
    out = {}
    if not uids:
        return out
    for u in db['users'].find({"_id": {"$in": uids}}, {"first_name": 1, "username": 1}):
        un = str(u.get("username") or "").lstrip("@")   # в базе username бывает уже с «@»
        out[u["_id"]] = ((u.get("first_name") or "") + (f" @{un}" if un else "")).strip()
    for u in uids:
        if not out.get(u):
            c = db['chat_stats'].find_one({"uid": u}, {"name": 1}) or {}
            out[u] = c.get("name") or "Аноним"
    return out


def _sum(coll, match, field):
    r = list(db[coll].aggregate([{"$match": match}, {"$group": {"_id": None, "s": {"$sum": f"${field}"}, "n": {"$sum": 1}}}]))
    return (int(r[0]["s"]), int(r[0]["n"])) if r else (0, 0)


def stock():
    from config import ADMIN_CHAT_IDS, OWNER_ID
    staff = list(set(list(ADMIN_CHAT_IDS) + [OWNER_ID]))
    wallets, holders = _sum('paid_users', {"bounty_points": {"$gt": 0}, "uid": {"$nin": staff}}, "bounty_points")
    staff_w, _ = _sum('paid_users', {"bounty_points": {"$gt": 0}, "uid": {"$in": staff}}, "bounty_points")
    banks, banks_n = _sum('family_banks', {"balance": {"$gt": 0}}, "balance")
    safes = []
    safe_pts = 0
    for s in db['safes_state'].find({}, {"balance": 1}):
        bal = int(s.get("balance") or 0)
        is_pts = "red" not in str(s["_id"])
        safes.append({"id": str(s["_id"]), "balance": bal, "points": is_pts})
        if is_pts:
            safe_pts += bal
    auction, auction_n = _sum('auction_lots', {"status": "active", "leader_uid": {"$ne": None}}, "current_bid")
    debt, debt_n = _sum('paid_users', {"debt": {"$gt": 0}}, "debt")
    total = wallets + banks + safe_pts + auction
    return {"wallets": wallets, "holders": holders, "staff_wallets": staff_w, "banks": banks, "banks_n": banks_n,
            "safes": safes, "safe_pts": safe_pts, "auction": auction, "auction_n": auction_n,
            "debt": debt, "debt_n": debt_n, "total": total, "staff": staff}


def concentration(st):
    """Кто держит массу: кошельки и копилки вместе, как отдельные «владельцы»"""
    top_w = list(db['paid_users'].find({"bounty_points": {"$gt": 0}, "uid": {"$nin": st["staff"]}},
                                       {"uid": 1, "bounty_points": 1}).sort("bounty_points", -1).limit(60))
    top_b = list(db['family_banks'].find({"balance": {"$gt": 0}}, {"balance": 1}).sort("balance", -1).limit(60))
    ents = [("w", w["uid"], int(w["bounty_points"])) for w in top_w] + [("b", b["_id"], int(b["balance"])) for b in top_b]
    ents.sort(key=lambda e: -e[2])
    owners = st["holders"] + st["banks_n"]
    share = lambda k: round(100 * sum(e[2] for e in ents[:k]) / st["total"], 1) if st["total"] else 0
    k1 = max(1, math.ceil(owners * 0.01))
    # имена
    uids = [e[1] for e in ents[:30] if e[0] == "w"]
    for e in ents[:30]:
        if e[0] == "b":
            uids += [int(x) for x in str(e[1]).split("_")[1:] if x.lstrip("-").isdigit()]
    nm = _names(uids)
    rows = []
    for kind, key, val in ents[:30]:
        if kind == "w":
            rows.append({"kind": "Кошелёк", "who": nm.get(key, "Аноним"), "id": str(key), "value": val})
        else:
            ids = [int(x) for x in str(key).split("_")[1:] if x.lstrip("-").isdigit()]
            rows.append({"kind": "Копилка семьи", "who": " + ".join(nm.get(i, "Аноним") for i in ids), "id": ", ".join(map(str, ids)), "value": val})
    return {"top10": share(10), "top1pct": share(min(k1, len(ents))), "top1pct_n": k1, "owners": owners, "rows": rows}


def flows(days):
    since = time.time() - days * 86400
    rows = list(db['points_ledger'].aggregate([
        {"$match": {"field": "bounty_points", "ts": {"$gte": since}, "delta": {"$exists": True}}},
        {"$group": {"_id": {"r": "$reason", "pos": {"$gt": ["$delta", 0]}}, "s": {"$sum": "$delta"}, "n": {"$sum": 1}}},
    ], allowDiskUse=True))
    by = {}
    for r in rows:
        k = r["_id"]["r"] or "unknown"
        e = by.setdefault(k, {"reason": k, "label": _label(k), "plus": 0, "minus": 0, "n": 0, "transfer": k in TRANSFER})
        e["plus" if r["_id"]["pos"] else "minus"] += int(r["s"])
        e["n"] += int(r["n"])
    items = list(by.values())
    for e in items:
        e["net"] = e["plus"] + e["minus"]
    faucets = sorted([e for e in items if not e["transfer"] and e["net"] > 0], key=lambda e: -e["net"])
    sinks = sorted([e for e in items if not e["transfer"] and e["net"] < 0], key=lambda e: e["net"])
    moves = sorted([e for e in items if e["transfer"]], key=lambda e: -(e["plus"] - e["minus"]))
    minted = sum(e["net"] for e in faucets)
    burned = sum(e["net"] for e in sinks)
    # по дням (МСК), без перемещений
    daily = list(db['points_ledger'].aggregate([
        {"$match": {"field": "bounty_points", "ts": {"$gte": since}, "delta": {"$exists": True}, "reason": {"$nin": list(TRANSFER)}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$dt", "timezone": "+03:00"}},
                    "plus": {"$sum": {"$cond": [{"$gt": ["$delta", 0]}, "$delta", 0]}},
                    "minus": {"$sum": {"$cond": [{"$lt": ["$delta", 0]}, "$delta", 0]}}}},
        {"$sort": {"_id": 1}},
    ], allowDiskUse=True))
    return {"days": days, "minted": minted, "burned": burned, "net": minted + burned,
            "faucets": faucets[:15], "sinks": sinks[:15], "moves": moves[:15],
            "daily": [{"d": d["_id"], "plus": int(d["plus"]), "minus": int(d["minus"])} for d in daily]}


def snapshot(st):
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    db['econ_snapshots'].update_one({"_id": today}, {"$set": {
        "total": st["total"], "wallets": st["wallets"], "banks": st["banks"], "safes": st["safe_pts"],
        "auction": st["auction"], "debt": st["debt"], "ts": time.time()}}, upsert=True)
    return [{"d": s["_id"], "total": s.get("total", 0), "wallets": s.get("wallets", 0), "banks": s.get("banks", 0)}
            for s in db['econ_snapshots'].find().sort("_id", -1).limit(90)][::-1]


def register_economy_routes(app):
    @app.route('/glaz/api/economy')
    def api_economy():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        try:
            days = max(1, min(180, int(request.args.get("days", 7))))
        except ValueError:
            days = 7
        try:
            from core.cfg import cfg
            pps, rps = float(cfg("points_per_star")), float(cfg("rub_per_star"))
        except Exception:
            pps, rps = 5.0, 2.0
        st = stock()
        out = {"stock": {k: v for k, v in st.items() if k != "staff"}, "rate": {"points_per_star": pps, "rub_per_star": rps}}
        out["concentration"] = concentration(st)
        out["flows"] = flows(days)
        out["history"] = snapshot(st)
        return jsonify(out)
