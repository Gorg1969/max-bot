from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import time
import re
import random
import urllib3
from modules import GoogleDrive, Publisher, Scheduler, UserState

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ ==========
drive = GoogleDrive()
scheduler = Scheduler()
user_state = UserState()

# ========== API КЛИЕНТ ==========
class MaxAPIClient:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = TOKEN
    
    def send_message(self, user_id, text, format="markdown"):
        try:
            payload = {"text": text, "format": format}
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"user_id": user_id},
                json=payload,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

api_client = MaxAPIClient()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ СО ССЫЛКАМИ ==========
def parse_links_from_string(text):
    pattern = r'https://drive\.google\.com/drive/folders/[a-zA-Z0-9_-]+'
    return re.findall(pattern, text)

def extract_group_id(folder_name):
    match = re.search(r'-(\d+)', folder_name)
    return match.group(1) if match else None

def get_folder_name(folder_id):
    """Получение названия папки по ID"""
    try:
        url = f"https://drive.google.com/drive/folders/{folder_id}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        name_pattern = r'<span class="[^"]*">([^<]+)</span>'
        names = re.findall(name_pattern, response.text)
        return names[0] if names else "Неизвестная папка"
    except Exception as e:
        logger.error(f"❌ Ошибка получения названия: {e}")
        return "Неизвестная папка"

# ========== ПУБЛИКАЦИЯ ==========
def start_publication(user_id, links):
    logger.info(f"🚀 Запуск публикации для {user_id}, ссылок: {len(links)}")
    
    folders_to_publish = []
    errors = []
    
    for i, folder_url in enumerate(links):
        folder_id = drive.extract_folder_id(folder_url)
        if not folder_id:
            errors.append(f"Ссылка {i+1}: не удалось извлечь ID")
            continue
        
        folder_name = get_folder_name(folder_id)
        group_id = extract_group_id(folder_name)
        
        if not group_id:
            errors.append(f"Ссылка {i+1}: нет ID группы в названии '{folder_name}'")
            continue
        
        folders_to_publish.append({
            'url': folder_url,
            'id': folder_id,
            'name': folder_name,
            'group_id': group_id
        })
    
    if not folders_to_publish:
        api_client.send_message(user_id, "❌ Не найдено папок с ID групп для публикации.")
        return
    
    total = len(folders_to_publish)
    api_client.send_message(user_id, f"✅ Найдено {total} папок. Начинаю публикацию...")
    
    published = 0
    publication_errors = []
    post_number = 0
    
    for folder in folders_to_publish:
        post_number += 1
        
        if not user_state.is_publication_active(user_id):
            api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            break
        
        if post_number > 1:
            delay = random.randint(60, 180)
            logger.info(f"⏳ Задержка {delay} сек. перед постом {post_number}")
            time.sleep(delay)
        
        if (post_number - 1) % 10 == 0 and post_number > 1:
            logger.info("⏳ Пауза 5 минут")
            time.sleep(300)
        
        # Публикуем папку
        success, msg = drive.publish_folder(folder['id'], folder['group_id'], post_number, total)
        if success:
            published += 1
            logger.info(f"✅ Опубликовано: {folder['name']}")
        else:
            publication_errors.append(f"{folder['name']}: {msg}")
            logger.error(f"❌ Ошибка: {folder['name']} - {msg}")
    
    # Итог
    result_msg = f"✅ **ПУБЛИКАЦИЯ ЗАВЕРШЕНА!**\n\n📊 Всего папок: {total}\n✅ Опубликовано: {published}\n❌ Ошибок: {len(publication_errors)}"
    if publication_errors:
        result_msg += "\n\n⚠️ Ошибки:\n" + "\n".join(publication_errors[:5])
        if len(publication_errors) > 5:
            result_msg += f"\n... и ещё {len(publication_errors) - 5} ошибок"
    
    api_client.send_message(user_id, result_msg)
    user_state.stop_publication(user_id)

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
            api_client.send_message(
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
            user_state.stop_publication(user_id)
            api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200

        if text and 'drive.google.com' in text:
            links = parse_links_from_string(text)
            if links:
                user_state.start_publication(user_id)
                start_publication(user_id, links)
            else:
                api_client.send_message(user_id, "❌ Ссылок не найдено")
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
