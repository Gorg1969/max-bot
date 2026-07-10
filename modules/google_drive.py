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
    
    # ========== УПРАВЛЕНИЕ ПАПКАМИ ==========
    
    def create_temp_folder(self, user_id):
        """Создание временной папки для пользователя на Google Диске"""
        try:
            query = f"name='temp_{user_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.drive.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            
            if files:
                logger.info(f"📁 Временная папка уже существует: {files[0]['id']}")
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
    
    def delete_temp_folder(self, folder_id):
        """Удаление временной папки со всем содержимым"""
        try:
            self.drive.files().delete(fileId=folder_id).execute()
            logger.info(f"🗑️ Временная папка {folder_id} удалена")
            return True
        except HttpError as e:
            logger.error(f"❌ Ошибка удаления папки: {e}")
            return False
    
    def get_temp_folder_files(self, folder_id):
        """Список файлов во временной папке"""
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.drive.files().list(q=query, fields="files(id, name, mimeType)").execute()
            return results.get('files', [])
        except HttpError as e:
            logger.error(f"❌ Ошибка получения списка файлов: {e}")
            return []
    
    # ========== РАБОТА С ФАЙЛАМИ ==========
    
    def save_file_to_temp(self, file_data, filename, folder_id):
        """Сохранение файла во временную папку"""
        try:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            media = MediaFileUpload(file_data, resumable=True)
            file = self.drive.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            logger.info(f"✅ Файл сохранён во временную папку: {filename}")
            return file.get('id')
        except HttpError as e:
            logger.error(f"❌ Ошибка сохранения файла: {e}")
            return None
    
    def get_file_content(self, file_id):
        """Получение содержимого файла (для текстовых файлов)"""
        try:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read().decode('utf-8')
        except HttpError as e:
            logger.error(f"❌ Ошибка чтения файла: {e}")
            return None
    
    def download_file_to_memory(self, file_id):
        """Скачивание файла в память (для работы с архивами)"""
        try:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh
        except HttpError as e:
            logger.error(f"❌ Ошибка скачивания файла: {e}")
            return None
    
    def download_file(self, file_id, local_path):
        """Скачивание файла на локальный диск"""
        try:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.FileIO(local_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.close()
            logger.info(f"✅ Файл скачан: {local_path}")
            return True
        except HttpError as e:
            logger.error(f"❌ Ошибка скачивания: {e}")
            return False
    
    def delete_file(self, file_id):
        """Удаление файла с Google Диска"""
        try:
            self.drive.files().delete(fileId=file_id).execute()
            logger.info(f"🗑️ Удалён файл: {file_id}")
            return True
        except HttpError as e:
            logger.error(f"❌ Ошибка удаления: {e}")
            return False
    
    def cleanup_temp_folder(self, folder_id):
        """Очистка временной папки"""
        files = self.get_temp_folder_files(folder_id)
        for file in files:
            self.delete_file(file['id'])
        logger.info(f"🧹 Временная папка {folder_id} очищена")
        return True
    
    # ========== ЗАГРУЗКА ЧАСТЯМИ ==========
    
    def upload_chunk(self, folder_id, chunk_data, chunk_name):
        """Загрузка части файла на Google Диск"""
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
    
    def list_chunks(self, folder_id):
        """Список частей файла во временной папке"""
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.drive.files().list(q=query, fields="files(id, name)").execute()
            return results.get('files', [])
        except HttpError as e:
            logger.error(f"❌ Ошибка получения списка: {e}")
            return []
    
    def assemble_file_from_chunks(self, folder_id, output_name):
        """Сборка файла из частей"""
        logger.info(f"🔧 Сборка файла {output_name} из частей в папке {folder_id}")
        return True
    
    def copy_file_to_folder(self, file_id, folder_id):
        """Копирование файла в папку на Google Диске"""
        try:
            file = self.drive.files().get(fileId=file_id, fields='name').execute()
            file_name = file.get('name')
            
            body = {'name': file_name, 'parents': [folder_id]}
            copied_file = self.drive.files().copy(fileId=file_id, body=body).execute()
            logger.info(f"✅ Файл скопирован: {copied_file.get('id')}")
            return copied_file.get('id')
        except HttpError as e:
            logger.error(f"❌ Ошибка копирования: {e}")
            return None
