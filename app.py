from flask import Flask, request, jsonify
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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# ИНИЦИАЛИЗАЦИЯ MAX API (УНИВЕРСАЛЬНЫЙ ВАРИАНТ)
# ============================================

def init_max_api():
    """Универсальная инициализация MAX API"""
    token = os.environ.get('MAX_API_TOKEN')
    if not token:
        logger.error("❌ MAX_API_TOKEN не установлен в переменных окружения!")
        return None
    
    import maxapi
    
    # Пробуем разные варианты
    possible_classes = ['MaxBotAPI', 'MaxAPI', 'Client', 'ApiClient']
    
    for class_name in possible_classes:
        if hasattr(maxapi, class_name):
            try:
                api_class = getattr(maxapi, class_name)
                api = api_class(token=token)
                logger.info(f"✅ MAX API инициализирован через класс: {class_name}")
                return api
            except Exception as e:
                logger.warning(f"⚠️ Не удалось инициализировать через {class_name}: {e}")
    
    # Если не нашли - используем первый попавшийся класс
    for attr in dir(maxapi):
        if not attr.startswith('_') and callable(getattr(maxapi, attr)):
            try:
                api = getattr(maxapi, attr)(token=token)
                logger.info(f"✅ MAX API инициализирован через класс: {attr}")
                return api
            except:
                continue
    
    logger.error("❌ Не удалось инициализировать MAX API")
    return None

# ============================================
# ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
# ============================================

# Инициализация Flask
app = Flask(__name__)

# Инициализация БД и менеджера файлов
db = Database()
fm = FileManager()

# Инициализация API
api = init_max_api()
if api is None:
    logger.error("❌ MAX API не инициализирован. Бот не будет работать!")
    # Можно создать заглушку для тестирования
    class DummyApi:
        def send_message(self, user_id, text):
            logger.info(f"💬 [ЗАГЛУШКА] Сообщение для {user_id}: {text}")
            return True
        def send_photos_to_chat(self, chat_id, photo_files, text):
            logger.info(f"📸 [ЗАГЛУШКА] Фото в {chat_id}: {len(photo_files)} шт")
            return True
        def send_message_to_chat(self, chat_id, text):
            logger.info(f"💬 [ЗАГЛУШКА] Сообщение в {chat_id}: {text[:50]}...")
            return True
    api = DummyApi()

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
        'global_stop': publisher.global_stop if hasattr(publisher, 'global_stop') else False
    })

@app.route('/api/test')
def test_api():
    """Тестовый эндпоинт для проверки API"""
    try:
        import maxapi
        attrs = [attr for attr in dir(maxapi) if not attr.startswith('_')]
        return jsonify({
            'available_classes': attrs,
            'api_initialized': api is not None
        })
    except Exception as e:
        return jsonify({'error': str(e)})

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
    logger.info(f"🔧 MAX_API_TOKEN: {'установлен' if os.environ.get('MAX_API_TOKEN') else 'НЕ УСТАНОВЛЕН!'}")
    app.run(host='0.0.0.0', port=port, debug=False)
