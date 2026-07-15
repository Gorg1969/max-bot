import logging
import os
import time
import re
import requests
import threading
import base64

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_publishes = {}
        self.FOLDER_TIMEOUT = 60

    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None

    def _upload_image_bytes(self, image_bytes, filename):
        """
        Загружает изображение из байтов на сервер MAX через POST /uploads
        """
        try:
            files = {
                'file': (filename, image_bytes, 'image/jpeg')
            }
            
            response = requests.post(
                f"{self.api.base_url}/uploads",
                headers={"Authorization": self.api.token},
                files=files,
                timeout=30,
                verify=False
            )
            
            if response.status_code == 200:
                token = response.json().get('token')
                if token:
                    logger.info(f"✅ Загружено фото: {filename}")
                    return token
                else:
                    logger.error(f"❌ Токен не получен: {response.text}")
                    return None
            else:
                logger.error(f"❌ Ошибка загрузки {filename}: {response.status_code} - {response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {filename}: {e}")
            return None

    def _send_with_images_from_data(self, chat_id, text, images_data):
        """
        Отправляет сообщение с изображениями из подготовленных данных
        Загружает фото на MAX и отправляет с токенами
        """
        try:
            if not self.api.token:
                logger.error("❌ Токен не установлен")
                return False
            
            # Загружаем каждое изображение на сервер MAX
            image_tokens = []
            for img_data in images_data[:3]:
                img_bytes = img_data.get('data')
                img_name = img_data.get('name')
                
                if not img_bytes:
                    continue
                
                # Преобразуем обратно в bytes
                if isinstance(img_bytes, list):
                    img_bytes = bytes(img_bytes)
                
                token = self._upload_image_bytes(img_bytes, img_name)
                if token:
                    image_tokens.append(token)
            
            # Формируем attachments
            attachments = []
            for token in image_tokens:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            # Отправляем сообщение
            payload = {
                "chat_id": chat_id,
                "text": text,
                "format": "markdown"
            }
            
            if attachments:
                payload["attachments"] = attachments
            
            response = requests.post(
                f"{self.api.base_url}/messages",
                headers={
                    "Authorization": self.api.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение отправлено в чат {chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {response.status_code} - {response.text[:200]}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def _send_message_only(self, chat_id, text):
        """Отправляет только текст"""
        try:
            if not self.api.token:
                return False
            
            payload = {
                "chat_id": chat_id,
                "text": text,
                "format": "markdown"
            }
            
            response = requests.post(
                f"{self.api.base_url}/messages",
                headers={
                    "Authorization": self.api.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=30,
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Текст отправлен в чат {chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки текста: {response.status_code} - {response.text[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки текста: {e}")
            return False

    def _parse_metadata(self, metadata_text):
        """
        Парсит метаданные из текста после #изъятая
        """
        metadata = {}
        if not metadata_text:
            return metadata
        
        fields = {
            'Название': r'Название:\s*(.+)',
            'Ссылка': r'Ссылка:\s*(.+)',
            'Код предложения': r'Код предложения:\s*(.+)',
            'Цена в лизинге': r'Цена\s*[вВ]\s*лизинге:\s*(.+)',
        }
        
        for key, pattern in fields.items():
            match = re.search(pattern, metadata_text)
            if match:
                metadata[key] = match.group(1).strip()
        
        return metadata

    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, full_text, images_data):
        """
        Обрабатывает ОДНУ папку из подготовленных данных
        """
        try:
            # 1. Извлекаем chat_id
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            logger.info(f"📤 Публикация папки {folder_name} в чат {chat_id}")
            
            # 2. Отправляем текст + фото
            if images_data:
                success = self._send_with_images_from_data(chat_id, ad_text, images_data)
            else:
                success = self._send_message_only(chat_id, ad_text)
            
            if not success:
                return False, f"Не удалось отправить в чат {chat_id}"
            
            # 3. Сохраняем метаданные для отчета
            metadata = self._parse_metadata(metadata_text)
            self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, time.time())
            self.db.add_publication(user_id, folder_name, chat_id)
            
            return True, f"✅ Папка {folder_name} опубликована"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            return False, str(e)

    def start(self, user_id):
        """Запускает публикацию (устаревший метод, используется для обратной совместимости)"""
        return False

    def stop(self, user_id):
        """Останавливает публикацию"""
        if self.active_publishes.get(user_id, False):
            self.active_publishes[user_id] = False
            logger.info(f"⏹️ Публикация остановлена для {user_id}")
            return True
        return False

    def is_running(self, user_id):
        return self.active_publishes.get(user_id, False)
