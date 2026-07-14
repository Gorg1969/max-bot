import logging
import os
import time
import re
import json
import threading
import hashlib
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
        
        # Флаги для реальной остановки
        self.running = False
        self.stop_requested = False
        self.publish_thread = None
        
        # Защита от дубликатов
        self.published_hashes = set()
        self.hash_file = "published_hashes.json"
        self._load_published_hashes()
        
        # Состояние глобального стопа
        self.global_stop_file = "global_stop.json"
        self._load_global_stop_state()
    
    def _load_published_hashes(self):
        """Загружает хэши опубликованных объявлений"""
        try:
            if os.path.exists(self.hash_file):
                with open(self.hash_file, 'r') as f:
                    data = json.load(f)
                    self.published_hashes = set(data.get('hashes', []))
                logger.info(f"🔓 Загружено {len(self.published_hashes)} хэшей опубликованных объявлений")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки хэшей: {e}")
            self.published_hashes = set()
    
    def _save_published_hashes(self):
        """Сохраняет хэши опубликованных объявлений"""
        try:
            with open(self.hash_file, 'w') as f:
                json.dump({'hashes': list(self.published_hashes)}, f)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения хэшей: {e}")
    
    def _load_global_stop_state(self):
        """Загружает состояние глобального стопа"""
        try:
            if os.path.exists(self.global_stop_file):
                with open(self.global_stop_file, 'r') as f:
                    data = json.load(f)
                    self.global_stop = data.get('global_stop', False)
                logger.info(f"🔓 Загружено состояние глобального стопа: {self.global_stop}")
            else:
                self.global_stop = False
                self._save_global_stop_state()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки состояния: {e}")
            self.global_stop = False
    
    def _save_global_stop_state(self):
        """Сохраняет состояние глобального стопа"""
        try:
            with open(self.global_stop_file, 'w') as f:
                json.dump({'global_stop': self.global_stop}, f)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения состояния: {e}")
    
    def _get_ad_hash(self, folder_path):
        """Создает уникальный хэш объявления"""
        hasher = hashlib.md5()
        try:
            # Хэшируем содержимое info.txt
            info_path = os.path.join(folder_path, 'info.txt')
            if os.path.exists(info_path):
                with open(info_path, 'rb') as f:
                    hasher.update(f.read())
            
            # Хэшируем имена файлов изображений
            files = sorted(os.listdir(folder_path))
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    hasher.update(f.encode())
                    # Добавляем размер файла для надежности
                    file_path = os.path.join(folder_path, f)
                    if os.path.exists(file_path):
                        hasher.update(str(os.path.getsize(file_path)).encode())
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания хэша: {e}")
            return str(time.time())
        
        return hasher.hexdigest()
    
    def extract_chat_id(self, folder_name):
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def fix_image_orientation(self, img):
        """Исправляет ориентацию изображения на основе EXIF-данных"""
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            
            exif = img._getexif()
            if exif and orientation in exif:
                orientation_value = exif[orientation]
                if orientation_value == 3:
                    img = img.rotate(180, expand=True)
                elif orientation_value == 6:
                    img = img.rotate(270, expand=True)
                elif orientation_value == 8:
                    img = img.rotate(90, expand=True)
        except Exception as e:
            logger.debug(f"⚠️ Ошибка исправления ориентации: {e}")
        return img
    
    def compress_image(self, image_path, max_size_mb=0.8, quality=75):
        """Сжимает изображение с исправлением ориентации и очисткой EXIF"""
        try:
            with Image.open(image_path) as img:
                img = self.fix_image_orientation(img)
                
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                max_dimension = 1280
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
                compressed_data = buffer.getvalue()
                
                if len(compressed_data) > max_size_mb * 1024 * 1024:
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=50, optimize=True, progressive=True)
                    compressed_data = buffer.getvalue()
                
                return compressed_data
        except Exception as e:
            logger.error(f"❌ Ошибка сжатия: {e}")
            with open(image_path, 'rb') as f:
                return f.read()
    
    def get_sorted_images(self, folder_path, max_count=10):
        """Возвращает отсортированный список изображений (до 10)"""
        images = []
        if not os.path.exists(folder_path):
            return images
            
        for file in os.listdir(folder_path):
            if file.lower().endswith(('.jpg', '.jpeg', '.png')):
                if file.startswith('.'):
                    continue
                images.append(file)
        
        images.sort()
        return images[:max_count]
    
    def stop_global(self):
        """Глобальная остановка всех публикаций"""
        self.global_stop = True
        self._save_global_stop_state()
        logger.info("🛑 ГЛОБАЛЬНАЯ ОСТАНОВКА ВСЕХ ПУБЛИКАЦИЙ")
        
        # Останавливаем цикл публикации
        self.stop_publishing_loop()
        
        # Останавливаем всех пользователей
        for user_id in list(self.user_states.keys()):
            if self.user_states[user_id] == UserState.PUBLISHING:
                self.user_states[user_id] = UserState.STOPPED
                self.api.send_message(user_id, "⏹️ Публикация остановлена глобальной командой.")
        
        return True
    
    def reset_global_stop(self):
        """Сброс глобального флага остановки"""
        self.global_stop = False
        self._save_global_stop_state()
        logger.info("🔄 Глобальный флаг остановки сброшен")
        return True
    
    def start_publishing_loop(self, user_id, check_interval=60):
        """Запускает непрерывный цикл публикации новых объявлений"""
        if self.running:
            logger.warning("⚠️ Цикл публикации уже запущен")
            return False
        
        if self.global_stop:
            logger.warning(f"⚠️ Глобальная остановка активна! Публикация для {user_id} невозможна")
            self.api.send_message(user_id, "⚠️ Публикация запрещена глобальной остановкой. Выполните /reset_global")
            return False
        
        self.running = True
        self.stop_requested = False
        
        self.publish_thread = threading.Thread(
            target=self._publishing_loop,
            args=(user_id, check_interval)
        )
        self.publish_thread.daemon = True
        self.publish_thread.start()
        
        logger.info(f"🚀 Запущен цикл публикации для пользователя {user_id}")
        self.api.send_message(user_id, f"🔄 Запущен автоматический поиск новых объявлений (проверка каждые {check_interval} сек)")
        return True
    
    def stop_publishing_loop(self):
        """Останавливает цикл публикации"""
        if not self.running:
            logger.info("ℹ️ Цикл публикации не запущен")
            return False
        
        logger.info("⏹️ Остановка цикла публикации...")
        self.stop_requested = True
        self.running = False
        
        if self.publish_thread and self.publish_thread.is_alive():
            self.publish_thread.join(timeout=5)
        
        logger.info("✅ Цикл публикации остановлен")
        return True
    
    def _publishing_loop(self, user_id, check_interval):
        """Основной цикл публикации"""
        logger.info(f"🔄 Запущен цикл проверки для {user_id}")
        
        while not self.stop_requested and self.running:
            try:
                # Проверяем глобальный стоп
                if self.global_stop:
                    logger.info(f"⏹️ Глобальная остановка! Цикл прерван для {user_id}")
                    self.api.send_message(user_id, "⏹️ Цикл публикации прерван глобальной остановкой.")
                    break
                
                # Проверяем новые объявления
                new_ads = self._check_new_ads(user_id)
                
                if new_ads:
                    logger.info(f"📢 Найдено {len(new_ads)} новых объявлений для {user_id}")
                    self.api.send_message(user_id, f"📢 Найдено {len(new_ads)} новых объявлений. Начинаю публикацию...")
                    
                    for ad in new_ads:
                        if self.stop_requested or not self.running or self.global_stop:
                            break
                        self._publish_ad(user_id, ad)
                        time.sleep(2)  # Задержка между отправками
                
                # Ждем следующую проверку
                for _ in range(check_interval):
                    if self.stop_requested or not self.running or self.global_stop:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле публикации: {e}")
                time.sleep(10)  # Пауза при ошибке
        
        self.running = False
        self.api.send_message(user_id, "⏹️ Цикл публикации завершен")
        logger.info(f"⏹️ Цикл публикации для {user_id} завершен")
    
    def _check_new_ads(self, user_id):
        """Проверяет новые объявления для публикации"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            
            new_ads = []
            
            if os.path.exists(samosvaly_path) and os.path.isdir(samosvaly_path):
                for folder_name in os.listdir(samosvaly_path):
                    folder_path = os.path.join(samosvaly_path, folder_name)
                    if os.path.isdir(folder_path):
                        info_path = os.path.join(folder_path, 'info.txt')
                        if os.path.exists(info_path):
                            # Проверяем, не опубликовано ли уже
                            ad_hash = self._get_ad_hash(folder_path)
                            if ad_hash not in self.published_hashes:
                                new_ads.append(folder_name)
                                # Сразу добавляем в опубликованные, чтобы не дублировать
                                self.published_hashes.add(ad_hash)
                                self._save_published_hashes()
            
            return new_ads
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки новых объявлений: {e}")
            return []
    
    def _publish_ad(self, user_id, folder_name):
        """Публикует одно объявление"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            folder_path = os.path.join(user_folder, "Самосвалы", folder_name)
            
            if not os.path.exists(folder_path):
                return False
            
            # Читаем текст
            info_path = os.path.join(folder_path, 'info.txt')
            with open(info_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # Извлекаем chat_id
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                return False
            
            # Получаем фото
            images = self.get_sorted_images(folder_path, max_count=10)
            logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}, фото: {len(images)}")
            
            # Проверяем остановку перед отправкой
            if self.stop_requested or not self.running or self.global_stop:
                logger.info(f"⏹️ Публикация прервана для {folder_name}")
                return False
            
            photo_files = []
            for img_name in images:
                img_path = os.path.join(folder_path, img_name)
                if os.path.exists(img_path):
                    try:
                        compressed = self.compress_image(img_path)
                        photo_files.append((img_name, compressed))
                    except Exception as e:
                        logger.error(f"❌ Ошибка сжатия {img_name}: {e}")
            
            # Отправляем
            if photo_files:
                success = self.api.send_photos_to_chat(
                    chat_id=chat_id,
                    photo_files=photo_files,
                    text=text
                )
            else:
                success = self.api.send_message_to_chat(chat_id, text)
            
            if success:
                self.db.add_publication(user_id, folder_name, chat_id)
                logger.info(f"✅ Опубликовано: {folder_name}")
                return True
            else:
                logger.error(f"❌ Не удалось опубликовать: {folder_name}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            return False
    
    def start(self, user_id):
        """Запускает однократную публикацию всех объявлений (существующий метод)"""
        global GLOBAL_STOP
        
        try:
            # Проверяем глобальный стоп
            if self.global_stop:
                logger.warning(f"⚠️ Глобальная остановка активна! Публикация для {user_id} невозможна")
                self.api.send_message(user_id, "⚠️ Публикация запрещена глобальной остановкой. Выполните /reset_global")
                return False
            
            # Проверяем, не запущена ли уже публикация
            if self.user_states.get(user_id) == UserState.PUBLISHING:
                logger.warning(f"⚠️ Публикация уже запущена для пользователя {user_id}")
                self.api.send_message(user_id, "⚠️ Публикация уже запущена. Дождитесь завершения.")
                return False
            
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            
            # Устанавливаем состояние PUBLISHING
            self.user_states[user_id] = UserState.PUBLISHING
            
            user_folder = self.fm.get_user_folder(user_id)
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            
            # Получаем список подпапок
            if os.path.exists(samosvaly_path) and os.path.isdir(samosvaly_path):
                subfolders = []
                for item in os.listdir(samosvaly_path):
                    item_path = os.path.join(samosvaly_path, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            subfolders.append(item)
            else:
                subfolders = self.fm.get_subfolders(user_id)
            
            if not subfolders:
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                self.user_states[user_id] = UserState.IDLE
                return False
            
            self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
            published = 0
            
            for folder_name in subfolders:
                # Проверяем глобальный стоп
                if self.global_stop:
                    logger.info(f"⏹️ ГЛОБАЛЬНАЯ ОСТАНОВКА! Публикация прервана для {user_id}")
                    self.api.send_message(user_id, "⏹️ Публикация прервана глобальной остановкой.")
                    self.user_states[user_id] = UserState.STOPPED
                    break
                
                # Проверяем состояние пользователя
                if self.user_states.get(user_id) == UserState.STOPPED:
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                try:
                    # Проверяем, не опубликовано ли уже
                    folder_path = os.path.join(samosvaly_path, folder_name)
                    ad_hash = self._get_ad_hash(folder_path)
                    if ad_hash in self.published_hashes:
                        logger.info(f"ℹ️ Объявление {folder_name} уже было опубликовано, пропускаем")
                        continue
                    
                    info_path = os.path.join(folder_path, 'info.txt')
                    if not os.path.exists(info_path):
                        continue
                    
                    with open(info_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    chat_id = self.extract_chat_id(folder_name)
                    if not chat_id:
                        logger.warning(f"⚠️ Не удалось извлечь ID чата из {folder_name}")
                        continue
                    
                    # Получаем до 10 изображений
                    images = self.get_sorted_images(folder_path, max_count=10)
                    logger.info(f"📤 Публикация в чат {chat_id}: {folder_name}, фото: {len(images)}")
                    
                    # Проверяем глобальный стоп
                    if self.global_stop:
                        logger.info(f"⏹️ ГЛОБАЛЬНАЯ ОСТАНОВКА! Публикация прервана для {user_id}")
                        self.api.send_message(user_id, "⏹️ Публикация прервана глобальной остановкой.")
                        self.user_states[user_id] = UserState.STOPPED
                        break
                    
                    # Проверяем состояние пользователя
                    if self.user_states.get(user_id) == UserState.STOPPED:
                        break
                    
                    # Подготавливаем фото
                    photo_files = []
                    for img_name in images:
                        img_path = os.path.join(folder_path, img_name)
                        if not os.path.exists(img_path):
                            continue
                        try:
                            compressed = self.compress_image(img_path)
                            photo_files.append((img_name, compressed))
                        except Exception as e:
                            logger.error(f"❌ Ошибка сжатия {img_name}: {e}")
                    
                    # Отправляем
                    if photo_files:
                        success = self.api.send_photos_to_chat(
                            chat_id=chat_id,
                            photo_files=photo_files,
                            text=text
                        )
                    else:
                        success = self.api.send_message_to_chat(chat_id, text)
                    
                    if not success:
                        logger.error(f"❌ Не удалось отправить объявление в {chat_id}")
                        continue
                    
                    # Добавляем в опубликованные
                    self.published_hashes.add(ad_hash)
                    self._save_published_hashes()
                    
                    # Запись в БД и задержка
                    self.db.add_publication(user_id, folder_name, chat_id)
                    published += 1
                    logger.info(f"✅ Опубликовано: {folder_name}")
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка при публикации {folder_name}: {e}")
                    continue
            
            # Завершаем публикацию
            self.user_states[user_id] = UserState.IDLE
            
            if published > 0:
                self.api.send_message(user_id, f"✅ Публикация завершена! Опубликовано {published} объявлений.")
            else:
                self.api.send_message(user_id, "❌ Не удалось опубликовать ни одного объявления.")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.user_states[user_id] = UserState.IDLE
            self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")
            return False
    
    def stop(self, user_id):
        """Останавливает публикацию для конкретного пользователя"""
        current_state = self.user_states.get(user_id, UserState.IDLE)
        
        if current_state == UserState.PUBLISHING:
            self.user_states[user_id] = UserState.STOPPED
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
            self.api.send_message(user_id, "⏹️ Публикация остановлена.")
            return True
        elif current_state == UserState.STOPPED:
            logger.info(f"ℹ️ Публикация уже остановлена для пользователя {user_id}")
            self.api.send_message(user_id, "ℹ️ Публикация уже остановлена.")
            return False
        else:
            logger.info(f"ℹ️ Публикация не активна для пользователя {user_id}")
            self.api.send_message(user_id, "ℹ️ Нет активной публикации для остановки.")
            return False
