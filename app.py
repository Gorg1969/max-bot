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

def get_subfolders_recursive(folder_id, depth=0, max_depth=5, visited=None):
    """Рекурсивное получение всех подпапок с ID групп (без циклов)"""
    if visited is None:
        visited = set()
    
    # Если уже обрабатывали эту папку — пропускаем
    if folder_id in visited:
        logger.info(f"⏭️ Пропускаю уже обработанную папку: {folder_id}")
        return []
    
    visited.add(folder_id)
    
    try:
        url = f"https://drive.google.com/drive/folders/{folder_id}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Ищем ссылки на подпапки
        folder_pattern = r'https://drive.google.com/drive/folders/([a-zA-Z0-9_-]+)[^"]*'
        folder_ids = re.findall(folder_pattern, response.text)
        folder_ids = list(set(folder_ids))
        
        # Пытаемся найти названия
        name_pattern = r'<span class="[^"]*">([^<]+)</span>'
        names = re.findall(name_pattern, response.text)
        
        result = []
        for i, fid in enumerate(folder_ids):
            # Пропускаем текущую папку (саму себя)
            if fid == folder_id:
                continue
            
            name = names[i] if i < len(names) else f"Папка {i+1}"
            
            # Проверяем, есть ли в названии ID группы
            if re.search(r'-(\d+)', name):
                # Есть ID группы — добавляем
                result.append({'id': fid, 'name': name})
                logger.info(f"📁 Найдена папка с ID: {name}")
            else:
                # Нет ID группы — заходим внутрь (рекурсия)
                if depth < max_depth:
                    logger.info(f"📂 Захожу в папку: {name} (глубина {depth+1})")
                    deeper = get_subfolders_recursive(fid, depth + 1, max_depth, visited)
                    result.extend(deeper)
                else:
                    logger.warning(f"⚠️ Максимальная глубина достигнута в папке: {name}")
        
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка получения подпапок: {e}")
        return []

def extract_group_id(folder_name):
    """Извлечение ID группы из названия папки"""
    match = re.search(r'-(\d+)', folder_name)
    if match:
        group_id = match.group(1)
        logger.info(f"✅ Извлечён ID группы: {group_id} из '{folder_name}'")
        return group_id
    else:
        logger.warning(f"⚠️ Не найден ID группы в: '{folder_name}'")
        return None

def get_public_files(folder_id):
    """Получение списка файлов в публичной папке Google Drive"""
    try:
        url = f"https://drive.google.com/drive/folders/{folder_id}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Ищем ID файлов
        file_pattern = r'https://drive.google.com/file/d/([a-zA-Z0-9_-]+)/view[^"]*'
        file_ids = re.findall(file_pattern, response.text)
        
        # Ищем названия файлов
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

def download_public_image(file_id):
    """Скачивание публичного изображения"""
    try:
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        response = requests.get(url, timeout=10)
        return response.content
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания изображения: {e}")
        return None

def publish_folder(user_id, folder_id, group_id):
    """Публикация одной папки"""
    try:
        logger.info(f"📤 Публикация папки {folder_id} в группу {group_id}")
        
        files = get_public_files(folder_id)
        if not files:
            logger.warning(f"⚠️ Нет файлов в папке {folder_id}")
            return False, "Нет файлов в папке"
        
        # Находим info.txt
        info_file = None
        for f in files:
            if f['name'].lower() in ['info.txt', 'info.md']:
                info_file = f
                break
        
        if not info_file:
            logger.warning(f"⚠️ Нет info.txt в папке {folder_id}")
            return False, "Нет info.txt"
        
        # Скачиваем info.txt
        info_text = download_public_file(info_file['id'])
        if not info_text:
            return False, "Не удалось скачать info.txt"
        
        # Отправляем текст в группу
        if info_text:
            api_client.send_message(group_id, info_text)
            logger.info(f"✅ Отправлен info.txt в группу {group_id}")
        
        # Находим изображения (до 10 штук)
        images = [f for f in files if f['name'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))][:10]
        logger.info(f"🖼️ Найдено изображений: {len(images)}")
        
        # Отправляем изображения
        for image in images:
            api_client.send_message(group_id, f"📷 {image['name']}")
            api_client.send_message(group_id, f"🔗 https://drive.google.com/file/d/{image['id']}/view")
            logger.info(f"✅ Отправлено изображение: {image['name']}")
        
        return True, "Успешно"
        
    except Exception as e:
        logger.error(f"❌ Ошибка публикации: {e}")
        return False, str(e)

