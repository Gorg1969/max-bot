import os
import shutil
import zipfile
import re
import logging

logger = logging.getLogger(__name__)

class FileManager:
    def __init__(self, data_dir="/app/data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
    
    def get_user_folder(self, user_id):
        """Возвращает ПРЯМОЙ путь к папке пользователя"""
        user_folder = os.path.join(self.data_dir, f"user_{user_id}")
        os.makedirs(user_folder, exist_ok=True)
        return user_folder
    
    def get_ads_folder(self, user_id):
        """Возвращает ФИКСИРОВАННЫЙ путь к папке с объявлениями"""
        user_folder = self.get_user_folder(user_id)
        ads_folder = os.path.join(user_folder, "ads")
        os.makedirs(ads_folder, exist_ok=True)
        return ads_folder
    
    def is_text_file(self, file, file_name):
        """Определяет, является ли файл текстовым"""
        # По MIME типу
        if file.content_type and 'text/' in file.content_type:
            return True
        
        # По расширению
        if file_name.lower().endswith(('.txt', '.text', '.md', '.info')):
            return True
        
        # Если файл называется "info" - проверяем содержимое
        if file_name.lower() == 'info' or file_name.lower() == 'info.txt':
            try:
                # Читаем первые 1024 байта
                sample = file.stream.read(1024)
                file.stream.seek(0)
                # Если нет нулевых байтов - это текст
                if b'\x00' not in sample:
                    return True
            except:
                pass
        
        return False
    
    def save_uploaded_files_stream(self, files, user_id, append=False):
        """
        ПОТОКОВОЕ сохранение файлов с определением типа
        """
        try:
            ads_folder = self.get_ads_folder(user_id)
            
            if not append:
                if os.path.exists(ads_folder):
                    shutil.rmtree(ads_folder)
                os.makedirs(ads_folder, exist_ok=True)
            else:
                os.makedirs(ads_folder, exist_ok=True)
            
            saved_count = 0
            skipped_count = 0
            
            for file in files:
                if not file.filename:
                    continue
                if file.filename.startswith('.'):
                    continue
                
                # Определяем имя файла и папку
                rel_path = file.filename
                file_name = os.path.basename(rel_path)
                dir_name = os.path.dirname(rel_path)
                
                # Проверяем, не является ли файл текстовым
                is_text = self.is_text_file(file, file_name)
                
                # Если это текстовый файл и у него нет расширения .txt
                if is_text and not file_name.lower().endswith('.txt'):
                    new_file_name = file_name + '.txt'
                    rel_path = os.path.join(dir_name, new_file_name)
                    logger.info(f"📝 Текстовый файл переименован: {file_name} -> {new_file_name}")
                    file_name = new_file_name
                
                full_path = os.path.join(ads_folder, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                # Проверяем размер
                try:
                    file.stream.seek(0, 2)
                    file_size = file.stream.tell()
                    file.stream.seek(0)
                    
                    if file_size > 20 * 1024 * 1024:  # 20 MB
                        logger.warning(f"⚠️ Файл {file_name} слишком большой ({file_size//1024//1024}MB) - пропускаем")
                        skipped_count += 1
                        continue
                except:
                    pass
                
                # Сохраняем
                try:
                    with open(full_path, 'wb') as f:
                        while True:
                            chunk = file.stream.read(64 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                    saved_count += 1
                except Exception as e:
                    logger.error(f"❌ Ошибка сохранения {file_name}: {e}")
                    if os.path.exists(full_path):
                        os.remove(full_path)
                    continue
                finally:
                    try:
                        file.stream.close()
                    except:
                        pass
            
            logger.info(f"✅ Сохранено {saved_count} файлов ({skipped_count} пропущено)")
            return {
                'success': True, 
                'saved_count': saved_count,
                'skipped_count': skipped_count
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_subfolders(self, user_id):
        """Возвращает список подпапок с текстовыми файлами из папки ads/"""
        ads_folder = self.get_ads_folder(user_id)
        subfolders = []
        
        if not os.path.exists(ads_folder):
            logger.warning(f"⚠️ Папка ads не существует для пользователя {user_id}")
            return subfolders
        
        for root, dirs, files in os.walk(ads_folder):
            # Ищем любой текстовый файл
            for file in files:
                if file.lower().endswith('.txt') or file.lower() == 'info':
                    rel_path = os.path.relpath(root, ads_folder)
                    if rel_path != '.':
                        subfolders.append(rel_path)
                    break
        
        logger.info(f"📁 Всего найдено {len(subfolders)} папок с текстовыми файлами")
        return subfolders
    
    def get_folder_path(self, user_id, folder_name):
        """Возвращает путь к конкретной папке в ads/"""
        ads_folder = self.get_ads_folder(user_id)
        return os.path.join(ads_folder, folder_name)
    
    def clear_user_data(self, user_id):
        """Очищает данные пользователя"""
        user_folder = self.get_user_folder(user_id)
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
            os.makedirs(user_folder, exist_ok=True)
            logger.info(f"🗑️ Данные пользователя {user_id} очищены")
    
    def get_folders(self, user_id):
        """Возвращает список папок с текстовыми файлами из ads/"""
        ads_folder = self.get_ads_folder(user_id)
        folders = []
        if os.path.exists(ads_folder):
            for item in os.listdir(ads_folder):
                item_path = os.path.join(ads_folder, item)
                if os.path.isdir(item_path):
                    # Проверяем наличие текстового файла
                    for file in os.listdir(item_path):
                        if file.lower().endswith('.txt') or file.lower() == 'info':
                            folders.append(item)
                            break
        return folders
    
    def extract_chat_id_from_name(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            return f"-{match.group(1)}"
        return None
    
    def get_folder_size(self, user_id, folder_name=None):
        """Возвращает размер папки в байтах"""
        try:
            if folder_name:
                folder_path = self.get_folder_path(user_id, folder_name)
            else:
                folder_path = self.get_user_folder(user_id)
            
            if not os.path.exists(folder_path):
                return 0
            
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
            
            return total_size
        except Exception as e:
            logger.error(f"❌ Ошибка получения размера папки: {e}")
            return 0
    
    def cleanup_old_files(self, max_age_hours=24):
        """Очищает файлы старше указанного времени"""
        try:
            import time
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            deleted_count = 0
            
            for user_dir in os.listdir(self.data_dir):
                user_path = os.path.join(self.data_dir, user_dir)
                if not os.path.isdir(user_path):
                    continue
                
                dir_mtime = os.path.getmtime(user_path)
                if current_time - dir_mtime > max_age_seconds:
                    shutil.rmtree(user_path)
                    deleted_count += 1
                    logger.info(f"🗑️ Удалена старая папка: {user_dir}")
                    continue
                
                for root, dirs, files in os.walk(user_path):
                    for f in files:
                        file_path = os.path.join(root, f)
                        try:
                            file_mtime = os.path.getmtime(file_path)
                            if current_time - file_mtime > max_age_seconds:
                                os.remove(file_path)
                                deleted_count += 1
                        except:
                            continue
            
            if deleted_count > 0:
                logger.info(f"🧹 Очищено {deleted_count} старых файлов")
            
        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых файлов: {e}")
    
    def get_all_user_ids(self):
        """Возвращает список всех user_id из папок"""
        try:
            user_ids = []
            for item in os.listdir(self.data_dir):
                if item.startswith('user_'):
                    user_id_str = item.replace('user_', '')
                    try:
                        user_ids.append(int(user_id_str))
                    except:
                        continue
            return user_ids
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка пользователей: {e}")
            return []
