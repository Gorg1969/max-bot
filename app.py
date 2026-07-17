# app.py - ПОЛНАЯ ВЕРСИЯ

from flask import Flask, request, jsonify, render_template_string, send_file
import os
import logging
import json
import requests
import traceback
import sys
import time
import hashlib
from datetime import datetime
from rq import Queue
from rq.job import Job
from redis import Redis
from modules import Database, FileManager
from modules.report_generator import ReportGenerator
from modules.tasks import process_folder_task, cleanup_user_task

# ========== ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ ==========
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
app.config['PROPAGATE_EXCEPTIONS'] = True

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "DEBUG")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ИЗ ОКРУЖЕНИЯ ==========
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
MAX_API_URL = os.environ.get("MAX_API_URL", "https://platform-api2.max.ru")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН в переменных окружения!")

logger.info(f"✅ Токен загружен из окружения (первые 10 символов): {TOKEN[:10] if TOKEN else 'НЕТ'}...")

# ========== ИНИЦИАЛИЗАЦИЯ RQ ==========
try:
    redis_conn = Redis.from_url(REDIS_URL)
    queue = Queue('default', connection=redis_conn)
    logger.info(f"✅ Подключение к Redis: {REDIS_URL}")
except Exception as e:
    logger.error(f"❌ Ошибка подключения к Redis: {e}")
    redis_conn = None
    queue = None

# ========== ИНИЦИАЛИЗАЦИЯ БД И МЕНЕДЖЕРОВ ==========
db = Database()
fm = FileManager(DATA_DIR)
report_gen = ReportGenerator(fm, db)

# ========== ДИАГНОСТИЧЕСКАЯ ФУНКЦИЯ ==========
def log_request():
    """Логирует входящий запрос"""
    logger.info("=" * 80)
    logger.info(f"📥 {request.method} {request.path}")
    logger.info(f"📋 Content-Type: {request.content_type}")
    logger.info(f"📋 Content-Length: {request.content_length}")
    if request.args:
        logger.info(f"📋 Args: {dict(request.args)}")
    if request.form:
        logger.info(f"📋 Form: {dict(request.form)}")
    if request.files:
        logger.info(f"📋 Files: {list(request.files.keys())}")

# ========== ОБРАБОТЧИКИ ОШИБОК ==========
@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"❌ Необработанная ошибка: {e}")
    logger.error(traceback.format_exc())
    return jsonify({
        'success': False,
        'message': f'Внутренняя ошибка сервера: {str(e)}',
        'error_type': type(e).__name__
    }), 500

@app.errorhandler(404)
def not_found(e):
    logger.warning(f"⚠️ 404: {request.path}")
    return jsonify({
        'success': False,
        'message': f'Маршрут не найден: {request.path}'
    }), 404

@app.errorhandler(400)
def bad_request(e):
    logger.warning(f"⚠️ 400: {e}")
    return jsonify({
        'success': False,
        'message': f'Некорректный запрос: {str(e)}'
    }), 400

@app.errorhandler(413)
def too_large(e):
    return jsonify({
        'success': False,
        'message': 'Файл слишком большой. Максимальный размер: 200 МБ'
    }), 413

# ========== МАРШРУТЫ ==========

