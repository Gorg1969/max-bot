import re
import requests
import logging

logger = logging.getLogger(__name__)

def extract_file_id_from_url(url):
    """Извлечение ID файла из любой ссылки Google Drive"""
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',           # /file/d/ID
        r'id=([a-zA-Z0-9_-]+)',                 # ?id=ID
        r'open\?id=([a-zA-Z0-9_-]+)',           # open?id=ID
        r'([a-zA-Z0-9_-]{28,})'                 # просто ID (если ничего не нашлось)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def convert_to_direct_link(url):
    """Конвертация любой ссылки Google Drive в прямую ссылку для скачивания"""
    file_id = extract_file_id_from_url(url)
    if not file_id:
        return None
    return f"https://drive.google.com/uc?export=download&id={file_id}"

def download_file_from_drive(url, save_path):
    """Скачивание файла с Google Drive по ссылке (с автоконвертацией)"""
    try:
        # Конвертируем ссылку
        direct_url = convert_to_direct_link(url)
        if not direct_url:
            logger.error(f"❌ Не удалось извлечь ID из ссылки: {url}")
            return False
        
        logger.info(f"📥 Скачивание: {direct_url}")
        
        # Скачиваем
        response = requests.get(direct_url, stream=True, timeout=300, verify=False)
        
        if response.status_code != 200:
            logger.error(f"❌ Ошибка скачивания: {response.status_code}")
            return False
        
        # Проверяем, что это ZIP
        if response.content[:2] != b'PK':
            # Пробуем с confirm=1
            direct_url = f"https://drive.google.com/uc?export=download&confirm=1&id={extract_file_id_from_url(url)}"
            response = requests.get(direct_url, stream=True, timeout=300, verify=False)
            
            if response.status_code != 200 or response.content[:2] != b'PK':
                logger.error("❌ Ссылка ведёт не на ZIP-архив")
                return False
        
        # Сохраняем
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
        
        logger.info(f"✅ Файл скачан: {save_path}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return False

def process_google_drive_link(user_id, url, api, fm, publisher, user_auth):
    """Обработка ссылки на Google Drive (для бота)"""
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
    
    # Сохраняем файл на сервер
    user_folder = fm.get_user_folder(user_id)
    zip_path = os.path.join(user_folder, 'temp.zip')
    
    api.send_message(user_id, "⏳ Скачивание файла... (до 5 минут)")
    if download_file_from_drive(url, zip_path):
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
