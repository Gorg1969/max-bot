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

# ========== УНИВЕРСАЛЬНЫЙ ПОИСК СЕРТИФИКАТА ==========
def find_certificate():
    """Универсальный поиск сертификата Минцифры"""
    base_dir = os.path.dirname(__file__)
    
    cert_names = [
        'russian_trusted_root_ca_gost_2025',
        'russian_trusted_root_ca_gost_2025.cer',
        'russian_trusted_root_ca_gost_2025.pem',
        'russian_trusted_root_ca_gost_2025.crt',
    ]
    
    for name in cert_names:
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            logger.info(f"Найден сертификат: {name}")
            return path
    
    try:
        for file in os.listdir(base_dir):
            if 'russian' in file.lower() and file.endswith(('.cer', '.pem', '.crt')):
                path = os.path.join(base_dir, file)
                logger.info(f"Найден сертификат: {file}")
                return path
    except:
        pass
    
    certs_dir = os.path.join(base_dir, 'certs')
    if os.path.exists(certs_dir):
        try:
            for file in os.listdir(certs_dir):
                if 'russian' in file.lower() and file.endswith(('.cer', '.pem', '.crt')):
                    path = os.path.join(certs_dir, file)
                    logger.info(f"Найден сертификат в certs/: {file}")
                    return path
        except:
            pass
    
    logger.warning("Сертификат Минцифры НЕ НАЙДЕН!")
    return None

# Временное решение - принудительно отключаем сертификат
CERT_PATH = None
USE_CERT = False

if USE_CERT:
    logger.info(f"Сертификат загружен: {CERT_PATH}")
else:
    logger.warning("Сертификат не найден! Используется стандартная проверка")

# ========== ФУНКЦИИ ==========

def get_headers():
    if not TOKEN:
        logger.error("ТОКЕН НЕ УСТАНОВЛЕН!")
        return None
    
    return {
        "Authorization": f"Bearer {TOKEN}",
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
            
        r = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r.status_code == 200:
            return True
            
        if r.status_code == 400:
            # Пробуем без parse_mode
            payload2 = {"chat_id": chat_id, "text": text}
            r2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=10,
                verify=CERT_PATH if USE_CERT else False
            )
            return r2.status_code == 200
            
        return False
    except Exception as e:
        logger.error(f"Ошибка: {e}")
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

        r = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r.status_code == 200:
            return True
        
        # Пробуем без parse_mode
        payload2 = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard_rows}
            }]
        }
        
        r2 = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload2,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        return r2.status_code == 200
    except Exception as e:
        logger.error(f"Ошибка: {e}")
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
    return "Bot is running!", 200

@app.route('/health')
def health():
    return {
        "status": "ok",
        "time": time.strftime('%Y-%m-%d %H:%M:%S'),
        "certificate": {
            "found": USE_CERT,
            "path": CERT_PATH
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

# ⭐ НОВЫЙ ЭНДПОИНТ ДЛЯ НАСТРОЙКИ ВЕБХУКА
@app.route('/setup_webhook')
def setup_webhook():
    """Настройка вебхука через браузер"""
    token = request.args.get('token')
    
    if not token:
        return "❌ Ошибка: не передан токен.<br>Используйте: <b>/setup_webhook?token=ВАШ_ТОКЕН</b>", 400
    
    webhook_url = "https://max-bot-ulzl.onrender.com/webhook"
    base_url = "https://platform-api2.max.ru"
    
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Удаляем старую подписку
        result = "<b>🗑️ Удаление старой подписки...</b><br>"
        try:
            r_del = requests.delete(
                f"{base_url}/subscriptions",
                headers=headers,
                timeout=10,
                verify=CERT_PATH if USE_CERT else False
            )
            result += f"DELETE: {r_del.status_code}<br>"
            if r_del.status_code == 200:
                result += "✅ Старая подписка удалена<br>"
        except Exception as e:
            result += f"⚠️ Ошибка DELETE: {e}<br>"
        
        # Создаем новую подписку
        result += "<br><b>📝 Создание новой подписки...</b><br>"
        r = requests.post(
            f"{base_url}/subscriptions",
            headers=headers,
            json={"url": webhook_url},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        result += f"POST: {r.status_code}<br>"
        result += f"Ответ: {r.text[:200]}<br>"
        
        if r.status_code == 200:
            result += "✅ <b>ВЕБХУК УСПЕШНО НАСТРОЕН!</b><br>"
            result += f"🌐 Вебхук: {webhook_url}"
        else:
            result += f"❌ Ошибка: {r.text[:200]}"
        
        return f"<html><body style='font-family: monospace; padding: 20px;'>{result}</body></html>"
        
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("Получен вебхук")
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
