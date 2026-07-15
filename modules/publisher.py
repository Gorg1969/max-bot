import logging
import os
import time
import re
import json
import requests
import threading

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, api, file_manager, db):
        self.api = api
        self.fm = file_manager
        self.db = db
        self.active_publishes = {}  # user_id -> bool
        self.uploaded_folders = {}  # user_id -> set()
        self.FOLDER_TIMEOUT = 60
    
    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def extract_folder_number(self, folder_name):
        """Извлекает порядковый номер папки"""
        match = re.match(r'^(\d+)', folder_name)
        if match:
            return match.group(1)
        match = re.search(r'/(\d+)\s*-', folder_name)
        if match:
            return match.group(1)
        return None
    
    def get_sorted_images(self, folder_path, max_count=3):
        """Возвращает список изображений (до 3 штук)"""
        images = []
        if not os.path.exists(folder_path):
            return images
        
        extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        
        for file in os.listdir(folder_path):
            if file.startswith('.'):
                continue
            if file.lower().endswith(extensions):
                img_path = os.path.join(folder_path, file)
                try:
                    if os.path.getsize(img_path) > 0:
                        images.append(img_path)
                except Exception:
                    continue
        
        images.sort()
        return images[:max_count]
    
    def get_txt_file(self, folder_path):
        """
        Находит текстовый файл в папке
        Ищет файлы с расширением .txt и файл 'info' без расширения
        """
        if not os.path.exists(folder_path):
            return None
        
        try:
            for file in os.listdir(folder_path):
                file_path = os.path.join(folder_path, file)
                
                # Пропускаем изображения
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                    continue
                
                # Проверяем, что файл не слишком большой
                try:
                    size = os.path.getsize(file_path)
                    if size == 0 or size > 1024 * 1024:  # Пустой или > 1MB
                        continue
                except:
                    continue
                
                # Если файл с расширением .txt
                if file.lower().endswith('.txt'):
                    logger.info(f"📄 Найден .txt файл: {file}")
                    return file_path
                
                # Если файл называется 'info' (без расширения)
                if file.lower() == 'info':
                    logger.info(f"📄 Найден файл info: {file}")
                    return file_path
                
                # Пробуем прочитать как текстовый файл
                try:
                    with open(file_path, 'rb') as f:
                        content = f.read(1024)
                        # Если нет нулевых байтов - это текстовый файл
                        if b'\x00' not in content:
                            try:
                                text_content = content.decode('utf-8', errors='ignore')
                                # Если есть хотя бы одно слово или #изъятая - это наш файл
                                if any(c.isalpha() for c in text_content) or '#изъятая' in text_content:
                                    logger.info(f"📄 Найден текстовый файл: {file}")
                                    return file_path
                            except:
                                pass
                except:
                    pass
        except:
            pass
        
        return None
    
    def get_ad_text(self, folder_path):
        """
        Извлекает текст объявления из текстового файла
        Текст до #изъятая - тело объявления
        """
        txt_file = self.get_txt_file(folder_path)
        if not txt_file:
            logger.warning(f"⚠️ Не найден текстовый файл в {folder_path}")
            return None
        
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Разделитель #изъятая
            if '#изъятая' in content:
                text = content.split('#изъятая')[0].strip()
            else:
                text = content.strip()
            
            logger.info(f"📝 Текст объявления: {len(text)} символов")
            return text
            
        except Exception as e:
            logger.error(f"❌ Ошибка чтения {txt_file}: {e}")
            return None
    
    def get_ad_metadata(self, folder_path):
        """
        Извлекает метаданные из текстового файла (после #изъятая)
        """
        txt_file = self.get_txt_file(folder_path)
        if not txt_file:
            return {}
        
        metadata = {}
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Ищем метаданные после разделителя
            if '#изъятая' in content:
                parts = content.split('#изъятая')
                if len(parts) > 1:
                    metadata_content = parts[1].strip()
                    
                    fields = {
                        'Название': r'Название:\s*(.+)',
                        'Ссылка': r'Ссылка:\s*(.+)',
                        'Код предложения': r'Код предложения:\s*(.+)',
                        'Цена в лизинге': r'Цена\s*[вВ]\s*лизинге:\s*(.+)',
                    }
                    
                    for key, pattern in fields.items():
                        match = re.search(pattern, metadata_content)
                        if match:
                            metadata[key] = match.group(1).strip()
        
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга метаданных: {e}")
        
        return metadata
    
    def read_image_data(self, image_path):
        """Читает изображение"""
        try:
            with open(image_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"❌ Ошибка чтения {image_path}: {e}")
            return None
    
    def _send_message_with_photos(self, chat_id, text, image_paths):
        """Отправляет сообщение с фото в MAX API"""
        try:
            if not self.api.token:
                logger.error("❌ Токен не установлен")
                return False
            
            files = []
            for img_path in image_paths:
                img_data = self.read_image_data(img_path)
                if img_data:
                    filename = os.path.basename(img_path)
                    files.append(('file', (filename, img_data, 'image/jpeg')))
            
            data = {
                "chat_id": chat_id,
                "text": text
            }
            
            response = requests.post(
                f"{self.api.base_url}/messages",
                headers={"Authorization": self.api.token},
                data=data,
                files=files,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение отправлено в чат {chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {response.status_code} - {response.text[:200]}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Таймаут отправки в чат {chat_id}")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def _send_message_only(self, chat_id, text):
        """Отправляет только текст"""
        try:
            if not self.api.token:
                return False
            
            payload = {
                "chat_id": chat_id,
                "text": text,
                "format": "markdown"
            }
            
            response = requests.post(
                f"{self.api.base_url}/messages",
                headers={
                    "Authorization": self.api.token,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=30,
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Текст отправлен в чат {chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки текста: {response.status_code} - {response.text[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки текста: {e}")
            return False
    
    def publish_ad(self, user_id, folder_path, folder_name):
        """Публикует одно объявление"""
        try:
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                return False, f"Не удалось извлечь ID чата из {folder_name}", None
            
            folder_num = self.extract_folder_number(folder_name) or folder_name
            logger.info(f"📤 Публикация папки #{folder_num} в чат {chat_id}")
            
            # Получаем текст
            text = self.get_ad_text(folder_path)
            if not text:
                return False, f"Не найден текстовый файл в {folder_name}", chat_id
            
            # Получаем изображения (до 3)
            image_paths = self.get_sorted_images(folder_path, max_count=3)
            logger.info(f"🖼️ Найдено {len(image_paths)} изображений")
            
            # Отправляем
            if image_paths:
                success = self._send_message_with_photos(chat_id, text, image_paths)
            else:
                success = self._send_message_only(chat_id, text)
            
            if not success:
                return False, f"Не удалось отправить в чат {chat_id}", chat_id
            
            # Сохраняем метаданные
            metadata = self.get_ad_metadata(folder_path)
            self.db.save_ad_metadata(user_id, folder_name, chat_id, metadata, time.time())
            self.db.add_publication(user_id, folder_name, chat_id)
            
            return True, f"✅ Папка #{folder_num} опубликована в чат {chat_id}", chat_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации {folder_name}: {e}")
            return False, str(e), None
    
    def start(self, user_id):
        """Запускает публикацию"""
        try:
            if self.active_publishes.get(user_id, False):
                self.api.send_message(user_id, "⚠️ Публикация уже запущена.")
                return False
            
            logger.info(f"🚀 Запуск публикации для пользователя {user_id}")
            self.active_publishes[user_id] = True
            
            ads_folder = self.fm.get_ads_folder(user_id)
            
            if not os.path.exists(ads_folder):
                self.api.send_message(user_id, "❌ Нет загруженных объявлений.")
                self.active_publishes[user_id] = False
                return False
            
            # Собираем все папки с текстовыми файлами
            subfolders = []
            for root, dirs, files in os.walk(ads_folder):
                # Проверяем наличие текстового файла
                for file in files:
                    if file.lower().endswith('.txt') or file.lower() == 'info':
                        rel_path = os.path.relpath(root, ads_folder)
                        if rel_path != '.':
                            subfolders.append(rel_path)
                        break
            
            if not subfolders:
                self.api.send_message(user_id, "❌ Нет папок с текстовыми файлами.")
                self.active_publishes[user_id] = False
                return False
            
            total = len(subfolders)
            self.api.send_message(user_id, f"📢 Начинаю публикацию {total} объявлений...")
            
            published = 0
            failed = 0
            results = []
            
            for idx, folder_name in enumerate(subfolders):
                if not self.active_publishes.get(user_id, False):
                    logger.info(f"⏹️ Остановлено пользователем {user_id}")
                    break
                
                folder_path = os.path.join(ads_folder, folder_name)
                logger.info(f"📤 [{idx+1}/{total}] Обработка: {folder_name}")
                
                success, message, chat_id = self.publish_ad(user_id, folder_path, folder_name)
                
                if success:
                    published += 1
                    results.append(f"✅ {folder_name}")
                    logger.info(f"✅ [{idx+1}/{total}] {message}")
                else:
                    failed += 1
                    results.append(f"❌ {folder_name}: {message}")
                    logger.warning(f"❌ [{idx+1}/{total}] {message}")
                
                time.sleep(2)
            
            self.active_publishes[user_id] = False
            
            result_text = f"📊 **Результат публикации:**\n\n"
            result_text += f"📁 Всего папок: {total}\n"
            result_text += f"✅ Успешно: {published}\n"
            if failed > 0:
                result_text += f"❌ Ошибок: {failed}\n"
            
            if results:
                result_text += f"\n📋 Детали:\n" + "\n".join(results[:10])
                if len(results) > 10:
                    result_text += f"\n... и еще {len(results) - 10} объявлений"
            
            self.api.send_message(user_id, result_text)
            
            if published > 0:
                self.api.send_message(user_id, 
                    f"📊 **Отчет готов!**\n\n"
                    f"🔗 Скачать отчет: https://maxbot.bothost.tech/report/{user_id}"
                )
            
            # Очищаем папку ads/
            try:
                import shutil
                if os.path.exists(ads_folder):
                    shutil.rmtree(ads_folder)
                    logger.info(f"🗑️ Папка ads/ удалена")
            except Exception as e:
                logger.error(f"❌ Ошибка удаления ads/: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            import traceback
            traceback.print_exc()
            self.active_publishes[user_id] = False
            self.api.send_message(user_id, f"❌ Ошибка: {str(e)[:200]}")
            return False
    
    def stop(self, user_id):
        """Останавливает публикацию"""
        if self.active_publishes.get(user_id, False):
            self.active_publishes[user_id] = False
            logger.info(f"⏹️ Публикация остановлена для {user_id}")
            self.api.send_message(user_id, "⏹️ Публикация остановлена.")
            return True
        else:
            self.api.send_message(user_id, "ℹ️ Нет активной публикации.")
            return False
    
    def is_running(self, user_id):
        return self.active_publishes.get(user_id, False)
