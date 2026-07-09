from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import re
import random
import urllib3

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"

# ========== НАСТРОЙКИ ТАЙМИНГОВ ==========
TIMING = {
    "min_delay": 60,
    "max_delay": 180,
    "batch_size": 10,
    "batch_pause": 300,
}

# ========== ХРАНИЛИЩЕ ==========
user_publications = {}

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

# ========== ИЗВЛЕЧЕНИЕ ID ПАПКИ (БЕЗ API) ==========
def extract_folder_id_from_url(url):
    """Извлечение ID папки из ссылки Google Drive"""
    patterns = [
        r'folders/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'([a-zA-Z0-9_-]{28,})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            folder_id = match.group(1)
            logger.info(f"✅ Извлечён ID: {folder_id}")
            return folder_id
    return None

def extract_group_id(folder_name):
    match = re.search(r'-(\d+)', folder_name)
    if match:
        return match.group(1)
    return None

# ========== ПАРСИНГ СТРОКИ СО ССЫЛКАМИ ==========
def parse_links_from_string(text):
    pattern = r'https://drive\.google\.com/drive/folders/[a-zA-Z0-9_-]+'
    links = re.findall(pattern, text)
    return links

# ========== ПОЛУЧЕНИЕ ФАЙЛОВ ИЗ ПАПКИ ==========
def get_public_files(folder_id):
    try:
        url = f"https://drive.google.com/drive/folders/{folder_id}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        file_pattern = r'https://drive.google.com/file/d/([a-zA-Z0-9_-]+)/view[^"]*'
        file_ids = re.findall(file_pattern, response.text)
        
        name_pattern = r'<span class="[^"]*">([^<]+\.(jpg|jpeg|png|gif|txt|md))</span>'
        names = re.findall(name_pattern, response.text)
        
        files = []
        for i, file_id in enumerate(file_ids):
            name = names[i][0] if i < len(names) else f"file_{file_id}"
            files.append({'id': file_id, 'name': name})
        return files
    except Exception as e:
        logger.error(f"❌ Ошибка получения файлов: {e}")
        return []

def download_public_file(file_id):
    try:
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        response = requests.get(url, timeout=10)
        return response.text
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return None

# ========== ПУБЛИКАЦИЯ ПАПКИ ==========
def publish_folder_by_link(folder_url, group_id, post_number=None, total_posts=None):
    try:
        folder_id = extract_folder_id_from_url(folder_url)
        if not folder_id:
            return False, "Не удалось извлечь ID папки"
        
        logger.info(f"📤 Публикация {folder_url} -> {group_id}")
        
        files = get_public_files(folder_id)
        if not files:
            return False, "Нет файлов в папке"
        
        info_file = None
        for f in files:
            if f['name'].lower() in ['info.txt', 'info.md']:
                info_file = f
                break
        
        if not info_file:
            return False, "Нет info.txt"
        
        info_text = download_public_file(info_file['id'])
        if not info_text:
            return False, "Не удалось скачать info.txt"
        
        if info_text:
            if post_number and total_posts:
                header = f"📝 **Пост {post_number}/{total_posts}**\n\n"
                send_message(group_id, header + info_text)
            else:
                send_message(group_id, info_text)
        
        images = [f for f in files if f['name'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))][:10]
        for image in images:
            send_message(group_id, f"📷 {image['name']}\n🔗 https://drive.google.com/file/d/{image['id']}/view")
        
        return True, "Успешно"
    except Exception as e:
        return False, str(e)

