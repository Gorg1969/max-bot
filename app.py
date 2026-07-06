from flask import Flask, request, jsonify
import requests
import json
import logging
import re
import time
import random
import os
from pathlib import Path

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = "ВАШ_ТОКЕН_БОТА"  # ВСТАВЬТЕ СЮДА ТОКЕН!
BASE_URL = "https://platform-api2.max.ru"

# ========== ХРАНИЛИЩА ==========
user_states = {}
user_folders = {}
user_publication_status = {}

# ========== ОТПРАВКА СООБЩЕНИЙ ==========

def send_message_to_chat(chat_id, text):
    """Отправка сообщения в чат"""
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10
        )
        logger.info(f"   Отправка: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"   Ошибка отправки: {e}")
        return False

def send_keyboard_to_chat(chat_id, text, buttons):
    """Отправка сообщения с кнопками"""
    try:
        keyboard_buttons = []
        for button in buttons:
            keyboard_buttons.append([{
                "text": button["text"],
                "type": "callback",
                "payload": button["payload"]
            }])
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard_buttons}
            }]
        }
        
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload,
            timeout=10
        )
        logger.info(f"   Клавиатура: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"   Ошибка клавиатуры: {e}")
        return False

def send_to_group(chat_id, text):
    """Отправка поста в группу"""
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10
        )
        return r.status_code == 200
    except:
        return False

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ПАПКАМИ ==========

def get_folders(base_path):
    """Получает список подпапок с ID групп"""
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
    """Получает текст поста из папки"""
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
    """Реалистичная задержка"""
    return random.randint(60, 180)

# ========== МЕНЮ ==========

def show_main_menu(chat_id):
    """Главное меню"""
    folder = user_folders.get(chat_id, "Не выбрана")
    
    send_keyboard_to_chat(
        chat_id,
        f"🏠 **Главное меню**\n\n"
        f"📂 Папка: `{folder}`\n\n"
        f"Выберите действие:",
        [
            {"text": "📂 Выбрать папку", "payload": "choose_folder"},
            {"text": "▶️ Начать публикацию", "payload": "start_publish"},
            {"text": "⏹ Остановить", "payload": "stop_publication"},
            {"text": "ℹ️ Помощь", "payload": "help"}
        ]
    )

def show_folder_selection(chat_id):
    """Выбор папки"""
    current_folder = user_folders.get(chat_id)
    
    if current_folder:
        send_keyboard_to_chat(
            chat_id,
            f"📂 **Текущая папка:**\n`{current_folder}`\n\nЧто хотите сделать?",
            [
                {"text": "📁 Изменить папку", "payload": "change_folder"},
                {"text": "▶️ Начать публикацию", "payload": "start_publish"},
                {"text": "🏠 В главное меню", "payload": "main_menu"}
            ]
        )
    else:
        send_message_to_chat(
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
            "💡 ID группы берется из имени папки (включая минус)\n"
            "   Например: `-123456789`\n\n"
            "📝 Введите путь к папке:"
        )
        user_states[chat_id] = "waiting_folder"

