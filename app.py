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
    """Универсальный поиск сертификата Минцифры в разных форматах"""
    base_dir = os.path.dirname(__file__)
    
    # Проверяем конкретные имена
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
    
    # Ищем любой файл с 'russian'
    try:
        for file in os.listdir(base_dir):
            if 'russian' in file.lower() and file.endswith(('.cer', '.pem', '.crt')):
                path = os.path.join(base_dir, file)
                logger.info(f"Найден сертификат: {file}")
                return path
    except Exception as e:
        logger.warning(f"Ошибка поиска: {e}")
    
    # Проверяем папку certs
    certs_dir = os.path.join(base_dir, 'certs')
    if os.path.exists(certs_dir):
        try:
            for file in os.listdir(certs_dir):
                if 'russian' in file.lower() and file.endswith(('.cer', '.pem', '.crt')):
                    path = os.path.join(certs_dir, file)
                    logger.info(f"Найден сертификат в certs/: {file}")
                    return path
        except Exception as e:
            logger.warning(f"Ошибка поиска в certs/: {e}")
    
    logger.warning("Сертификат Минцифры НЕ НАЙДЕН!")
    return None

# Находим сертификат
CERT_PATH = find_certificate()
USE_CERT = CERT_PATH is not None

if USE_CERT:
    logger.info(f"Сертификат загружен: {CERT_PATH}")
else:
    logger.warning("Сертификат не найден! Используется стандартная проверка")

# ========== ФУНКЦИИ ==========

def get_headers():
    """Получение правильных заголовков с Bearer токеном"""
    if not TOKEN:
        logger.error("ТОКЕН НЕ УСТАНОВЛЕН!")
        return None
    
    return {
        "Authorization": f"Bearer {TOKEN}",
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
            
        logger.info(f"Отправка в chat_id={chat_id}")
        
        r = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        logger.info(f"Ответ: {r.status_code}")
        
        if r.status_code == 200:
            return True
            
        if r.status_code == 400:
            logger.info("Пробую без parse_mode...")
            payload2 = {
                "chat_id": chat_id,
                "text": text
            }
            r2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=10,
                verify=CERT_PATH if USE_CERT else False
            )
            
            if r2.status_code == 200:
                return True
            
            return False
            
        return False
            
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return False

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
