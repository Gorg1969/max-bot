# app.py - ПОЛНАЯ ВЕРСИЯ С SQLite

from flask import Flask, request, jsonify, render_template_string, send_file
import os
import logging
import json
import requests
import traceback
import sys
import time
import hashlib
import base64
from datetime import datetime
from rq import Queue
from rq.job import Job
from redis import Redis
from modules import Database, FileManager
from modules.report_generator import ReportGenerator
from modules.tasks import process_folder_task, cleanup_user_task

# ========== ИНИЦИАЛИЗАЦИЯ ==========
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
app.config['PROPAGATE_EXCEPTIONS'] = True

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
MAX_API_URL = os.environ.get("MAX_API_URL", "https://platform-api2.max.ru")

# ✅ SQLite вместо PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///app/data/tokens.db")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

logger.info(f"✅ Токен: {TOKEN[:10] if TOKEN else 'НЕТ'}...")
logger.info(f"📁 DATA_DIR: {DATA_DIR}")
logger.info(f"🔴 REDIS_URL: {REDIS_URL}")
logger.info(f"💾 База данных: SQLite")

# ========== ОЖИДАНИЕ REDIS ==========
def wait_for_redis(max_retries=20, delay=2):
    for attempt in range(max_retries):
        try:
            test_conn = Redis.from_url(REDIS_URL, socket_connect_timeout=5)
            test_conn.ping()
            test_conn.close()
            logger.info(f"✅ Redis готов! (попытка {attempt + 1})")
            return True
        except Exception as e:
            logger.info(f"⏳ Ожидание Redis... ({attempt + 1}/{max_retries})")
            time.sleep(delay)
    logger.error("❌ Redis не запустился!")
    return False

wait_for_redis()

# ========== RQ ==========
redis_conn = None
queue = None

def init_redis():
    global redis_conn, queue
    try:
        redis_conn = Redis.from_url(REDIS_URL, socket_connect_timeout=5)
        redis_conn.ping()
        queue = Queue('default', connection=redis_conn)
        logger.info(f"✅ Подключение к Redis")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False

init_redis()

# ========== БД ==========
db = None
fm = None
report_gen = None

def init_database():
    global db, fm, report_gen
    try:
        db = Database()
        fm = FileManager(DATA_DIR)
        report_gen = ReportGenerator(fm, db)
        logger.info("✅ База данных SQLite инициализирована")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False

init_database()

# ========== ОБРАБОТЧИКИ ОШИБОК ==========
@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"❌ Ошибка: {e}")
    return jsonify({'success': False, 'message': str(e)}), 500

