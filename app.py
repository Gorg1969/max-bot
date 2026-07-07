from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import re
import random
from pathlib import Path
import urllib3

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN", "f9LHodD0cOJlllLX1fR59yrbAD6H3UWttud4hPu4zQOQnY2SwNo5NIJtSRA5feJviS8obhPIQ2954lD9YGNp")
BASE_URL = "https://platform-api2.max.ru"

# ПУТЬ К СЕРТИФИКАТУ
CERT_PATH = os.path.join(os.path.dirname(__file__), 'russian_trusted_root_ca_gost_2025')
USE_CERT = os.path.exists(CERT_PATH)
if USE_CERT:
    logger.info(f"✅ Сертификат найден: {CERT_PATH}")
else:
    logger.warning("⚠️ Сертификат не найден! Использую verify=False")

# ========== ХРАНИЛИЩА ==========
user_states = {}
user_folders = {}
user_publication_status = {}

# ========== ОТПРАВКА ==========

def send_message(chat_id, text, parse_mode="Markdown"):
    """Отправка сообщения в чат по chat_id"""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        logger.info(f"📤 Отправка: {r.status_code} - {r.text[:100]}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def send_keyboard(chat_id, text, buttons):
    """Отправка клавиатуры в чат по chat_id с тестированием разных форматов"""
    try:
        # Формируем клавиатуру
        keyboard_buttons = []
        for button in buttons:
            keyboard_buttons.append([{
                "text": button["text"],
                "type": "callback",
                "payload": button["payload"]
            }])

        # ПРОБУЕМ РАЗНЫЕ ФОРМАТЫ ПО ОЧЕРЕДИ
        
        # Формат 1: Стандартный MAX формат (как в документации)
        payload1 = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "keyboard": {
                "buttons": keyboard_buttons,
                "type": "inline"
            }
        }
        
        logger.info(f"🔍 Формат 1: {json.dumps(payload1, ensure_ascii=False)[:300]}")
        
        r1 = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload1,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r1.status_code == 200:
            logger.info("✅ Формат 1 работает!")
            return True
        
        logger.warning(f"❌ Формат 1 не работает: {r1.status_code} - {r1.text}")
        
        # Формат 2: Через attachments
        payload2 = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard_buttons}
            }]
        }
        
        logger.info(f"🔍 Формат 2: {json.dumps(payload2, ensure_ascii=False)[:300]}")
        
        r2 = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload2,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r2.status_code == 200:
            logger.info("✅ Формат 2 работает!")
            return True
        
        logger.warning(f"❌ Формат 2 не работает: {r2.status_code} - {r2.text}")
        
        # Формат 3: Простая клавиатура (без inline)
        payload3 = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "keyboard": {
                "buttons": keyboard_buttons,
                "type": "keyboard"
            }
        }
        
        logger.info(f"🔍 Формат 3: {json.dumps(payload3, ensure_ascii=False)[:300]}")
        
        r3 = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload3,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r3.status_code == 200:
            logger.info("✅ Формат 3 работает!")
            return True
        
        logger.warning(f"❌ Формат 3 не работает: {r3.status_code} - {r3.text}")
        
        # Формат 4: Только клавиатура без текста
        payload4 = {
            "chat_id": chat_id,
            "text": text,
            "keyboard": {
                "buttons": keyboard_buttons,
                "type": "inline"
            }
        }
        
        logger.info(f"🔍 Формат 4: {json.dumps(payload4, ensure_ascii=False)[:300]}")
        
        r4 = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload4,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r4.status_code == 200:
            logger.info("✅ Формат 4 работает!")
            return True
        
        logger.warning(f"❌ Формат 4 не работает: {r4.status_code} - {r4.text}")
        
        # Если ничего не работает, отправляем обычное сообщение
        logger.error("❌ Все форматы клавиатуры не работают! Отправляю обычное сообщение.")
        return send_message(chat_id, text + "\n\n(Клавиатура не поддерживается)")
        
    except Exception as e:
        logger.error(f"❌ Ошибка клавиатуры: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def send_to_group(chat_id, text):
    """Отправка в группу"""
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        return r.status_code == 200
    except:
        return False

# ========== РАБОТА С ПАПКАМИ ==========

def get_folders(base_path):
    try:
        path = Path(base_path)
        if not path.exists():
            return []
        folders = []
        for item in path.iterdir():
            if item.is_dir():
                files = list(item.glob("*"))
                if files:
                    match = re.search(r'(-\d+)$', item.name)
                    group_id = match.group(1) if match else None
                    folders.append({
                        "name": item.name,
                        "path": str(item),
                        "group_id": group_id
                    })
        return folders
    except Exception as e:
        logger.error(f"Ошибка чтения папки: {e}")
        return []

def get_post_text(folder_path):
    try:
        path = Path(folder_path)
        text_files = list(path.glob("*.txt")) + list(path.glob("*.md"))
        if text_files:
            with open(text_files[0], 'r', encoding='utf-8') as f:
                return f.read().strip()
        return None
    except Exception as e:
        logger.error(f"Ошибка чтения файла: {e}")
        return None

def human_delay():
    return random.randint(60, 180)

# ========== МЕНЮ ==========

def show_main_menu(chat_id):
    """Главное меню"""
    folder = user_folders.get(chat_id, "Не выбрана")
    success = send_keyboard(
        chat_id,
        f"🏠 **Главное меню**\n\n📂 Папка: `{folder}`\n\nВыберите действие:",
        [
            {"text": "📂 Выбрать папку", "payload": "choose_folder"},
            {"text": "▶️ Начать публикацию", "payload": "start_publish"},
            {"text": "⏹ Остановить", "payload": "stop_publication"},
            {"text": "ℹ️ Помощь", "payload": "help"}
        ]
    )
    if not success:
        logger.error("❌ Не удалось отправить клавиатуру!")
        # Отправляем простое сообщение с инструкцией
        send_message(
            chat_id,
            "🏠 **Главное меню**\n\n"
            "📂 Папка: `" + folder + "`\n\n"
            "К сожалению, клавиатура не поддерживается.\n"
            "Используйте команды:\n"
            "/choose - выбрать папку\n"
            "/start_publish - начать публикацию\n"
            "/stop - остановить\n"
            "/help - помощь"
        )
    return success

def show_folder_selection(chat_id):
    """Выбор папки"""
    current = user_folders.get(chat_id)
    if current:
        send_keyboard(
            chat_id,
            f"📂 **Текущая папка:**\n`{current}`\n\nЧто хотите сделать?",
            [
                {"text": "📁 Изменить папку", "payload": "change_folder"},
                {"text": "▶️ Начать публикацию", "payload": "start_publish"},
                {"text": "🏠 В главное меню", "payload": "main_menu"}
            ]
        )
    else:
        send_message(
            chat_id,
            "📁 **Укажите путь к папке с постами**\n\n"
            "📂 **Структура:**\n"
            "```\n"
            "Папка/\n"
            "├── Мои тренировки -123456789/\n"
            "│   └── post.txt\n"
            "├── Новости -987654321/\n"
            "│   └── post.txt\n"
            "└── ...\n"
            "```\n\n"
            "💡 ID группы в имени папки (с минусом)\n"
            "📝 Введите путь:"
        )
        user_states[chat_id] = "waiting_folder"

def publish_posts(chat_id, folder_path):
    """Публикация постов"""
    if user_publication_status.get(chat_id, False):
        send_message(chat_id, "⚠️ Публикация уже запущена!")
        return

    folders = get_folders(folder_path)
    if not folders:
        send_message(chat_id, "❌ Нет папок с файлами!")
        return

    user_publication_status[chat_id] = True
    total = len(folders)
    published = 0
    skipped = 0

    send_message(chat_id, f"📁 Найдено: {total}\n🔄 Начинаю публикацию...")

    for i, folder in enumerate(folders, 1):
        if not user_publication_status.get(chat_id, True):
            send_message(chat_id, f"⏹ Остановлено! Опубликовано: {published}/{total}")
            break

        group_id = folder.get("group_id")
        if not group_id:
            skipped += 1
            continue

        text = get_post_text(folder["path"])
        if not text:
            skipped += 1
            continue

        result = send_to_group(group_id, f"📝 **Пост {i}/{total}**\n📁 {folder['name']}\n\n{text}")

        if result:
            published += 1
            send_message(chat_id, f"✅ Пост {i}/{total} опубликован в {group_id}")
        else:
            skipped += 1
            send_message(chat_id, f"❌ Ошибка публикации в {group_id}")

        if i < total and user_publication_status.get(chat_id, True):
            delay = human_delay()
            mins = delay // 60
            secs = delay % 60
            send_message(chat_id, f"⏳ Следующий пост через {mins}м {secs}с")
            time.sleep(delay)

    if user_publication_status.get(chat_id, True):
        send_message(
            chat_id,
            f"✅ **ГОТОВО!**\nОпубликовано: {published}/{total}\nПропущено: {skipped}"
        )

    user_publication_status[chat_id] = False
    show_main_menu(chat_id)

# ========== ВЕБХУК ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")
        logger.info(f"📦 Данные: {json.dumps(data, ensure_ascii=False)[:500]}")

        if not data:
            return jsonify({"ok": True}), 200

        # ===== ИЗВЛЕКАЕМ ДАННЫЕ =====
        user_id = None
        chat_id = None
        text = ""
        payload = ""

        # Проверяем системные события
        if 'event' in data:
            event_type = data.get('event')
            chat_id = data.get('chat_id')
            logger.info(f"⚙️ Системное событие: {event_type}, chat_id: {chat_id}")
            
            if event_type == 'bot_started' and chat_id:
                send_message(chat_id, "🤖 Бот запущен! Используйте /start для начала работы.")
                show_main_menu(chat_id)
            elif event_type == 'bot_stopped' and chat_id:
                send_message(chat_id, "⏹ Бот остановлен. Для запуска используйте /start")
            
            return jsonify({"ok": True}), 200

        # Извлекаем из callback_query (кнопки)
        if 'callback_query' in data:
            cb = data['callback_query']
            user_id = cb.get('user_id') or cb.get('from', {}).get('id')
            chat_id = cb.get('chat_id') or data.get('chat_id')
            payload = cb.get('payload', '')
            
            logger.info(f"🔘 Нажата кнопка: payload='{payload}', user_id={user_id}, chat_id={chat_id}")
            
            if user_id and chat_id and payload:
                return handle_callback(user_id, chat_id, payload)

        # Извлекаем из сообщения
        if 'message' in data:
            msg = data['message']
            if 'sender' in msg:
                user_id = msg['sender'].get('user_id')
            if 'recipient' in msg:
                chat_id = msg['recipient'].get('chat_id')
            if 'body' in msg:
                text = msg['body'].get('text', '')

        # Если не нашли через message, пробуем прямые поля
        if not user_id and 'user_id' in data:
            user_id = data.get('user_id')
        if not chat_id and 'chat_id' in data:
            chat_id = data.get('chat_id')
        if not text and 'text' in data:
            text = data.get('text', '')

        logger.info(f"💬 Итог: user_id={user_id}, chat_id={chat_id}, text='{text}'")

        if not user_id or not chat_id:
            logger.error("❌ Нет user_id или chat_id!")
            return jsonify({"ok": False, "error": "Missing IDs"}), 400

        # ===== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ =====
        if text:
            logger.info(f"📨 Обработка сообщения от {user_id}: {text[:50]}")

            if text == "/start" or text == "start":
                show_main_menu(chat_id)
                user_states[user_id] = None
                return jsonify({"ok": True}), 200

            if user_id in user_states and user_states[user_id] == "waiting_folder":
                folder_path = text.strip()
                if os.path.exists(folder_path):
                    user_folders[user_id] = folder_path
                    user_states[user_id] = None
                    folders = get_folders(folder_path)
                    send_message(chat_id, f"✅ Папка установлена!\nНайдено папок: {len(folders)}")
                    show_main_menu(chat_id)
                else:
                    send_message(chat_id, f"❌ Папка не найдена: {folder_path}")
                return jsonify({"ok": True}), 200

        logger.info("=" * 50)
        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"ok": False}), 500

