import logging
import os
import time
import threading
from flask import Flask, request, jsonify, render_template_string

# Импорты из modules
from modules.database import Database
from modules.file_manager import FileManager
from modules.publisher import Publisher
from modules.web_interface import WebInterface
from max_client import MaxClient

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,  # ← ВКЛЮЧАЕМ DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

db = Database()
fm = FileManager()

# Инициализация клиента MAX
token = (
    os.environ.get('API_TOKEN') or
    os.environ.get('MAX_TOKEN') or
    os.environ.get('MAX_BOT_TOKEN')
)

if not token:
    logger.error("❌ Токен не найден!")
    client = None
else:
    logger.info(f"✅ Токен найден (первые 10): {token[:10]}...")
    client = MaxClient(token)

publisher = Publisher(client, fm, db)
web_interface = WebInterface(fm, publisher)

# ========== ВАШ РЕАЛЬНЫЙ USER_ID ==========
MY_USER_ID = 151296248  # ← ИЗМЕНИЛ НА ВАШ!
last_processed_message_id = None

def send_message(chat_id, text):
    if not client:
        logger.warning("⚠️ Клиент не инициализирован!")
        return False
    return publisher.send_message(chat_id, text)

def handle_command(chat_id, text):
    logger.info(f"📩 Обработка команды от {chat_id}: {text}")
    
    if text.startswith('/start'):
        return "👋 Привет! Я бот для публикации объявлений.\nИспользуйте /help для списка команд."
    elif text.startswith('/help'):
        return "🤖 Команды:\n/start - Приветствие\n/publish - ОДНОКРАТНАЯ публикация\n/stop - Остановить публикацию\n/status - Статус бота"
    elif text.startswith('/publish'):
        send_message(chat_id, "📢 Начинаю однократную публикацию...")
        threading.Thread(target=publisher.start, args=(chat_id,)).start()
        return None
    elif text.startswith('/stop'):
        send_message(chat_id, "⏹️ Останавливаю публикацию...")
        publisher.stop(chat_id)
        return None
    elif text.startswith('/stop_global'):
        publisher.stop_global()
        return "🛑 Глобальная остановка ВСЕХ публикаций"
    elif text.startswith('/reset_global'):
        publisher.reset_global_stop()
        return "🔄 Глобальный стоп сброшен"
    elif text.startswith('/status'):
        return f"📊 Статус:\n• Глобальный стоп: {'❌ ВКЛ' if publisher.global_stop else '✅ ВЫКЛ'}\n• Публикация: {'🔄 активна' if publisher.running else '⏸️ не активна'}"
    else:
        return f"❓ Неизвестная команда. Используйте /help"

def poll_messages():
    global last_processed_message_id
    
    logger.info("🔄 Запущен цикл Long Polling...")
    logger.info(f"📌 Используем chat_id: {MY_USER_ID}")
    
    while True:
        try:
            if not client:
                logger.error("❌ Клиент не инициализирован!")
                time.sleep(10)
                continue
            
            # Получаем сообщения для ВАШЕГО chat_id
            logger.debug(f"📥 Опрос сообщений для chat_id={MY_USER_ID}")
            messages = client.get_messages(MY_USER_ID, count=10)
            
            if messages is None:
                logger.warning("⚠️ API вернул None")
                time.sleep(5)
                continue
            
            if messages:
                logger.info(f"📨 Получено {len(messages)} сообщений")
                for message in messages:
                    logger.debug(f"📨 Сообщение: {message}")
                    
                    msg_id = message.get('body', {}).get('mid')
                    if not msg_id:
                        continue
                    
                    if last_processed_message_id and msg_id == last_processed_message_id:
                        continue
                    
                    text = message.get('body', {}).get('text', '')
                    if text:
                        logger.info(f"📩 Новое сообщение: {text}")
                        response = handle_command(MY_USER_ID, text)
                        if response:
                            send_message(MY_USER_ID, response)
                    
                    last_processed_message_id = msg_id
            else:
                logger.debug("📭 Новых сообщений нет")
            
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в Long Polling: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)

def start_polling():
    if client:
        poll_thread = threading.Thread(target=poll_messages, daemon=True)
        poll_thread.start()
        logger.info("✅ Long Polling запущен в фоновом потоке")
    else:
        logger.error("❌ Клиент не инициализирован, Long Polling не запущен")

# ========== ВЕБХУК (для отладки) ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"📨 Получен вебхук: {data}")
        
        if not data:
            return jsonify({'status': 'ok'}), 200
        
        update_type = data.get('update_type')
        if update_type != 'message_created':
            return jsonify({'status': 'ok'}), 200
        
        message = data.get('message', {})
        recipient = message.get('recipient', {})
        body = message.get('body', {})
        
        chat_id = recipient.get('chat_id')
        text = body.get('text', '')
        
        if not chat_id or not text:
            return jsonify({'status': 'ok'}), 200
        
        logger.info(f"📩 Вебхук: сообщение от {chat_id}: {text}")
        response = handle_command(chat_id, text)
        if response:
            send_message(chat_id, response)
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка в вебхуке: {e}")
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
        'api_available': client is not None,
        'global_stop': publisher.global_stop,
        'running': publisher.running,
        'polling': True,
        'chat_id': MY_USER_ID
    })

# ========== ТЕСТОВЫЙ ЭНДПОИНТ ==========

@app.route('/test_api')
def test_api():
    """Проверяет работу API"""
    if not client:
        return jsonify({'error': 'Клиент не инициализирован'})
    
    messages = client.get_messages(MY_USER_ID, count=5)
    return jsonify({
        'chat_id': MY_USER_ID,
        'messages_count': len(messages) if messages else 0,
        'messages': messages
    })

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    
    start_polling()
    
    logger.info("=" * 50)
    logger.info("🚀 БОТ ЗАПУЩЕН!")
    logger.info(f"📌 Ваш chat_id: {MY_USER_ID}")
    logger.info("📌 Тестовый эндпоинт: /test_api")
    logger.info("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=False)
