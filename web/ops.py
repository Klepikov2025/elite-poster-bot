"""
Вкладки «📡 Радар и списки», «💥 Репрессии», «🕵️ Чёрный ящик» (2.0, 12.10.2026).

- Радар: события с типом (наказания, деньги, статусы, связь, безопасность, система), фильтр, поиск, «показать ещё».
- Списки: VIP / BEYOND / ЧС с именами, поиском и честным CSV.
- Репрессии: предпросмотр (сколько ID, кто уже в ЧС, кто под защитой статуса, админов не трогаем),
  фоновое задание с прогрессом, кнопкой «Остановить» и историей.
- Чёрный ящик: список переписок с именами, последним сообщением и поиском.
"""
import re
import threading
import time
from datetime import datetime

import pytz
from flask import jsonify, request, session

from database import db, users_collection, banned_collection, proxy_sessions

EKB = pytz.timezone("Asia/Yekaterinburg")

# Тип события радара — по значку в начале текста
KINDS = [
    ("punish", "Наказания", ("💥", "🤐", "🔨", "⚡", "💀", "🔇", "🚫 ОТКЛОНЕНА")),
    ("amnesty", "Амнистии и защита", ("🕊", "🥷", "🛡", "🔊", "💎 ИММУНИТЕТ")),
    ("money", "Деньги", ("💰", "💸", "💎", "🧩", "🎫", "🗑")),
    ("status", "Статусы и теги", ("👑", "🏳", "❌ СНЯТ", "⚠️ СНЯТ", "🎖", "📍", "🧹 СНЯТ")),
    ("comms", "Связь", ("📩", "✅", "🚀", "⏰", "🤖", "👁", "🧹", "⛔", "⏳", "✂", "🎯", "🔎")),
    ("security", "Безопасность", ("🔐", "🔑", "⚠️", "🚨")),
    ("system", "Настройки", ("⚙", "🎛", "📝", "🗺", "🧠", "📜")),
]
_LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\s*(?:\[([^\]]{1,40})\]\s*)?(.*)$", re.S)


def _kind(text):
    for key, _, marks in KINDS:
        if text.startswith(marks):
            return key
    return "other"


def _parse(doc):
    raw = str(doc.get("text", ""))
    m = _LINE.match(raw)
    who, body = (m.group(2), m.group(3)) if m else (None, raw)
    return {"ts": doc.get("ts"), "who": who, "text": body, "kind": _kind(body.lstrip())}


def _names(uids):
    out = {}
    if not uids:
        return out
    for u in users_collection.find({"_id": {"$in": list(uids)}}, {"first_name": 1, "username": 1}):
        nm = u.get("first_name") or (("@" + str(u["username"]).lstrip("@")) if u.get("username") else None)
        if nm:
            out[u["_id"]] = nm
    return out


