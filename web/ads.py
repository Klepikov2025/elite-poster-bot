from flask import request, jsonify, session
from database import db
import time
from datetime import datetime
import pytz
from bson.objectid import ObjectId

def register_ads_routes(app, bot, add_radar_log):
    
    # Бронебойная функция перевода времени (понимает и числа, и даты)
    def to_ekb_str(dt):
        if not dt: return "неизвестно"
        try:
            # Если бот сохранил время как обычное число (timestamp)
            if isinstance(dt, (int, float)):
                dt_obj = datetime.fromtimestamp(dt, pytz.utc)
            # Если это уже готовая строка
            elif isinstance(dt, str):
                return dt
            # Если это классический объект datetime
            else:
                dt_obj = dt
                if dt_obj.tzinfo is None:
                    dt_obj = pytz.utc.localize(dt_obj)
            
            # Переводим в часовой пояс Екатеринбурга (+5)
            return dt_obj.astimezone(pytz.timezone('Asia/Yekaterinburg')).strftime('%d.%m.%Y %H:%M')
        except Exception as e:
            return str(dt) # Если формат совсем странный, выводим как есть

    @app.route('/glaz/api/ads/subs', methods=['GET'])
    def api_get_ad_subs():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        # Достаем абсолютно ВСЕ подписки (фильтровать будем в Питоне, чтобы БД не крашилась от конфликта типов)
        all_subs = list(db['ad_subscriptions'].find())
        now_ts = time.time()
        now_dt = datetime.now(pytz.utc)
        
        results = []
        for sub in all_subs:
            end_date = sub.get("end_date")
            
            # Умная проверка активности
            is_active = False
            if isinstance(end_date, (int, float)) and end_date > now_ts:
                is_active = True
            elif isinstance(end_date, datetime):
                if end_date.tzinfo is None: 
                    end_date = pytz.utc.localize(end_date)
                if end_date > now_dt: 
                    is_active = True
            elif isinstance(end_date, str):
                is_active = True # Строки пока считаем активными, чтобы не потерять запись
            
            if is_active:
                results.append({
                    "id": str(sub['_id']),
                    "uid": sub.get("user_id") or sub.get("uid", "Не указан"), # Подстраховка имени поля
                    "network": sub.get("network", "Неизвестно"),
                    "city": sub.get("city", "Неизвестно"),
                    "end_date": to_ekb_str(end_date),
                    "has_pin": sub.get("has_pin", False)
                })
            
        return jsonify(results)

    @app.route('/glaz/api/ads/manage', methods=['POST'])
    def api_manage_ad_sub():
        if not session.get('logged_in'): return jsonify({"success": False}), 401
        
        data = request.json
        action = data.get('action')
        sub_id = data.get('sub_id')
        
        if action == 'delete':
            # Аннулируем доступ (просто обнуляем дату)
            db['ad_subscriptions'].update_one(
                {"_id": ObjectId(sub_id)}, 
                {"$set": {"end_date": 0}}
            )
            add_radar_log(f"✂️ Рекламный доступ аннулирован (ID: {sub_id})")
            return jsonify({"success": True, "message": "Доступ аннулирован!"})
            
        elif action == 'extend':
            days = int(data.get('days', 0))
            sub = db['ad_subscriptions'].find_one({"_id": ObjectId(sub_id)})
            
            if sub:
                end_date = sub.get("end_date")
                
                # Продлеваем грамотно, в зависимости от того, в каком формате лежит дата
                if isinstance(end_date, (int, float)):
                    new_date = end_date + (days * 86400) # 86400 секунд в дне
                elif isinstance(end_date, datetime):
                    from datetime import timedelta
                    new_date = end_date + timedelta(days=days)
                else:
                    new_date = time.time() + (days * 86400) # Запасной вариант

                db['ad_subscriptions'].update_one(
                    {"_id": ObjectId(sub_id)}, 
                    {"$set": {"end_date": new_date}}
                )
                add_radar_log(f"⏳ Рекламный доступ продлен на {days} дн. (ID: {sub_id})")
                return jsonify({"success": True, "message": f"Продлено на {days} дней!"})
                
        return jsonify({"success": False, "error": "Неизвестное действие"})