def handle_callback(user_id, chat_id, payload):
    """Обработка нажатий кнопок"""
    try:
        logger.info(f"🔘 Обработка callback: {payload} от {user_id}")
        
        if payload == "main_menu":
            show_main_menu(chat_id)
            
        elif payload == "choose_folder" or payload == "change_folder":
            show_folder_selection(chat_id)
            
        elif payload == "start_publish":
            folder = user_folders.get(user_id)
            if folder:
                if user_publication_status.get(user_id, False):
                    send_message(chat_id, "⚠️ Публикация уже запущена!")
                else:
                    send_message(chat_id, "🚀 Начинаю публикацию...")
                    publish_posts(chat_id, folder)
            else:
                send_message(chat_id, "❌ Сначала выберите папку!")
                show_folder_selection(chat_id)
                
        elif payload == "stop_publication":
            user_publication_status[user_id] = False
            send_message(chat_id, "⏹ Останавливаю публикацию...")
            time.sleep(1)
            show_main_menu(chat_id)
            
        elif payload == "help":
            send_message(
                chat_id,
                "📖 **Помощь**\n\n"
                "1. Выберите папку\n"
                "2. Нажмите «Начать публикацию»\n"
                "3. Бот опубликует посты\n\n"
                "📂 Имя папки: название -ID_группы"
            )
            show_main_menu(chat_id)
            
        else:
            logger.warning(f"⚠️ Неизвестный payload: {payload}")
            
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки callback: {e}")
        return False

@app.route('/')
def index():
    return "🤖 MAX Bot is running on Render.com!", 200

@app.route('/health')
def health():
    return {"status": "ok", "time": time.strftime('%Y-%m-%d %H:%M:%S')}, 200

@app.route('/setup_webhook')
def setup_webhook():
    token = request.args.get('token')
    if not token:
        return "❌ Нет токена", 400

    webhook_url = "https://max-bot-ulzl.onrender.com/webhook"

    try:
        requests.delete(
            f"{BASE_URL}/subscriptions",
            headers={"Authorization": token},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        r = requests.post(
            f"{BASE_URL}/subscriptions",
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={"url": webhook_url},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        return f"✅ Статус: {r.status_code}\n✅ Ответ: {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
