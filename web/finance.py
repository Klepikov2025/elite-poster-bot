from flask import request, jsonify, session, redirect, url_for
from database import db, withdrawals_collection, update_user_stats
import time
from datetime import datetime

def register_finance_routes(app, bot, add_radar_log, OWNER_ID, ROOT_PIN):

    @app.route('/glaz/withdrawal_action', methods=['POST'])
    def glaz_withdrawal_action():
        if not session.get('logged_in'): return redirect(url_for('login'))
        wd_id = request.form.get('wd_id')
        action = request.form.get('action')
        wd = withdrawals_collection.find_one({"_id": wd_id})
        if wd and wd.get('status') == 'pending':
            uid = wd['user_id']
            amount = wd['amount']
            if action == 'pay':
                update_user_stats(uid, balance_add=-amount)
                withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "paid"}})
                add_radar_log(f"💸 ОПЛАЧЕНА ЗАЯВКА: {wd_id}")
                try: bot.send_message(uid, f"✅ Ваш запрос на вывод {amount}⭐️ одобрен! Деньги отправлены.")
                except: pass
            elif action == 'reject':
                withdrawals_collection.update_one({"_id": wd_id}, {"$set": {"status": "rejected"}})
                add_radar_log(f"🚫 ОТКЛОНЕНА ЗАЯВКА: {wd_id}")
                try: bot.send_message(uid, "❌ Ваш запрос на вывод средств отклонён.")
                except: pass
        return redirect(url_for('admin_panel'))

    @app.route('/glaz/add_promo', methods=['POST'])
    def glaz_add_promo():
        if not session.get('logged_in'): return redirect(url_for('login'))
        code = request.form.get('code').strip().upper()
        discount = int(request.form.get('discount'))
        target = request.form.get('target')
        limit = int(request.form.get('limit'))
        db['promocodes'].update_one(
            {"_id": code},
            {"$set": {"type": "percent", "value": discount, "target": target, "usage_limit": limit, "used_count": 0, "owner_uid": OWNER_ID, "is_active": True}},
            upsert=True
        )
        add_radar_log(f"🎫 СОЗДАН ПРОМОКОД: {code} ({discount}%)")
        return redirect(url_for('admin_panel'))

    @app.route('/glaz/delete_promo', methods=['POST'])
    def glaz_delete_promo():
        """Уничтожитель промокодов"""
        if not session.get('logged_in'): return redirect(url_for('login'))
        
        code = request.form.get('code')
        if code:
            db['promocodes'].delete_one({"_id": code})
            add_radar_log(f"🗑 ПРОМОКОД УНИЧТОЖЕН: {code}")
            
        return redirect(url_for('admin_panel'))

    # === API РОУТЫ ===
    @app.route('/glaz/api/root/finance', methods=['POST'])
    def api_get_root_finance():
        data = request.json
        if data.get('pin') != ROOT_PIN:
            return jsonify({"error": "Access Denied"}), 403
            
        today_str = datetime.now().strftime("%d.%m.%Y")
        
        # 🔥 ТЕПЕРЬ СЧИТАЕМ ВСЕ ТИПЫ ДОХОДОВ ЗА СЕГОДНЯ ИЗ DAILY_REVENUE
        today_revenue = list(db['daily_revenue'].find({"date": today_str}))
        total_stars = sum(r.get('amount', 0) for r in today_revenue)
        
        # Оставляем детальный список логов для авторазбанов внизу блока
        today_payments = list(db['fine_payments'].find({"date": today_str}))
        formatted_list = []
        for p in today_payments:
            formatted_list.append({
                "uid": p["uid"],
                "amount": p["amount"],
                "time": time.strftime("%H:%M:%S", time.localtime(p["timestamp"]))
            })
            
        return jsonify({
            "total_today": total_stars,
            "payments": formatted_list
        })

    @app.route('/glaz/api/analytics/revenue', methods=['POST'])
    def api_get_revenue_stats():
        data = request.json
        if data.get('pin') != ROOT_PIN: 
            return jsonify({"error": "Unauthorized"}), 403
        
        # 1. Получаем период из запроса вебки (по умолчанию неделя)
        period = data.get('period', 'week')
        pipeline = []
        
        # 2. Фильтр машины времени Скайнета
        if period != 'all':
            from datetime import timedelta, datetime
            days = 7 if period == 'week' else 30
            # Генерируем список правильных дат за последние 7 или 30 дней
            valid_dates = [(datetime.now() - timedelta(days=i)).strftime("%d.%m.%Y") for i in range(days)]
            
            # Говорим базе: отдай только те доходы, дата которых есть в нашем списке
            pipeline.append({"$match": {"date": {"$in": valid_dates}}})
            
        # 3. Суммируем доходы по дням и типам
        pipeline.extend([
            {"$group": {
                "_id": {"date": "$date", "type": "$type"},
                "total": {"$sum": "$amount"}
            }}
        ])
        
        stats = list(db['daily_revenue'].aggregate(pipeline))
        
        # 4. Умная сортировка! Выстраиваем даты в правильном календарном порядке
        try:
            from datetime import datetime
            stats.sort(key=lambda x: datetime.strptime(x['_id']['date'], "%d.%m.%Y"))
        except:
            pass # Если попалась битая дата - игнорируем
            
        return jsonify(stats)

@app.route('/glaz/api/get_prices', methods=['GET'])
    def api_get_prices():
        if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
        
        prices = db['settings'].find_one({"_id": "skynet_pricing"})
        if not prices:
            # Откозоустойчивый дефолт, если в базе еще нет записи
            prices = {
                "vip_price": 250,
                "reg_small_1": 105, "reg_small_7": 490, "reg_small_15": 720, "reg_small_30": 938,
                "reg_big_1": 105, "reg_big_7": 656, "reg_big_15": 1288, "reg_big_30": 1563,
                "vip_big_chat_1": 1095, "vip_big_chat_7": 7656
            }
        return jsonify(prices)

    @app.route('/glaz/api/save_prices', methods=['POST'])
    def api_save_prices():
        if not session.get('logged_in'): return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        data = request.json
        db['settings'].update_one(
            {"_id": "skynet_pricing"},
            {"$set": {
                "vip_price": int(data.get("vip_price", 250)),
                "reg_small_1": int(data.get("reg_small_1", 105)),
                "reg_small_7": int(data.get("reg_small_7", 490)),
                "reg_small_15": int(data.get("reg_small_15", 720)),
                "reg_small_30": int(data.get("reg_small_30", 938)),
                "reg_big_1": int(data.get("reg_big_1", 105)),
                "reg_big_7": int(data.get("reg_big_7", 656)),
                "reg_big_15": int(data.get("reg_big_15", 1288)),
                "reg_big_30": int(data.get("reg_big_30", 1563)),
                "vip_big_chat_1": int(data.get("vip_big_chat_1", 1095)),
                "vip_big_chat_7": int(data.get("vip_big_chat_7", 7656))
            }},
            upsert=True
        )
        add_radar_log("💰 Сетка тарифов (VIP и Реклама) изменена администратором")
        return jsonify({"success": True, "message": "Финансовая матрица успешно обновлена!"})