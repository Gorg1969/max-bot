import logging
import os
import time
import re
import requests
import base64
from PIL import Image
import io

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_users = {}
    
    def extract_chat_id(self, folder_name):
        """Извлекает ID чата из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def compress_image(self, image_path, max_size_mb=0.5, quality=75):
        """Сжимает изображение до указанного размера"""
        try:
            with Image.open(image_path) as img:
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                # Уменьшаем размер
                max_dimension = 1280
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=quality, optimize=True)
                compressed_data = output.getvalue()
                
                return compressed_data
        except Exception as e:
            logger.error(f"❌ Ошибка сжатия: {e}")
            with open(image_path, 'rb') as f:
                return f.read()
    
    def upload_photo_to_max(self, photo_path):
        """Загружает одно фото в MAX"""
        try:
            compressed_data = self.compress_image(photo_path, max_size_mb=0.5, quality=75)
            photo_base64 = base64.b64encode(compressed_data).decode('utf-8')
            
            attachment = {
                "type": "image",
                "payload": {
                    "content": photo_base64,
                    "mime_type": "image/jpeg",
                    "filename": os.path.basename(photo_path).rsplit('.', 1)[0] + '.jpg'
                }
            }
            return attachment
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки фото: {e}")
            return None
    
    def send_photo_separately(self, chat_id, photo_path, caption=None):
        """Отправляет одно фото отдельным сообщением"""
        try:
            attachment = self.upload_photo_to_max(photo_path)
            if not attachment:
                return False
            
            # Отправляем фото с подписью (если есть)
            if caption:
                success = self.api.send_message_to_chat_with_attachments(chat_id, caption, [attachment])
            else:
                success = self.api.send_message_to_chat_with_attachments(chat_id, "📸", [attachment])
            
            if success:
                logger.info(f"✅ Отправлено фото: {os.path.basename(photo_path)}")
            else:
                logger.error(f"❌ Не удалось отправить фото: {os.path.basename(photo_path)}")
            
            return success
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            return False
    
    def start(self, user_id):
        """Запускает публикацию для пользователя"""
        try:
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            
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
                return False
            
            self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
            self.active_users[user_id] = True
            published = 0
            
            for folder_name in subfolders:
                if not self.active_users.get(user_id, True):
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
                        continue
                    
                    # Собираем изображения (только первые 5)
                    images = []
                    for file in os.listdir(folder_path):
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            images.append(os.path.join(folder_path, file))
                            if len(images) >= 5:
                                break
                    
                    logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}")
                    logger.info(f"📄 Текст: {text[:100]}...")
                    logger.info(f"🖼️ Найдено {len(images)} изображений")
                    
                    # 🔥 НОВЫЙ ПОДХОД: отправляем текст, потом каждое фото отдельно
                    
                    # 1. Отправляем текст
                    success = self.api.send_message_to_chat(chat_id, text)
                    if not success:
                        logger.error(f"❌ Не удалось отправить текст в {chat_id}")
                        continue
                    
                    logger.info(f"✅ Текст отправлен в {chat_id}")
                    time.sleep(1)
                    
                    # 2. Отправляем каждое фото отдельно (с подписью)
                    for i, img_path in enumerate(images):
                        if not self.active_users.get(user_id, True):
                            break
                        
                        # Первое фото отправляем с пометкой "Фото 1", остальные без подписи
                        if i == 0:
                            caption = f"📸 Фото 1/{len(images)}"
                        else:
                            caption = None
                        
                        self.send_photo_separately(chat_id, img_path, caption)
                        time.sleep(1)  # Пауза между фото
                    
                    # Добавляем в базу данных
                    self.db.add_publication(user_id, folder_name, chat_id)
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    
                    # Пауза между объявлениями
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
        if user_id in self.active_users:
            self.active_users[user_id] = False
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
