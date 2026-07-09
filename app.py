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
    "min_delay": 60,            # 1 минута
    "max_delay": 180,           # 3 минуты
    "batch_size": 10,           # 10 постов
    "batch_pause": 300,         # 5 минут
}

# ========== ХРАНИЛИЩЕ ==========
user_states = {}
user_publications = {}
user_links = {}

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
def extract_folder_id_from_url(url):
    patterns = [
        r'folders/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'([a-zA-Z0-9_-]{28,})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def extract_group_id(folder_name):
    match = re.search(r'-(\d+)', folder_name)
    if match:
        return match.group(1)
    return None

# ========== ПОЛУЧЕНИЕ ФАЙЛОВ ==========
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

# ========== ПАРСИНГ ФАЙЛА ==========
def parse_links_file(content):
    lines = content.strip().split('\n')
    links = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and 'drive.google.com' in line:
            links.append(line)
    return links

# ========== ПУБЛИКАЦИЯ ПАПКИ ==========
def publish_folder(folder_id, group_id, post_number=None, total_posts=None):
    try:
        logger.info(f"📤 Публикация {folder_id} -> {group_id}")
        
        files = get_public_files(folder_id)
        if not files:
            return False, "Нет файлов"
        
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

# ========== ПОИСК ПОДПАПОК ==========
def find_subfolders_with_id(folder_url):
    folder_id = extract_folder_id_from_url(folder_url)
    if not folder_id:
        return [], "Неверная ссылка"
    
    try:
        url = f"https://drive.google.com/drive/folders/{folder_id}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        folder_pattern = r'https://drive.google.com/drive/folders/([a-zA-Z0-9_-]+)[^"]*'
        folder_ids = re.findall(folder_pattern, response.text)
        folder_ids = list(set(folder_ids))
        
        name_pattern = r'<span class="[^"]*">([^<]+)</span>'
        names = re.findall(name_pattern, response.text)
        
        result = []
        for i, fid in enumerate(folder_ids):
            name = names[i] if i < len(names) else f"Папка {i+1}"
            if extract_group_id(name):
                result.append({'id': fid, 'name': name})
        
        return result, None
    except Exception as e:
        return [], str(e)

# ========== ЗАПУСК ПУБЛИКАЦИИ ==========
def start_publication(user_id, links):
    logger.info(f"🚀 Запуск публикации для {user_id}, ссылок: {len(links)}")
    
    all_subfolders = []
    errors = []
    
    for i, folder_url in enumerate(links):
        logger.info(f"📌 Обработка ссылки {i+1}/{len(links)}")
        subfolders, error = find_subfolders_with_id(folder_url)
        
        if error:
            errors.append(f"Ссылка {i+1}: {error}")
            continue
        
        if not subfolders:
            errors.append(f"Ссылка {i+1}: нет папок с ID")
            continue
        
        all_subfolders.extend(subfolders)
    
    if not all_subfolders:
        send_message(user_id, "❌ Не найдено папок с ID групп для публикации.")
        return
    
    total = len(all_subfolders)
    logger.info(f"📊 Всего папок для публикации: {total}")
    send_message(user_id, f"✅ Найдено {total} папок. Начинаю публикацию...")
    
    published = 0
    publication_errors = []
    post_number = 0
    
    for subfolder in all_subfolders:
        post_number += 1
        
        if not user_publications.get(user_id, True):
            send_message(user_id, "⏹️ Публикация остановлена.")
            break
        
        group_id = extract_group_id(subfolder['name'])
        if not group_id:
            continue
        
        if post_number > 1:
            delay = random.randint(TIMING["min_delay"], TIMING["max_delay"])
            logger.info(f"⏳ Задержка {delay} сек. перед постом {post_number}")
            time.sleep(delay)
        
        if (post_number - 1) % TIMING["batch_size"] == 0 and post_number > 1:
            logger.info(f"⏳ Пауза {TIMING['batch_pause']} сек.")
            time.sleep(TIMING["batch_pause"])
        
        success, msg = publish_folder(subfolder['id'], group_id, post_number, total)
        if success:
            published += 1
        else:
            publication_errors.append(f"{subfolder['name']}: {msg}")
    
    # ========== ИТОГОВОЕ СООБЩЕНИЕ (ТОЛЬКО ОН!) ==========
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
        file_id = None
        
        # ========== ПАРСИНГ ==========
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
                "📄 Отправьте файл .txt со ссылками на папки.\n"
                "Каждая ссылка на новой строке.\n\n"
                "▶️ После загрузки публикация начнётся автоматически.\n"
                "⏹ Для остановки отправьте /stop"
            )
            return jsonify({"ok": True}), 200

        # ========== ОСТАНОВКА ==========
        if text and text.strip() == '/stop':
            user_publications[user_id] = False
            send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200

        # ========== ОБРАБОТКА ФАЙЛА ==========
        if file_id:
            content = download_public_file(file_id)
            if content:
                links = parse_links_file(content)
                if links:
                    user_links[user_id] = links
                    send_message(user_id, f"✅ Получено {len(links)} ссылок. Начинаю публикацию...")
                    user_publications[user_id] = True
                    start_publication(user_id, links)
                else:
                    send_message(user_id, "❌ Ссылок не найдено")
            else:
                send_message(user_id, "❌ Не удалось прочитать файл")
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
