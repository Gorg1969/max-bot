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

# ГЛОБАЛЬНЫЕ ХРАНИЛИЩА (ОБЯВЛЕНИЕ ДО ОПРЕДЕЛЕНИЯ ФУНКЦИЙ)
user_states = {}                  # Текущие состояния пользователя
user_folders = {}               # Связка user_id -> путь к папке
user_publication_status = {}    # Флаг публикации (True/False)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"

# ========== ПРОВЕРКА СЕРТИФИКАТА ==========
CERT_FILE = 'russian_trusted_root_ca_gost_2025.cer'
CERT_PATH = os.path.join(os.path.dirname(__file__), CERT_FILE)
USE_CERT = False  # ПОКА ОТКЛЮЧЕН

if os.path.exists(CERT_PATH):
    logger.info(f"✅ Сертификат найден: {CERT_PATH}, но пока отключен")
else:
    logger.warning(f"⚠️ Сертификат НЕ НАЙДЕН: {CERT_PATH}")

# Остальные функции (send_message, send_keyboard, get_folders...) начинаются отсюда

# ========== ФУНКЦИЯ ЗАПРОСОВ К МАХ ==========
def max_request(method, endpoint, data=None, headers=None):
    """Универсальный запрос к API МАХ"""
    url = f"{BASE_URL}{endpoint}"
    
    request_headers = {}
    
    if TOKEN:
        request_headers["Authorization"] = TOKEN
        logger.info(f"🔑 Токен добавлен: {TOKEN[:4]}...{TOKEN[-4:]}")
    else:
        logger.error("❌ ТОКЕН НЕ НАЙДЕН!")
    
    request_headers["Content-Type"] = "application/json"
    
    if headers:
        request_headers.update(headers)
    
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=request_headers,
            json=data,
            timeout=30,
            verify=False
        )
        logger.info(f"📤 {method} {endpoint} -> {response.status_code}")
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка запроса: {e}")
        raise

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С СООБЩЕНИЯМИ ==========

def get_headers():
    """Получение заголовков с токеном"""
    if not TOKEN:
        logger.error("❌ ТОКЕН НЕ УСТАНОВЛЕН!")
        return None
    
    return {
        "Authorization": TOKEN,
        "Content-Type": "application/json"
    }

