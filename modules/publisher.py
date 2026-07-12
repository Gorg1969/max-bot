import logging
import os
import time
import re
import requests
import base64

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_users = {}
    
    def extract_chat_id(self, folder_name):
        """
        Извлекает ID чата из названия папки
        Пример: "Название -123456789" -> "-123456789"
        """
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def upload_photo_to_max(self, photo_path):
        """
        Загружает фото в MAX и возвращает attachment объект
        """
        try:
            # Читаем файл
            with open(photo_path, 'rb') as f:
                photo_data = f.read()
            
            # Кодируем в base64
            photo_base64 = base64.b64encode(photo_data).decode('utf-8')
            
            # Определяем тип файла
            ext = os.path.splitext(photo_path)[1].lower()
            mime_type = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }.get(ext, 'image/jpeg')
            
            # Формируем attachment для MAX API
            attachment = {
                "type": "image",
                "payload": {
                    "content": photo_base64,
                    "mime_type": mime_type,
                    "filename": os.path.basename(photo_path)
                }
            }
            
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
                    
                    # Собираем изображения
                    images = []
                    for file in os.listdir(folder_path):
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            images.append(os.path.join(folder_path, file))
                    
                    logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}")
                    logger.info(f"📄 Текст: {text[:100]}...")
                    logger.info(f"🖼️ Найдено {len(images)} изображений")
                    
                    # Загружаем фото в MAX и создаём attachments
                    attachments = []
                    for img_path in images[:5]:  # MAX может иметь ограничение по кол-ву фото
                        attachment = self.upload_photo_to_max(img_path)
                        if attachment:
                            attachments.append(attachment)
                            logger.info(f"✅ Загружено фото: {os.path.basename(img_path)}")
                    
                    # Отправляем сообщение с фото
                    if attachments:
                        success = self.api.send_message_to_chat_with_attachments(chat_id, text, attachments)
                    else:
                        logger.warning(f"⚠️ Нет фото для публикации, отправляю только текст")
                        success = self.api.send_message_to_chat(chat_id, text)
                    
                    if success:
                        # Добавляем в базу данных
                        self.db.add_publication(user_id, folder_name, chat_id)
                        published += 1
                        logger.info(f"✅ Опубликовано: {folder_name}")
                    else:
                        logger.error(f"❌ Не удалось опубликовать: {folder_name}")
                    
                    time.sleep(1)  # Пауза между публикациями
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации папки {folder_name}: {e}")
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
