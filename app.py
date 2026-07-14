import logging
import os
import time
import re
import json
import threading
import hashlib
from enum import Enum
from PIL import Image, ExifTags
import io
import requests
import urllib3
from flask import Flask, request, jsonify, render_template_string

# Отключаем предупреждения о SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# ============================================
# PUBLISHER (КАК ВЧЕРА)
# ============================================

class UserState(Enum):
    IDLE = "idle"
    PUBLISHING = "publishing"
    STOPPED = "stopped"

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.user_states = {}
        self.running = False
        self.stop_requested = False
        self.publish_thread = None
        self.published_hashes = set()
        self.hash_file = "published_hashes.json"
        self._load_published_hashes()
        self.global_stop_file = "global_stop.json"
        self._load_global_stop_state()
    
    def _load_published_hashes(self):
        try:
            if os.path.exists(self.hash_file):
                with open(self.hash_file, 'r') as f:
                    data = json.load(f)
                    self.published_hashes = set(data.get('hashes', []))
                logger.info(f"🔓 Загружено {len(self.published_hashes)} хэшей")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки хэшей: {e}")
    
    def _save_published_hashes(self):
        try:
            with open(self.hash_file, 'w') as f:
                json.dump({'hashes': list(self.published_hashes)}, f)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения хэшей: {e}")
    
    def _load_global_stop_state(self):
        try:
            if os.path.exists(self.global_stop_file):
                with open(self.global_stop_file, 'r') as f:
                    data = json.load(f)
                    self.global_stop = data.get('global_stop', False)
                logger.info(f"🔓 Загружено состояние глобального стопа: {self.global_stop}")
            else:
                self.global_stop = False
                self._save_global_stop_state()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки состояния: {e}")
            self.global_stop = False
    
    def _save_global_stop_state(self):
        try:
            with open(self.global_stop_file, 'w') as f:
                json.dump({'global_stop': self.global_stop}, f)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения состояния: {e}")
    
    def _get_ad_hash(self, folder_path):
        hasher = hashlib.md5()
        try:
            info_path = os.path.join(folder_path, 'info.txt')
            if os.path.exists(info_path):
                with open(info_path, 'rb') as f:
                    hasher.update(f.read())
            files = sorted(os.listdir(folder_path))
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    hasher.update(f.encode())
                    file_path = os.path.join(folder_path, f)
                    if os.path.exists(file_path):
                        hasher.update(str(os.path.getsize(file_path)).encode())
        except Exception as e:
            logger.error(f"❌ Ошибка создания хэша: {e}")
            return str(time.time())
        return hasher.hexdigest()
    
    def extract_chat_id(self, folder_name):
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def fix_image_orientation(self, img):
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif and orientation in exif:
                orientation_value = exif[orientation]
                if orientation_value == 3:
                    img = img.rotate(180, expand=True)
                elif orientation_value == 6:
                    img = img.rotate(270, expand=True)
                elif orientation_value == 8:
                    img = img.rotate(90, expand=True)
        except Exception as e:
            logger.debug(f"⚠️ Ошибка исправления ориентации: {e}")
        return img
    
    def compress_image(self, image_path, max_size_mb=0.8, quality=75):
        try:
            with Image.open(image_path) as img:
                img = self.fix_image_orientation(img)
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                max_dimension = 1280
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
                compressed_data = buffer.getvalue()
                if len(compressed_data) > max_size_mb * 1024 * 1024:
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=50, optimize=True, progressive=True)
                    compressed_data = buffer.getvalue()
                return compressed_data
        except Exception as e:
            logger.error(f"❌ Ошибка сжатия: {e}")
            with open(image_path, 'rb') as f:
                return f.read()
    
    def get_sorted_images(self, folder_path, max_count=10):
        images = []
        if not os.path.exists(folder_path):
            return images
        for file in os.listdir(folder_path):
            if file.lower().endswith(('.jpg', '.jpeg', '.png')):
                if file.startswith('.'):
                    continue
                images.append(file)
        images.sort()
        return images[:max_count]
    
    def stop_global(self):
        self.global_stop = True
        self._save_global_stop_state()
        logger.info("🛑 ГЛОБАЛЬНАЯ ОСТАНОВКА ВСЕХ ПУБЛИКАЦИЙ")
        self.stop_publishing_loop()
        for user_id in list(self.user_states.keys()):
            if self.user_states[user_id] == UserState.PUBLISHING:
                self.user_states[user_id] = UserState.STOPPED
        return True
    
    def reset_global_stop(self):
        self.global_stop = False
        self._save_global_stop_state()
        logger.info("🔄 Глобальный флаг остановки сброшен")
        return True
    
    def start_publishing_loop(self, user_id, check_interval=60):
        if self.running:
            logger.warning("⚠️ Цикл публикации уже запущен")
            return False
        if self.global_stop:
            logger.warning(f"⚠️ Глобальная остановка активна!")
            return False
        self.running = True
        self.stop_requested = False
        self.publish_thread = threading.Thread(
            target=self._publishing_loop,
            args=(user_id, check_interval)
        )
        self.publish_thread.daemon = True
        self.publish_thread.start()
        logger.info(f"🚀 Запущен цикл публикации для пользователя {user_id}")
        return True
    
    def stop_publishing_loop(self):
        if not self.running:
            return False
        logger.info("⏹️ Остановка цикла публикации...")
        self.stop_requested = True
        self.running = False
        if self.publish_thread and self.publish_thread.is_alive():
            self.publish_thread.join(timeout=5)
        logger.info("✅ Цикл публикации остановлен")
        return True
    
    def _publishing_loop(self, user_id, check_interval):
        logger.info(f"🔄 Запущен цикл проверки для {user_id}")
        while not self.stop_requested and self.running:
            try:
                if self.global_stop:
                    logger.info(f"⏹️ Глобальная остановка! Цикл прерван для {user_id}")
                    break
                new_ads = self._check_new_ads(user_id)
                if new_ads:
                    logger.info(f"📢 Найдено {len(new_ads)} новых объявлений")
                    for ad in new_ads:
                        if self.stop_requested or not self.running or self.global_stop:
                            break
                        self._publish_ad(user_id, ad)
                        time.sleep(2)
                for _ in range(check_interval):
                    if self.stop_requested or not self.running or self.global_stop:
                        break
                    time.sleep(1)
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле публикации: {e}")
                time.sleep(10)
        self.running = False
        logger.info(f"⏹️ Цикл публикации для {user_id} завершен")
    
    def _check_new_ads(self, user_id):
        try:
            user_folder = self.fm.get_user_folder(user_id)
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            new_ads = []
            if os.path.exists(samosvaly_path) and os.path.isdir(samosvaly_path):
                for folder_name in os.listdir(samosvaly_path):
                    folder_path = os.path.join(samosvaly_path, folder_name)
                    if os.path.isdir(folder_path):
                        info_path = os.path.join(folder_path, 'info.txt')
                        if os.path.exists(info_path):
                            ad_hash = self._get_ad_hash(folder_path)
                            if ad_hash not in self.published_hashes:
                                new_ads.append(folder_name)
                                self.published_hashes.add(ad_hash)
                                self._save_published_hashes()
            return new_ads
        except Exception as e:
            logger.error(f"❌ Ошибка проверки новых объявлений: {e}")
            return []
    
    def _publish_ad(self, user_id, folder_name):
        try:
            user_folder = self.fm.get_user_folder(user_id)
            folder_path = os.path.join(user_folder, "Самосвалы", folder_name)
            if not os.path.exists(folder_path):
                return False
            info_path = os.path.join(folder_path, 'info.txt')
            with open(info_path, 'r', encoding='utf-8') as f:
                text = f.read()
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                return False
            images = self.get_sorted_images(folder_path, max_count=10)
            logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}, фото: {len(images)}")
            if self.stop_requested or not self.running or self.global_stop:
                logger.info(f"⏹️ Публикация прервана для {folder_name}")
                return False
            photo_files = []
            for img_name in images:
                img_path = os.path.join(folder_path, img_name)
                if os.path.exists(img_path):
                    try:
                        compressed = self.compress_image(img_path)
                        photo_files.append((img_name, compressed))
                    except Exception as e:
                        logger.error(f"❌ Ошибка сжатия {img_name}: {e}")
            if photo_files:
                success = self.api.send_photos_to_chat(chat_id, photo_files, text)
            else:
                success = self.api.send_message_to_chat(chat_id, text)
            if success:
                self.db.add_publication(user_id, folder_name, chat_id)
                logger.info(f"✅ Опубликовано: {folder_name}")
                return True
            else:
                logger.error(f"❌ Не удалось опубликовать: {folder_name}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            return False
    
    def start(self, user_id):
        try:
            if self.global_stop:
                logger.warning(f"⚠️ Глобальная остановка активна!")
                return False
            if self.user_states.get(user_id) == UserState.PUBLISHING:
                logger.warning(f"⚠️ Публикация уже запущена")
                return False
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            self.user_states[user_id] = UserState.PUBLISHING
            user_folder = self.fm.get_user_folder(user_id)
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            if os.path.exists(samosvaly_path) and os.path.isdir(samosvaly_path):
                subfolders = []
                for item in os.listdir(samosvaly_path):
                    item_path = os.path.join(samosvaly_path, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
            else:
                subfolders = self.fm.get_subfolders(user_id)
            if not subfolders:
                self.user_states[user_id] = UserState.IDLE
                return False
            published = 0
            for folder_name in subfolders:
                if self.global_stop:
                    logger.info(f"⏹️ ГЛОБАЛЬНАЯ ОСТАНОВКА!")
                    self.user_states[user_id] = UserState.STOPPED
                    break
                if self.user_states.get(user_id) == UserState.STOPPED:
                    logger.info(f"⏹️ Публикация остановлена пользователем")
                    break
                try:
                    folder_path = os.path.join(samosvaly_path, folder_name)
                    ad_hash = self._get_ad_hash(folder_path)
                    if ad_hash in self.published_hashes:
                        logger.info(f"ℹ️ Объявление {folder_name} уже было опубликовано")
                        continue
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        continue
                    images = self.get_sorted_images(folder_path, max_count=10)
                    if self.global_stop:
                        logger.info(f"⏹️ ГЛОБАЛЬНАЯ ОСТАНОВКА!")
                        self.user_states[user_id] = UserState.STOPPED
                        break
                    if self.user_states.get(user_id) == UserState.STOPPED:
                        break
                    photo_files = []
                    for img_name in images:
                        img_path = os.path.join(folder_path, img_name)
                        if not os.path.exists(img_path):
                            continue
                        try:
                            compressed = self.compress_image(img_path)
                            photo_files.append((img_name, compressed))
                        except Exception as e:
                            logger.error(f"❌ Ошибка сжатия {img_name}: {e}")
                    if photo_files:
                        success = self.api.send_photos_to_chat(chat_id, photo_files, text)
                    else:
                        success = self.api.send_message_to_chat(chat_id, text)
                    if not success:
                        continue
                    self.published_hashes.add(ad_hash)
                    self._save_published_hashes()
                    self.db.add_publication(user_id, folder_name, chat_id)
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"❌ Ошибка при публикации {folder_name}: {e}")
                    continue
            self.user_states[user_id] = UserState.IDLE
            if published > 0:
                logger.info(f"✅ Публикация завершена! Опубликовано {published} объявлений.")
            else:
                logger.info(f"❌ Не удалось опубликовать ни одного объявления.")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            self.user_states[user_id] = UserState.IDLE
            return False
    
    def stop(self, user_id):
        current_state = self.user_states.get(user_id, UserState.IDLE)
        if current_state == UserState.PUBLISHING:
            self.user_states[user_id] = UserState.STOPPED
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
            return True
        elif current_state == UserState.STOPPED:
            logger.info(f"ℹ️ Публикация уже остановлена для пользователя {user_id}")
            return False
        else:
            logger.info(f"ℹ️ Публикация не активна для пользователя {user_id}")
            return False

# ============================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================

def get_token():
    return (
        os.environ.get('API_TOKEN') or
        os.environ.get('MAX_TOKEN') or
        os.environ.get('MAX_BOT_TOKEN')
    )

app = Flask(__name__)

# Заглушка для БД и FileManager (замените на свои)
class Database:
    def add_publication(self, user_id, folder_name, chat_id):
        logger.info(f"📝 Добавлена публикация: {folder_name} -> {chat_id}")
class FileManager:
    def get_user_folder(self, user_id):
        folder = f"/app/data/user_{user_id}"
        os.makedirs(folder, exist_ok=True)
        return folder
    def get_subfolders(self, user_id):
        return []

db = Database()
fm = FileManager()

# API - будем использовать прямые HTTP запросы
api = None  # Не используем maxapi

publisher = Publisher(api, fm, db)

# Храним ID последнего обработанного обновления
last_update_id = 0

# ========== ОТПРАВКА СООБЩЕНИЙ ==========

def send_message(chat_id, text):
    """Отправка сообщения в чат"""
    token = get_token()
    if not token:
        logger.warning(f"⚠️ Токен не найден!")
        return False
    
    try:
        url = "https://platform-api2.max.ru/messages"
        headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }
        json_data = {
            "chat_id": chat_id,
            "text": text,
        }
        
        logger.info(f"📤 Отправка в чат {chat_id}: {text[:30]}...")
        response = requests.post(url, headers=headers, json=json_data, timeout=30, verify=False)
        
        if response.status_code == 200:
            logger.info(f"✅ Сообщение отправлено в чат {chat_id}")
            return True
        else:
            logger.error(f"❌ Ошибка API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

# ========== ОБРАБОТКА КОМАНД ==========

def handle_command(chat_id, text):
    """Обработка команд"""
    logger.info(f"📩 Обработка команды от {chat_id}: {text}")
    
    if text.startswith('/start'):
        return "👋 Привет! Я бот для публикации объявлений.\nИспользуйте /help для списка команд."
    
    elif text.startswith('/help'):
        return (
            "🤖 Команды:\n"
            "/start - Приветствие\n"
            "/publish - ОДНОКРАТНАЯ публикация\n"
            "/stop - Остановить публикацию\n"
            "/status - Статус бота\n"
            "/stop_global - Глобальная остановка\n"
            "/reset_global - Сброс стопа"
        )
    
    elif text.startswith('/publish'):
        send_message(chat_id, "📢 Начинаю однократную публикацию...")
        threading.Thread(target=publisher.start, args=(chat_id,)).start()
        return None
    
    elif text.startswith('/stop'):
        send_message(chat_id, "⏹️ Останавливаю публикацию...")
        publisher.stop(chat_id)
        return None
    
    elif text.startswith('/stop_global'):
        publisher.stop_global()
        return "🛑 Глобальная остановка ВСЕХ публикаций"
    
    elif text.startswith('/reset_global'):
        publisher.reset_global_stop()
        return "🔄 Глобальный стоп сброшен"
    
    elif text.startswith('/status'):
        status = (
            f"📊 Статус:\n"
            f"• Глобальный стоп: {'❌ ВКЛ' if publisher.global_stop else '✅ ВЫКЛ'}\n"
            f"• Публикация: {'🔄 активна' if publisher.running else '⏸️ не активна'}\n"
            f"• Автоматическая публикация: ⏸️ ОТКЛЮЧЕНА"
        )
        return status
    
    else:
        return f"❓ Неизвестная команда. Используйте /help"

# ========== LONG POLLING ==========

def poll_updates():
    """Основной цикл Long Polling"""
    global last_update_id
    
    logger.info("🔄 Запущен цикл Long Polling через /updates...")
    
    while True:
        try:
            token = get_token()
            if not token:
                logger.error("❌ Токен не найден!")
                time.sleep(10)
                continue
            
            url = "https://platform-api2.max.ru/updates"
            headers = {"Authorization": token}
            params = {
                "offset": last_update_id + 1,
                "limit": 10,
                "timeout": 30,
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=35, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                updates = data.get('updates', [])
                
                if updates:
                    logger.info(f"📨 Получено {len(updates)} обновлений")
                    for update in updates:
                        update_id = update.get('update_id')
                        update_type = update.get('update_type')
                        
                        if update_type == 'message_created':
                            message = update.get('message', {})
                            recipient = message.get('recipient', {})
                            body = message.get('body', {})
                            chat_id = recipient.get('chat_id')
                            text = body.get('text', '')
                            
                            if chat_id and text:
                                logger.info(f"📩 Новое сообщение от {chat_id}: {text}")
                                response_text = handle_command(chat_id, text)
                                if response_text:
                                    send_message(chat_id, response_text)
                        elif update_type == 'bot_started':
                            chat_id = update.get('chat_id')
                            payload = update.get('payload')
                            logger.info(f"🚀 Бот запущен пользователем {chat_id}, payload: {payload}")
                            if chat_id:
                                send_message(chat_id, "👋 Привет! Я бот для публикации объявлений.")
                        
                        if update_id:
                            last_update_id = max(last_update_id, update_id)
                else:
                    logger.debug("📭 Новых обновлений нет")
            else:
                logger.error(f"❌ Ошибка получения обновлений: {response.status_code} - {response.text}")
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в Long Polling: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)

# ========== ВЕБ-ИНТЕРФЕЙС ==========

@app.route('/')
def index():
    return """
    <h1>📤 Бот для публикации объявлений</h1>
    <p>Бот работает в режиме Long Polling</p>
    <p>Отправьте команду /start в диалоге с ботом</p>
    """

@app.route('/status')
def status():
    return jsonify({
        'status': 'running',
        'global_stop': publisher.global_stop,
        'running': publisher.running,
        'polling': True,
        'last_update_id': last_update_id
    })

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    logger.info("📨 Получен запрос на /webhook (заглушка)")
    return jsonify({'status': 'ok'}), 200

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    
    # Запускаем Long Polling в фоне
    poll_thread = threading.Thread(target=poll_updates, daemon=True)
    poll_thread.start()
    logger.info("✅ Long Polling запущен")
    
    logger.info("=" * 50)
    logger.info("🚀 БОТ ЗАПУЩЕН (режим Long Polling)!")
    logger.info("📌 АВТОМАТИЧЕСКАЯ ПУБЛИКАЦИЯ ОТКЛЮЧЕНА")
    logger.info("📌 Используйте /publish для однократной публикации")
    logger.info("📌 ВЕБХУК НЕ НУЖЕН - бот сам опрашивает API")
    logger.info("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=False)
