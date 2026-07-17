# app.py - ПОЛНАЯ ВЕРСИЯ С ИСПРАВЛЕНИЯМИ

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

# ========== ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ ==========
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
app.config['PROPAGATE_EXCEPTIONS'] = True

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")),
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

# ========== ИНИЦИАЛИЗАЦИЯ RQ С РЕТРИЯМИ ==========
redis_conn = None
queue = None

def init_redis_with_retry(max_retries=10, delay=3):
    """Инициализация Redis с повторными попытками"""
    global redis_conn, queue
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🔄 Попытка {attempt + 1}/{max_retries} подключения к Redis: {REDIS_URL}")
            redis_conn = Redis.from_url(
                REDIS_URL,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            redis_conn.ping()
            queue = Queue('default', connection=redis_conn)
            logger.info(f"✅ Подключение к Redis: {REDIS_URL}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Redis (попытка {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"⏳ Повторная попытка через {delay} секунд...")
                time.sleep(delay)
            else:
                logger.error("❌ Все попытки подключения к Redis исчерпаны!")
                redis_conn = None
                queue = None
                return False
    
    return False

# Инициализируем с ретриями
init_redis_with_retry(max_retries=5, delay=3)

def ensure_redis():
    """Гарантирует наличие подключения к Redis"""
    global redis_conn, queue
    
    if redis_conn is not None:
        try:
            redis_conn.ping()
            return True
        except Exception as e:
            logger.warning(f"⚠️ Redis потерял соединение: {e}")
            redis_conn = None
            queue = None
    
    # Пытаемся переподключиться
    logger.info("🔄 Попытка переподключения к Redis...")
    return init_redis_with_retry(max_retries=3, delay=2)

# ========== ИНИЦИАЛИЗАЦИЯ БД С ПРОВЕРКОЙ ==========
db = None
fm = None
report_gen = None

def init_database():
    global db, fm, report_gen
    try:
        db = Database()
        fm = FileManager(DATA_DIR)
        report_gen = ReportGenerator(fm, db)
        logger.info("✅ База данных инициализирована")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

def ensure_database():
    global db, fm, report_gen
    if db is not None:
        try:
            db.get_publications(0, limit=1)
            return True
        except Exception as e:
            logger.warning(f"⚠️ БД потеряла соединение: {e}")
            db = None
            fm = None
            report_gen = None
    return init_database()

# Инициализируем БД
init_database()

# ========== ДИАГНОСТИЧЕСКАЯ ФУНКЦИЯ ==========
def log_request():
    if logger.level <= logging.DEBUG:
        logger.debug("=" * 80)
        logger.debug(f"📥 {request.method} {request.path}")

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
    return jsonify({'success': False, 'message': f'Маршрут не найден: {request.path}'}), 404

@app.errorhandler(400)
def bad_request(e):
    return jsonify({'success': False, 'message': f'Некорректный запрос: {str(e)}'}), 400

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'message': 'Файл слишком большой. Максимальный размер: 200 МБ'}), 413

