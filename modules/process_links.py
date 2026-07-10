import re
import os
import logging
import requests
from .google_drive import GoogleDrive

logger = logging.getLogger(__name__)

def extract_file_id_from_url(url):
    """Извлечение ID файла из ссылки Google Drive"""
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'([a-zA-Z0-9_-]{28,})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_file_from_drive(file_id, save_path):
    """Скачивание файла с Google Drive"""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(url, stream=True, timeout=300, verify=False)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    return False

def process_google_drive_link(user_id, url, api, fm, publisher, user_auth):
    """Обработка ссылки на файл с Google Drive"""
    api.send_message(user_id, "📥 Получил ссылку. Начинаю обработку...")
    
    # Проверяем авторизацию
    token = user_auth.get_user_token(user_id)
    if not token:
        api.send_message(user_id, "❌ Пользователь не авторизован. Подключите Google Диск через /auth")
        return
    
    # Извлекаем ID файла
    file_id = extract_file_id_from_url(url)
    if not file_id:
        api.send_message(user_id, "❌ Не удалось извлечь ID файла из ссылки.")
        return
    
    # Сохраняем файл на сервер (временное решение)
    user_folder = fm.get_user_folder(user_id)
    zip_path = os.path.join(user_folder, 'temp.zip')
    
    api.send_message(user_id, "⏳ Скачивание файла... (до 5 минут)")
    if download_file_from_drive(file_id, zip_path):
        size = os.path.getsize(zip_path)
        api.send_message(user_id, f"✅ Файл скачан: {size // 1024 // 1024} МБ")
        
        api.send_message(user_id, "📦 Распаковка архива...")
        if fm.extract_zip(user_id, zip_path):
            os.remove(zip_path)
            api.send_message(user_id, "✅ Архив распакован. Начинаю публикацию...")
            publisher.start(user_id)
        else:
            api.send_message(user_id, "❌ Ошибка распаковки архива.")
            fm.clear_user_data(user_id)
    else:
        api.send_message(user_id, "❌ Не удалось скачать файл. Проверьте ссылку.")
