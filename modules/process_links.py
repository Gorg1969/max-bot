import requests
import re
import os
from urllib.parse import urlparse, parse_qs

def extract_file_id_from_url(url):
    """
    Извлекает file_id из ссылки Google Drive
    Пример: https://drive.google.com/file/d/1V7LRSzWASnPvd06nYvWDf4aQeiw9HFVo/view
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

def download_large_file_from_drive(file_id, destination_path, chunk_size=8192):
    """
    Скачивает большой файл с Google Drive с обработкой подтверждения
    
    Args:
        file_id (str): ID файла в Google Drive
        destination_path (str): Путь для сохранения файла
        chunk_size (int): Размер чанка для скачивания
    
    Returns:
        str: Путь к сохранённому файлу
    
    Raises:
        Exception: Если не удалось скачать файл
    """
    
    # Формируем начальную ссылку
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    
    # Создаём сессию для сохранения cookies
    session = requests.Session()
    
    print(f"📥 Начинаем скачивание: {download_url}")
    
    try:
        # Первый запрос - получаем страницу с подтверждением (если нужно)
        response = session.get(download_url, stream=True, allow_redirects=True)
        response.raise_for_status()
        
        # Проверяем, не перенаправило ли на страницу с подтверждением
        if "confirm" in response.url:
            print("🔄 Обнаружена страница подтверждения, извлекаем параметр...")
            
            # Извлекаем параметр confirm из URL
            confirm_match = re.search(r"confirm=([^&]+)", response.url)
            if confirm_match:
                confirm_param = confirm_match.group(1)
                print(f"✅ Найден параметр confirm: {confirm_param}")
                
                # Формируем новую ссылку с подтверждением
                new_url = f"https://drive.google.com/uc?export=download&confirm={confirm_param}&id={file_id}"
                print(f"🔄 Повторный запрос: {new_url}")
                
                # Делаем повторный запрос с подтверждением
                response = session.get(new_url, stream=True)
                response.raise_for_status()
        
        # Проверяем, что скачивается именно файл, а не HTML
        content_type = response.headers.get("content-type", "")
        
        if "text/html" in content_type:
            # Если всё равно получили HTML, возможно, файл требует авторизации
            raise Exception("❌ Получен HTML вместо файла. Возможно, файл недоступен или требует входа в аккаунт.")
        
        # Определяем размер файла для прогресса
        total_size = int(response.headers.get("content-length", 0))
        if total_size > 0:
            print(f"📦 Размер файла: {total_size / (1024*1024):.2f} МБ")
        
        # Скачиваем файл с прогрессом
        downloaded = 0
        with open(destination_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Показываем прогресс каждые 5 МБ
                    if downloaded % (5 * 1024 * 1024) < chunk_size:
                        progress = (downloaded / total_size * 100) if total_size > 0 else 0
                        print(f"📥 Скачано: {downloaded / (1024*1024):.1f} МБ ({progress:.1f}%)")
        
        print(f"✅ Файл успешно скачан: {destination_path}")
        return destination_path
        
    except requests.exceptions.RequestException as e:
        raise Exception(f"❌ Ошибка сети при скачивании: {e}")
    except Exception as e:
        raise Exception(f"❌ Ошибка при скачивании: {e}")

def process_google_drive_link(link, download_dir="downloads"):
    """
    Основная функция для обработки ссылки Google Drive
    
    Args:
        link (str): Ссылка на файл в Google Drive
        download_dir (str): Директория для сохранения
    
    Returns:
        str: Путь к скачанному файлу
    """
    
    # Создаём папку для загрузок, если её нет
    os.makedirs(download_dir, exist_ok=True)
    
    # Извлекаем ID файла
    file_id = extract_file_id_from_url(link)
    if not file_id:
        raise ValueError("❌ Не удалось извлечь ID файла из ссылки")
    
    print(f"🔑 ID файла: {file_id}")
    
    # Формируем имя для сохранения
    filename = f"file_{file_id}.zip"
    
    # Полный путь для сохранения
    destination = os.path.join(download_dir, filename)
    
    # Скачиваем файл
    return download_large_file_from_drive(file_id, destination)

# Сохраняем совместимость со старым кодом
def download_file_from_drive(url, destination_path):
    """
    Устаревшая функция для обратной совместимости
    """
    try:
        file_id = extract_file_id_from_url(url)
        if not file_id:
            return False
        result = download_large_file_from_drive(file_id, destination_path)
        return True if result else False
    except Exception as e:
        print(f"❌ Ошибка скачивания: {e}")
        return False
