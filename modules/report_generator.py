import os
import re
import csv
from datetime import datetime
import pytz
import logging
import shutil

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
            'Код предложения': ''
        }
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            fields = {
                'Название': r'Название:\s*(.+)',
                'Ссылка': r'Ссылка:\s*(.+)',
                'Код предложения': r'Код предложения:\s*(.+)',
            }
            
            for key, pattern in fields.items():
                match = re.search(pattern, content)
                if match:
                    data[key] = match.group(1).strip()
                
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга {info_path}: {e}")
        
        return data

    def generate_report(self, user_id):
        """Генерирует отчет в CSV формате"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            
            if not os.path.exists(samosvaly_path):
                logger.warning(f"⚠️ Папка Самосвалы не найдена")
                return None
            
            moscow_tz = pytz.timezone('Europe/Moscow')
            report_data = []
            
            for folder_name in os.listdir(samosvaly_path):
                folder_path = os.path.join(samosvaly_path, folder_name)
                info_path = os.path.join(folder_path, 'info.txt')
                
                if not os.path.exists(info_path):
                    continue
                
                info = self.parse_info_file(info_path)
                pub_time = self.db.get_publication_time(user_id, folder_name)
                
                if pub_time:
                    pub_time = pub_time.astimezone(moscow_tz)
                    time_str = pub_time.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
                
                chat_id = self.fm.extract_chat_id_from_name(folder_name)
                post_link = f"https://max.ru/post/{chat_id}" if chat_id else ""
                
                report_data.append({
                    'Время по МСК МАХ': time_str,
                    'Ссылка на опубликованное объявление в МАХ': post_link,
                    'Ссылка (откуда информация)': info.get('Ссылка', ''),
                    'Марка/модель': info.get('Название', ''),
                    'Код предложения': info.get('Код предложения', ''),
                })
            
            if not report_data:
                logger.warning(f"⚠️ Нет данных для отчета")
                return None
            
            # Сохраняем в CSV (легкий, без pandas)
            report_filename = f"Отчет_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            report_path = os.path.join(user_folder, report_filename)
            
            with open(report_path, 'w', encoding='utf-8-sig', newline='') as f:
                if report_data:
                    writer = csv.DictWriter(f, fieldnames=report_data[0].keys())
                    writer.writeheader()
                    writer.writerows(report_data)
            
            logger.info(f"📊 Отчет создан: {report_path}")
            return report_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            return None

    def cleanup_user_data(self, user_id, keep_report=True):
        """Удаляет данные пользователя"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            if not os.path.exists(user_folder):
                return
            
            if keep_report:
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        logger.info(f"🗑️ Удалена папка: {item}")
                    elif not item.startswith('Отчет_'):
                        os.remove(item_path)
                        logger.info(f"🗑️ Удален файл: {item}")
            else:
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")
