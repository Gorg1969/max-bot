# app.py - с утилиткой отладки
from flask import Flask, request, jsonify, render_template_string, send_file
import requests
import logging
import os
import shutil
import urllib3
import json
import threading
import time
import queue
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from werkzeug.exceptions import ClientDisconnected
from modules import Database, FileManager, Publisher, WebInterface
from modules.report_generator import ReportGenerator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# Настройка логирования с детальным выводом
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем отдельный логгер для API запросов
api_logger = logging.getLogger('api_debug')
api_logger.setLevel(logging.DEBUG)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

db = Database()
fm = FileManager(DATA_DIR)

# ========== УТИЛИТКА ДЛЯ ОТЛАДКИ ==========
class DebugAPIClient:
    """Клиент с детальным логированием всех запросов"""
    
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL
        self.debug_dir = "/app/debug_logs"
        os.makedirs(self.debug_dir, exist_ok=True)
        
    def _log_request(self, method: str, url: str, headers: dict, data: dict, response: requests.Response):
        """Логирует запрос и ответ в файл"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            log_file = os.path.join(self.debug_dir, f"request_{timestamp}.log")
            
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"METHOD: {method}\n")
                f.write(f"URL: {url}\n")
                f.write("-" * 40 + "\n")
                f.write("HEADERS:\n")
                for key, value in headers.items():
                    # Скрываем токен в логах
                    if key.lower() == 'authorization':
                        value = value[:15] + "..." if value else ""
                    f.write(f"  {key}: {value}\n")
                f.write("-" * 40 + "\n")
                f.write("REQUEST DATA:\n")
                f.write(json.dumps(data, indent=2, ensure_ascii=False) if data else "None\n")
                f.write("-" * 40 + "\n")
                f.write("RESPONSE:\n")
                f.write(f"STATUS: {response.status_code}\n")
                f.write(f"HEADERS:\n")
                for key, value in response.headers.items():
                    f.write(f"  {key}: {value}\n")
                f.write("-" * 40 + "\n")
                f.write("BODY (first 2000 chars):\n")
                body = response.text[:2000] if response.text else "Empty"
                f.write(body)
                if response.text and len(response.text) > 2000:
                    f.write(f"\n... (truncated, total {len(response.text)} chars)")
                f.write("\n" + "=" * 80 + "\n")
                
            logger.info(f"📝 Лог запроса сохранен: {log_file}")
            return log_file
            
        except Exception as e:
            logger.error(f"❌ Ошибка логирования: {e}")
            return None
    
    def _parse_response(self, response: requests.Response) -> tuple:
        """Парсит ответ с обработкой ошибок"""
        try:
            # Пробуем получить JSON
            if response.status_code == 200:
                try:
                    return True, response.json()
                except json.JSONDecodeError:
                    return False, f"Не JSON: {response.text[:200]}"
            else:
                # Сохраняем тело ответа для анализа
                body_preview = response.text[:500] if response.text else "Empty"
                return False, f"Код {response.status_code}: {body_preview}"
        except Exception as e:
            return False, str(e)
    
    def send_message(self, user_id, text, attachments=None):
        """Отправляет сообщение пользователю с логированием"""
        if not self.token:
            return False
        
        try:
            payload = {"text": text, "format": "markdown"}
            if attachments:
                payload["attachments"] = attachments
            
            url = f"{self.base_url}/messages"
            headers = {
                "Authorization": self.token,
                "Content-Type": "application/json"
            }
            params = {"user_id": user_id}
            
            logger.info(f"📤 [API] Отправка сообщения пользователю {user_id}")
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=30,
                verify=False
            )
            
            self._log_request("POST", url, headers, {"params": params, "payload": payload}, response)
            
            success, result = self._parse_response(response)
            if not success:
                logger.error(f"❌ Ошибка отправки пользователю {user_id}: {result}")
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def upload_file(self, image_data) -> Optional[str]:
        """Загружает файл с логированием"""
        if not self.token:
            return None
        
        try:
            # 1. Получаем URL для загрузки
            url = f"{self.base_url}/uploads"
            headers = {"Authorization": self.token}
            params = {"type": "image"}
            
            logger.info(f"📤 [API] Запрос URL для загрузки")
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                timeout=30,
                verify=False
            )
            
            self._log_request("POST", url, headers, {"params": params}, response)
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения URL: {response.status_code}")
                return None
            
            upload_data = response.json()
            upload_url = upload_data.get('url')
            
            if not upload_url:
                logger.error(f"❌ Не получен URL: {upload_data}")
                return None
            
            # 2. Извлекаем байты изображения
            if isinstance(image_data, dict):
                if 'data' in image_data:
                    img_data = image_data['data']
                else:
                    for key, value in image_data.items():
                        if isinstance(value, (list, bytes, bytearray)):
                            img_data = value
                            break
                    else:
                        logger.error(f"❌ В словаре нет данных: {image_data.keys()}")
                        return None
            else:
                img_data = image_data
            
            if isinstance(img_data, list):
                image_bytes = bytes(img_data)
            elif isinstance(img_data, (bytes, bytearray)):
                image_bytes = bytes(img_data)
            else:
                logger.error(f"❌ Неподдерживаемый тип данных: {type(img_data)}")
                return None
            
            # 3. Отправляем файл
            files = {'data': ('image.jpg', image_bytes, 'image/jpeg')}
            
            logger.info(f"📤 [API] Загрузка файла ({len(image_bytes)} байт)")
            
            upload_response = requests.post(
                upload_url,
                files=files,
                timeout=60,
                verify=False
            )
            
            self._log_request("POST", upload_url, {}, {"files": files}, upload_response)
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Ошибка загрузки: {upload_response.status_code}")
                return None
            
            upload_result = upload_response.json()
            
            # 4. Извлекаем токен
            token = None
            if 'photos' in upload_result and isinstance(upload_result['photos'], dict):
                for photo_data in upload_result['photos'].values():
                    if isinstance(photo_data, dict) and 'token' in photo_data:
                        token = photo_data['token']
                        break
            
            if not token and 'token' in upload_result:
                token = upload_result['token']
            
            if token:
                logger.info(f"✅ Файл загружен, токен: {token[:20]}...")
                return token
            else:
                logger.error(f"❌ Не получен токен: {upload_result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def send_to_chat(self, chat_id: str, text: str, image_tokens: List[str]) -> bool:
        """Отправляет сообщение в чат с логированием"""
        if not self.token:
            return False
        
        try:
            attachments = []
            for token in image_tokens[:10]:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            payload = {
                "text": text,
                "format": "markdown"
            }
            
            if attachments:
                payload["attachments"] = attachments
            
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            
            url = f"{self.base_url}/messages"
            headers = {
                "Authorization": self.token,
                "Content-Type": "application/json"
            }
            params = {"chat_id": chat_id_with_dash}
            
            logger.info(f"📤 [API] Отправка в чат {chat_id_with_dash} с {len(attachments)} фото")
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=60,
                verify=False
            )
            
            self._log_request("POST", url, headers, {"params": params, "payload": payload}, response)
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение отправлено в чат {chat_id_with_dash}")
                return True
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

# Создаем отладочный клиент
debug_api = DebugAPIClient()

# Переопределяем Publisher с отладочным клиентом
class DebugPublisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.user_publishers: Dict[int, Publisher] = {}
        self.user_locks: Dict[int, threading.Lock] = {}
        self._lock = threading.Lock()
        logger.info("✅ DebugPublisher инициализирован")
    
    def _get_lock(self, user_id: int) -> threading.Lock:
        with self._lock:
            if user_id not in self.user_locks:
                self.user_locks[user_id] = threading.Lock()
            return self.user_locks[user_id]
    
    def _get_publisher(self, user_id: int):
        with self._get_lock(user_id):
            if user_id not in self.user_publishers:
                self.user_publishers[user_id] = Publisher(self.api, self.fm, self.db)
                logger.info(f"📦 Создан публикатор для пользователя {user_id}")
            return self.user_publishers[user_id]
    
    def publish_single_folder(self, user_id: int, folder_name: str, 
                              ad_text: str, metadata_text: str, 
                              images_data: List) -> Tuple[bool, str]:
        publisher = self._get_publisher(user_id)
        return publisher.publish_single_folder(
            user_id, folder_name, ad_text, metadata_text, images_data
        )
    
    def stop(self, user_id: int) -> bool:
        with self._get_lock(user_id):
            if user_id in self.user_publishers:
                self.user_publishers[user_id].stop(user_id)
                del self.user_publishers[user_id]
                logger.info(f"⏹️ Публикатор для пользователя {user_id} остановлен")
                return True
            return False

# Используем обновленный класс Publisher с отладкой
# Модифицируем Publisher чтобы он использовал debug_api
class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api  # Используем debug_api
        self.fm = file_manager
        self.db = db
        self.user_publishers: Dict[int, 'PublisherInstance'] = {}
        self.user_locks: Dict[int, threading.Lock] = {}
        self._lock = threading.Lock()
        logger.info("✅ Publisher инициализирован")
    
    def _get_lock(self, user_id: int) -> threading.Lock:
        with self._lock:
            if user_id not in self.user_locks:
                self.user_locks[user_id] = threading.Lock()
            return self.user_locks[user_id]
    
    def _get_publisher(self, user_id: int) -> 'PublisherInstance':
        with self._get_lock(user_id):
            if user_id not in self.user_publishers:
                self.user_publishers[user_id] = PublisherInstance(
                    self.api, self.fm, self.db, user_id
                )
                logger.info(f"📦 Создан публикатор для пользователя {user_id}")
            return self.user_publishers[user_id]
    
    def publish_single_folder(self, user_id: int, folder_name: str, 
                              ad_text: str, metadata_text: str, 
                              images_data: List) -> Tuple[bool, str]:
        publisher = self._get_publisher(user_id)
        return publisher.publish_single_folder(folder_name, ad_text, metadata_text, images_data)
    
    def stop(self, user_id: int) -> bool:
        with self._get_lock(user_id):
            if user_id in self.user_publishers:
                self.user_publishers[user_id].stop()
                del self.user_publishers[user_id]
                logger.info(f"⏹️ Публикатор для пользователя {user_id} остановлен")
                return True
            return False

class PublisherInstance:
    """Экземпляр публикатора для одного пользователя"""
    
    def __init__(self, api, file_manager, db, user_id: int):
        self.api = api  # debug_api
        self.fm = file_manager
        self.db = db
        self.user_id = user_id
        self.stop_flag = False
        self.lock = threading.Lock()
        self.FOLDER_TIMEOUT = 60
        self.running = False
        self.current_folder = None
        self.total_folders = 0
        self.processed_folders = 0
        self.failed_folders = 0
        self.max_photos_per_ad = 10
        
    def is_stopped(self) -> bool:
        return self.stop_flag
    
    def stop(self):
        with self.lock:
            self.stop_flag = True
            self.running = False
            logger.info(f"⏹️ Остановка публикации для пользователя {self.user_id}")
    
    def extract_chat_id(self, folder_name: str) -> Optional[str]:
        import re
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            chat_id = match.group(1)
            if len(chat_id) >= 10:
                return chat_id
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return match.group(1)
        return None
    
    def publish_single_folder(self, folder_name: str, ad_text: str, 
                              metadata_text: str, images_data: List) -> Tuple[bool, str]:
        try:
            with self.lock:
                self.current_folder = folder_name
                self.total_folders += 1
            
            if self.is_stopped():
                return False, "Остановка пользователем"
            
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            logger.info(f"📤 Извлечен chat_id: {chat_id}")
            
            # Загружаем фото через debug_api
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            image_tokens = []
            
            for i in range(max_images):
                if self.is_stopped():
                    return False, "Остановка пользователем"
                
                img_data = images_data[i]
                if not img_data:
                    continue
                
                logger.info(f"📤 Загрузка изображения {i+1}/{max_images}")
                token = self.api.upload_file(img_data)
                if token:
                    image_tokens.append(token)
                    logger.info(f"✅ Изображение {i+1} загружено")
                else:
                    logger.warning(f"⚠️ Не удалось загрузить изображение {i+1}")
            
            # Отправляем в чат через debug_api
            success = self.api.send_to_chat(chat_id, ad_text, image_tokens)
            
            if not success:
                return False, "Не удалось отправить сообщение"
            
            # Сохраняем метаданные
            import time
            metadata = self._parse_metadata(metadata_text)
            self.db.save_ad_metadata(self.user_id, folder_name, f"-{chat_id}", metadata, time.time())
            self.db.add_publication(self.user_id, folder_name, f"-{chat_id}")
            
            with self.lock:
                self.processed_folders += 1
            
            return True, f"✅ Папка {folder_name} опубликована с {len(image_tokens)} фото"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            with self.lock:
                self.failed_folders += 1
            return False, str(e)
    
    def _parse_metadata(self, metadata_text: str) -> Dict:
        import re
        metadata = {}
        if not metadata_text:
            return metadata
        
        fields = {
            'Название': r'Название:\s*(.+)',
            'Ссылка': r'Ссылка:\s*(.+)',
            'Код предложения': r'Код предложения:\s*(.+)',
            'Цена в лизинге': r'Цена\s*[вВ]\s*лизинге:\s*(.+)',
        }
        
        for key, pattern in fields.items():
            match = re.search(pattern, metadata_text, re.IGNORECASE)
            if match:
                metadata[key] = match.group(1).strip()
        
        return metadata

# Создаем экземпляры с отладкой
api = debug_api  # Используем отладочный клиент
publisher = Publisher(api, fm, db)
report_gen = ReportGenerator(fm, db)

# ========== HTML СТРАНИЦА (с добавлением кнопки скачать логи) ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-top: 0; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; text-align: center; cursor: pointer; transition: all 0.3s; }
        .drop-zone:hover { background: #e3f2fd; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        .drop-zone p { margin: 0; color: #666; }
        .drop-zone .icon { font-size: 48px; display: block; margin-bottom: 10px; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; transition: all 0.3s; }
        .btn-primary { background: #007bff; color: white; }
        .btn-primary:hover { background: #0056b3; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .btn-info { background: #17a2b8; color: white; }
        .btn-info:hover { background: #138496; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
        .file-list { text-align: left; margin: 20px 0; padding: 0; list-style: none; }
        .file-list li { background: #f8f9fa; padding: 10px 15px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #007bff; color: white; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .file-list li .status-badge { font-size: 12px; padding: 2px 10px; border-radius: 20px; }
        .file-list li .status-badge.pending { background: #ffc107; color: #333; }
        .file-list li .status-badge.processing { background: #17a2b8; color: white; }
        .file-list li .status-badge.done { background: #28a745; color: white; }
        .file-list li .status-badge.error { background: #dc3545; color: white; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; }
        .instructions { background: #fff3cd; padding: 15px 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 3px; font-size: 14px; color: #d63384; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; line-height: 1.5; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }
        .selected-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 14px; }
        .report-section { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; text-align: center; }
        .settings-section { background: #e7f5ff; padding: 15px; border-radius: 10px; margin: 15px 0; border: 1px solid #007bff; }
        .settings-section label { display: inline-block; margin-right: 15px; font-weight: bold; }
        .settings-section input[type="number"] { width: 60px; padding: 5px; border: 1px solid #ccc; border-radius: 5px; }
        .settings-section select { padding: 5px; border: 1px solid #ccc; border-radius: 5px; }
        .queue-info { background: #f8f9fa; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #17a2b8; }
        .queue-info strong { color: #17a2b8; }
        .debug-section { background: #f8f9fa; padding: 15px; border-radius: 10px; margin: 10px 0; border: 1px solid #6c757d; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте головную папку (любое название)<br>
            2️⃣ Внутри создайте подпапки объявлений: <code>1 -123456789</code>, <code>2 -987654321</code><br>
            3️⃣ В каждой подпапке: <code>info.txt</code> (текст) и фото (1-10 шт)<br>
            4️⃣ В тексте используйте разделитель <code>#изъятая</code><br>
            5️⃣ Перетащите головную папку в поле ниже
        </div>
        
        <div class="settings-section">
            <h4>⚙️ Настройки публикации</h4>
            <label>
                📸 Максимум фото:
                <input type="number" id="maxPhotos" value="6" min="1" max="10">
            </label>
            <label>
                ⏱️ Задержка между папками (сек):
                <input type="number" id="delayBetween" value="3" min="0" max="30">
            </label>
            <label>
                📋 Очередь:
                <select id="queueMode">
                    <option value="sequential">Последовательная</option>
                    <option value="parallel">Параллельная (макс 3)</option>
                </select>
            </label>
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите головную папку сюда</strong></p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <div class="queue-info" id="queueInfo">
                <strong>📋 Очередь публикации:</strong> 
                <span id="queueStatus">Ожидание</span>
            </div>
            <ul class="file-list" id="fileListContent"></ul>
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
                <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
                <button class="btn btn-warning" onclick="stopPublish()">⏹️ Остановить</button>
                <button class="btn btn-info" onclick="downloadLogs()">📥 Скачать логи</button>
            </div>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="report-section">
            <button class="btn btn-primary" onclick="getReport()">📊 Скачать отчет</button>
            <p style="margin-top: 10px; color: #666; font-size: 14px;">После публикации всех папок</p>
        </div>
        
        <div class="debug-section">
            <button class="btn btn-info" onclick="downloadLogs()">📥 Скачать логи API</button>
            <p style="margin-top: 10px; color: #666; font-size: 14px;">Логи всех запросов к MAX API</p>
        </div>
        
        <div class="footer">⚡ MAX Bot | Загрузка объявлений</div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const userId = urlParams.get('user_id') || 151296248;
        
        let selectedFiles = [];
        let isProcessing = false;
        let isStopped = false;
        let folderQueue = [];
        let currentIndex = 0;
        
        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const fileList = document.getElementById('fileList');
        const fileListContent = document.getElementById('fileListContent');
        const selectedInfo = document.getElementById('selectedInfo');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');
        const queueStatus = document.getElementById('queueStatus');

        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const items = e.dataTransfer.items;
            const files = [];
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry && entry.isDirectory) {
                        readDirectory(entry, files, '');
                    }
                }
            }
            if (files.length > 0) {
                selectedFiles = files;
                displayFiles(selectedFiles);
            }
        });

        folderInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            if (files.length > 0) {
                selectedFiles = files;
                displayFiles(selectedFiles);
            }
        });

        function readDirectory(entry, files, path) {
            const reader = entry.createReader();
            reader.readEntries((entries) => {
                for (let e of entries) {
                    if (e.isDirectory) {
                        readDirectory(e, files, path + e.name + '/');
                    } else {
                        e.file((file) => {
                            file.webkitRelativePath = path + file.name;
                            files.push(file);
                        });
                    }
                }
            });
        }

        function displayFiles(files) {
            fileListContent.innerHTML = '';
            const folders = new Map();
            const fileCount = {};
            
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const folder = parts[0] + '/' + parts[1];
                    if (!folders.has(folder)) {
                        folders.set(folder, []);
                    }
                    folders.get(folder).push(f);
                    if (!fileCount[folder]) fileCount[folder] = 0;
                    fileCount[folder]++;
                }
            });
            
            const sortedFolders = Array.from(folders.keys()).sort();
            
            folderQueue = sortedFolders.map(folder => ({
                name: folder,
                files: folders.get(folder),
                status: 'pending',
                result: null
            }));
            
            sortedFolders.forEach((folder, index) => {
                const li = document.createElement('li');
                const count = fileCount[folder] || 0;
                const displayName = folder.includes('/') ? folder.split('/')[1] : folder;
                li.id = `folder-${index}`;
                li.innerHTML = `
                    <span>📁 <strong>${displayName}</strong></span>
                    <span>
                        <span class="count">${count} файлов</span>
                        <span class="status-badge pending" id="status-${index}">⏳ Ожидание</span>
                    </span>
                `;
                fileListContent.appendChild(li);
            });
            
            selectedInfo.textContent = `✅ Выбрано ${sortedFolders.length} папок, всего ${files.length} файлов`;
            fileList.style.display = 'block';
            updateQueueStatus();
            showStatus('info', '📦 Нажмите "Загрузить" для отправки');
        }

        function updateQueueStatus() {
            const total = folderQueue.length;
            const done = folderQueue.filter(f => f.status === 'done').length;
            const errors = folderQueue.filter(f => f.status === 'error').length;
            const processing = folderQueue.filter(f => f.status === 'processing').length;
            
            if (isStopped) {
                queueStatus.textContent = `⏹️ Остановлено (${done}/${total})`;
            } else if (isProcessing) {
                queueStatus.textContent = `🔄 Обработка... (${done + processing}/${total})`;
            } else if (done === total && total > 0) {
                queueStatus.textContent = `✅ Завершено (${done}/${total})`;
            } else {
                queueStatus.textContent = `📋 Готово к публикации (${done}/${total})`;
            }
            
            if (errors > 0) {
                queueStatus.textContent += ` ⚠️ Ошибок: ${errors}`;
            }
        }

        function updateFolderStatus(index, status, result = '') {
            const badge = document.getElementById(`status-${index}`);
            if (badge) {
                badge.className = `status-badge ${status}`;
                const labels = {
                    'pending': '⏳ Ожидание',
                    'processing': '🔄 Обработка',
                    'done': '✅ Готово',
                    'error': '❌ Ошибка'
                };
                badge.textContent = labels[status] || status;
            }
            folderQueue[index].status = status;
            if (result) {
                folderQueue[index].result = result;
            }
            updateQueueStatus();
        }

        function clearFiles() {
            if (isProcessing) {
                if (!confirm('Остановить публикацию и очистить?')) return;
                stopPublish();
            }
            selectedFiles = [];
            folderQueue = [];
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            progress.textContent = '0%';
            folderInput.value = '';
            isStopped = false;
            currentIndex = 0;
        }

        function addLog(message) {
            logDiv.style.display = 'block';
            logDiv.textContent += message + '\\n';
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        function showStatus(type, message) {
            statusDiv.className = 'status ' + type;
            statusDiv.textContent = message;
            statusDiv.style.display = 'block';
        }

        function getReport() {
            window.open(`/report/${userId}`, '_blank');
        }

        function downloadLogs() {
            window.open(`/download_logs`, '_blank');
        }

        function stopPublish() {
            isStopped = true;
            isProcessing = false;
            addLog('⏹️ Публикация остановлена пользователем');
            showStatus('warning', '⏹️ Публикация остановлена');
            
            fetch('/stop_publish', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(userId) })
            }).catch(e => console.error('Ошибка остановки:', e));
        }

        async function prepareFolderData(folderName, files, maxPhotos) {
            const txtFile = files.find(f => f.name === 'info' || f.name.endsWith('.txt'));
            if (!txtFile) {
                return null;
            }
            
            let fullText = await txtFile.text();
            
            let adText = fullText;
            let metadataText = '';
            
            if (fullText.includes('#изъятая')) {
                const parts = fullText.split('#изъятая');
                adText = parts[0].trim();
                metadataText = parts[1] ? parts[1].trim() : '';
            }
            
            const imageFiles = files
                .filter(f => f.type && f.type.startsWith('image/'))
                .slice(0, maxPhotos);
            
            const images = [];
            for (const img of imageFiles) {
                try {
                    const arrayBuffer = await img.arrayBuffer();
                    images.push({
                        name: img.name,
                        data: Array.from(new Uint8Array(arrayBuffer)),
                        type: img.type || 'image/jpeg'
                    });
                } catch (e) {
                    addLog(`⚠️ Ошибка чтения ${img.name}: ${e.message}`);
                }
            }
            
            return {
                folderName: folderName,
                adText: adText,
                metadataText: metadataText,
                fullText: fullText,
                images: images
            };
        }

        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }
            
            if (isProcessing) {
                addLog('⚠️ Обработка уже выполняется, подождите...');
                return;
            }
            
            const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 3;
            const delayBetween = parseInt(document.getElementById('delayBetween').value) || 2;
            const queueMode = document.getElementById('queueMode').value;
            
            isProcessing = true;
            isStopped = false;
            currentIndex = 0;
            
            showStatus('info', '⏳ Подготовка данных...');
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            progress.textContent = '0%';
            logDiv.textContent = '';
            addLog('🚀 Начинаем обработку...');
            addLog(`📸 Максимум фото: ${maxPhotos}`);
            addLog(`⏱️ Задержка: ${delayBetween} сек`);
            addLog(`📋 Режим очереди: ${queueMode}`);
            
            folderQueue.forEach((f, i) => {
                updateFolderStatus(i, 'pending');
            });
            
            const totalFolders = folderQueue.length;
            addLog(`📁 Найдено ${totalFolders} папок`);
            showStatus('info', `⏳ Подготовка 0/${totalFolders} папок...`);
            
            let uploadedFolders = 0;
            let failedFolders = 0;
            
            async function processFolder(index) {
                if (isStopped) return;
                
                const folder = folderQueue[index];
                if (!folder || folder.status === 'done') return;
                
                const folderName = folder.name;
                const files = folder.files;
                
                try {
                    updateFolderStatus(index, 'processing');
                    addLog(`📤 Обработка ${index+1}/${totalFolders}: ${folderName}...`);
                    
                    const folderData = await prepareFolderData(folderName, files, maxPhotos);
                    
                    if (!folderData) {
                        addLog(`⚠️ Пропускаем ${folderName}: нет текстового файла`);
                        failedFolders++;
                        updateFolderStatus(index, 'error', 'Нет текстового файла');
                        return;
                    }
                    
                    addLog(`📤 Отправка ${index+1}/${totalFolders}: ${folderName} (${folderData.images.length} фото)`);
                    
                    const response = await fetch('/publish_folder', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            user_id: parseInt(userId),
                            folder: folderData,
                            max_photos: maxPhotos
                        })
                    });
                    
                    let result;
                    const responseText = await response.text();
                    
                    try {
                        result = JSON.parse(responseText);
                    } catch (parseError) {
                        addLog(`⚠️ Сервер вернул не JSON: ${responseText.substring(0, 200)}...`);
                        addLog(`📝 Полный ответ сохранен в логах сервера`);
                        failedFolders++;
                        updateFolderStatus(index, 'error', 'Ошибка сервера: не JSON ответ');
                        return;
                    }
                    
                    if (result.success) {
                        uploadedFolders++;
                        addLog(`✅ ${folderName}: опубликовано`);
                        updateFolderStatus(index, 'done', 'Успешно');
                    } else {
                        failedFolders++;
                        addLog(`❌ ${folderName}: ${result.message || 'Неизвестная ошибка'}`);
                        updateFolderStatus(index, 'error', result.message || 'Неизвестная ошибка');
                    }
                    
                } catch (error) {
                    failedFolders++;
                    addLog(`❌ ${folderName}: ошибка - ${error.message}`);
                    updateFolderStatus(index, 'error', error.message);
                }
                
                const progressPercent = Math.round(((index + 1) / totalFolders) * 100);
                progress.style.width = progressPercent + '%';
                progress.textContent = `${index+1}/${totalFolders}`;
            }
            
            if (queueMode === 'parallel') {
                const maxParallel = 3;
                let activePromises = [];
                
                for (let i = 0; i < totalFolders; i++) {
                    if (isStopped) break;
                    
                    while (activePromises.length >= maxParallel) {
                        await Promise.race(activePromises);
                        activePromises = activePromises.filter(p => !p._resolved);
                    }
                    
                    const promise = processFolder(i);
                    promise._resolved = false;
                    promise.then(() => { promise._resolved = true; });
                    activePromises.push(promise);
                    
                    await new Promise(r => setTimeout(r, Math.max(0, delayBetween * 0.5)));
                }
                
                await Promise.all(activePromises);
                
            } else {
                for (let i = 0; i < totalFolders; i++) {
                    if (isStopped) break;
                    await processFolder(i);
                    
                    if (i < totalFolders - 1 && !isStopped) {
                        await new Promise(r => setTimeout(r, delayBetween * 1000));
                    }
                }
            }
            
            progress.style.width = '100%';
            progress.textContent = `${totalFolders}/${totalFolders}`;
            
            const done = folderQueue.filter(f => f.status === 'done').length;
            const errors = folderQueue.filter(f => f.status === 'error').length;
            
            if (isStopped) {
                showStatus('warning', `⏹️ Остановлено. Загружено ${done} папок, ${errors} с ошибками`);
                addLog(`⏹️ Остановлено. Загружено ${done} папок, ${errors} с ошибками`);
            } else if (errors === 0) {
                showStatus('success', `✅ Загружено ${done} папок!`);
                addLog(`✅ ВСЕ ${done} папок загружены!`);
            } else {
                showStatus('warning', `⚠️ Загружено ${done} папок, ${errors} с ошибками`);
                addLog(`⚠️ Загружено ${done} папок, ${errors} с ошибками`);
            }
            
            if (done > 0) {
                addLog(`\\n📊 Скачать отчет: /report/${userId}`);
            }
            
            isProcessing = false;
        }
    </script>
</body>
</html>
"""

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template_string(UPLOAD_PAGE)

