from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
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
    
    def send_photo(self, group_id, image_data, caption=None):
        """Отправка изображения"""
        try:
            # Здесь нужно использовать multipart/form-data
            # Это пример, требует доработки
            files = {'file': ('image.jpg', image_data, 'image/jpeg')}
            data = {'caption': caption} if caption else {}
            response = requests.post(
                f"{self.base_url}/messages",
                headers=self.get_headers(),
                params={"chat_id": group_id},
                data=data,
                files=files,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            return False

api_client = MaxAPIClient()

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
    """Обработка вебхука от МАХ"""
    try:
        data = request.get_json()
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id = None
        text = None
        payload = None
        
        # ========== ОБРАБОТКА CALLBACK ==========
        if 'callback' in data:
            callback = data['callback']
            payload = callback.get('payload')
            if 'user' in callback:
                user_id = callback['user'].get('user_id')
        
        # ========== ОБРАБОТКА СООБЩЕНИЯ ==========
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
                user_state.set_state(user_id, 'waiting_folder')
                api_client.send_message(user_id, "📁 **Введите ссылку на корневую папку Google Drive:**\n\nПример: `https://drive.google.com/drive/folders/ABC123`")
            elif payload == "start_publish":
                api_client.send_message(user_id, "▶️ Начинаю публикацию... (выберите папку через /choose)")
            elif payload == "stop":
                api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            elif payload == "help":
                show_help(user_id)
            return jsonify({"ok": True}), 200

        # ========== ОБРАБОТКА КОМАНД ==========
        if text:
            text_lower = text.lower().strip()
            
            if text_lower == "/start":
                show_main_menu(user_id)
            
            elif text_lower == "/choose":
                user_state.set_state(user_id, 'waiting_folder')
                api_client.send_message(user_id, "📁 **Введите ссылку на корневую папку Google Drive:**\n\nПример: `https://drive.google.com/drive/folders/ABC123`")
            
            elif text_lower == "/stop":
                api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            
            elif text_lower == "/help":
                show_help(user_id)
            
            elif user_state.get_state(user_id) == 'waiting_folder':
                # Пользователь ввёл ссылку на папку
                folder_url = text
                user_state.clear_state(user_id)
                
                # Здесь нужны credentials пользователя
                # Пока используем заглушку
                api_client.send_message(user_id, "✅ Папка получена. Начинаю публикацию...")
                
                # В реальности нужно получать credentials от пользователя
                # Сейчас используем заглушку
                storage = GoogleDriveStorage(user_id, credentials=None)  # Нужны реальные credentials
                publisher = Publisher(user_id, storage, api_client, scheduler)
                publisher.start_publication(folder_url)

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

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
    # Отправка клавиатуры
    api_client.send_message(user_id, keyboard['text'], 'markdown')

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

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
