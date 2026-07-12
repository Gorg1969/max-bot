import logging
import os
import time
import re

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
    
    def get_sorted_images(self, folder_path, max_count=5):
        """
        Возвращает отсортированный список изображений в папке
        Сортировка по имени файла (чтобы порядок был предсказуемым)
        """
        images = []
        if not os.path.exists(folder_path):
            logger.error(f"❌ Папка не найдена: {folder_path}")
            return images
            
        for file in os.listdir(folder_path):
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                # Пропускаем системные файлы
                if file.startswith('.'):
                    continue
                images.append(file)
        
        # Сортируем по имени
        images.sort()
        return images[:max_count]
    
    def start(self, user_id):
        """Запускает публикацию для пользователя"""
        try:
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            
            # Получаем папку пользователя через FileManager (ЕДИНЫЙ ИСТОЧНИК)
            user_folder = self.fm.get_user_folder(user_id)
            logger.info(f"📁 Папка пользователя: {user_folder}")
            
            # Проверяем, есть ли папка "Самосвалы" внутри
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            
            # Определяем папки с объявлениями
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
                logger.warning(f"⚠️ Папка 'Самосвалы' не найдена, ищем в {user_folder}")
                subfolders = []
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
                            logger.info(f"✅ Папка {item} - валидна (есть info.txt)")
            
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
                    # Путь к папке с объявлением (ЕДИНЫЙ ИСТОЧНИК)
                    if os.path.exists(samosvaly_path):
                        folder_path = os.path.join(samosvaly_path, folder_name)
                    else:
                        folder_path = os.path.join(user_folder, folder_name)
                    
                    logger.info(f"📁 Путь к папке: {folder_path}")
                    
                    # Читаем текст
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        logger.warning(f"⚠️ Нет info.txt в папке {folder_name}")
                        continue
                    
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    # Извлекаем ID чата
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    # Получаем список изображений (отсортированный)
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
                    
                    # 2. Отправляем каждое фото отдельно через send_photo_to_chat
                    for i, img_name in enumerate(images):
                        if not self.active_users.get(user_id, True):
                            break
                        
                        img_path = os.path.join(folder_path, img_name)
                        
                        # Проверяем, что файл существует
                        if not os.path.exists(img_path):
                            logger.warning(f"⚠️ Файл не найден: {img_path}")
                            continue
                        
                        # Проверяем размер файла
                        file_size = os.path.getsize(img_path) / (1024 * 1024)
                        if file_size > 10:
                            logger.warning(f"⚠️ Файл {img_name} слишком большой ({file_size:.1f} МБ), пропускаем")
                            continue
                        
                        caption = f"📸 Фото {i+1}/{len(images)}" if i == 0 else None
                        
                        # 🔥 ИСПОЛЬЗУЕМ НОВЫЙ МЕТОД send_photo_to_chat
                        success = self.api.send_photo_to_chat(chat_id, img_path, caption)
                        
                        if success:
                            logger.info(f"✅ Отправлено фото: {img_name}")
                        else:
                            logger.error(f"❌ Не удалось отправить фото: {img_name}")
                        
                        time.sleep(1)
                    
                    # Сохраняем в базу
                    self.db.add_publication(user_id, folder_name, chat_id)
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации папки {folder_name}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
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
        else:
            logger.info(f"ℹ️ Публикация для пользователя {user_id} не была активна")
