from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import re
import random
import shutil
import zipfile
import sqlite3
import urllib3

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"
DB_PATH = "/app/data/publications.db"

# ========== ИНИЦИАЛИЗАЦИЯ БД ==========
def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            folder_name TEXT NOT NULL,
            group_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            error TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_publication(user_id, folder_name, group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'INSERT INTO publications (user_id, folder_name, group_id, status) VALUES (?, ?, ?, ?)',
        (user_id, folder_name, group_id, 'pending')
    )
    conn.commit()
    conn.close()

def update_publication_status(folder_name, status, error=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if error:
        c.execute(
            'UPDATE publications SET status = ?, updated_at = CURRENT_TIMESTAMP, error = ? WHERE folder_name = ?',
            (status, error, folder_name)
        )
    else:
        c.execute(
            'UPDATE publications SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE folder_name = ?',
            (status, folder_name)
        )
    conn.commit()
    conn.close()

def get_pending_publications(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'SELECT folder_name, group_id FROM publications WHERE user_id = ? AND status = ?',
        (user_id, 'pending')
    )
    rows = c.fetchall()
    conn.close()
    return rows

def clear_user_data(user_id):
    """Удаление всех данных пользователя"""
    user_folder = os.path.join(DATA_DIR, str(user_id))
    shutil.rmtree(user_folder, ignore_errors=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM publications WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ========== ОТПРАВКА СООБЩЕНИЙ ==========
def send_message(user_id, text):
    try:
        payload = {"text": text, "format": "markdown"}
        response = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            params={"user_id": user_id},
            json=payload,
            timeout=30,
            verify=False
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

# ========== ИЗВЛЕЧЕНИЕ ID ==========
def extract_group_id(folder_name):
    match = re.search(r'-(\d+)', folder_name)
    if match:
        return match.group(1)
    return None

# ========== РАБОТА С ФАЙЛАМИ ==========
def extract_zip(user_id, zip_path):
    """Распаковка ZIP-архива"""
    user_folder = os.path.join(DATA_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(user_folder)
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка распаковки: {e}")
        return False

def get_subfolders(user_id):
    """Получение списка подпапок с ID групп"""
    user_folder = os.path.join(DATA_DIR, str(user_id))
    if not os.path.exists(user_folder):
        return []
    
    items = os.listdir(user_folder)
    subfolders = []
    for item in items:
        item_path = os.path.join(user_folder, item)
        if os.path.isdir(item_path):
            group_id = extract_group_id(item)
            if group_id:
                subfolders.append({'name': item, 'group_id': group_id, 'path': item_path})
    return subfolders

def publish_local_folder(folder_path, group_id, post_number=None, total_posts=None):
    """Публикация одной папки"""
    try:
        # Находим info.txt
        info_file = None
        images = []
        
        for f in os.listdir(folder_path):
            file_path = os.path.join(folder_path, f)
            if os.path.isfile(file_path):
                if f.lower() in ['info.txt', 'info.md']:
                    info_file = file_path
                elif f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    images.append(file_path)
        
        if not info_file:
            return False, "Нет info.txt"
        
        # Читаем info.txt
        with open(info_file, 'r', encoding='utf-8') as f:
            info_text = f.read()
        
        # Отправляем текст
        if info_text:
            if post_number and total_posts:
                header = f"📝 **Пост {post_number}/{total_posts}**\n\n"
                send_message(group_id, header + info_text)
            else:
                send_message(group_id, info_text)
        
        # Отправляем изображения (до 10 штук)
        images = images[:10]
        for image_path in images:
            filename = os.path.basename(image_path)
            send_message(group_id, f"📷 {filename}")
        
        return True, "Успешно"
    except Exception as e:
        return False, str(e)

# ========== ПУБЛИКАЦИЯ ==========
def start_publication(user_id):
    """Запуск публикации из локальной папки"""
    user_folder = os.path.join(DATA_DIR, str(user_id))
    if not os.path.exists(user_folder):
        send_message(user_id, "❌ Нет данных для публикации.")
        return
    
    # Получаем список папок
    subfolders = get_subfolders(user_id)
    if not subfolders:
        send_message(user_id, "❌ Нет папок с ID групп.")
        clear_user_data(user_id)
        return
    
    # Добавляем в БД
    for folder in subfolders:
        add_publication(user_id, folder['name'], folder['group_id'])
    
    total = len(subfolders)
    send_message(user_id, f"✅ Найдено {total} папок. Начинаю публикацию...")
    
    published = 0
    errors = []
    post_number = 0
    
    for folder in subfolders:
        post_number += 1
        update_publication_status(folder['name'], 'processing')
        
        # Задержка (кроме первого)
        if post_number > 1:
            delay = random.randint(60, 180)
            logger.info(f"⏳ Задержка {delay} сек. перед постом {post_number}")
            time.sleep(delay)
        
        # Пауза после 10 постов
        if (post_number - 1) % 10 == 0 and post_number > 1:
            logger.info("⏳ Пауза 5 минут")
            time.sleep(300)
        
        success, msg = publish_local_folder(
            folder['path'], 
            folder['group_id'], 
            post_number, 
            total
        )
        
        if success:
            published += 1
            update_publication_status(folder['name'], 'done')
            logger.info(f"✅ Опубликовано: {folder['name']}")
            # Удаляем папку сразу после публикации
            shutil.rmtree(folder['path'])
        else:
            errors.append(f"{folder['name']}: {msg}")
            update_publication_status(folder['name'], 'error', msg)
            logger.error(f"❌ Ошибка: {folder['name']} - {msg}")
    
    # Итог
    result_msg = f"✅ **ПУБЛИКАЦИЯ ЗАВЕРШЕНА!**\n\n📊 Всего папок: {total}\n✅ Опубликовано: {published}\n❌ Ошибок: {len(errors)}"
    if errors:
        result_msg += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:5])
        if len(errors) > 5:
            result_msg += f"\n... и ещё {len(errors) - 5} ошибок"
    
    send_message(user_id, result_msg)
    clear_user_data(user_id)

# ========== ЭНДПОИНТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!", 200

@app.route('/health')
def health():
    return {"status": "ok"}, 200

@app.route('/setup_webhook')
def setup_webhook():
    token = request.args.get('token') or TOKEN
    if not token:
        return "❌ Токен не найден", 400
    
    webhook_url = "https://maxbot.bothost.tech/webhook"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    
    try:
        r = requests.post(
            "https://platform-api2.max.ru/subscriptions",
            headers=headers,
            json={"url": webhook_url},
            timeout=10,
            verify=False
        )
        return f"✅ Вебхук настроен: {r.status_code}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id = None
        text = None
        file_id = None
        
        if 'message' in data:
            msg = data['message']
            if 'sender' in msg:
                user_id = msg['sender'].get('user_id')
            if 'body' in msg:
                body = msg['body']
                text = body.get('text')
                if 'attachments' in body:
                    for att in body['attachments']:
                        if att.get('type') == 'file':
                            file_id = att.get('payload', {}).get('id')
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text={text}, file_id={file_id}")

        # ========== КОМАНДА /start ==========
        if text and text.strip() == '/start':
            send_message(
                user_id,
                "🏠 **Главное меню**\n\n"
                "📤 **Загрузите ZIP-архив** с папками для публикации.\n\n"
                "📌 **Структура архива:**\n"
                "```\n"
                "архив.zip\n"
                "├── Самосвалы 8 -76576474415864/\n"
                "│   ├── info.txt\n"
                "│   ├── image1.jpg\n"
                "│   └── image2.jpg\n"
                "└── Экскаваторы -987654321/\n"
                "    ├── info.txt\n"
                "    └── image.jpg\n"
                "```\n\n"
                "▶️ После загрузки публикация начнётся автоматически.\n"
                "⏹ Для остановки отправьте /stop"
            )
            return jsonify({"ok": True}), 200

        # ========== ОСТАНОВКА ==========
        if text and text.strip() == '/stop':
            send_message(user_id, "⏹️ Публикация остановлена.")
            clear_user_data(user_id)
            return jsonify({"ok": True}), 200

        # ========== ОБРАБОТКА ЗАГРУЖЕННОГО ФАЙЛА ==========
        if file_id:
            send_message(user_id, "📥 Получаю архив...")
            
            # Скачиваем файл с Google Drive
            try:
                url = f"https://drive.google.com/uc?export=download&id={file_id}"
                response = requests.get(url, timeout=30)
                if response.status_code != 200:
                    send_message(user_id, "❌ Не удалось скачать файл.")
                    return jsonify({"ok": True}), 200
            except Exception as e:
                send_message(user_id, f"❌ Ошибка скачивания: {e}")
                return jsonify({"ok": True}), 200
            
            # Сохраняем временный архив
            user_folder = os.path.join(DATA_DIR, str(user_id))
            os.makedirs(user_folder, exist_ok=True)
            zip_path = os.path.join(user_folder, "temp.zip")
            with open(zip_path, 'wb') as f:
                f.write(response.content)
            
            # Распаковываем
            if extract_zip(user_id, zip_path):
                os.remove(zip_path)
                send_message(user_id, "✅ Архив распакован. Начинаю публикацию...")
                start_publication(user_id)
            else:
                send_message(user_id, "❌ Ошибка распаковки архива.")
                shutil.rmtree(user_folder, ignore_errors=True)
            
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500
@app.route('/debug_webhook', methods=['POST'])
def debug_webhook():
    """Диагностика: показывает, что приходит от MAX"""
    data = request.get_json()
    logger.info("=" * 50)
    logger.info("🔍 ДИАГНОСТИКА ВЕБХУКА")
    logger.info(json.dumps(data, indent=2, ensure_ascii=False))
    return jsonify({"ok": True}), 200
# ========== ЗАПУСК ==========

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
