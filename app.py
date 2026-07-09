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

# ========== API КЛИЕНТ ДЛЯ MAX ==========
class MaxAPIClient:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = TOKEN
    
    def get_headers(self):
        return {"Authorization": self.token, "Content-Type": "application/json"}
    
    def send_message(self, user_id, text, format="markdown"):
        try:
            payload = {"text": text, "format": format}
            response = requests.post(
                f"{self.base_url}/messages",
                headers=self.get_headers(),
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

api_client = MaxAPIClient()

# ========== РАБОТА С ПАПКАМИ ==========

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
            return match.group(1)
    return None

def extract_group_id(folder_name):
    """Извлечение ID группы из названия папки"""
    match = re.search(r'-(\d+)', folder_name)
    if match:
        return match.group(1)
    return None

def get_public_files(folder_id):
    """Получение списка файлов в публичной папке Google Drive"""
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
    """Скачивание публичного файла"""
    try:
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        response = requests.get(url, timeout=10)
        return response.text
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания файла: {e}")
        return None

def parse_links_file(content):
    """Парсинг файла со ссылками"""
    lines = content.strip().split('\n')
    links = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            if 'drive.google.com' in line:
                links.append(line)
    return links

def publish_folder(folder_id, group_id):
    """Публикация одной папки (без уведомлений пользователю)"""
    try:
        logger.info(f"📤 Публикация папки {folder_id} в группу {group_id}")
        
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
            api_client.send_message(group_id, info_text)
            logger.info(f"✅ Отправлен info.txt в группу {group_id}")
        
        images = [f for f in files if f['name'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))][:10]
        logger.info(f"🖼️ Найдено изображений: {len(images)}")
        
        for image in images:
            api_client.send_message(group_id, f"📷 {image['name']}")
            api_client.send_message(group_id, f"🔗 https://drive.google.com/file/d/{image['id']}/view")
            logger.info(f"✅ Отправлено изображение: {image['name']}")
        
        return True, "Успешно"
        
    except Exception as e:
        logger.error(f"❌ Ошибка публикации: {e}")
        return False, str(e)

def process_folder(folder_url):
    """Обработка одной папки (поиск подпапок с ID групп)"""
    folder_id = extract_folder_id_from_url(folder_url)
    if not folder_id:
        return [], f"Неверная ссылка: {folder_url}"
    
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
        return [], f"Ошибка доступа: {e}"

def start_publication_from_links(user_id, links):
    """Публикация по списку ссылок (только итоговое сообщение)"""
    logger.info(f"🚀 Запуск публикации из файла для пользователя {user_id}")
    logger.info(f"📊 Получено ссылок: {len(links)}")
    
    total_published = 0
    total_errors = []
    processed_links = 0
    
    for i, folder_url in enumerate(links):
        processed_links += 1
        logger.info(f"📌 Обработка ссылки {i+1}/{len(links)}: {folder_url}")
        
        subfolders, error = process_folder(folder_url)
        
        if error:
            total_errors.append(f"Ссылка {i+1}: {error}")
            continue
        
        if not subfolders:
            total_errors.append(f"Ссылка {i+1}: нет папок с ID групп")
            continue
        
        for subfolder in subfolders:
            group_id = extract_group_id(subfolder['name'])
            if not group_id:
                total_errors.append(f"{subfolder['name']} - нет ID группы")
                continue
            
            success, msg = publish_folder(subfolder['id'], group_id)
            if success:
                total_published += 1
            else:
                total_errors.append(f"{subfolder['name']} - {msg}")
            
            # Задержка между постами (2 минуты)
            time.sleep(120)
            
            # Пауза после 10 постов
            if total_published % 10 == 0:
                logger.info("⏳ Пауза 5 минут...")
                time.sleep(300)
    
    # ОТПРАВЛЯЕМ ТОЛЬКО ИТОГОВОЕ СООБЩЕНИЕ
    result_msg = (
        f"✅ **ПУБЛИКАЦИЯ ЗАВЕРШЕНА!**\n\n"
        f"📊 Обработано ссылок: {processed_links}\n"
        f"✅ Опубликовано папок: {total_published}\n"
        f"❌ Ошибок: {len(total_errors)}"
    )
    
    if total_errors:
        result_msg += "\n\n⚠️ **Ошибки:**\n" + "\n".join(total_errors[:5])
        if len(total_errors) > 5:
            result_msg += f"\n... и ещё {len(total_errors) - 5} ошибок"
    
    api_client.send_message(user_id, result_msg)
    logger.info(f"🏁 Публикация завершена для пользователя {user_id}")

