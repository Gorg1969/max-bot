import requests
import re
import os
import time
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

def download_large_file_from_drive(file_id, destination_path, chunk_size=8192):
    """
    Скачивает большой файл с Google Drive (>200 МБ)
    """
    
    print(f"📥 Начинаем скачивание файла {file_id}")
    
    # Создаём сессию
    session = requests.Session()
    
    # Заголовки браузера - ОБЯЗАТЕЛЬНО!
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }
    
    # 1. ПЕРВЫЙ ЗАПРОС - получаем страницу с подтверждением
    initial_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    print(f"🔄 Шаг 1: Запрос к {initial_url}")
    
    try:
        response = session.get(initial_url, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status()
        
        print(f"📊 Статус: {response.status_code}")
        print(f"📊 URL после редиректа: {response.url}")
        
        # 2. ИЩЕМ ПАРАМЕТР CONFIRM
        confirm_param = None
        
        # Проверяем URL на наличие confirm
        if 'confirm=' in response.url:
            match = re.search(r'confirm=([^&]+)', response.url)
            if match:
                confirm_param = match.group(1)
                print(f"✅ Найден confirm в URL: {confirm_param}")
        
        # Если не нашли в URL, ищем в HTML
        if not confirm_param:
            html_content = response.text
            # Ищем confirm в JavaScript или HTML
            confirm_patterns = [
                r'confirm=([^&"\']+)',
                r'"confirm":"([^"]+)"',
                r'confirm=([a-zA-Z0-9_-]+)'
            ]
            
            for pattern in confirm_patterns:
                match = re.search(pattern, html_content)
                if match:
                    confirm_param = match.group(1)
                    print(f"✅ Найден confirm в HTML: {confirm_param}")
                    break
        
        # 3. ФОРМИРУЕМ ССЫЛКУ ДЛЯ СКАЧИВАНИЯ
        if confirm_param:
            download_url = f"https://drive.google.com/uc?export=download&confirm={confirm_param}&id={file_id}"
        else:
            # Если confirm не найден, пробуем стандартные варианты
            print("⚠️ Confirm не найден, пробуем стандартные варианты...")
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
        
        print(f"🔄 Шаг 2: Скачивание по {download_url}")
        
        # 4. СКАЧИВАЕМ ФАЙЛ
        response = session.get(
            download_url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=60
        )
        response.raise_for_status()
        
        # Проверяем, что это файл, а не HTML
        content_type = response.headers.get('content-type', '').lower()
        content_disposition = response.headers.get('content-disposition', '')
        
        print(f"📊 Content-Type: {content_type}")
        print(f"📊 Content-Disposition: {content_disposition}")
        
        # Если получили HTML - пробуем другой метод
        if 'text/html' in content_type or not content_disposition:
            print("⚠️ Получен HTML вместо файла, пробуем альтернативный метод...")
            
            # Альтернативный метод - через download.php
            alt_url = f"https://drive.google.com/download?export=download&id={file_id}"
            print(f"🔄 Альтернативный запрос: {alt_url}")
            
            response = session.get(
                alt_url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=60
            )
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', '').lower()
            content_disposition = response.headers.get('content-disposition', '')
            
            if 'text/html' in content_type:
                raise Exception("Файл не доступен для скачивания. Возможно, он приватный или удалён.")
        
        # 5. СОХРАНЯЕМ ФАЙЛ
        total_size = int(response.headers.get('content-length', 0))
        if total_size > 0:
            print(f"📦 Размер файла: {total_size / (1024*1024):.2f} МБ")
        else:
            print("📦 Размер файла неизвестен")
        
        downloaded = 0
        with open(destination_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Показываем прогресс
                    if downloaded % (10 * 1024 * 1024) < chunk_size:
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            print(f"📥 Скачано: {downloaded / (1024*1024):.1f} МБ ({progress:.1f}%)")
                        else:
                            print(f"📥 Скачано: {downloaded / (1024*1024):.1f} МБ")
        
        print(f"✅ Файл успешно скачан: {destination_path}")
        return destination_path
        
    except requests.exceptions.RequestException as e:
        raise Exception(f"❌ Ошибка сети: {e}")
    except Exception as e:
        raise Exception(f"❌ Ошибка скачивания: {e}")

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
    
    # Скачиваем файл
    return download_large_file_from_drive(file_id, destination)

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

# Экспортируем все необходимые функции
__all__ = [
    'extract_file_id_from_url',
    'convert_to_direct_link',
    'download_large_file_from_drive',
    'process_google_drive_link',
    'download_file_from_drive'
]