def register_ops_routes(app, bot, add_radar_log, ban_user_everywhere, mute_user_everywhere,
                        unban_user_everywhere, unmute_user_everywhere, protected_ids):

    def _auth():
        return bool(session.get('logged_in'))

    # ---------------- РАДАР ----------------
    @app.route('/glaz/api/radar2')
    def api_radar2():
        if not _auth(): return jsonify({"error": "Unauthorized"}), 401
        try:
            limit = max(20, min(500, int(request.args.get("limit", 150))))
        except ValueError:
            limit = 150
        q = (request.args.get("q") or "").strip()
        kind = request.args.get("kind") or ""
        match = {}
        if request.args.get("before"):
            try:
                match["ts"] = {"$lt": float(request.args["before"])}
            except ValueError:
                pass
        if q:
            match["text"] = {"$regex": re.escape(q), "$options": "i"}
        out = []
        # тип определяется по тексту, поэтому при фильтре читаем с запасом
        cur = db['radar_logs'].find(match).sort("ts", -1).limit(limit * (6 if kind else 1))
        for d in cur:
            p = _parse(d)
            if kind and p["kind"] != kind:
                continue
            out.append(p)
            if len(out) >= limit:
                break
        day_ago = time.time() - 86400
        counts = {}
        for d in db['radar_logs'].find({"ts": {"$gte": day_ago}}, {"text": 1}).limit(5000):
            k = _parse(d)["kind"]
            counts[k] = counts.get(k, 0) + 1
        return jsonify({"items": out, "kinds": [{"key": k, "label": lbl} for k, lbl, _ in KINDS] + [{"key": "other", "label": "Прочее"}],
                        "counts_24h": counts})

    # ---------------- СПИСКИ ----------------
    @app.route('/glaz/api/lists')
    def api_lists():
        if not _auth(): return jsonify({"error": "Unauthorized"}), 401
        t = request.args.get("type")
        q = (request.args.get("q") or "").strip().lstrip("@")
        rows = []
        if t in ("vip", "queer"):
            f = {"is_vip": True} if t == "vip" else {"is_queer": True}
            if q:
                f["$or"] = [{"_id": int(q)}] if q.isdigit() else [{"first_name": {"$regex": re.escape(q), "$options": "i"}},
                                                                  {"username": {"$regex": re.escape(q), "$options": "i"}},
                                                                  {"main_city": {"$regex": re.escape(q), "$options": "i"}}]
            total = users_collection.count_documents({"is_vip": True} if t == "vip" else {"is_queer": True})
            for u in users_collection.find(f, {"first_name": 1, "username": 1, "main_city": 1, "custom_tag": 1, "is_deleted": 1}).limit(3000):
                rows.append({"id": u["_id"], "name": u.get("first_name") or "", "username": str(u.get("username") or "").lstrip("@"),
                             "info": u.get("main_city") or "", "tag": u.get("custom_tag") or "", "deleted": bool(u.get("is_deleted"))})
        elif t == "banned":
            f = {}
            if q:
                f = {"_id": int(q)} if q.isdigit() else {"reason": {"$regex": re.escape(q), "$options": "i"}}
            total = banned_collection.count_documents({})
            docs = list(banned_collection.find(f).sort("_id", -1).limit(3000))
            names = _names([d["_id"] for d in docs])
            for d in docs:
                rows.append({"id": d["_id"], "name": names.get(d["_id"], ""), "username": "", "info": d.get("reason") or "",
                             "tag": d.get("date") or "", "deleted": False})
        else:
            return jsonify({"error": "type"}), 400
        return jsonify({"rows": rows, "total": total, "shown": len(rows)})

    # ---------------- ЧЁРНЫЙ ЯЩИК ----------------
    @app.route('/glaz/api/proxy2/sessions')
    def api_proxy2_sessions():
        if not _auth(): return jsonify({"error": "Unauthorized"}), 401
        q = (request.args.get("q") or "").strip()
        f = {}
        if q.isdigit():
            f = {"$or": [{"vip_id": int(q)}, {"guest_id": int(q)}]}
        elif request.args.get("active") == "1":
            f = {"is_active": True}
        docs = list(proxy_sessions.find(f, {"history": {"$slice": -1}, "vip_id": 1, "guest_id": 1, "is_active": 1}).sort("_id", -1).limit(80))
        # число сообщений без загрузки всей переписки
        counts = {d["_id"]: d.get("n", 0) for d in proxy_sessions.aggregate([
            {"$match": {"_id": {"$in": [x["_id"] for x in docs]}}},
            {"$project": {"n": {"$size": {"$ifNull": ["$history", []]}}}}])}
        names = _names({x for d in docs for x in (d.get("vip_id"), d.get("guest_id")) if isinstance(x, int)})
        out = []
        for d in docs:
            last = (d.get("history") or [{}])[-1] if d.get("history") else {}
            out.append({"id": d["_id"], "vip_id": d.get("vip_id"), "guest_id": d.get("guest_id"),
                        "vip_name": names.get(d.get("vip_id"), ""), "guest_name": names.get(d.get("guest_id"), ""),
                        "is_active": bool(d.get("is_active")), "count": counts.get(d["_id"], 0),
                        "last_text": str(last.get("text", ""))[:120], "last_time": last.get("time", ""),
                        "last_from_vip": last.get("sender") == d.get("vip_id")})
        out.sort(key=lambda s: (not s["is_active"],))
        return jsonify(out)

    # ---------------- РЕПРЕССИИ ----------------
    def _parse_ids(raw):
        seen, ids = set(), []
        for tok in re.split(r"[\s,;]+", str(raw or "")):
            tok = tok.strip()
            if tok.isdigit() and tok not in seen:
                seen.add(tok)
                ids.append(int(tok))
        return ids

    @app.route('/glaz/api/mass/preview', methods=['POST'])
    def api_mass_preview():
        if not _auth(): return jsonify({"error": "Unauthorized"}), 401
        ids = _parse_ids((request.json or {}).get("uids"))[:5000]
        prot = set(protected_ids())
        known = {u["_id"]: u for u in users_collection.find({"_id": {"$in": ids}}, {"is_vip": 1, "is_queer": 1, "first_name": 1})}
        banned = {b["_id"] for b in banned_collection.find({"_id": {"$in": ids}}, {"_id": 1})}
        return jsonify({
            "total": len(ids),
            "admins": [i for i in ids if i in prot],
            "unknown": sum(1 for i in ids if i not in known),
            "banned": sum(1 for i in ids if i in banned),
            "shielded": [{"id": i, "name": known[i].get("first_name", ""), "status": "VIP" if known[i].get("is_vip") else "BEYOND"}
                         for i in ids if i in known and (known[i].get("is_vip") or known[i].get("is_queer"))][:50],
        })

    def _run_job(jid, ids, action, reason, admin):
        done = 0
        for uid in ids:
            if done % 10 == 0:
                st = (db['mass_jobs'].find_one({"_id": jid}, {"status": 1}) or {}).get("status")
                if st == "stopping":
                    break
                db['mass_jobs'].update_one({"_id": jid}, {"$set": {"done": done, "hb": time.time()}})
            try:
                if action == 'ban':
                    ban_user_everywhere(uid, reason=reason, admin_name=f"Web: {admin}")
                elif action == 'mute':
                    mute_user_everywhere(uid, reason=reason, admin_name=f"Web: {admin}")
                elif action == 'unban':
                    unban_user_everywhere(uid); unmute_user_everywhere(uid)
            except Exception as e:
                db['mass_jobs'].update_one({"_id": jid}, {"$inc": {"errors": 1}, "$set": {"last_error": str(e)[:200]}})
            done += 1
            time.sleep(0.5)
        stopped = (db['mass_jobs'].find_one({"_id": jid}, {"status": 1}) or {}).get("status") == "stopping"
        db['mass_jobs'].update_one({"_id": jid}, {"$set": {"done": done, "status": "stopped" if stopped else "done", "finished_at": time.time()}})
        names = {"ban": "БАН", "mute": "МУТ", "unban": "АМНИСТИЯ"}
        add_radar_log(f"✅ Массовый {names.get(action, action)} {'остановлен' if stopped else 'завершён'}: {done} из {len(ids)}")
        try:
            from config import STAFF_GROUP_ID
            bot.send_message(STAFF_GROUP_ID,
                             f"🚀 ВЕБ-АДМИНКА ({admin}): массовый {names.get(action, action)} — обработано {done} из {len(ids)}.\n📝 Причина: {reason}")
        except Exception:
            pass

    def _reap():
        """Задание, прерванное перезапуском сервера (нет «пульса» 5 минут), помечаем прерванным."""
        db['mass_jobs'].update_many({"status": {"$in": ["running", "stopping"]}, "hb": {"$lt": time.time() - 300}},
                                    {"$set": {"status": "interrupted", "finished_at": time.time()}})

    @app.route('/glaz/api/mass/run', methods=['POST'])
    def api_mass_run():
        if not _auth(): return jsonify({"success": False}), 401
        d = request.json or {}
        action = d.get("action")
        if action not in ("ban", "mute", "unban"):
            return jsonify({"success": False, "message": "Неизвестное действие"})
        prot = set(protected_ids())
        ids = [i for i in _parse_ids(d.get("uids"))[:5000] if i not in prot]
        if not ids:
            return jsonify({"success": False, "message": "Нет ID для обработки (админов не трогаем)"})
        reason = str(d.get("reason") or "Массовая репрессия (Web)").strip()[:200]
        admin = session.get("login") or "админ"
        _reap()
        if db['mass_jobs'].find_one({"status": {"$in": ["running", "stopping"]}}):
            return jsonify({"success": False, "message": "Уже идёт другое массовое действие — дождитесь или остановите его"})
        jid = f"m{int(time.time() * 1000)}"
        db['mass_jobs'].insert_one({"_id": jid, "action": action, "reason": reason, "admin": admin, "total": len(ids),
                                    "done": 0, "errors": 0, "status": "running", "started_at": time.time(), "hb": time.time(), "ids_sample": ids[:20]})
        names = {"ban": "БАН", "mute": "МУТ", "unban": "АМНИСТИЮ"}
        add_radar_log(f"⚡ Запущен массовый {names[action]} ({reason}) для {len(ids)} юзеров")
        threading.Thread(target=_run_job, args=(jid, ids, action, reason, admin), daemon=True).start()
        return jsonify({"success": True, "id": jid, "message": f"Запущено для {len(ids)} ID — примерно {max(1, len(ids) // 120)} мин."})

    @app.route('/glaz/api/mass/jobs')
    def api_mass_jobs():
        if not _auth(): return jsonify({"error": "Unauthorized"}), 401
        fmt = lambda ts: datetime.fromtimestamp(ts, EKB).strftime("%d.%m %H:%M") if ts else ""
        _reap()
        out = []
        for j in db['mass_jobs'].find().sort("started_at", -1).limit(15):
            out.append({"id": j["_id"], "action": j.get("action"), "reason": j.get("reason"), "admin": j.get("admin"),
                        "total": j.get("total", 0), "done": j.get("done", 0), "errors": j.get("errors", 0),
                        "status": j.get("status"), "started": fmt(j.get("started_at")), "finished": fmt(j.get("finished_at"))})
        return jsonify(out)

    @app.route('/glaz/api/mass/stop', methods=['POST'])
    def api_mass_stop():
        if not _auth(): return jsonify({"success": False}), 401
        r = db['mass_jobs'].update_one({"_id": (request.json or {}).get("id"), "status": "running"}, {"$set": {"status": "stopping"}})
        return jsonify({"success": bool(r.modified_count)})
