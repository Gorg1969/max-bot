# modules/max_client.py
import os
import re
import pandas as pd
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
        """Парсит info.txt и извлекает нужные поля для отчета"""
        data = {}
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Ищем поля по маркерам
            fields = {
                'Название': r'Название:\s*(.+)',
                'Ссылка': r'Ссылка:\s*(.+)',
                'Код предложения': r'Код предложения:\s*(.+)',
            }
            
            for key, pattern in fields.items():
                match = re.search(pattern, content)
                if match:
                    data[key] = match.group(1).strip()
                else:
                    data[key] = ''
            
            # Если есть разделитель "#изъятая", можно взять текст до него
            if '#изъятая' in content:
                data['ad_text'] = content.split('#изъятая')[0].strip()
            else:
                data['ad_text'] = content.strip()
                
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга {info_path}: {e}")
            data = {'Название': '', 'Ссылка': '', 'Код предложения': '', 'ad_text': ''}
        
        return data

    def generate_report(self, user_id):
        """Генерирует отчет и возвращает путь к файлу"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            samosvaly_path = os.path.join(user_folder, "Самосвалы")
            
            if not os.path.exists(samosvaly_path):
                logger.warning(f"⚠️ Папка Самосвалы не найдена для пользователя {user_id}")
                return None
            
            report_data = []
            moscow_tz = pytz.timezone('Europe/Moscow')
            
            for folder_name in os.listdir(samosvaly_path):
                folder_path = os.path.join(samosvaly_path, folder_name)
                info_path = os.path.join(folder_path, 'info.txt')
                
                if not os.path.exists(info_path):
                    continue
                
                # Парсим данные из info.txt
                info = self.parse_info_file(info_path)
                
                # Получаем время публикации из БД
                pub_time = self.db.get_publication_time(user_id, folder_name)
                if pub_time:
                    # Конвертируем в московское время
                    pub_time = pub_time.astimezone(moscow_tz)
                    time_str = pub_time.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
                
                # Формируем ссылку на пост (заглушка, можно доработать)
                chat_id = self.fm.extract_chat_id(folder_name)
                post_link = f"https://max.ru/post/{chat_id}" if chat_id else ""
                
                report_data.append({
                    'Время по МСК МАХ': time_str,
                    'Ссылка на опубликованное объявление в МАХ': post_link,
                    'Ссылка (откуда информация)': info.get('Ссылка', ''),
                    'Марка/модель': info.get('Название', ''),
                    'Код предложения': info.get('Код предложения', ''),
                    'Папка': folder_name
                })
            
            if not report_data:
                logger.warning(f"⚠️ Нет данных для отчета пользователя {user_id}")
                return None
            
            # Создаем DataFrame
            df = pd.DataFrame(report_data)
            
            # Сохраняем в Excel
            report_filename = f"Отчет_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            report_path = os.path.join(user_folder, report_filename)
            
            with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Лист1', index=False)
                # Настраиваем ширину колонок
                worksheet = writer.sheets['Лист1']
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_length = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_length
            
            logger.info(f"📊 Отчет создан: {report_path}")
            return report_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            return None

    def cleanup_user_data(self, user_id, keep_report=False):
        """Удаляет временные папки и файлы пользователя, кроме отчета"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            if not os.path.exists(user_folder):
                return
            
            # Если нужно сохранить отчеты
            if keep_report:
                # Удаляем всё, кроме файлов отчетов
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        logger.info(f"🗑️ Удалена папка: {item}")
                    elif not item.startswith('Отчет_'):
                        os.remove(item_path)
                        logger.info(f"🗑️ Удален файл: {item}")
            else:
                # Удаляем всё
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки данных пользователя {user_id}: {e}")
