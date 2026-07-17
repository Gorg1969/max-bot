# app.py - ПОЛНАЯ ВЕРСИЯ С КЛИЕНТСКОЙ И СЕРВЕРНОЙ ЧАСТЬЮ

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

# ========== ОБНОВЛЕННЫЙ МАРШРУТ ДЛЯ ПРИЕМА СЖАТЫХ ИЗОБРАЖЕНИЙ ==========
@app.route('/upload_folders', methods=['POST', 'OPTIONS'])
def upload_folders():
    """Принимает FormData с файлами и создает задачи в RQ"""
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
        
        # Получаем информацию о папках из поля folders[]
        folders_info = request.form.getlist('folders[]')
        logger.info(f"📁 Получено папок: {len(folders_info)}")
        
        if not folders_info:
            return jsonify({'success': False, 'message': 'Нет данных о папках'}), 400
        
        if queue is None:
            return jsonify({'success': False, 'message': 'Очередь недоступна'}), 500
        
        job_ids = []
        folder_data_list = []
        
        # Обрабатываем каждую папку
        for folder_json in folders_info:
            try:
                folder_data = json.loads(folder_json)
                folder_name = folder_data.get('name')
                ad_text = folder_data.get('adText')
                image_count = folder_data.get('imageCount', 0)
                
                logger.info(f"📂 Обработка папки: {folder_name} ({image_count} фото)")
                
                # Извлекаем изображения из FormData
                images = []
                for i in range(image_count):
                    field_name = f'images_{folder_name}_{i}'
                    if field_name in request.files:
                        img_file = request.files[field_name]
                        img_data = img_file.read()
                        if img_data:
                            images.append({
                                'name': img_file.filename,
                                'data': list(img_data),
                                'type': img_file.content_type or 'image/jpeg'
                            })
                            logger.info(f"  ✅ Изображение {i+1}: {img_file.filename} ({len(img_data)} байт)")
                
                # Разделяем текст
                metadata_text = ''
                if '#изъятая' in ad_text:
                    parts = ad_text.split('#изъятая')
                    ad_text = parts[0].strip()
                    metadata_text = parts[1] if len(parts) > 1 else ''
                
                folder_payload = {
                    'folderName': folder_name,
                    'adText': ad_text,
                    'metadataText': metadata_text,
                    'images': images
                }
                
                folder_data_list.append(folder_payload)
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ Ошибка парсинга JSON: {e}")
                continue
        
        if not folder_data_list:
            return jsonify({'success': False, 'message': 'Нет данных для обработки'}), 400
        
        # Создаем задачи
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
                logger.info(f"📝 Создана задача {job.id} для {folder_data['folderName']}")
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

