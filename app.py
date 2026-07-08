from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import re
import urllib3
from modules import GoogleDriveStorage, Publisher, Scheduler, UserState

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ ==========
scheduler = Scheduler(delay=120, batch_size=10, batch_pause=300)
user_state = UserState()

# ========== API КЛИЕНТ ДЛЯ MAX ==========
class MaxAPIClient:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = TOKEN
    
    def get_headers(self):
        return {
            "Authorization": self.token,
            "Content-Type": "application/json"
        }
    
    def send_message(self, user_id, text, format="markdown"):
        """Отправка сообщения"""
        try:
            payload = {"text": text, "format": format}
            response = requests.post(
                f"{self.base_url}/messages",
                headers=self.get_headers(),
                params={"user_id": user_id},
                json=payload,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

api_client = MaxAPIClient()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def extract_folder_id_from_url(url: str) -> str:
    """Извлечение folder_id из ссылки Google Drive"""
    patterns = [
        r'folders/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'drive.google.com/open\?id=([a-zA-Z0-9_-]+)',
        r'([a-zA-Z0-9_-]{28,})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

# ========== МЕНЮ ==========

def show_main_menu(user_id):
    """Главное меню"""
    keyboard = {
        "text": "🏠 **Главное меню**\n\nВыберите действие:",
        "format": "markdown",
        "attachments": [{
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [{"text": "📂 Выбрать папку", "type": "callback", "payload": "choose_folder"}],
                    [{"text": "▶️ Начать публикацию", "type": "callback", "payload": "start_publish"}],
                    [{"text": "⏹ Остановить", "type": "callback", "payload": "stop"}],
                    [{"text": "ℹ️ Помощь", "type": "callback", "payload": "help"}]
                ]
            }
        }]
    }
    response = requests.post(
        f"{BASE_URL}/messages",
        headers=api_client.get_headers(),
        params={"user_id": user_id},
        json=keyboard,
        timeout=30,
        verify=False
    )

def show_folder_menu(user_id):
    """Меню выбора папки — поле для ввода ссылки"""
    keyboard = {
        "text": (
            "📂 **Выбор папки**\n\n"
            "Вставьте ссылку на **корневую папку** Google Drive.\n\n"
            "**Важно:**\n"
            "✅ Папка должна быть доступна для чтения и записи.\n"
            "✅ Внутри папки должны быть подпапки с объявлениями.\n"
            "✅ Название подпапки должно содержать ID группы.\n"
            "   Пример: `Самосвалы 8 -76576474415864`\n\n"
            "📎 **Пример ссылки:**\n"
            "`https://drive.google.com/drive/folders/ABC123XYZ`"
        ),
        "format": "markdown",
        "attachments": [{
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [{"text": "🔙 Назад", "type": "callback", "payload": "back"}],
                    [{"text": "🏠 В меню", "type": "callback", "payload": "main_menu"}]
                ]
            }
        }]
    }
    
    response = requests.post(
        f"{BASE_URL}/messages",
        headers=api_client.get_headers(),
        params={"user_id": user_id},
        json=keyboard,
        timeout=30,
        verify=False
    )
    
    user_state.set_state(user_id, 'waiting_folder_link')

def show_help(user_id):
    help_text = (
        "📖 **Помощь**\n\n"
        "📂 /choose - Выбрать папку\n"
        "▶️ /start - Главное меню\n"
        "⏹ /stop - Остановить публикацию\n"
        "ℹ️ /help - Справка\n\n"
        "**Как это работает:**\n"
        "1. Создайте корневую папку на Google Drive.\n"
        "2. Внутри создайте подпапки с названием: `Название -123456789`.\n"
        "3. В каждой подпапке: до 10 изображений и файл `info.txt`.\n"
        "4. Отправьте боту ссылку на корневую папку.\n"
        "5. Бот автоматически опубликует всё с задержками."
    )
    api_client.send_message(user_id, help_text)

# ========== ЭНДПОИНТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!", 200

@app.route('/health')
def health():
    return {
        "status": "ok",
        "time": time.strftime('%Y-%m-%d %H:%M:%S'),
        "scheduler": scheduler.get_status()
    }, 200

@app.route('/setup_webhook')
def setup_webhook():
    token = request.args.get('token') or TOKEN
    if not token:
        return "❌ Токен не найден", 400
    
    webhook_url = "https://maxbot.bothost.tech/webhook"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    
    try:
        r = requests.post(
            "https://platform-api2.max.ru/subscriptions",
            headers=headers,
            json={"url": webhook_url},
            timeout=10,
            verify=False
        )
        return f"✅ Вебхук настроен: {r.status_code}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id = None
        text = None
        payload = None
        
        if 'callback' in data:
            callback = data['callback']
            payload = callback.get('payload')
            if 'user' in callback:
                user_id = callback['user'].get('user_id')
        
        elif 'message' in data:
            message = data['message']
            if 'sender' in message:
                user_id = message['sender'].get('user_id')
            if 'body' in message:
                text = message['body'].get('text')
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text='{text}', payload='{payload}'")

        # ========== ОБРАБОТКА КНОПОК ==========
        if payload:
            if payload == "choose_folder":
                show_folder_menu(user_id)
            elif payload == "start_publish":
                api_client.send_message(user_id, "▶️ Начинаю публикацию...")
            elif payload == "stop":
                api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            elif payload == "help":
                show_help(user_id)
            elif payload == "back":
                show_main_menu(user_id)
            elif payload == "main_menu":
                show_main_menu(user_id)
            else:
                # ❌ НЕ ОТПРАВЛЯЕМ СООБЩЕНИЕ ДЛЯ НЕИЗВЕСТНЫХ КНОПОК
                logger.info(f"🔘 Неизвестный payload: {payload}")
                pass
            
            return jsonify({"ok": True}), 200

        # ========== ОБРАБОТКА КОМАНД ==========
        if text:
            text_lower = text.lower().strip()
            
            if text_lower == "/start":
                show_main_menu(user_id)
            
            elif text_lower == "/choose":
                show_folder_menu(user_id)
            
            elif text_lower == "/stop":
                api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            
            elif text_lower == "/help":
                show_help(user_id)
            
            elif user_state.get_state(user_id) == 'waiting_folder_link':
                # Пользователь ввёл ссылку
                folder_url = text.strip()
                user_state.clear_state(user_id)
                
                if not folder_url.startswith('https://drive.google.com/'):
                    api_client.send_message(
                        user_id,
                        "❌ **Неверная ссылка!**\n\n"
                        "Ссылка должна начинаться с:\n"
                        "`https://drive.google.com/`\n\n"
                        "Попробуйте ещё раз."
                    )
                    show_folder_menu(user_id)
                    return jsonify({"ok": True}), 200
                
                folder_id = extract_folder_id_from_url(folder_url)
                if not folder_id:
                    api_client.send_message(
                        user_id,
                        "❌ **Не удалось извлечь ID папки.**\n\n"
                        "Убедитесь, что ссылка правильная.\n"
                        "Пример: `https://drive.google.com/drive/folders/ABC123XYZ`"
                    )
                    show_folder_menu(user_id)
                    return jsonify({"ok": True}), 200
                
                api_client.send_message(
                    user_id,
                    f"✅ **Папка принята!**\n\n"
                    f"📁 ID: `{folder_id}`\n"
                    f"⏳ Начинаю сканирование..."
                )
                
                # Запускаем публикацию
                storage = GoogleDriveStorage(user_id, credentials=None)
                publisher = Publisher(user_id, storage, api_client, scheduler)
                publisher.start_publication(folder_url)

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
