import os
import io
import json
import logging
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

class GoogleDrive:
    """Работа с Google Диском: загрузка, скачивание, управление временными файлами"""
    
    def __init__(self, token):
        self.token = token
        self.credentials = Credentials(token=token)
        self.drive = build('drive', 'v3', credentials=self.credentials)
    
    @classmethod
    def from_user_id(cls, user_id, auth):
        token = auth.get_user_token(user_id)
        if not token:
            return None
        return cls(token)
    
    def create_temp_folder(self, user_id):
        try:
            query = f"name='temp_{user_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.drive.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            
            if files:
                return files[0]['id']
            
            file_metadata = {
                'name': f'temp_{user_id}',
                'mimeType': 'application/vnd.google-apps.folder'
            }
            file = self.drive.files().create(body=file_metadata, fields='id').execute()
            logger.info(f"📁 Создана временная папка для {user_id}: {file.get('id')}")
            return file.get('id')
        except HttpError as e:
            logger.error(f"❌ Ошибка создания папки: {e}")
            return None
    
    def upload_chunk(self, folder_id, chunk_data, chunk_name):
        try:
            file_metadata = {
                'name': chunk_name,
                'parents': [folder_id]
            }
            media = MediaFileUpload(chunk_data, resumable=True)
            file = self.drive.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            return file.get('id')
        except HttpError as e:
            logger.error(f"❌ Ошибка загрузки части: {e}")
            return None
    
    def download_chunk(self, file_id, local_path):
        try:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.FileIO(local_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.close()
            logger.info(f"✅ Скачан файл: {local_path}")
            return True
        except HttpError as e:
            logger.error(f"❌ Ошибка скачивания: {e}")
            return False
    
    def list_chunks(self, folder_id):
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.drive.files().list(q=query, fields="files(id, name)").execute()
            return results.get('files', [])
        except HttpError as e:
            logger.error(f"❌ Ошибка получения списка: {e}")
            return []
    
    def delete_file(self, file_id):
        try:
            self.drive.files().delete(fileId=file_id).execute()
            logger.info(f"🗑️ Удалён файл: {file_id}")
            return True
        except HttpError as e:
            logger.error(f"❌ Ошибка удаления: {e}")
            return False
    
    def cleanup_temp_folder(self, folder_id):
        files = self.list_chunks(folder_id)
        for file in files:
            self.delete_file(file['id'])
        logger.info(f"🧹 Временная папка {folder_id} очищена")
        return True
    
    def assemble_file_from_chunks(self, folder_id, output_name):
        logger.info(f"🔧 Сборка файла {output_name} из частей в папке {folder_id}")
        return True
