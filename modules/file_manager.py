import os
import shutil
import zipfile
import logging

logger = logging.getLogger(__name__)

class FileManager:
    def __init__(self, data_dir="/app/data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
    
    def get_user_folder(self, user_id):
        user_folder = os.path.join(self.data_dir, f"user_{user_id}")
        os.makedirs(user_folder, exist_ok=True)
        return user_folder
    
    def get_temp_folder(self, user_id):
        temp_folder = os.path.join(self.get_user_folder(user_id), "temp_upload")
        os.makedirs(temp_folder, exist_ok=True)
        return temp_folder
    
    def save_uploaded_files(self, files, user_id):
        try:
            temp_folder = self.get_temp_folder(user_id)
            
            if os.path.exists(temp_folder):
                shutil.rmtree(temp_folder)
            os.makedirs(temp_folder)
            
            saved_count = 0
            for file in files:
                rel_path = getattr(file, 'filename', file.name)
                if not rel_path:
                    rel_path = file.name
                
                full_path = os.path.join(temp_folder, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                file.save(full_path)
                saved_count += 1
            
            logger.info(f"✅ Сохранено {saved_count} файлов во временную папку")
            
            folders = []
            for item in os.listdir(temp_folder):
                item_path = os.path.join(temp_folder, item)
                if os.path.isdir(item_path):
                    info_path = os.path.join(item_path, 'info.txt')
                    if os.path.exists(info_path):
                        folders.append(item)
                        logger.info(f"📁 Найдена папка объявления: {item}")
                    else:
                        logger.warning(f"⚠️ В папке {item} нет info.txt")
            
            if not folders:
                return {
                    'success': False,
                    'folders': [],
                    'message': 'Не найдено папок с info.txt'
                }
            
            user_folder = self.get_user_folder(user_id)
            moved_folders = []
            for folder in folders:
                src = os.path.join(temp_folder, folder)
                dst = os.path.join(user_folder, folder)
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.move(src, dst)
                moved_folders.append(folder)
                logger.info(f"📦 Перенесена папка {folder}")
            
            shutil.rmtree(temp_folder)
            
            return {
                'success': True,
                'folders': moved_folders,
                'message': f'✅ Загружено {len(moved_folders)} объявлений'
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения файлов: {e}")
            return {
                'success': False,
                'folders': [],
                'message': f'Ошибка: {str(e)}'
            }
    
    def extract_zip(self, user_id, zip_path):
        try:
            user_folder = self.get_user_folder(user_id)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(user_folder)
            logger.info(f"✅ ZIP распакован для пользователя {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка распаковки ZIP: {e}")
            return False
    
    def clear_user_data(self, user_id):
        user_folder = self.get_user_folder(user_id)
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
            os.makedirs(user_folder, exist_ok=True)
            logger.info(f"🗑️ Данные пользователя {user_id} очищены")
    
    def get_folders(self, user_id):
        user_folder = self.get_user_folder(user_id)
        folders = []
        if os.path.exists(user_folder):
            for item in os.listdir(user_folder):
                item_path = os.path.join(user_folder, item)
                if os.path.isdir(item_path):
                    info_path = os.path.join(item_path, 'info.txt')
                    if os.path.exists(info_path):
                        folders.append(item)
        return folders
    
    def get_folder_path(self, user_id, folder_name):
        return os.path.join(self.get_user_folder(user_id), folder_name)
    
    def get_subfolders(self, user_id):
        user_folder = self.get_user_folder(user_id)
        subfolders = []
        
        if not os.path.exists(user_folder):
            logger.warning(f"⚠️ Папка пользователя {user_id} не существует")
            return subfolders
        
        for root, dirs, files in os.walk(user_folder):
            if 'info.txt' in files:
                folder_name = os.path.basename(root)
                subfolders.append(folder_name)
                logger.info(f"📁 Найдена подпапка с info.txt: {folder_name}")
        
        logger.info(f"📁 Всего найдено {len(subfolders)} подпапок для пользователя {user_id}")
        return subfolders
