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

# ========== ПРОВЕРКА И КОНВЕРТАЦИЯ СЕРТИФИКАТА ==========
CERT_FILE = 'russian_trusted_root_ca_gost_2025.cer'
CERT_PATH = os.path.join(os.path.dirname(__file__), CERT_FILE)
USE_CERT = False  # ← ОБЯЗАТЕЛЬНО ОБЪЯВИТЬ

def convert_cer_to_pem(cer_path):
    """Конвертирует DER (бинарный) сертификат в PEM"""
    try:
        with open(cer_path, 'rb') as f:
            der_data = f.read()
        
        import base64
        pem_data = base64.b64encode(der_data).decode('ascii')
        pem_str = f"-----BEGIN CERTIFICATE-----\n{pem_data}\n-----END CERTIFICATE-----"
        
        pem_path = cer_path.replace('.cer', '.pem')
        with open(pem_path, 'w') as f:
            f.write(pem_str)
        
        return pem_path
    except Exception as e:
        logger.warning(f"⚠️ Ошибка конвертации: {e}")
        return None

# Проверяем наличие файла
if os.path.exists(CERT_PATH):
    try:
        # Пробуем прочитать как текст
        with open(CERT_PATH, 'r') as f:
            content = f.read()
        
        # Если это DER (бинарный) — конвертируем
        if '-----BEGIN CERTIFICATE-----' not in content:
            logger.info("🔄 Конвертация сертификата из DER в PEM...")
            pem_path = convert_cer_to_pem(CERT_PATH)
            if pem_path:
                CERT_PATH = pem_path
                USE_CERT = True
                logger.info(f"✅ Сертификат сконвертирован: {CERT_PATH}")
            else:
                USE_CERT = False
                logger.warning("⚠️ Не удалось конвертировать сертификат")
        else:
            USE_CERT = True
            logger.info(f"✅ Сертификат найден (PEM): {CERT_PATH}")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка чтения сертификата: {e}")
        USE_CERT = False
else:
    USE_CERT = False
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
        if USE_CERT:
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=data,
                    timeout=30,
                    verify=CERT_PATH
                )
                logger.info(f"📤 {method} {endpoint} -> {response.status_code} (с сертификатом)")
                return response
            except Exception as e:
                logger.warning(f"⚠️ Ошибка с сертификатом: {e}")
        
        # Fallback - без проверки SSL
        response = requests.request(
            method=method,
            url=url,
            headers=request_headers,
            json=data,
            timeout=30,
            verify=False
        )
        logger.info(f"📤 {method} {endpoint} -> {response.status_code} (без сертификата)")
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка запроса: {e}")
        raise

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С СООБЩЕНИЯМИ ==========

def get_headers():
    if not TOKEN:
        logger.error("❌ ТОКЕН НЕ УСТАНОВЛЕН!")
        return None
    
    return {
        "Authorization": TOKEN,
        "Content-Type": "application/json"
    }

def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        headers = get_headers()
        if not headers:
            return False
            
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        response = max_request("POST", "/messages", data=payload, headers=headers)
        
        if response.status_code == 200:
            return True
            
        if response.status_code == 400:
            payload2 = {"chat_id": chat_id, "text": text}
            response2 = max_request("POST", "/messages", data=payload2, headers=headers)
            return response2.status_code == 200
            
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False

def send_keyboard(chat_id, text, buttons):
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

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard_rows}
            }]
        }

        response = max_request("POST", "/messages", data=payload, headers=headers)
        
        if response.status_code == 200:
            return True
        
        payload2 = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard_rows}
            }]
        }
        
        response2 = max_request("POST", "/messages", data=payload2, headers=headers)
        return response2.status_code == 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False

def show_main_menu(chat_id):
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

def extract_ids_from_data(data):
    user_id = None
    chat_id = None
    text = ""
    
    def search(obj):
        nonlocal user_id, chat_id, text
        if isinstance(obj, dict):
            if 'chat_id' in obj and obj['chat_id']:
                chat_id = obj['chat_id']
            if 'user_id' in obj and obj['user_id']:
                user_id = obj['user_id']
            if 'text' in obj and obj['text']:
                text = obj['text']
            for value in obj.values():
                search(value)
        elif isinstance(obj, list):
            for item in obj:
                search(item)
    
    search(data)
    return user_id, chat_id, text

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
                verify=CERT_PATH if USE_CERT else False
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
            verify=CERT_PATH if USE_CERT else False
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
    """Обработка вебхука от МАХ"""
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        # ========== ПАРСИНГ ДАННЫХ МАХ ==========
        chat_id = None
        text = None
        
        # Структура МАХ: message.recipient.chat_id и message.body.text
        if 'message' in data:
            message = data['message']
            
            # Извлекаем chat_id из recipient
            if 'recipient' in message:
                recipient = message['recipient']
                chat_id = recipient.get('chat_id')
            
            # Извлекаем текст из body
            if 'body' in message:
                body = message['body']
                text = body.get('text')
        
        # Если не нашли через message - пробуем другие варианты
        if not chat_id:
            # Проверяем прямой recipient (если данные без обертки)
            if 'recipient' in data:
                chat_id = data['recipient'].get('chat_id')
            
            # Проверяем прямые поля
            if not chat_id:
                chat_id = data.get('chat_id')
                text = data.get('text')
        
        if not chat_id:
            logger.warning("⚠️ Не удалось найти chat_id в данных")
            logger.info(f"📦 Данные: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
            return jsonify({"ok": True}), 200

        logger.info(f"💬 chat_id={chat_id}, text='{text}'")

        # ========== ОБРАБОТКА КОМАНД ==========
        if text and isinstance(text, str):
            text_lower = text.lower().strip()
            
            if text_lower in ["/start", "start"]:
                show_main_menu(chat_id)
                return jsonify({"ok": True}), 200

            if text_lower == "/help":
                send_message(
                    chat_id,
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
