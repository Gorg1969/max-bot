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
        # Словарь для хранения временных данных до получения вебхука
        self.pending_messages = {}  # key: chat_id -> {user_id, folder_name, metadata, timestamp}

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
        Отправляет сообщение в чат и получает ID.
        ВАЖНО: при отсутствии ID возвращает None, НЕ заглушку!
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
            
            chat_id_str = str(chat_id)
            chat_id_for_api = chat_id_str if chat_id_str.startswith('-') else f"-{chat_id_str}"
            
            logger.info(f"📤 Отправка в чат {chat_id_for_api} с {len(attachments)} фото")
            
            response = requests.post(
                f"{self.api.base_url}/messages?chat_id={chat_id_for_api}",
                headers={
                    "Authorization": self.api.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                message_id = None
                post_link = None
                
                try:
                    result = response.json()
                    logger.info(f"📨 Ответ API: {json.dumps(result, indent=2)}")
                    
                    # Ищем ID в ответе
                    if isinstance(result, dict):
                        if 'data' in result and isinstance(result['data'], dict):
                            if 'id' in result['data']:
                                message_id = result['data']['id']
                            elif 'message_id' in result['data']:
                                message_id = result['data']['message_id']
                        
                        if not message_id and 'id' in result:
                            message_id = result['id']
                        
                        if not message_id and 'message_id' in result:
                            message_id = result['message_id']
                        
                        if not message_id and 'mid' in result:
                            message_id = result['mid']
                    
                    # ЕСЛИ ID НЕ НАЙДЕН - ВОЗВРАЩАЕМ None, А НЕ ЗАГЛУШКУ!
                    if message_id:
                        post_link = f"https://max.ru/c/{chat_id_str}/{message_id}"
                        logger.info(f"🔗 Получен ID: {message_id}, ссылка: {post_link}")
                        return True, post_link
                    else:
                        # ❌ НЕ СОЗДАЕМ ЗАГЛУШКУ!
                        logger.warning(f"⚠️ ID не найден в ответе для чата {chat_id_str}")
                        logger.warning(f"⚠️ Ответ: {response.text[:200]}")
                        return True, None  # Успех, но без ID
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка парсинга: {e}")
                    return True, None
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
                        post_link = None
                except:
                    post_link = None
                
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
        """
        Публикует папку с уже загруженными токенами фото.
        Сохраняет в pending ДО получения ID.
        """
        try:
            if self.STOP_FLAG.get(user_id, False):
                logger.info(f"⏹️ Пропускаем папку {folder_name} - остановка")
                return False, "Остановка пользователем"
            
            # Извлекаем chat_id из названия папки
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
            
            # Парсим метаданные
            metadata = self._parse_metadata(metadata_text)
            metadata['chat_id'] = chat_id
            
            # ЕСЛИ ССЫЛКА ПОЛУЧЕНА СРАЗУ
            if post_link:
                metadata['post_link'] = post_link
                logger.info(f"🔗 Ссылка получена сразу: {post_link}")
                
                # Сохраняем в БД с ссылкой
                now = datetime.now(self.moscow_tz)
                timestamp = now.timestamp()
                self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, timestamp)
                self.db.add_publication(user_id, folder_name, chat_id, status='success')
                
                logger.info(f"✅ Папка {folder_name} опубликована, ссылка сохранена")
                return True, f"✅ Папка {folder_name} опубликована"
            
            # ЕСЛИ ССЫЛКА НЕ ПОЛУЧЕНА - ЖДЕМ ВЕБХУК
            else:
                logger.info(f"⏳ Ссылка не получена сразу, ожидаем вебхук для {folder_name}")
                
                # Сохраняем в БД с пустой ссылкой (pending)
                now = datetime.now(self.moscow_tz)
                timestamp = now.timestamp()
                self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, timestamp)
                self.db.add_publication(user_id, folder_name, chat_id, status='pending')
                
                # СОХРАНЯЕМ В PENDING ДЛЯ ВЕБХУКА
                pending_key = f"{chat_id}_{folder_name}"
                self.pending_messages[pending_key] = {
                    'user_id': user_id,
                    'folder_name': folder_name,
                    'chat_id': chat_id,
                    'metadata': metadata,
                    'timestamp': timestamp
                }
                logger.info(f"📝 Добавлено в pending: {pending_key}")
                logger.info(f"📊 Всего pending записей: {len(self.pending_messages)}")
                
                return True, f"✅ Папка {folder_name} опубликована, ожидаем подтверждение"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)

    def handle_message_created(self, chat_id, message_id, user_id=None):
        """
        Обрабатывает событие message_created из вебхука.
        ОБНОВЛЯЕТ ССЫЛКУ В БД.
        """
        try:
            if not chat_id or not message_id:
                logger.warning(f"⚠️ Неполные данные: chat_id={chat_id}, message_id={message_id}")
                return False
            
            chat_id_str = str(chat_id)
            logger.info(f"📨 Обработка вебхука: chat_id={chat_id_str}, message_id={message_id}")
            logger.info(f"📊 Всего pending записей: {len(self.pending_messages)}")
            
            # ИЩЕМ В PENDING ПО chat_id
            found = False
            matching_keys = []
            
            for key, data in self.pending_messages.items():
                if data['chat_id'] == chat_id_str:
                    matching_keys.append(key)
                    found = True
                    logger.info(f"✅ Найдена pending запись: {key}")
            
            if not found:
                logger.warning(f"⚠️ Нет pending записи для chat_id {chat_id_str}")
                logger.info(f"📊 Содержимое pending: {list(self.pending_messages.keys())}")
                return False
            
            # ОБНОВЛЯЕМ ВСЕ НАЙДЕННЫЕ ЗАПИСИ
            for key in matching_keys:
                data = self.pending_messages[key]
                folder_name = data['folder_name']
                user_id_from_pending = data['user_id']
                
                # Формируем полную ссылку
                post_link = f"https://max.ru/c/{chat_id_str}/{message_id}"
                
                # ОБНОВЛЯЕМ ССЫЛКУ В БД
                self.db.update_post_link(user_id_from_pending, folder_name, post_link)
                self.db.update_publication_status(user_id_from_pending, folder_name, 'success')
                
                # Удаляем из pending
                del self.pending_messages[key]
                
                logger.info(f"✅ ОБНОВЛЕНО! Для {folder_name} получена ссылка: {post_link}")
            
            logger.info(f"✅ Обработано {len(matching_keys)} записей")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            import traceback
            traceback.print_exc()
            return False

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
