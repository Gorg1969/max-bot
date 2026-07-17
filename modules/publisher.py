# modules/publisher.py - с поддержкой нескольких пользователей

import logging
import os
import time
import re
import requests
import threading
import json
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.FOLDER_TIMEOUT = 120
        # ✅ Отдельные флаги для каждого пользователя
        self.STOP_FLAG = {}

    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            chat_id = match.group(1)
            if len(chat_id) >= 10:
                return chat_id
        
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return match.group(1)
        
        match = re.search(r'(\d+)', folder_name)
        if match:
            chat_id = match.group(1)
            if len(chat_id) >= 10:
                return chat_id
        
        return None

    def _upload_file_to_max(self, image_data, user_id):
        """Загружает ОДНО изображение (оптимизировано по памяти)"""
        try:
            if self.STOP_FLAG.get(user_id, False):
                return None

            # 1. Получаем URL для загрузки
            response = requests.post(
                f"{self.api.base_url}/uploads",
                headers={"Authorization": self.api.token},
                params={"type": "image"},
                timeout=30,
                verify=False
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения URL: {response.status_code}")
                return None
            
            upload_data = response.json()
            upload_url = upload_data.get('url')
            
            if not upload_url:
                logger.error(f"❌ Не получен URL: {upload_data}")
                return None
            
            # ✅ Извлекаем байты без создания list() (экономия памяти)
            if isinstance(image_data, dict):
                if 'data' in image_data:
                    img_data = image_data['data']
                else:
                    for key, value in image_data.items():
                        if isinstance(value, (list, bytes, bytearray)):
                            img_data = value
                            break
                    else:
                        logger.error(f"❌ В словаре нет данных")
                        return None
            else:
                img_data = image_data
            
            # ✅ Конвертируем в байты напрямую (без list())
            if isinstance(img_data, list):
                image_bytes = bytes(img_data)
            elif isinstance(img_data, (bytes, bytearray)):
                image_bytes = bytes(img_data)
            else:
                logger.error(f"❌ Неподдерживаемый тип данных: {type(img_data)}")
                return None
            
            # 3. Отправляем файл
            files = {'data': ('image.jpg', image_bytes, 'image/jpeg')}
            
            upload_response = requests.post(
                upload_url,
                files=files,
                timeout=60,
                verify=False
            )
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Ошибка загрузки: {upload_response.status_code}")
                return None
            
            upload_result = upload_response.json()
            
            # 4. Извлекаем токен
            token = None
            if 'photos' in upload_result and isinstance(upload_result['photos'], dict):
                for photo_data in upload_result['photos'].values():
                    if isinstance(photo_data, dict) and 'token' in photo_data:
                        token = photo_data['token']
                        break
            
            if not token and 'token' in upload_result:
                token = upload_result['token']
            
            if not token:
                logger.error(f"❌ Не получен токен: {upload_result}")
                return None
            
            # ✅ Освобождаем память
            del image_bytes
            
            time.sleep(0.3)
            return token
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
            return None

    def _send_to_chat(self, chat_id, text, image_tokens):
        """Отправляет сообщение в чат"""
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
            
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            
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
                response_data = response.json()
                post_id = None
                if 'message' in response_data:
                    post_id = response_data['message'].get('id')
                elif 'id' in response_data:
                    post_id = response_data['id']
                
                return True, post_id
            else:
                logger.error(f"❌ Ошибка: {response.status_code}")
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False, None

    def _send_to_user(self, user_id, text, image_tokens):
        """Отправляет в личные сообщения"""
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
            
            response = requests.post(
                f"{self.api.base_url}/messages?user_id={user_id}",
                headers={
                    "Authorization": self.api.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                response_data = response.json()
                post_id = None
                if 'message' in response_data:
                    post_id = response_data['message'].get('id')
                elif 'id' in response_data:
                    post_id = response_data['id']
                
                return True, post_id
            else:
                logger.error(f"❌ Ошибка: {response.status_code}")
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False, None

    def _parse_metadata(self, metadata_text):
        """Парсит метаданные"""
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

    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, images_data):
        """Публикует одну папку для конкретного пользователя"""
        try:
            # ✅ Проверяем флаг ТОЛЬКО для этого пользователя
            if self.STOP_FLAG.get(user_id, False):
                return False, "Остановка пользователем"
            
            start_time = time.time()
            
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            # Загружаем изображения (максимум 10)
            image_tokens = []
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            
            for i in range(max_images):
                if self.STOP_FLAG.get(user_id, False):
                    return False, "Остановка пользователем"
                
                if time.time() - start_time > self.FOLDER_TIMEOUT:
                    return False, f"Таймаут обработки папки {folder_name}"
                
                img_data = images_data[i]
                if not img_data:
                    continue
                
                token = self._upload_file_to_max(img_data, user_id)
                if token:
                    image_tokens.append(token)
            
            # Отправляем сообщение
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            post_id = None
            
            if image_tokens:
                success, post_id = self._send_to_chat(chat_id, ad_text, image_tokens)
            else:
                success, post_id = self._send_to_chat(chat_id, ad_text, [])
            
            if not success:
                if image_tokens:
                    success, post_id = self._send_to_user(user_id, ad_text, image_tokens)
                else:
                    success, post_id = self._send_to_user(user_id, ad_text, [])
            
            if not success:
                return False, "Не удалось отправить сообщение"
            
            if not post_id:
                hash_input = f"{chat_id}_{time.time()}_{folder_name}"
                post_id = hashlib.md5(hash_input.encode()).hexdigest()[:12]
            
            post_link = f"https://max.ru/c/{chat_id_with_dash}/{post_id}"
            
            metadata = self._parse_metadata(metadata_text)
            metadata['post_link'] = post_link
            metadata['post_id'] = post_id
            
            self.db.save_ad_metadata(
                user_id, folder_name, chat_id_with_dash, metadata, 
                time.time(), post_id=post_id, post_link=post_link
            )
            self.db.add_publication(user_id, folder_name, chat_id_with_dash, post_id)
            
            return True, f"✅ Папка {folder_name} опубликована с {len(image_tokens)} фото"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            return False, str(e)

    def stop(self, user_id):
        """Останавливает публикацию ТОЛЬКО для одного пользователя"""
        logger.info(f"⏹️ Остановка для пользователя {user_id}")
        self.STOP_FLAG[user_id] = True
        
        def reset_stop_flag():
            time.sleep(10)
            self.STOP_FLAG[user_id] = False
        
        threading.Thread(target=reset_stop_flag, daemon=True).start()
        return True

    def is_running(self, user_id):
        return self.STOP_FLAG.get(user_id, False)
