import logging
import os
import time
import re
import base64
from enum import Enum
from PIL import Image, ExifTags
import io
from flask import Flask, request, jsonify, render_template_string

# Импорты из modules
from modules.database import Database
from modules.file_manager import FileManager
from modules.publisher import Publisher  # ← ИСПОЛЬЗУЕМ Publisher ИЗ modules
from modules.web_interface import WebInterface
from modules.process_links import *

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
        # Пробуем разные варианты
        if hasattr(maxapi, 'Bot'):
            api = maxapi.Bot(token=token)
            logger.info("✅ MAX API инициализирован через класс: Bot")
            return api
        elif hasattr(maxapi, 'MaxBotAPI'):
            api = maxapi.MaxBotAPI(token=token)
            logger.info("✅ MAX API инициализирован через класс: MaxBotAPI")
            return api
        else:
            logger.error("❌ Не найден подходящий класс в maxapi")
            return None
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
publisher = Publisher(api, fm, db)  # ← ИСПОЛЬЗУЕМ Publisher ИЗ modules
web_interface = WebInterface(fm, publisher)

# ========== ФУНКЦИИ ОТПРАВКИ ==========

def send_message(chat_id, text):
    """Отправка сообщения"""
    if not api:
        logger.warning(f"⚠️ API не инициализирован!")
        return False
    
    try:
        if hasattr(api, 'send_message'):
            api.send_message(chat_id, text)
        elif hasattr(api, 'sendMessage'):
            api.sendMessage(chat_id, text)
        else:
            logger.error(f"❌ Нет метода отправки!")
            return False
        
        logger.info(f"✅ Сообщение отправлено в {chat_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

# ========== ВЕБХУК ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхуков"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'status': 'ok'}), 200
        
        # Проверяем тип обновления
        update_type = data.get('update_type')
        
        # Только сообщения от пользователя
        if update_type != 'message_created':
            return jsonify({'status': 'ok'}), 200
        
        # Извлекаем данные из правильной структуры
        message = data.get('message', {})
        recipient = message.get('recipient', {})
        body = message.get('body', {})
        
        chat_id = recipient.get('chat_id')
        text = body.get('text', '')
        
        if not chat_id or not text:
            return jsonify({'status': 'ok'}), 200
        
        logger.info(f"📩 Сообщение от {chat_id}: {text}")
        
        # Обработка команд
        response = None
        
        if text.startswith('/start'):
            response = "👋 Привет! Я бот для публикации объявлений.\nИспользуйте /help для списка команд."
        
        elif text.startswith('/publish'):
            send_message(chat_id, "📢 Начинаю публикацию...")
            threading.Thread(target=publisher.start, args=(chat_id,)).start()
            return jsonify({'status': 'ok'}), 200
        
        elif text.startswith('/stop'):
            send_message(chat_id, "⏹️ Останавливаю публикацию...")
            publisher.stop(chat_id)
            return jsonify({'status': 'ok'}), 200
        
        elif text.startswith('/stop_global'):
            publisher.stop_global()
            response = "🛑 Глобальная остановка всех публикаций"
        
        elif text.startswith('/reset_global'):
            publisher.reset_global_stop()
            response = "🔄 Глобальный стоп сброшен"
        
        elif text.startswith('/status'):
            status = f"📊 Статус:\n"
            status += f"• Глобальный стоп: {'❌ ВКЛ' if publisher.global_stop else '✅ ВЫКЛ'}\n"
            status += f"• Публикация: {'🔄 активна' if publisher.running else '⏸️ не активна'}"
            response = status
        
        elif text.startswith('/help'):
            response = "🤖 Команды:\n"
            response += "/start - Приветствие\n"
            response += "/publish - Начать публикацию\n"
            response += "/stop - Остановить публикацию\n"
            response += "/status - Статус бота\n"
            response += "/stop_global - Глобальная остановка\n"
            response += "/reset_global - Сброс стопа"
        
        else:
            response = f"❓ Неизвестная команда. Используйте /help"
        
        if response:
            send_message(chat_id, response)
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка в вебхуке: {e}")
        return jsonify({'status': 'error'}), 500

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

@app.route('/status')
def status():
    return jsonify({
        'status': 'running',
        'api_available': api is not None,
        'global_stop': publisher.global_stop,
        'running': publisher.running
    })

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
