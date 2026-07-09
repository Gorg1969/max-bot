import re
import requests
import logging

logger = logging.getLogger(__name__)

class GoogleDrive:
    """Работа с Google Drive"""
    
    def __init__(self):
        self.base_url = "https://drive.google.com"
    
    def extract_folder_id(self, url):
        """Извлечение ID папки из ссылки"""
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
    
    def get_files(self, folder_id):
        """Получение списка файлов в папке"""
        try:
            url = f"https://drive.google.com/drive/folders/{folder_id}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            file_pattern = r'https://drive.google.com/file/d/([a-zA-Z0-9_-]+)/view[^"]*'
            file_ids = re.findall(file_pattern, response.text)
            
            name_pattern = r'<span class="[^"]*">([^<]+\.(jpg|jpeg|png|gif|txt|md))</span>'
            names = re.findall(name_pattern, response.text)
            
            files = []
            for i, file_id in enumerate(file_ids):
                name = names[i][0] if i < len(names) else f"file_{file_id}"
                files.append({'id': file_id, 'name': name})
            return files
        except Exception as e:
            logger.error(f"❌ Ошибка получения файлов: {e}")
            return []
    
    def download_file(self, file_id):
        """Скачивание файла"""
        try:
            url = f"https://drive.google.com/uc?export=download&id={file_id}"
            response = requests.get(url, timeout=10)
            return response.text
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания: {e}")
            return None
    
    def publish_folder(self, folder_id, group_id, post_number=None, total_posts=None):
        """Публикация папки"""
        try:
            logger.info(f"📤 Публикация {folder_id} -> {group_id}")
            
            files = self.get_files(folder_id)
            if not files:
                return False, "Нет файлов в папке"
            
            info_file = None
            for f in files:
                if f['name'].lower() in ['info.txt', 'info.md']:
                    info_file = f
                    break
            
            if not info_file:
                return False, "Нет info.txt"
            
            info_text = self.download_file(info_file['id'])
            if not info_text:
                return False, "Не удалось скачать info.txt"
            
            # Отправляем текст
            if info_text:
                if post_number and total_posts:
                    header = f"📝 **Пост {post_number}/{total_posts}**\n\n"
                    self._send_message(group_id, header + info_text)
                else:
                    self._send_message(group_id, info_text)
            
            # Отправляем изображения
            images = [f for f in files if f['name'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))][:10]
            for image in images:
                self._send_message(group_id, f"📷 {image['name']}\n🔗 https://drive.google.com/file/d/{image['id']}/view")
            
            return True, "Успешно"
        except Exception as e:
            return False, str(e)
    
    def _send_message(self, chat_id, text):
        """Внутренняя отправка сообщения (заглушка)"""
        # Здесь будет вызов API MAX
        logger.info(f"📤 Отправка в {chat_id}: {text[:50]}...")
        return True
