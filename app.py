# app.py - ПОЛНАЯ ВЕРСИЯ С ДИАГНОСТИКОЙ

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
    level=getattr(logging, os.environ.get("LOG_LEVEL", "DEBUG")),  # Включаем DEBUG
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

# ========== ДИАГНОСТИЧЕСКИЙ ДЕКОРАТОР ==========
def log_request_response(f):
    """Декоратор для логирования всех запросов и ответов"""
    def wrapper(*args, **kwargs):
        # Логируем запрос
        logger.info("=" * 80)
        logger.info(f"📥 {request.method} {request.path}")
        logger.info(f"📋 Headers: {dict(request.headers)}")
        logger.info(f"📋 Content-Type: {request.content_type}")
        logger.info(f"📋 Content-Length: {request.content_length}")
        logger.info(f"📋 Remote Addr: {request.remote_addr}")
        logger.info(f"📋 User-Agent: {request.headers.get('User-Agent', 'Unknown')}")
        
        # Логируем параметры
        if request.args:
            logger.info(f"📋 Args: {dict(request.args)}")
        if request.form:
            logger.info(f"📋 Form: {dict(request.form)}")
        if request.files:
            logger.info(f"📋 Files: {list(request.files.keys())}")
            for key, files in request.files.items():
                for file in files:
                    logger.info(f"   📎 {key}: {file.filename} ({file.content_type}) - {file.content_length if hasattr(file, 'content_length') else 'unknown'} bytes")
        
        # Логируем тело запроса (если это JSON)
        if request.is_json:
            try:
                logger.info(f"📋 JSON: {json.dumps(request.json, ensure_ascii=False, indent=2)[:1000]}")
            except:
                logger.info(f"📋 JSON: {request.data[:500]}")
        
        # Выполняем запрос
        start_time = time.time()
        try:
            response = f(*args, **kwargs)
            elapsed = time.time() - start_time
            
            # Логируем ответ
            logger.info(f"📤 Response: {response[1] if isinstance(response, tuple) else 'OK'}")
            logger.info(f"⏱️ Время выполнения: {elapsed:.3f} сек")
            
            # Если ответ - JSON, логируем его
            if isinstance(response, tuple) and len(response) > 0:
                if isinstance(response[0], dict):
                    logger.info(f"📤 JSON Response: {json.dumps(response[0], ensure_ascii=False, indent=2)[:500]}")
            
            logger.info("=" * 80)
            return response
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Ошибка: {e}")
            logger.error(traceback.format_exc())
            logger.info("=" * 80)
            raise
            
    return wrapper

# ========== ОБРАБОТЧИКИ ОШИБОК ==========
@app.errorhandler(Exception)
def handle_exception(e):
    """Обработка всех необработанных исключений"""
    logger.error(f"❌ Необработанная ошибка: {e}")
    logger.error(traceback.format_exc())
    return jsonify({
        'success': False,
        'message': f'Внутренняя ошибка сервера: {str(e)}',
        'error_type': type(e).__name__
    }), 500

@app.errorhandler(404)
def not_found(e):
    """Обработка 404"""
    logger.warning(f"⚠️ 404: {request.path}")
    return jsonify({
        'success': False,
        'message': f'Маршрут не найден: {request.path}',
        'available_routes': [str(rule) for rule in app.url_map.iter_rules()]
    }), 404

@app.errorhandler(400)
def bad_request(e):
    """Обработка 400"""
    logger.warning(f"⚠️ 400: {e}")
    return jsonify({
        'success': False,
        'message': f'Некорректный запрос: {str(e)}'
    }), 400

@app.errorhandler(413)
def too_large(e):
    """Обработка слишком большого запроса"""
    return jsonify({
        'success': False,
        'message': 'Файл слишком большой. Максимальный размер: 200 МБ'
    }), 413

# ========== МАРШРУТЫ ==========

