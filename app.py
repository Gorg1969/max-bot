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

# ========== ХРАНИЛИЩА (теперь всё по user_id) ==========
user_states = {}
user_folders = {}
user_publication_status = {}

# ========== ОТПРАВКА ==========
def send_message(chat_id, text):
    """Отправка сообщения в чат по chat_id"""
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        logger.info(f"📤 Отправка: {r.status_code} - {r.text[:100]}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def send_keyboard(chat_id, text, buttons):
    """Отправка клавиатуры в чат по chat_id"""
    try:
        keyboard_rows = []
        for button in buttons:
            keyboard_rows.append([
                {
                    "text": button["text"],
                    "type": "callback",
                    "payload": button["payload"]
                }
            ])

        payload = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard_rows}
            }]
        }

        logger.info(f"🔍 Отправляемая клавиатура: {json.dumps(payload, ensure_ascii=False)}")

        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload,
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        logger.info(f"⌨️ Клавиатура: {r.status_code} - {r.text[:100]}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка клавиатуры: {e}")
        return False

def send_to_group(chat_id, text):
    """Отправка в группу"""
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10,
            verify=CERT_PATH if USE_CERT else False
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка группы: {e}")
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
    folder = user_folders.get(chat_id, "Не выбрана")
    # Небольшая пауза
    time.sleep(0.1)
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

def publish_posts(user_id, chat_id, folder_path):
    """Публикация постов (вызывается только после проверки статуса)"""
    total_folders = get_folders(folder_path)
    if not total_folders:
        send_message(chat_id, "❌ Нет папок с файлами!")
        user_publication_status[user_id] = False
        show_main_menu(chat_id)
        return

    published = 0
    skipped = 0
    total = len(total_folders)
    
    send_message(chat_id, f"📁 Найдено: {total}\n🔄 Начинаю публикацию...")

    for i, folder in enumerate(total_folders, 1):
        # Проверяем флаг остановки перед каждой итерацией
        if not user_publication_status.get(user_id, True):
            send_message(chat_id, f"⏹ Публикация остановлена пользователем. Опубликовано: {published}/{total}")
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

        if i < total and user_publication_status.get(user_id, True):
            delay = human_delay()
            mins = delay // 60
            secs = delay % 60
            send_message(chat_id, f"⏳ Следующий пост через {mins}м {secs}с")
            time.sleep(delay)

    if user_publication_status.get(user_id, True):
        send_message(
            chat_id,
            f"✅ **ГОТОВО!**\nОпубликовано: {published}/{total}\nПропущено: {skipped}"
        )

    user_publication_status[user_id] = False
    show_main_menu(chat_id)

# ========== ВЕБХУК ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(silent=True)
        
        if not data:
            return jsonify({"ok": True}), 200

        logger.info("=" * 50)
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")
        logger.info(f"📦 Данные: {json.dumps(data, ensure_ascii=False)[:500]}")

        # ===== ИЗВЛЕКАЕМ ДАННЫЕ (универсально) =====
        user_id = (
            data.get('user_id')
            or data.get('message', {}).get('sender', {}).get('user_id')
            or data.get('message', {}).get('from', {}).get('id')
            or data.get('callback_query', {}).get('user_id')
            or data.get('callback_query', {}).get('sender', {}).get('user_id')
            or data.get('callback_query', {}).get('from', {}).get('id')
        )
        
        chat_id = (
            data.get('chat_id')
            or data.get('message', {}).get('recipient', {}).get('chat_id')
            or data.get('callback_query', {}).get('chat_id')
        )
        
        text = ""
        if 'message' in data and 'body' in data['message']:
            text = data['message']['body'].get('text', '')
        elif 'text' in data:
            text = data.get('text', '')

        if isinstance(text, str):
            text = text.strip()

        logger.info(f"💬 user_id: {user_id}, chat_id: {chat_id}, text: '{text}'")

        if not user_id or not chat_id:
            logger.error("❌ Не удалось определить user_id или chat_id!")
            return jsonify({"ok": True}), 200

        # ===== ОБРАБОТКА ТЕКСТА =====
        if text:
            logger.info(f"📨 Обработка текста от {user_id}")

            if text == "/start":
                show_main_menu(chat_id)
                user_states[user_id] = None
            
            elif user_states.get(user_id) == "waiting_folder":
                folder_path = text.strip()
                if os.path.exists(folder_path):
                    user_folders[user_id] = folder_path
                    user_states[user_id] = None
                    folders = get_folders(folder_path)
                    send_message(chat_id, f"✅ Папка установлена!\nНайдено папок: {len(folders)}")
                    show_main_menu(chat_id)
                else:
                    send_message(chat_id, f"❌ Папка не найдена: {folder_path}")

        # ===== ОБРАБОТКА КНОПОК (исправлен поиск ID) =====
        if "callback_query" in data:
            cb = data["callback_query"]
            # Переопределим переменные точно из callback, чтобы избежать подмены scope
            uid = (
                cb.get("user_id")
                or cb.get("sender", {}).get("user_id")
                or cb.get("from", {}).get("id")
            )
            cid = cb.get("chat_id") or data.get("chat_id")
            payload = cb.get("payload", "")

            if not uid or not cid:
                logger.error("❌ Нет user_id или chat_id внутри callback object!")
                return jsonify({"ok": True}), 200

            logger.info(f"🔘 Нажата кнопка: {payload} от {uid}")

            try:
                if payload == "main_menu":
                    show_main_menu(cid)
                elif payload == "choose_folder" or payload == "change_folder":
                    show_folder_selection(cid)
                elif payload == "start_publish":
                    folder = user_folders.get(uid)
                    if folder:
                        if user_publication_status.get(uid, False):
                            send_message(cid, "⚠️ Публикация уже запущена!")
                        else:
                            user_publication_status[uid] = True
                            send_message(cid, "🚀 Начинаю публикацию...")
                            # Вызываем функцию отдельным потоком логики (в данном коде последовательно)
                            publish_posts(uid, cid, folder)
                    else:
                        send_message(cid, "❌ Сначала выберите папку!")
                        show_folder_selection(cid)
                elif payload == "stop_publication":
                    user_publication_status[uid] = False
                    send_message(cid, "⏹ Останавливаю публикацию...")
                    time.sleep(2)
                    show_main_menu(cid)
                elif payload == "help":
                    send_message(
                        cid,
                        "📖 **Помощь**\n\n"
                        "1. Выберите папку\n"
                        "2. Нажмите «Начать публикацию»\n"
                        "3. Бот опубликует посты\n\n"
                        "📂 Имя папки: название -ID_группы"
                    )
                    show_main_menu(cid)
            except Exception as btn_err:
                logger.error(f"❌ КРИТИЧЕСКАЯ ошибка при обработке кнопки: {btn_err}")
                # Защита от падения вебхука
                try:
                    send_message(cid, "⚠️ Произошла внутренняя ошибка бота.")
                except:
                    pass

        logger.info("=" * 50)
        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ГЛОБАЛЬНАЯ ОШИБКА WEBHOOK: {e}", exc_info=True)
        return jsonify({"ok": True}), 200  # Возвращаем OK платформе, даже если у нас упал Python


@app.route('/')
def index():
    return "🤖 MAX Bot is running!", 200

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