def send_message(user_id, text, parse_mode="Markdown"):
    """Отправка сообщения в МАХ (ТОЛЬКО НА USER_ID!)"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        # ПРАВИЛЬНЫЙ ФОРМАТ ДЛЯ МАХ
        payload = {
            "user_id": user_id,           # <-- user_id
            "text": text,
            "parse_mode": parse_mode
        }
        
        logger.info(f"📤 Отправка в user_id={user_id}")
        logger.info(f"📦 Пейлоад: {json.dumps(payload, ensure_ascii=False)[:200]}")
        
        response = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30,
            verify=False
        )
        
        logger.info(f"📤 Ответ: {response.status_code} - {response.text[:200]}")
        
        if response.status_code == 200:
            return True
            
        # Если ошибка 400, пробуем без markdown
        if response.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "user_id": user_id,             # <-- user_id
                "text": text
            }
            response2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Ответ без parse_mode: {response2.status_code} - {response2.text[:200]}")
            return response2.status_code == 200
            
        return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def send_keyboard(user_id, text, buttons):
    """Отправка клавиатуры в МАХ (ТОЛЬКО НА USER_ID!)"""
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
            "user_id": user_id,              # <-- user_id
            "text": text,
            "parse_mode": "Markdown",
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {
                    "buttons": keyboard_rows
                }
            }]
        }

        logger.info(f"📤 Отправка клавиатуры в user_id={user_id}")
        logger.info(f"📦 Пейлоад: {json.dumps(payload, ensure_ascii=False)[:300]}")

        response = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30,
            verify=False
        )
        
        logger.info(f"📤 Ответ: {response.status_code} - {response.text[:200]}")
        
        if response.status_code == 200:
            logger.info("✅ Клавиатура отправлена!")
            return True
        
        if response.status_code == 400:
            logger.info("🔄 Пробую без parse_mode...")
            payload2 = {
                "user_id": user_id,               # <-- user_id
                "text": text,
                "attachments": [{
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": keyboard_rows
                    }
                }]
            }
            
            response2 = requests.post(
                f"{BASE_URL}/messages",
                headers=headers,
                json=payload2,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Ответ без parse_mode: {response2.status_code} - {response2.text[:200]}")
            
            if response2.status_code == 200:
                return True
        
        logger.info("🔄 Отправляю обычное сообщение...")
        return send_message(user_id, text)  # <-- user_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка клавиатуры: {e}")
        return False

def send_to_group(chat_id, text):
    """Отправка в группу (используется chat_id)"""
    try:
        headers = get_headers()
        if not headers:
            return False
            
        payload = {
            "chat_id": chat_id,                 # <-- chat_id (только для групп)
            "text": text,
            "parse_mode": "Markdown"
        }
        response = requests.post(
            f"{BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30,
            verify=False
        )
        logger.info(f"📤 Отправка в группу {chat_id}: {response.status_code}")
        return response.status_code == 200
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

def show_main_menu(user_id):
    """Главное меню (отправка на user_id)"""
    folder = user_folders.get(user_id, "Не выбрана")
    send_keyboard(
        user_id,                                   # <-- user_id
        f"🏠 **Главное меню**\n\n📂 Папка: `{folder}`\n\nВыберите действие:",
        [
            {"text": "📂 Выбрать папку", "payload": "choose_folder"},
            {"text": "▶️ Начать публикацию", "payload": "start_publish"},
            {"text": "⏹ Остановить", "payload": "stop_publication"},
            {"text": "ℹ️ Помощь", "payload": "help"}
        ]
    )

def show_folder_selection(user_id):
    """Выбор папки (отправка на user_id)"""
    current = user_folders.get(user_id)
    if current:
        send_keyboard(
            user_id,                                  # <-- user_id
            f"📂 **Текущая папка:**\n`{current}`\n\nЧто хотите сделать?",
            [
                {"text": "📁 Изменить папку", "payload": "change_folder"},
                {"text": "▶️ Начать публикацию", "payload": "start_publish"},
                {"text": "🏠 В главное меню", "payload": "main_menu"}
            ]
        )
    else:
        send_message(
            user_id,                                 # <-- user_id
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
        user_states[user_id] = "waiting_folder"

def publish_posts(user_id, folder_path):
    """Публикация постов (отправка на chat_id)"""
    if user_publication_status.get(user_id, False):
        send_message(user_id, "⚠️ Публикация уже запущена!")
        return

    folders = get_folders(folder_path)
    if not folders:
        send_message(user_id, "❌ Нет папок с файлами!")
        return

    user_publication_status[user_id] = True
    total = len(folders)
    published = 0
    skipped = 0

    send_message(user_id, f"📁 Найдено: {total}\n🔄 Начинаю публикацию...")

    for i, folder in enumerate(folders, 1):
        if not user_publication_status.get(user_id, True):
            send_message(user_id, f"⏹ Остановлено! Опубликовано: {published}/{total}")
            break

        group_id = folder.get("group_id")
        if not group_id:
            send_message(user_id, f"⚠️ В папке {folder['name']} нет ID группы")
            skipped += 1
            continue

        text = get_post_text(folder["path"])
        if not text:
            send_message(user_id, f"⚠️ В папке {folder['name']} нет текста")
            skipped += 1
            continue

        result = send_to_group(group_id, f"📝 **Пост {i}/{total}**\n📁 {folder['name']}\n\n{text}")

        if result:
            published += 1
            send_message(user_id, f"✅ Пост {i}/{total} опубликован в {group_id}")
        else:
            skipped += 1
            send_message(user_id, f"❌ Ошибка публикации в {group_id}")

        if i < total and user_publication_status.get(user_id, True):
            delay = human_delay()
            mins = delay // 60
            secs = delay % 60
            send_message(user_id, f"⏳ Следующий пост через {mins}м {secs}с")
            time.sleep(delay)

    if user_publication_status.get(user_id, True):
        send_message(
            user_id,
            f"✅ **ГОТОВО!**\nОпубликовано: {published}/{total}\nПропущено: {skipped}"
        )

    user_publication_status[user_id] = False
    show_main_menu(user_id)

# ========== ВЕБХУК ==========

def extract_user_and_chat(data):
    """Поиск user_id и chat_id в любых вложенных объектах"""
    user_id = None
    chat_id = None
    text = ""

    def search(obj):
        nonlocal user_id, chat_id, text
        if isinstance(obj, dict):
            if "user_id" in obj:
                user_id = obj["user_id"]
            if "chat_id" in obj:
                chat_id = obj["chat_id"]
            if "text" in obj:
                text = obj["text"]
            for value in obj.values():
                search(value)
        elif isinstance(obj, list):
            for item in obj:
                search(item)

    search(data)
    return user_id, chat_id, text

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхука от МАХ"""
    try:
        data = request.get_json()
        logger.info("=" * 50)
        logger.info(f"ПОЛУЧЕН ВЕБХУК: {json.dumps(data, ensure_ascii=False)[:500]}")

        # Универсальный поиск user_id
        user_id, _, text = extract_user_and_chat(data)

        if not user_id:
            logger.error("❌ Не удалось найти user_id!")
            return jsonify({"ok": True}), 200

        # Работаем только с user_id
        if text and isinstance(text, str):
            text_lower = text.lower().strip()
            
            if text_lower in ["/start", "start"]:
                show_main_menu(user_id)  # <-- user_id
                return jsonify({"ok": True}), 200

            if text_lower == "/help":
                send_message(
                    user_id,                     # <-- user_id
                    "📖 **Помощь**\n\nКоманды:\n/start - Главное меню\n/choose - Выбрать папку\n/publish - Начать публикацию\n/stop - Остановить\n/help - Справка"
                )
                return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