# ========== HTML СТРАНИЦА С ОБНОВЛЕННЫМ КЛИЕНТСКИМ КОДОМ ==========
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
        .file-list li .sub { color: #666; font-size: 12px; margin-left: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте головную папку с подпапками объявлений<br>
            2️⃣ В каждой подпапке: <code>info.txt</code> (текст) и фото (1-10 шт)<br>
            3️⃣ В тексте используйте разделитель <code>#изъятая</code><br>
            4️⃣ Перетащите головную папку в поле ниже<br>
            5️⃣ Изображения будут сжаты автоматически
        </div>
        
        <div class="settings-section">
            <h4>⚙️ Настройки</h4>
            <label>📸 Максимум фото: <input type="number" id="maxPhotos" value="6" min="1" max="10"></label>
            <label>⏱️ Задержка между папками (сек): <input type="number" id="delayBetween" value="3" min="1" max="30"></label>
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите головную папку сюда</strong></p>
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
        let selectedFiles = [];
        let isProcessing = false;
        let isStopped = false;
        let folderQueue = [];
        let jobIds = [];
        let processedCount = 0;
        let totalFolders = 0;
        let jobStatusInterval = null;
        
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

        // ========== РЕКУРСИВНЫЙ ОБХОД ПАПОК ==========
        function readDirectoryRecursive(entry, path, files, callback) {
            if (entry.isDirectory) {
                const reader = entry.createReader();
                let allEntries = [];
                
                function readEntries() {
                    reader.readEntries((entries) => {
                        if (entries.length === 0) {
                            // Все файлы в папке прочитаны - обрабатываем их
                            let pending = allEntries.length;
                            if (pending === 0) {
                                callback();
                                return;
                            }
                            
                            allEntries.forEach(e => {
                                if (e.isDirectory) {
                                    readDirectoryRecursive(e, path + e.name + '/', files, () => {
                                        pending--;
                                        if (pending === 0) callback();
                                    });
                                } else {
                                    e.file((file) => {
                                        file.webkitRelativePath = path + file.name;
                                        files.push(file);
                                        pending--;
                                        if (pending === 0) callback();
                                    });
                                }
                            });
                        } else {
                            allEntries = allEntries.concat(entries);
                            readEntries();
                        }
                    }, (error) => {
                        console.error('Ошибка чтения папки:', error);
                        callback();
                    });
                }
                readEntries();
            } else {
                // Это файл
                entry.file((file) => {
                    file.webkitRelativePath = path + file.name;
                    files.push(file);
                    callback();
                });
            }
        }

        // ========== ОБРАБОТЧИКИ DROP И CHANGE ==========
        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            
            const items = e.dataTransfer.items;
            const files = [];
            let pending = 0;
            
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry) {
                        pending++;
                        readDirectoryRecursive(entry, '', files, () => {
                            pending--;
                            if (pending === 0) {
                                selectedFiles = files;
                                displayFiles(selectedFiles);
                            }
                        });
                    }
                }
            }
            
            if (pending === 0 && files.length > 0) {
                selectedFiles = files;
                displayFiles(selectedFiles);
            }
        });

        folderInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            if (files.length > 0) {
                selectedFiles = files;
                displayFiles(selectedFiles);
            }
        });

        // ========== СЖАТИЕ ИЗОБРАЖЕНИЙ ==========
        function compressImage(file, maxWidth = 1920, maxHeight = 1920, quality = 0.85) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = function(e) {
                    const img = new Image();
                    img.onload = function() {
                        let width = img.width;
                        let height = img.height;
                        
                        if (width > maxWidth) {
                            height = (height * maxWidth) / width;
                            width = maxWidth;
                        }
                        if (height > maxHeight) {
                            width = (width * maxHeight) / height;
                            height = maxHeight;
                        }
                        
                        const canvas = document.createElement('canvas');
                        canvas.width = width;
                        canvas.height = height;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, width, height);
                        
                        canvas.toBlob((blob) => {
                            if (blob) {
                                const compressedFile = new File([blob], file.name, {
                                    type: 'image/jpeg',
                                    lastModified: Date.now()
                                });
                                resolve(compressedFile);
                            } else {
                                reject(new Error('Не удалось сжать изображение'));
                            }
                        }, 'image/jpeg', quality);
                    };
                    img.onerror = reject;
                    img.src = e.target.result;
                };
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
        }

        // ========== ОТОБРАЖЕНИЕ ПАПОК ==========
        function displayFiles(files) {
            fileListContent.innerHTML = '';
            const folders = new Map();
            
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const rootFolder = parts[0];
                    const subFolder = parts.length > 2 ? parts.slice(1, -1).join('/') : 'root';
                    const key = rootFolder + '/' + subFolder;
                    
                    if (!folders.has(key)) {
                        folders.set(key, {
                            root: rootFolder,
                            sub: subFolder,
                            display: subFolder === 'root' ? rootFolder : rootFolder + '/' + subFolder,
                            count: 0,
                            files: []
                        });
                    }
                    const folder = folders.get(key);
                    folder.count++;
                    folder.files.push(f);
                }
            });
            
            const sortedFolders = Array.from(folders.values()).sort((a, b) => a.display.localeCompare(b.display));
            
            folderQueue = sortedFolders.map(f => ({
                name: f.display,
                status: 'pending',
                count: f.count,
                files: f.files
            }));
            
            sortedFolders.forEach(folder => {
                const li = document.createElement('li');
                const isSubFolder = folder.sub !== 'root';
                const icon = isSubFolder ? '📂' : '📁';
                
                li.innerHTML = `
                    <span>${icon} <strong>${folder.display}</strong></span>
                    <span class="count">${folder.count} файлов</span>
                `;
                li.style.borderLeftColor = isSubFolder ? '#28a745' : '#007bff';
                fileListContent.appendChild(li);
            });
            
            selectedInfo.textContent = `✅ Найдено ${sortedFolders.length} папок, всего ${files.length} файлов`;
            fileList.style.display = 'block';
            updateQueueStatus();
            showStatus('info', `📦 Найдено ${sortedFolders.length} папок с объявлениями`);
        }

        // ========== ОБНОВЛЕНИЕ СТАТУСА ==========
        function updateQueueStatus() {
            const total = folderQueue.length;
            const done = folderQueue.filter(f => f.status === 'done').length;
            const errors = folderQueue.filter(f => f.status === 'error').length;
            
            if (isStopped) {
                queueStatus.textContent = `⏹️ Остановлено (${done}/${total})`;
            } else if (isProcessing) {
                queueStatus.textContent = `🔄 ${done+errors}/${total}`;
            } else if (done === total && total > 0) {
                queueStatus.textContent = `✅ Завершено (${done}/${total})`;
            } else {
                queueStatus.textContent = `📋 ${done}/${total}`;
            }
            if (errors > 0) queueStatus.textContent += ` ⚠️${errors}`;
        }

        function updateFolderStatus(folderName, status) {
            const index = folderQueue.findIndex(f => f.name === folderName);
            if (index !== -1) {
                folderQueue[index].status = status;
                updateQueueStatus();
            }
        }

        // ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
        function addLog(message) {
            logDiv.style.display = 'block';
            logDiv.textContent += message + '\\n';
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        function showStatus(type, message) {
            statusDiv.className = 'status ' + type;
            statusDiv.textContent = message;
            statusDiv.style.display = 'block';
        }

        function getReport() {
            window.open(`/report/${userId}`, '_blank');
        }

        function clearFiles() {
            if (isProcessing && !confirm('Остановить публикацию и очистить?')) return;
            selectedFiles = [];
            folderQueue = [];
            jobIds = [];
            processedCount = 0;
            totalFolders = 0;
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            progress.textContent = '0%';
            folderInput.value = '';
            isStopped = false;
            if (jobStatusInterval) {
                clearInterval(jobStatusInterval);
                jobStatusInterval = null;
            }
        }

        function stopPublish() {
            isStopped = true;
            isProcessing = false;
            addLog('⏹️ Публикация остановлена пользователем');
            showStatus('warning', '⏹️ Публикация остановлена');
            
            if (jobStatusInterval) {
                clearInterval(jobStatusInterval);
                jobStatusInterval = null;
            }
            
            fetch('/stop_publish', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    user_id: parseInt(userId),
                    job_ids: jobIds 
                })
            }).catch(e => console.error('Ошибка остановки:', e));
        }

        // ========== МОНИТОРИНГ ЗАДАЧ ==========
        function startJobMonitoring() {
            if (jobStatusInterval) clearInterval(jobStatusInterval);
            
            jobStatusInterval = setInterval(async () => {
                try {
                    const response = await fetch('/job_status', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ job_ids: jobIds })
                    });
                    
                    if (!response.ok) return;
                    const data = await response.json();
                    
                    let completed = 0;
                    let failed = 0;
                    let finished = 0;
                    
                    jobIds.forEach(jobId => {
                        const status = data[jobId];
                        if (status) {
                            if (status.status === 'finished') {
                                finished++;
                                if (status.result && status.result.success) {
                                    completed++;
                                    const folderName = status.result.folder_name;
                                    updateFolderStatus(folderName, 'done');
                                } else {
                                    failed++;
                                    const folderName = status.result ? status.result.folder_name : 'unknown';
                                    updateFolderStatus(folderName, 'error');
                                }
                            } else if (status.status === 'failed') {
                                failed++;
                            }
                        }
                    });
                    
                    processedCount = completed + failed;
                    updateQueueStatus();
                    
                    const progressPercent = Math.round((processedCount / totalFolders) * 100);
                    progress.style.width = progressPercent + '%';
                    progress.textContent = `${progressPercent}%`;
                    
                    if (finished >= jobIds.length) {
                        clearInterval(jobStatusInterval);
                        jobStatusInterval = null;
                        isProcessing = false;
                        
                        if (failed === 0 && completed === totalFolders) {
                            showStatus('success', `✅ Загружено ${completed} папок!`);
                            addLog(`✅ ВСЕ ${completed} папок загружены!`);
                        } else {
                            showStatus('warning', `⚠️ Загружено ${completed} папок, ${failed} с ошибками`);
                            addLog(`⚠️ Загружено ${completed} папок, ${failed} с ошибками`);
                        }
                        
                        if (completed > 0) {
                            addLog(`\\n📊 Скачать отчет: /report/${userId}`);
                        }
                    }
                } catch (error) {
                    console.error('Ошибка мониторинга:', error);
                }
            }, 2000);
        }

        // ========== ОСНОВНАЯ ФУНКЦИЯ ЗАГРУЗКИ ==========
        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }
            
            if (isProcessing) {
                addLog('⚠️ Обработка уже выполняется, подождите...');
                return;
            }
            
            const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 6;
            const delayBetween = parseInt(document.getElementById('delayBetween').value) || 3;
            
            isProcessing = true;
            isStopped = false;
            processedCount = 0;
            jobIds = [];
            
            showStatus('info', '⏳ Подготовка данных...');
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            progress.textContent = '0%';
            logDiv.textContent = '';
            addLog('🚀 Начинаем обработку...');
            addLog(`📸 Максимум фото на объявление: ${maxPhotos}`);
            
            // Группируем файлы по подпапкам
            const folders = {};
            selectedFiles.forEach(file => {
                const parts = file.webkitRelativePath.split('/');
                if (parts.length >= 3) {
                    const rootFolder = parts[0];
                    const subFolder = parts.slice(1, -1).join('/');
                    const key = rootFolder + '/' + subFolder;
                    
                    if (!folders[key]) {
                        folders[key] = {
                            name: key,
                            root: rootFolder,
                            sub: subFolder,
                            files: []
                        };
                    }
                    folders[key].files.push(file);
                } else if (parts.length === 2) {
                    const key = parts[0];
                    if (!folders[key]) {
                        folders[key] = {
                            name: key,
                            root: key,
                            sub: 'root',
                            files: []
                        };
                    }
                    folders[key].files.push(file);
                }
            });
            
            const folderNames = Object.keys(folders);
            totalFolders = folderNames.length;
            
            folderQueue = folderNames.map(name => ({
                name: name,
                status: 'pending',
                count: folders[name].files.length
            }));
            updateQueueStatus();
            
            addLog(`📁 Найдено ${totalFolders} папок`);
            
            const formData = new FormData();
            formData.append('user_id', userId);
            formData.append('max_photos', maxPhotos);
            formData.append('delay_between', delayBetween);
            formData.append('total_folders', totalFolders);
            
            // Обрабатываем каждую папку
            let processedFolders = 0;
            
            for (const folderName of folderNames) {
                const folder = folders[folderName];
                const files = folder.files;
                
                addLog(`📂 Обработка папки: ${folderName} (${files.length} файлов)`);
                
                let infoFile = null;
                let imageFiles = [];
                
                for (const file of files) {
                    const fileName = file.name.toLowerCase();
                    if (fileName.endsWith('.txt') && fileName.includes('info')) {
                        infoFile = file;
                    } else if (fileName.match(/\\.(jpg|jpeg|png|gif|bmp|webp)$/)) {
                        imageFiles.push(file);
                    }
                }
                
                if (!infoFile) {
                    addLog(`⚠️ Нет info.txt в папке ${folderName}, пропускаем`);
                    continue;
                }
                
                const selectedImages = imageFiles.slice(0, maxPhotos);
                addLog(`🖼️ Найдено ${imageFiles.length} изображений, берем ${selectedImages.length}`);
                
                // Сжимаем изображения
                let compressedImages = [];
                for (let i = 0; i < selectedImages.length; i++) {
                    try {
                        addLog(`📸 Сжатие ${i+1}/${selectedImages.length}: ${selectedImages[i].name}`);
                        const compressed = await compressImage(selectedImages[i], 1920, 1920, 0.85);
                        compressedImages.push(compressed);
                        const origSize = (selectedImages[i].size / 1024 / 1024).toFixed(2);
                        const compSize = (compressed.size / 1024 / 1024).toFixed(2);
                        addLog(`✅ Сжато: ${origSize}МБ -> ${compSize}МБ`);
                    } catch (e) {
                        addLog(`⚠️ Ошибка сжатия ${selectedImages[i].name}: ${e.message}`);
                        compressedImages.push(selectedImages[i]);
                    }
                }
                
                // Читаем info.txt
                const infoContent = await infoFile.text();
                
                // Добавляем в FormData
                formData.append('folders[]', JSON.stringify({
                    name: folderName,
                    adText: infoContent,
                    imageCount: compressedImages.length
                }));
                
                for (let i = 0; i < compressedImages.length; i++) {
                    const img = compressedImages[i];
                    formData.append(`images_${folderName}_${i}`, img, img.name);
                }
                
                processedFolders++;
                addLog(`✅ Папка ${folderName} подготовлена (${compressedImages.length} фото)`);
            }
            
            addLog(`📤 Отправка ${processedFolders} папок на сервер...`);
            
            try {
                const response = await fetch('/upload_folders', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    const text = await response.text();
                    throw new Error(`HTTP ${response.status}: ${text.substring(0, 200)}`);
                }
                
                const result = await response.json();
                
                if (!result.success) {
                    throw new Error(result.message || 'Ошибка загрузки');
                }
                
                jobIds = result.job_ids || [];
                addLog(`✅ Создано ${jobIds.length} задач`);
                
                if (jobIds.length === 0) {
                    showStatus('error', '❌ Не создано ни одной задачи');
                    isProcessing = false;
                    return;
                }
                
                startJobMonitoring();
                
            } catch (error) {
                addLog(`❌ Ошибка: ${error.message}`);
                showStatus('error', `❌ Ошибка: ${error.message}`);
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
