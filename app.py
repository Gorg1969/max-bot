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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN", "f9LHodD0cOJlllLX1fR59yrbAD6H3UWttud4hPu4zQOQnY2SwNo5NIJtSRA5feJviS8obhPIQ2954lD9YGNp")
BASE_URL = "https://platform-api2.max.ru"

# ========== ХРАНИЛИЩА ==========
user_states = {}
user_folders = {}
user_publication_status = {}

# ========== ОТПРАВКА ==========

def send_message(chat_id, text):
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10,
            verify=False
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return False

def send_keyboard(chat_id, text, buttons):
    try:
        kb = []
        for b in buttons:
            kb.append([{"text": b["text"], "type": "callback", "payload": b["payload"]}])
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "attachments": [{"type": "inline_keyboard", "payload": {"buttons": kb}}]
        }
        
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=payload,
            timeout=10,
            verify=False
        )
        logger.info(f"✅ Клавиатура отправлена: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Ошибка клавиатуры: {e}")
        return False

def send_to_group(chat_id, text):
    try:
        r = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json={"chat_id": chat_id, "text": text},
            timeout=10,
            verify=False
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
    except:
        return []

def get_post_text(folder_path):
    try:
        path = Path(folder_path)
        text_files = list(path.glob("*.txt")) + list(path.glob("*.md"))
        if text_files:
            with open(text_files[0], 'r', encoding='utf-8') as f:
                return f.read().strip()
        return None
    except:
        return None

# ========== МЕНЮ ==========

def show_main_menu(chat_id):
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
        send_message(chat_id, "📁 **Укажите путь к папке с постами**\n\n📂 Структура:\nПапка/\n├── Мои тренировки -123456789/\n│   └── post.txt\n└── ...\n\n💡 ID группы в имени папки (с минусом)\n📝 Введите путь:")
        user_states[chat_id] = "waiting_folder"

def publish_posts(chat_id, folder_path):
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
        
        result = send_to_group(
            group_id,
            f"📝 **Пост {i}/{total}**\n📁 {folder['name']}\n\n{text}"
        )
        
        if result:
            published += 1
            send_message(chat_id, f"✅ Пост {i}/{total} опубликован в {group_id}")
        else:
            skipped += 1
            send_message(chat_id, f"❌ Ошибка публикации в {group_id}")
        
        if i < total and user_publication_status.get(chat_id, True):
            delay = random.randint(60, 180)
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
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")
        
        if not data:
            return jsonify({"ok": True}), 200
        
        # Сообщения
        if "message" in data:
            msg = data["message"]
            chat_id = msg.get("recipient", {}).get("chat_id")
            text = msg.get("body", {}).get("text", "")
            
            logger.info(f"💬 Сообщение в чат {chat_id}: {text}")
            
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
                    send_message(chat_id, f"✅ Папка установлена!\nНайдено папок: {len(folders)}")
                    show_main_menu(chat_id)
                else:
                    send_message(chat_id, f"❌ Папка не найдена: {folder_path}")
            else:
                show_main_menu(chat_id)
        
        # Кнопки
        elif "callback_query" in data:
            cb = data["callback_query"]
            chat_id = cb.get("chat_id")
            payload = cb.get("payload", "")
            
            logger.info(f"🔘 Нажата кнопка: {payload}")
            
            if payload == "main_menu":
                show_main_menu(chat_id)
            elif payload == "choose_folder" or payload == "change_folder":
                show_folder_selection(chat_id)
            elif payload == "start_publish":
                folder = user_folders.get(chat_id)
                if folder:
                    if user_publication_status.get(chat_id, False):
                        send_message(chat_id, "⚠️ Публикация уже запущена!")
                    else:
                        send_message(chat_id, "🚀 Начинаю публикацию...")
                        publish_posts(chat_id, folder)
                else:
                    send_message(chat_id, "❌ Сначала выберите папку!")
                    show_folder_selection(chat_id)
            elif payload == "stop_publication":
                user_publication_status[chat_id] = False
                send_message(chat_id, "⏹ Останавливаю публикацию...")
                time.sleep(2)
                show_main_menu(chat_id)
            elif payload == "help":
                send_message(
                    chat_id,
                    "📖 **Помощь**\n\n1. Выберите папку\n2. Нажмите «Начать публикацию»\n3. Бот опубликует посты\n\n📂 Имя папки: название -ID_группы"
                )
                show_main_menu(chat_id)
        
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
        requests.delete(
            f"{BASE_URL}/subscriptions",
            headers={"Authorization": token},
            timeout=10,
            verify=False
        )
        r = requests.post(
            f"{BASE_URL}/subscriptions",
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={"url": webhook_url},
            timeout=10,
            verify=False
        )
        return f"✅ Статус: {r.status_code}\n✅ Ответ: {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