def publish_posts(chat_id, folder_path):
    """Публикация постов"""
    if user_publication_status.get(chat_id, False):
        send_message_to_chat(chat_id, "⚠️ Публикация уже запущена!")
        return
    
    folders = get_folders(folder_path)
    if not folders:
        send_message_to_chat(chat_id, "❌ Нет папок с файлами!")
        return
    
    user_publication_status[chat_id] = True
    total = len(folders)
    published = 0
    skipped = 0
    
    send_message_to_chat(chat_id, f"📁 Найдено: {total}\n🔄 Начинаю публикацию...")
    
    for i, folder in enumerate(folders, 1):
        if not user_publication_status.get(chat_id, True):
            send_message_to_chat(chat_id, f"⏹ Остановлено! Опубликовано: {published}/{total}")
            break
        
        group_id = folder.get("group_id")
        if not group_id:
            skipped += 1
            continue
        
        text = get_post_text(folder["path"])
        if not text:
            skipped += 1
            continue
        
        result = send_to_group(
            group_id,
            f"📝 **Пост {i}/{total}**\n📁 {folder['name']}\n\n{text}"
        )
        
        if result:
            published += 1
            send_message_to_chat(chat_id, f"✅ Пост {i}/{total} опубликован в {group_id}")
        else:
            skipped += 1
            send_message_to_chat(chat_id, f"❌ Ошибка публикации в {group_id}")
        
        if i < total and user_publication_status.get(chat_id, True):
            delay = human_delay()
            mins = delay // 60
            secs = delay % 60
            send_message_to_chat(chat_id, f"⏳ Следующий пост через {mins}м {secs}с")
            time.sleep(delay)
    
    if user_publication_status.get(chat_id, True):
        send_message_to_chat(
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
        
        if not data:
            return jsonify({"ok": True}), 200
        
        # ОБРАБОТКА СООБЩЕНИЙ
        if "message" in data:
            msg = data["message"]
            sender = msg.get("sender", {})
            user_id = sender.get("user_id")
            body = msg.get("body", {})
            text = body.get("text", "")
            chat_id = msg.get("recipient", {}).get("chat_id")
            
            logger.info(f"💬 Сообщение от {user_id} в чат {chat_id}: {text}")
            
            if not chat_id:
                return jsonify({"ok": True}), 200
            
            if text == "/start":
                show_main_menu(chat_id)
                user_states[chat_id] = None
            
            elif chat_id in user_states and user_states[chat_id] == "waiting_folder":
                folder_path = text.strip()
                if os.path.exists(folder_path):
                    user_folders[chat_id] = folder_path
                    user_states[chat_id] = None
                    folders = get_folders(folder_path)
                    send_message_to_chat(
                        chat_id,
                        f"✅ Папка установлена!\nНайдено папок: {len(folders)}"
                    )
                    show_main_menu(chat_id)
                else:
                    send_message_to_chat(chat_id, f"❌ Папка не найдена: {folder_path}")
            
            elif text:
                show_main_menu(chat_id)
        
        # ОБРАБОТКА КНОПОК
        elif "callback_query" in data:
            cb = data["callback_query"]
            chat_id = cb.get("chat_id")
            payload = cb.get("payload", "")
            
            logger.info(f"🔘 Нажата кнопка: {payload} от {chat_id}")
            
            if payload == "main_menu":
                show_main_menu(chat_id)
            
            elif payload == "choose_folder" or payload == "change_folder":
                show_folder_selection(chat_id)
            
            elif payload == "start_publish":
                folder = user_folders.get(chat_id)
                if folder:
                    if user_publication_status.get(chat_id, False):
                        send_message_to_chat(chat_id, "⚠️ Публикация уже запущена!")
                    else:
                        send_message_to_chat(chat_id, "🚀 Начинаю публикацию...")
                        publish_posts(chat_id, folder)
                else:
                    send_message_to_chat(chat_id, "❌ Сначала выберите папку!")
                    show_folder_selection(chat_id)
            
            elif payload == "stop_publication":
                user_publication_status[chat_id] = False
                send_message_to_chat(chat_id, "⏹ Останавливаю публикацию...")
                time.sleep(2)
                show_main_menu(chat_id)
            
            elif payload == "help":
                send_message_to_chat(
                    chat_id,
                    "📖 **Помощь**\n\n"
                    "1. Выберите папку с постами\n"
                    "2. Нажмите «Начать публикацию»\n"
                    "3. Бот опубликует посты в группы\n\n"
                    "📂 Имя папки должно содержать ID группы\n"
                    "   Например: `Мои тренировки -123456789`\n\n"
                    "📝 Текст в формате Markdown"
                )
                show_main_menu(chat_id)
        
        logger.info("=" * 50)
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

@app.route('/')
def index():
    return "🤖 MAX Bot is running on Render.com!", 200

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