@app.errorhandler(504)
def gateway_timeout(e):
    return jsonify({'success': False, 'message': 'Таймаут обработки запроса. Попробуйте позже.'}), 504

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
    """Принимает FormData и создает задачи в RQ (ОПТИМИЗИРОВАННАЯ ВЕРСИЯ)"""
    log_request()
    
    try:
        logger.info("=" * 60)
        logger.info("📥 НАЧАЛО ОБРАБОТКИ /upload_folders")
        
        if request.method == 'OPTIONS':
            return '', 200
        
        # Проверка Content-Type
        if not request.content_type or 'multipart/form-data' not in request.content_type:
            return jsonify({'success': False, 'message': 'Ожидается multipart/form-data'}), 400
        
        # Проверка user_id
        user_id = request.form.get('user_id', type=int)
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        max_photos = request.form.get('max_photos', 6, type=int)
        max_photos = max(1, min(10, max_photos))
        
        # Проверка Redis
        if not ensure_redis():
            return jsonify({'success': False, 'message': 'Очередь недоступна'}), 503
        
        # Проверка БД
        if not ensure_database():
            return jsonify({'success': False, 'message': 'База данных недоступна'}), 503
        
        # Получаем информацию о папках
        folders_info = request.form.getlist('folders[]')
        logger.info(f"📁 Получено папок: {len(folders_info)}")
        
        if not folders_info:
            return jsonify({'success': False, 'message': 'Нет данных о папках'}), 400
        
        # Ограничиваем количество папок
        MAX_FOLDERS = 50
        if len(folders_info) > MAX_FOLDERS:
            logger.warning(f"⚠️ Слишком много папок: {len(folders_info)}, ограничено {MAX_FOLDERS}")
            folders_info = folders_info[:MAX_FOLDERS]
        
        job_ids = []
        errors = []
        total_images_processed = 0
        total_size_processed = 0
        
        # Обрабатываем каждую папку
        start_time = time.time()
        MAX_PROCESSING_TIME = 20  # 20 секунд на подготовку
        
        for idx, folder_json in enumerate(folders_info):
            # Проверка таймаута
            if time.time() - start_time > MAX_PROCESSING_TIME:
                logger.warning(f"⏱️ Таймаут подготовки, обработано {idx} из {len(folders_info)}")
                break
            
            try:
                folder_data = json.loads(folder_json)
                folder_name = folder_data.get('name', f'folder_{idx}')
                ad_text = folder_data.get('adText', '')
                image_count = folder_data.get('imageCount', 0)
                
                # Валидация
                if not isinstance(image_count, int) or image_count < 0:
                    image_count = 0
                image_count = min(image_count, max_photos)
                
                # Ограничение размера: не более 5 МБ на изображение
                MAX_IMAGE_SIZE = 5 * 1024 * 1024
                
                images = []
                if image_count > 0:
                    for i in range(image_count):
                        field_name = f'images_{folder_name}_{i}'
                        if field_name in request.files:
                            try:
                                img_file = request.files[field_name]
                                if img_file and img_file.filename:
                                    img_data = img_file.read()
                                    
                                    # Проверка размера
                                    if len(img_data) > MAX_IMAGE_SIZE:
                                        logger.warning(f"⚠️ Изображение {img_file.filename} слишком большое: {len(img_data)} байт")
                                        continue
                                    
                                    if img_data and len(img_data) > 0:
                                        # Используем base64 вместо list()
                                        img_base64 = base64.b64encode(img_data).decode('ascii')
                                        
                                        images.append({
                                            'name': img_file.filename,
                                            'data': img_base64,
                                            'type': img_file.content_type or 'image/jpeg',
                                            'size': len(img_data)
                                        })
                                        
                                        total_images_processed += 1
                                        total_size_processed += len(img_data)
                                        logger.info(f"  ✅ Изобр {i+1}: {img_file.filename} ({len(img_data)} байт)")
                                        
                                        # Освобождаем память
                                        del img_data
                            except Exception as e:
                                logger.error(f"❌ Ошибка чтения изображения {i}: {e}")
                                continue
                
                # Разделяем текст
                metadata_text = ''
                if '#изъятая' in ad_text:
                    parts = ad_text.split('#изъятая')
                    ad_text = parts[0].strip()
                    metadata_text = parts[1] if len(parts) > 1 else ''
                
                # Ограничиваем размер данных в задаче
                MAX_TASK_SIZE = 50 * 1024 * 1024  # 50 МБ на задачу
                
                folder_payload = {
                    'folderName': folder_name[:100],
                    'adText': ad_text[:5000],
                    'metadataText': metadata_text[:1000],
                    'images': images[:max_photos]
                }
                
                # Проверяем размер задачи
                task_size = len(json.dumps(folder_payload))
                if task_size > MAX_TASK_SIZE:
                    logger.warning(f"⚠️ Задача {folder_name} слишком большая: {task_size} байт, уменьшаем")
                    folder_payload['images'] = images[:3]
                
                # Создаем задачу с таймаутом
                job = queue.enqueue(
                    process_folder_task,
                    user_id,
                    folder_payload,
                    job_id=None,
                    result_ttl=3600,
                    failure_ttl=3600,
                    timeout=600  # 10 минут на задачу
                )
                job_ids.append(job.id)
                logger.info(f"  ✅ Задача {job.id}: {folder_name} ({len(images)} фото)")
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ Ошибка парсинга JSON папки {idx}: {e}")
                errors.append(f"Папка {idx}: ошибка формата")
                continue
            except Exception as e:
                logger.error(f"❌ Ошибка обработки папки {idx}: {e}")
                errors.append(f"Папка {idx}: {str(e)[:50]}")
                continue
        
        logger.info(f"📊 ИТОГО: {len(job_ids)} задач, {total_images_processed} фото, {total_size_processed/1024/1024:.2f} МБ")
        
        response = {
            'success': True,
            'message': f'Создано {len(job_ids)} задач',
            'job_ids': job_ids,
            'total_folders': len(job_ids),
            'total_images': total_images_processed,
            'total_size_mb': round(total_size_processed / 1024 / 1024, 2)
        }
        
        if errors:
            response['warnings'] = errors[:5]
        
        logger.info("=" * 60)
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500

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
        start_time = time.time()
        MAX_STATUS_TIME = 5  # 5 секунд
        
        for job_id in job_ids:
            if time.time() - start_time > MAX_STATUS_TIME:
                logger.warning("⏱️ Таймаут получения статусов")
                break
            
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                status = {
                    'status': job.get_status(),
                    'created_at': job.created_at.isoformat() if job.created_at else None,
                }
                
                if job.is_finished:
                    status['result'] = job.return_value()
                elif job.is_failed:
                    status['error'] = str(job.exc_info) if job.exc_info else 'Unknown error'
                
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
    if not ensure_database():
        return "❌ База данных недоступна", 503
    
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
        if not ensure_database():
            return "❌ База данных недоступна", 503
        
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
    redis_status = False
    try:
        if redis_conn:
            redis_conn.ping()
            redis_status = True
    except:
        pass
    
    db_status = db is not None
    
    return {
        "status": "ok" if (redis_status and db_status) else "degraded",
        "timestamp": datetime.now().isoformat(),
        "redis": redis_status,
        "database": db_status,
        "queue": queue is not None,
        "token": bool(TOKEN)
    }

