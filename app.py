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

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"

# ========== ПРОВЕРКА СЕРТИФИКАТА ==========
CERT_FILE = 'russian_trusted_root_ca_gost_2025.cer'
CERT_PATH = os.path.join(os.path.dirname(__file__), CERT_FILE)
USE_CERT = False  # ПОКА ОТКЛЮЧЕН

if os.path.exists(CERT_PATH):
    logger.info(f"✅ Сертификат найден: {CERT_PATH}, но пока отключен")
else:
    logger.warning(f"⚠️ Сертификат НЕ НАЙДЕН: {CERT_PATH}")

# ========== ФУНКЦИЯ ЗАПРОСОВ К МАХ ==========
def max_request(method, endpoint, data=None, headers=None):
    """Универсальный запрос к API МАХ"""
    url = f"{BASE_URL}{endpoint}"
    
    request_headers = {}
    
    if TOKEN:
        request_headers["Authorization"] = TOKEN
        logger.info(f"🔑 Токен добавлен: {TOKEN[:4]}...{TOKEN[-4:]}")
    else:
        logger.error("❌ ТОКЕН НЕ НАЙДЕН!")
    
    request_headers["Content-Type"] = "application/json"
    
    if headers:
        request_headers.update(headers)
    
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=request_headers,
            json=data,
            timeout=30,
            verify=False
        )
        logger.info(f"📤 {method} {endpoint} -> {response.status_code}")
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка запроса: {e}")
        raise

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С СООБЩЕНИЯМИ ==========

def get_headers():
    """Получение заголовков с токеном"""
    if not TOKEN:
        logger.error("❌ ТОКЕН НЕ УСТАНОВЛЕН!")
        return None
    
    return {
        "Authorization": TOKEN,
        "Content-Type": "application/json"
    }

def send_message(chat_id, text, parse_mode="Markdown"):
    """Отправка сообщения в МАХ (ТОЛЬКО НА CHAT_ID!)"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        # ✅ ПРАВИЛЬНЫЙ ФОРМАТ ДЛЯ МАХ - ТОЛЬКО CHAT_ID
        payload = {
            "recipient": {
                "chat_id": chat_id  # <-- ТОЛЬКО chat_id!
            },
            "text": text,
            "parse_mode": parse_mode
        }
        
        logger.info(f"📤 Отправка в chat_id={chat_id}")
        logger.info(f"📦 Пейлоад: {json.dumps(payload, ensure_ascii=False)[:200]}")
        
        response = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30,
            verify=False
        )
        
        logger.info(f"📤 Ответ: {response.status_code} - {response.text[:200]}")
        
        if response.status_code == 200:
            return True
            
        if response.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "recipient": {
                    "chat_id": chat_id  # <-- ТОЛЬКО chat_id!
                },
                "text": text
            }
            response2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Ответ без parse_mode: {response2.status_code} - {response2.text[:200]}")
            return response2.status_code == 200
            
        return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def send_keyboard(chat_id, text, buttons):
    """Отправка клавиатуры в МАХ (ТОЛЬКО НА CHAT_ID!)"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        keyboard_rows = []
        for button in buttons:
            keyboard_rows.append([{
                "text": button["text"],
                "type": "callback",
                "payload": button["payload"]
            }])

        # ✅ ПРАВИЛЬНЫЙ ФОРМАТ ДЛЯ МАХ - ТОЛЬКО CHAT_ID
        payload = {
            "recipient": {
                "chat_id": chat_id  # <-- ТОЛЬКО chat_id!
            },
            "text": text,
            "parse_mode": "Markdown",
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {
                    "buttons": keyboard_rows
                }
            }]
        }

        logger.info(f"📤 Отправка клавиатуры в chat_id={chat_id}")
        logger.info(f"📦 Пейлоад: {json.dumps(payload, ensure_ascii=False)[:300]}")

        response = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30,
            verify=False
        )
        
        logger.info(f"📤 Ответ: {response.status_code} - {response.text[:200]}")
        
        if response.status_code == 200:
            logger.info("✅ Клавиатура отправлена!")
            return True
        
        if response.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "recipient": {
                    "chat_id": chat_id  # <-- ТОЛЬКО chat_id!
                },
                "text": text,
                "attachments": [{
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": keyboard_rows
                    }
                }]
            }
            
            response2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Ответ без parse_mode: {response2.status_code} - {response2.text[:200]}")
            
            if response2.status_code == 200:
                return True
        
        logger.info("🔄 Отправляю обычное сообщение...")
        return send_message(chat_id, text)
        
    except Exception as e:
        logger.error(f"❌ Ошибка клавиатуры: {e}")
        return False

