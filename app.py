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
        for key, files in request.files.items():
            for file in files:
                logger.info(f"   📎 {key}: {file.filename} ({file.content_type})")

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
        'message': f'Маршрут не найден: {request.path}',
        'available_routes': [str(rule) for rule in app.url_map.iter_rules()]
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
    """Принимает FormData с файлами и создает задачи в RQ"""
    log_request()
    
    try:
        logger.info("=" * 60)
        logger.info("📥 НАЧАЛО ОБРАБОТКИ /upload_folders")
        
        if request.method == 'OPTIONS':
            logger.info("📋 OPTIONS запрос")
            return '', 200
        
        if not request.content_type or 'multipart/form-data' not in request.content_type:
            logger.error(f"❌ Неверный Content-Type: {request.content_type}")
            return jsonify({
                'success': False, 
                'message': f'Ожидается multipart/form-data, получено: {request.content_type}'
            }), 400
        
        user_id = request.form.get('user_id', type=int)
        max_photos = request.form.get('max_photos', 6, type=int)
        delay_between = request.form.get('delay_between', 3, type=int)
        
        logger.info(f"👤 user_id: {user_id}")
        logger.info(f"📸 max_photos: {max_photos}")
        logger.info(f"⏱️ delay_between: {delay_between}")
        
        if not user_id:
            logger.error("❌ Нет user_id")
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        files = request.files.getlist('files[]')
        logger.info(f"📁 Получено файлов: {len(files)}")
        
        if not files:
            logger.error("❌ Нет файлов")
            return jsonify({'success': False, 'message': 'Нет файлов'}), 400
        
        if queue is None:
            logger.error("❌ Очередь недоступна")
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
            else:
                logger.warning(f"⚠️ Файл без пути: {file_path}")
        
        logger.info(f"📁 Найдено {len(folders)} папок")
        
        if not folders:
            logger.error("❌ Нет папок")
            return jsonify({'success': False, 'message': 'Не найдено папок с файлами'}), 400
        
        # Обрабатываем каждую папку
        job_ids = []
        folder_data_list = []
        
        for folder_name, folder_files in folders.items():
            logger.info(f"📂 Обработка папки: {folder_name} ({len(folder_files)} файлов)")
            
            # Находим info.txt
            info_file = None
            image_files = []
            
            for f in folder_files:
                filename = f.filename.lower()
                if filename.endswith('.txt') and 'info' in filename:
                    info_file = f
                    logger.info(f"  📄 Найден info.txt: {f.filename}")
                elif filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                    image_files.append(f)
                    logger.info(f"  🖼️ Найдено изображение: {f.filename}")
            
            if not info_file:
                logger.warning(f"⚠️ Нет info.txt в папке {folder_name}")
                continue
            
            # Читаем текст
            try:
                info_content = info_file.read().decode('utf-8')
                logger.info(f"📝 info.txt прочитан: {len(info_content)} символов")
            except Exception as e:
                logger.error(f"❌ Ошибка чтения info.txt: {e}")
                continue
            
            # Разделяем текст
            ad_text = info_content
            metadata_text = ''
            if '#изъятая' in info_content:
                parts = info_content.split('#изъятая')
                ad_text = parts[0].strip()
                metadata_text = parts[1] if len(parts) > 1 else ''
                logger.info(f"✂️ Разделен текст: {len(ad_text)} символов до #изъятая")
            
            # Ограничиваем количество фото
            image_files = image_files[:max_photos]
            logger.info(f"🖼️ Изображений для загрузки: {len(image_files)} (максимум {max_photos})")
            
            # Читаем изображения
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
                        logger.info(f"  ✅ Изображение загружено: {img_file.filename} ({len(img_data)} байт)")
                except Exception as e:
                    logger.error(f"❌ Ошибка чтения {img_file.filename}: {e}")
            
            folder_data = {
                'folderName': folder_name,
                'adText': ad_text,
                'metadataText': metadata_text,
                'images': images
            }
            
            folder_data_list.append(folder_data)
            logger.info(f"✅ Папка {folder_name} подготовлена: {len(images)} изображений")
        
        if not folder_data_list:
            logger.error("❌ Нет данных для задач")
            return jsonify({'success': False, 'message': 'Нет данных для обработки'}), 400
        
        # Создаем задачи в RQ
        logger.info(f"📝 Создание {len(folder_data_list)} задач в RQ...")
        for i, folder_data in enumerate(folder_data_list):
            logger.info(f"  📝 Задача {i+1}: {folder_data['folderName']}")
            
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
                logger.info(f"  ✅ Создана задача {job.id}")
            except Exception as e:
                logger.error(f"  ❌ Ошибка создания задачи: {e}")
        
        logger.info(f"✅ Успешно создано {len(job_ids)} задач")
        logger.info("=" * 60)
        
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
    log_request()
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
                logger.warning(f"⚠️ Задача {job_id} не найдена: {e}")
                result[job_id] = {'status': 'unknown', 'error': str(e)}
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения статуса: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stop_publish', methods=['POST'])
def stop_publish():
    log_request()
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
                    logger.info(f"  ✅ Отменена задача {job_id}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отменить задачу {job_id}: {e}")
        
        if queue:
            queue.enqueue(cleanup_user_task, user_id, timeout=60)
            logger.info(f"🧹 Добавлена задача очистки для пользователя {user_id}")
        
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
    log_request()
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
        
        logger.info(f"💬 user_id={user_id}, text={text[:100] if text else 'empty'}")
        
        # Обработка команд
        if text and text.strip() == '/start':
            url = f"{MAX_API_URL}/messages?user_id={user_id}"
            payload = {
                "text": "🏠 **Главное меню**\n\n"
                       "🌐 **Загрузить папку:**\n"
                       f"🔗 https://maxbot.bothost.tech/upload?user_id={user_id}\n\n"
                       "📊 **Получить отчет:**\n"
                       f"🔗 https://maxbot.bothost.tech/report/{user_id}\n\n"
                       "⏹ **Остановить публикацию:** `/stop`\n\n"
                       "📋 **Инструкция:**\n"
                       "1. Подготовьте папки с объявлениями\n"
                       "2. Используйте разделитель #изъятая\n"
                       "3. Фото до 10 шт на объявление",
                "format": "markdown"
            }
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            # Останавливаем публикацию
            url = f"{MAX_API_URL}/messages?user_id={user_id}"
            payload = {
                "text": "⏹️ **Публикация остановлена!**",
                "format": "markdown"
            }
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            
            # Также останавливаем через API
            if queue:
                # Отменяем все задачи пользователя
                from rq import Worker
                workers = Worker.all(connection=redis_conn)
                for worker in workers:
                    for job in worker.get_current_job():
                        if job and job.args and len(job.args) > 0 and job.args[0] == user_id:
                            job.cancel()
            
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/report':
            report_path = report_gen.generate_report(user_id)
            url = f"{MAX_API_URL}/messages?user_id={user_id}"
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            
            if report_path:
                filename = os.path.basename(report_path)
                download_url = f"https://maxbot.bothost.tech/download_report/{user_id}/{filename}"
                payload = {
                    "text": f"📊 **Отчет создан!**\n\n🔗 [Скачать отчет]({download_url})",
                    "format": "markdown"
                }
            else:
                payload = {
                    "text": "❌ Нет данных для отчета.",
                    "format": "markdown"
                }
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка вебхука: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/report/<int:user_id>')
def report_page(user_id):
    log_request()
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
        <p><small>Отчет сгенерирован: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
    </body>
    </html>
    """

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    try:
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            logger.error(f"❌ Файл не найден: {file_path}")
            return "❌ Файл не найден", 404
        
        logger.info(f"📥 Скачивание файла: {file_path}")
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
        "data_dir": DATA_DIR,
        "python_version": sys.version,
        "app_version": "2.0.1"
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

# ========== HTML СТРАНИЦА ==========
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
        .file-list li .status-badge { font-size: 12px; padding: 2px 10px; border-radius: 20px; margin-left: 10px; }
        .file-list li .status-badge.pending { background: #ffc107; color: #333; }
        .file-list li .status-badge.processing { background: #17a2b8; color: white; }
        .file-list li .status-badge.done { background: #28a745; color: white; }
        .file-list li .status-badge.error { background: #dc3545; color: white; }
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
        .settings-section select { padding: 5px; border: 1px solid #ccc; border-radius: 5px; }
        .queue-info { background: #f8f9fa; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #17a2b8; }
        .queue-info strong { color: #17a2b8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте головную папку (любое название)<br>
            2️⃣ Внутри создайте подпапки объявлений: <code>1 -123456789</code>, <code>2 -987654321</code><br>
            3️⃣ В каждой подпапке: <code>info.txt</code> (текст) и фото (1-10 шт)<br>
            4️⃣ В тексте используйте разделитель <code>#изъятая</code>:<br>
            &nbsp;&nbsp;• Текст ДО разделителя — публикуется в чат<br>
            &nbsp;&nbsp;• Текст ПОСЛЕ разделителя — идет в отчет<br>
            5️⃣ Перетащите головную папку в поле ниже<br>
            6️⃣ Каждая папка отправляется отдельным запросом
        </div>
        
        <div class="settings-section">
            <h4>⚙️ Настройки публикации</h4>
            <label>
                📸 Максимум фото:
                <input type="number" id="maxPhotos" value="6" min="1" max="10">
            </label>
            <label>
                ⏱️ Задержка между папками (сек):
                <input type="number" id="delayBetween" value="3" min="1" max="30">
            </label>
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите головную папку сюда</strong></p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <div class="queue-info" id="queueInfo">
                <strong>📋 Очередь публикации:</strong> 
                <span id="queueStatus">Ожидание</span>
            </div>
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
            <p style="margin-top: 10px; color: #666; font-size: 14px;">После публикации всех папок</p>
        </div>
        
        <div class="footer">⚡ MAX Bot | Загрузка объявлений</div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const userId = urlParams.get('user_id') || 151296248;
        
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

        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const items = e.dataTransfer.items;
            const files = [];
            let pendingReads = 0;
            
            function processEntry(entry, path) {
                if (entry.isDirectory) {
                    const reader = entry.createReader();
                    reader.readEntries((entries) => {
                        for (let e of entries) {
                            processEntry(e, path + entry.name + '/');
                        }
                    });
                } else {
                    entry.file((file) => {
                        file.webkitRelativePath = path + file.name;
                        files.push(file);
                        pendingReads--;
                        if (pendingReads === 0) {
                            selectedFiles = files;
                            displayFiles(selectedFiles);
                        }
                    });
                }
            }
            
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry) {
                        pendingReads++;
                        processEntry(entry, '');
                    }
                }
            }
            
            if (pendingReads === 0 && files.length > 0) {
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

        function displayFiles(files) {
            fileListContent.innerHTML = '';
            const folders = new Map();
            
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const folderName = parts[0];
                    const subFolder = parts.slice(1, -1).join('/') || 'root';
                    const key = folderName + '/' + subFolder;
                    
                    if (!folders.has(key)) {
                        folders.set(key, {
                            name: folderName,
                            sub: subFolder,
                            count: 0,
                            display: subFolder === 'root' ? folderName : folderName + '/' + subFolder
                        });
                    }
                    folders.get(key).count++;
                }
            });
