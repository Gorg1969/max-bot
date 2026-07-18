# modules/publisher.py

import logging
import time
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

class Publisher:
    """Класс для публикации объявлений"""
    
    def __init__(self, db, bot_token, max_token=None):
        """
        Инициализация Publisher
        
        Args:
            db: объект базы данных
            bot_token: токен Telegram бота
            max_token: токен для Max API
        """
        self.db = db
        self.bot_token = bot_token
        self.max_token = max_token
        self.STOP_FLAG = {}  # {user_id: bool}
        self.FOLDER_TIMEOUT = 300  # 5 минут
    
    def publish_single_folder(self, user_id, folder_name, ad_text, metadata_text, images_data):
        """
        Обрабатывает ОДНУ папку и сохраняет статус в БД
        """
        try:
            if self.STOP_FLAG.get(user_id, False):
                logger.info(f"⏹️ Пропускаем папку {folder_name} - остановка")
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
            
            # 2. Загружаем изображения (максимум 10)
            image_tokens = []
            max_images = min(len(images_data), 10) if isinstance(images_data, list) else 0
            
            logger.info(f"📸 Найдено {len(images_data)} изображений, загружаем максимум {max_images}")
            
            for i in range(max_images):
                if self.STOP_FLAG.get(user_id, False):
                    self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='error', error='Остановка пользователем')
                    return False, "Остановка пользователем"
                
                if time.time() - start_time > self.FOLDER_TIMEOUT:
                    error_msg = f"Таймаут обработки папки {folder_name}"
                    self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='error', error=error_msg)
                    return False, error_msg
                
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
            
            # 3. Отправляем сообщение в чат и получаем ссылку
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
            
            # 4. Сохраняем метаданные для отчета
            metadata = self._parse_metadata(metadata_text)
            
            # Добавляем ссылку на пост в метаданные
            if post_link:
                metadata['post_link'] = post_link
            else:
                chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
                metadata['post_link'] = f"https://max.ru/c/{chat_id_with_dash}"
            
            # Сохраняем метаданные
            self.db.save_ad_metadata(user_id, folder_name, f"-{chat_id}", metadata, time.time())
            
            # Добавляем успешную публикацию
            self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='success')
            
            return True, f"✅ Папка {folder_name} опубликована с {len(image_tokens)} фото"
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            
            # Сохраняем ошибку в БД
            chat_id = self.extract_chat_id(folder_name) or 'unknown'
            self.db.add_publication(user_id, folder_name, f"-{chat_id}", status='error', error=error_msg)
            
            return False, error_msg
    
    def extract_chat_id(self, folder_name: str) -> Optional[str]:
        """Извлекает chat_id из имени папки"""
        # Здесь должна быть ваша логика извлечения chat_id
        # Например, если папка называется "chat_123456"
        import re
        match = re.search(r'[-+]?\d+', folder_name)
        return match.group(0) if match else None
    
    def _upload_file_to_max(self, image_data, user_id: int) -> Optional[str]:
        """Загружает файл в Max и возвращает токен"""
        # Здесь должна быть ваша логика загрузки в Max
        # Пока возвращаем заглушку
        return f"token_{hash(image_data)}"
    
    def _send_to_chat(self, chat_id: str, text: str, image_tokens: List[str]) -> Tuple[bool, Optional[str]]:
        """Отправляет сообщение в чат"""
        # Здесь должна быть ваша логика отправки в чат
        return True, f"https://max.ru/c/{chat_id}"
    
    def _send_to_user(self, user_id: int, text: str, image_tokens: List[str]) -> Tuple[bool, Optional[str]]:
        """Отправляет сообщение пользователю"""
        # Здесь должна быть ваша логика отправки пользователю
        return True, None
    
    def _parse_metadata(self, metadata_text: str) -> dict:
        """Парсит метаданные из текста"""
        # Здесь должна быть ваша логика парсинга метаданных
        return {"text": metadata_text}
