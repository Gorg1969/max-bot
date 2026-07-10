from flask import Flask, request, jsonify
import requests
import logging
import os
import urllib3
import re
from modules import Database, FileManager, Publisher, WebInterface

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 * 2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

db = Database()
fm = FileManager(DATA_DIR)

class APIClient:
    def __init__(self):
        self.token = TOKEN
    
    def send_message(self, user_id, text):
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{BASE_URL}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"user_id": user_id},
                json=payload,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def send_message_to_chat(self, chat_id, text):
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{BASE_URL}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"chat_id": chat_id},
                json=payload,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False
    
    def send_message_to_chat_with_attachments(self, chat_id, text, attachments):
        try:
            payload = {
                "text": text,
                "format": "markdown",
                "attachments": attachments
            }
            response = requests.post(
                f"{BASE_URL}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"chat_id": chat_id},
                json=payload,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки с вложениями: {e}")
            return False

api = APIClient()
publisher = Publisher(api, fm, db)
web = WebInterface(fm, publisher)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def extract_file_id_from_url(url):
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'([a-zA-Z0-9_-]{28,})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_file_from_drive(file_id, save_path):
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(url, stream=True, timeout=300)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    return False

def process_google_drive_link(user_id, url):
    api.send_message(user_id, "📥 Получил ссылку. Начинаю обработку...")
    
    file_id = extract_file_id_from_url(url)
    if not file_id:
        api.send_message(user_id, "❌ Не удалось извлечь ID файла из ссылки.")
        return
    
    user_folder = fm.get_user_folder(user_id)
    zip_path = os.path.join(user_folder, 'temp.zip')
    
    api.send_message(user_id, "⏳ Скачивание файла... (до 5 минут)")
    if download_file_from_drive(file_id, zip_path):
        size = os.path.getsize(zip_path)
        api.send_message(user_id, f"✅ Файл скачан: {size // 1024 // 1024} МБ")
        
        api.send_message(user_id, "📦 Распаковка архива...")
        if fm.extract_zip(user_id, zip_path):
            os.remove(zip_path)
            api.send_message(user_id, "✅ Архив распакован. Начинаю публикацию...")
            publisher.start(user_id)
        else:
            api.send_message(user_id, "❌ Ошибка распаковки архива.")
            fm.clear_user_data(user_id)
    else:
        api.send_message(user_id, "❌ Не удалось скачать файл. Проверьте ссылку.")

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'GET':
        return web.upload_page()
    
    try:
        user_id = 151296248
        result = web.upload_file(request, user_id)
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500

@app.route('/health')
def health():
    return {"status": "ok"}

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
        
        if 'message' in data:
            msg = data['message']
            if 'sender' in msg:
                user_id = msg['sender'].get('user_id')
            if 'body' in msg:
                text = msg['body'].get('text')
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text={text}")

        if text and text.strip() == '/start':
            api.send_message(
                user_id,
                "🏠 **Главное меню**\n\n"
                "📤 **Загрузите архив:**\n"
                "1. Загрузите ZIP-архив на Google Drive.\n"
                "2. Откройте доступ 'Всем, у кого есть ссылка'.\n"
                "3. Скопируйте ссылку и отправьте боту.\n\n"
                "📌 Бот скачает архив и начнёт публикацию.\n"
                "⏹ Для остановки публикации отправьте `/stop`"
            )
            return jsonify({"ok": True}), 200

        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200

        if text and 'drive.google.com' in text:
            process_google_drive_link(user_id, text)
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
