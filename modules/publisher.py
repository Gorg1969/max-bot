import time
import random
import os
import logging

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api_client, file_manager, database):
        self.api = api_client
        self.fm = file_manager
        self.db = database
        self.is_running = {}
    
    def publish_folder(self, folder_path, group_id, post_number=None, total_posts=None):
        try:
            info_file = None
            images = []
            
            for f in os.listdir(folder_path):
                file_path = os.path.join(folder_path, f)
                if os.path.isfile(file_path):
                    if f.lower() in ['info.txt', 'info.md']:
                        info_file = file_path
                    elif f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                        images.append(file_path)
            
            if not info_file:
                return False, "Нет info.txt"
            
            with open(info_file, 'r', encoding='utf-8') as f:
                info_text = f.read()
            
            if info_text:
                if post_number and total_posts:
                    header = f"📝 **Пост {post_number}/{total_posts}**\n\n"
                    self.api.send_message(group_id, header + info_text)
                else:
                    self.api.send_message(group_id, info_text)
            
            images = images[:10]
            for image_path in images:
                filename = os.path.basename(image_path)
                self.api.send_message(group_id, f"📷 {filename}")
            
            return True, "Успешно"
        except Exception as e:
            return False, str(e)
    
    def start(self, user_id):
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
                shutil.rmtree(folder['path'])
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
