from flask import Flask, request, jsonify
import logging
import os
import time
import threading
from datetime import datetime
import re
from PIL import Image, ExifTags
import io
from enum import Enum

# Импорты модулей
from modules.database import Database
from modules.file_manager import FileManager
from modules.publisher import Publisher  # ← ИСПОЛЬЗУЕМ publisher.py
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
    """Инициализация MAX API"""
    token = (
        os.environ.get('API_TOKEN') or
        os.environ.get('MAX_TOKEN') or
        os.environ.get('MAX_BOT_TOKEN')
    )
    
    if not token:
        logger.error("❌ Токен не найден!")
        return None
    
    logger.info(f"✅ Токен найден (первые 10): {token[:10]}...")
    
    try:
        import maxapi
        api = maxapi.Bot(token=token)  # ← ИСПОЛЬЗУЕМ Bot КАК В СТАРОМ КОДЕ
        logger.info("✅ MAX API инициализирован через класс: Bot")
        return api
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        return None

# ============================================
# ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
# ============================================

app = Flask(__name__)

db = Database()
fm = FileManager()
api = init_max_api()
publisher = Publisher(api, fm, db)  # ← ИСПОЛЬЗУЕМ publisher.py
download_handler = DownloadHandler()
web_interface = WebInterface(fm, publisher, download_handler)

# ========== ФУНКЦИИ ОТПРАВКИ ==========

def send_message(chat_id, text):
    """Отправка сообщения - КАК В СТАРОМ КОДЕ"""
    if api:
        try:
            # Используем метод как в старом app.py
            api.send_message(chat_id, text)
            logger.info(f"💬 Сообщение отправлено в {chat_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    else:
        logger.info(f"💬 [ДЕМО] {chat_id}: {text[:50]}...")
        return False

# ========== ВЕБХУКИ ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхуков - КАК В СТАРОМ КОДЕ"""
    try:
        data = request.get_json()
        logger.info(f"📨 Получен вебхук")
        
        if data and 'message' in data:
            message = data['message']
            chat_id = message.get('chat', {}).get('id')
            text = message.get('text', '')
            
            logger.info(f"📩 Сообщение от {chat_id}: {text}")
            
            if chat_id and text:
                if text.startswith('/start'):
                    send_message(chat_id, "👋 Привет! Я бот для публикации объявлений.")
                
                elif text.startswith('/publish'):
                    send_message(chat_id, "📢 Начинаю публикацию...")
                    threading.Thread(target=publisher.start, args=(chat_id,)).start()
                
                elif text.startswith('/stop'):
                    send_message(chat_id, "⏹️ Останавливаю публикацию...")
                    publisher.stop(chat_id)
                
                elif text.startswith('/stop_global'):
                    publisher.stop_global()
                    send_message(chat_id, "🛑 Глобальная остановка всех публикаций")
                
                elif text.startswith('/reset_global'):
                    publisher.reset_global_stop()
                    send_message(chat_id, "🔄 Глобальный стоп сброшен")
                
                elif text.startswith('/status'):
                    status = "📊 Статус:\n"
                    status += f"• Глобальный стоп: {'❌ ВКЛ' if publisher.global_stop else '✅ ВЫКЛ'}\n"
                    status += f"• Публикация: {'🔄 активна' if publisher.running else '⏸️ не активна'}"
                    send_message(chat_id, status)
                
                elif text.startswith('/report'):
                    send_message(chat_id, "📊 Создаю отчет...")
                    report_path = db.generate_report(chat_id)
                    if report_path and os.path.exists(report_path):
                        base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
                        filename = os.path.basename(report_path)
                        download_url = f"{base_url}/download_report/{chat_id}/{filename}"
                        send_message(chat_id, f"📊 Отчет создан!\n🔗 Скачать: {download_url}")
                    else:
                        send_message(chat_id, "❌ Нет данных для отчета")
                
                elif text.startswith('/help'):
                    response = "🤖 Команды:\n"
                    response += "/start - Приветствие\n"
                    response += "/publish - Начать публикацию\n"
                    response += "/stop - Остановить публикацию\n"
                    response += "/status - Статус бота\n"
                    response += "/report - Получить отчет\n"
                    response += "/stop_global - Глобальная остановка\n"
                    response += "/reset_global - Сброс стопа"
                    send_message(chat_id, response)
                
                else:
                    send_message(chat_id, f"❓ Неизвестная команда. Используйте /help")
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/webhook', methods=['GET'])
def webhook_get():
    return jsonify({'status': 'ok'}), 200

# ========== ОСТАЛЬНЫЕ РОУТЫ ==========

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
    return web_interface.download_report(user_id, filename)

@app.route('/status')
def status():
    return jsonify({
        'status': 'running',
        'time': datetime.now().isoformat(),
        'api_available': api is not None,
        'global_stop': publisher.global_stop,
        'running': publisher.running
    })

# ========== ФОНОВЫЕ ЗАДАЧИ ==========

def cleanup_thread():
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
    app.run(host='0.0.0.0', port=port, debug=False)
