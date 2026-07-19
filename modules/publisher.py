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
        ИСПРАВЛЕНО: Поиск seq/token вместо ссылок из markup.
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
            'response_json': None,
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
            diagnostic['response_body'] = response.text[:5000]
            
            logger.info(f"📨 СТАТУС ОТВЕТА: {response.status_code}")
            
            if response.status_code == 200:
                message_id = None
                post_link = None
                
                try:
                    result = response.json()
                    diagnostic['response_json'] = result
                    
                    # 🔥 НОВЫЙ АЛГОРИТМ ПОИСКА ССЫЛКИ
                    
                    # Приоритет 1: Заголовок Location (абсолютный путь)
                    location = response.headers.get('Location', '')
                    if location:
                        if location.startswith('/'):
                            post_link = f"https://max.ru{location}"
                        else:
                            post_link = location
                        logger.info(f"✅ Ссылка найдена в Header Location: {post_link}")
                        return True, post_link

                    # Приоритет 2: Поле seq (числовой ID поста)
                    if isinstance(result, dict):
                        msg = result.get('message', {})
                        body = msg.get('body', {})
                        
                        if 'seq' in body:
                            message_id = str(body['seq'])
                            logger.info(f"✅ Найден seq в message.body: {message_id}")
                        elif 'seq' in result:
                            message_id = str(result['seq'])
                            logger.info(f"✅ Найден seq в root: {message_id}")
                    
                    # Если нашли числовой ID - собираем стандартную ссылку
                    if message_id:
                        final_link = f"https://max.ru/c/{chat_id_str}/{message_id}"
                        logger.info(f"🔗 ФИНАЛЬНАЯ ССЫЛКА: {final_link}")
                        
                        diagnostic['status'] = 'success'
                        diagnostic['message_id'] = message_id
                        diagnostic['post_link'] = final_link
                        self.diagnostic_log.append(diagnostic)
                        return True, final_link
                    
                    # Приоритет 3: Публичный токен (если придет вдруг alias/public_token)
                    public_token = None
                    def find_key(obj, key_name):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if k == key_name:
                                    return v
                                found = find_key(v, key_name)
                                if found: return found
                        elif isinstance(obj, list):
                            for item in obj:
                                found = find_key(item, key_name)
                                if found: return found
                        return None
                    
                    public_token = find_key(result, 'alias') or find_key(result, 'public_token')
                    if public_token and not public_token.startswith('http'):
                        final_link = f"https://max.ru/c/{chat_id_str}/{public_token}"
                        logger.info(f"🔗 Токен найден: {final_link}")
                        return True, final_link

                    # Если ничего не найдено
                    logger.warning("⚠️ Технический ID не найден в ответе.")
                    fallback_link = f"https://max.ru/c/{chat_id_str}"
                    diagnostic['status'] = 'pending'
                    diagnostic['error'] = 'ID не найден'
                    self.diagnostic_log.append(diagnostic)
                    return True, fallback_link
                        
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

    def _parse_metadata(self, metadata_text):
        """Парсит метаданные из текста после #изъятая."""
        metadata = {}
        if not metadata_text:
            return metadata
        
        fields = {
            'Название': r'Название:\s*(.+)',
            'Ссылка': r'Ссылка:\s*(.+)',           # Это ВАША ссылка на товар (источник)
            'Код предложения': r'Код предложения:\s*(.+)',
            'Цена в лизинге': r'Цена\s*[вВ]\s*лизинге:\s*(.+)',
        }
        
        for key, pattern in fields.items():
            match = re.search(pattern, metadata_text, re.IGNORECASE)
            if match:
                metadata[key] = match.group(1).strip()
        
        return metadata

    def publish_folder_with_tokens(self, user_id, folder_name, ad_text, metadata_text, image_tokens):
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
            
            success, post_link = self._send_and_get_id(chat_id, ad_text, image_tokens)
            
            if not success:
                logger.warning("⚠️ Отправка в чат не удалась, пробуем в личные сообщения...")
                success, post_link = self._send_to_user(user_id, ad_text, image_tokens)
            
            if not success:
                return False, "Не удалось отправить сообщение"
            
            # Парсим метаданные пользователя (там лежит "Ссылка" из info.txt)
            metadata = self._parse_metadata(metadata_text)
            metadata['chat_id'] = chat_id
            
            # Сохраняем link от MAX отдельно
            if post_link:
                metadata['post_link'] = post_link
                logger.info(f"🔗 Ссылка на пост сохранена: {post_link}")
            else:
                metadata['post_link'] = ''
            
            now = datetime.now(self.moscow_tz)
            timestamp = now.timestamp()
            self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, timestamp)
            
            # Определяем статус для БД
            status_db = 'success' if post_link and not post_link.endswith('mid.') else 'pending'
            self.db.add_publication(user_id, folder_name, chat_id, status=status_db)
            
            # Если ссылка временная (на сам канал), кладем в pending ожидания вебхука
            if status_db == 'pending':
                pending_key = f"{chat_id}_{folder_name}"
                self.pending_messages[pending_key] = {
                    'user_id': user_id,
                    'folder_name': folder_name,
                    'chat_id': chat_id,
                    'metadata': metadata,
                    'timestamp': timestamp
                }
                logger.info(f"📝 Добавлено в pending: {pending_key}. Всего: {len(self.pending_messages)}")
            
            logger.info(f"✅ Папка {folder_name} опубликована")
            return True, f"✅ Папка {folder_name} опубликована"
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)

    def handle_message_created(self, chat_id, message_id, user_id=None):
        try:
            if not chat_id or not message_id:
                return False
            
            chat_id_str = str(chat_id)
            logger.info(f"📨 ВЕБХУК: chat_id={chat_id_str}, message_id={message_id}")
            
            found = False
            matching_keys = []
            
            for key, data in self.pending_messages.items():
                if data['chat_id'] == chat_id_str:
                    matching_keys.append(key)
                    found = True
            
            if not found:
                logger.warning(f"⚠️ Нет pending записи для чата {chat_id_str}")
                return False
            
            for key in matching_keys:
                data = self.pending_messages[key]
                folder_name = data['folder_name']
                uid = data['user_id']
                
                # Собираем правильную ссылку при получении web_id
                new_link = f"https://max.ru/c/{chat_id_str}/{message_id}"
                
                self.db.update_post_link(uid, folder_name, new_link)
                self.db.update_publication_status(uid, folder_name, 'success')
                
                del self.pending_messages[key]
                logger.info(f"✅ Обновлена ссылка для {folder_name}: {new_link}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            return False

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