def show_main_menu(chat_id):
    """Главное меню"""
    send_keyboard(
        chat_id,
        "🏠 **Главное меню**\n\nВыберите действие:",
        [
            {"text": "📂 Выбрать папку", "payload": "choose_folder"},
            {"text": "▶️ Начать публикацию", "payload": "start_publish"},
            {"text": "⏹ Остановить", "payload": "stop_publication"},
            {"text": "ℹ️ Помощь", "payload": "help"}
        ]
    )

# ========== ЭНДПОИНТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!", 200

@app.route('/health')
def health():
    return {
        "status": "ok",
        "time": time.strftime('%Y-%m-%d %H:%M:%S'),
        "certificate": {
            "found": USE_CERT,
            "path": CERT_PATH
        },
        "token": {
            "exists": bool(TOKEN),
            "preview": f"{TOKEN[:4]}...{TOKEN[-4:]}" if TOKEN else None
        }
    }, 200

@app.route('/debug')
def debug():
    """Отладка"""
    return {
        "token": "✅" if TOKEN else "❌",
        "token_preview": f"{TOKEN[:4]}...{TOKEN[-4:]}" if TOKEN else None,
        "certificate": {
            "found": USE_CERT,
            "path": CERT_PATH,
            "exists": os.path.exists(CERT_PATH) if CERT_PATH else False
        }
    }, 200

@app.route('/setup_webhook')
def setup_webhook():
    token = request.args.get('token') or TOKEN
    
    if not token:
        return "❌ Токен не найден", 400
    
    webhook_url = "https://max-bot-ulzl.onrender.com/webhook"
    
    html = f"""
    <html>
    <body style="font-family: monospace; padding: 20px;">
        <h2>🔐 Настройка вебхука</h2>
        <p><b>Сертификат:</b> {'✅ Есть' if USE_CERT else '❌ Нет'}</p>
        <p><b>Токен:</b> {token[:4]}...{token[-4:]}</p>
        <hr>
    """
    
    try:
        headers = {
            "Authorization": token,
            "Content-Type": "application/json"
        }
        
        html += "<h3>🗑️ Удаление...</h3>"
        try:
            r_del = requests.delete(
                "https://platform-api2.max.ru/subscriptions",
                headers=headers,
                timeout=10,
                verify=False
            )
            html += f"<p>DELETE: {r_del.status_code}</p>"
        except Exception as e:
            html += f"<p>⚠️ Ошибка: {e}</p>"
        
        html += "<h3>📝 Создание...</h3>"
        r = requests.post(
            "https://platform-api2.max.ru/subscriptions",
            headers=headers,
            json={"url": webhook_url},
            timeout=10,
            verify=False
        )
        html += f"<p>POST: {r.status_code}</p>"
        html += f"<p>Ответ: {r.text[:300]}</p>"
        
        if r.status_code == 200:
            html += "<p style='color: green;'>✅ ВЕБХУК НАСТРОЕН!</p>"
        else:
            html += f"<p style='color: red;'>❌ Ошибка: {r.text[:200]}</p>"
        
        html += "</body></html>"
        return html
        
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхука от МАХ (ТОЛЬКО CHAT_ID!)"""
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        # ========== ИЩЕМ ТОЛЬКО CHAT_ID ==========
        chat_id = None
        text = None
        
        # Рекурсивный поиск chat_id и text
        def search(obj):
            nonlocal chat_id, text
            if isinstance(obj, dict):
                if "chat_id" in obj and chat_id is None:
                    chat_id = obj["chat_id"]
                if "text" in obj and text is None:
                    text = obj["text"]
                for value in obj.values():
                    search(value)
            elif isinstance(obj, list):
                for item in obj:
                    search(item)
        
        search(data)
        
        if not chat_id:
            logger.warning("⚠️ Не удалось найти chat_id в данных")
            logger.info(f"📦 Данные: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
            return jsonify({"ok": True}), 200

        logger.info(f"💬 chat_id={chat_id}, text='{text}'")

        # ========== ОБРАБОТКА КОМАНД ==========
        if text and isinstance(text, str):
            text_lower = text.lower().strip()
            
            if text_lower in ["/start", "start"]:
                show_main_menu(chat_id)  # <-- ТОЛЬКО chat_id!
                return jsonify({"ok": True}), 200

            if text_lower == "/help":
                send_message(
                    chat_id,  # <-- ТОЛЬКО chat_id!
                    "📖 **Помощь**\n\nКоманды:\n/start - Главное меню\n/choose - Выбрать папку\n/publish - Начать публикацию\n/stop - Остановить\n/help - Справка"
                )
                return jsonify({"ok": True}), 200

            if text_lower == "/choose":
                send_message(chat_id, "📁 Выберите папку (функция в разработке)")
                return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
