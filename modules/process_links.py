import re
import os
import gdown
from urllib.parse import urlparse, parse_qs

def extract_file_id_from_url(url):
    """
    Извлекает file_id из ссылки Google Drive
    """
    # Пробуем найти ID в пути
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    
    # Пробуем найти ID в параметрах
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if 'id' in params:
        return params['id'][0]
    
    return None

def convert_to_direct_link(url):
    """
    Конвертирует ссылку Google Drive в прямую ссылку для скачивания
    """
    file_id = extract_file_id_from_url(url)
    if not file_id:
        return None, None
    
    direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    return direct_url, file_id

def download_file_from_drive(url, destination_path):
    """
    Скачивает файл с Google Drive используя gdown (самый надёжный способ)
    """
    try:
        # Извлекаем ID файла
        file_id = extract_file_id_from_url(url)
        if not file_id:
            raise ValueError("❌ Не удалось извлечь ID файла из ссылки")
        
        print(f"🔑 ID файла: {file_id}")
        print(f"📥 Начинаем скачивание через gdown...")
        
        # Используем gdown для скачивания
        # gdown автоматически обрабатывает все подтверждения и предупреждения
        gdown.download(
            url=url,  # Можно передать полную ссылку
            output=destination_path,
            quiet=False,  # Показываем прогресс
            fuzzy=True    # Разрешаем скачивание даже если файл большой
        )
        
        # Проверяем, что файл действительно скачан
        if os.path.exists(destination_path):
            size = os.path.getsize(destination_path)
            print(f"✅ Файл успешно скачан через gdown: {size / (1024*1024):.2f} МБ")
            return True
        else:
            raise Exception("Файл не был создан")
            
    except Exception as e:
        print(f"❌ Ошибка скачивания через gdown: {e}")
        return False

# Основная функция для обработки ссылки (сохраняем совместимость)
def process_google_drive_link(link, download_dir="downloads"):
    """
    Основная функция для обработки ссылки Google Drive
    """
    # Создаём папку для загрузок
    os.makedirs(download_dir, exist_ok=True)
    
    # Извлекаем ID файла
    file_id = extract_file_id_from_url(link)
    if not file_id:
        raise ValueError("❌ Не удалось извлечь ID файла из ссылки")
    
    print(f"🔑 ID файла: {file_id}")
    
    # Формируем имя для сохранения
    filename = f"file_{file_id}.zip"
    destination = os.path.join(download_dir, filename)
    
    # Удаляем старый файл, если есть
    if os.path.exists(destination):
        os.remove(destination)
    
    # Скачиваем файл через gdown
    success = download_file_from_drive(link, destination)
    
    if success:
        return destination
    else:
        raise Exception("❌ Не удалось скачать файл")

# Экспортируем все необходимые функции
__all__ = [
    'extract_file_id_from_url',
    'convert_to_direct_link',
    'download_file_from_drive',
    'process_google_drive_link'
]
