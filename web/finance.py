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

    @app.route('/glaz/api/root/finance', methods=['POST'])
    def api_get_root_finance():
        data = request.json
        # Жесткая проверка пин-кода
        if data.get('pin') != ROOT_PIN:
            return jsonify({"error": "Access Denied"}), 403
            
        today_str = datetime.now().strftime("%d.%m.%Y")
        
        # 🧠 Агрегация: Считаем сумму звезд за сегодня
        today_payments = list(db['fine_payments'].find({"date": today_str}))
        total_stars = sum(p.get('amount', 0) for p in today_payments)
        
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
        
        # Агрегация: группируем по ДАТЕ и ТИПУ (для будущего графика-календаря)
        pipeline = [
            {"$group": {
                "_id": {"date": "$date", "type": "$type"},
                "total": {"$sum": "$amount"}
            }},
            {"$sort": {"_id.date": 1}}
        ]
        stats = list(db['daily_revenue'].aggregate(pipeline))
        return jsonify(stats)