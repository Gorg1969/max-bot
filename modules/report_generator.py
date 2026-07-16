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
    
    def generate_report(self, user_id):
        """Генерирует отчет с двумя листами: Успешно и Ошибки"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            
            all_publications = self.db.get_publications_with_status(user_id)
            
            if not all_publications:
                logger.warning(f"⚠️ Нет публикаций для пользователя {user_id}")
                return None
            
            moscow_tz = pytz.timezone('Europe/Moscow')
            
            success_list = []
            error_list = []
            
            for pub in all_publications:
                folder_name = pub.get('folder_name')
                group_id = pub.get('group_id')
                full_url = pub.get('full_url')
                status = pub.get('status', 'unknown')
                error_text = pub.get('error_text', '')
                created_at = pub.get('created_at')
                
                metadata = self.db.get_ad_metadata(user_id, folder_name)
                
                if created_at:
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at)
                        except:
                            created_at = datetime.now()
                    if created_at.tzinfo is None:
                        created_at = moscow_tz.localize(created_at)
                    time_str = created_at.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
                
                # Формируем полную ссылку
                if full_url:
                    post_link = full_url
                elif group_id:
                    # Если нет full_url, но есть group_id - формируем ссылку на чат
                    post_link = f"https://max.ru/c/{group_id}"
                else:
                    post_link = ""
                
                if status == 'success':
                    success_list.append({
                        '№': len(success_list) + 1,
                        'Папка': folder_name,
                        'Время публикации (МСК)': time_str,
                        'Ссылка на пост': post_link,
                        'Ссылка (источник)': metadata.get('Ссылка', ''),
                        'Марка/модель': metadata.get('Название', ''),
                        'Код предложения': metadata.get('Код предложения', ''),
                        'Цена в лизинге': metadata.get('Цена в лизинге', ''),
                    })
                else:
                    error_list.append({
                        '№': len(error_list) + 1,
                        'Папка': folder_name,
                        'Время ошибки': time_str,
                        'Статус': status,
                        'Текст ошибки': error_text,
                    })
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.xlsx"
            report_path = os.path.join(user_folder, report_filename)
            
            with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
                # Лист 1: Успешные
                if success_list:
                    df_success = pd.DataFrame(success_list)
                    df_success.to_excel(writer, sheet_name='Успешно', index=False)
                else:
                    pd.DataFrame({'Сообщение': ['Нет успешных публикаций']}).to_excel(
                        writer, sheet_name='Успешно', index=False
                    )
                
                # Лист 2: Ошибки
                if error_list:
                    df_errors = pd.DataFrame(error_list)
                    df_errors.to_excel(writer, sheet_name='Ошибки', index=False)
                else:
                    pd.DataFrame({'Сообщение': ['Ошибок нет']}).to_excel(
                        writer, sheet_name='Ошибки', index=False
                    )
                
                # Лист 3: Сводка
                summary = {
                    'Всего публикаций': len(success_list) + len(error_list),
                    'Успешно': len(success_list),
                    'С ошибками': len(error_list),
                    'Процент успеха': f"{(len(success_list) / (len(success_list) + len(error_list)) * 100):.1f}%" if (len(success_list) + len(error_list)) > 0 else "0%",
                    'Время создания': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                pd.DataFrame([summary]).to_excel(writer, sheet_name='Сводка', index=False)
            
            logger.info(f"📊 Отчет создан: {report_path}")
            logger.info(f"   ✅ Успешно: {len(success_list)}")
            logger.info(f"   ❌ Ошибок: {len(error_list)}")
            
            self.cleanup_user_data(user_id, keep_report=True)
            
            return report_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def cleanup_user_data(self, user_id, keep_report=True):
        """Очищает временные данные пользователя"""
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
                    elif not (item.startswith('Отчет_') or item.endswith('.xlsx')):
                        os.remove(item_path)
                        logger.info(f"🗑️ Удален файл: {item}")
            else:
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")
