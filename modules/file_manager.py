import os
import shutil
import zipfile
import re
import logging

logger = logging.getLogger(__name__)

class FileManager:
    def __init__(self, data_dir="/app/data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
    
    def get_user_folder(self, user_id):
        """Возвращает ПРЯМОЙ путь к папке пользователя"""
        user_folder = os.path.join(self.data_dir, f"user_{user_id}")
        os.makedirs(user_folder, exist_ok=True)
        return user_folder
    
    def get_ads_folder(self, user_id):
        """Возвращает ФИКСИРОВАННЫЙ путь к папке с объявлениями"""
        user_folder = self.get_user_folder(user_id)
        ads_folder = os.path.join(user_folder, "ads")
        os.makedirs(ads_folder, exist_ok=True)
        return ads_folder
    
    def save_uploaded_files_stream(self, files, user_id, append=False):
        """
        ПОТОКОВОЕ сохранение файлов - ВСЕГДА в папку ads/
        """
        try:
            # ФИКСИРОВАННЫЙ ПУТЬ - всегда в ads/
            ads_folder = self.get_ads_folder(user_id)
            
            if not append:
                if os.path.exists(ads_folder):
                    shutil.rmtree(ads_folder)
                os.makedirs(ads_folder, exist_ok=True)
            else:
                os.makedirs(ads_folder, exist_ok=True)
            
            saved_count = 0
            for file in files:
                if not file.filename:
                    continue
                if file.filename.startswith('.'):
                    continue
                
                # Сохраняем файлы прямо в ads/, сохраняя структуру подпапок
                # Если файл был в подпапке - сохраняем структуру
                rel_path = file.filename
                full_path = os.path.join(ads_folder, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, 'wb') as f:
                    while True:
                        chunk = file.stream.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                saved_count += 1
            
            logger.info(f"✅ Сохранено {saved_count} файлов в /ads/")
            return {'success': True, 'saved_count': saved_count}
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_subfolders(self, user_id):
        """Возвращает список подпапок с info.txt из ФИКСИРОВАННОЙ папки ads/"""
        ads_folder = self.get_ads_folder(user_id)
        subfolders = []
        
        if not os.path.exists(ads_folder):
            logger.warning(f"⚠️ Папка ads не существует для пользователя {user_id}")
            return subfolders
        
        # Рекурсивно обходим папку ads/
        for root, dirs, files in os.walk(ads_folder):
            if 'info.txt' in files:
                # Берем имя папки относительно ads/
                rel_path = os.path.relpath(root, ads_folder)
                if rel_path == '.':
                    # Если info.txt в самой папке ads
                    folder_name = os.path.basename(root)
                else:
                    folder_name = rel_path
                subfolders.append(folder_name)
                logger.info(f"📁 Найдена папка с info.txt: {folder_name}")
        
        logger.info(f"📁 Всего найдено {len(subfolders)} папок с info.txt")
        return subfolders
    
    def get_folder_path(self, user_id, folder_name):
        """Возвращает путь к конкретной папке в ads/"""
        ads_folder = self.get_ads_folder(user_id)
        return os.path.join(ads_folder, folder_name)
    
    def clear_user_data(self, user_id):
        """Очищает данные пользователя"""
        user_folder = self.get_user_folder(user_id)
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
            os.makedirs(user_folder, exist_ok=True)
            logger.info(f"🗑️ Данные пользователя {user_id} очищены")
    
    def get_folders(self, user_id):
        """Возвращает список папок с info.txt из ads/"""
        ads_folder = self.get_ads_folder(user_id)
        folders = []
        if os.path.exists(ads_folder):
            for item in os.listdir(ads_folder):
                item_path = os.path.join(ads_folder, item)
                if os.path.isdir(item_path):
                    info_path = os.path.join(item_path, 'info.txt')
                    if os.path.exists(info_path):
                        folders.append(item)
        return folders
    
    def extract_chat_id_from_name(self, folder_name):
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