@app.route('/', methods=['GET'])
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    log_request()
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_folders', methods=['POST', 'OPTIONS'])
def upload_folders():
    log_request()
    
    try:
        logger.info("=" * 60)
        logger.info("📥 НАЧАЛО ОБРАБОТКИ /upload_folders")
        
        if request.method == 'OPTIONS':
            return '', 200
        
        if not request.content_type or 'multipart/form-data' not in request.content_type:
            return jsonify({
                'success': False, 
                'message': f'Ожидается multipart/form-data, получено: {request.content_type}'
            }), 400
        
        user_id = request.form.get('user_id', type=int)
        max_photos = request.form.get('max_photos', 6, type=int)
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        files = request.files.getlist('files[]')
        logger.info(f"📁 Получено файлов: {len(files)}")
        
        if not files:
            return jsonify({'success': False, 'message': 'Нет файлов'}), 400
        
        if queue is None:
            return jsonify({'success': False, 'message': 'Очередь недоступна'}), 500
        
        # Группируем файлы по папкам
        folders = {}
        for file in files:
            file_path = file.filename
            if '/' in file_path:
                folder_name = file_path.split('/')[0]
                if folder_name not in folders:
                    folders[folder_name] = []
                folders[folder_name].append(file)
        
        logger.info(f"📁 Найдено {len(folders)} папок")
        
        if not folders:
            return jsonify({'success': False, 'message': 'Не найдено папок с файлами'}), 400
        
        job_ids = []
        folder_data_list = []
        
        for folder_name, folder_files in folders.items():
            logger.info(f"📂 Обработка папки: {folder_name} ({len(folder_files)} файлов)")
            
            info_file = None
            image_files = []
            
            for f in folder_files:
                filename = f.filename.lower()
                if filename.endswith('.txt') and 'info' in filename:
                    info_file = f
                elif filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                    image_files.append(f)
            
            if not info_file:
                logger.warning(f"⚠️ Нет info.txt в папке {folder_name}")
                continue
            
            try:
                info_content = info_file.read().decode('utf-8')
            except Exception as e:
                logger.error(f"❌ Ошибка чтения info.txt: {e}")
                continue
            
            ad_text = info_content
            metadata_text = ''
            if '#изъятая' in info_content:
                parts = info_content.split('#изъятая')
                ad_text = parts[0].strip()
                metadata_text = parts[1] if len(parts) > 1 else ''
            
            image_files = image_files[:max_photos]
            
            images = []
            for img_file in image_files:
                try:
                    img_data = img_file.read()
                    if img_data:
                        images.append({
                            'name': img_file.filename,
                            'data': list(img_data),
                            'type': img_file.content_type or 'image/jpeg'
                        })
                except Exception as e:
                    logger.error(f"❌ Ошибка чтения {img_file.filename}: {e}")
            
            folder_data = {
                'folderName': folder_name,
                'adText': ad_text,
                'metadataText': metadata_text,
                'images': images
            }
            
            folder_data_list.append(folder_data)
        
        if not folder_data_list:
            return jsonify({'success': False, 'message': 'Нет данных для обработки'}), 400
        
        for folder_data in folder_data_list:
            try:
                job = queue.enqueue(
                    process_folder_task,
                    user_id,
                    folder_data,
                    job_id=None,
                    result_ttl=3600,
                    failure_ttl=3600,
                    timeout=300
                )
                job_ids.append(job.id)
                logger.info(f"📝 Создана задача {job.id}")
            except Exception as e:
                logger.error(f"❌ Ошибка создания задачи: {e}")
        
        return jsonify({
            'success': True,
            'message': f'Создано {len(job_ids)} задач',
            'job_ids': job_ids,
            'total_folders': len(folder_data_list)
        })
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False, 
            'message': str(e),
            'error_type': type(e).__name__
        }), 500

@app.route('/job_status', methods=['POST'])
def job_status():
    try:
        data = request.get_json()
        if not data:
            return jsonify({})
        
        job_ids = data.get('job_ids', [])
        if not job_ids:
            return jsonify({})
        
        result = {}
        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                status = {
                    'status': job.get_status(),
                    'created_at': job.created_at.isoformat() if job.created_at else None,
                }
                
                if job.is_finished:
                    status['result'] = job.return_value()
                elif job.is_failed:
                    status['error'] = str(job.exc_info)
                
                result[job_id] = status
            except Exception as e:
                result[job_id] = {'status': 'unknown', 'error': str(e)}
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения статуса: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stop_publish', methods=['POST'])
def stop_publish():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        user_id = data.get('user_id')
        job_ids = data.get('job_ids', [])
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        cancelled = 0
        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                if job.get_status() in ['queued', 'started']:
                    job.cancel()
                    cancelled += 1
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отменить задачу {job_id}: {e}")
        
        if queue:
            queue.enqueue(cleanup_user_task, user_id, timeout=60)
        
        return jsonify({
            'success': True,
            'message': f'Остановлено {cancelled} задач',
            'cancelled': cancelled
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка остановки: {e}")
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
                       f"🔗 https://maxbot.bothost.tech/report/{user_id}",
                "format": "markdown"
            }
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка вебхука: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

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
        
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return str(e), 500

@app.route('/health')
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "redis": redis_conn is not None,
        "queue": queue is not None,
        "token": bool(TOKEN)
    }

@app.route('/status')
def status():
    return {
        "status": "running",
        "token_set": bool(TOKEN),
        "redis_connected": redis_conn is not None,
        "queue_available": queue is not None,
        "data_dir": DATA_DIR
    }

@app.route('/routes')
def list_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'path': str(rule)
        })
    return jsonify({
        'routes': routes,
        'total': len(routes)
    })

