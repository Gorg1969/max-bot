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
    
    def compress_image(self, image_path, max_size_mb=1.0, quality=85):
        """
        Сжимает изображение до указанного размера
        """
        try:
            # Открываем изображение
            with Image.open(image_path) as img:
                # Конвертируем в RGB если нужно (для JPEG)
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                # Определяем максимальный размер
                max_dimension = 1920
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    logger.info(f"📐 Изменён размер: {img.width}x{img.height}")
                
                # Сжимаем до указанного размера
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=quality, optimize=True)
                compressed_data = output.getvalue()
                
                # Проверяем размер
                size_mb = len(compressed_data) / (1024 * 1024)
                logger.info(f"📦 Размер после сжатия: {size_mb:.2f} МБ")
                
                return compressed_data
                
        except Exception as e:
            logger.error(f"❌ Ошибка сжатия изображения {image_path}: {e}")
            # Если сжатие не удалось, читаем оригинал
            with open(image_path, 'rb') as f:
                return f.read()
    
    def upload_photo_to_max(self, photo_path):
        """
        Загружает фото в MAX с сжатием
        """
        try:
            # Сжимаем изображение
            compressed_data = self.compress_image(photo_path, max_size_mb=0.8, quality=80)
            
            # Кодируем в base64
            photo_base64 = base64.b64encode(compressed_data).decode('utf-8')
            
            # Формируем attachment для MAX API
            attachment = {
                "type": "image",
                "payload": {
                    "content": photo_base64,
                    "mime_type": "image/jpeg",  # Всегда JPEG после сжатия
                    "filename": os.path.basename(photo_path).rsplit('.', 1)[0] + '.jpg'
                }
            }
            
            logger.info(f"✅ Фото готово: {os.path.basename(photo_path)} ({len(compressed_data) / 1024:.0f} КБ)")
            return attachment
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки фото {photo_path}: {e}")
            return None
    
    def start(self, user_id):
        """Запускает публикацию для пользователя"""
        try:
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            
            # Получаем папку пользователя
            user_folder = self.fm.get_user_folder(user_id)
            logger.info(f"📁 Папка пользователя: {user_folder}")
            
            # Проверяем, есть ли папка "Самосвалы" внутри
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            
            if os.path.exists(samosvaly_path) and os.path.isdir(samosvaly_path):
                logger.info(f"📁 Найдена папка: {samosvaly_path}")
                subfolders = []
                for item in os.listdir(samosvaly_path):
                    item_path = os.path.join(samosvaly_path, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
                            logger.info(f"✅ Папка {item} - валидна (есть info.txt)")
                        else:
                            logger.warning(f"⚠️ В папке {item} нет info.txt")
            else:
                logger.warning(f"⚠️ Папка 'Самосвалы' не найдена")
                subfolders = []
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
            
            if not subfolders:
                logger.warning(f"⚠️ Нет подпапок с info.txt")
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                return False
            
            logger.info(f"📁 Найдено {len(subfolders)} подпапок")
            
            self.api.send_message(
                user_id,
                f"📢 Начинаю публикацию {len(subfolders)} объявлений..."
            )
            
            self.active_users[user_id] = True
            published = 0
            
            for folder_name in subfolders:
                if not self.active_users.get(user_id, True):
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    # Путь к папке с объявлением
                    if os.path.exists(samosvaly_path):
                        folder_path = os.path.join(samosvaly_path, folder_name)
                    else:
                        folder_path = os.path.join(user_folder, folder_name)
                    
                    info_path = os.path.join(folder_path, 'info.txt')
                    
                    if not os.path.exists(info_path):
                        logger.warning(f"⚠️ Нет info.txt в папке {folder_name}")
                        continue
                    
                    # Читаем info.txt
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    # Извлекаем ID чата из названия папки (с дефисом)
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
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
                    
                    # Загружаем фото в MAX (с сжатием)
                    attachments = []
                    for img_path in images:
                        attachment = self.upload_photo_to_max(img_path)
                        if attachment:
                            attachments.append(attachment)
                            logger.info(f"✅ Загружено фото: {os.path.basename(img_path)}")
                        else:
                            logger.warning(f"⚠️ Не удалось загрузить фото: {os.path.basename(img_path)}")
                    
                    # Отправляем сообщение с фото
                    if attachments:
                        success = self.api.send_message_to_chat_with_attachments(chat_id, text, attachments)
                    else:
                        logger.warning(f"⚠️ Нет фото для публикации, отправляю только текст")
                        success = self.api.send_message_to_chat(chat_id, text)
                    
                    if success:
                        self.db.add_publication(user_id, folder_name, chat_id)
                        published += 1
                        logger.info(f"✅ Опубликовано: {folder_name}")
                    else:
                        logger.error(f"❌ Не удалось опубликовать: {folder_name}")
                    
                    # Пауза между публикациями (2 секунды, чтобы не перегружать API)
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации папки {folder_name}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
            
            self.active_users[user_id] = False
            
            if published > 0:
                self.api.send_message(
                    user_id, 
                    f"✅ Публикация завершена! Опубликовано {published} объявлений."
                )
            else:
                self.api.send_message(
                    user_id, 
                    "❌ Не удалось опубликовать ни одного объявления. Проверьте содержимое папок."
                )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")
            return False
    
    def stop(self, user_id):
        """Останавливает публикацию"""
        if user_id in self.active_users:
            self.active_users[user_id] = False
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
        else:
            logger.info(f"ℹ️ Публикация для пользователя {user_id} не была активна")