@app.route('/download_logs', methods=['GET'])
def download_logs():
    """Скачивает все логи API в zip архив"""
    try:
        import zipfile
        from io import BytesIO
        
        debug_dir = "/app/debug_logs"
        if not os.path.exists(debug_dir):
            return "❌ Нет логов для скачивания", 404
        
        # Создаем zip архив в памяти
        memory_file = BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename in os.listdir(debug_dir):
                filepath = os.path.join(debug_dir, filename)
                if os.path.isfile(filepath):
                    zf.write(filepath, filename)
        
        memory_file.seek(0)
        return send_file(
            memory_file,
            as_attachment=True,
            download_name=f"api_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mimetype='application/zip'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания логов: {e}")
        return str(e), 500

@app.route('/publish_folder', methods=['POST'])
def publish_folder():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        folder_data = data.get('folder')
        max_photos = data.get('max_photos', 6)
        
        if not user_id or not folder_data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        folder_name = folder_data.get('folderName')
        ad_text = folder_data.get('adText')
        metadata_text = folder_data.get('metadataText')
        images = folder_data.get('images', [])
        
        if len(images) > max_photos:
            images = images[:max_photos]
        
        logger.info(f"📦 Получена папка: {folder_name} от пользователя {user_id}")
        logger.info(f"📝 Текст: {len(ad_text)} символов, 🖼️ Фото: {len(images)} (макс: {max_photos})")
        
        if not TOKEN:
            return jsonify({'success': False, 'message': 'Токен не настроен'}), 500
        
        success, message = publisher.publish_single_folder(
            user_id, folder_name, ad_text, metadata_text, images
        )
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 500
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/stop_publish', methods=['POST'])
def stop_publish():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        publisher.stop(user_id)
        logger.info(f"⏹️ Остановка публикации для пользователя {user_id}")
        return jsonify({'success': True, 'message': 'Публикация остановлена'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка остановки: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
            api.send_message(
                user_id,
                "🏠 **Главное меню**\n\n"
                "🌐 **Загрузить папку:**\n"
                f"🔗 https://maxbot.bothost.tech/upload?user_id={user_id}\n\n"
                "📊 **Получить отчет:**\n"
                f"🔗 https://maxbot.bothost.tech/report/{user_id}\n\n"
                "⏹ **Остановить публикацию:** `/stop`\n\n"
                "📋 **Инструкция:**\n"
                "1. Подготовьте папки с объявлениями\n"
                "2. Используйте разделитель #изъятая\n"
                "3. Фото до 10 шт на объявление\n\n"
                "⚙️ **Настройки в веб-интерфейсе:**\n"
                "• Максимум фото: 1-10\n"
                "• Задержка между папками\n"
                "• Режим очереди: последовательный/параллельный"
            )
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ **Публикация остановлена!**\n\n✅ Все процессы остановлены")
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/report':
            api.send_message(user_id, "📊 Создаю отчет...")
            report_path = report_gen.generate_report(user_id)
            if report_path:
                filename = os.path.basename(report_path)
                download_url = f"https://maxbot.bothost.tech/download_report/{user_id}/{filename}"
                api.send_message(
                    user_id,
                    f"📊 **Отчет создан!**\n\n"
                    f"🔗 [Скачать отчет]({download_url})"
                )
            else:
                api.send_message(user_id, "❌ Нет данных для отчета.")
            return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

@app.route('/report/<int:user_id>')
def report_page(user_id):
    report_path = report_gen.generate_report(user_id)
    if not report_path:
        return "❌ Нет данных для отчета", 404
    
    filename = os.path.basename(report_path)
    download_url = f"/download_report/{user_id}/{filename}"
    
    return f"""
    <html>
    <head><title>Отчет</title></head>
    <body style="font-family: Arial; max-width: 600px; margin: 50px auto; text-align: center;">
        <h1>📊 Отчет готов!</h1>
        <p><a href="{download_url}" style="display: inline-block; padding: 12px 30px; background: #28a745; color: white; text-decoration: none; border-radius: 5px;">📥 Скачать отчет</a></p>
        <p><a href="/upload">⬅️ Вернуться к загрузке</a></p>
    </body>
    </html>
    """

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    try:
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            return "❌ Файл не найден", 404
        
        response = send_file(file_path, as_attachment=True, download_name=filename)
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return str(e), 500

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/status')
def status():
    return {"status": "running", "token_set": bool(TOKEN)}

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
            json={"url": webhook_url, "update_types": ["message_created", "bot_started", "bot_stopped"]},
            timeout=10,
            verify=False
        )
        if r.status_code == 200:
            return f"✅ Вебхук настроен: {webhook_url}"
        else:
            return f"❌ Ошибка: {r.status_code} - {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
    app.run(host='0.0.0.0', port=port, threaded=True)
