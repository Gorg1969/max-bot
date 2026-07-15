from flask import Flask, request, jsonify, render_template_string, send_file
import requests
import logging
import os
import shutil
import urllib3
import json
import threading
import time
from werkzeug.exceptions import ClientDisconnected
from modules import Database, FileManager, Publisher, WebInterface
from modules.report_generator import ReportGenerator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 МБ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

db = Database()
fm = FileManager(DATA_DIR)

# ========== APIClient ==========
class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL

    def send_message(self, user_id, text, attachments=None):
        if not self.token:
            return False
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
            if response.status_code != 200:
                logger.error(f"❌ Ошибка отправки: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def send_message_to_chat(self, chat_id, text):
        if not self.token:
            return False
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
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False

    def upload_file_to_max(self, file_data, filename):
        """
        Загружает файл на сервер MAX через /uploads
        Возвращает token для использования в сообщении
        """
        try:
            ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
            file_type = 'image'
            
            # ШАГ 1: Получаем URL для загрузки
            logger.info(f"📤 Запрос URL для загрузки: {filename}")
            response = requests.post(
                f"{self.base_url}/uploads",
                headers={"Authorization": self.token},
                params={"type": file_type},
                timeout=(10, 30),
                verify=False
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения URL: {response.status_code} - {response.text}")
                return None
            
            upload_data = response.json()
            upload_url = upload_data.get('url')
            
            if not upload_url:
                logger.error("❌ Не получен URL для загрузки")
                return None
            
            logger.info(f"📤 URL для загрузки получен")
            
            # ШАГ 2: Загружаем файл
            files = {'file': (filename, file_data, 'image/jpeg')}
            response = requests.post(
                upload_url,
                files=files,
                timeout=(30, 120),
                verify=False
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка загрузки файла: {response.status_code} - {response.text}")
                return None
            
            result = response.json()
            
            # ПРАВИЛЬНЫЙ ПАРСИНГ ТОКЕНА
            token = None
            
            # Вариант 1: token в корне
            if 'token' in result:
                token = result['token']
                logger.info(f"✅ Токен найден в корне ответа")
            # Вариант 2: token внутри photos
            elif 'photos' in result:
                photos = result['photos']
                for key, value in photos.items():
                    if isinstance(value, dict) and 'token' in value:
                        token = value['token']
                        logger.info(f"✅ Токен найден в photos[{key}]['token']")
                        break
            
            if token:
                logger.info(f"✅ Файл загружен, token получен: {token[:20]}...")
                return token
            else:
                logger.error(f"❌ Не найден token в ответе: {result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки файла: {e}")
            return None

    def send_photos_to_chat(self, chat_id, photo_files, text=None, caption=None):
        """
        Отправляет фото в чат через двухэтапную загрузку
        photo_files: список кортежей (filename, binary_data)
        """
        if not self.token:
            logger.error("❌ Токен не установлен!")
            return False
        
        try:
            attachments = []
            total = len(photo_files)
            
            for i, (filename, data) in enumerate(photo_files):
                logger.info(f"📤 Загрузка фото {i+1}/{total}: {filename} ({len(data)} байт)")
                token = self.upload_file_to_max(data, filename)
                if token:
                    attachments.append({
                        "type": "image",
                        "payload": {"token": token}
                    })
                    logger.info(f"✅ Фото {i+1} загружено")
                else:
                    logger.warning(f"⚠️ Не удалось загрузить {filename}")
            
            if not attachments:
                logger.error("❌ Нет загруженных файлов для отправки")
                # Если нет фото - отправляем только текст
                if text:
                    return self.send_message_to_chat(chat_id, text)
                return False
            
            # ОТПРАВЛЯЕМ JSON
            payload = {
                "chat_id": chat_id,
                "text": text or "",
                "format": "markdown",
                "attachments": attachments
            }
            
            logger.info(f"📤 Отправка сообщения с {len(attachments)} фото в чат {chat_id}")
            
            response = requests.post(
                f"{self.base_url}/messages",
                headers={
                    "Authorization": self.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60,
                verify=False
            )
            
            logger.info(f"📊 Статус ответа: {response.status_code}")
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение с {len(attachments)} фото отправлено")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {response.status_code}")
                logger.error(f"❌ Ответ сервера: {response.text[:500]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            import traceback
            traceback.print_exc()
            return False

api = APIClient()
publisher = Publisher(api, fm, db)
report_gen = ReportGenerator(fm, db)

# ========== HTML СТРАНИЦА (СОКРАЩЕНА ДЛЯ ЭКОНОМИИ МЕСТА) ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-top: 0; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; text-align: center; cursor: pointer; transition: all 0.3s; }
        .drop-zone:hover { background: #e3f2fd; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        .drop-zone p { margin: 0; color: #666; }
        .drop-zone .icon { font-size: 48px; display: block; margin-bottom: 10px; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; transition: all 0.3s; }
        .btn-primary { background: #007bff; color: white; }
        .btn-primary:hover { background: #0056b3; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .file-list { text-align: left; margin: 20px 0; padding: 0; list-style: none; }
        .file-list li { background: #f8f9fa; padding: 10px 15px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #007bff; color: white; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; }
        .instructions { background: #fff3cd; padding: 15px 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 3px; font-size: 14px; color: #d63384; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; line-height: 1.5; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }
        .selected-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте головную папку (любое название)<br>
            2️⃣ Внутри создайте подпапки объявлений: <code>1 -123456789</code><br>
            3️⃣ В каждой подпапке: <code>info.txt</code> и фото<br>
            4️⃣ Перетащите головную папку в поле ниже
        </div>
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите папку сюда</strong></p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <ul class="file-list" id="fileListContent"></ul>
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
                <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
            </div>
        </div>
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        <div id="status" class="status"></div>
        <div id="log"></div>
        <div class="footer">⚡ MAX Bot | Загрузка объявлений</div>
    </div>
    <script>
        let selectedFiles = [];
        let userId = 151296248;
        const CHUNK_SIZE = 1;
        const RETRY_DELAY = 1000;
        const MAX_WIDTH = 800;
        const QUALITY = 0.6;
        // ... (остальной JS код из предыдущей версии)
    </script>
</body>
</html>
"""

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    try:
        if 'files[]' not in request.files:
            return jsonify({'success': False, 'message': 'Файлы не найдены'}), 400
        
        files = request.files.getlist('files[]')
        if not files:
            return jsonify({'success': False, 'message': 'Файлы не выбраны'}), 400
        
        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'user_id не указан'}), 400
        
        try:
            user_id = int(user_id)
        except ValueError:
            return jsonify({'success': False, 'message': 'Неверный user_id'}), 400
        
        append = request.form.get('append', 'false').lower() == 'true'
        chunk_num = request.form.get('chunk_num', '1')
        total_chunks = request.form.get('total_chunks', '1')
        
        logger.info(f"📦 Пачка {chunk_num}/{total_chunks}: {len(files)} файлов")
        
        result = fm.save_uploaded_files_stream(files, user_id, append=append)
        
        if not result['success']:
            return jsonify({'success': False, 'message': result.get('error', 'Ошибка сохранения')}), 500
        
        return jsonify({
            'success': True,
            'saved_count': result['saved_count'],
            'message': f'Сохранено {result["saved_count"]} файлов'
        })
        
    except ClientDisconnected:
        logger.warning("⚠️ Клиент разорвал соединение")
        return jsonify({'success': False, 'message': 'Соединение прервано'}), 400
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки пачки: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/start_publish', methods=['POST'])
def start_publish():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'user_id не указан'}), 400
        
        api.send_message(user_id, f"📢 Начинаю публикацию объявлений...")
        threading.Thread(target=publisher.start, args=(user_id,)).start()
        
        return jsonify({'success': True, 'message': 'Публикация запущена'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска публикации: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
                "🌐 **Загрузить папку:**\n"
                f"🔗 https://maxbot.bothost.tech/upload?user_id={user_id}\n\n"
                "📊 **Получить отчет:**\n"
                f"🔗 https://maxbot.bothost.tech/report/{user_id}\n\n"
                "⏹ **Остановить публикацию:** `/stop`"
            )
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/report':
            api.send_message(user_id, "📊 Создаю отчет...")
            report_path = report_gen.generate_report(user_id)
            if report_path:
                filename = os.path.basename(report_path)
                download_url = f"https://maxbot.bothost.tech/download_report/{user_id}/{filename}"
                api.send_message(
                    user_id,
                    f"📊 **Отчет создан!**\n\n"
                    f"🔗 [Скачать отчет]({download_url})"
                )
            else:
                api.send_message(user_id, "❌ Нет данных для отчета.")
            return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

@app.route('/report/<int:user_id>')
def report_page(user_id):
    report_path = report_gen.generate_report(user_id)
    if not report_path:
        return "❌ Нет данных для отчета", 404
    
    filename = os.path.basename(report_path)
    download_url = f"/download_report/{user_id}/{filename}"
    
    return f"""
    <html>
    <head><title>Отчет</title></head>
    <body style="font-family: Arial; max-width: 600px; margin: 50px auto; text-align: center;">
        <h1>📊 Отчет готов!</h1>
        <p><a href="{download_url}" style="display: inline-block; padding: 12px 30px; background: #28a745; color: white; text-decoration: none; border-radius: 5px;">📥 Скачать отчет</a></p>
        <p><a href="/upload">⬅️ Вернуться к загрузке</a></p>
    </body>
    </html>
    """

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    try:
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            return "❌ Файл не найден", 404
        
        response = send_file(file_path, as_attachment=True, download_name=filename)
        
        threading.Thread(target=report_gen.cleanup_user_data, args=(user_id, True)).start()
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return str(e), 500

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/status')
def status():
    return {"status": "running", "token_set": bool(TOKEN)}

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
            json={"url": webhook_url, "update_types": ["message_created", "bot_started", "bot_stopped"]},
            timeout=10,
            verify=False
        )
        if r.status_code == 200:
            return f"✅ Вебхук настроен: {webhook_url}"
        else:
            return f"❌ Ошибка: {r.status_code} - {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
    app.run(host='0.0.0.0', port=port, threaded=True)
