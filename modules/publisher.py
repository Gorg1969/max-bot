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
        self.pending_messages = {}
        self.diagnostic_log = []

    def extract_chat_id_from_folder(self, folder_name):
        if not folder_name:
            return None
        
        match = re.search(r'(-?\d{10,})', folder_name)
        if match:
            chat_id = match.group(1)
            if not chat_id.startswith('-') and len(chat_id) >= 10:
                chat_id = f"-{chat_id}"
            return chat_id
        
        match = re.search(r'(\d{10,})', folder_name)
        if match:
            return f"-{match.group(1)}"
        
        return None

    def _send_and_get_id(self, chat_id, text, image_tokens):
        """
        Отправляет сообщение в чат и получает ID из ответа API.
        """
        diagnostic = {
            'timestamp': datetime.now().isoformat(),
            'chat_id': chat_id,
            'text_length': len(text),
            'image_count': len(image_tokens),
            'status': None,
            'message_id': None,
            'post_link': None,
            'error': None,
            'response_status': None,
            'response_headers': None,
            'response_body': None,
            'response_json': None
        }
        
        try:
            if not self.api.token:
                diagnostic['error'] = 'Нет токена API'
                self.diagnostic_log.append(diagnostic)
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
            
            diagnostic['response_status'] = response.status_code
            diagnostic['response_headers'] = dict(response.headers)
            diagnostic['response_body'] = response.text[:2000]
            
            logger.info(f"📨 СТАТУС ОТВЕТА: {response.status_code}")
            
            if response.status_code == 200:
                message_id = None
                post_link = None
                
                try:
                    result = response.json()
                    diagnostic['response_json'] = result
                    logger.info(f"📨 JSON ОТВЕТА: {json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
                    
                    # 🔥 ИЩЕМ ID ВО ВСЕХ ВОЗМОЖНЫХ МЕСТАХ
                    if isinstance(result, dict):
                        # Вариант 1: message.body.mid (основной) - используем ПОЛНЫЙ mid
                        if 'message' in result and isinstance(result['message'], dict):
                            msg = result['message']
                            if 'body' in msg and isinstance(msg['body'], dict):
                                if 'mid' in msg['body']:
                                    message_id = msg['body']['mid']  # Сохраняем ПОЛНОСТЬЮ, включая "mid."
                                    logger.info(f"✅ Найден ID в message.body.mid: {message_id}")
                        
                        # Вариант 2: data.mid
                        if not message_id and 'data' in result and isinstance(result['data'], dict):
                            if 'mid' in result['data']:
                                message_id = result['data']['mid']
                                logger.info(f"✅ Найден ID в data.mid: {message_id}")
                        
                        # Вариант 3: прямые поля
                        if not message_id and 'mid' in result:
                            message_id = result['mid']
                            logger.info(f"✅ Найден ID в mid: {message_id}")
                        
                        # Вариант 4: message_id
                        if not message_id and 'message_id' in result:
                            message_id = str(result['message_id'])
                            logger.info(f"✅ Найден ID в message_id: {message_id}")
                        
                        # Вариант 5: id
                        if not message_id and 'id' in result:
                            message_id = str(result['id'])
                            logger.info(f"✅ Найден ID в id: {message_id}")
                    
                    # Проверяем Location заголовок
                    if not message_id:
                        location = response.headers.get('Location', '')
                        if location:
                            logger.info(f"📍 Location: {location}")
                            match = re.search(r'/([a-fA-F0-9.]+)$', location)
                            if match:
                                message_id = match.group(1)
                                logger.info(f"✅ Найден ID в Location: {message_id}")
                    
                    # Если ID найден - создаем ссылку
                    if message_id:
                        post_link = f"https://max.ru/c/{chat_id_str}/{message_id}"
                        logger.info(f"🔗 Ссылка создана: {post_link}")
                        
                        diagnostic['status'] = 'success'
                        diagnostic['message_id'] = message_id
                        diagnostic['post_link'] = post_link
                        self.diagnostic_log.append(diagnostic)
                        
                        return True, post_link
                    else:
                        logger.warning(f"⚠️ ID НЕ НАЙДЕН в ответе!")
                        logger.warning(f"⚠️ Полный ответ: {response.text[:500]}")
                        
                        diagnostic['status'] = 'failed'
                        diagnostic['error'] = 'ID не найден в ответе API'
                        self.diagnostic_log.append(diagnostic)
                        
                        # Фолбэк - ссылка на чат
                        post_link = f"https://max.ru/c/{chat_id_str}"
                        logger.info(f"🔗 Используем ссылку на чат: {post_link}")
                        return True, post_link
                        
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Ошибка парсинга JSON: {e}")
                    diagnostic['status'] = 'failed'
                    diagnostic['error'] = f'JSONDecodeError: {e}'
                    self.diagnostic_log.append(diagnostic)
                    return True, None
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки ответа: {e}")
                    import traceback
                    traceback.print_exc()
                    diagnostic['status'] = 'failed'
                    diagnostic['error'] = str(e)
                    self.diagnostic_log.append(diagnostic)
                    return True, None
            else:
                logger.error(f"❌ Ошибка API: {response.status_code}")
                diagnostic['status'] = 'failed'
                diagnostic['error'] = f'HTTP {response.status_code}'
                self.diagnostic_log.append(diagnostic)
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
            diagnostic['status'] = 'failed'
            diagnostic['error'] = str(e)
            self.diagnostic_log.append(diagnostic)
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
            
            logger.info(f"📤 Отправка пользователю {user_id}")
            
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
                    
                    if 'message' in result and isinstance(result['message'], dict):
                        msg = result['message']
                        if 'body' in msg and isinstance(msg['body'], dict):
                            if 'mid' in msg['body']:
                                message_id = msg['body']['mid']
                    elif 'data' in result and isinstance(result['data'], dict):
                        if 'mid' in result['data']:
                            message_id = result['data']['mid']
                    elif 'mid' in result:
                        message_id = result['mid']
                    
                    if message_id:
                        post_link = f"https://max.ru/c/{user_id}/{message_id}"
                    else:
                        post_link = None
                except:
                    post_link = None
                
                if not post_link:
                    post_link = f"https://max.ru/c/{user_id}"
                
                logger.info(f"✅ Отправлено пользователю {user_id}, ссылка: {post_link}")
                return True, post_link
            else:
                logger.error(f"❌ Ошибка: {response.status_code}")
                return False, None
                
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return False, None

    def _parse_metadata(self, metadata_text):
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
        """
        try:
            if self.STOP_FLAG.get(user_id, False):
                logger.info(f"⏹️ Пропускаем папку {folder_name} - остановка")
                return False, "Остановка пользователем"
            
            chat_id = self.extract_chat_id_from_folder(folder_name)
            
            if not chat_id:
                logger.error(f"❌ Не удалось извлечь chat_id из: {folder_name}")
                return False, f"Не удалось извлечь chat_id из {folder_name}"
            
            logger.info(f"📤 Извлечен chat_id: {chat_id}")
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
            
            # Если ссылка получена
            if post_link:
                metadata['post_link'] = post_link
                now = datetime.now(self.moscow_tz)
                timestamp = now.timestamp()
                self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, timestamp)
                self.db.add_publication(user_id, folder_name, chat_id, status='success')
                logger.info(f"✅ Папка {folder_name} опубликована, ссылка: {post_link}")
                return True, f"✅ Папка {folder_name} опубликована"
            
            # Если ссылка не получена
            else:
                logger.warning(f"⚠️ Ссылка НЕ ПОЛУЧЕНА для {folder_name}")
                now = datetime.now(self.moscow_tz)
                timestamp = now.timestamp()
                self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, timestamp)
                self.db.add_publication(user_id, folder_name, chat_id, status='pending')
                
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
        Обрабатывает вебхук message_created.
        Обновляет ссылку в БД.
        """
        try:
            if not chat_id or not message_id:
                return False
            
            chat_id_str = str(chat_id)
            logger.info(f"📨 ВЕБХУК: chat_id={chat_id_str}, message_id={message_id}")
            logger.info(f"📊 Всего pending записей: {len(self.pending_messages)}")
            
            found = False
            matching_keys = []
            
            for key, data in self.pending_messages.items():
                if data['chat_id'] == chat_id_str:
                    matching_keys.append(key)
                    found = True
            
            if not found:
                logger.warning(f"⚠️ Нет pending записи для chat_id {chat_id_str}")
                return False
            
            for key in matching_keys:
                data = self.pending_messages[key]
                folder_name = data['folder_name']
                user_id_from_pending = data['user_id']
                
                post_link = f"https://max.ru/c/{chat_id_str}/{message_id}"
                
                self.db.update_post_link(user_id_from_pending, folder_name, post_link)
                self.db.update_publication_status(user_id_from_pending, folder_name, 'success')
                
                del self.pending_messages[key]
                logger.info(f"✅ Обновлена ссылка для {folder_name}: {post_link}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            return False

    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, images_data):
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
        logger.info(f"⏹️ Остановка для пользователя {user_id}")
        self.STOP_FLAG[user_id] = True
        
        try:
            user_folder = self.fm.get_user_folder(user_id)
            if os.path.exists(user_folder):
                import shutil
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
        except Exception as e:
            logger.error(f"❌ Ошибка удаления: {e}")
        
        def reset_stop_flag():
            time.sleep(5)
            self.STOP_FLAG[user_id] = False
        
        threading.Thread(target=reset_stop_flag, daemon=True).start()
        return True

    def is_running(self, user_id):
        return self.STOP_FLAG.get(user_id, False)
    
    def get_diagnostic_log(self):
        return self.diagnostic_log
    
    def clear_diagnostic_log(self):
        self.diagnostic_log = []
        logger.info("🧹 Диагностический журнал очищен")
