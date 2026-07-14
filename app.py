from flask import Flask, request, jsonify, render_template_string
import logging
import os
import time
import threading
from datetime import datetime

# Импорты модулей
from modules.database import Database
from modules.file_manager import FileManager
from modules.publisher import Publisher
from modules.web_interface import WebInterface
from modules.download_handler import DownloadHandler

# НАСТРОЙКА MAX API - ИСПРАВЬТЕ ИМПОРТ
# Попробуйте один из вариантов:

# Вариант 1 (если класс называется MaxBotAPI)
from maxapi import MaxBotAPI as MaxApi

# Вариант 2 (если класс называется Client)
# from maxapi import Client as MaxApi

# Вариант 3 (если используется напрямую)
# import maxapi
# MaxApi = maxapi

logger = logging.getLogger(__name__)

# Инициализация Flask
app = Flask(__name__)

# Инициализация БД и менеджера файлов
db = Database()
fm = FileManager()

# Инициализация API
# Получаем токен из переменных окружения
TOKEN = os.environ.get('MAX_API_TOKEN', 'YOUR_TOKEN_HERE')
api = MaxApi(token=TOKEN)

# Инициализация Publisher
publisher = Publisher(api, fm, db)

# Инициализация DownloadHandler
download_handler = DownloadHandler()

# Инициализация WebInterface
web_interface = WebInterface(fm, publisher, download_handler)

# ========== РОУТЫ ==========

@app.route('/')
def index():
    """Главная страница - загрузка объявлений"""
    return web_interface.upload_page()

@app.route('/upload_folder', methods=['POST'])
def upload_folder():
    """Загрузка папок с объявлениями"""
    user_id = request.form.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id не указан'})
    
    try:
        user_id = int(user_id)
    except ValueError:
        return jsonify({'success': False, 'message': 'Неверный user_id'})
    
    result = web_interface.upload_file(request, user_id)
    return jsonify(result)

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    """Скачивание отчета"""
    return web_interface.download_report(user_id, filename)

@app.route('/status')
def status():
    """Проверка статуса бота"""
    return jsonify({
        'status': 'running',
        'time': datetime.now().isoformat(),
        'global_stop': publisher.global_stop
    })

# ========== ФОНОВЫЕ ЗАДАЧИ ==========

def cleanup_thread():
    """Периодическая очистка файлов с истекшим сроком"""
    while True:
        time.sleep(300)  # Каждые 5 минут
        try:
            download_handler.cleanup_expired_files()
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")

# Запускаем поток очистки
cleanup = threading.Thread(target=cleanup_thread, daemon=True)
cleanup.start()

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
