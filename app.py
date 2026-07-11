from flask import Flask, request, jsonify, session
import requests
import logging
import os
import urllib3
from modules import Database, FileManager, Publisher, WebInterface
from modules.process_links import process_google_drive_link, download_file_from_drive

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

# ========== ОБРАБОТКА ССЫЛКИ НА GOOGLE DRIVE ==========

@app.route('/process_drive_link', methods=['POST'])
def process_drive_link():
    """Обработка ссылки на Google Drive (поддержка больших файлов 200+ МБ)"""
    try:
        data = request.get_json()
        url = data.get('url')
        user_id = int(data.get('user_id', 151296248))
        
        if not url:
            return jsonify({'success': False, 'message': 'Ссылка не передана'}), 400
        
        logger.info(f"📥 Получена ссылка: {url}")
        
        # Получаем папку пользователя
        user_folder = fm.get_user_folder(user_id)
        zip_path = os.path.join(user_folder, 'temp.zip')
        
        # 🔥 ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ С ПОДДЕРЖКОЙ БОЛЬШИХ ФАЙЛОВ
        try:
            # Пытаемся скачать через новую функцию
            file_path = process_google_drive_link(url, download_dir=user_folder)
            
            # Если файл скачался под другим именем, переименовываем в temp.zip
            if file_path != zip_path:
                # Если temp.zip уже существует, удаляем
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                os.rename(file_path, zip_path)
            
            # Проверяем, что файл существует
            if not os.path.exists(zip_path):
                raise Exception("Файл не был скачан")
            
            # Проверяем размер
            size = os.path.getsize(zip_path)
            logger.info(f"✅ Файл скачан: {size // 1024 // 1024} МБ")
            
            # Распаковываем
            if fm.extract_zip(user_id, zip_path):
                os.remove(zip_path)
                publisher.start(user_id)
                return jsonify({'success': True, 'message': 'Архив загружен и обработан. Публикация началась!'})
            else:
                fm.clear_user_data(user_id)
                return jsonify({'success': False, 'message': 'Ошибка распаковки архива'}), 500
                
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания: {e}")
            return jsonify({'success': False, 'message': f'Не удалось скачать файл: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ссылки: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

# ========== ОСТАЛЬНЫЕ МАРШРУТЫ ==========

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
                "🌐 **Загрузите архив через веб-интерфейс:**\n"
                f"🔗 `https://maxbot.bothost.tech/upload`\n\n"
                "📌 **Требования к архиву:**\n"
                "• Формат: `.zip`\n"
                "• Внутри папки с ID групп: `Название -123456789`\n"
                "• В каждой папке: `info.txt` и изображения\n\n"
                "⏹ Для остановки публикации отправьте `/stop`"
            )
            return jsonify({"ok": True}), 200

        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
