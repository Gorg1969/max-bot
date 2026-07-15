import os
import re
import csv
import shutil
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, file_manager, db):
        self.fm = file_manager
        self.db = db
    
    def parse_info_file(self, info_path):
        """Парсит info.txt и извлекает нужные поля"""
        data = {
            'Название': '',
            'Ссылка': '',
            'Код предложения': '',
            'Цена в лизинге': '',
            'Полный текст': ''
        }
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
                    data[key] = match.group(1).strip()
            
            # Полный текст объявления
            if '#изъятая' in content:
                data['Полный текст'] = content.split('#изъятая')[0].strip()
            else:
                data['Полный текст'] = content.strip()
                
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга {info_path}: {e}")
        
        return data
    
    def count_images_in_folder(self, folder_path):
        """Подсчитывает количество изображений в папке"""
        count = 0
        extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        
        if os.path.exists(folder_path):
            for file in os.listdir(folder_path):
                if file.startswith('.'):
                    continue
                if file.lower().endswith(extensions):
                    count += 1
        
        return count
    
    def generate_report(self, user_id):
        """Генерирует отчет в CSV формате и удаляет временные папки"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            ads_folder = self.fm.get_ads_folder(user_id)
            
            if not os.path.exists(ads_folder):
                logger.warning(f"⚠️ Папка ads не найдена для пользователя {user_id}")
                return None
            
            moscow_tz = pytz.timezone('Europe/Moscow')
            report_data = []
            
            # Рекурсивно ищем все папки с info.txt
            for root, dirs, files in os.walk(ads_folder):
                if 'info.txt' in files:
                    # Получаем имя папки относительно ads/
                    folder_name = os.path.relpath(root, ads_folder)
                    if folder_name == '.':
                        continue
                    
                    logger.info(f"📄 Обработка папки: {folder_name}")
                    
                    info_path = os.path.join(root, 'info.txt')
                    info = self.parse_info_file(info_path)
                    
                    # Получаем время публикации из БД
                    pub_time = self.db.get_publication_time(user_id, folder_name)
                    
                    if pub_time:
                        if isinstance(pub_time, str):
                            pub_time = datetime.fromisoformat(pub_time)
                        pub_time = pub_time.astimezone(moscow_tz)
                        time_str = pub_time.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        time_str = datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Формируем ссылку на пост
                    chat_id = self.fm.extract_chat_id_from_name(folder_name)
                    post_link = f"https://max.ru/post/{chat_id}" if chat_id else ""
                    
                    # Считаем количество фото
                    photo_count = self.count_images_in_folder(root)
                    
                    report_data.append({
                        '№': len(report_data) + 1,
                        'Папка': folder_name,
                        'Время публикации (МСК)': time_str,
                        'Ссылка на пост': post_link,
                        'Ссылка (источник)': info.get('Ссылка', ''),
                        'Марка/модель': info.get('Название', ''),
                        'Код предложения': info.get('Код предложения', ''),
                        'Цена в лизинге': info.get('Цена в лизинге', ''),
                        'Количество фото': photo_count,
                        'Текст объявления': info.get('Полный текст', '')[:200] + '...' if len(info.get('Полный текст', '')) > 200 else info.get('Полный текст', '')
                    })
            
            if not report_data:
                logger.warning(f"⚠️ Нет данных для отчета пользователя {user_id}")
                return None
            
            # Сохраняем в CSV
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.csv"
            report_path = os.path.join(user_folder, report_filename)
            
            with open(report_path, 'w', encoding='utf-8-sig', newline='') as f:
                if report_data:
                    writer = csv.DictWriter(f, fieldnames=report_data[0].keys())
                    writer.writeheader()
                    writer.writerows(report_data)
            
            logger.info(f"📊 Отчет создан: {report_path} ({len(report_data)} записей)")
            
            # ✅ Удаляем временную папку ads/ после создания отчета
            self.cleanup_user_data(user_id, keep_report=True)
            
            return report_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def cleanup_user_data(self, user_id, keep_report=True):
        """Удаляет временные данные пользователя, но сохраняет отчет"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            if not os.path.exists(user_folder):
                return
            
            if keep_report:
                # Удаляем ВСЕ папки, кроме файлов отчетов
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        logger.info(f"🗑️ Удалена папка: {item}")
                    elif not item.startswith('Отчет_'):
                        os.remove(item_path)
                        logger.info(f"🗑️ Удален файл: {item}")
                    else:
                        logger.info(f"ℹ️ Отчет сохранен: {item}")
            else:
                # Удаляем всё
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")
