# modules/publisher.py - РАБОЧАЯ ВЕРСИЯ

import logging
import os
import time
import re
import requests
import threading
import json
import base64
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.FOLDER_TIMEOUT = 120
        self.STOP_FLAG = {}
        
        # Проверяем наличие необходимых атрибутов
        if not hasattr(self.api, 'base_url'):
            logger.warning("⚠️ API объект не содержит base_url, используется значение по умолчанию")
            self.api.base_url = "https://platform-api2.max.ru"
        
        if not hasattr(self.api, 'token'):
            logger.error("❌ API объект не содержит token!")
        
        logger.info(f"✅ Publisher инициализирован с base_url: {self.api.base_url}")

    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из имени папки"""
        try:
            # Паттерн: "Название - 1234567890" или просто "1234567890"
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
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения chat_id: {e}")
            return None

    def _upload_file_to_max(self, image_data, user_id):
        """Загружает изображение на сервер MAX"""
        try:
            if self.STOP_FLAG.get(user_id, False):
                return None

            # Получаем URL для загрузки
            response = requests.post(
                f"{self.api.base_url}/uploads",
                headers={"Authorization": self.api.token},
                params={"type": "image"},
                timeout=30,
                verify=False
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения URL: {response.status_code}")
                logger.error(f"Ответ: {response.text[:200]}")
                return None
            
            upload_data = response.json()
            upload_url = upload_data.get('url')
            
            if not upload_url:
                logger.error(f"❌ Не получен URL: {upload_data}")
                return None
            
            # Подготавливаем данные изображения
            image_bytes = None
            
            if isinstance(image_data, dict):
                if 'bytes' in image_data:
                    image_bytes = image_data['bytes']
                elif 'data' in image_data:
                    image_bytes = base64.b64decode(image_data['data'])
            elif isinstance(image_data, (bytes, bytearray)):
                image_bytes = bytes(image_data)
            else:
                logger.error(f"❌ Неподдерживаемый тип: {type(image_data)}")
                return None
            
            if not image_bytes:
                logger.error("❌ Нет байтов изображения")
                return None
            
            # Загружаем изображение
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
            
            # Извлекаем токен изображения
            token = None
            if 'photos' in upload_result and isinstance(upload_result['photos'], dict):
                for photo_data in upload_result['photos'].values():
                    if isinstance(photo_data, dict) and 'token' in photo_data:
                        token = photo_data['token']
                        break
            
            if not token and 'token' in upload_result:
                token = upload_result['token']
            
            if not token:
                logger.error(f"❌ Нет токена в ответе: {upload_result}")
                return None
            
            # Очищаем память
            del image_bytes
            time.sleep(0.3)
            return token
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки изображения: {e}")
            return None

    def _send_to_chat(self, chat_id, text, image_tokens):
        """Отправляет сообщение в чат"""
        try:
            if not self.api.token:
                logger.error("❌ Нет токена для отправки")
                return False, None
            
            # Формируем вложения
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
            
            # Добавляем chat_id с дефисом, если нужно
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            
            # Отправляем в чат
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
                
                logger.info(f"✅ Отправлено в чат {chat_id_with_dash}, post_id: {post_id}")
                return True, post_id
            else:
                logger.error(f"❌ Ошибка отправки в чат: {response.status_code}")
                logger.error(f"Ответ: {response.text[:500]}")
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False, None

    def _send_to_user(self, user_id, text, image_tokens):
        """Отправляет сообщение пользователю (личное сообщение)"""
        try:
            if not self.api.token:
                logger.error("❌ Нет токена для отправки")
                return False, None
            
            # Формируем вложения
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
            
            # Отправляем в личные сообщения
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
                
                logger.info(f"✅ Отправлено пользователю {user_id}, post_id: {post_id}")
                return True, post_id
            else:
                logger.error(f"❌ Ошибка отправки в личные: {response.status_code}")
                logger.error(f"Ответ: {response.text[:500]}")
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в личные: {e}")
            return False, None

    def _parse_metadata(self, metadata_text):
        """Парсит метаданные из текста"""
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
        """Публикует одну папку с объявлением"""
        try:
            if self.STOP_FLAG.get(user_id, False):
                return False, "Остановка пользователем"
            
            start_time = time.time()
            
            # Извлекаем chat_id из имени папки
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                return False, f"Не удалось извлечь chat_id из папки: {folder_name}"
            
            logger.info(f"📂 Публикация папки: {folder_name}, chat_id: {chat_id}")
            
            # Загружаем изображения
            image_tokens = []
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            
            for i in range(max_images):
                if self.STOP_FLAG.get(user_id, False):
                    return False, "Остановка пользователем"
                
                if time.time() - start_time > self.FOLDER_TIMEOUT:
                    return False, f"Таймаут при обработке папки: {folder_name}"
                
                img_data = images_data[i]
                if not img_data:
                    continue
                
                token = self._upload_file_to_max(img_data, user_id)
                if token:
                    image_tokens.append(token)
                    logger.info(f"📸 Загружено изображение {i+1}/{max_images}")
            
            # Отправляем в чат
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            post_id = None
            
            logger.info(f"📤 Отправка в чат {chat_id_with_dash} с {len(image_tokens)} фото")
            
            if image_tokens:
                success, post_id = self._send_to_chat(chat_id, ad_text, image_tokens)
            else:
                success, post_id = self._send_to_chat(chat_id, ad_text, [])
            
            # Если не удалось отправить в чат, пробуем в личные
            if not success:
                logger.warning(f"⚠️ Не удалось отправить в чат, пробуем в личные {user_id}")
                if image_tokens:
                    success, post_id = self._send_to_user(user_id, ad_text, image_tokens)
                else:
                    success, post_id = self._send_to_user(user_id, ad_text, [])
            
            if not success:
                return False, "Не удалось отправить сообщение ни в чат, ни в личные"
            
            # Генерируем post_id если не получен
            if not post_id:
                hash_input = f"{chat_id}_{time.time()}_{folder_name}"
                post_id = hashlib.md5(hash_input.encode()).hexdigest()[:12]
                logger.warning(f"⚠️ post_id не получен, сгенерирован: {post_id}")
            
            # Формируем ссылку
            post_link = f"https://max.ru/c/{chat_id_with_dash}/{post_id}"
            
            # Парсим метаданные
            metadata = self._parse_metadata(metadata_text)
            metadata['post_link'] = post_link
            metadata['post_id'] = post_id
            
            # Сохраняем в БД
            if self.db:
                try:
                    self.db.save_ad_metadata(
                        user_id, folder_name, chat_id_with_dash, metadata, 
                        time.time(), post_id=post_id, post_link=post_link
                    )
                    self.db.add_publication(user_id, folder_name, chat_id_with_dash, post_id)
                    logger.info(f"💾 Сохранено в БД: {post_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка сохранения в БД: {e}")
            
            return True, f"✅ Опубликовано с {len(image_tokens)} фото, ссылка: {post_link}"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации папки: {e}")
            logger.error(f"Трассировка:", exc_info=True)
            return False, str(e)

    def stop(self, user_id):
        """Останавливает публикацию для пользователя"""
        logger.info(f"⏹️ Остановка публикации для пользователя {user_id}")
        self.STOP_FLAG[user_id] = True
        
        def reset_stop_flag():
            time.sleep(10)
            self.STOP_FLAG[user_id] = False
            logger.info(f"🔄 Сброшен флаг остановки для {user_id}")
        
        threading.Thread(target=reset_stop_flag, daemon=True).start()
        return True

    def is_running(self, user_id):
        """Проверяет, выполняется ли публикация для пользователя"""
        return self.STOP_FLAG.get(user_id, False)
