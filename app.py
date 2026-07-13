from flask import Flask, request, jsonify, render_template_string
import requests
import logging
import os
import shutil
import urllib3
import json
import time
from modules import Database, FileManager, Publisher, WebInterface

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 * 2  # 2 ГБ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ ==========
db = Database()
fm = FileManager(DATA_DIR)

class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL

    def send_message(self, user_id, text, attachments=None):
        """Отправляет сообщение пользователю"""
        try:
            payload = {"text": text, "format": "markdown"}
            if attachments:
                payload["attachments"] = attachments
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"user_id": user_id},
                json=payload,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Отправка сообщения пользователю {user_id}, статус: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"❌ Ошибка отправки: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def send_message_to_chat(self, chat_id, text):
        """Отправляет сообщение в чат по ID группы (с дефисом)"""
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"chat_id": chat_id},
                json=payload,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Отправка сообщения в чат {chat_id}, статус: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"❌ Ошибка отправки в чат: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False

    def send_photos_to_chat(self, chat_id, photo_files, text=None, caption=None):
        """
        Отправляет фото в чат вместе с текстом объявления.
        Отправляем каждое фото отдельно: первое с текстом, остальные без текста
        """
        try:
            if not photo_files:
                return self.send_message_to_chat(chat_id, text or caption or "")
            
            success = True
            
            for i, (filename, data) in enumerate(photo_files):
                # Подготавливаем файл
                files = [('file', (filename, data, 'image/jpeg'))]
                
                # Подготавливаем данные
                if i == 0:
                    # Первое фото отправляем с текстом
                    form_data = {
                        "chat_id": chat_id,
                        "text": text or caption or "",
                        "format": "markdown"
                    }
                else:
                    # Остальные фото отправляем без текста (или с минимальным)
                    form_data = {
                        "chat_id": chat_id
                    }
                
                # Отправляем запрос с файлом
                response = requests.post(
                    f"{self.base_url}/messages",
                    headers={"Authorization": self.token},
                    data=form_data,
                    files=files,
                    timeout=60,
                    verify=False
                )
                
                logger.info(f"📤 Отправка фото {i+1}/{len(photo_files)} в чат {chat_id}, статус: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"❌ Ошибка отправки фото {i+1}: {response.text[:300]}")
                    success = False
                    break
                
                # Задержка между отправками (чтобы не было флуда)
                if i < len(photo_files) - 1:
                    time.sleep(1)
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

api = APIClient()
publisher = Publisher(api, fm, db)
web = WebInterface(fm, publisher)

# ========== ХРАНИЛИЩЕ ДЛЯ ВРЕМЕННЫХ ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ==========
user_temp_data = {}

# ========== HTML СТРАНИЦА ДЛЯ ЗАГРУЗКИ ПАПКИ ==========
UPLOAD_PAGE = """... (оставляем без изменений) ..."""

# ========== ФУНКЦИЯ ДЛЯ ОТПРАВКИ КНОПОК ==========
def send_confirmation_buttons(user_id):
    """Отправляет кнопки подтверждения в MAX"""
    try:
        attachments = [{
            "type": "keyboard",
            "buttons": [
                [
                    {
                        "text": "✅ Да, публиковать",
                        "payload": json.dumps({"action": "confirm_publish", "user_id": user_id})
                    },
                    {
                        "text": "❌ Нет, отменить",
                        "payload": json.dumps({"action": "cancel_publish", "user_id": user_id})
                    }
                ]
            ]
        }]
        
        payload = {
            "text": "Выберите действие:",
            "format": "markdown",
            "attachments": attachments
        }
        
        response = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            params={"user_id": user_id},
            json=payload,
            timeout=30,
            verify=False
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Кнопки отправлены пользователю {user_id}")
            return True
        else:
            logger.error(f"❌ Ошибка отправки кнопок: {response.text}")
            send_text_fallback(user_id)
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки кнопок: {e}")
        send_text_fallback(user_id)
        return False

def send_text_fallback(user_id):
    """Отправляет текстовое сообщение вместо кнопок"""
    api.send_message(
        user_id,
        "⚠️ Кнопки временно недоступны. Пожалуйста, напишите:\n"
        "• `Да` - чтобы начать публикацию\n"
        "• `Нет` - чтобы отменить"
    )

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    """Страница загрузки папки"""
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_folder', methods=['POST'])
def upload_folder():
    """Обработка загрузки папки с поиском info.txt в подпапках"""
    # ... (оставляем без изменений) ...

@app.route('/webhook', methods=['POST'])
def webhook():
    # ... (оставляем без изменений) ...

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/setup_webhook')
def setup_webhook():
    # ... (оставляем без изменений) ...

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
