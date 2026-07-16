# modules/publisher.py - исправленная версия
import logging
import os
import time
import re
import requests
import threading
import shutil
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple  # <-- ДОБАВЛЕН ИМПОРТ

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
        self.FOLDER_TIMEOUT = 120
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
            
            logger.info(f"📦 [ПУБЛИКАЦИЯ] Начало обработки папки: {folder_name}")
            logger.info(f"📝 [ПУБЛИКАЦИЯ] Текст: {len(ad_text)} символов")
            logger.info(f"🖼️ [ПУБЛИКАЦИЯ] Количество изображений: {len(images_data)}")
            
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                logger.error(f"❌ [ПУБЛИКАЦИЯ] Не удалось извлечь chat_id из: {folder_name}")
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            logger.info(f"✅ [ПУБЛИКАЦИЯ] Извлечен chat_id: {chat_id}")
            
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            logger.info(f"📸 [ПУБЛИКАЦИЯ] Загружаем максимум {max_images} изображений")
            
            image_tokens = []
            for i in range(max_images):
                if self.is_stopped():
                    return False, "Остановка пользователем"
                
                img_data = images_data[i]
                if not img_data:
                    logger.warning(f"⚠️ [ПУБЛИКАЦИЯ] Изображение {i+1} пустое, пропускаем")
                    continue
                
                logger.info(f"📤 [ПУБЛИКАЦИЯ] Загрузка изображения {i+1}/{max_images}")
                token = self.api.upload_file(img_data)
                if token:
                    image_tokens.append(token)
                    logger.info(f"✅ [ПУБЛИКАЦИЯ] Изображение {i+1} загружено, токен: {token[:20]}...")
                else:
                    logger.warning(f"⚠️ [ПУБЛИКАЦИЯ] Не удалось загрузить изображение {i+1}")
            
            logger.info(f"📦 [ПУБЛИКАЦИЯ] Загружено {len(image_tokens)} из {max_images} изображений")
            
            logger.info(f"📤 [ПУБЛИКАЦИЯ] Отправка в чат {chat_id} с {len(image_tokens)} фото")
            success = self.api.send_to_chat(chat_id, ad_text, image_tokens)
            
            if not success:
                logger.error(f"❌ [ПУБЛИКАЦИЯ] Не удалось отправить сообщение в чат {chat_id}")
                return False, "Не удалось отправить сообщение"
            
            logger.info(f"✅ [ПУБЛИКАЦИЯ] Сообщение отправлено в чат {chat_id}")
            
            metadata = self._parse_metadata(metadata_text)
            self.db.save_ad_metadata(self.user_id, folder_name, f"-{chat_id}", metadata, time.time())
            self.db.add_publication(self.user_id, folder_name, f"-{chat_id}")
            
            with self.lock:
                self.processed_folders += 1
            
            return True, f"✅ Папка {folder_name} опубликована с {len(image_tokens)} фото"
            
        except Exception as e:
            logger.error(f"❌ [ПУБЛИКАЦИЯ] Ошибка публикации {folder_name}: {e}")
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


class Publisher:
    """Менеджер публикаций"""
    
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
                logger.info(f"⏹️ Публикатор для пользователя {user_id} остановлен")
                return True
            return False
