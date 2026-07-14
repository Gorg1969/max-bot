import logging
import os
import time
import threading
import requests
import urllib3
from flask import Flask, request, jsonify, render_template_string

# Импорты из modules
from modules.database import Database
from modules.file_manager import FileManager
from modules.publisher import Publisher
from modules.web_interface import WebInterface

# Отключаем предупреждения о SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

app = Flask(__name__)

db = Database()
fm = FileManager()
publisher = Publisher(None, fm, db)
web_interface = WebInterface(fm, publisher)

# Храним ID последнего обработанного обновления
last_update_id = 0

# ========== ОТПРАВКА СООБЩЕНИЙ ==========

def send_message(chat_id, text):
    """Отправка сообщения в чат"""
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
        
        logger.info(f"📤 Отправка в чат {chat_id}: {text[:30]}...")
        response = requests.post(url, headers=headers, json=json_data, timeout=30, verify=False)
        
        if response.status_code == 200:
            logger.info(f"✅ Сообщение отправлено в чат {chat_id}")
            return True
        else:
            logger.error(f"❌ Ошибка API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

# ========== ОБРАБОТКА КОМАНД ==========

def handle_command(chat_id, text):
    """Обработка команд"""
    logger.info(f"📩 Обработка команды от {chat_id}: {text}")
    
    if text.startswith('/start'):
        return "👋 Привет! Я бот для публикации объявлений.\nИспользуйте /help для списка команд."
    
    elif text.startswith('/help'):
        return (
            "🤖 Команды:\n"
            "/start - Приветствие\n"
            "/publish - ОДНОКРАТНАЯ публикация\n"
            "/stop - Остановить публикацию\n"
            "/status - Статус бота\n"
            "/stop_global - Глобальная остановка\n"
            "/reset_global - Сброс стопа"
        )
    
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
        status = (
            f"📊 Статус:\n"
            f"• Глобальный стоп: {'❌ ВКЛ' if publisher.global_stop else '✅ ВЫКЛ'}\n"
            f"• Публикация: {'🔄 активна' if publisher.running else '⏸️ не активна'}\n"
            f"• Автоматическая публикация: ⏸️ ОТКЛЮЧЕНА"
        )
        return status
    
    else:
        return f"❓ Неизвестная команда. Используйте /help"

# ========== LONG POLLING (ПРАВИЛЬНЫЙ) ==========

def poll_updates():
    """Основной цикл Long Polling - используем /updates"""
    global last_update_id
    
    logger.info("🔄 Запущен цикл Long Polling через /updates...")
    
    while True:
        try:
            token = get_token()
            if not token:
                logger.error("❌ Токен не найден!")
                time.sleep(10)
                continue
            
            # Используем /updates для Long Polling
            url = "https://platform-api2.max.ru/updates"
            headers = {
                "Authorization": token,
            }
            params = {
                "offset": last_update_id + 1,
                "limit": 10,
                "timeout": 30,
            }
            
            logger.debug(f"📥 Запрос обновлений с offset={last_update_id + 1}")
            response = requests.get(url, headers=headers, params=params, timeout=35, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                updates = data.get('updates', [])
                
                if updates:
                    logger.info(f"📨 Получено {len(updates)} обновлений")
                    for update in updates:
                        update_id = update.get('update_id')
                        update_type = update.get('update_type')
                        
                        # Обрабатываем только новые сообщения
                        if update_type == 'message_created':
                            message = update.get('message', {})
                            recipient = message.get('recipient', {})
                            body = message.get('body', {})
                            chat_id = recipient.get('chat_id')
                            text = body.get('text', '')
                            
                            if chat_id and text:
                                logger.info(f"📩 Новое сообщение от {chat_id}: {text}")
                                response_text = handle_command(chat_id, text)
                                if response_text:
                                    send_message(chat_id, response_text)
                        elif update_type == 'bot_started':
                            # Запуск бота через диплинк
                            chat_id = update.get('chat_id')
                            payload = update.get('payload')
                            logger.info(f"🚀 Бот запущен пользователем {chat_id}, payload: {payload}")
                            if chat_id:
                                send_message(chat_id, "👋 Привет! Я бот для публикации объявлений.")
                        
                        # Обновляем ID последнего обработанного обновления
                        if update_id:
                            last_update_id = max(last_update_id, update_id)
                else:
                    logger.debug("📭 Новых обновлений нет")
            else:
                logger.error(f"❌ Ошибка получения обновлений: {response.status_code} - {response.text}")
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в Long Polling: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)

# Запускаем Long Polling в фоновом потоке
def start_polling():
    poll_thread = threading.Thread(target=poll_updates, daemon=True)
    poll_thread.start()
    logger.info("✅ Long Polling запущен")

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
        'polling': True,
        'last_update_id': last_update_id
    })

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    
    # Запускаем Long Polling
    start_polling()
    
    logger.info("=" * 50)
    logger.info("🚀 БОТ ЗАПУЩЕН (режим Long Polling)!")
    logger.info("📌 АВТОМАТИЧЕСКАЯ ПУБЛИКАЦИЯ ОТКЛЮЧЕНА")
    logger.info("📌 Используйте /publish для однократной публикации")
    logger.info("📌 ВЕБХУК НЕ НУЖЕН - бот сам опрашивает API через /updates")
    logger.info("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=False)
