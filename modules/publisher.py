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

logger = logging.getLogger(__name__)

class UserState(Enum):
    IDLE = "idle"
    PUBLISHING = "publishing"
    STOPPED = "stopped"

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.user_states = {}  # user_id -> UserState
        
        # Флаги для реальной остановки
        self.running = False
        self.stop_requested = False
        self.publish_thread = None
        
        # Защита от дубликатов
        self.published_hashes = set()
        self.hash_file = "published_hashes.json"
        self._load_published_hashes()
        
        # Состояние глобального стопа
        self.global_stop_file = "global_stop.json"
        self._load_global_stop_state()
    
    def _load_published_hashes(self):
        """Загружает хэши опубликованных объявлений"""
        try:
            if os.path.exists(self.hash_file):
                with open(self.hash_file, 'r') as f:
                    data = json.load(f)
                    self.published_hashes = set(data.get('hashes', []))
                logger.info(f"🔓 Загружено {len(self.published_hashes)} хэшей опубликованных объявлений")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки хэшей: {e}")
            self.published_hashes = set()
    
    def _save_published_hashes(self):
        """Сохраняет хэши опубликованных объявлений"""
        try:
            with open(self.hash_file, 'w') as f:
                json.dump({'hashes': list(self.published_hashes)}, f)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения хэшей: {e}")
    
    def _load_global_stop_state(self):
        """Загружает состояние глобального стопа"""
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
        """Сохраняет состояние глобального стопа"""
        try:
            with open(self.global_stop_file, 'w') as f:
                json.dump({'global_stop': self.global_stop}, f)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения состояния: {e}")
    
    def _get_ad_hash(self, folder_path):
        """Создает уникальный хэш объявления"""
        hasher = hashlib.md5()
        try:
            # Хэшируем содержимое info.txt
            info_path = os.path.join(folder_path, 'info.txt')
            if os.path.exists(info_path):
                with open(info_path, 'rb') as f:
                    hasher.update(f.read())
            
            # Хэшируем имена файлов изображений
            files = sorted(os.listdir(folder_path))
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    hasher.update(f.encode())
                    # Добавляем размер файла для надежности
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
        """Исправляет ориентацию изображения на основе EXIF-данных"""
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
        """Сжимает изображение с исправлением ориентации и очисткой EXIF"""
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
        """Возвращает отсортированный список изображений (до 10)"""
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
        """Глобальная остановка всех публикаций"""
        self.global_stop = True
        self._save_global_stop_state()
        logger.info("🛑 ГЛОБАЛЬНАЯ ОСТАНОВКА ВСЕХ ПУБЛИКАЦИЙ")
        
        # Останавливаем цикл публикации
        self.stop_publishing_loop()
        
        # Останавливаем всех пользователей
        for user_id in list(self.user_states.keys()):
            if self.user_states[user_id] == UserState.PUBLISHING:
                self.user_states[user_id] = UserState.STOPPED
                self.api.send_message(user_id, "⏹️ Публикация остановлена глобальной командой.")
        
        return True
    
    def reset_global_stop(self):
        """Сброс глобального флага остановки"""
        self.global_stop = False
        self._save_global_stop_state()
        logger.info("🔄 Глобальный флаг остановки сброшен")
        return True
    
    def start_publishing_loop(self, user_id, check_interval=60):
        """Запускает непрерывный цикл публикации новых объявлений"""
        if self.running:
            logger.warning("⚠️ Цикл публикации уже запущен")
            return False
        
        if self.global_stop:
            logger.warning(f"⚠️ Глобальная остановка активна! Публикация для {user_id} невозможна")
            self.api.send_message(user_id, "⚠️ Публикация запрещена глобальной остановкой. Выполните /reset_global")
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
        self.api.send_message(user_id, f"🔄 Запущен автоматический поиск новых объявлений (проверка каждые {check_interval} сек)")
        return True
    
    def stop_publishing_loop(self):
        """Останавливает цикл публикации"""
        if not self.running:
            logger.info("ℹ️ Цикл публикации не запущен")
            return False
        
        logger.info("⏹️ Остановка цикла публикации...")
        self.stop_requested = True
        self.running = False
        
        if self.publish_thread and self.publish_thread.is_alive():
            self.publish_thread.join(timeout=5)
        
        logger.info("✅ Цикл публикации остановлен")
        return True
    
    def _publishing_loop(self, user_id, check_interval):
        """Основной цикл публикации"""
        logger.info(f"🔄 Запущен цикл проверки для {user_id}")
        
        while not self.stop_requested and self.running:
            try:
                # Проверяем глобальный стоп
                if self.global_stop:
                    logger.info(f"⏹️ Глобальная остановка! Цикл прерван для {user_id}")
                    self.api.send_message(user_id, "⏹️ Цикл публикации прерван глобальной остановкой.")
                    break
                
                # Проверяем новые объявления
                new_ads = self._check_new_ads(user_id)
                
                if new_ads:
                    logger.info(f"📢 Найдено {len(new_ads)} новых объявлений для {user_id}")
                    self.api.send_message(user_id, f"📢 Найдено {len(new_ads)} новых объявлений. Начинаю публикацию...")
                    
                    for ad in new_ads:
                        if self.stop_requested or not self.running or self.global_stop:
                            break
                        self._publish_ad(user_id, ad)
                        time.sleep(2)  # Задержка между отправками
                
                # Ждем следующую проверку
                for _ in range(check_interval):
                    if self.stop_requested or not self.running or self.global_stop:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле публикации: {e}")
                time.sleep(10)  # Пауза при ошибке
        
        self.running = False
        self.api.send_message(user_id, "⏹️ Цикл публикации завершен")
        logger.info(f"⏹️ Цикл публикации для {user_id} завершен")
    
    def _check_new_ads(self, user_id):
        """Проверяет новые объявления для публи