@app.route('/', methods=['GET'])
@log_request_response
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
@log_request_response
def upload_page():
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_folders', methods=['POST', 'OPTIONS'])
@log_request_response
def upload_folders():
    """Принимает FormData с файлами и создает задачи в RQ"""
    try:
        logger.info("=" * 60)
        logger.info("📥 НАЧАЛО ОБРАБОТКИ /upload_folders")
        
        # Проверяем метод
        if request.method == 'OPTIONS':
            logger.info("📋 OPTIONS запрос - отправляем CORS")
            return '', 200
        
        # Проверяем Content-Type
        if not request.content_type or 'multipart/form-data' not in request.content_type:
            logger.error(f"❌ Неверный Content-Type: {request.content_type}")
            return jsonify({
                'success': False, 
                'message': f'Ожидается multipart/form-data, получено: {request.content_type}'
            }), 400
        
        # Получаем данные
        logger.info("📋 Получение данных из формы...")
        user_id = request.form.get('user_id', type=int)
        max_photos = request.form.get('max_photos', 6, type=int)
        delay_between = request.form.get('delay_between', 3, type=int)
        total_folders = request.form.get('total_folders', 0, type=int)
        
        logger.info(f"👤 user_id: {user_id} (тип: {type(user_id)})")
        logger.info(f"📸 max_photos: {max_photos}")
        logger.info(f"⏱️ delay_between: {delay_between}")
        logger.info(f"📊 total_folders: {total_folders}")
        
        if not user_id:
            logger.error("❌ Нет user_id")
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        # Получаем файлы
        logger.info("📁 Получение файлов из запроса...")
        files = request.files.getlist('files[]')
        logger.info(f"📁 Получено файлов: {len(files)}")
        
        # Логируем каждый файл
        for i, file in enumerate(files):
            logger.info(f"  📎 Файл {i+1}: {file.filename}")
            logger.info(f"     Content-Type: {file.content_type}")
            logger.info(f"     Content-Length: {file.content_length if hasattr(file, 'content_length') else 'unknown'}")
            logger.info(f"     Headers: {dict(file.headers) if hasattr(file, 'headers') else 'N/A'}")
        
        if not files:
            logger.error("❌ Нет файлов")
            return jsonify({'success': False, 'message': 'Нет файлов'}), 400
        
        # Проверяем очередь
        if queue is None:
            logger.error("❌ Очередь недоступна")
            return jsonify({'success': False, 'message': 'Очередь недоступна'}), 500
        
        # Группируем файлы по папкам
        logger.info("📂 Группировка файлов по папкам...")
        folders = {}
        for file in files:
            file_path = file.filename
            logger.info(f"  📄 Обработка: {file_path}")
            
            if '/' in file_path:
                # Извлекаем имя папки из пути
                folder_name = file_path.split('/')[0]
                # Убираем возможный префикс с номером
                if ' -' in folder_name:
                    folder_name = folder_name.split(' -')[0]
                elif ' -' in folder_name:
                    folder_name = folder_name.split(' -')[0]
                
                logger.info(f"  📁 Папка: {folder_name}")
                
                if folder_name not in folders:
                    folders[folder_name] = []
                folders[folder_name].append(file)
            else:
                logger.warning(f"  ⚠️ Файл без пути: {file_path}")
        
        logger.info(f"📁 Найдено {len(folders)} папок")
        for folder_name, folder_files in folders.items():
            logger.info(f"  📁 {folder_name}: {len(folder_files)} файлов")
        
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
            other_files = []
            
            for f in folder_files:
                filename = f.filename.lower()
                if filename.endswith('.txt') and ('info' in filename or 'readme' in filename):
                    info_file = f
                    logger.info(f"  📄 Найден info.txt: {f.filename}")
                elif filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                    image_files.append(f)
                    logger.info(f"  🖼️ Найдено изображение: {f.filename}")
                else:
                    other_files.append(f)
                    logger.info(f"  📎 Другой файл: {f.filename}")
            
            if not info_file:
                logger.warning(f"⚠️ Нет info.txt в папке {folder_name}")
                continue
            
            # Читаем текст
            try:
                info_content = info_file.read().decode('utf-8')
                logger.info(f"📝 info.txt прочитан: {len(info_content)} символов")
                logger.info(f"📝 Содержимое info.txt:\n{info_content[:500]}...")
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
                logger.info(f"✂️ Разделен текст: {len(ad_text)} символов до #изъятая, {len(metadata_text)} после")
                logger.info(f"📝 Текст для публикации (первые 200 символов):\n{ad_text[:200]}...")
                logger.info(f"📝 Метаданные (первые 200 символов):\n{metadata_text[:200]}...")
            else:
                logger.info("ℹ️ Разделитель #изъятая не найден, весь текст идет в публикацию")
            
            # Ограничиваем количество фото
            image_files = image_files[:max_photos]
            logger.info(f"🖼️ Изображений для загрузки: {len(image_files)} (максимум {max_photos})")
            
            # Читаем изображения
            images = []
            for img_file in image_files:
                try:
                    logger.info(f"📖 Чтение изображения: {img_file.filename}")
                    img_data = img_file.read()
                    logger.info(f"  📊 Размер: {len(img_data)} байт")
                    
                    # Проверяем размер
                    if len(img_data) > 20 * 1024 * 1024:  # 20 МБ
                        logger.warning(f"  ⚠️ Изображение слишком большое: {len(img_data)} байт")
                    
                    images.append({
                        'name': img_file.filename,
                        'data': list(img_data)[:100] + ['...'] if len(img_data) > 100 else list(img_data),  # Для логов
                        'type': img_file.content_type or 'image/jpeg',
                        'size': len(img_data)
                    })
                    logger.info(f"  ✅ Изображение загружено: {img_file.filename} ({len(img_data)} байт)")
                except Exception as e:
                    logger.error(f"❌ Ошибка чтения {img_file.filename}: {e}")
            
            # Подготавливаем данные для задачи
            folder_data = {
                'folderName': folder_name,
                'adText': ad_text,
                'metadataText': metadata_text,
                'images': images,
                'image_count': len(images)
            }
            
            folder_data_list.append(folder_data)
            logger.info(f"✅ Папка {folder_name} подготовлена: {len(images)} изображений")
        
        if not folder_data_list:
            logger.error("❌ Нет данных для задач")
            return jsonify({'success': False, 'message': 'Нет данных для обработки'}), 400
        
        # Создаем задачи в RQ
        logger.info(f"📝 Создание {len(folder_data_list)} задач в RQ...")
        for i, folder_data in enumerate(folder_data_list):
            logger.info(f"  📝 Задача {i+1}: {folder_data['folderName']} ({folder_data['image_count']} фото)")
            
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
        
        logger.info(f"✅ Успешно создано {len(job_ids)} задач")
        logger.info("=" * 60)
        
        return jsonify({
            'success': True,
            'message': f'Создано {len(job_ids)} задач',
            'job_ids': job_ids,
            'total_folders': len(folder_data_list),
            'debug': {
                'files_received': len(files),
                'folders_found': len(folders),
                'tasks_created': len(job_ids)
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в upload_folders: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False, 
            'message': f'Ошибка: {str(e)}',
            'error_type': type(e).__name__,
            'traceback': traceback.format_exc().split('\n')[-10:]
        }), 500

@app.route('/job_status', methods=['POST'])
@log_request_response
def job_status():
    """Получение статуса задач"""
    try:
        data = request.get_json()
        job_ids = data.get('job_ids', [])
        
        logger.info(f"📊 Запрос статуса для {len(job_ids)} задач")
        
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
                logger.info(f"  📊 {job_id}: {status['status']}")
            except Exception as e:
                logger.warning(f"⚠️ Задача {job_id} не найдена: {e}")
                result[job_id] = {'status': 'unknown', 'error': str(e)}
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения статуса: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stop_publish', methods=['POST'])
@log_request_response
def stop_publish():
    """Остановка публикации"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        job_ids = data.get('job_ids', [])
        
        logger.info(f"⏹️ Остановка для пользователя {user_id}, задач: {len(job_ids)}")
        
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
@log_request_response
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
        
        # ... остальной код webhook ...
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

@app.route('/report/<int:user_id>')
@log_request_response
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
        <p><small>Отчет сгенерирован: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
    </body>
    </html>
    """

@app.route('/download_report/<int:user_id>/<path:filename>')
@log_request_response
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
@log_request_response
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "redis": redis_conn is not None,
        "queue": queue is not None,
        "token": bool(TOKEN)
    }

@app.route('/status')
@log_request_response
def status():
    return {
        "status": "running",
        "token_set": bool(TOKEN),
        "redis_connected": redis_conn is not None,
        "queue_available": queue is not None,
        "data_dir": DATA_DIR,
        "python_version": sys.version,
        "app_version": "2.0.0"
    }

@app.route('/routes')
@log_request_response
def list_routes():
    """Вывод всех доступных маршрутов для отладки"""
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
    <!-- ... ваш HTML код ... -->
</head>
<body>
    <!-- ... ваш HTML код ... -->
</body>
</html>
"""

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    # ПРЕДУПРЕЖДЕНИЕ: Это только для разработки!
    logger.warning("⚠️ ЗАПУСК В РЕЖИМЕ РАЗРАБОТКИ! Используйте Gunicorn для production!")
    logger.info(f"🚀 Запуск на http://0.0.0.0:{port}")
    logger.info("📋 Доступные маршруты:")
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.methods} {rule}")
    app.run(host='0.0.0.0', port=port, debug=True)  # Включаем debug для детальных ошибок