# ========== МЕНЮ С КНОПКАМИ ==========

def show_main_menu(user_id):
    """Главное меню с кнопками"""
    keyboard = {
        "text": "🏠 **Главное меню**\n\nВыберите действие:",
        "format": "markdown",
        "attachments": [{
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [{"text": "📄 Загрузить ссылки", "type": "callback", "payload": "upload_links"}],
                    [{"text": "▶️ Начать публикацию", "type": "callback", "payload": "start_publish"}],
                    [{"text": "⏹ Остановить", "type": "callback", "payload": "stop"}],
                    [{"text": "ℹ️ Помощь", "type": "callback", "payload": "help"}]
                ]
            }
        }]
    }
    
    response = requests.post(
        f"{BASE_URL}/messages",
        headers=api_client.get_headers(),
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
    return {"status": "ok", "time": time.strftime('%Y-%m-%d %H:%M:%S')}, 200

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
        
        # Извлекаем данные
        if 'callback' in data:
            callback = data['callback']
            payload = callback.get('payload')
            if 'user' in callback:
                user_id = callback['user'].get('user_id')
        
        elif 'message' in data:
            message = data['message']
            if 'sender' in message:
                user_id = message['sender'].get('user_id')
            if 'body' in message:
                body = message['body']
                text = body.get('text')
                # Проверяем вложения (файлы)
                if 'attachments' in body:
                    for att in body['attachments']:
                        if att.get('type') == 'file':
                            file_id = att.get('payload', {}).get('id')
                            logger.info(f"📎 Найден файл: {file_id}")
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text='{text}', payload='{payload}', file_id={file_id}")

        # ========== ОБРАБОТКА КНОПОК ==========
        if payload:
            if payload == "upload_links":
                api_client.send_message(
                    user_id,
                    "📁 **Отправьте файл со ссылками**\n\n"
                    "Файл должен быть в формате `.txt`.\n"
                    "Каждая ссылка — на новой строке.\n\n"
                    "Пример:\n"
                    "`https://drive.google.com/drive/folders/ABC123`\n"
                    "`https://drive.google.com/drive/folders/DEF456`"
                )
                user_states[user_id] = 'waiting_link_file'
            
            elif payload == "start_publish":
                api_client.send_message(
                    user_id,
                    "📁 **Сначала загрузите файл со ссылками через кнопку 'Загрузить ссылки'**"
                )
            
            elif payload == "stop":
                api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            
            elif payload == "help":
                api_client.send_message(
                    user_id,
                    "📖 **Помощь**\n\n"
                    "1. Нажмите 'Загрузить ссылки'\n"
                    "2. Отправьте файл со ссылками\n"
                    "3. Бот начнёт публикацию автоматически\n\n"
                    "Файл должен быть .txt, каждая ссылка на новой строке.\n"
                    "Ссылки должны вести на папки Google Drive."
                )
            return jsonify({"ok": True}), 200

        # ========== ОБРАБОТКА ФАЙЛА ==========
        if file_id and user_states.get(user_id) == 'waiting_link_file':
            api_client.send_message(user_id, "📥 Получаю файл...")
            
            file_content = download_public_file(file_id)
            if file_content:
                links = parse_links_file(file_content)
                if links:
                    api_client.send_message(
                        user_id,
                        f"✅ **Получено ссылок: {len(links)}**\n\n"
                        f"📁 Начинаю публикацию...\n"
                        f"⏳ Это займёт некоторое время.\n"
                        f"📊 Уведомления о ходе будут только в логах."
                    )
                    user_states[user_id] = None
                    start_publication_from_links(user_id, links)
                else:
                    api_client.send_message(user_id, "❌ Файл не содержит ссылок на Google Drive.")
            else:
                api_client.send_message(user_id, "❌ Не удалось прочитать файл.")
            user_states[user_id] = None
            return jsonify({"ok": True}), 200

        # ========== ОБРАБОТКА КОМАНД (для совместимости) ==========
        if text:
            text_lower = text.lower().strip()
            if text_lower == "/start":
                show_main_menu(user_id)

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
