import logging
import os
import time
import re
import base64
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
    
    def get_sorted_images(self, folder_path, max_count=3):
        """Возвращает отсортированный список изображений"""
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
    
    def start(self, user_id):
        """Запускает публикацию для пользователя"""
        try:
            # Проверяем, не запущена ли уже публикация
            if self.user_states.get(user_id) == UserState.PUBLISHING:
                logger.warning(f"⚠️ Публикация уже запущена для пользователя {user_id}")
                self.api.send_message(user_id, "⚠️ Публикация уже запущена. Дождитесь завершения.")
                return False
            
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            
            # Устанавливаем состояние PUBLISHING
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
                subfolders = []
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
            
            if not subfolders:
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                self.user_states[user_id] = UserState.IDLE
                return False
            
            self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
            published = 0
            
            for folder_name in subfolders:
                # Проверяем состояние
                if self.user_states.get(user_id) == UserState.STOPPED:
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    if os.path.exists(samosvaly_path):
                        folder_path = os.path.join(samosvaly_path, folder_name)
                    else:
                        folder_path = os.path.join(user_folder, folder_name)
                    
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    images = self.get_sorted_images(folder_path, max_count=3)
                    
                    logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}")
                    logger.info(f"🖼️ Найдено {len(images)} изображений")
                    
                    # Проверяем состояние перед отправкой
                    if self.user_states.get(user_id) == UserState.STOPPED:
                        logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                        break
                    
                                    try:
                    # Определяем путь к папке
                    if os.path.exists(samosvaly_path):
                        folder_path = os.path.join(samosvaly_path, folder_name)
                    else:
                        folder_path = os.path.join(user_folder, folder_name)
                    
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    images = self.get_sorted_images(folder_path, max_count=3)
                    logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}, фото: {len(images)}")
                    
                    # Проверяем состояние
                    if self.user_states.get(user_id) == UserState.STOPPED:
                        break
                    
                    # Подготавливаем фото
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
                    
                    # Отправляем ОДНО сообщение с текстом и фото
                    if photo_files:
                        success = self.api.send_photos_to_chat(
                            chat_id=chat_id,
                            photo_files=photo_files,
                            text=text        # ← текст объявления передаётся здесь
                        )
                    else:
                        # Если фото нет, шлём хотя бы текст
                        success = self.api.send_message_to_chat(chat_id, text)
                    
                    if not success:
                        logger.error(f"❌ Не удалось отправить объявление в {chat_id}")
                        continue
                    
                    # Запись в БД и задержка
                    self.db.add_publication(user_id, folder_name, chat_id)
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    time.sleep(2)   # задержка между постами (регулируйте)
            
            # Завершаем публикацию
            self.user_states[user_id] = UserState.IDLE
            
            if published > 0:
                self.api.send_message(user_id, f"✅ Публикация завершена! Опубликовано {published} объявлений.")
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
        """Останавливает публикацию"""
        current_state = self.user_states.get(user_id, UserState.IDLE)
        
        if current_state == UserState.PUBLISHING:
            self.user_states[user_id] = UserState.STOPPED
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
            self.api.send_message(user_id, "⏹️ Публикация остановлена.")
            return True
        elif current_state == UserState.STOPPED:
            logger.info(f"ℹ️ Публикация уже остановлена для пользователя {user_id}")
            self.api.send_message(user_id, "ℹ️ Публикация уже остановлена.")
            return False
        else:
            logger.info(f"ℹ️ Публикация не активна для пользователя {user_id}")
            self.api.send_message(user_id, "ℹ️ Нет активной публикации для остановки.")
            return False
