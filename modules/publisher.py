# modules/publisher.py
import logging
import os
import time
import re
import requests
import threading
import json
import uuid
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_publishes = {}
        self.publish_threads = {}
        self.FOLDER_TIMEOUT = 120
        self.STOP_FLAG = {}
        self.moscow_tz = pytz.timezone('Europe/Moscow')

    def extract_chat_id_from_folder(self, folder_name):
        """
        Извлекает chat_id из названия папки.
        Поддерживает форматы:
        - "-1001234567890"
        - "1 -1001234567890"
        - "1-1001234567890"
        - "Канал 1 -1001234567890"
        - "1001234567890" (без минуса, добавит автоматически)
        """
        if not folder_name:
            return None
        
        # Ищем chat_id в формате -1001234567890 (с минусом)
        match = re.search(r'(-?\d{10,})', folder_name)
        if match:
            chat_id = match.group(1)
            # Если chat_id без минуса, добавляем
            if not chat_id.startswith('-') and len(chat_id) >= 10:
                chat_id = f"-{chat_id}"
            return chat_id
        
        # Если не нашли, пробуем найти просто число
        match = re.search(r'(\d{10,})', folder_name)
        if match:
            return f"-{match.group(1)}"
        
        return None

    def _send_and_get_id(self, chat_id, text, image_tokens):
        """
        Отправляет сообщение в чат и пытается получить ID.
        Если ID не получен, генерирует временный.
        """
        try:
            if not self.api.token:
                return False, None
            
            attachments = []
            for token in image_tokens[:10]:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            payload = {
                "text": text,
                "format": "markdown"
            }
            
            if attachments:
                payload["attachments"] = attachments
            
            chat_id_with_dash = chat_id if str(chat_id).startswith('-') else f"-{chat_id}"
            
            logger.info(f"📤 Отправка в чат {chat_id_with_dash} с {len(attachments)} фото")
            
            response = requests.post(
                f"{self.api.base_url}/messages?chat_id={chat_id_with_dash}",
                headers={
                    "Authorization": self.api.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                # Пытаемся получить ID из ответа
                message_id = None
                try:
                    result = response.json()
                    logger.info(f"📨 Ответ API: {json.dumps(result, indent=2)}")
                    
                    # Ищем ID в разных местах
                    if 'data' in result and 'id' in result['data']:
                        message_id = result['data']['id']
                    elif 'id' in result:
                        message_id = result['id']
                    elif 'message_id' in result:
                        message_id = result['message_id']
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось распарсить ответ API: {e}")
                
                # Формируем ссылку
                if message_id:
                    post_link = f"https://max.ru/c/{chat_id_with_dash}/{message_id}"
                    logger.info(f"🔗 Получен ID из API: {message_id}")
                    return True, post_link
                else:
                    # Генерируем временный ID
                    temp_id = str(uuid.uuid4())[:8]
                    post_link = f"https://max.ru/c/{chat_id_with_dash}/{temp_id}?temp=1"
                    logger.warning(f"⚠️ API не вернул ID, используем сгенерированный: {temp_id}")
                    return True, post_link
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            import traceback
            traceback.print_exc()
            return False, None

    def _send_to_user(self, user_id, text, image_tokens):
        """Отправляет сообщение пользователю (резерв)"""
        try:
            if not self.api.token:
                return False, None
            
            attachments = []
            for token in image_tokens[:10]:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            payload = {
                "user_id": user_id,
                "text": text,
                "format": "markdown"
            }
            
            if attachments:
                payload["attachments"] = attachments
            
            logger.info(f"📤 Отправка пользователю {user_id} с {len(attachments)} фото")
            
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
                # Пробуем получить ID
                message_id = None
                post_link = None
                try:
                    result = response.json()
                    if 'data' in result and 'id' in result['data']:
                        message_id = result['data']['id']
                    elif 'id' in result:
                        message_id = result['id']
                    
                    if message_id:
                        post_link = f"https://max.ru/c/{user_id}/{message_id}"
                    else:
                        post_link = f"https://max.ru/c/{user_id}"
                except:
                    post_link = f"https://max.ru/c/{user_id}"
                
                logger.info(f"✅ Сообщение отправлено пользователю {user_id}")
                return True, post_link
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False, None

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

    def publish_folder_with_tokens(self, user_id, folder_name, ad_text, metadata_text, image_tokens):
        """Публикует папку с уже загруженными токенами фото"""
        try:
            if self.STOP_FLAG.get(user_id, False):
                logger.info(f"⏹️ Пропускаем папку {folder_name} - остановка")
                return False, "Остановка пользователем"
            
            # ===== ИЗВЛЕКАЕМ CHAT_ID ИЗ НАЗВАНИЯ ПАПКИ =====
            chat_id = self.extract_chat_id_from_folder(folder_name)
            
            if not chat_id:
                logger.error(f"❌ Не удалось извлечь chat_id из: {folder_name}")
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            logger.info(f"📤 Извлечен chat_id из имени папки: {chat_id}")
            logger.info(f"📸 Получено {len(image_tokens)} токенов фото")
            
            # Отправляем сообщение
            success, post_link = self._send_and_get_id(chat_id, ad_text, image_tokens)
            
            if not success:
                logger.warning("⚠️ Отправка в чат не удалась, пробуем в личные сообщения...")
                success, post_link = self._send_to_user(user_id, ad_text, image_tokens)
            
            if not success:
                return False, "Не удалось отправить сообщение"
            
            # Сохраняем метаданные
            metadata = self._parse_metadata(metadata_text)
            
            if post_link:
                metadata['post_link'] = post_link
                logger.info(f"🔗 Сохранена ссылка: {post_link}")
            
            # Сохраняем chat_id в метаданных
            metadata['chat_id'] = chat_id
            
            # Время публикации
            now = datetime.now(self.moscow_tz)
            timestamp = now.timestamp()
            
            # Сохраняем в БД
            self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, timestamp)
            self.db.add_publication(user_id, folder_name, chat_id, status='success')
            
            logger.info(f"✅ Папка {folder_name} опубликована в чат {chat_id}")
            return True, f"✅ Папка {folder_name} опубликована в чат {chat_id}"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)

    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, images_data):
        """Старый метод - загружает фото и публикует"""
        try:
            if self.STOP_FLAG.get(user_id, False):
                return False, "Остановка пользователем"
            
            image_tokens = []
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            
            for i in range(max_images):
                if self.STOP_FLAG.get(user_id, False):
                    return False, "Остановка пользователем"
                
                img_data = images_data[i]
                if not img_data:
                    continue
                
                if isinstance(img_data, dict):
                    data = img_data.get('data')
                    if isinstance(data, list):
                        image_bytes = bytes(data)
                    elif isinstance(data, bytes):
                        image_bytes = data
                    else:
                        continue
                else:
                    image_bytes = img_data
                
                token = self.api.upload_file(image_bytes, f"image_{i}.jpg")
                if token:
                    image_tokens.append(token)
                    time.sleep(0.3)
            
            return self.publish_folder_with_tokens(
                user_id, folder_name, ad_text, metadata_text, image_tokens
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return False, str(e)

    def stop(self, user_id):
        """Останавливает публикацию"""
        logger.info(f"⏹️ Остановка публикации для пользователя {user_id}")
        self.STOP_FLAG[user_id] = True
        
        try:
            user_folder = self.fm.get_user_folder(user_id)
            if os.path.exists(user_folder):
                import shutil
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Удалены все файлы пользователя {user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка удаления файлов: {e}")
        
        def reset_stop_flag():
            time.sleep(5)
            self.STOP_FLAG[user_id] = False
        
        threading.Thread(target=reset_stop_flag, daemon=True).start()
        return True

    def is_running(self, user_id):
        return self.STOP_FLAG.get(user_id, False)
