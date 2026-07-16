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
    
    def generate_report(self, user_id):
        """Генерирует отчет из метаданных в БД"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            
            # Получаем все публикации пользователя
            publications = self.db.get_publications(user_id)
            
            if not publications:
                logger.warning(f"⚠️ Нет публикаций для пользователя {user_id}")
                return None
            
            moscow_tz = pytz.timezone('Europe/Moscow')
            report_data = []
            
            for pub in publications:
                folder_name = pub.get('folder_name')
                chat_id = pub.get('group_id')
                created_at = pub.get('created_at')
                
                # Получаем метаданные из БД
                metadata = self.db.get_ad_metadata(user_id, folder_name)
                
                # Время публикации
                if created_at:
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at)
                    created_at = created_at.astimezone(moscow_tz)
                    time_str = created_at.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
                
                # Ссылка на пост
                post_link = f"https://max.ru/post/{chat_id}" if chat_id else ""
                
                report_data.append({
                    '№': len(report_data) + 1,
                    'Папка': folder_name,
                    'Время публикации (МСК)': time_str,
                    'Ссылка на пост': post_link,
                    'Ссылка (источник)': metadata.get('Ссылка', ''),
                    'Марка/модель': metadata.get('Название', ''),
                    'Код предложения': metadata.get('Код предложения', ''),
                    'Цена в лизинге': metadata.get('Цена в лизинге', ''),
                })
            
            if not report_data:
                return None
            
            # Сохраняем в CSV
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.csv"
            report_path = os.path.join(user_folder, report_filename)
            
            with open(report_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=report_data[0].keys())
                writer.writeheader()
                writer.writerows(report_data)
            
            logger.info(f"📊 Отчет создан: {report_path} ({len(report_data)} записей)")
            
            # Очищаем временные данные (но оставляем отчет)
            self.cleanup_user_data(user_id, keep_report=True)
            
            return report_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def cleanup_user_data(self, user_id, keep_report=True):
        """Удаляет временные данные пользователя"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            if not os.path.exists(user_folder):
                return
            
            if keep_report:
                # Удаляем все папки, кроме файлов отчетов
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
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")
