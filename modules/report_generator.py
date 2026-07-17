# modules/report_generator.py

import os
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
        """Генерирует отчет для пользователя"""
        try:
            user_folder = self.fm.get_user_folder(user_id)
            publications = self.db.get_publications(user_id)
            
            if not publications:
                logger.warning(f"⚠️ Нет публикаций для {user_id}")
                return None
            
            moscow_tz = pytz.timezone('Europe/Moscow')
            report_data = []
            
            for pub in publications:
                folder_name = pub.get('folder_name')
                chat_id = pub.get('group_id')
                created_at = pub.get('created_at')
                
                metadata = self.db.get_ad_metadata(user_id, folder_name)
                
                if created_at:
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at)
                    if created_at.tzinfo is None:
                        created_at = moscow_tz.localize(created_at)
                    else:
                        created_at = created_at.astimezone(moscow_tz)
                    time_str = created_at.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
                
                post_link = metadata.get('post_link', '')
                if not post_link and chat_id:
                    post_link = f"https://max.ru/c/{chat_id}"
                
                report_data.append({
                    '№': len(report_data) + 1,
                    'Папка': folder_name,
                    'Время публикации (МСК)': time_str,
                    'Ссылка на пост': post_link,
                    'Ссылка (источник)': metadata.get('Ссылка', ''),
                    'Марка/модель': metadata.get('Название', ''),
                    'Код предложения': metadata.get('Код предложения', '')
                })
            
            if not report_data:
                return None
            
            # Сохраняем в Excel
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.xlsx"
            report_path = os.path.join(user_folder, report_filename)
            
            try:
                import openpyxl
                from openpyxl.styles import Font, Alignment, PatternFill
                
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Отчет по публикациям"
                
                headers = ['№', 'Папка', 'Время публикации (МСК)', 
                          'Ссылка на пост', 'Ссылка (источник)', 
                          'Марка/модель', 'Код предложения']
                
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
                
                for col, header in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col, value=header)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")
                
                for row_idx, row_data in enumerate(report_data, 2):
                    ws.cell(row=row_idx, column=1, value=row_data['№'])
                    ws.cell(row=row_idx, column=2, value=row_data['Папка'])
                    ws.cell(row=row_idx, column=3, value=row_data['Время публикации (МСК)'])
                    
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
                
                column_widths = {'A': 6, 'B': 35, 'C': 22, 'D': 50, 'E': 50, 'F': 35, 'G': 20}
                for col, width in column_widths.items():
                    ws.column_dimensions[col].width = width
                
                wb.save(report_path)
                logger.info(f"📊 Отчет создан: {report_path}")
                
            except ImportError:
                report_filename = f"Отчет_{timestamp}.csv"
                report_path = os.path.join(user_folder, report_filename)
                with open(report_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=report_data[0].keys())
                    writer.writeheader()
                    writer.writerows(report_data)
                logger.info(f"📊 Отчет создан в CSV: {report_path}")
            
            return report_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            return None
