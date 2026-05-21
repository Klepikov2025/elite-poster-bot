from flask import request, jsonify, session
from database import db
import time
from datetime import datetime
import pytz

def register_ads_routes(app, bot, add_radar_log):
    
    # Вспомогательная функция для перевода времени из базы
    def to_ekb_str(dt):
        if dt is None: return "неизвестно"
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(pytz.timezone('Asia/Yekaterinburg')).strftime('%d.%m.%Y %H:%M')

    @app.route('/glaz/api/ads/subs', methods=['GET'])
    def api_get_ad_subs():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        # Достаем все активные подписки (где end_date больше текущего времени)
        now = datetime.now(pytz.utc)
        active_subs = list(db['ad_subscriptions'].find({"end_date": {"$gt": now}}).sort("end_date", 1))
        
        results = []
        for sub in active_subs:
            results.append({
                "id": str(sub['_id']),
                "uid": sub.get("user_id"),
                "network": sub.get("network", "Неизвестно"),
                "city": sub.get("city", "Неизвестно"),
                "end_date": to_ekb_str(sub.get("end_date")),
                "has_pin": sub.get("has_pin", False)
            })
            
        return jsonify(results)

    @app.route('/glaz/api/ads/manage', methods=['POST'])
    def api_manage_ad_sub():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        
        data = request.json
        action = data.get('action') # 'delete' или 'extend'
        sub_id = data.get('sub_id')
        
        from bson.objectid import ObjectId
        
        if action == 'delete':
            # Аннулируем доступ (ставим дату окончания в прошлое)
            db['ad_subscriptions'].update_one(
                {"_id": ObjectId(sub_id)}, 
                {"$set": {"end_date": datetime.now(pytz.utc)}}
            )
            add_radar_log(f"✂️ Рекламный доступ аннулирован (ID: {sub_id})")
            return jsonify({"success": True, "message": "Доступ аннулирован!"})
            
        elif action == 'extend':
            days = int(data.get('days', 0))
            from datetime import timedelta
            
            sub = db['ad_subscriptions'].find_one({"_id": ObjectId(sub_id)})
            if sub:
                new_date = sub["end_date"] + timedelta(days=days)
                db['ad_subscriptions'].update_one(
                    {"_id": ObjectId(sub_id)}, 
                    {"$set": {"end_date": new_date}}
                )
                add_radar_log(f"⏳ Рекламный доступ продлен на {days} дн. (ID: {sub_id})")
                return jsonify({"success": True, "message": f"Продлено на {days} дней!"})
                
        return jsonify({"success": False, "error": "Неизвестное действие"})