import logging
import os
import time
import re
from PIL import Image
import io

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_users = {}
        self.stop_flags = {}  # Флаги остановки для каждого пользователя
    
    def extract_chat_id(self, folder_name):
        """Извлекает ID чата из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def compress_image(self, image_path, max_size_mb=0.8, quality=75):
        """
        Сжимает изображение до указанного размера
        """
        try:
            with Image.open(image_path) as img:
                # Конвертируем в RGB
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                # Уменьшаем размер
                max_dimension = 1280
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                # Сжимаем
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True)
                compressed_data = buffer.getvalue()
                
                # Если всё ещё слишком большой, снижаем качество
                if len(compressed_data) > max_size_mb * 1024 * 1024:
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=50, optimize=True)
                    compressed_data = buffer.getvalue()
                
                return compressed_data
        except Exception as e:
            logger.error(f"❌ Ошибка сжатия: {e}")
            with open(image_path, 'rb') as f:
                return f.read()
    
    def get_sorted_images(self, folder_path, max_count=5):
        """Возвращает отсортированный список изображений"""
        images = []
        if not os.path.exists(folder_path):
            return images
            
        for file in os.listdir(folder_path):
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                if file.startswith('.'):
                    continue
                images.append(file)
        
        images.sort()
        return images[:max_count]
    
    def start(self, user_id):
        """Запускает публикацию для пользователя"""
        try:
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            
            # Сбрасываем флаг остановки
            self.stop_flags[user_id] = False
            
            # Получаем папку пользователя
            user_folder = self.fm.get_user_folder(user_id)
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            
            # Определяем папки с объявлениями
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
                return False
            
            self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
            self.active_users[user_id] = True
            published = 0
            
            for folder_name in subfolders:
                # 🔥 ПРОВЕРКА ОСТАНОВКИ
                if self.stop_flags.get(user_id, False):
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    # Путь к папке с объявлением
                    if os.path.exists(samosvaly_path):
                        folder_path = os.path.join(samosvaly_path, folder_name)
                    else:
                        folder_path = os.path.join(user_folder, folder_name)
                    
                    # Читаем текст
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    # Извлекаем ID чата
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    # Получаем список изображений
                    images = self.get_sorted_images(folder_path, max_count=5)
                    
                    logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}")
                    logger.info(f"📄 Текст: {text[:100]}...")
                    logger.info(f"🖼️ Найдено {len(images)} изображений")
                    
                    # 1. Отправляем текст
                    success = self.api.send_message_to_chat(chat_id, text)
                    if not success:
                        logger.error(f"❌ Не удалось отправить текст в {chat_id}")
                        continue
                    
                    logger.info(f"✅ Текст отправлен в {chat_id}")
                    time.sleep(1)
                    
                    # 2. Отправляем каждое фото
                    for i, img_name in enumerate(images):
                        # 🔥 ПРОВЕРКА ОСТАНОВКИ
                        if self.stop_flags.get(user_id, False):
                            logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                            break
                        
                        img_path = os.path.join(folder_path, img_name)
                        
                        if not os.path.exists(img_path):
                            logger.warning(f"⚠️ Файл не найден: {img_path}")
                            continue
                        
                        # Сжимаем фото
                        try:
                            compressed_data = self.compress_image(img_path)
                            caption = f"📸 Фото {i+1}/{len(images)}" if i == 0 else None
                            
                            success = self.api.send_photo_to_chat(
                                chat_id, 
                                img_path, 
                                caption, 
                                compressed_data=compressed_data
                            )
                            
                            if success:
                                logger.info(f"✅ Отправлено фото: {img_name}")
                            else:
                                logger.error(f"❌ Не удалось отправить фото: {img_name}")
                            
                            time.sleep(1)
                        except Exception as e:
                            logger.error(f"❌ Ошибка отправки фото {img_name}: {e}")
                    
                    # 3. Сохраняем в базу (только если публикация успешна)
                    # 🔥 НЕ ПРОВЕРЯЕМ СУЩЕСТВУЮЩИЕ ОБЪЯВЛЕНИЯ - просто добавляем
                    self.db.add_publication(user_id, folder_name, chat_id)
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации папки {folder_name}: {e}")
                    continue
            
            self.active_users[user_id] = False
            
            if published > 0:
                self.api.send_message(user_id, f"✅ Публикация завершена! Опубликовано {published} объявлений.")
            else:
                self.api.send_message(user_id, "❌ Не удалось опубликовать ни одного объявления.")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")
            return False
    
    def stop(self, user_id):
        """Останавливает публикацию"""
        self.stop_flags[user_id] = True
        self.active_users[user_id] = False
        logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