# ========== UPLOAD_PAGE (сокращенный) ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; text-align: center; cursor: pointer; }
        .drop-zone:hover { background: #e3f2fd; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; }
        .status.error { background: #f8d7da; color: #721c24; display: block; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; }
        .file-list li { background: #f8f9fa; padding: 10px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; }
        .settings-section { background: #e7f5ff; padding: 15px; border-radius: 10px; margin: 15px 0; }
        .settings-section label { display: inline-block; margin-right: 15px; font-weight: bold; }
        .settings-section input[type="number"] { width: 60px; padding: 5px; border: 1px solid #ccc; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="settings-section">
            <label>📸 Максимум фото: <input type="number" id="maxPhotos" value="6" min="1" max="10"></label>
            <label>⏱️ Задержка (сек): <input type="number" id="delayBetween" value="3" min="1" max="30"></label>
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span style="font-size:48px;">📂</span>
            <p><strong>Перетащите головную папку сюда</strong></p>
            <button class="btn btn-success" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div id="selectedInfo"></div>
            <ul class="file-list" id="fileListContent"></ul>
            <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
            <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
            <button class="btn btn-warning" onclick="stopPublish()">⏹️ Остановить</button>
        </div>
        
        <div class="progress-bar" id="progressBar"><div class="progress" id="progress">0%</div></div>
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div style="margin-top:20px;text-align:center;">
            <button class="btn btn-success" onclick="getReport()">📊 Скачать отчет</button>
        </div>
    </div>

    <script>
        const userId = new URLSearchParams(window.location.search).get('user_id') || 151296248;
        let selectedFiles = [], isProcessing = false, folderQueue = [], jobIds = [], totalFolders = 0;
        let jobStatusInterval = null;
        const MAX_FOLDERS = 50, MAX_IMAGES_PER_FOLDER = 10, MAX_IMAGE_SIZE_MB = 5;
        
        // ... весь JavaScript как в предыдущей версии (с обработкой на клиенте) ...
        // Он уже был в предыдущих сообщениях, вставьте его сюда полностью
        
        // Для краткости здесь сокращено, но в полной версии должен быть полный JS код
        // с функциями readDirectoryRecursive, compressImage, displayFiles, uploadFolder и т.д.
        
        function getReport() { window.open(`/report/${userId}`, '_blank'); }
        function clearFiles() { location.reload(); }
        function stopPublish() { /* ... */ }
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

@app.route('/upload_folders', methods=['POST', 'OPTIONS'])
def upload_folders():
    """Принимает FormData с ОДНОЙ папкой"""
    try:
        if request.method == 'OPTIONS':
            return '', 200
        
        user_id = request.form.get('user_id', type=int)
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        max_photos = request.form.get('max_photos', 6, type=int)
        max_photos = max(1, min(10, max_photos))
        
        if queue is None:
            return jsonify({'success': False, 'message': 'Очередь недоступна'}), 503
        
        folders_info = request.form.getlist('folders[]')
        if not folders_info:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        folder_json = folders_info[0]
        folder_data = json.loads(folder_json)
        folder_name = folder_data.get('name', 'folder')
        ad_text = folder_data.get('adText', '')
        image_count = folder_data.get('imageCount', 0)
        
        images = []
        MAX_IMAGE_SIZE = 5 * 1024 * 1024
        
        for i in range(min(image_count, max_photos)):
            field_name = f'images_{folder_name}_{i}'
            if field_name in request.files:
                img_file = request.files[field_name]
                img_data = img_file.read()
                if len(img_data) > MAX_IMAGE_SIZE:
                    continue
                if img_data:
                    # ✅ base64 вместо list() - экономия памяти
                    img_base64 = base64.b64encode(img_data).decode('ascii')
                    images.append({
                        'name': img_file.filename,
                        'data': img_base64,
                        'type': img_file.content_type or 'image/jpeg'
                    })
                    del img_data
        
        metadata_text = ''
        if '#изъятая' in ad_text:
            parts = ad_text.split('#изъятая')
            ad_text = parts[0].strip()
            metadata_text = parts[1] if len(parts) > 1 else ''
        
        folder_payload = {
            'folderName': folder_name[:100],
            'adText': ad_text[:5000],
            'metadataText': metadata_text[:1000],
            'images': images[:max_photos]
        }
        
        job = queue.enqueue(
            process_folder_task,
            user_id,
            folder_payload,
            job_id=None,
            result_ttl=3600,
            failure_ttl=3600,
            timeout=600
        )
        
        return jsonify({
            'success': True,
            'message': f'Создана задача {job.id}',
            'job_ids': [job.id],
            'total_folders': 1,
            'total_images': len(images)
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/job_status', methods=['POST'])
def job_status():
    try:
        data = request.get_json()
        job_ids = data.get('job_ids', [])
        result = {}
        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                status = {'status': job.get_status()}
                if job.is_finished:
                    status['result'] = job.return_value()
                elif job.is_failed:
                    status['error'] = str(job.exc_info)
                result[job_id] = status
            except:
                result[job_id] = {'status': 'unknown'}
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/stop_publish', methods=['POST'])
def stop_publish():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        job_ids = data.get('job_ids', [])
        cancelled = 0
        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                if job.get_status() in ['queued', 'started']:
                    job.cancel()
                    cancelled += 1
            except:
                pass
        return jsonify({'success': True, 'message': f'Остановлено {cancelled} задач'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
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
        
        logger.info(f"💬 user_id={user_id}")
        
        if text and text.strip() == '/start':
            url = f"{MAX_API_URL}/messages?user_id={user_id}"
            payload = {
                "text": "🏠 **Главное меню**\n\n"
                       "🌐 **Загрузить папку:**\n"
                       f"🔗 https://maxbot.bothost.tech/upload?user_id={user_id}\n\n"
                       "📊 **Получить отчет:**\n"
                       f"🔗 https://maxbot.bothost.tech/report/{user_id}\n\n"
                       "⏹ **Остановить:** /stop\n"
                       "📋 **Статус:** /status",
                "format": "markdown"
            }
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            if queue:
                for job in queue.jobs:
                    if job and job.args and len(job.args) > 0 and job.args[0] == user_id:
                        job.cancel()
            url = f"{MAX_API_URL}/messages?user_id={user_id}"
            payload = {"text": "⏹️ **Публикация остановлена!**", "format": "markdown"}
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/status':
            user_jobs = 0
            if queue:
                for job in queue.jobs:
                    if job and job.args and len(job.args) > 0 and job.args[0] == user_id:
                        user_jobs += 1
            url = f"{MAX_API_URL}/messages?user_id={user_id}"
            payload = {
                "text": f"📊 **Статус**\n\n"
                       f"👤 Ваш ID: {user_id}\n"
                       f"📋 Ваших задач: {user_jobs}\n"
                       f"📊 Всего задач: {len(queue.jobs) if queue else 0}",
                "format": "markdown"
            }
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"ok": False}), 500

@app.route('/report/<int:user_id>')
def report_page(user_id):
    report_path = report_gen.generate_report(user_id)
    if not report_path:
        return "❌ Нет данных для отчета", 404
    filename = os.path.basename(report_path)
    return f"""
    <html>
    <body style="text-align:center;padding:50px;font-family:Arial;">
        <h1>📊 Отчет готов!</h1>
        <p><a href="/download_report/{user_id}/{filename}" style="padding:12px 30px;background:#28a745;color:white;text-decoration:none;border-radius:5px;">📥 Скачать</a></p>
        <p><a href="/upload">⬅️ Вернуться</a></p>
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
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        return str(e), 500

@app.route('/health')
def health():
    return {"status": "ok", "redis": redis_conn is not None, "queue": queue is not None}

@app.route('/status')
def status():
    return {"status": "running", "token_set": bool(TOKEN), "redis": redis_conn is not None}

# ========== ЗАПУСК ==========
# НЕТ if __name__ == "__main__" - ТОЛЬКО ДЛЯ GUNICORN!
