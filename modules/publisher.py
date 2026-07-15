import logging
import os
import time
import re
import json
import requests
from PIL import Image
import io

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_publishes = {}  # user_id -> bool
        self.uploaded_folders = {}  # user_id -> set()
    
    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def get_sorted_images(self, folder_path, max_count=3):
        """
        Возвращает список путей к изображениям (до 3 штук)
        с проверкой на валидность изображений
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
                # Проверяем, что файл действительно изображение
                try:
                    with Image.open(img_path) as img:
                        img.verify()  # Проверяем целостность
                    images.append(img_path)
                except Exception as e:
                    logger.warning(f"⚠️ Невалидное изображение {file}: {e}")
                    continue
        
        # Сортируем и берем первые 3
        images.sort()
        return images[:max_count]
    
    def compress_image(self, image_path, max_size_mb=10):
        """
        Сжимает изображение если оно больше max_size_mb
        Возвращает bytes или None при ошибке
        """
        try:
            with Image.open(image_path) as img:
                # Конвертируем в RGB если нужно
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                
                # Сжимаем если файл большой
                file_size = os.path.getsize(image_path)
                if file_size > max_size_mb * 1024 * 1024:
                    # Уменьшаем качество
                    quality = 85
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=quality, optimize=True)
                    
                    while buffer.tell() > max_size_mb * 1024 * 1024 and quality > 30:
                        quality -= 5
                        buffer.seek(0)
                        buffer.truncate()
                        img.save(buffer, format='JPEG', quality=quality, optimize=True)
                    
                    logger.info(f"✅ Сжато изображение: {os.path.basename(image_path)} ({file_size//1024}KB -> {buffer.tell()//1024}KB)")
                    return buffer.getvalue()
                else:
                    # Возвращаем оригинал
                    with open(image_path, 'rb') as f:
                        return f.read()
        except Exception as e:
            logger.error(f"❌ Ошибка сжатия {image_path}: {e}")
            return None
    
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
    
    def publish_ad(self, user_id, folder_path, folder_name):
        """
        Публикует одно объявление в чат MAX
        Возвращает (success, message, chat_id)
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
            
            # 3. Получаем до 3 изображений
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
    
    def _send_message_with_photos(self, chat_id, text, image_paths):
        """
        Отправляет сообщение с фото в MAX API
        """
        try:
            if not self.api.token:
                logger.error("❌ Токен не установлен")
                return False
            
            # Подготавливаем файлы для отправки
            files = []
            for img_path in image_paths:
                # Сжимаем если нужно
                img_data = self.compress_image(img_path)
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
                timeout=120,
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение с фото отправлено в чат {chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {response.status_code} - {response.text}")
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
            
            self.api.send_message(user_id, f"📢 Начинаю публикацию {len(subfolders)} объявлений...")
            
            published = 0
            failed = 0
            results = []
            
            for folder_name in subfolders:
                # Проверяем состояние
                if not self.active_publishes.get(user_id, False):
                    logger.info(f"⏹️ Публикация остановлена пользователем {user_id}")
                    break
                
                folder_path = os.path.join(ads_folder, folder_name)
                
                # Публикуем
                success, message, chat_id = self.publish_ad(user_id, folder_path, folder_name)
                
                if success:
                    published += 1
                    self.uploaded_folders[user_id].add(folder_name)
                    results.append(f"✅ {folder_name} -> {chat_id}")
                else:
                    failed += 1
                    results.append(f"❌ {folder_name}: {message}")
                
                logger.info(message)
                
                # Задержка между постами
                time.sleep(2)
            
            # Завершаем публикацию
            self.active_publishes[user_id] = False
            
            # Отправляем результат
            result_text = f"📊 **Результат публикации:**\n\n"
            result_text += f"✅ Успешно: {published}\n"
            if failed > 0:
                result_text += f"❌ Ошибок: {failed}\n"
            result_text += f"\n📋 Детали:\n" + "\n".join(results[:10])
            
            if len(results) > 10:
                result_text += f"\n... и еще {len(results) - 10} объявлений"
            
            self.api.send_message(user_id, result_text)
            
            # Если есть опубликованные - предлагаем отчет
            if published > 0:
                self.api.send_message(user_id, 
                    f"📊 **Отчет готов!**\n\n"
                    f"🔗 Скачать отчет: https://maxbot.bothost.tech/report/{user_id}"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.active_publishes[user_id] = False
            self.api.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")
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
