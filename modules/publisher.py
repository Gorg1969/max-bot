# modules/publisher.py
import logging
import time
import re
import json
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, db, bot_token, max_token=None, api=None):
        self.db = db
        self.bot_token = bot_token
        self.max_token = max_token
        self.api = api
        self.STOP_FLAG = {}
        self.FOLDER_TIMEOUT = 300

    def stop(self, user_id):
        self.STOP_FLAG[user_id] = True
        logger.info(f"⏹️ Остановка для {user_id}")
        return True

    def reset_stop(self, user_id):
        self.STOP_FLAG[user_id] = False
        logger.info(f"🔄 Сброс остановки для {user_id}")
        return True

    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, images_data):
        try:
            if self.STOP_FLAG.get(user_id, False):
                self.db.add_publication(user_id, folder_name, 'stopped', status='error', error='Остановка пользователем')
                return False, "Остановка пользователем"

            start_time = time.time()
            
            # 1. Извлекаем chat_id
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                error_msg = f"Не удалось извлечь chat_id из {folder_name}"
                logger.error(f"❌ {error_msg}")
                self.db.add_publication(user_id, folder_name, 'unknown', status='error', error=error_msg)
                return False, error_msg

            logger.info(f"📤 Извлечен chat_id: {chat_id}")

            # 2. Загружаем изображения (максимум 3)
            image_tokens = []
            max_images = min(len(images_data), 3) if isinstance(images_data, list) else 0
            
            logger.info(f"📸 Найдено {len(images_data)} изображений, загружаем максимум {max_images}")

            for i in range(max_images):
                if self.STOP_FLAG.get(user_id, False):
                    self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='error', error='Остановка пользователем')
                    return False, "Остановка пользователем"
                
                if time.time() - start_time > self.FOLDER_TIMEOUT:
                    error_msg = f"Таймаут обработки папки {folder_name}"
                    self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='error', error=error_msg)
                    return False, error_msg

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

            # 3. Отправляем сообщение в чат
            post_link = None
            if image_tokens:
                success, post_link = self._send_to_chat(chat_id, ad_text, image_tokens)
            else:
                logger.info(f"📤 Отправка только текста в чат {chat_id}")
                success, post_link = self._send_to_chat(chat_id, ad_text, [])

            # Если не удалось отправить в чат, пробуем в личные сообщения
            if not success:
                logger.warning("⚠️ Отправка в чат не удалась, пробуем в личные сообщения...")
                if image_tokens:
                    success, _ = self._send_to_user(user_id, ad_text, image_tokens)
                else:
                    success, _ = self._send_to_user(user_id, ad_text, [])

            if not success:
                error_msg = "Не удалось отправить сообщение"
                self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='error', error=error_msg)
                return False, error_msg

            # 4. Сохраняем метаданные
            metadata = self._parse_metadata(metadata_text)
            
            if post_link:
                metadata['post_link'] = post_link
            else:
                chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
                metadata['post_link'] = f"https://max.ru/c/{chat_id_with_dash}"

            self.db.save_ad_metadata(user_id, folder_name, f"-{chat_id}", metadata, time.time())
            self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='success')

            return True, f"✅ Папка {folder_name} опубликована с {len(image_tokens)} фото"

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            
            chat_id = self.extract_chat_id(folder_name) or 'unknown'
            self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='error', error=error_msg)
            
            return False, error_msg

    def extract_chat_id(self, folder_name: str) -> Optional[str]:
        """Извлекает chat_id из имени папки"""
        if not folder_name:
            return None
        
        # Ищем формат с дефисом: "1 -123456789"
        match = re.search(r'(\d+)\s*-\s*(\d+)', folder_name)
        if match:
            return match.group(2)
        
        # Ищем любое число
        match = re.search(r'(\d+)', folder_name)
        return match.group(1) if match else None

    def _upload_file_to_max(self, image_data, user_id: int) -> Optional[str]:
        """Загружает файл в Max и возвращает токен"""
        try:
            if not self.api:
                logger.error("❌ API клиент не установлен")
                return None

            # Извлекаем данные изображения
            if isinstance(image_data, dict):
                data = image_data.get('data')
                if isinstance(data, list):
                    image_bytes = bytes(data)
                elif isinstance(data, bytes):
                    image_bytes = data
                elif isinstance(data, str):
                    if data.startswith('data:image'):
                        import base64
                        data_parts = data.split(',')
                        if len(data_parts) > 1:
                            image_bytes = base64.b64decode(data_parts[1])
                        else:
                            image_bytes = base64.b64decode(data)
                    else:
                        image_bytes = data.encode()
                else:
                    return None
                
                filename = image_data.get('name', 'image.jpg')
                return self.api.upload_file(image_bytes, filename)
            
            elif isinstance(image_data, bytes):
                return self.api.upload_file(image_data, 'image.jpg')
            
            return None

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки изображения: {e}")
            return None

    def _send_to_chat(self, chat_id: str, text: str, image_tokens: List[str]) -> Tuple[bool, Optional[str]]:
        """Отправляет сообщение в чат"""
        try:
            if not self.api:
                logger.error("❌ API клиент не установлен")
                return False, None

            if not chat_id:
                logger.error("❌ Нет chat_id для отправки")
                return False, None

            if image_tokens:
                success = self.api.send_message_with_attachments(chat_id, text, image_tokens)
            else:
                success = self.api.send_message_to_chat(chat_id, text)

            if success:
                chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
                post_link = f"https://max.ru/c/{chat_id_with_dash}"
                logger.info(f"✅ Сообщение отправлено в чат {chat_id}")
                return True, post_link

            return False, None

        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False, None

    def _send_to_user(self, user_id: int, text: str, image_tokens: List[str]) -> Tuple[bool, Optional[str]]:
        """Отправляет сообщение пользователю"""
        try:
            if not self.api:
                logger.error("❌ API клиент не установлен")
                return False, None

            # Если есть фото, отправляем с вложениями
            if image_tokens:
                attachments = [{"type": "image", "payload": {"token": t}} for t in image_tokens[:3]]
                success = self.api.send_message(user_id, text, attachments)
            else:
                success = self.api.send_message(user_id, text)

            if success:
                logger.info(f"✅ Сообщение отправлено пользователю {user_id}")
                return True, None

            return False, None

        except Exception as e:
            logger.error(f"❌ Ошибка отправки пользователю: {e}")
            return False, None

    def _parse_metadata(self, metadata_text: str) -> dict:
        """Парсит метаданные из текста"""
        try:
            if metadata_text and metadata_text.strip().startswith('{'):
                return json.loads(metadata_text)
        except:
            pass

        metadata = {}
        if metadata_text:
            lines = metadata_text.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                for separator in [': ', ':', '= ', '=', ' - ']:
                    if separator in line:
                        parts = line.split(separator, 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip()
                            metadata[key] = value
                            break

        return metadata

    def get_queue_status(self, user_id):
        """Получает статус очереди для пользователя"""
        return {
            'stop_flag': self.STOP_FLAG.get(user_id, False)
        }
