from flask import request, jsonify, session
from database import db
import time
from datetime import datetime
import pytz
from bson.objectid import ObjectId
import traceback

def register_ads_routes(app, bot, add_radar_log):
    
    @app.route('/glaz/api/ads/subs', methods=['GET'])
    def api_get_ad_subs():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        try:
            # 🔥 ГЕНИАЛЬНЫЙ ФИКС: Принудительно читаем из той же базы, куда пишет mpserv.py
            try:
                target_db = db.client['elite_bot_db']
                collection = target_db['ad_subscriptions']
            except:
                collection = db['ad_subscriptions']
                
            # Берем все записи (убрали жесткий фильтр по времени, чтобы видеть вообще всё)
            all_subs = list(collection.find())
            
            results = []
            for sub in all_subs:
                end_date = sub.get("end_date")
                
                # Бронебойная конвертация времени
                date_str = "неизвестно"
                end_ts = None
                try:
                    if isinstance(end_date, datetime):
                        end_ts = (pytz.utc.localize(end_date) if end_date.tzinfo is None else end_date).timestamp()
                    elif isinstance(end_date, (int, float)):
                        end_ts = float(end_date)
                except Exception:
                    end_ts = None
                try:
                    if isinstance(end_date, datetime):
                        if end_date.tzinfo is None:
                            end_date = pytz.utc.localize(end_date)
                        date_str = end_date.astimezone(pytz.timezone('Asia/Yekaterinburg')).strftime('%d.%m.%Y %H:%M')
                    elif isinstance(end_date, (int, float)):
                        date_str = datetime.fromtimestamp(end_date, pytz.utc).astimezone(pytz.timezone('Asia/Yekaterinburg')).strftime('%d.%m.%Y %H:%M')
                    else:
                        date_str = str(end_date)
                except Exception:
                    date_str = "ошибка даты"

                results.append({
                    "id": str(sub.get('_id', '')),
                    "uid": str(sub.get("user_id") or sub.get("uid", "Не указан")),
                    "network": str(sub.get("network", "Неизвестно")),
                    "city": str(sub.get("city", "Неизвестно")),
                    "end_date": date_str if end_ts != 0 else "отключена",
                    "end_ts": end_ts,
                    "has_pin": sub.get("has_pin", False)
                })
            
            return jsonify(results)
            
        except Exception as e:
            # Если питон падает, выводим красную ошибку прямо в таблицу на сайте!
            print(traceback.format_exc())
            return jsonify({"error": f"Ошибка чтения подписок: {e}"})

    @app.route('/glaz/api/ads/manage', methods=['POST'])
    def api_manage_ad_sub():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        
        try:
            data = request.json
            action = data.get('action')
            sub_id = data.get('sub_id')
            
            try:
                target_db = db.client['elite_bot_db']
                collection = target_db['ad_subscriptions']
            except:
                collection = db['ad_subscriptions']
            
            if action == 'delete':
                collection.update_one({"_id": ObjectId(sub_id)}, {"$set": {"end_date": 0}})
                add_radar_log(f"✂️ Рекламный доступ аннулирован (ID: {sub_id})")
                return jsonify({"success": True, "message": "Доступ аннулирован!"})
                
            elif action == 'extend':
                days = int(data.get('days', 0))
                sub = collection.find_one({"_id": ObjectId(sub_id)})
                
                if sub:
                    if not (0 < days <= 3650):
                        return jsonify({"success": False, "error": "Число дней от 1 до 3650"})
                    end_date = sub.get("end_date")
                    # Продлеваем от «сейчас», если подписка уже кончилась (раньше прибавляли к прошедшей дате)
                    if isinstance(end_date, (int, float)):
                        new_date = max(float(end_date), time.time()) + (days * 86400)
                    elif isinstance(end_date, datetime):
                        from datetime import timedelta
                        base = end_date if end_date.tzinfo is None else end_date.astimezone(pytz.utc).replace(tzinfo=None)
                        new_date = max(base, datetime.utcnow()) + timedelta(days=days)
                    else:
                        new_date = time.time() + (days * 86400)

                    collection.update_one({"_id": ObjectId(sub_id)}, {"$set": {"end_date": new_date}})
                    add_radar_log(f"⏳ Рекламный доступ продлен на {days} дн. (ID: {sub_id})")
                    return jsonify({"success": True, "message": f"Продлено на {days} дней!"})
                    
            return jsonify({"success": False, "error": "Неизвестное действие"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})