# modules/publisher.py
import logging
import os
import time
import re
import requests
import threading
import shutil
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

class PublisherInstance:
    """Экземпляр публикатора для одного пользователя"""
    
    def __init__(self, api, file_manager, db, user_id: int):
        self.api = api
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
        self.max_photos_per_ad = 10  # Увеличено до 10
        
    def is_stopped(self) -> bool:
        return self.stop_flag
    
    def stop(self):
        with self.lock:
            self.stop_flag = True
            self.running = False
            logger.info(f"⏹️ Остановка публикации для пользователя {self.user_id}")
    
    def get_status(self) -> Dict:
        with self.lock:
            return {
                'user_id': self.user_id,
                'running': self.running,
                'stop_flag': self.stop_flag,
                'current_folder': self.current_folder,
                'total_folders': self.total_folders,
                'processed_folders': self.processed_folders,
                'failed_folders': self.failed_folders,
                'max_photos': self.max_photos_per_ad
            }
    
    def extract_chat_id(self, folder_name: str) -> Optional[str]:
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            chat_id = match.group(1)
            if len(chat_id) >= 10:
                return chat_id
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return match.group(1)
        return None
    
    def _upload_file_to_max(self, image_data, retry_count: int = 3) -> Optional[str]:
        if self.is_stopped():
            return None
        
        for attempt in range(retry_count):
            try:
                if self.is_stopped():
                    return None
                
                response = requests.post(
                    f"{self.api.base_url}/uploads",
                    headers={"Authorization": self.api.token},
                    params={"type": "image"},
                    timeout=30,
                    verify=False
                )
                
                if response.status_code != 200:
                    logger.warning(f"⚠️ Попытка {attempt + 1}: Ошибка получения URL: {response.status_code}")
                    time.sleep(2 ** attempt)
                    continue
                
                upload_data = response.json()
                upload_url = upload_data.get('url')
                
                if not upload_url:
                    logger.warning(f"⚠️ Попытка {attempt + 1}: Не получен URL")
                    time.sleep(2 ** attempt)
                    continue
                
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
                            continue
                else:
                    img_data = image_data
                
                if isinstance(img_data, list):
                    image_bytes = bytes(img_data)
                elif isinstance(img_data, (bytes, bytearray)):
                    image_bytes = bytes(img_data)
                else:
                    logger.error(f"❌ Неподдерживаемый тип данных: {type(img_data)}")
                    continue
                
                files = {'data': ('image.jpg', image_bytes, 'image/jpeg')}
                
                upload_response = requests.post(
                    upload_url,
                    files=files,
                    timeout=60,
                    verify=False
                )
                
                if upload_response.status_code != 200:
                    logger.warning(f"⚠️ Попытка {attempt + 1}: Ошибка загрузки: {upload_response.status_code}")
                    time.sleep(2 ** attempt)
                    continue
                
                upload_result = upload_response.json()
                
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
                    time.sleep(0.5)
                    return token
                else:
                    logger.warning(f"⚠️ Попытка {attempt + 1}: Не получен токен")
                    time.sleep(2 ** attempt)
                    
            except Exception as e:
                logger.error(f"❌ Попытка {attempt + 1}: {e}")
                time.sleep(2 ** attempt)
        
        return None
    
    def _send_to_chat(self, chat_id: str, text: str, image_tokens: List[str]) -> bool:
        try:
            if not self.api.token or self.is_stopped():
                return False
            
            attachments = []
            # МАКСИМУМ 10 ФОТО (согласно API)
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
            
            logger.info(f"📤 Отправка в чат {chat_id_with_dash} с {len(attachments)} фото")
            
            response = requests.post(
                f"{self.api.base_url}/messages?chat_id={chat_id_with_dash}",
                headers={
                    "Authorization": self.api.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение отправлено в чат {chat_id_with_dash}")
                return True
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def _parse_metadata(self, metadata_text: str) -> Dict:
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
    
    def publish_single_folder(self, folder_name: str, ad_text: str, 
                              metadata_text: str, images_data: List) -> Tuple[bool, str]:
        try:
            with self.lock:
                self.current_folder = folder_name
                self.total_folders += 1
            
            if self.is_stopped():
                return False, "Остановка пользователем"
            
            start_time = time.time()
            
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                logger.error(f"❌ Не удалось извлечь chat_id из: {folder_name}")
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            logger.info(f"📤 Извлечен chat_id: {chat_id}")
            
            # МАКСИМУМ 10 ФОТО
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            
            logger.info(f"📸 Найдено {len(images_data)} изображений, загружаем максимум {max_images}")
            
            image_tokens = []
            for i in range(max_images):
                if self.is_stopped():
                    return False, "Остановка пользователем"
                
                if time.time() - start_time > self.FOLDER_TIMEOUT:
                    return False, f"Таймаут обработки папки {folder_name}"
                
                logger.info(f"📤 Загрузка изображения {i+1}/{max_images}")
                
                img_data = images_data[i]
                if not img_data:
                    continue
                
                token = self._upload_file_to_max(img_data)
                if token:
                    image_tokens.append(token)
                    logger.info(f"✅ Изображение {i+1} загружено")
                else:
                    logger.warning(f"⚠️ Не удалось загрузить изображение {i+1}")
            
            logger.info(f"📦 Загружено {len(image_tokens)} из {max_images} изображений")
            
            success = self._send_to_chat(chat_id, ad_text, image_tokens)
            
            if not success:
                return False, "Не удалось отправить сообщение"
            
            metadata = self._parse_metadata(metadata_text)
            self.db.save_ad_metadata(self.user_id, folder_name, f"-{chat_id}", metadata, time.time())
            self.db.add_publication(self.user_id, folder_name, f"-{chat_id}")
            
            with self.lock:
                self.processed_folders += 1
            
            return True, f"✅ Папка {folder_name} опубликована с {len(image_tokens)} фото"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            with self.lock:
                self.failed_folders += 1
            return False, str(e)


class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.user_publishers: Dict[int, PublisherInstance] = {}
        self.user_locks: Dict[int, threading.Lock] = {}
        self._lock = threading.Lock()
        logger.info("✅ Publisher инициализирован")
    
    def _get_lock(self, user_id: int) -> threading.Lock:
        with self._lock:
            if user_id not in self.user_locks:
                self.user_locks[user_id] = threading.Lock()
            return self.user_locks[user_id]
    
    def _get_publisher(self, user_id: int) -> PublisherInstance:
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
                logger.info(f"⏹️ Публикатор для пользователя {user_id} остановлен и удален")
                return True
            return False
    
    def get_status(self, user_id: int) -> Optional[Dict]:
        with self._get_lock(user_id):
            if user_id not in self.user_publishers:
                return {'running': False}
            return self.user_publishers[user_id].get_status()
    
    def is_running(self, user_id: int) -> bool:
        with self._get_lock(user_id):
            if user_id not in self.user_publishers:
                return False
            return self.user_publishers[user_id].running
