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
        self.FOLDER_TIMEOUT = 60  # Таймаут на обработку одной папки (сек)

    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None

    def _upload_file_to_max(self, image_data):
        """
        Загружает одно изображение через POST /uploads и возвращает токен
        Согласно документации: https://dev.max.ru/docs-api/methods/POST/uploads
        """
        try:
            # 1. Получаем URL для загрузки
            upload_type = "image"
            response = requests.post(
                f"{self.api.base_url}/uploads",
                headers={"Authorization": self.api.token},
                params={"type": upload_type},
                timeout=30,
                verify=False
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения URL для загрузки: {response.status_code} - {response.text}")
                return None
            
            upload_data = response.json()
            upload_url = upload_data.get('url')
            
            if not upload_url:
                logger.error(f"❌ Не получен URL для загрузки: {upload_data}")
                return None
            
            logger.info(f"📤 Получен URL для загрузки: {upload_url[:50]}...")
            
            # 2. Загружаем файл по полученному URL
            # Преобразуем данные обратно в bytes
            if isinstance(image_data, list):
                image_bytes = bytes(image_data)
            else:
                image_bytes = image_data
            
            # Определяем MIME тип
            mime_type = 'image/jpeg'
            # Постараемся определить по сигнатуре файла
            if len(image_bytes) > 4:
                if image_bytes[:4] == b'\x89PNG':
                    mime_type = 'image/png'
                elif image_bytes[:2] == b'GIF':
                    mime_type = 'image/gif'
                elif image_bytes[:4] == b'RIFF':
                    mime_type = 'image/webp'
            
            files = {
                'data': ('image.jpg', image_bytes, mime_type)
            }
            
            # Загружаем файл
            upload_response = requests.post(
                upload_url,
                files=files,
                timeout=60,
                verify=False
            )
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Ошибка загрузки файла: {upload_response.status_code} - {upload_response.text}")
                return None
            
            upload_result = upload_response.json()
            token = upload_result.get('token')
            
            if not token:
                logger.error(f"❌ Не получен токен после загрузки: {upload_result}")
                return None
            
            logger.info(f"✅ Файл загружен, получен токен: {token[:10]}...")
            
            # Делаем паузу после загрузки, чтобы файл обработался на сервере
            time.sleep(1)
            
            return token
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки файла в MAX: {e}")
            return None

    def _send_message_to_chat(self, chat_id, text, image_tokens):
        """
        Отправляет сообщение с изображениями в чат по документации MAX API
        """
        try:
            if not self.api.token:
                logger.error("❌ Токен не установлен")
                return False
            
            # Формируем вложения
            attachments = []
            
            # Добавляем изображения (до 12 штук, но мы отправляем до 6)
            for token in image_tokens[:6]:
                attachments.append({
                    "type": "image",
                    "payload": {
                        "token": token
                    }
                })
            
            # Формируем тело запроса
            payload = {
                "chat_id": chat_id,
                "text": text,
                "format": "markdown",
                "attachments": attachments
            }
            
            logger.info(f"📤 Отправка сообщения в чат {chat_id} с {len(attachments)} изображениями")
            
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
            logger.error(f"❌ Ошибка отправки сообщения: {e}")
            return False

    def _parse_metadata(self, metadata_text):
        """Парсит метаданные из текста после #изъятая"""
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
            match = re.search(pattern, metadata_text, re.IGNORECASE)
            if match:
                metadata[key] = match.group(1).strip()
        
        return metadata

    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, full_text, images_data):
        """
        Обрабатывает ОДНУ папку:
        1. Загружает каждое изображение через POST /uploads (с таймаутом 60 сек на папку)
        2. Отправ
