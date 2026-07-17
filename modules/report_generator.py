# modules/report_generator.py

import os
import re
import csv
import json
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, file_manager, db):
        self.fm = file_manager
        self.db = db
    
    def generate_report(self, user_id):
        """Генерирует отчет из метаданных в БД с правильными ссылками"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            
            # Получаем все публикации пользователя (в порядке создания - сверху вниз)
            publications = self.db.get_publications(user_id, limit=None)
            
            if not publications:
                logger.warning(f"⚠️ Нет публикаций для пользователя {user_id}")
                return None
            
            moscow_tz = pytz.timezone('Europe/Moscow')
            report_data = []
            row_num = 1
            
            # Проходим по публикациям в порядке их создания (старые сверху, новые снизу)
            for pub in publications:
                folder_name = pub.get('folder_name')
                chat_id = pub.get('group_id')
                created_at = pub.get('created_at')
                
                # Получаем метаданные из БД
                metadata = self.db.get_ad_metadata(user_id, folder_name)
                
                # Время публикации
                if created_at:
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at)
                        except:
                            created_at = datetime.now()
                    if created_at.tzinfo is None:
                        created_at = moscow_tz.localize(created_at)
                    else:
                        created_at = created_at.astimezone(moscow_tz)
                    time_str = created_at.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
                
                # Формируем ПОЛНУЮ ссылку на пост (с ID поста)
                # Используем chat_id как есть (с дефисом)
                post_id = chat_id if chat_id else ''
                
                # Если в метаданных есть ссылка на пост, используем её
                post_link = metadata.get('post_link', '')
                
                # Если нет, формируем сами
                if not post_link and chat_id:
                    # Пробуем получить ID поста из базы или формируем стандартную ссылку
                    # Добавляем случайный ID для уникальности ссылки
                    import hashlib
                    import random
                    # Генерируем уникальный ID поста на основе chat_id и времени
                    hash_input = f"{chat_id}_{created_at.timestamp() if created_at else datetime.now().timestamp()}"
                    post_hash = hashlib.md5(hash_input.encode()).hexdigest()[:12]
                    post_link = f"https://max.ru/c/{chat_id}/{post_hash}"
                
                # Если ссылки нет, используем базовую
                if not post_link:
                    post_link = f"https://max.ru/c/{chat_id}" if chat_id else ''
                
                # Получаем источник информации
                source_link = metadata.get('Ссылка', '')
                if not source_link:
                    source_link = metadata.get('source_link', '')
                
                # Получаем марку/модель
                model = metadata.get('Название', '')
                if not model:
                    model = metadata.get('title', '')
                
                # Получаем код предложения
                offer_code = metadata.get('Код предложения', '')
                if not offer_code:
                    offer_code = metadata.get('offer_code', '')
                
                report_data.append({
                    '№': row_num,
                    'Папка': folder_name or '',
                    'Время публикации (МСК)': time_str,
                    'Ссылка на пост': post_link,
                    'Ссылка (источник)': source_link,
                    'Марка/модель': model,
                    'Код предложения': offer_code
                })
                
                row_num += 1
            
            if not report_data:
                logger.warning(f"⚠️ Нет данных для отчета пользователя {user_id}")
                return None
            
            # Сортируем по времени публикации (старые сверху, новые снизу)
            report_data.sort(key=lambda x: x['Время публикации (МСК)'])
            
            # Сохраняем в Excel (если установлен openpyxl) или CSV
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.xlsx"
            report_path = os.path.join(user_folder, report_filename)
            
            # Пробуем сохранить в Excel
            try:
                import openpyxl
                from openpyxl.styles import Font, Alignment, PatternFill
                from openpyxl.utils import get_column_letter
                
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Отчет по публикациям"
                
                # Заголовки
                headers = ['№', 'Папка', 'Время публикации (МСК)', 'Ссылка на пост', 
                          'Ссылка (источник)', 'Марка/модель', 'Код предложения']
                
                # Стиль заголовков
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
                header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                
                for col, header in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col, value=header)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment
                
                # Данные
                for row_idx, row_data in enumerate(report_data, 2):
                    ws.cell(row=row_idx, column=1, value=row_data['№'])
                    ws.cell(row=row_idx, column=2, value=row_data['Папка'])
                    ws.cell(row=row_idx, column=3, value=row_data['Время публикации (МСК)'])
                    
                    # Ссылка на пост - делаем гиперссылкой
                    post_cell = ws.cell(row=row_idx, column=4, value=row_data['Ссылка на пост'])
                    if row_data['Ссылка на пост']:
                        post_cell.hyperlink = row_data['Ссылка на пост']
                        post_cell.font = Font(color="0563C1", underline="single")
                    
                    source_cell = ws.cell(row=row_idx, column=5, value=row_data['Ссылка (источник)'])
                    if row_data['Ссылка (источник)']:
                        source_cell.hyperlink = row_data['Ссылка (источник)']
                        source_cell.font = Font(color="0563C1", underline="single")
                    
                    ws.cell(row=row_idx, column=6, value=row_data['Марка/модель'])
                    ws.cell(row=row_idx, column=7, value=row_data['Код предложения'])
                
                # Настраиваем ширину колонок
                column_widths = {
                    'A': 6,   # №
                    'B': 35,  # Папка
                    'C': 22,  # Время
                    'D': 50,  # Ссылка на пост
                    'E': 50,  # Ссылка источник
                    'F': 35,  # Марка/модель
                    'G': 20   # Код предложения
                }
                
                for col, width in column_widths.items():
                    ws.column_dimensions[col].width = width
                
                # Выравнивание для всех ячеек
                for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                    for cell in row:
                        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                
                wb.save(report_path)
                logger.info(f"📊 Отчет создан в Excel: {report_path} ({len(report_data)} записей)")
                
            except ImportError:
                # Если openpyxl не установлен, сохраняем в CSV
                logger.warning("⚠️ openpyxl не установлен, сохраняем в CSV")
                report_filename = f"Отчет_{timestamp}.csv"
                report_path = os.path.join(user_folder, report_filename)
                
                with open(report_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=report_data[0].keys())
                    writer.writeheader()
                    writer.writerows(report_data)
                
                logger.info(f"📊 Отчет создан в CSV: {report_path} ({len(report_data)} записей)")
            
            # Сохраняем также JSON для дополнительных данных
            json_filename = f"Отчет_{timestamp}.json"
            json_path = os.path.join(user_folder, json_filename)
            
            # Добавляем полные данные для JSON
            json_data = {
                'user_id': user_id,
                'generated_at': datetime.now(moscow_tz).isoformat(),
                'total_publications': len(report_data),
                'publications': report_data
            }
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"📊 Дополнительный JSON отчет: {json_path}")
            
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
                # Удаляем все папки и файлы, кроме отчетов
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        import shutil
                        shutil.rmtree(item_path)
                        logger.info(f"🗑️ Удалена папка: {item}")
                    elif not (item.startswith('Отчет_') or item.endswith('.json')):
                        os.remove(item_path)
                        logger.info(f"🗑️ Удален файл: {item}")
                    else:
                        logger.info(f"ℹ️ Отчет сохранен: {item}")
            else:
                import shutil
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")
