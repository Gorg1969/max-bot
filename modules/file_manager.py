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
        """Возвращает путь к папке пользователя"""
        user_folder = os.path.join(self.data_dir, f"user_{user_id}")
        os.makedirs(user_folder, exist_ok=True)
        return user_folder
    
    def get_temp_folder(self, user_id):
        """Возвращает путь к временной папке для загрузки"""
        temp_folder = os.path.join(self.get_user_folder(user_id), "temp_upload")
        os.makedirs(temp_folder, exist_ok=True)
        return temp_folder
    
    def extract_chat_id_from_name(self, folder_name):
        """Извлекает chat_id из имени папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def save_uploaded_files_stream(self, files, user_id):
        """
        ПОТОКОВОЕ сохранение файлов - НЕ ДЕРЖИТ В ПАМЯТИ!
        Сохраняет файлы чанками по 64KB
        """
        try:
            user_folder = self.get_user_folder(user_id)
            
            # Очищаем папку пользователя
            if os.path.exists(user_folder):
                shutil.rmtree(user_folder)
            os.makedirs(user_folder, exist_ok=True)
            
            saved_count = 0
            for file in files:
                if not file.filename:
                    continue
                
                # Пропускаем системные файлы
                if file.filename.startswith('.'):
                    continue
                
                rel_path = file.filename
                full_path = os.path.join(user_folder, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                # Сохраняем потоково, чанками по 64KB
                with open(full_path, 'wb') as f:
                    while True:
                        chunk = file.stream.read(64 * 1024)  # 64KB
                        if not chunk:
                            break
                        f.write(chunk)
                saved_count += 1
            
            logger.info(f"✅ Сохранено {saved_count} файлов потоково")
            return {'success': True, 'saved_count': saved_count}
            
        except Exception as e:
            logger.error(f"❌ Ошибка потокового сохранения: {e}")
            return {'success': False, 'error': str(e)}
    
    def save_uploaded_files(self, files, user_id):
        """
        Сохраняет загруженные файлы с сохранением структуры папок
        (старый метод, оставлен для совместимости)
        """
        try:
            temp_folder = self.get_temp_folder(user_id)
            
           
