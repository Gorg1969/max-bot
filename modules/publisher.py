import logging
import os
import time
import re
import json
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_publishes = {}  # user_id -> bool
        self.uploaded_folders = {}  # user_id -> set()
        self.FOLDER_TIMEOUT = 60  # Максимальное время на обработку одной папки
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def get_sorted_images(self, folder_path, max_count=3):
        """
        Возвращает список изображений (до 3 штук)
        БЕЗ сжатия - клиент уже сжал!
        """
        images = []
        if not os.path.exists(folder_path):
            return images
        
        # Поддерживаемые расширения
        extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        
        for file in os.listdir(folder_path):
            if file.startswith('.'):
                continue
            if file.lower().endswith(extensions):
                img_path = os.path.join(folder_path, file)
                # Проверяем, что файл существует и не пустой
                try:
                    if os.path.getsize(img_path) > 0:
                        images.append(img_path)
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка чтения {file}: {e}")
                    continue
        
        # Сортируем и берем первые 3
        images.sort()
        return images[:max_count]
    
    def get_ad_text(self, folder_path):
        """
        Извлекает текст объявления из info.txt
        """
        info_path = os.path.join(folder_path, 'info.txt')
        if not os.path.exists(info_path):
            return None
        
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Если есть разделитель, берем текст до него
            if '#изъятая' in content:
                text = content.split('#изъятая')[0].strip()
            else:
                text = content.strip()
            
            # Обрезаем слишком длинный текст (MAX API может не принять)
            if len(text) > 4000:
                text = text[:4000] + "..."
            
            return text
        except Exception as e:
            logger.error(f"❌ Ошибка чтения info.txt: {e}")
            return None
    
    def get_ad_metadata(self, folder_path):
        """
        Извлекает метаданные из info.txt для отчета
        """
        info_path = os.path.join(folder_path, 'info.txt')
        if not os.path.exists(info_path):
            return {}
        
        metadata = {}
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            fields = {
                'Название': r'Название:\s*(.+)',
                'Ссылка': r'Ссылка:\s*(.+)',
                'Код предложения': r'Код предложения:\s*(.+)',
                'Цена в лизинге': r'Цена\s*[вВ]\s*лизинге:\s*(.+)',
            }
            
            for key, pattern in fields.items():
                match = re.search(pattern, content)
                if match:
                    metadata[key] = match.group(1).strip()
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга метаданных: {e}")
        
        return metadata
    
    def read_image_data(self, image_path):
        """
        Читает изображение без сжатия (клиент уже сжал)
        """
        try:
            with open(image_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"❌ Ошибка чтения {image_path}: {e}")
            return None
    
    def _publish_ad_safe(self, user_id, folder_path, folder_name):
        """
        Безопасная публикация с таймаутом
        """
        try:
            # 1. Получаем chat_id из названия папки
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                return False, f"Не удалось извлечь ID чата из {folder_name}", None
            
            # 2. Получаем текст объявления
            text = self.get_ad_text(folder_path)
            if not text:
                return False, f"Не найден info.txt в {folder_name}", chat_id
            
            # 3. Получаем до 3 изображений (уже сжатые клиентом)
            image_paths = self.get_sorted_images(folder_path, max_count=3)
            
            # 4. Отправляем в MAX API
            if image_paths:
                # Отправляем с фото
                success = self._send_message_with_photos(chat_id, text, image_paths)
            else:
                # Отправляем только текст
                success = self.api.send_message_to_chat(chat_id, text)
            
            if not success:
                return False, f"Не удалось отправить в чат {chat_id}", chat_id
            
            # 5. Сохраняем метаданные в БД
            metadata = self.get_ad_metadata(folder_path)
            self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, time.time())
            
            # 6. Записываем в публикации
            self.db.add_publication(user_id, folder_name, chat_id)
            
            return True, f"✅ Опубликовано: {folder_name} в чат {chat_id}", chat_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            return False, str(e), None
    
    def publish_ad_with_timeout(self, user_id, folder_path, folder_name):
        """
        Публикует с таймаутом. Если превышает 60 сек - пропускаем.
        """
        result = [None, None, None]  # success, message, chat_id
        
        def _publish():
            success, message, chat_id = self._publish_ad_safe(user_id, folder_path, folder_name)
            result[0] = success
            result[1] = message
            result[2] = chat_id
        
        # Запускаем в отдельном потоке с таймаутом
        thread = threading.Thread(target=_publish)
        thread.daemon = True
        thread.start()
        thread.join(timeout=self.FOLDER_TIMEOUT)
        
        if thread.is_alive():
            # Превышен таймаут - пропускаем папку
            logger.warning(f"⏰ Таймаут {self.FOLDER_TIMEOUT}с при обработке {folder_name}")
            return False, f"⏰ Таймаут обработки папки {folder_name}", None
        
        return result[0], result[1], result[2]
    
    def _send_message_with_photos(self, chat_id, text, image_paths):
        """
        Отправляет сообщение с фото в MAX API
        """
        try:
            if not self.api.token:
                logger.error("❌ Токен не установлен")
                return False
            
            # Подготавливаем файлы для отправки (без сжатия!)
            files = []
            for img_path in image_paths:
                img_data = self.read_image_data(img_path)
                if img_data:
                    filename = os.path.basename(img_path)
                    files.append(('file', (filename, img_data, 'image/jpeg')))
            
            if not files:
                # Если нет фото - отправляем только текст
                return self.api.send_message_to_chat(chat_id, text)
            
            # Формируем данные
            data = {
                "chat_id": chat_id,
                "text": text,
                "format": "markdown"
            }
            
            # Отправляем через requests (multipart/form-data)
            response = requests.post(
                f"{self.api.base_url}/messages",
                headers={"Authorization": self.api.token},
                data=data,
                files=files,
                timeout=60,  # Таймаут запроса 60 сек
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение с фото отправлено в чат {chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {response.status_code} - {response.text[:200]}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Таймаут отправки в чат {chat_id}")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка отправки сообщения с фото: {e}")
            return False
    
    def start(self, user_id):
        """Запускает публикацию для пользователя"""
        try:
            # Проверяем, не запущена ли уже публикация
            if self.active_publishes.get(user_id, False):
                logger.warning(f"⚠️ Публикация уже запущена для пользователя {user_id}")
                self.api.send_message(user_id, "⚠️ Публикация уже запущена. Дождитесь завершения.")
                return False
            
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            self.active_publishes[user_id] = True
            self.uploaded_folders[user_id] = set()
            
            # Получаем фиксированную папку ads/
            ads_folder = self.fm.get_ads_folder(user_id)
            
            if not os.path.exists(ads_folder):
                self.api.send_message(user_id, "❌ Нет загруженных объявлений для публикации.")
                self.active_publishes[user_id] = False
                return False
            
            # Ищем все подпапки с info.txt
            subfolders = []
            for root, dirs, files in os.walk(ads_folder):
                if 'info.txt' in files:
                    rel_path = os.path.relpath(root, ads_folder)
                    if rel_path != '.':
                        subfolders.append(rel_path)
            
            if not subfolders:
                self.api.send_message(user_id, "❌ Нет папок с объявлениями для публикации.")
                self.active_publishes[user_id] = False
                return False
            
            total_folders = len(subfolders)
            self.api.send_message(user_id, f"📢 Начинаю публикацию {total_folders} объявлений...")
            
            published = 0
            failed = 0
            timeout = 0
            results = []
            
            for idx, folder_name in enumerate(subfolders):
                # Проверяем состояние
                if not self.active_publishes.get(user_id, False):
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                folder_path = os.path.join(ads_folder, folder_name)
                
                # Логируем прогресс
                logger.info(f"📤 [{idx+1}/{total_folders}] Обработка: {folder_name}")
                
                # Публикуем с таймаутом
                success, message, chat_id = self.publish_ad_with_timeout(user_id, folder_path, folder_name)
                
                if success:
                    published += 1
                    self.uploaded_folders[user_id].add(folder_name)
                    results.append(f"✅ {folder_name} -> {chat_id}")
                    logger.info(f"✅ [{idx+1}/{total_folders}] {message}")
                else:
                    if "Таймаут" in message:
                        timeout += 1
                    else:
                        failed += 1
                    results.append(f"❌ {folder_name}: {message}")
                    logger.warning(f"❌ [{idx+1}/{total_folders}] {message}")
                
                # Задержка между постами (2 сек)
                time.sleep(2)
                
                # Обновляем статус каждые 5 папок
                if (idx + 1) % 5 == 0:
                    self.api.send_message(
                        user_id, 
                        f"📊 Прогресс: {idx+1}/{total_folders}\n"
                        f"✅ Успешно: {published}\n"
                        f"❌ Ошибок: {failed}\n"
                        f"⏰ Таймаутов: {timeout}"
                    )
            
            # Завершаем публикацию
            self.active_publishes[user_id] = False
            
            # Отправляем финальный результат
            result_text = f"📊 **Результат публикации:**\n\n"
            result_text += f"📁 Всего папок: {total_folders}\n"
            result_text += f"✅ Успешно: {published}\n"
            if failed > 0:
                result_text += f"❌ Ошибок: {failed}\n"
            if timeout > 0:
                result_text += f"⏰ Таймаутов: {timeout}\n"
            
            # Показываем первые 5 результатов
            if results:
                result_text += f"\n📋 Детали:\n" + "\n".join(results[:5])
                if len(results) > 5:
                    result_text += f"\n... и еще {len(results) - 5} объявлений"
            
            self.api.send_message(user_id, result_text)
            
            # Если есть опубликованные - предлагаем отчет
            if published > 0:
                self.api.send_message(user_id, 
                    f"📊 **Отчет готов!**\n\n"
                    f"🔗 Скачать отчет: https://maxbot.bothost.tech/report/{user_id}"
                )
            
            # Очищаем память - удаляем папку ads/
            try:
                import shutil
                if os.path.exists(ads_folder):
                    shutil.rmtree(ads_folder)
                    logger.info(f"🗑️ Папка ads/ удалена для пользователя {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка удаления ads/: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.active_publishes[user_id] = False
            self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)[:200]}")
            return False
    
    def stop(self, user_id):
        """Останавливает публикацию для конкретного пользователя"""
        if self.active_publishes.get(user_id, False):
            self.active_publishes[user_id] = False
            logger.info(f"⏹️ Публикация остановлена для пользователя {user_id}")
            self.api.send_message(user_id, "⏹️ Публикация остановлена.")
            return True
        else:
            self.api.send_message(user_id, "ℹ️ Нет активной публикации для остановки.")
            return False
    
    def is_running(self, user_id):
        """Проверяет, запущена ли публикация для пользователя"""
        return self.active_publishes.get(user_id, False)
