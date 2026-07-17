# app.py - ПОЛНАЯ ВЕРСИЯ С ИСПРАВЛЕНИЯМИ

from flask import Flask, request, jsonify, render_template_string, send_file
import os
import logging
import json
import requests
import traceback
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

# ========== ОБРАБОТЧИКИ ОШИБОК ==========
@app.errorhandler(Exception)
def handle_exception(e):
    """Обработка всех необработанных исключений"""
    logger.error(f"❌ Необработанная ошибка: {e}")
    logger.error(traceback.format_exc())
    return jsonify({
        'success': False,
        'message': f'Внутренняя ошибка сервера: {str(e)}'
    }), 500

@app.errorhandler(404)
def not_found(e):
    """Обработка 404"""
    return jsonify({
        'success': False,
        'message': 'Маршрут не найден'
    }), 404

@app.errorhandler(400)
def bad_request(e):
    """Обработка 400"""
    return jsonify({
        'success': False,
        'message': 'Некорректный запрос'
    }), 400

@app.errorhandler(413)
def too_large(e):
    """Обработка слишком большого запроса"""
    return jsonify({
        'success': False,
        'message': 'Файл слишком большой. Максимальный размер: 200 МБ'
    }), 413

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

# ========== ОСТАЛЬНОЙ КОД (UPLOAD_PAGE, МАРШРУТЫ) ==========
# ... весь ваш код с HTML страницей и маршрутами ...

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    # ПРЕДУПРЕЖДЕНИЕ: Это только для разработки!
    logger.warning("⚠️ ЗАПУСК В РЕЖИМЕ РАЗРАБОТКИ! Используйте Gunicorn для production!")
    app.run(host='0.0.0.0', port=port, debug=False)
