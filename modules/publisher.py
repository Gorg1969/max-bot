import logging
import os
import time
import re
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
    
    def compress_image_to_bytes(self, image_path, max_size_mb=0.5, quality=60):
        try:
            with Image.open(image_path) as img:
                img = self.fix_image_orientation(img)
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                max_dimension = 800
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
                compressed_data = buffer.getvalue()
                
                if len(compressed_data) > max_size_mb * 1024 * 1024:
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=40, optimize=True)
                    compressed_data = buffer.getvalue()
                
                return compressed_data
                
        except Exception as e:
            logger.error(f"❌ Ошибка сжатия {image_path}: {e}")
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
    
    def parse_info_file(self, info_path):
        """
        Парсит info.txt:
        - До разделителя "#изъятая" - текст для объявления
        - После разделителя - данные для отчета
        """
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            delimiter = "#изъятая"
            
            if delimiter in content:
                parts = content.split(delimiter, 1)
                ad_text = parts[0].strip()
                metadata_part = parts[1].strip() if len(parts) > 1 else ""
            else:
                ad_text = content.strip()
                metadata_part = ""
            
            metadata = {}
            if metadata_part:
                lines = metadata_part.split('\n')
                for line in lines:
                    line = line.strip()
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        # Убираем markdown ссылки
                        if '[' in value and ']' in value and '(' in value and ')' in value:
                            import re
                            url_match = re.search(r'\(([^)]+)\)', value)
                            if url_match:
                                value = url_match.group(1)
                        metadata[key] = value
            
            return {
                'ad_text': ad_text,
                'metadata': metadata
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга info.txt: {e}")
            return {
                'ad_text': content,
                'metadata': {}
            }
    
    def start(self, user_id):
        try:
            if self.user_states.get(user_id) == UserState.PUBLISHING:
                logger.warning(f"⚠️ Публикация уже запущена")
                self.api.send_message(user_id, "⚠️ Публикация уже запущена. Дождитесь завершения.")
                return False
            
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            self.user_states[user_id] = UserState.PUBLISHING
            
            # Получаем папки из ads/
            subfolders = self.fm.get_subfolders(user_id)
            
            if not subfolders:
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                self.user_states[user_id] = UserState.IDLE
                return False
            
            self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
            published = 0
            
            for folder_name in subfolders:
                if self.user_states.get(user_id) == UserState.STOPPED:
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    folder_path = self.fm.get_folder_path(user_id, folder_name)
                    
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    
                    # ===== ПАРСИМ INFO.TXT =====
                    parsed = self.parse_info_file(info_path)
                    ad_text = parsed['ad_text']          # Только для объявления
                    metadata = parsed['metadata']        # Только для отчета
                    
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    # ===== ПОЛУЧАЕМ ИЗОБРАЖЕНИЯ =====
                    images = self.get_sorted_images(folder_path, max_count=10)
                    
                    if self.user_states.get(user_id) == UserState.STOPPED:
                        break
                    
                    # Подготавливаем фото
                    photo_files = []
                    for img_name in images:
                        img_path = os.path.join(folder_path, img_name)
                        if not os.path.exists(img_path):
                            continue
                        try:
                            # Читаем файл как бинарные данные (уже сжатые на клиенте)
                            with open(img_path, 'rb') as f:
                                photo_data = f.read()
                            photo_files.append((img_name, photo_data))
                        except Exception as e:
                            logger.error(f"❌ Ошибка подготовки {img_name}: {e}")
                    
                    # Отправляем
                    if photo_files:
                        success = self.api.send_photos_to_chat(
                            chat_id=chat_id,
                            photo_files=photo_files,
                            text=ad_text
                        )
                    else:
                        success = self.api.send_message_to_chat(chat_id, ad_text)
                    
                    if not success:
                        logger.error(f"❌ Не удалось отправить объявление в {chat_id}")
                        continue
                    
                    # Сохраняем в БД с метаданными для отчета
                    self.db.add_publication(user_id, folder_name, chat_id)
                    self.db.save_ad_metadata(
                        user_id=user_id,
                        folder_name=folder_name,
                        chat_id=chat_id,
                        metadata=metadata,
                        published_at=time.time()
                    )
                    
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка при публикации {folder_name}: {e}")
                    continue
            
            self.user_states[user_id] = UserState.IDLE
            
            if published > 0:
                self.api.send_message(user_id, f"✅ Публикация завершена! Опубликовано {published} объявлений.")
                # Очищаем папку после публикации
                self.fm.clear_ads_folder(user_id)
                logger.info(f"🗑️ Папка ads пользователя {user_id} очищена после публикации")
            else:
                self.api.send_message(user_id, "❌ Не удалось опубликовать ни одного объявления.")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.user_states[user_id] = UserState.IDLE
            self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")
            return False
    
    def stop(self, user_id):
        current_state = self.user_states.get(user_id, UserState.IDLE)
        if current_state == UserState.PUBLISHING:
            self.user_states[user_id] = UserState.STOPPED
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
            self.api.send_message(user_id, "⏹️ Публикация остановлена.")
            return True
        elif current_state == UserState.STOPPED:
            self.api.send_message(user_id, "ℹ️ Публикация уже остановлена.")
            return False
        else:
            self.api.send_message(user_id, "ℹ️ Нет активной публикации для остановки.")
            return False
