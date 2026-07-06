from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN", "ВАШ_ТОКЕН_БОТА")
BASE_URL = "https://platform-api2.max.ru"

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

def send_keyboard(chat_id, text, buttons):
    try:
        kb = []
        for b in buttons:
            kb.append([{"text": b["text"], "type": "callback", "payload": b["payload"]}])
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{"type": "inline_keyboard", "payload": {"buttons": kb}}]
        }
        
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload,
            timeout=10,
            verify=False
        )
        logger.info(f"⌨️ Клавиатура: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка клавиатуры: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")
        logger.info(f"📦 Данные: {json.dumps(data, ensure_ascii=False)[:300]}")
        
        if not data:
            return jsonify({"ok": True}), 200
        
        # ===== ИЗВЛЕКАЕМ CHAT_ID =====
        # Пробуем из разных полей
        chat_id = data.get('chat_id')
        if not chat_id:
            chat_id = data.get('recipient', {}).get('chat_id')
        if not chat_id:
            chat_id = data.get('message', {}).get('recipient', {}).get('chat_id')
        
        # ===== ИЗВЛЕКАЕМ ТЕКСТ =====
        text = data.get('body', {}).get('text', '')
        if not text:
            text = data.get('message', {}).get('body', {}).get('text', '')
        
        # ===== ИЗВЛЕКАЕМ USER_ID =====
        user_id = data.get('user_id')
        if not user_id:
            user_id = data.get('sender', {}).get('user_id')
        if not user_id:
            user_id = data.get('message', {}).get('sender', {}).get('user_id')
        
        logger.info(f"💬 chat_id: {chat_id}, user_id: {user_id}, text: {text}")
        
        if chat_id:
            # Отвечаем на любое сообщение
            send_message(chat_id, f"✅ Бот получил: {text}")
            
            if text == "/start":
                send_keyboard(
                    chat_id,
                    "🏠 **Главное меню**\n\nВыберите действие:",
                    [
                        {"text": "📂 Выбрать папку", "payload": "choose_folder"},
                        {"text": "▶️ Начать публикацию", "payload": "start_publish"},
                        {"text": "ℹ️ Помощь", "payload": "help"}
                    ]
                )
        
        logger.info("=" * 50)
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

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
