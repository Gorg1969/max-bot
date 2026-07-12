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
        """
        Извлекает group_id из названия папки
        Пример: "Квартиры -123456789" -> "123456789"
        """
        # Ищем число после дефиса
        match = re.search(r'-(\d+)', folder_name)
        if match:
            return match.group(1)
        return None
    
    def start(self, user_id):
        """Запускает публикацию для пользователя"""
        try:
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            
            # Получаем список подпапок
            subfolders = self.fm.get_subfolders(user_id)
            
            if not subfolders:
                logger.warning(f"⚠️ Нет подпапок для пользователя {user_id}")
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                return False
            
            logger.info(f"📁 Найдено {len(subfolders)} подпапок: {subfolders}")
            
            # Отправляем сообщение о начале
            self.api.send_message(
                user_id,
                f"📢 Начинаю публикацию {len(subfolders)} объявлений..."
            )
            
            # Отмечаем, что публикация активна
            self.active_users[user_id] = True
            
            # Проходим по всем папкам
            for folder_name in subfolders:
                # Проверяем, не остановлена ли публикация
                if not self.active_users.get(user_id, True):
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    # Извлекаем group_id из названия папки
                    group_id = self.extract_group_id(folder_name)
                    
                    if not group_id:
                        logger.warning(f"⚠️ Не удалось извлечь group_id из {folder_name}")
                        continue
                    
                    # Получаем путь к папке
                    folder_path = self.fm.get_folder_path(user_id, folder_name)
                    
                    # Читаем info.txt
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        logger.warning(f"⚠️ Нет info.txt в папке {folder_name}")
                        continue
                    
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    # Собираем изображения
                    images = []
                    for file in os.listdir(folder_path):
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            images.append(os.path.join(folder_path, file))
                    
                    logger.info(f"📤 Публикация в группу {group_id}: {folder_name}")
                    
                    # Отправляем сообщение в чат
                    if images:
                        # Отправляем с изображениями
                        attachments = []
                        for img_path in images[:5]:  # MAX может иметь ограничение по кол-ву фото
                            try:
                                with open(img_path, 'rb') as f:
                                    # Здесь логика отправки фото через MAX API
                                    pass
                            except Exception as e:
                                logger.error(f"❌ Ошибка загрузки фото {img_path}: {e}")
                        
                        self.api.send_message_to_chat(group_id, text)
                    else:
                        self.api.send_message_to_chat(group_id, text)
                    
                    # Добавляем в базу данных
                    self.db.add_publication(user_id, folder_name, group_id)
                    
                    # Небольшая пауза между публикациями
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации папки {folder_name}: {e}")
                    continue
            
            self.active_users[user_id] = False
            logger.info(f"✅ Публикация завершена для пользователя {user_id}")
            self.api.send_message(user_id, "✅ Публикация завершена!")
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
