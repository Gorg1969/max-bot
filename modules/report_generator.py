import os
import re
import csv
import shutil
from datetime import datetime
import pytz
import logging
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, file_manager, db):
        self.fm = file_manager
        self.db = db
    
    def generate_report(self, user_id):
        """Генерирует Excel-отчет с форматированием"""
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
            
            # Создаем Excel файл
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.xlsx"
            report_path = os.path.join(user_folder, report_filename)
            
            # Создаем Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Отчет по публикациям"
            
            # ====== ЗАГОЛОВКИ ======
            headers = [
                '№', 
                'Папка', 
                'Время публикации (МСК)', 
                'Ссылка на пост', 
                'Ссылка (источник)', 
                'Марка/модель', 
                'Код предложения', 
                'Цена в лизинге'
            ]
            
            # Записываем заголовки
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True, size=11, color="FFFFFF")
                cell.fill = PatternFill(start_color="1E88E5", end_color="1E88E5", fill_type="solid")
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            
            # ====== ДАННЫЕ ======
            for row_idx, data in enumerate(report_data, 2):
                ws.cell(row=row_idx, column=1, value=data['№'])
                ws.cell(row=row_idx, column=2, value=data['Папка'])
                ws.cell(row=row_idx, column=3, value=data['Время публикации (МСК)'])
                
                # Ссылка на пост - делаем гиперссылкой
                post_cell = ws.cell(row=row_idx, column=4, value=data['Ссылка на пост'])
                if data['Ссылка на пост']:
                    post_cell.hyperlink = data['Ссылка на пост']
                    post_cell.font = Font(color="0563C1", underline="single")
                
                # Ссылка источник - гиперссылка
                source_cell = ws.cell(row=row_idx, column=5, value=data['Ссылка (источник)'])
                if data['Ссылка (источник)']:
                    source_cell.hyperlink = data['Ссылка (источник)']
                    source_cell.font = Font(color="0563C1", underline="single")
                
                ws.cell(row=row_idx, column=6, value=data['Марка/модель'])
                ws.cell(row=row_idx, column=7, value=data['Код предложения'])
                ws.cell(row=row_idx, column=8, value=data['Цена в лизинге'])
            
            # ====== ФОРМАТИРОВАНИЕ ======
            # Ширина колонок
            column_widths = {
                'A': 5,   # №
                'B': 30,  # Папка
                'C': 22,  # Время
                'D': 40,  # Ссылка на пост
                'E': 40,  # Ссылка источник
                'F': 25,  # Марка/модель
                'G': 18,  # Код предложения
                'H': 18,  # Цена
            }
            
            for col, width in column_widths.items():
                ws.column_dimensions[col].width = width
            
            # Выравнивание для всех ячеек
            for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=len(headers)):
                for cell in row:
                    if cell.row == 1:
                        continue
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            
            # ====== ГРАНИЦЫ ======
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=len(headers)):
                for cell in row:
                    cell.border = thin_border
            
            # ====== СОХРАНЯЕМ ======
            wb.save(report_path)
            
            logger.info(f"📊 Excel-отчет создан: {report_path} ({len(report_data)} записей)")
            
            # Очищаем временные данные
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
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        logger.info(f"🗑️ Удалена папка: {item}")
                    elif not item.startswith('Отчет_') and not item.endswith('.xlsx'):
                        os.remove(item_path)
                        logger.info(f"🗑️ Удален файл: {item}")
                    else:
                        logger.info(f"ℹ️ Отчет сохранен: {item}")
            else:
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")с