# ========== ЗАПУСК ПУБЛИКАЦИИ ==========
def start_publication(user_id, links):
    logger.info(f"🚀 Запуск публикации для {user_id}, ссылок: {len(links)}")
    
    folders_to_publish = []
    errors = []
    
    for i, folder_url in enumerate(links):
        # Извлекаем ID
        folder_id = extract_folder_id_from_url(folder_url)
        if not folder_id:
            errors.append(f"Ссылка {i+1}: не удалось извлечь ID")
            continue
        
        # Получаем название папки
        try:
            url = f"https://drive.google.com/drive/folders/{folder_id}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            name_pattern = r'<span class="[^"]*">([^<]+)</span>'
            names = re.findall(name_pattern, response.text)
            folder_name = names[0] if names else f"Папка {i+1}"
        except:
            folder_name = f"Папка {i+1}"
        
        group_id = extract_group_id(folder_name)
        if not group_id:
            errors.append(f"Ссылка {i+1}: нет ID группы в названии '{folder_name}'")
            continue
        
        folders_to_publish.append({
            'url': folder_url,
            'name': folder_name,
            'group_id': group_id
        })
    
    if not folders_to_publish:
        send_message(user_id, "❌ Не найдено папок с ID групп для публикации.")
        return
    
    total = len(folders_to_publish)
    logger.info(f"📊 Всего папок для публикации: {total}")
    send_message(user_id, f"✅ Найдено {total} папок с ID групп. Начинаю публикацию...")
    
    published = 0
    publication_errors = []
    post_number = 0
    
    for folder in folders_to_publish:
        post_number += 1
        
        if not user_publications.get(user_id, True):
            send_message(user_id, "⏹️ Публикация остановлена.")
            break
        
        if post_number > 1:
            delay = random.randint(TIMING["min_delay"], TIMING["max_delay"])
            logger.info(f"⏳ Задержка {delay} сек. перед постом {post_number}")
            time.sleep(delay)
        
        if (post_number - 1) % TIMING["batch_size"] == 0 and post_number > 1:
            logger.info(f"⏳ Пауза {TIMING['batch_pause']} сек.")
            time.sleep(TIMING["batch_pause"])
        
        success, msg = publish_folder_by_link(
            folder['url'], 
            folder['group_id'], 
            post_number, 
            total
        )
        if success:
            published += 1
            logger.info(f"✅ Опубликовано: {folder['name']}")
        else:
            publication_errors.append(f"{folder['name']}: {msg}")
            logger.error(f"❌ Ошибка: {folder['name']} - {msg}")
    
    result_msg = f"✅ **ПУБЛИКАЦИЯ ЗАВЕРШЕНА!**\n\n📊 Всего папок: {total}\n✅ Опубликовано: {published}\n❌ Ошибок: {len(publication_errors)}"
    if publication_errors:
        result_msg += "\n\n⚠️ Ошибки:\n" + "\n".join(publication_errors[:5])
        if len(publication_errors) > 5:
            result_msg += f"\n... и ещё {len(publication_errors) - 5} ошибок"
    
    send_message(user_id, result_msg)
    logger.info(f"🏁 Публикация завершена для {user_id}")

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
        
        if 'message' in data:
            msg = data['message']
            if 'sender' in msg:
                user_id = msg['sender'].get('user_id')
            if 'body' in msg:
                text = msg['body'].get('text')
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text={text}")

        if text and text.strip() == '/start':
            send_message(
                user_id,
                "🏠 **Главное меню**\n\n"
                "📄 **Отправьте ссылки на папки** (через запятую или с новой строки).\n"
                "В названии папки должен быть ID группы: `Название -123456789`\n\n"
                "📌 **Пример:**\n"
                "`https://drive.google.com/drive/folders/ABC123, https://drive.google.com/drive/folders/DEF456`\n\n"
                "▶️ После отправки публикация начнётся автоматически.\n"
                "⏹ Для остановки отправьте /stop"
            )
            return jsonify({"ok": True}), 200

        if text and text.strip() == '/stop':
            user_publications[user_id] = False
            send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200

        if text and 'drive.google.com' in text:
            links = parse_links_from_string(text)
            if links:
                user_publications[user_id] = True
                start_publication(user_id, links)
            else:
                send_message(user_id, "❌ Ссылок не найдено")
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
