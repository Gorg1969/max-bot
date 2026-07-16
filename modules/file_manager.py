import os
import shutil
import re
import logging

logger = logging.getLogger(__name__)

class FileManager:
    def __init__(self, data_dir="/app/data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
    
    def get_user_folder(self, user_id):
        """Возвращает путь к папке пользователя"""
        user_folder = os.path.join(self.data_dir, f"user_{user_id}")
        os.makedirs(user_folder, exist_ok=True)
        return user_folder
    
    def get_ads_folder(self, user_id):
        """Возвращает путь к папке с объявлениями"""
        user_folder = self.get_user_folder(user_id)
        ads_folder = os.path.join(user_folder, "ads")
        os.makedirs(ads_folder, exist_ok=True)
        return ads_folder
    
    def extract_chat_id_from_name(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def cleanup_old_files(self, max_age_hours=24):
        """Очищает старые файлы"""
        try:
            import time
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            deleted_count = 0
            
            for user_dir in os.listdir(self.data_dir):
                user_path = os.path.join(self.data_dir, user_dir)
                if not os.path.isdir(user_path):
                    continue
                
                dir_mtime = os.path.getmtime(user_path)
                if current_time - dir_mtime > max_age_seconds:
                    shutil.rmtree(user_path)
                    deleted_count += 1
                    logger.info(f"🗑️ Удалена старая папка: {user_dir}")
            
            if deleted_count > 0:
                logger.info(f"🧹 Очищено {deleted_count} старых папок")
            
        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых файлов: {e}")
