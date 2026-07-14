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
        
        # Останавливаем цикл публикации если он был запущен
        self.stop_publishing_loop()
        
        # Останавливаем всех пользователей
        for user_id in list(self.user_states.keys()):
            if self.user_states[user_id] == UserState.PUBLISHING:
                self.user_states[user_id] = UserState.STOPPED
                if self.api:
                    try:
                        self.api.send_message(user_id, "⏹️ Публикация остановлена глобальной командой.")
                    except:
                        pass
        
        return True
    
    def reset_global_stop(self):
        """Сброс глобального флага остановки"""
        self.global_stop = False
        self._save_global_stop_state()
        logger.info("🔄 Глобальный флаг остановки сброшен")
        return True
    
    # ===== МЕТОДЫ ДЛЯ АВТОПУБЛИКАЦИИ (ОСТАВЛЕНЫ, НО НЕ ИСПОЛЬЗУЮТСЯ) =====
    
    def start_publishing_loop(self, user_id, check_interval=60):
        """Запускает непрерывный цикл публикации - НЕ ИСПОЛЬЗОВАТЬ!"""
        logger.warning("⚠️ start_publishing_loop вызван, но автопубликация ОТКЛЮЧЕНА!")
        return False
    
    def stop_publishing_loop(self):
        """Останавливает цикл публикации"""
        if not self.running:
            return False
        self.stop_requested = True
        self.running = False
        return True
    
    def _publishing_loop(self, user_id, check_interval):
        """Основной цикл публикации - НЕ ИСПОЛЬЗОВАТЬ!"""
        logger.warning("⚠️ _publishing_loop вызван, но автопубликация ОТКЛЮЧЕНА!")
        return
    
    def _check_new_ads(self, user_id):
        """Проверяет новые объявления - НЕ ИСПОЛЬЗОВАТЬ!"""
        return []
    
    def _publish_ad(self, user_id, folder_name):
        """Публикует одно объявление - НЕ ИСПОЛЬЗОВАТЬ!"""
        return False
    
    # ===== ОСНОВНЫЕ МЕТОДЫ =====
    
    def start(self, user_id):
        """ОДНОКРАТНАЯ публикация всех объявлений"""
        try:
            if self.global_stop:
                logger.warning(f"⚠️ Глобальная остановка активна!")
                if self.api:
                    try:
                        self.api.send_message(user_id, "⚠️ Публикация запрещена глобальной остановкой. Выполните /reset_global")
                    except:
                        pass
                return False
            
            if self.user_states.get(user_id) == UserState.PUBLISHING:
                logger.warning(f"⚠️ Публикация уже запущена для пользователя {user_id}")
                if self.api:
                    try:
                        self.api.send_message(user_id, "⚠️ Публикация уже запущена. Дождитесь завершения.")
                    except:
                        pass
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
                if self.api:
                    try:
                        self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                    except:
                        pass
                self.user_states[user_id] = UserState.IDLE
                return False
            
            if self.api:
                try:
                    self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
                except:
                    pass
            
            published = 0
            
            for folder_name in subfolders:
                if self.global_stop:
                    logger.info(f"⏹️ ГЛОБАЛЬНАЯ ОСТАНОВКА! Публикация прервана для {user_id}")
                    if self.api:
                        try:
                            self.api.send_message(user_id, "⏹️ Публикация прервана глобальной остановкой.")
                        except:
                            pass
                    self.user_states[user_id] = UserState.STOPPED
                    break
                
                if self.user_states.get(user_id) == UserState.STOPPED:
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    folder_path = os.path.join(samosvaly_path, folder_name)
                    ad_hash = self._get_ad_hash(folder_path)
                    if ad_hash in self.published_hashes:
                        logger.info(f"ℹ️ Объявление {folder_name} уже было опубликовано, пропускаем")
                        continue
                    
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    images = self.get_sorted_images(folder_path, max_count=10)
                    logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}, фото: {len(images)}")
                    
                    if self.global_stop:
                        logger.info(f"⏹️ ГЛОБАЛЬНАЯ ОСТАНОВКА! Публикация прервана для {user_id}")
                        if self.api:
                            try:
                                self.api.send_message(user_id, "⏹️ Публикация прервана глобальной остановкой.")
                            except:
                                pass
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
                    
                    if self.api:
                        try:
                            if photo_files:
                                success = self.api.send_photos_to_chat(
                                    chat_id=chat_id,
                                    photo_files=photo_files,
                                    text=text
                                )
                            else:
                                success = self.api.send_message_to_chat(chat_id, text)
                        except Exception as e:
                            logger.error(f"❌ Ошибка отправки: {e}")
                            success = False
                    else:
                        success = False
                    
                    if not success:
                        logger.error(f"❌ Не удалось отправить объявление в {chat_id}")
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
                if self.api:
                    try:
                        self.api.send_message(user_id, f"✅ Публикация завершена! Опубликовано {published} объявлений.")
                    except:
                        pass
            else:
                if self.api:
                    try:
                        self.api.send_message(user_id, "❌ Не удалось опубликовать ни одного объявления.")
                    except:
                        pass
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.user_states[user_id] = UserState.IDLE
            if self.api:
                try:
                    self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")
                except:
                    pass
            return False
    
    def stop(self, user_id):
        """Останавливает публикацию для конкретного пользователя"""
        current_state = self.user_states.get(user_id, UserState.IDLE)
        
        if current_state == UserState.PUBLISHING:
            self.user_states[user_id] = UserState.STOPPED
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
            if self.api:
                try:
                    self.api.send_message(user_id, "⏹️ Публикация остановлена.")
                except:
                    pass
            return True
        elif current_state == UserState.STOPPED:
            logger.info(f"ℹ️ Публикация уже остановлена для пользователя {user_id}")
            if self.api:
                try:
                    self.api.send_message(user_id, "ℹ️ Публикация уже остановлена.")
                except:
                    pass
            return False
        else:
            logger.info(f"ℹ️ Публикация не активна для пользователя {user_id}")
            if self.api:
                try:
                    self.api.send_message(user_id, "ℹ️ Нет активной публикации для остановки.")
                except:
                    pass
            return False