@app.route('/status')
def status():
    redis_status = False
    try:
        if redis_conn:
            redis_conn.ping()
            redis_status = True
    except:
        pass
    
    return {
        "status": "running",
        "token_set": bool(TOKEN),
        "redis_connected": redis_status,
        "queue_available": queue is not None,
        "database_available": db is not None,
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
    return jsonify({'routes': routes, 'total': len(routes)})

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
            2️⃣ В каждой подпапке: info.txt и фото (макс 10)<br>
            3️⃣ Используйте разделитель #изъятая<br>
            4️⃣ Перетащите головную папку в поле ниже<br>
            5️⃣ Изображения будут сжаты автоматически
        </div>
        
        <div class="settings-section">
            <h4>⚙️ Настройки</h4>
            <label>📸 Максимум фото: <input type="number" id="maxPhotos" value="6" min="1" max="10"></label>
            <label>⏱️ Задержка (сек): <input type="number" id="delayBetween" value="3" min="1" max="30"></label>
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
        // ========== КЛИЕНТСКИЙ КОД ==========
        const userId = new URLSearchParams(window.location.search).get('user_id') || 151296248;
        let selectedFiles = [];
        let isProcessing = false;
        let folderQueue = [];
        let jobIds = [];
        let totalFolders = 0;
        let jobStatusInterval = null;
        
        const MAX_FOLDERS = 50;
        const MAX_IMAGES_PER_FOLDER = 10;
        const MAX_IMAGE_SIZE_MB = 5;
        
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
                            let pending = allEntries.length;
                            if (pending === 0) { callback(); return; }
                            
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
                    });
                }
                readEntries();
            } else {
                entry.file((file) => {
                    file.webkitRelativePath = path + file.name;
                    files.push(file);
                    callback();
                });
            }
        }

        // ========== ОБРАБОТЧИКИ DROP ==========
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
                if (file.size > 20 * 1024 * 1024) {
                    reject(new Error(`Файл слишком большой: ${(file.size/1024/1024).toFixed(1)} МБ`));
                    return;
                }
                
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
            
            if (sortedFolders.length > MAX_FOLDERS) {
                showStatus('warning', `⚠️ Слишком много папок: ${sortedFolders.length} (макс ${MAX_FOLDERS})`);
                sortedFolders = sortedFolders.slice(0, MAX_FOLDERS);
            }
            
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

        // ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
        function updateQueueStatus() {
            const total = folderQueue.length;
            const done = folderQueue.filter(f => f.status === 'done').length;
            const errors = folderQueue.filter(f => f.status === 'error').length;
            queueStatus.textContent = isProcessing ? `🔄 ${done+errors}/${total}` : `📋 ${done}/${total}`;
            if (errors > 0) queueStatus.textContent += ` ⚠️${errors}`;
        }

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

        function getReport() { window.open(`/report/${userId}`, '_blank'); }

        function clearFiles() {
            if (isProcessing && !confirm('Остановить публикацию и очистить?')) return;
            selectedFiles = []; folderQueue = []; jobIds = [];
            fileList.style.display = 'none'; statusDiv.style.display = 'none';
            progressBar.style.display = 'none'; logDiv.style.display = 'none';
            progress.style.width = '0%'; progress.textContent = '0%';
            folderInput.value = '';
            if (jobStatusInterval) { clearInterval(jobStatusInterval); jobStatusInterval = null; }
        }

        function stopPublish() {
            isProcessing = false;
            addLog('⏹️ Остановка...');
            if (jobStatusInterval) { clearInterval(jobStatusInterval); jobStatusInterval = null; }
            fetch('/stop_publish', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(userId), job_ids: jobIds })
            }).catch(e => console.error(e));
        }

        // ========== МОНИТОРИНГ ЗАДАЧ ==========
        function startJobMonitoring() {
            if (jobStatusInterval) clearInterval(jobStatusInterval);
            
            let checkCount = 0;
            const MAX_CHECKS = 60;
            
            jobStatusInterval = setInterval(async () => {
                try {
                    checkCount++;
                    
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
                            if (s.status === 'finished') { 
                                finished++; 
                                if (s.result && s.result.success) done++; 
                                else failed++; 
                            }
                            else if (s.status === 'failed') failed++;
                        }
                    });
                    
                    const total = jobIds.length;
                    const pct = total > 0 ? Math.round(((done + failed) / total) * 100) : 0;
                    progress.style.width = pct + '%';
                    progress.textContent = pct + '%';
                    
                    if (finished >= total) {
                        clearInterval(jobStatusInterval);
                        jobStatusInterval = null;
                        isProcessing = false;
                        
                        if (failed === 0 && done === total) {
                            showStatus('success', `✅ Загружено ${done} папок!`);
                            addLog(`✅ ВСЕ ${done} папок загружены!`);
                        } else {
                            showStatus('warning', `⚠️ Загружено ${done} папок, ${failed} с ошибками`);
                            addLog(`⚠️ Загружено ${done} папок, ${failed} с ошибками`);
                        }
                        if (done > 0) addLog(`📊 Отчет: /report/${userId}`);
                    } else if (checkCount > MAX_CHECKS) {
                        clearInterval(jobStatusInterval);
                        jobStatusInterval = null;
                        isProcessing = false;
                        showStatus('warning', `⏱️ Таймаут мониторинга. Проверьте статус позже.`);
                        addLog(`⏱️ Мониторинг остановлен после ${MAX_CHECKS} проверок`);
                    }
                } catch(e) { 
                    console.error(e);
                }
            }, 2000);
        }

        // ========== ОСНОВНАЯ ФУНКЦИЯ ЗАГРУЗКИ ==========
        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку');
                return;
            }
            if (isProcessing) {
                addLog('⚠️ Уже выполняется');
                return;
            }
            
            isProcessing = true;
            jobIds = [];
            const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 6;
            
            const formData = new FormData();
            formData.append('user_id', userId);
            formData.append('max_photos', maxPhotos);
            
            const folders = {};
            selectedFiles.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 3) {
                    const key = parts[0] + '/' + parts.slice(1, -1).join('/');
                    if (!folders[key]) folders[key] = [];
                    folders[key].push(f);
                } else if (parts.length === 2) {
                    if (!folders[parts[0]]) folders[parts[0]] = [];
                    folders[parts[0]].push(f);
                }
            });
            
            const folderNames = Object.keys(folders);
            totalFolders = folderNames.length;
            
            if (totalFolders > MAX_FOLDERS) {
                showStatus('error', `❌ Слишком много папок: ${totalFolders} (макс ${MAX_FOLDERS})`);
                isProcessing = false;
                return;
            }
            
            folderQueue = folderNames.map(n => ({ name: n, status: 'pending' }));
            updateQueueStatus();
            
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            progress.textContent = '0%';
            logDiv.textContent = '';
            addLog(`🚀 Загрузка ${totalFolders} папок...`);
            
            let totalImages = 0;
            
            for (const folderName of folderNames) {
                const files = folders[folderName];
                
                let infoFile = null;
                let imageFiles = [];
                
                for (const f of files) {
                    const name = f.name.toLowerCase();
                    if (name.endsWith('.txt') && name.includes('info')) {
                        infoFile = f;
                    } else if (name.match(/\\.(jpg|jpeg|png|gif|bmp|webp)$/)) {
                        if (f.size > MAX_IMAGE_SIZE_MB * 1024 * 1024) {
                            addLog(`⚠️ ${f.name} слишком большой (${(f.size/1024/1024).toFixed(1)} МБ), пропускаем`);
                            continue;
                        }
                        imageFiles.push(f);
                    }
                }
                
                if (!infoFile) {
                    addLog(`⚠️ Нет info.txt в ${folderName}`);
                    continue;
                }
                
                const selectedImages = imageFiles.slice(0, Math.min(maxPhotos, MAX_IMAGES_PER_FOLDER));
                addLog(`📂 ${folderName}: ${selectedImages.length} фото`);
                
                const compressed = [];
                for (let i = 0; i < selectedImages.length; i++) {
                    try {
                        addLog(`📸 Сжатие ${i+1}/${selectedImages.length}: ${selectedImages[i].name}`);
                        const img = await compressImage(selectedImages[i], 1920, 1920, 0.85);
                        compressed.push(img);
                        totalImages++;
                    } catch(e) {
                        addLog(`⚠️ Ошибка сжатия: ${e.message}`);
                    }
                }
                
                const infoContent = await infoFile.text();
                
                formData.append('folders[]', JSON.stringify({
                    name: folderName,
                    adText: infoContent.substring(0, 5000),
                    imageCount: compressed.length
                }));
                
                for (let i = 0; i < compressed.length; i++) {
                    formData.append(`images_${folderName}_${i}`, compressed[i], compressed[i].name);
                }
            }
            
            addLog(`📤 Отправка ${totalImages} изображений...`);
            
            try {
                const resp = await fetch('/upload_folders', { method: 'POST', body: formData });
                if (!resp.ok) {
                    const t = await resp.text();
                    throw new Error(`HTTP ${resp.status}: ${t.substring(0, 200)}`);
                }
                const result = await resp.json();
                if (!result.success) throw new Error(result.message || 'Ошибка');
                
                jobIds = result.job_ids || [];
                addLog(`✅ Создано ${jobIds.length} задач (${result.total_images || 0} фото, ${result.total_size_mb || 0} МБ)`);
                
                if (jobIds.length > 0) {
                    startJobMonitoring();
                } else {
                    isProcessing = false;
                    showStatus('error', '❌ Не создано задач');
                }
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
    app.run(host='0.0.0.0', port=port, debug=False)
