from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN", "f9LHodD0cOJlllLX1fR59yrbAD6H3UWttud4hPu4zQOQnY2SwNo5NIJtSRA5feJviS8obhPIQ2954lD9YGNp")
BASE_URL = "https://platform-api2.max.ru"

# ========== ОТПРАВКА ==========

def send_message(chat_id, text):
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10,
            verify=False
        )
        logger.info(f"📤 Отправка: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False

# ========== ВЕБХУК (ПРИНИМАЕТ POST!) ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")
        logger.info(f"📦 Данные: {json.dumps(data, ensure_ascii=False)[:300]}")
        
        if not data:
            return jsonify({"ok": True}), 200
        
        # Обработка сообщения
        if "message" in data:
            msg = data["message"]
            chat_id = msg.get("recipient", {}).get("chat_id")
            text = msg.get("body", {}).get("text", "")
            
            logger.info(f"💬 Чат: {chat_id}, Текст: {text}")
            
            if chat_id:
                send_message(chat_id, f"✅ Бот получил: {text}")
        
        # Обработка кнопок
        elif "callback_query" in data:
            cb = data["callback_query"]
            chat_id = cb.get("chat_id")
            payload = cb.get("payload", "")
            logger.info(f"🔘 Кнопка: {payload}")
            if chat_id:
                send_message(chat_id, f"✅ Нажата кнопка: {payload}")
        
        logger.info("=" * 50)
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== СТРАНИЦЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running on Render.com!", 200

@app.route('/health')
def health():
    return {"status": "ok", "time": time.strftime('%Y-%m-%d %H:%M:%S')}, 200

@app.route('/setup_webhook')
def setup_webhook():
    token = request.args.get('token')
    if not token:
        return "❌ Нет токена", 400
    
    webhook_url = "https://max-bot-ulzl.onrender.com/webhook"
    
    try:
        requests.delete(
            f"{BASE_URL}/subscriptions",
            headers={"Authorization": token},
            timeout=10,
            verify=False
        )
        r = requests.post(
            f"{BASE_URL}/subscriptions",
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={"url": webhook_url},
            timeout=10,
            verify=False
        )
        return f"✅ Статус: {r.status_code}\n✅ Ответ: {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
