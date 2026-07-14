from flask import Flask, request, jsonify, render_template_string
from maxapi import MaxApi
import logging
import os
from datetime import datetime
import threading

# Импорты ваших модулей
from database import Database
from file_manager import FileManager
from publisher import Publisher
from web_interface import WebInterface
from download_handler import DownloadHandler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация
app = Flask(__name__)
db = Database()
fm = FileManager()

# Инициализация API (настройте под свой токен)
api = MaxApi(token=os.environ.get('MAX_API_TOKEN', 'YOUR_TOKEN'))

# Инициализация Publisher
publisher = Publisher(api, fm, db)

# Инициализация DownloadHandler
download_handler = DownloadHandler()

# Инициализация WebInterface
web_interface = WebInterface(fm, publisher, download_handler)

@app.route('/')
def index():
    return web_interface.upload_page()

@app.route('/upload_folder', methods=['POST'])
def upload_folder():
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
    """Роут для скачивания отчета"""
    return web_interface.download_report(user_id, filename)

@app.route('/status')
def status():
    """Проверка статуса бота"""
    return jsonify({
        'status': 'running',
        'time': datetime.now().isoformat()
    })

# Фоновая очистка старых файлов
def cleanup_thread():
    """Периодическая очистка файлов с истекшим сроком"""
    while True:
        import time
        time.sleep(300)  # Каждые 5 минут
        try:
            download_handler.cleanup_expired_files()
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")

# Запускаем поток очистки
cleanup = threading.Thread(target=cleanup_thread, daemon=True)
cleanup.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
