from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import re
import random
from pathlib import Path
import urllib3

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN", "f9LHodD0cOJlllLX1fR59yrbAD6H3UWttud4hPu4zQOQnY2SwNo5NIJtSRA5feJviS8obhPIQ2954lD9YGNp")
BASE_URL = "https://platform-api2.max.ru"

# Хранилища
user_states = {}
user_folders = {}
user_publication_status = {}

# ========== ОТПРАВКА СООБЩЕНИЙ (С ОТКЛЮЧЕНИЕМ SSL) ==========

def send_message_to_chat(chat_id, text):
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10,
            verify=False  # ОТКЛЮЧАЕМ SSL!
        )
        logger.info(f"   Отправка: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"   Ошибка: {e}")
        return False

def send_keyboard_to_chat(chat_id, text, buttons):
    try:
        keyboard_buttons = []
        for button in buttons:
            keyboard_buttons.append([{
                "text": button["text"],
                "type": "callback",
                "payload": button["payload"]
            }])
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard_buttons}
            }]
        }
        
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload,
            timeout=10,
            verify=False  # ОТКЛЮЧАЕМ SSL!
        )
        logger.info(f"   Клавиатура: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"   Ошибка клавиатуры: {e}")
        return False

# ========== МЕНЮ ==========

def show_main_menu(chat_id):
    folder = user_folders.get(chat_id, "Не выбрана")
    send_keyboard_to_chat(
        chat_id,
        f"🏠 Главное меню\n📂 Папка: {folder}\n\nВыберите действие:",
        [
            {"text": "📂 Выбрать папку", "payload": "choose_folder"},
            {"text": "▶️ Начать публикацию", "payload": "start_publish"},
            {"text": "⏹ Остановить", "payload": "stop_publication"},
            {"text": "ℹ️ Помощь", "payload": "help"}
        ]
    )

# ========== ВЕБХУК ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")
        
        if not data:
            return jsonify({"ok": True}), 200
        
        if "message" in data:
            msg = data["message"]
            chat_id = msg.get("recipient", {}).get("chat_id")
            text = msg.get("body", {}).get("text", "")
            
            logger.info(f"💬 Сообщение в чат {chat_id}: {text}")
            
            if text == "/start":
                show_main_menu(chat_id)
        
        elif "callback_query" in data:
            cb = data["callback_query"]
            chat_id = cb.get("chat_id")
            payload = cb.get("payload", "")
            
            logger.info(f"🔘 Кнопка: {payload}")
            
            if payload == "choose_folder":
                send_message_to_chat(chat_id, "📁 Введите путь к папке:")
                user_states[chat_id] = "waiting_folder"
            elif payload == "start_publish":
                send_message_to_chat(chat_id, "🚀 Начинаю публикацию...")
            elif payload == "help":
                send_message_to_chat(chat_id, "📖 Помощь")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"ok": False}), 500

# ========== МАРШРУТ ДЛЯ НАСТРОЙКИ ВЕБХУКА ==========

@app.route('/setup_webhook')
def setup_webhook():
    token = request.args.get('token')
    if not token:
        return "❌ Нет токена! Добавьте ?token=ВАШ_ТОКЕН", 400
    
    webhook_url = "https://max-bot-ulzl.onrender.com/webhook"
    
    try:
        # Сначала удаляем старые подписки
        requests.delete(
            "https://platform-api2.max.ru/subscriptions",
            headers={"Authorization": token},
            timeout=10,
            verify=False  # ОТКЛЮЧАЕМ SSL!
        )
        
        # Настраиваем новую
        r = requests.post(
            "https://platform-api2.max.ru/subscriptions",
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={"url": webhook_url},
            timeout=10,
            verify=False  # ОТКЛЮЧАЕМ SSL!
        )
        return f"✅ Статус: {r.status_code}\n✅ Ответ: {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

# ========== СТРАНИЦЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running on Render.com!", 200

@app.route('/health')
def health():
    return {"status": "ok", "time": time.strftime('%Y-%m-%d %H:%M:%S')}, 200

@app.route('/ping')
def ping():
    return "pong", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
