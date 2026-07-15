import logging
import os
import time
import re
from enum import Enum
from PIL import Image, ExifTags
import io

logger = logging.getLogger(__name__)

class UserState(Enum):
    IDLE = "idle"
    PUBLISHING = "publishing"
    STOPPED = "stopped"

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.user_states = {}  # user_id -> UserState
    
    def extract_chat_id(self, folder_name):
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def get_sorted_images(self, folder_path, max_count=6):
        """
        Возвращает отсортированный список изображений (максимум 6)
        """
        images = []
        if not os.path.exists(folder_path):
            return images
        
        allowed_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        
        for file in os.listdir(folder_path):
            if file.startswith('.'):
                continue
            if file.lower().endswith(allowed_extensions):
                images.append(file)
                logger.debug(f"🖼️ Найдено изображение: {file}")
        
        images.sort()
        return images[:max_count]
    
    def parse_info_file(self, info_path):
        """
        Парсит info.txt:
        - До разделителя "#изъятая" - текст для объявления
        - После разделителя - данные для отчета
        """
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            delimiter = "#изъятая"
            
            if delimiter in content:
                parts = content.split(delimiter, 1)
                ad_text = parts[0].strip()
                metadata_part = parts[1].strip() if len(parts) > 1 else ""
            else:
                ad_text = content.strip()
                metadata_part = ""
            
            metadata = {}
            if metadata_part:
                lines = metadata_part.split('\n')
                for line in lines:
                    line = line.strip()
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        if '[' in value and ']' in value and '(' in value and ')' in value:
                            import re
                            url_match = re.search(r'\(([^)]+)\)', value)
                            if url_match:
                                value = url_match.group(1)
                        metadata[key] = value
            
            return {
                'ad_text': ad_text,
                'metadata': metadata
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга info.txt: {e}")
            return {
                'ad_text': content,
                'metadata': {}
            }
    
    def start(self, user_id):
        try:
            if self.user_states.get(user_id) == UserState.PUBLISHING:
                logger.warning(f"⚠️ Публикация уже запущена")
                self.api.send_message(user_id, "⚠️ Публикация уже запущена. Дождитесь завершения.")
                return False
            
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            self.user_states[user_id] = UserState.PUBLISHING
            
            # Получаем папки из ads/
            subfolders = self.fm.get_subfolders(user_id)
            
            if not subfolders:
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                self.user_states[user_id] = UserState.IDLE
                return False
            
            self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
            published = 0
            failed = 0
            
            for folder_name in subfolders:
                if self.user_states.get(user_id) == UserState.STOPPED:
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    folder_path = self.fm.get_folder_path(user_id, folder_name)
                    
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    
                    parsed = self.parse_info_file(info_path)
                    ad_text = parsed['ad_text']
                    metadata = parsed['metadata']
                    
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    # ===== БЕРЁМ НЕ БОЛЕЕ 6 ФОТО =====
                    images = self.get_sorted_images(folder_path, max_count=6)
                    # =================================
                    
                    if self.user_states.get(user_id) == UserState.STOPPED:
                        break
                    
                    photo_files = []
                    for img_name in images:
                        img_path = os.path.join(folder_path, img_name)
                        if not os.path.exists(img_path):
                            continue
                        try:
                            with open(img_path, 'rb') as f:
                                photo_data = f.read()
                            photo_files.append((img_name, photo_data))
                            logger.info(f"📸 Подготовлено фото: {img_name} ({len(photo_data)} байт)")
                        except Exception as e:
                            logger.error(f"❌ Ошибка чтения {img_name}: {e}")
                    
                    if photo_files:
                        success = self.api.send_photos_to_chat(
                            chat_id=chat_id,
                            photo_files=photo_files,
                            text=ad_text
                        )
                    else:
                        logger.info(f"ℹ️ Нет фото для {folder_name}, отправляю только текст")
                        success = self.api.send_message_to_chat(chat_id, ad_text)
                    
                    if not success:
                        logger.error(f"❌ Не удалось отправить объявление {folder_name}")
                        failed += 1
                        continue
                    
                    self.db.add_publication(user_id, folder_name, chat_id)
                    self.db.save_ad_metadata(
                        user_id=user_id,
                        folder_name=folder_name,
                        chat_id=chat_id,
                        metadata=metadata,
                        published_at=time.time()
                    )
                    
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка при публикации {folder_name}: {e}")
                    failed += 1
                    continue
            
            self.user_states[user_id] = UserState.IDLE
            
            # Очищаем папку ТОЛЬКО ПОСЛЕ ВСЕХ ПУБЛИКАЦИЙ
            self.fm.clear_ads_folder(user_id)
            logger.info(f"🗑️ Папка ads пользователя {user_id} очищена после публикации")
            
            if published > 0:
                self.api.send_message(user_id, f"✅ Публикация завершена! Опубликовано {published} объявлений.")
                if failed > 0:
                    self.api.send_message(user_id, f"⚠️ {failed} объявлений не опубликованы (ошибки).")
            else:
                self.api.send_message(user_id, "❌ Не удалось опубликовать ни одного объявления.")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            traceback.print_exc()
            self.user_states[user_id] = UserState.IDLE
            self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")
            return False
    
    def stop(self, user_id):
        current_state = self.user_states.get(user_id, UserState.IDLE)
        if current_state == UserState.PUBLISHING:
            self.user_states[user_id] = UserState.STOPPED
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
            self.api.send_message(user_id, "⏹️ Публикация остановлена.")
            return True
        elif current_state == UserState.STOPPED:
            self.api.send_message(user_id, "ℹ️ Публикация уже остановлена.")
            return False
        else:
            self.api.send_message(user_id, "ℹ️ Нет активной публикации для остановки.")
            return False
