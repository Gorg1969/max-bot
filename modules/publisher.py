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
    
    def extract_group_id(self, folder_name):
        """Извлекает group_id из названия папки"""
        match = re.search(r'-(\d+)', folder_name)
        if match:
            return match.group(1)
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
                # Ищем подпапки внутри "Самосвалы"
                subfolders = []
                for item in os.listdir(samosvaly_path):
                    item_path = os.path.join(samosvaly_path, item)
                    if os.path.isdir(item_path):
                        # Проверяем наличие info.txt
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
                            logger.info(f"✅ Папка {item} - валидна (есть info.txt)")
                        else:
                            logger.warning(f"⚠️ В папке {item} нет info.txt")
            else:
                # Если нет папки "Самосвалы", ищем прямо в user_folder
                logger.warning(f"⚠️ Папка 'Самосвалы' не найдена, ищем в {user_folder}")
                subfolders = []
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
            
            if not subfolders:
                logger.warning(f"⚠️ Нет подпапок с info.txt для пользователя {user_id}")
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                return False
            
            logger.info(f"📁 Найдено {len(subfolders)} подпапок: {subfolders}")
            
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
                    # Путь к папке с объявлением (внутри Самосвалы)
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
                    
                    # Извлекаем group_id из названия папки
                    group_id = self.extract_group_id(folder_name)
                    if not group_id:
                        logger.warning(f"⚠️ Не удалось извлечь group_id из {folder_name}")
                        continue
                    
                    logger.info(f"📤 Публикация в группу {group_id}: {folder_name}")
                    logger.info(f"📄 Текст: {text[:100]}...")
                    
                    # Отправляем сообщение в чат
                    self.api.send_message_to_chat(group_id, text)
                    
                    # Добавляем в базу данных
                    self.db.add_publication(user_id, folder_name, group_id)
                    
                    published += 1
                    time.sleep(1)  # Пауза между публикациями
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации папки {folder_name}: {e}")
                    continue
            
            self.active_users[user_id] = False
            
            if published > 0:
                self.api.send_message(user_id, f"✅ Публикация завершена! Опубликовано {published} объявлений.")
            else:
                self.api.send_message(user_id, "❌ Не удалось опубликовать ни одного объявления. Проверьте содержимое папок.")
            
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