# ========== HTML СТРАНИЦА (сокращенная версия) ==========
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
        .drop-zone .icon { font-size: 48px; display: block; margin-bottom: 10px; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; transition: all 0.3s; }
        .btn-primary { background: #007bff; color: white; }
        .btn-primary:hover { background: #0056b3; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
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
        .report-section { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; text-align: center; }
        .settings-section { background: #e7f5ff; padding: 15px; border-radius: 10px; margin: 15px 0; border: 1px solid #007bff; }
        .settings-section label { display: inline-block; margin-right: 15px; font-weight: bold; }
        .settings-section input[type="number"] { width: 60px; padding: 5px; border: 1px solid #ccc; border-radius: 5px; }
        .queue-info { background: #f8f9fa; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #17a2b8; }
        .queue-info strong { color: #17a2b8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте головную папку с подпапками<br>
            2️⃣ В каждой подпапке: info.txt и фото<br>
            3️⃣ Используйте разделитель #изъятая в тексте<br>
            4️⃣ Перетащите головную папку в поле ниже
        </div>
        
        <div class="settings-section">
            <h4>⚙️ Настройки</h4>
            <label>📸 Максимум фото: <input type="number" id="maxPhotos" value="6" min="1" max="10"></label>
            <label>⏱️ Задержка: <input type="number" id="delayBetween" value="3" min="1" max="30"></label>
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите папку сюда</strong></p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <div class="queue-info"><strong>📋 Очередь:</strong> <span id="queueStatus">Ожидание</span></div>
            <ul class="file-list" id="fileListContent"></ul>
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
                <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
                <button class="btn btn-warning" onclick="stopPublish()">⏹️ Остановить</button>
            </div>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="report-section">
            <button class="btn btn-primary" onclick="getReport()">📊 Скачать отчет</button>
        </div>
        
        <div class="footer">⚡ MAX Bot</div>
    </div>

    <script>
        const userId = new URLSearchParams(window.location.search).get('user_id') || 151296248;
        let selectedFiles = [], isProcessing = false, folderQueue = [], jobIds = [];
        let totalFolders = 0, processedCount = 0, jobStatusInterval = null;
        
        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const fileList = document.getElementById('fileList');
        const fileListContent = document.getElementById('fileListContent');
        const selectedInfo = document.getElementById('selectedInfo');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');
        const queueStatus = document.getElementById('queueStatus');

        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const items = e.dataTransfer.items;
            const files = [];
            let pending = 0;
            
            function processEntry(entry, path) {
                if (entry.isDirectory) {
                    const reader = entry.createReader();
                    reader.readEntries((entries) => {
                        for (let e of entries) processEntry(e, path + entry.name + '/');
                    });
                } else {
                    entry.file((file) => {
                        file.webkitRelativePath = path + file.name;
                        files.push(file);
                        pending--;
                        if (pending === 0) { selectedFiles = files; displayFiles(selectedFiles); }
                    });
                }
            }
            
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry) { pending++; processEntry(entry, ''); }
                }
            }
            if (pending === 0 && files.length > 0) { selectedFiles = files; displayFiles(selectedFiles); }
        });

        folderInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            if (files.length > 0) { selectedFiles = files; displayFiles(selectedFiles); }
        });

        function displayFiles(files) {
            fileListContent.innerHTML = '';
            const folders = new Map();
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const name = parts[0];
                    if (!folders.has(name)) folders.set(name, 0);
                    folders.set(name, folders.get(name) + 1);
                }
            });
            const sorted = Array.from(folders.keys()).sort();
            folderQueue = sorted.map(n => ({ name: n, status: 'pending' }));
            sorted.forEach(folder => {
                const li = document.createElement('li');
                li.innerHTML = `<span>📁 <strong>${folder}</strong></span><span class="count">${folders.get(folder)} файлов</span>`;
                fileListContent.appendChild(li);
            });
            selectedInfo.textContent = `✅ Выбрано ${sorted.length} папок, ${files.length} файлов`;
            fileList.style.display = 'block';
            updateQueueStatus();
        }

        function updateQueueStatus() {
            const total = folderQueue.length;
            const done = folderQueue.filter(f => f.status === 'done').length;
            const errors = folderQueue.filter(f => f.status === 'error').length;
            queueStatus.textContent = isProcessing ? `🔄 ${done+errors}/${total}` : `📋 ${done}/${total}`;
            if (errors > 0) queueStatus.textContent += ` ⚠️${errors}`;
        }

        function addLog(msg) { logDiv.style.display = 'block'; logDiv.textContent += msg + '\\n'; logDiv.scrollTop = logDiv.scrollHeight; }
        function showStatus(type, msg) { statusDiv.className = 'status ' + type; statusDiv.textContent = msg; statusDiv.style.display = 'block'; }
        function getReport() { window.open(`/report/${userId}`, '_blank'); }
        function clearFiles() {
            if (isProcessing && !confirm('Остановить?')) return;
            selectedFiles = []; folderQueue = []; jobIds = [];
            fileList.style.display = 'none'; statusDiv.style.display = 'none';
            progressBar.style.display = 'none'; logDiv.style.display = 'none';
            progress.style.width = '0%'; folderInput.value = '';
            if (jobStatusInterval) { clearInterval(jobStatusInterval); jobStatusInterval = null; }
        }

        function stopPublish() {
            isProcessing = false; addLog('⏹️ Остановка...');
            if (jobStatusInterval) { clearInterval(jobStatusInterval); jobStatusInterval = null; }
            fetch('/stop_publish', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(userId), job_ids: jobIds })
            }).catch(e => console.error(e));
        }

        function startJobMonitoring() {
            if (jobStatusInterval) clearInterval(jobStatusInterval);
            jobStatusInterval = setInterval(async () => {
                try {
                    const resp = await fetch('/job_status', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ job_ids: jobIds })
                    });
                    if (!resp.ok) return;
                    const data = await resp.json();
                    let done = 0, failed = 0, finished = 0;
                    jobIds.forEach(id => {
                        const s = data[id];
                        if (s) {
                            if (s.status === 'finished') { finished++; if (s.result && s.result.success) done++; else failed++; }
                            else if (s.status === 'failed') failed++;
                        }
                    });
                    processedCount = done + failed;
                    const pct = Math.round((processedCount / totalFolders) * 100);
                    progress.style.width = pct + '%';
                    progress.textContent = pct + '%';
                    if (finished >= jobIds.length) {
                        clearInterval(jobStatusInterval);
                        jobStatusInterval = null;
                        isProcessing = false;
                        if (failed === 0 && done === totalFolders) {
                            showStatus('success', `✅ Загружено ${done} папок!`);
                            addLog(`✅ ВСЕ ${done} папок загружены!`);
                        } else {
                            showStatus('warning', `⚠️ Загружено ${done} папок, ${failed} с ошибками`);
                        }
                        if (done > 0) addLog(`📊 Отчет: /report/${userId}`);
                    }
                } catch(e) { console.error(e); }
            }, 2000);
        }

        async function uploadFolder() {
            if (selectedFiles.length === 0) { showStatus('error', '❌ Выберите папку'); return; }
            if (isProcessing) { addLog('⚠️ Уже выполняется'); return; }
            
            isProcessing = true;
            jobIds = [];
            processedCount = 0;
            const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 6;
            
            const formData = new FormData();
            formData.append('user_id', userId);
            formData.append('max_photos', maxPhotos);
            
            const folders = new Set();
            selectedFiles.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const name = parts[0];
                    folders.add(name);
                    formData.append('files[]', f, `${name}/${parts.slice(1).join('/')}`);
                }
            });
            
            totalFolders = folders.size;
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            progress.textContent = '0%';
            logDiv.textContent = '';
            addLog(`🚀 Загрузка ${totalFolders} папок...`);
            
            try {
                const resp = await fetch('/upload_folders', { method: 'POST', body: formData });
                if (!resp.ok) { const t = await resp.text(); throw new Error(`HTTP ${resp.status}: ${t.substring(0, 100)}`); }
                const result = await resp.json();
                if (!result.success) throw new Error(result.message || 'Ошибка');
                jobIds = result.job_ids || [];
                addLog(`✅ Создано ${jobIds.length} задач`);
                if (jobIds.length > 0) startJobMonitoring();
                else { isProcessing = false; showStatus('error', '❌ Нет задач'); }
            } catch(e) {
                addLog(`❌ ${e.message}`);
                showStatus('error', `❌ ${e.message}`);
                isProcessing = false;
            }
        }
    </script>
</body>
</html>
"""

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    logger.warning("⚠️ ЗАПУСК В РЕЖИМЕ РАЗРАБОТКИ! Используйте Gunicorn для production!")
    logger.info("📋 Доступные маршруты:")
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.methods} {rule}")
    app.run(host='0.0.0.0', port=port, debug=False)
