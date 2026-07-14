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
# ИНИЦИАЛИЗАЦИЯ MAX API
# ============================================

def init_max_api():
    """Универсальная инициализация MAX API"""
    # Пробуем все возможные имена переменных
    token = (
        os.environ.get('API_TOKEN') or          # ← ОСНОВНОЙ ВАРИАНТ (ЕСТЬ!)
        os.environ.get('MAX_TOKEN') or          
        os.environ.get('MAX_API_TOKEN') or      
        os.environ.get('MAX_BOT_TOKEN')         
    )
    
    if not token:
        logger.error("❌ Токен не найден ни в одной переменной!")
        logger.info("🔍 Проверьте переменные: API_TOKEN, MAX_TOKEN, MAX_API_TOKEN, MAX_BOT_TOKEN")
        return None
    
    logger.info(f"✅ Токен найден в переменной (первые 10 символов): {token[:10]}...")
    logger.info(f"✅ Полный токен: {token[:20]}... (длина: {len(token)})")
    
    try:
        import maxapi
        # Пробуем разные варианты классов
        for class_name in ['MaxBotAPI', 'MaxAPI', 'Client', 'ApiClient']:
            if hasattr(maxapi, class_name):
                try:
                    api_class = getattr(maxapi, class_name)
                    api = api_class(token=token)
                    logger.info(f"✅ MAX API инициализирован через класс: {class_name}")
                    return api
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось через {class_name}: {e}")
        
        # Если не нашли - используем первый попавшийся класс
        for attr in dir(maxapi):
            if not attr.startswith('_') and callable(getattr(maxapi, attr)):
                try:
                    api = getattr(maxapi, attr)(token=token)
                    logger.info(f"✅ MAX API инициализирован через класс: {attr}")
                    return api
                except:
                    continue
        
        logger.error("❌ Не найден подходящий класс в maxapi")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации MAX API: {e}")
        return None

# ============================================
# ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
# ============================================

app = Flask(__name__)

# Инициализация БД и менеджера файлов
db = Database()
fm = FileManager()

# Инициализация API
api = init_max_api()

# Инициализация Publisher
publisher = Publisher(api, fm, db)

# Инициализация DownloadHandler
download_handler = DownloadHandler()

# Инициализация WebInterface
web_interface = WebInterface(fm, publisher, download_handler)

# ========== ВЕБХУКИ ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхуков от MAX платформы"""
    try:
        data = request.get_json()
        logger.info(f"📨 Получен вебхук: {data}")
        
        if data and 'message' in data:
            message = data['message']
            chat_id = message.get('chat', {}).get('id')
            text = message.get('text', '')
            
            if chat_id and text:
                # Обработка команд
                if text.startswith('/start'):
                    response = "👋 Привет! Я бот для публикации объявлений.\n"
                    response += "Используйте веб-интерфейс для загрузки объявлений."
                    send_message(chat_id, response)
                
                elif text.startswith('/publish'):
                    response = "📢 Начинаю публикацию..."
                    send_message(chat_id, response)
                    threading.Thread(target=publisher.start, args=(chat_id,)).start()
                
                elif text.startswith('/stop'):
                    response = "⏹️ Останавливаю публикацию..."
                    send_message(chat_id, response)
                    publisher.stop(chat_id)
                
                elif text.startswith('/stop_global'):
                    if is_admin(chat_id):
                        publisher.stop_global()
                        send_message(chat_id, "🛑 Глобальная остановка всех публикаций")
                    else:
                        send_message(chat_id, "⛔ У вас нет прав для этой команды")
                
                elif text.startswith('/reset_global'):
                    if is_admin(chat_id):
                        publisher.reset_global_stop()
                        send_message(chat_id, "🔄 Глобальный стоп сброшен")
                    else:
                        send_message(chat_id, "⛔ У вас нет прав для этой команды")
                
                elif text.startswith('/status'):
                    status = {
                        'global_stop': publisher.global_stop if hasattr(publisher, 'global_stop') else False,
                        'is_running': publisher.running if hasattr(publisher, 'running') else False
                    }
                    response = f"📊 Статус:\n"
                    response += f"• Глобальный стоп: {'✅ ВЫКЛ' if not status['global_stop'] else '❌ ВКЛ'}\n"
                    response += f"• Публикация: {'🔄 активна' if status['is_running'] else '⏸️ не активна'}"
                    send_message(chat_id, response)
                
                elif text.startswith('/report'):
                    response = "📊 Создаю отчет..."
                    send_message(chat_id, response)
                    report_path = db.generate_report(chat_id)
                    if report_path and os.path.exists(report_path):
                        base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
                        filename = os.path.basename(report_path)
                        download_url = f"{base_url}/download_report/{chat_id}/{filename}"
                        send_message(chat_id, f"📊 Отчет создан!\n🔗 Скачать: {download_url}")
                    else:
                        send_message(chat_id, "❌ Нет данных для отчета")
                
                else:
                    send_message(chat_id, f"❓ Неизвестная команда: {text}")
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/webhook', methods=['GET'])
def webhook_get():
    """GET для проверки вебхука"""
    return jsonify({'status': 'ok', 'message': 'Webhook is alive'}), 200

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def is_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    admin_ids = os.environ.get('ADMIN_IDS', '')
    if not admin_ids:
        return False
    return str(user_id) in admin_ids.split(',')

def send_message(chat_id, text):
    """Отправка сообщения"""
    if api:
        try:
            api.send_message(chat_id, text)
            logger.info(f"💬 Сообщение отправлено в {chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки сообщения: {e}")
    else:
        logger.info(f"💬 [ДЕМО] Сообщение для {chat_id}: {text}")

# ========== ОСТАЛЬНЫЕ РОУТЫ ==========

@app.route('/')
def index():
    """Главная страница"""
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
    token_vars = {
        'API_TOKEN': bool(os.environ.get('API_TOKEN')),
        'MAX_TOKEN': bool(os.environ.get('MAX_TOKEN')),
        'MAX_API_TOKEN': bool(os.environ.get('MAX_API_TOKEN')),
        'MAX_BOT_TOKEN': bool(os.environ.get('MAX_BOT_TOKEN')),
    }
    return jsonify({
        'status': 'running',
        'time': datetime.now().isoformat(),
        'api_available': api is not None,
        'token_variables': token_vars,
        'global_stop': publisher.global_stop if hasattr(publisher, 'global_stop') else False
    })

# ========== ФОНОВЫЕ ЗАДАЧИ ==========

def cleanup_thread():
    """Периодическая очистка файлов с истекшим сроком"""
    while True:
        time.sleep(300)
        try:
            download_handler.cleanup_expired_files()
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")

cleanup = threading.Thread(target=cleanup_thread, daemon=True)
cleanup.start()

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    
    # Проверяем все переменные с токенами
    logger.info("=== ПРОВЕРКА ПЕРЕМЕННЫХ С ТОКЕНАМИ ===")
    token_vars = ['API_TOKEN', 'MAX_TOKEN', 'MAX_API_TOKEN', 'MAX_BOT_TOKEN']
    for var in token_vars:
        value = os.environ.get(var)
        if value:
            logger.info(f"✅ {var}: установлен (длина: {len(value)}, начало: {value[:10]}...)")
        else:
            logger.info(f"❌ {var}: НЕ УСТАНОВЛЕН")
    logger.info("========================================")
    
    app.run(host='0.0.0.0', port=port, debug=False)
