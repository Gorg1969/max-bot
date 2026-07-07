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
# ТОКЕН БЕРЕТСЯ ТОЛЬКО ИЗ ПЕРЕМЕННОЙ ОКРУЖЕНИЯ!
TOKEN = os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"

# ПУТЬ К СЕРТИФИКАТУ
CERT_PATH = os.path.join(os.path.dirname(__file__), 'russian_trusted_root_ca_gost_2025')
USE_CERT = os.path.exists(CERT_PATH)

# ========== ХРАНИЛИЩА ==========
user_states = {}
user_folders = {}
user_publication_status = {}

# ========== ОТПРАВКА ==========

def get_headers():
    """Получение правильных заголовков с Bearer токеном"""
    if not TOKEN:
        logger.error("❌ ТОКЕН НЕ УСТАНОВЛЕН! Установите переменную окружения TOKEN")
        return None
    
    # Правильный формат - Bearer + пробел + токен
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

def send_message(chat_id, text, parse_mode="Markdown"):
    """Отправка сообщения в чат по chat_id"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        logger.info(f"📤 Отправка в chat_id={chat_id}: {text[:30]}...")
        
        r = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        logger.info(f"📤 Ответ: {r.status_code} - {r.text[:200]}")
        
        if r.status_code == 200:
            return True
            
        # Если ошибка 400, пробуем без parse_mode
        if r.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "chat_id": chat_id,
                "text": text
            }
            r2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=10,
                verify=CERT_PATH if USE_CERT else False
            )
            logger.info(f"📤 Ответ без parse_mode: {r2.status_code} - {r2.text[:200]}")
            
            if r2.status_code == 200:
                return True
            
            return False
            
        return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def send_keyboard(chat_id, text, buttons):
    """Отправка клавиатуры в чат по chat_id"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        keyboard_rows = []
        for button in buttons:
            keyboard_rows.append([{
                "text": button["text"],
                "type": "callback",
                "payload": button["payload"]
            }])

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {
                    "buttons": keyboard_rows
                }
            }]
        }

        logger.info(f"🔍 Отправка клавиатуры в chat_id={chat_id}")

        r = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r.status_code == 200:
            logger.info("✅ Клавиатура отправлена!")
            return True
        
        logger.error(f"❌ Ошибка клавиатуры: {r.status_code} - {r.text}")
        
        # Пробуем без parse_mode
        payload2 = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {
                    "buttons": keyboard_rows
                }
            }]
        }
        
        r2 = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload2,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        
        if r2.status_code == 200:
            logger.info("✅ Клавиатура отправлена (без parse_mode)!")
            return True
        
        logger.error(f"❌ Ошибка клавиатуры (2): {r2.status_code} - {r2.text}")
        
        # Отправляем обычное сообщение
        send_message(chat_id, text)
        send_message(chat_id, "📌 Команды:\n/start - меню\n/choose - выбрать папку\n/publish - начать публикацию\n/stop - остановить\n/help - помощь")
        return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка клавиатуры: {e}")
        return False

def send_to_group(chat_id, text):
    """Отправка в группу"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        r = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        logger.info(f"📤 Отправка в группу {chat_id}: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в группу: {e}")
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
    send_keyboard(
        chat_id,
        f"🏠 **Главное меню**\n\n📂 Папка: `{folder}`\n\nВыберите действие:",
        [
            {"text": "📂 Выбрать папку", "payload": "choose_folder"},
            {"text": "▶️ Начать публикацию", "payload": "start_publish"},
            {"text": "⏹ Остановить", "payload": "stop_publication"},
            {"text": "ℹ️ Помощь", "payload": "help"}
        ]
    )

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

def extract_ids_from_data(data):
    """Универсальное извлечение user_id и chat_id"""
    user_id = None
    chat_id = None
    text = ""
    
    def search(obj):
        nonlocal user_id, chat_id, text
        if isinstance(obj, dict):
            if 'chat_id' in obj and obj['chat_id']:
                chat_id = obj['chat_id']
            if 'user_id' in obj and obj['user_id']:
                user_id = obj['user_id']
            if 'text' in obj and obj['text']:
                text = obj['text']
            for value in obj.values():
                search(value)
        elif isinstance(obj, list):
            for item in obj:
                search(item)
    
    search(data)
    return user_id, chat_id, text

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id, chat_id, text = extract_ids_from_data(data)
        
        if not chat_id:
            chat_id = data.get('chat_id')
        if not user_id:
            user_data = data.get('user', {})
            user_id = user_data.get('user_id')

        if not chat_id and user_id:
            chat_id = user_id

        logger.info(f"💬 user_id={user_id}, chat_id={chat_id}, text='{text[:30] if text else ''}'")

        if not chat_id:
            return jsonify({"ok": True}), 200

        if text:
            logger.info(f"📨 Обработка: {text[:50]}")

            if text.lower() in ["/start", "start"]:
                show_main_menu(chat_id)
                if user_id:
                    user_states[user_id] = None
                return jsonify({"ok": True}), 200

            if text.lower() == "/choose":
                show_folder_selection(chat_id)
                return jsonify({"ok": True}), 200

            if text.lower() == "/publish":
                if user_id:
                    folder = user_folders.get(user_id)
                    if folder:
                        publish_posts(chat_id, folder)
                    else:
                        send_message(chat_id, "❌ Сначала выберите папку!")
                        show_folder_selection(chat_id)
                return jsonify({"ok": True}), 200

            if text.lower() == "/stop":
                if user_id:
                    user_publication_status[user_id] = False
                    send_message(chat_id, "⏹ Останавливаю публикацию...")
                    show_main_menu(chat_id)
                return jsonify({"ok": True}), 200

            if text.lower() == "/help":
                send_message(
                    chat_id,
                    "📖 **Помощь**\n\nКоманды:\n/start - Главное меню\n/choose - Выбрать папку\n/publish - Начать публикацию\n/stop - Остановить\n/help - Справка"
                )
                show_main_menu(chat_id)
                return jsonify({"ok": True}), 200

            if user_id and user_id in user_states and user_states[user_id] == "waiting_folder":
                folder_path = text.strip()
                if os.path.exists(folder_path):
                    user_folders[user_id] = folder_path
                    user_states[user_id] = None
                    folders = get_folders(folder_path)
                    send_message(chat_id, f"✅ Папка установлена! Найдено папок: {len(folders)}")
                    show_main_menu(chat_id)
                else:
                    send_message(chat_id, f"❌ Папка не найдена: {folder_path}")
                return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

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
        # Правильный формат с Bearer
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Удаляем старую подписку
        r_del = requests.delete(
            f"{BASE_URL}/subscriptions",
            headers=headers,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        logger.info(f"DELETE subscriptions: {r_del.status_code}")
        
        # Создаем новую подписку
        r = requests.post(
            f"{BASE_URL}/subscriptions",
            headers=headers,
            json={"url": webhook_url},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        return f"✅ DELETE: {r_del.status_code}\n✅ POST: {r.status_code} - {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
