import os
import io
import json
import re
import time
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError

class GoogleDriveStorage:
    """Работа с Google Drive пользователя"""
    
    def __init__(self, user_id: int, credentials: Credentials):
        self.user_id = user_id
        self.credentials = credentials
        self.drive = build('drive', 'v3', credentials=credentials)
    
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
    
    def get_file_id_by_name(self, folder_id: str, name: str) -> Optional[str]:
        """Поиск файла по имени в папке"""
        try:
            query = f"'{folder_id}' in parents and name='{name}' and trashed=false"
            results = self.drive.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            return files[0]['id'] if files else None
        except HttpError:
            return None
    
    def create_folder(self, parent_id: str, name: str) -> str:
        """Создание папки на Google Drive"""
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        file = self.drive.files().create(body=file_metadata, fields='id').execute()
        return file.get('id')
    
    def get_or_create_swap_folder(self, root_folder_id: str) -> str:
        """Получение или создание папки _max_bot_swap"""
        swap_folder_name = '_max_bot_swap'
        swap_id = self.get_file_id_by_name(root_folder_id, swap_folder_name)
        if not swap_id:
            swap_id = self.create_folder(root_folder_id, swap_folder_name)
        return swap_id
    
    def read_swap_file(self, swap_folder_id: str, user_id: int) -> Optional[Dict]:
        """Чтение файла подкачки пользователя"""
        file_name = f"user_{user_id}.json"
        file_id = self.get_file_id_by_name(swap_folder_id, file_name)
        if not file_id:
            return None
        
        try:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return json.loads(fh.read().decode('utf-8'))
        except Exception as e:
            print(f"⚠️ Ошибка чтения swap файла: {e}")
            return None
    
    def write_swap_file(self, swap_folder_id: str, user_id: int, data: Dict):
        """Запись файла подкачки пользователя"""
        file_name = f"user_{user_id}.json"
        file_id = self.get_file_id_by_name(swap_folder_id, file_name)
        
        content = json.dumps(data, ensure_ascii=False, indent=2)
        
        if file_id:
            # Обновляем существующий файл
            self.drive.files().update(
                fileId=file_id,
                media_body=io.BytesIO(content.encode('utf-8'))
            ).execute()
        else:
            # Создаём новый файл
            file_metadata = {
                'name': file_name,
                'parents': [swap_folder_id]
            }
            self.drive.files().create(
                body=file_metadata,
                media_body=io.BytesIO(content.encode('utf-8'))
            ).execute()
    
    def delete_swap_file(self, swap_folder_id: str, user_id: int):
        """Удаление файла подкачки пользователя"""
        file_name = f"user_{user_id}.json"
        file_id = self.get_file_id_by_name(swap_folder_id, file_name)
        if file_id:
            self.drive.files().delete(fileId=file_id).execute()
    
    def list_subfolders(self, folder_id: str) -> List[Dict]:
        """Получение списка подпапок"""
        try:
            query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.drive.files().list(
                q=query,
                fields="files(id, name)",
                orderBy="name"
            ).execute()
            return results.get('files', [])
        except HttpError:
            return []
    
    def list_files_in_folder(self, folder_id: str) -> List[Dict]:
        """Получение списка файлов в папке"""
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.drive.files().list(
                q=query,
                fields="files(id, name, mimeType)",
                orderBy="name"
            ).execute()
            return results.get('files', [])
        except HttpError:
            return []
    
    def download_text_file(self, file_id: str) -> Optional[str]:
        """Скачивание текстового файла"""
        try:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read().decode('utf-8')
        except Exception as e:
            print(f"⚠️ Ошибка скачивания текста: {e}")
            return None
    
    def download_image(self, file_id: str, file_name: str) -> Optional[bytes]:
        """Скачивание изображения"""
        try:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read()
        except Exception as e:
            print(f"⚠️ Ошибка скачивания изображения: {e}")
            return None
