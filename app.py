import logging
import os
import time
import threading
import requests
from flask import Flask, request, jsonify, render_template_string

# Импорты из modules
from modules.database import Database
from modules.file_manager import FileManager
from modules.publisher import Publisher
from modules.web_interface import WebInterface

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================

def get_token():
    """Получает токен из переменных окружения"""
    return (
        os.environ.get('API_TOKEN') or
        os.environ.get('MAX_TOKEN') or
        os.environ.get('MAX_BOT_TOKEN')
    )

# ============================================
# ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
# ============================================

app = Flask(__name__)

db = Database()
fm = FileManager()

# Инициализируем Publisher (без API, будем использовать прямые HTTP запросы)
publisher = Publisher(None, fm, db)  # ← api = None
web_interface = WebInterface(fm, publisher)

# ========== ОТПРАВКА СООБЩЕНИЙ (ЧЕРЕЗ HTTP) ==========

def send_message(chat_id, text):
    """Отправка сообщения через прямой HTTP запрос (БЕЗ asyncio)"""
    token = get_token()
    if not token:
        logger.warning(f"⚠️ Токен не найден!")
        return False
    
    try:
        url = "https://platform-api2.max.ru/messages"
        headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }
        json_data = {
            "chat_id": chat_id,
            "text": text,
        }
        
        logger.info(f"📤 Отправка в {chat_id}: {text[:30]}...")
        response = requests.post(url, headers=headers, json=json_data, timeout=30)
        
        if response.status_code == 200:
            logger.info(f"✅ Сообщение отправлено в {chat_id}")
            return True
        else:
            logger.error(f"❌ Ошибка API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

# ========== ВЕБХУК ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхуков"""
    try:
        data = request.get_json()
        logger.info(f"📨 Получен вебхук")
        
        if not data:
            return jsonify({'status': 'ok'}), 200
        
        update_type = data.get('update_type')
        
        # Пропускаем не-сообщения
        if update_type != 'message_created':
            return jsonify({'status': 'ok'}), 200
        
        message = data.get('message', {})
        recipient = message.get('recipient', {})
        body = message.get('body', {})
        
        chat_id = recipient.get('chat_id')
        text = body.get('text', '')
        
        if not chat_id or not text:
            return jsonify({'status': 'ok'}), 200
        
        logger.info(f"📩 Сообщение от {chat_id}: {text}")
        
        response = None
        
        if text.startswith('/start'):
            response = "👋 Привет! Я бот для публикации объявлений.\nИспользуйте /help для списка команд."
        
        elif text.startswith('/publish'):
            send_message(chat_id, "📢 Начинаю однократную публикацию...")
            threading.Thread(target=publisher.start, args=(chat_id,)).start()
            return jsonify({'status': 'ok'}), 200
        
        elif text.startswith('/stop'):
            send_message(chat_id, "⏹️ Останавливаю публикацию...")
            publisher.stop(chat_id)
            return jsonify({'status': 'ok'}), 200
        
        elif text.startswith('/stop_global'):
            publisher.stop_global()
            response = "🛑 Глобальная остановка ВСЕХ публикаций"
        
        elif text.startswith('/reset_global'):
            publisher.reset_global_stop()
            response = "🔄 Глобальный стоп сброшен"
        
        elif text.startswith('/status'):
            status = f"📊 Статус:\n"
            status += f"• Глобальный стоп: {'❌ ВКЛ' if publisher.global_stop else '✅ ВЫКЛ'}\n"
            status += f"• Публикация: {'🔄 активна' if publisher.running else '⏸️ не активна'}\n"
            status += f"• Автоматическая публикация: ⏸️ ОТКЛЮЧЕНА"
            response = status
        
        elif text.startswith('/help'):
            response = "🤖 Команды:\n"
            response += "/start - Приветствие\n"
            response += "/publish - ОДНОКРАТНАЯ публикация\n"
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
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error'}), 500

@app.route('/webhook', methods=['GET'])
def webhook_get():
    return jsonify({'status': 'ok'}), 200

# ========== ВЕБ-ИНТЕРФЕЙС ==========

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
        'global_stop': publisher.global_stop,
        'running': publisher.running,
        'auto_publish': False
    })

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    logger.info("=" * 50)
    logger.info("🚀 БОТ ЗАПУЩЕН!")
    logger.info("📌 АВТОМАТИЧЕСКАЯ ПУБЛИКАЦИЯ ОТКЛЮЧЕНА")
    logger.info("📌 Используйте /publish для однократной публикации")
    logger.info("📌 Нужен вебхук в MAX: https://ваш-домен/webhook")
    logger.info("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
