import time
import random
import os
import shutil
import logging
import sys
import re

if sys.platform == 'linux':
    sys.stdout.reconfigure(encoding='utf-8')

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api_client, file_manager, database):
        self.api = api_client
        self.fm = file_manager
        self.db = database
        self.is_running = {}
    
    def publish_folder(self, folder_path, group_id, post_number=None, total_posts=None):
        try:
            logger.info(f"📤 Публикация папки: {folder_path} в группу {group_id}")
            
            info_file = None
            images = []
            
            # Сканируем папку
            for f in os.listdir(folder_path):
                file_path = os.path.join(folder_path, f)
                if os.path.isfile(file_path):
                    f_lower = f.lower()
                    if f_lower in ['info.txt', 'info.md']:
                        info_file = file_path
                        logger.info(f"📄 Найден info.txt: {info_file}")
                    elif f_lower.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                        images.append(file_path)
                        logger.info(f"🖼️ Найдено изображение: {f}")
            
            if not info_file:
                logger.warning(f"⚠️ Нет info.txt в папке {folder_path}")
                return False, "Нет info.txt"
            
            # Читаем info.txt
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info_text = f.read()
            except UnicodeDecodeError:
                with open(info_file, 'r', encoding='cp1251') as f:
                    info_text = f.read()
            
            # Получаем прямые ссылки на изображения
            image_urls = []
            for image_path in images[:10]:  # Максимум 10 изображений
                # Загружаем изображение на Google Drive или используем прямой путь
                # Здесь мы используем прямой путь к файлу (он уже на сервере)
                image_urls.append(image_path)
            
            # ========== ОТПРАВЛЯЕМ ВСЁ В ОДНОМ СООБЩЕНИИ ==========
            
            # Формируем текст
            if post_number and total_posts:
                full_text = f"📌 **Пост {post_number}/{total_posts}**\n\n{info_text}"
            else:
                full_text = info_text
            
            # Формируем вложения (изображения)
            attachments = []
            for image_path in image_urls:
                # Используем прямую ссылку на файл
                attachments.append({
                    "type": "image",
                    "payload": {
                        "url": f"https://maxbot.bothost.tech/file/{os.path.basename(image_path)}"
                        # ИЛИ можно использовать токен, если загружать через /uploads
                    }
                })
            
            # Отправляем одно сообщение с текстом и изображениями
            logger.info(f"📤 Отправка сообщения в группу {group_id} с {len(attachments)} изображениями")
            
            result = self.api.send_message_to_chat_with_attachments(
                chat_id=group_id,
                text=full_text,
                attachments=attachments
            )
            
            if not result:
                logger.error(f"❌ Не удалось отправить сообщение в группу {group_id}")
                return False, "Ошибка отправки сообщения"
            else:
                logger.info(f"✅ Сообщение отправлено в группу {group_id}")
            
            return True, "Успешно"
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            return False, str(e)
    
    def start(self, user_id):
        logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
        
        self.is_running[user_id] = True
        user_folder = self.fm.get_user_folder(user_id)
        
        subfolders = self.fm.get_subfolders(user_id)
        if not subfolders:
            self.api.send_message(user_id, "❌ Нет папок с ID групп.")
            self.fm.clear_user_data(user_id)
            return
        
        for folder in subfolders:
            self.db.add_publication(user_id, folder['name'], folder['group_id'])
        
        total = len(subfolders)
        self.api.send_message(user_id, f"✅ Найдено {total} папок. Начинаю публикацию...")
        
        published = 0
        errors = []
        post_number = 0
        
        for folder in subfolders:
            if not self.is_running.get(user_id, True):
                self.api.send_message(user_id, "⏹️ Публикация остановлена.")
                break
            
            post_number += 1
            self.db.update_status(folder['name'], 'processing')
            
            if post_number > 1:
                delay = random.randint(60, 180)
                logger.info(f"⏳ Задержка {delay} сек. перед постом {post_number}")
                time.sleep(delay)
            
            if (post_number - 1) % 10 == 0 and post_number > 1:
                logger.info("⏳ Пауза 5 минут")
                time.sleep(300)
            
            logger.info(f"📤 Публикация папки {post_number}/{total}: {folder['name']}")
            
            success, msg = self.publish_folder(
                folder['path'], 
                folder['group_id'], 
                post_number, 
                total
            )
            
            if success:
                published += 1
                self.db.update_status(folder['name'], 'done')
                logger.info(f"✅ Опубликовано: {folder['name']}")
                try:
                    shutil.rmtree(folder['path'])
                    logger.info(f"🗑️ Папка удалена: {folder['path']}")
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления папки: {e}")
            else:
                errors.append(f"{folder['name']}: {msg}")
                self.db.update_status(folder['name'], 'error', msg)
                logger.error(f"❌ Ошибка: {folder['name']} - {msg}")
        
        result_msg = f"✅ **ПУБЛИКАЦИЯ ЗАВЕРШЕНА!**\n\n📊 Всего папок: {total}\n✅ Опубликовано: {published}\n❌ Ошибок: {len(errors)}"
        if errors:
            result_msg += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                result_msg += f"\n... и ещё {len(errors) - 5} ошибок"
        
        self.api.send_message(user_id, result_msg)
        self.fm.clear_user_data(user_id)
    
    def stop(self, user_id):
        self.is_running[user_id] = False
        logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
