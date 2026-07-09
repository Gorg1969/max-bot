import os
import zipfile
import shutil
import re
import logging

logger = logging.getLogger(__name__)

class FileManager:
    def __init__(self, data_dir='/app/data'):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
    
    def get_user_folder(self, user_id):
        folder = os.path.join(self.data_dir, str(user_id))
        os.makedirs(folder, exist_ok=True)
        return folder
    
    def clear_user_data(self, user_id):
        folder = self.get_user_folder(user_id)
        shutil.rmtree(folder, ignore_errors=True)
    
    def extract_zip(self, user_id, zip_path):
        """Распаковка ZIP с правильной кодировкой для русских названий"""
        user_folder = self.get_user_folder(user_id)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
                    # Пробуем разные кодировки для русского языка
                    filename = None
                    for encoding in ['utf-8', 'cp866', 'cp1251', 'koi8-r', 'cp437']:
                        try:
                            filename = file_info.filename.encode('cp437').decode(encoding)
                            break
                        except:
                            continue
                    
                    # Если не удалось декодировать — оставляем как есть
                    if filename is None:
                        filename = file_info.filename
                    
                    # Извлекаем файл
                    if filename.endswith('/'):
                        os.makedirs(os.path.join(user_folder, filename), exist_ok=True)
                    else:
                        target_path = os.path.join(user_folder, filename)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with open(target_path, 'wb') as f:
                            f.write(zip_ref.read(file_info))
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка распаковки: {e}")
            return False
    
    def get_subfolders(self, user_id):
        user_folder = self.get_user_folder(user_id)
        if not os.path.exists(user_folder):
            return []
        
        items = os.listdir(user_folder)
        subfolders = []
        for item in items:
            item_path = os.path.join(user_folder, item)
            if os.path.isdir(item_path):
                group_id = self.extract_group_id(item)
                if group_id:
                    subfolders.append({'name': item, 'group_id': group_id, 'path': item_path})
        return subfolders
    
    def extract_group_id(self, folder_name):
        """Извлечение ID группы из названия папки (с минусом!)"""
        # Приводим к правильной кодировке, если нужно
        try:
            folder_name = folder_name.encode('latin1').decode('utf-8')
        except:
            pass
        
        match = re.search(r'-(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def extract_folder_id_from_url(self, url):
        patterns = [
            r'folders/([a-zA-Z0-9_-]+)',
            r'id=([a-zA-Z0-9_-]+)',
            r'([a-zA-Z0-9_-]{28,})'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
