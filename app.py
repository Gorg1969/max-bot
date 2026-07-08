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
    else:
        USE_CERT = True
        logger.info(f"✅ Сертификат найден (PEM): {CERT_PATH}")
else:
    USE_CERT = False
    logger.warning(f"⚠️ Сертификат НЕ НАЙДЕН: {CERT_PATH}")

# ========== ФУНКЦИЯ ЗАПРОСОВ К МАХ ==========
def max_request(method, endpoint, data=None, headers=None):
    """Универсальный запрос к API МАХ"""
    url = f"{BASE_URL}{endpoint}"
    
    # ✅ ПРАВИЛЬНЫЕ ЗАГОЛОВКИ
    request_headers = {}
    
    if TOKEN:
        # ✅ ТОЛЬКО ТОКЕН, БЕЗ "Bearer "
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
                logger.info(f"📤 {method} {endpoint} -> {response.status_code}")
                return response
            except Exception as e:
                logger.warning(f"⚠️ Ошибка с сертификатом: {e}")
        
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
    
    # ✅ ПРАВИЛЬНЫЙ ФОРМАТ
    return {
        "Authorization": TOKEN,  # ← ТОЛЬКО ТОКЕН
        "Content-Type": "application/json"
    }

def send_message(chat_id, text, parse_mode="Markdown"):
    """Отправка сообщения"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        logger.info(f"📤 Отправка в chat_id={chat_id}")
        
        response = max_request(
            "POST",
            "/messages",
            data=payload,
            headers=headers
        )
        
        if response.status_code == 200:
            return True
            
        if response.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "chat_id": chat_id,
                "text": text
            }
            response2 = max_request(
                "POST",
                "/messages",
                data=payload2,
                headers=headers
            )
            return response2.status_code == 200
            
        return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def send_keyboard(chat_id, text, buttons):
    """Отправка клавиатуры"""
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
                "payload": {
                    "buttons": keyboard_rows
                }
            }]
        }

        response = max_request(
            "POST",
            "/messages",
            data=payload,
            headers=headers
        )
        
        if response.status_code == 200:
            return True
        
        payload2 = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {
                    "buttons": keyboard_rows
                }
            }]
        }
        
        response2 = max_request(
            "POST",
            "/messages",
            data=payload2,
            headers=headers
        )
        
        return response2.status_code == 200
        
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

def extract_ids_from_data(data):
    """Извлечение ID из данных"""
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
    """Отладка"""
    return {
        "token": "✅" if TOKEN else "❌",
        "token_preview": f"{TOKEN[:4]}...{TOKEN[-4:]}" if TOKEN else None,
        "certificate": {
            "found": USE_CERT,
            "path": CERT_PATH,
            "exists": os.path.exists(CERT_PATH) if CERT_PATH else False
        },
        "auth_format": "Authorization: <token> (без Bearer)"  # ← Добавляем пояснение
    }, 200

@app.route('/setup_webhook')
def setup_webhook():
    """Настройка вебхука"""
    token = request.args.get('token') or TOKEN
    
    if not token:
        return """
        <html>
        <body style="font-family: monospace; padding: 20px;">
            ❌ <b>Ошибка:</b> токен не передан и не установлен в окружении<br>
            Используйте: <b>/setup_webhook?token=ВАШ_ТОКЕН</b>
        </body>
        </html>
        """, 400
    
    webhook_url = "https://max-bot-ulzl.onrender.com/webhook"
    
    html = f"""
    <html>
    <body style="font-family: monospace; padding: 20px; background: #f0f0f0;">
        <div style="max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px;">
            <h2>🔐 Настройка вебхука для MAX</h2>
            <hr>
            <p><b>📁 Сертификат:</b> {'✅ Найден' if USE_CERT else '❌ Не найден'}</p>
            <p><b>📂 Путь:</b> {CERT_PATH if CERT_PATH else 'Не указан'}</p>
            <p><b>🔑 Токен:</b> {token[:4]}...{token[-4:] if len(token) > 8 else '***'}</p>
            <p><b>🌐 Вебхук:</b> {webhook_url}</p>
            <p><b>📌 Формат авторизации:</b> Authorization: &lt;token&gt; (без Bearer)</p>
            <hr>
    """
    
    try:
        # ✅ ПРАВИЛЬНЫЕ ЗАГОЛОВКИ
        headers = {
            "Authorization": token,  # ← ТОЛЬКО ТОКЕН, БЕЗ "Bearer "
            "Content-Type": "application/json"
        }
        
        # 1. Удаляем старую подписку
        html += "<h3>🗑️ Удаление старой подписки...</h3>"
        try:
            r_del = requests.delete(
                "https://platform-api2.max.ru/subscriptions",
                headers=headers,
                timeout=10,
                verify=CERT_PATH if USE_CERT else False
            )
            html += f"<p>DELETE: <b>{r_del.status_code}</b></p>"
            if r_del.status_code == 200:
                html += "<p style='color: green;'>✅ Старая подписка удалена</p>"
            else:
                html += f"<p style='color: orange;'>⚠️ Ответ: {r_del.text[:100]}</p>"
        except Exception as e:
            html += f"<p style='color: orange;'>⚠️ Ошибка: {e}</p>"
        
        # 2. Создаем новую подписку
        html += "<h3>📝 Создание новой подписки...</h3>"
        r = requests.post(
            "https://platform-api2.max.ru/subscriptions",
            headers=headers,
            json={"url": webhook_url},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        html += f"<p>POST: <b>{r.status_code}</b></p>"
        html += f"<p>Ответ: <pre style='background: #f5f5f5; padding: 10px;'>{r.text[:300]}</pre></p>"
        
        if r.status_code == 200:
            html += """
            <div style="background: #d4edda; padding: 15px; border-radius: 5px; margin: 10px 0;">
                ✅ <b>ВЕБХУК УСПЕШНО НАСТРОЕН!</b>
            </div>
            """
        else:
            html += f"""
            <div style="background: #f8d7da; padding: 15px; border-radius: 5px; margin: 10px 0;">
                ❌ <b>Ошибка настройки вебхука</b><br>
                Код: {r.status_code}<br>
                {r.text[:200]}
            </div>
            """
        
        html += """
        <hr>
        <p><a href="/health">✅ Проверить здоровье</a> | <a href="/debug">🔍 Отладка</a></p>
        </div>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        return f"""
        <html>
        <body style="font-family: monospace; padding: 20px;">
            <div style="background: #f8d7da; padding: 15px; border-radius: 5px;">
                ❌ <b>Ошибка:</b> {e}
            </div>
        </body>
        </html>
        """, 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхука"""
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id, chat_id, text = extract_ids_from_data(data)
        
        if not chat_id and user_id:
            chat_id = user_id

        logger.info(f"💬 user_id={user_id}, chat_id={chat_id}, text='{text[:30] if text else ''}'")

        if not chat_id:
            return jsonify({"ok": True}), 200

        if text:
            if text.lower() in ["/start", "start"]:
                show_main_menu(chat_id)
                return jsonify({"ok": True}), 200

            if text.lower() == "/help":
                send_message(
                    chat_id,
                    "📖 **Помощь**\n\nКоманды:\n/start - Главное меню\n/choose - Выбрать папку\n/publish - Начать публикацию\n/stop - Остановить\n/help - Справка"
                )
                return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
