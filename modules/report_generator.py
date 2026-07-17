# modules/report_generator.py
import os
import re
import csv
import shutil
from datetime import datetime
import pytz
import logging
import sqlite3

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, file_manager, db):
        self.fm = file_manager
        self.db = db
    
    def generate_report(self, user_id):
        """Генерирует отчет с двумя листами: успешные и ошибки"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            moscow_tz = pytz.timezone('Europe/Moscow')
            
            # Получаем все публикации пользователя
            publications = self.db.get_publications(user_id)
            
            if not publications:
                logger.warning(f"⚠️ Нет публикаций для пользователя {user_id}")
                return None
            
            # Разделяем на успешные и ошибки
            success_publications = []
            error_publications = []
            
            for pub in publications:
                if pub.get('status') == 'success':
                    success_publications.append(pub)
                else:
                    error_publications.append(pub)
            
            # Если нет успешных публикаций, но есть ошибки - создаем отчет только с ошибками
            if not success_publications and not error_publications:
                logger.warning(f"⚠️ Нет данных для отчета пользователя {user_id}")
                return None
            
            timestamp = datetime.now(moscow_tz).strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.csv"
            report_path = os.path.join(user_folder, report_filename)
            
            # Создаем два файла: основной и ошибки
            success_path = report_path
            error_path = os.path.join(user_folder, f"Ошибки_{timestamp}.csv")
            
            # Записываем успешные публикации
            if success_publications:
                self._write_success_report(success_publications, success_path, user_id, moscow_tz)
                logger.info(f"📊 Отчет создан: {success_path} ({len(success_publications)} записей)")
            
            # Записываем ошибки
            if error_publications:
                self._write_error_report(error_publications, error_path, user_id, moscow_tz)
                logger.info(f"📊 Отчет с ошибками создан: {error_path} ({len(error_publications)} записей)")
            
            # Очищаем данные пользователя из БД после создания отчета
            self.db.clear_user_data(user_id)
            logger.info(f"🗑️ Данные пользователя {user_id} удалены из БД")
            
            # Очищаем временные файлы
            self.cleanup_user_data(user_id, keep_report=True)
            
            # Возвращаем путь к основному отчету
            return success_path if success_publications else error_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _write_success_report(self, publications, filepath, user_id, tz):
        """Записывает успешные публикации в формате шаблона"""
        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            
            # Заголовки как в шаблоне
            writer.writerow(['№', 'Дата', 'Время публикации (МСК)', 'Ссылка на пост', 'Ссылка (источник)', 'Марка/модель', 'Код предложения'])
            
            row_num = 1
            
            # Группируем по дате
            date_groups = {}
            for pub in publications:
                folder_name = pub.get('folder_name')
                chat_id = pub.get('group_id')
                created_at = pub.get('created_at')
                
                # Получаем метаданные из БД
                metadata = self.db.get_ad_metadata(user_id, folder_name)
                
                # Полная ссылка на пост
                post_link = metadata.get('post_link', '')
                if not post_link and chat_id:
                    clean_chat_id = chat_id.replace('-', '') if chat_id.startswith('-') else chat_id
                    post_link = f"https://max.ru/c/-{clean_chat_id}"
                
                # Время публикации (МСК, без секунд)
                if created_at:
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at)
                        except:
                            created_at = datetime.now(tz)
                    if hasattr(created_at, 'astimezone'):
                        created_at = created_at.astimezone(tz)
                    date_str = created_at.strftime('%Y-%m-%d')
                    time_str = created_at.strftime('%H:%M')
                else:
                    now = datetime.now(tz)
                    date_str = now.strftime('%Y-%m-%d')
                    time_str = now.strftime('%H:%M')
                
                if date_str not in date_groups:
                    date_groups[date_str] = []
                
                date_groups[date_str].append({
                    'time': time_str,
                    'post_link': post_link,
                    'source_link': metadata.get('Ссылка', ''),
                    'model': metadata.get('Название', ''),
                    'offer_code': metadata.get('Код предложения', ''),
                })
            
            # Сортируем по дате (сначала новые)
            for date_str in sorted(date_groups.keys(), reverse=True):
                entries = date_groups[date_str]
                
                # Первая запись с датой
                first = True
                for entry in entries:
                    if first:
                        writer.writerow([
                            row_num,
                            date_str,
                            entry['time'],
                            entry['post_link'],
                            entry['source_link'],
                            entry['model'],
                            entry['offer_code']
                        ])
                        first = False
                    else:
                        writer.writerow([
                            row_num,
                            '',  # Дата пустая для последующих записей того же дня
                            entry['time'],
                            entry['post_link'],
                            entry['source_link'],
                            entry['model'],
                            entry['offer_code']
                        ])
                    row_num += 1
    
    def _write_error_report(self, publications, filepath, user_id, tz):
        """Записывает ошибки публикации"""
        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            
            # Заголовки для ошибок (без ссылок)
            writer.writerow(['№', 'Дата', 'Время', 'Папка', 'Статус', 'Ошибка'])
            
            row_num = 1
            for pub in publications:
                folder_name = pub.get('folder_name')
                created_at = pub.get('created_at')
                error = pub.get('error', 'Неизвестная ошибка')
                status = pub.get('status', 'error')
                
                # Время
                if created_at:
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at)
                        except:
                            created_at = datetime.now(tz)
                    if hasattr(created_at, 'astimezone'):
                        created_at = created_at.astimezone(tz)
                    date_str = created_at.strftime('%Y-%m-%d')
                    time_str = created_at.strftime('%H:%M')
                else:
                    now = datetime.now(tz)
                    date_str = now.strftime('%Y-%m-%d')
                    time_str = now.strftime('%H:%M')
                
                writer.writerow([
                    row_num,
                    date_str,
                    time_str,
                    folder_name,
                    status,
                    error
                ])
                row_num += 1
    
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
                    elif not (item.startswith('Отчет_') or item.startswith('Ошибки_')):
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
