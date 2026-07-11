import re
import requests
import os
import logging

logger = logging.getLogger(__name__)

def extract_file_id_from_url(url):
    """Извлечение ID файла из любой ссылки Google Drive"""
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'open\?id=([a-zA-Z0-9_-]+)',
        r'([a-zA-Z0-9_-]{28,})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_file_from_drive(url, save_path):
    """Скачивание файла с Google Drive по ссылке (с автоконвертацией)"""
    try:
        file_id = extract_file_id_from_url(url)
        if not file_id:
            logger.error(f"❌ Не удалось извлечь ID из ссылки: {url}")
            return False
        
        # Прямая ссылка
        direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        logger.info(f"📥 Скачивание: {direct_url}")
        
        response = requests.get(direct_url, stream=True, timeout=300, verify=False)
        
        if response.status_code != 200:
            logger.error(f"❌ Ошибка скачивания: {response.status_code}")
            return False
        
        # Проверяем, что это ZIP (PK = сигнатура ZIP)
        content_start = response.content[:2]
        if content_start != b'PK':
            # Пробуем с confirm=1
            logger.info("🔄 Пробую с confirm=1...")
            direct_url = f"https://drive.google.com/uc?export=download&confirm=1&id={file_id}"
            response = requests.get(direct_url, stream=True, timeout=300, verify=False)
            
            if response.status_code != 200 or response.content[:2] != b'PK':
                logger.error("❌ Ссылка ведёт не на ZIP-архив")
                return False
        
        # Сохраняем
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
        
        logger.info(f"✅ Файл скачан: {save_path} ({os.path.getsize(save_path)} байт)")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return False