def start_publication(user_id, folder_url):
    """Запуск публикации"""
    logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
    
    # 1. Извлекаем ID папки
    folder_id = extract_folder_id_from_url(folder_url)
    if not folder_id:
        api_client.send_message(user_id, "❌ Не удалось извлечь ID папки из ссылки.")
        return
    
    api_client.send_message(user_id, f"✅ **Папка принята!**\n\n📁 ID: `{folder_id}`\n⏳ Получаю список подпапок...")
    
    # 2. Получаем список подпапок (рекурсивно, без циклов)
    subfolders = get_subfolders_recursive(folder_id)
    if not subfolders:
        api_client.send_message(user_id, "❌ Не найдено папок с ID групп.")
        return
    
    # Логируем все найденные папки
    for sf in subfolders:
        logger.info(f"📁 Найдена папка: {sf['name']}")
        group_id = extract_group_id(sf['name'])
        if group_id:
            logger.info(f"  ✅ ID группы: {group_id}")
        else:
            logger.warning(f"  ❌ Нет ID группы в названии")
    
    api_client.send_message(
        user_id,
        f"✅ **Найдено папок с ID групп: {len(subfolders)}**\n\n"
        f"📁 Начинаю публикацию...\n"
        f"⏳ Это займёт некоторое время."
    )
    
    # 3. Публикуем каждую папку
    published_count = 0
    errors = []
    
    for i, subfolder in enumerate(subfolders):
        # Извлекаем ID группы из названия
        group_id = extract_group_id(subfolder['name'])
        if not group_id:
            error_msg = f"{subfolder['name']} - нет ID группы"
            errors.append(error_msg)
            api_client.send_message(user_id, f"❌ {error_msg}")
            continue
        
        # Сообщение пользователю о ходе
        api_client.send_message(
            user_id,
            f"📤 **{i+1}/{len(subfolders)}** Публикую: {subfolder['name']}"
        )
        
        # Публикуем папку
        success, msg = publish_folder(user_id, subfolder['id'], group_id)
        if success:
            published_count += 1
            api_client.send_message(user_id, f"✅ {subfolder['name']} - опубликовано")
        else:
            errors.append(f"{subfolder['name']} - {msg}")
            api_client.send_message(user_id, f"❌ {subfolder['name']} - ошибка: {msg}")
        
        # Задержка между постами (2 минуты)
        if i < len(subfolders) - 1:
            api_client.send_message(user_id, f"⏳ Пауза 2 минуты...")
            time.sleep(120)
        
        # Пауза после 10 постов
        if (i + 1) % 10 == 0 and i < len(subfolders) - 1:
            api_client.send_message(user_id, "⏳ Пауза 5 минут...")
            time.sleep(300)
    
    # 4. Завершение
    result_msg = (
        f"✅ **ПУБЛИКАЦИЯ ЗАВЕРШЕНА!**\n\n"
        f"📁 Всего папок: {len(subfolders)}\n"
        f"✅ Опубликовано: {published_count}\n"
        f"❌ Ошибок: {len(subfolders) - published_count}"
    )
    
    if errors:
        result_msg += "\n\n⚠️ **Ошибки:**\n" + "\n".join(errors[:5])
        if len(errors) > 5:
            result_msg += f"\n... и ещё {len(errors) - 5} ошибок"
    
    api_client.send_message(user_id, result_msg)

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
                text = message['body'].get('text')
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text='{text}', payload='{payload}'")

        # Обработка кнопок (callback)
        if payload:
            if payload == "choose_folder":
                api_client.send_message(
                    user_id,
                    "📁 **Введите ссылку на корневую папку Google Drive:**\n\n"
                    "Пример: `https://drive.google.com/drive/folders/ABC123XYZ`"
                )
            elif payload == "start_publish":
                api_client.send_message(
                    user_id,
                    "📁 **Сначала выберите папку через /choose**"
                )
            elif payload == "stop":
                api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            elif payload == "help":
                api_client.send_message(
                    user_id,
                    "📖 **Помощь**\n\n"
                    "/start - Главное меню\n"
                    "/choose - Выбрать папку\n"
                    "/publish - Начать публикацию\n"
                    "/stop - Остановить"
                )
            return jsonify({"ok": True}), 200

        # Обработка команд
        if text:
            text_lower = text.lower().strip()
            
            if text_lower == "/start":
                api_client.send_message(
                    user_id,
                    "🏠 **Главное меню**\n\n"
                    "📂 /choose - Выбрать папку\n"
                    "▶️ /publish - Начать публикацию\n"
                    "⏹ /stop - Остановить\n"
                    "ℹ️ /help - Помощь"
                )
            
            elif text_lower == "/choose":
                api_client.send_message(
                    user_id,
                    "📁 **Введите ссылку на корневую папку Google Drive:**\n\n"
                    "Пример: `https://drive.google.com/drive/folders/ABC123XYZ`"
                )
            
            elif text_lower == "/publish":
                api_client.send_message(
                    user_id,
                    "📁 **Сначала выберите папку через /choose**"
                )
            
            elif text_lower == "/stop":
                api_client.send_message(user_id, "⏹️ Публикация остановлена.")
            
            elif text_lower.startswith("https://drive.google.com/"):
                folder_url = text
                api_client.send_message(user_id, "✅ Папка принята! Начинаю публикацию...")
                start_publication(user_id, folder_url)

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
