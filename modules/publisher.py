import logging
import os
import time
import re
import requests
import threading
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_publishes = {}
        self.publish_threads = {}
        self.FOLDER_TIMEOUT = 60
        self.STOP_FLAG = {}

    def extract_chat_id(self, folder_name):
        """
        Извлекает chat_id из названия папки.
        ВОЗВРАЩАЕТ С МИНУСОМ для групп!
        Пример: "1/7 -76868172202744" -> "-76868172202744"
        """
        if not folder_name:
            return None
        
        # Ищем формат с дефисом: "1/7 -76868172202744" -> "-76868172202744"
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            chat_id = match.group(1)
            if len(chat_id) >= 10:
                return f"-{chat_id}"  # <-- ВОЗВРАЩАЕМ С МИНУСОМ
        
        # Ищем любое число
        match = re.search(r'(\d{10,})', folder_name)
        if match:
            return match.group(1)
        
        return None

    def _upload_file_to_max(self, image_data, user_id):
        """Загружает ОДНО изображение через POST /uploads"""
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
            
            # 2. Извлекаем байты из разных форматов
            if isinstance(image_data, dict):
                if 'data' in image_data:
                    img_data = image_data['data']
                else:
                    for key, value in image_data.items():
                        if isinstance(value, (list, bytes, bytearray)):
                            img_data = value
                            break
                    else:
                        logger.error(f"❌ В словаре нет данных: {image_data.keys()}")
                        return None
            else:
                img_data = image_data
            
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
            
            logger.info(f"✅ Файл загружен, токен: {token[:20]}...")
            
            time.sleep(1)
            return token
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
            return None

    def _send_to_chat(self, chat_id, text, image_tokens):
        """
        Отправляет сообщение в чат.
        chat_id уже приходит С МИНУСОМ из extract_chat_id.
        """
        try:
            if not self.api.token:
                return False
            
            # Формируем вложения (максимум 10 фото)
            attachments = []
            for token in image_tokens[:10]:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            # Формируем payload (без chat_id в теле!)
            payload = {
                "text": text,
                "format": "markdown"
            }
            
            if attachments:
                payload["attachments"] = attachments
            
            # chat_id уже с минусом, используем как есть
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
                logger.info(f"✅ Сообщение отправлено в чат {chat_id_with_dash}")
                return True
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def _send_to_user(self, user_id, text, image_tokens):
        """Отправляет сообщение в личные сообщения пользователя"""
        try:
            if not self.api.token:
                return False
            
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
                logger.info(f"✅ Сообщение отправлено пользователю {user_id}")
                return True
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
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

    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, images_data):
        """
        Обрабатывает ОДНУ папку:
        1. Загружает изображения (максимум 10) через POST /uploads
        2. Отправляет сообщение с текстом и фото в чат
        3. Сохраняет метаданные в БД
        """
        try:
            if self.STOP_FLAG.get(user_id, False):
                logger.info(f"⏹️ Пропускаем папку {folder_name} - остановка")
                return False, "Остановка пользователем"
            
            start_time = time.time()
            
            # 1. Извлекаем chat_id (С МИНУСОМ)
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                logger.error(f"❌ Не удалось извлечь chat_id из: {folder_name}")
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            logger.info(f"📤 Извлечен chat_id: {chat_id}")
            
            # 2. Загружаем изображения (максимум 10)
            image_tokens = []
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            
            logger.info(f"📸 Найдено {len(images_data)} изображений, загружаем максимум {max_images}")
            
            for i in range(max_images):
                if self.STOP_FLAG.get(user_id, False):
                    return False, "Остановка пользователем"
                
                if time.time() - start_time > self.FOLDER_TIMEOUT:
                    return False, f"Таймаут обработки папки {folder_name}"
                
                logger.info(f"📤 Загрузка изображения {i+1}/{max_images}")
                
                img_data = images_data[i]
                if not img_data:
                    continue
                
                token = self._upload_file_to_max(img_data, user_id)
                if token:
                    image_tokens.append(token)
                    logger.info(f"✅ Изображение {i+1} загружено")
                else:
                    logger.warning(f"⚠️ Не удалось загрузить изображение {i+1}")
            
            logger.info(f"📦 Загружено {len(image_tokens)} из {max_images} изображений")
            
            # 3. Отправляем сообщение в чат (chat_id уже с минусом)
            if image_tokens:
                success = self._send_to_chat(chat_id, ad_text, image_tokens)
            else:
                logger.info(f"📤 Отправка только текста в чат {chat_id}")
                success = self._send_to_chat(chat_id, ad_text, [])
            
            # Если не удалось отправить в чат, пробуем в личные сообщения
            if not success:
                logger.warning("⚠️ Отправка в чат не удалась, пробуем в личные сообщения...")
                if image_tokens:
                    success = self._send_to_user(user_id, ad_text, image_tokens)
                else:
                    success = self._send_to_user(user_id, ad_text, [])
            
            if not success:
                return False, "Не удалось отправить сообщение"
            
            # 4. Сохраняем метаданные для отчета
            metadata = self._parse_metadata(metadata_text)
            self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, time.time())
            self.db.add_publication(user_id, folder_name, chat_id)
            
            return True, f"✅ Папка {folder_name} опубликована с {len(image_tokens)} фото"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)

    def stop(self, user_id):
        """Останавливает публикацию и удаляет все файлы пользователя"""
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
