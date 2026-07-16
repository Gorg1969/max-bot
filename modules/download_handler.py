import os
import logging
from flask import send_file, abort, jsonify
import time

logger = logging.getLogger(__name__)

class DownloadHandler:
    def __init__(self, data_dir='/app/data'):
        self.data_dir = data_dir
        # Словарь для хранения времени создания ссылок
        self.download_links = {}  # filepath -> timestamp
    
    def generate_download_link(self, user_id, filename):
        """Генерирует ссылку для скачивания"""
        filepath = os.path.join(self.data_dir, f"user_{user_id}", filename)
        
        if not os.path.exists(filepath):
            return None
        
        # Сохраняем время создания ссылки
        self.download_links[filepath] = time.time()
        
        return f"/download_report/{user_id}/{filename}"
    
    def download_file(self, user_id, filename):
        """Обрабатывает скачивание файла"""
        try:
            # Проверяем путь
            safe_filename = os.path.basename(filename)
            filepath = os.path.join(self.data_dir, f"user_{user_id}", safe_filename)
            
            # Проверяем существование
            if not os.path.exists(filepath):
                logger.warning(f"⚠️ Файл не найден: {filepath}")
                return None, "Файл не найден или уже удален"
            
            # Проверяем, не истекло ли время
            if filepath in self.download_links:
                elapsed = time.time() - self.download_links[filepath]
                if elapsed > 600:  # 10 минут
                    # Удаляем файл если истекло
                    os.remove(filepath)
                    del self.download_links[filepath]
                    return None, "Срок действия ссылки истек (10 минут)"
            
            # Проверяем, что файл действительно в папке пользователя
            user_folder = os.path.join(self.data_dir, f"user_{user_id}")
            if not filepath.startswith(user_folder):
                return None, "Доступ запрещен"
            
            # Возвращаем файл для отправки
            return filepath, None
            
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания: {e}")
            return None, str(e)
    
    def cleanup_expired_files(self):
        """Периодическая очистка старых файлов"""
        try:
            current_time = time.time()
            expired_files = []
            
            for filepath, timestamp in self.download_links.items():
                if current_time - timestamp > 600:  # 10 минут
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        expired_files.append(filepath)
            
            # Удаляем из словаря
            for filepath in expired_files:
                del self.download_links[filepath]
            
            if expired_files:
                logger.info(f"🧹 Удалено {len(expired_files)} файлов с истекшим сроком")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")
