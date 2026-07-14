import logging
import os
import time
import threading
import asyncio
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
# ГЛОБАЛЬНЫЙ EVENT LOOP
# ============================================

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

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
        if hasattr(maxapi, 'Bot'):
            api = maxapi.Bot(token=token)
            logger.info("✅ MAX API инициализирован через Bot")
            return api
        else:
            logger.error("❌ Не найден класс Bot в maxapi")
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
publisher = Publisher(api, fm, db, loop=loop)
web_interface = WebInterface(fm, publisher)

# ========== ФУНКЦИИ ОТПРАВКИ ==========

def send_message(chat_id, text):
    """Отправка сообщения"""
    if not api:
        logger.warning(f"⚠️ API не инициализирован!")
        return False
    
    try:
        return publisher.send_message(chat_id, text)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def process_message(chat_id, text):
    """Обработка сообщения"""
    logger.info(f"📩 Сообщение от {chat_id}: {text}")
    
    response = None
    
    if text.startswith('/start'):
        response = "👋 Привет! Я бот для публикации объявлений.\nИспользуйте /help для списка команд."
    
    elif text.startswith('/publish'):
        send_message(chat_id, "📢 Начинаю однократную публикацию...")
        threading.Thread(target=publisher.start, args=(chat_id,)).start()
        return
    
    elif text.startswith('/stop'):
        send_message(chat_id, "⏹️ Останавливаю публикацию...")
        publisher.stop(chat_id)
        return
    
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

# ========== LONG POLLING (ПОЛЛИНГ) ==========

def poll_messages():
    """Основной цикл поллинга - опрашивает API на наличие новых сообщений"""
    logger.info("🔄 Запущен цикл поллинга...")
    
    last_update_id = 0
    
    while True:
        try:
            # Проверяем новые сообщения через API
            # Используем run_coroutine_threadsafe для вызова асинхронного метода
            future = asyncio.run_coroutine_threadsafe(
                api.get_updates(offset=last_update_id + 1, timeout=30),
                loop
            )
            updates = future.result(timeout=35)
            
            if updates:
                for update in updates:
                    # Проверяем, есть ли сообщение
                    if 'message' in update:
                        message = update['message']
                        chat_id = message.get('chat', {}).get('id')
                        text = message.get('text', '')
                        
                        if chat_id and text:
                            # Обрабатываем в отдельном потоке
                            threading.Thread(
                                target=process_message,
                                args=(chat_id, text)
                            ).start()
                        
                        # Обновляем last_update_id
                        if update.get('update_id'):
                            last_update_id = max(last_update_id, update['update_id'])
            
            # Небольшая пауза, чтобы не нагружать API
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в поллинге: {e}")
            time.sleep(5)

# Запускаем поллинг в отдельном потоке
def start_polling():
    """Запускает поллинг в фоновом потоке"""
    if api:
        poll_thread = threading.Thread(target=poll_messages, daemon=True)
        poll_thread.start()
        logger.info("✅ Поллинг запущен в фоновом потоке")
    else:
        logger.error("❌ API не инициализирован, поллинг не запущен")

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
        'api_available': api is not None,
        'global_stop': publisher.global_stop,
        'running': publisher.running,
        'auto_publish': False,
        'polling': True
    })

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    
    # Запускаем поллинг
    start_polling()
    
    logger.info("=" * 50)
    logger.info("🚀 БОТ ЗАПУЩЕН (режим Long Polling)!")
    logger.info("📌 АВТОМАТИЧЕСКАЯ ПУБЛИКАЦИЯ ОТКЛЮЧЕНА")
    logger.info("📌 Используйте /publish для однократной публикации")
    logger.info("📌 ВЕБХУК НЕ НУЖЕН - бот сам опрашивает API")
    logger.info("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=False)
