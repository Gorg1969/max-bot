import re
import json
from typing import Dict, List, Optional

class GoogleDriveStorage:
    """Работа с Google Drive (заглушка)"""
    
    def __init__(self, user_id: int, credentials=None):
        self.user_id = user_id
        self.credentials = credentials
    
    def get_folder_id_from_url(self, url: str) -> Optional[str]:
        """Извлечение folder_id из ссылки"""
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
    
    def list_subfolders(self, folder_id: str) -> List[Dict]:
        """Получение списка подпапок (заглушка)"""
        return [
            {"id": "sub1", "name": "Самосвалы 8 -76576474415864"},
            {"id": "sub2", "name": "Экскаваторы -987654321"}
        ]
    
    def list_files_in_folder(self, folder_id: str) -> List[Dict]:
        """Получение списка файлов (заглушка)"""
        return [
            {"id": "file1", "name": "info.txt"},
            {"id": "file2", "name": "image1.jpg"},
            {"id": "file3", "name": "image2.png"}
        ]
    
    def download_text_file(self, file_id: str) -> Optional[str]:
        """Скачивание текстового файла (заглушка)"""
        return "**Тестовое объявление**\n\nЭто тестовое сообщение."
    
    def download_image(self, file_id: str, file_name: str) -> Optional[bytes]:
        """Скачивание изображения (заглушка)"""
        return b"fake_image_data"
    
    def get_or_create_swap_folder(self, root_folder_id: str) -> str:
        """Получение папки для swap (заглушка)"""
        return "swap_folder_id"
    
    def read_swap_file(self, swap_folder_id: str, user_id: int) -> Optional[Dict]:
        """Чтение файла подкачки (заглушка)"""
        return None
    
    def write_swap_file(self, swap_folder_id: str, user_id: int, data: Dict):
        """Запись файла подкачки (заглушка)"""
        pass
    
    def delete_swap_file(self, swap_folder_id: str, user_id: int):
        """Удаление файла подкачки (заглушка)"""
        pass
