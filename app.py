from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
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

# ========== ПРОКСИ ДЛЯ РОССИЙСКОГО IP ==========
PROXY = {
    "http": "http://92.242.8.114:8080",
    "https": "http://92.242.8.114:8080"
}

# ========== ФУНКЦИЯ ЗАПРОСОВ К МАХ ==========
def max_request(method, endpoint, data=None, headers=None):
    """Универсальный запрос к API МАХ через прокси"""
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
              # ← ПРОКСИ
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

def send_message(user_id, text, parse_mode="Markdown"):
    """Отправка сообщения в МАХ (использует user_id)"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        payload = {
            "user_id": user_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        logger.info(f"📤 Отправка user_id={user_id}")
        logger.info(f"📦 Пейлоад: {json.dumps(payload, ensure_ascii=False)[:200]}")
        
        response = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30,
              # ← ПРОКСИ
            verify=False
        )
        
        logger.info(f"📤 Ответ: {response.status_code} - {response.text[:200]}")
        
        if response.status_code == 200:
            return True
            
        if response.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "user_id": user_id,
                "text": text
            }
            response2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=30,
                  # ← ПРОКСИ
                verify=False
            )
            logger.info(f"📤 Ответ без parse_mode: {response2.status_code} - {response2.text[:200]}")
            return response2.status_code == 200
            
        return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def send_keyboard(user_id, text, buttons):
    """Отправка клавиатуры в МАХ (использует user_id)"""
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
            "user_id": user_id,
            "text": text,
            "parse_mode": "Markdown",
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {
                    "buttons": keyboard_rows
                }
            }]
        }

        logger.info(f"📤 Отправка клавиатуры user_id={user_id}")
        logger.info(f"📦 Пейлоад: {json.dumps(payload, ensure_ascii=False)[:300]}")

        response = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30,
              # ← ПРОКСИ
            verify=False
        )
        
        logger.info(f"📤 Ответ: {response.status_code} - {response.text[:200]}")
        
        if response.status_code == 200:
            logger.info("✅ Клавиатура отправлена!")
            return True
        
        if response.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "user_id": user_id,
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
                  # ← ПРОКСИ
                verify=False
            )
            logger.info(f"📤 Ответ без parse_mode: {response2.status_code} - {response2.text[:200]}")
            
            if response2.status_code == 200:
                return True
        
        logger.info("🔄 Отправляю обычное сообщение...")
        return send_message(user_id, text)
        
    except Exception as e:
        logger.error(f"❌ Ошибка клавиатуры: {e}")
        return False

def show_main_menu(user_id):
    """Главное меню"""
    send_keyboard(
        user_id,
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
    return {
        "token": "✅" if TOKEN else "❌",
        "token_preview": f"{TOKEN[:4]}...{TOKEN[-4:]}" if TOKEN else None,
        "certificate": {
            "found": USE_CERT,
            "path": CERT_PATH,
            "exists": os.path.exists(CERT_PATH) if CERT_PATH else False
        }
    }, 200

@app.route('/test_proxy')
def test_proxy():
    """Тест прокси с API MAX"""
    try:
        headers = {
            "Authorization": TOKEN,
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            "https://platform-api2.max.ru/subscriptions",
            headers=headers,
            
            timeout=10,
            verify=False
        )
        
        return {
            "proxy_ip": "92.242.8.114:8080",
            "status": response.status_code,
            "response": response.text[:200],
            "note": "Если статус 200 — прокси работает с API MAX"
        }
    except Exception as e:
        return {"error": str(e)}

@app.route('/setup_webhook')
def setup_webhook():
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
            <p><b>📁 Сертификат:</b> {'✅ Найден' if USE_CERT else '❌ Не найден (отключен)'}</p>
            <p><b>📂 Путь:</b> {CERT_PATH if CERT_PATH else 'Не указан'}</p>
            <p><b>🔑 Токен:</b> {token[:4]}...{token[-4:] if len(token) > 8 else '***'}</p>
            <p><b>🌐 Вебхук:</b> {webhook_url}</p>
            <p><b>📌 Формат авторизации:</b> Authorization: &lt;token&gt; (без Bearer)</p>
            <hr>
    """
    
    try:
        headers = {
            "Authorization": token,
            "Content-Type": "application/json"
        }
        
        # 1. Удаляем старую подписку
        html += "<h3>🗑️ Удаление старой подписки...</h3>"
        try:
            r_del = requests.delete(
                "https://platform-api2.max.ru/subscriptions",
                headers=headers,
                timeout=10,
                
                verify=False
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
            
            verify=False
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
        <p><a href="/health">✅ Проверить здоровье</a> | <a href="/debug">🔍 Отладка</a> | <a href="/test_proxy">🧪 Тест прокси</a></p>
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
    """Обработка вебхука от МАХ (использует user_id)"""
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id = None
        text = None
        
        # Извлекаем данные из структуры МАХ
        if 'message' in data:
            message = data['message']
            
            # Извлекаем user_id из sender
            if 'sender' in message:
                sender = message['sender']
                user_id = sender.get('user_id')
            
            # Если не нашли - ищем в recipient
            if not user_id and 'recipient' in message:
                recipient = message['recipient']
                user_id = recipient.get('user_id')
            
            # Извлекаем текст
            if 'body' in message:
                body = message['body']
                text = body.get('text')
        
        # Если не нашли - рекурсивный поиск
        if not user_id:
            def search(obj):
                nonlocal user_id, text
                if isinstance(obj, dict):
                    if "user_id" in obj and user_id is None:
                        user_id = obj["user_id"]
                    if "text" in obj and text is None:
                        text = obj["text"]
                    for value in obj.values():
                        search(value)
                elif isinstance(obj, list):
                    for item in obj:
                        search(item)
            search(data)
        
        if not user_id:
            logger.warning("⚠️ Не удалось найти user_id")
            logger.info(f"📦 Данные: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text='{text}'")

        # Обработка команд
        if text and isinstance(text, str):
            text_lower = text.lower().strip()
            
            if text_lower in ["/start", "start"]:
                show_main_menu(user_id)
                return jsonify({"ok": True}), 200

            if text_lower == "/help":
                send_message(
                    user_id,
                    "📖 **Помощь**\n\nКоманды:\n/start - Главное меню\n/choose - Выбрать папку\n/publish - Начать публикацию\n/stop - Остановить\n/help - Справка"
                )
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
