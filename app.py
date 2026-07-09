from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import re
import urllib3

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"

# ========== ХРАНИЛИЩЕ СОСТОЯНИЙ ==========
user_states = {}

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
        logger.info(f"📤 Ответ: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

# ========== ИЗВЛЕЧЕНИЕ ID ИЗ ССЫЛКИ ==========
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
        logger.error(f"❌ Ошибка: {e}")
        return []

def download_public_file(file_id):
    try:
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        response = requests.get(url, timeout=10)
        return response.text
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return None

# ========== ПАРСИНГ ФАЙЛА СО ССЫЛКАМИ ==========
def parse_links_file(content):
    lines = content.strip().split('\n')
    links = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and 'drive.google.com' in line:
            links.append(line)
    return links

# ========== ПУБЛИКАЦИЯ ПАПКИ ==========
def publish_folder(folder_id, group_id):
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
            send_message(group_id, info_text)
        
        images = [f for f in files if f['name'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))][:10]
        for image in images:
            send_message(group_id, f"📷 {image['name']}\n🔗 https://drive.google.com/file/d/{image['id']}/view")
        
        return True, "Успешно"
    except Exception as e:
        return False, str(e)

# ========== ПОИСК ПОДПАПОК С ID ==========
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
    logger.info(f"🚀 Публикация для {user_id}, ссылок: {len(links)}")
    
    total_published = 0
    errors = []
    
    for i, folder_url in enumerate(links):
        logger.info(f"📌 Ссылка {i+1}/{len(links)}")
        subfolders, error = find_subfolders_with_id(folder_url)
        
        if error:
            errors.append(f"Ссылка {i+1}: {error}")
            continue
        
        if not subfolders:
            errors.append(f"Ссылка {i+1}: нет папок с ID")
            continue
        
        for subfolder in subfolders:
            group_id = extract_group_id(subfolder['name'])
            if not group_id:
                continue
            
            success, msg = publish_folder(subfolder['id'], group_id)
            if success:
                total_published += 1
            else:
                errors.append(f"{subfolder['name']}: {msg}")
            
            time.sleep(120)  # 2 минуты
    
    # Итог
    msg = f"✅ **ПУБЛИКАЦИЯ ЗАВЕРШЕНА!**\n\n📊 Обработано: {len(links)}\n✅ Опубликовано: {total_published}\n❌ Ошибок: {len(errors)}"
    if errors:
        msg += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:5])
    send_message(user_id, msg)

# ========== МЕНЮ ==========
def show_main_menu(user_id):
    keyboard = {
        "text": "🏠 **Главное меню**\n\nВыберите действие:",
        "format": "markdown",
        "attachments": [{
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [{"text": "📄 Загрузить ссылки", "type": "callback", "payload": "upload_links"}],
                    [{"text": "⏹ Остановить", "type": "callback", "payload": "stop"}]
                ]
            }
        }]
    }
    requests.post(
        f"{BASE_URL}/messages",
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
        params={"user_id": user_id},
        json=keyboard,
        timeout=30,
        verify=False
    )

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
        payload = None
        file_id = None
        
        # Простой парсинг
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
        
        if 'callback' in data:
            cb = data['callback']
            payload = cb.get('payload')
            if not user_id and 'user' in cb:
                user_id = cb['user'].get('user_id')
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text={text}, payload={payload}, file_id={file_id}")

        # Кнопки
        if payload:
            if payload == "upload_links":
                send_message(user_id, "📁 **Отправьте файл .txt со ссылками**\n\nКаждая ссылка на новой строке.")
                user_states[user_id] = 'waiting_file'
            elif payload == "stop":
                send_message(user_id, "⏹️ Остановлено")
            return jsonify({"ok": True}), 200

        # Команда /start
        if text and text.strip() == '/start':
            show_main_menu(user_id)
            return jsonify({"ok": True}), 200

        # Обработка файла
        if file_id and user_states.get(user_id) == 'waiting_file':
            send_message(user_id, "📥 Получаю файл...")
            content = download_public_file(file_id)
            if content:
                links = parse_links_file(content)
                if links:
                    send_message(user_id, f"✅ Получено {len(links)} ссылок. Начинаю публикацию...")
                    user_states[user_id] = None
                    start_publication(user_id, links)
                else:
                    send_message(user_id, "❌ Ссылок не найдено")
            else:
                send_message(user_id, "❌ Не удалось прочитать файл")
            user_states[user_id] = None
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
